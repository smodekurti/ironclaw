"""
ironclaw.security.audit
~~~~~~~~~~~~~~~~~~~~~~~~
Append-only structured audit log.

Every significant event — LLM calls, tool executions, handoffs, security
decisions — is written as a JSON line to the audit log file AND emitted via
the standard logging framework.  The log is designed for forensic replay:
given the log file you can reconstruct exactly what happened in every session.

Security properties
-------------------
- **Append-only**: the file is opened with ``O_APPEND``; no seek/overwrite.
- **Structured**: each entry is a single-line JSON object with a timestamp,
  event type, session/agent ID, and arbitrary key-value payload.
- **Tamper-evident (optional)**: if ``hmac_secret`` is provided, each entry
  gets a SHA-256 HMAC so you can detect post-hoc modifications.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
import queue

logger = logging.getLogger(__name__)

_SENTINEL = object()


class AuditLog:
    """
    Thread-safe, append-only structured audit log.

    Parameters
    ----------
    path : str | Path | None
        File path.  ``None`` → log to stderr / Python logging only.
    hmac_secret : str | None
        If set, each entry is signed with HMAC-SHA256.
    level : int
        Python logging level for mirrored log lines (default: INFO).
    """

    def __init__(
        self,
        path: str | Path | None = None,
        hmac_secret: str | None = None,
        level: int = logging.INFO,
    ) -> None:
        self._path = Path(path) if path else None
        self._secret = hmac_secret.encode() if hmac_secret else None
        self._level = level
        self._lock = threading.Lock()
        self._fh = None
        self._queue = queue.Queue()
        self._stop_event = threading.Event()
        self._worker: threading.Thread | None = None

        if self._path:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            # O_WRONLY | O_CREAT | O_APPEND — never seek, never truncate
            fd = os.open(self._path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            self._fh = os.fdopen(fd, "a", encoding="utf-8")
            self._worker = threading.Thread(target=self._write_loop, daemon=True)
            self._worker.start()
            import atexit
            atexit.register(self.close)

    def _write_loop(self) -> None:
        while not self._stop_event.is_set() or not self._queue.empty():
            try:
                line = self._queue.get(timeout=0.5)
                if line is None:
                    break
                if self._fh:
                    with self._lock:
                        self._fh.write(line + "\n")
                        self._fh.flush()
                self._queue.task_done()
            except queue.Empty:
                continue

    # ------------------------------------------------------------------
    # Core write
    # ------------------------------------------------------------------

    def record(self, event: str, **kwargs: Any) -> None:
        """
        Write a single audit event.

        Parameters
        ----------
        event : str
            Short snake_case event name, e.g. ``"tool_call_start"``.
        **kwargs
            Arbitrary key/value payload included in the log entry.
        """
        entry: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event,
            **kwargs,
        }

        if self._secret:
            payload = json.dumps(entry, separators=(",", ":"), sort_keys=True)
            sig = hmac.new(self._secret, payload.encode(), hashlib.sha256).hexdigest()
            entry["_sig"] = sig

        line = json.dumps(entry, separators=(",", ":"), default=str)

        if self._worker:
            self._queue.put(line)
        else:
            with self._lock:
                if self._fh:
                    self._fh.write(line + "\n")
                    self._fh.flush()

        logger.log(self._level, "[AUDIT] %s", line)

    # ------------------------------------------------------------------
    # Query helpers (for testing / dashboards)
    # ------------------------------------------------------------------

    def tail(self, n: int = 50) -> list[dict[str, Any]]:
        """Return the last *n* entries from the log file."""
        if not self._path or not self._path.exists():
            return []
        lines = self._path.read_text(encoding="utf-8").splitlines()
        entries = []
        for line in lines[-n:]:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        return entries

    def search(self, event: str | None = None, **filters: Any) -> list[dict[str, Any]]:
        """
        Simple scan of the log file with optional filters.

        Parameters
        ----------
        event : str | None
            Only return entries with this event type.
        **filters
            Additional key=value filters applied to each entry.
        """
        if not self._path or not self._path.exists():
            return []
        results = []
        with open(self._path, encoding="utf-8") as f:
            for line in f:
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event and entry.get("event") != event:
                    continue
                if all(entry.get(k) == v for k, v in filters.items()):
                    results.append(entry)
        return results

    def verify_signatures(self) -> Iterator[str]:
        """
        Validate HMAC signatures as a generator yielding tampered lines.
        Only meaningful when ``hmac_secret`` was provided at construction.
        """
        if not self._secret or not self._path or not self._path.exists():
            return
        with open(self._path, encoding="utf-8") as f:
            for lineno, line in enumerate(f, start=1):
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    yield f"line {lineno}: invalid JSON"
                    continue
                sig = entry.pop("_sig", None)
                if sig is None:
                    yield f"line {lineno}: missing signature"
                    continue
                payload = json.dumps(entry, separators=(",", ":"), sort_keys=True)
                expected = hmac.new(self._secret, payload.encode(), hashlib.sha256).hexdigest()
                if not hmac.compare_digest(sig, expected):
                    yield f"line {lineno}: signature mismatch"

    def close(self) -> None:
        if self._worker:
            self._stop_event.set()
            self._queue.put(None)
            self._worker.join(timeout=2.0)
        if self._fh:
            with self._lock:
                self._fh.close()
                self._fh = None

    def __enter__(self) -> "AuditLog":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()
