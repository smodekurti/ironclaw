"""
ironclaw.memory.shared
~~~~~~~~~~~~~~~~~~~~~~
Cross-agent shared state store.

Agents in the same Orchestrator session share a single SharedStateStore,
allowing them to collaborate via a common key-value namespace.

Access is thread-safe.  Keys are namespaced by default:
  ``set("x", v)``              → global key ``"x"``
  ``set("x", v, ns="agent1")`` → namespaced key ``"agent1:x"``
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from ironclaw.memory.base import KeyValueBackend


class SharedStateStore(KeyValueBackend):
    """
    In-memory (or SQLite-backed) shared state store.

    Parameters
    ----------
    db_path : str | Path | None
        If provided, state is persisted to a SQLite file so it survives
        restarts.  ``None`` → in-memory only.
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._lock = threading.RLock()
        self._db_path = Path(db_path) if db_path else None
        self._memory: dict[str, Any] = {}
        self._conn: sqlite3.Connection | None = None

        if self._db_path:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT)"
            )
            self._conn.commit()
            # Load persisted state into memory cache
            for key, val in self._conn.execute("SELECT key, value FROM state"):
                try:
                    self._memory[key] = json.loads(val)
                except json.JSONDecodeError:
                    self._memory[key] = val

    # ------------------------------------------------------------------
    # KeyValueBackend interface
    # ------------------------------------------------------------------

    def get(self, key: str, default: Any = None, ns: str = "") -> Any:
        full_key = f"{ns}:{key}" if ns else key
        with self._lock:
            return self._memory.get(full_key, default)

    def set(self, key: str, value: Any, ns: str = "") -> None:
        full_key = f"{ns}:{key}" if ns else key
        with self._lock:
            self._memory[full_key] = value
            if self._conn:
                self._conn.execute(
                    "INSERT OR REPLACE INTO state (key, value) VALUES (?, ?)",
                    (full_key, json.dumps(value, default=str)),
                )
                self._conn.commit()

    def delete(self, key: str, ns: str = "") -> None:
        full_key = f"{ns}:{key}" if ns else key
        with self._lock:
            self._memory.pop(full_key, None)
            if self._conn:
                self._conn.execute("DELETE FROM state WHERE key=?", (full_key,))
                self._conn.commit()

    def keys(self, ns: str = "") -> list[str]:
        with self._lock:
            if ns:
                prefix = f"{ns}:"
                return [k for k in self._memory if k.startswith(prefix)]
            return list(self._memory.keys())

    def clear(self) -> None:
        with self._lock:
            self._memory.clear()
            if self._conn:
                self._conn.execute("DELETE FROM state")
                self._conn.commit()

    # ------------------------------------------------------------------
    # Extra helpers
    # ------------------------------------------------------------------

    def increment(self, key: str, delta: int = 1, ns: str = "") -> int:
        """Atomically increment an integer counter."""
        with self._lock:
            current = int(self.get(key, 0, ns=ns))
            new_val = current + delta
            self.set(key, new_val, ns=ns)
            return new_val

    def snapshot(self) -> dict[str, Any]:
        """Return a copy of the entire store."""
        with self._lock:
            return dict(self._memory)

    def close(self) -> None:
        if self._conn:
            self._conn.close()
