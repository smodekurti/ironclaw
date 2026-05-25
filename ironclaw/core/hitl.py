"""
ironclaw.core.hitl
~~~~~~~~~~~~~~~~~~
Human-in-the-Loop (HITL) intercept store — SQLite-backed for multi-worker deployments.

Design
------
The original implementation stored pending intercepts in a module-level dict
``HITL_PENDING: dict[str, (asyncio.Event, str|None)]``.  That works in a single
process but breaks across multiple uvicorn workers: Worker A blocks on the
``asyncio.Event`` while the HTTP resolve request arrives on Worker B, which has
its own in-memory dict and cannot signal Worker A.

This module replaces the in-memory dict with a SQLite table.  The agent polls
the database (asyncio-friendly, non-blocking via ``asyncio.sleep``) instead of
waiting on an Event.  Any worker can write a resolution decision and any worker
running the blocked agent loop will see it on the next poll.

Usage
-----
::

    from ironclaw.core.hitl import HITLStore, configure_hitl

    # In server startup:
    store = HITLStore(db_path="/path/to/hitl.db")
    configure_hitl(store)

    # In agent execution (automatic — see agent.py):
    # store.add(call_id, tool_name, arguments)
    # await store.wait_for_decision(call_id, poll_interval=0.5, timeout=300)
    # store.remove(call_id)

    # Via API endpoint:
    # store.resolve(call_id, "approved" | "rejected")
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import time
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level singleton — configured once at server startup
# ---------------------------------------------------------------------------

_store: "HITLStore | None" = None


def configure_hitl(store: "HITLStore") -> None:
    """Wire the global HITLStore used by agent.py."""
    global _store
    _store = store


def get_hitl_store() -> "HITLStore | None":
    return _store


# ---------------------------------------------------------------------------
# HITLStore
# ---------------------------------------------------------------------------

class HITLStore:
    """
    Durable, multi-worker-safe store for Human-in-the-Loop intercepts.

    All public methods are synchronous (SQLite is fast enough for the tiny
    intercept table).  The async ``wait_for_decision()`` method wraps the
    polling loop in ``asyncio.sleep`` so it yields control to the event loop.

    Parameters
    ----------
    db_path:
        Path to the SQLite database file.  Defaults to ``":memory:"`` (useful
        for tests; not suitable for multi-worker deployments).
    poll_interval:
        Seconds between database polls while waiting for a decision.
    default_timeout:
        Maximum seconds to wait before auto-rejecting the intercept.
    """

    def __init__(
        self,
        db_path: str = ":memory:",
        poll_interval: float = 0.5,
        default_timeout: float = 300.0,
    ) -> None:
        self.db_path = db_path
        self.poll_interval = poll_interval
        self.default_timeout = default_timeout

        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")   # allow concurrent reads
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._init_schema()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _init_schema(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS hitl_intercepts (
                call_id     TEXT PRIMARY KEY,
                tool_name   TEXT NOT NULL,
                agent_id    TEXT NOT NULL DEFAULT '',
                arguments   TEXT NOT NULL DEFAULT '{}',
                status      TEXT NOT NULL DEFAULT 'pending',
                created_at  REAL NOT NULL,
                resolved_at REAL
            )
        """)
        self._conn.commit()

    # ------------------------------------------------------------------
    # Write API
    # ------------------------------------------------------------------

    def add(
        self,
        call_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        agent_id: str = "",
    ) -> None:
        """Register a new pending intercept."""
        self._conn.execute(
            """
            INSERT OR REPLACE INTO hitl_intercepts
                (call_id, tool_name, agent_id, arguments, status, created_at)
            VALUES (?, ?, ?, ?, 'pending', ?)
            """,
            (call_id, tool_name, agent_id, json.dumps(arguments), time.time()),
        )
        self._conn.commit()
        logger.info("HITL intercept registered: call_id=%s tool=%s", call_id, tool_name)

    def resolve(self, call_id: str, decision: str) -> bool:
        """
        Record a human decision for a pending intercept.

        Parameters
        ----------
        call_id:
            The intercept to resolve.
        decision:
            ``"approved"`` or ``"rejected"``.

        Returns
        -------
        bool
            ``True`` if the intercept existed and was updated, ``False`` if not found.
        """
        cur = self._conn.execute(
            """
            UPDATE hitl_intercepts
            SET status = ?, resolved_at = ?
            WHERE call_id = ? AND status = 'pending'
            """,
            (decision, time.time(), call_id),
        )
        self._conn.commit()
        updated = cur.rowcount > 0
        if updated:
            logger.info("HITL intercept resolved: call_id=%s decision=%s", call_id, decision)
        return updated

    def remove(self, call_id: str) -> None:
        """Delete an intercept record after the agent has consumed the decision."""
        self._conn.execute(
            "DELETE FROM hitl_intercepts WHERE call_id = ?", (call_id,)
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Read API
    # ------------------------------------------------------------------

    def get_status(self, call_id: str) -> str | None:
        """Return the current status string, or ``None`` if not found."""
        row = self._conn.execute(
            "SELECT status FROM hitl_intercepts WHERE call_id = ?", (call_id,)
        ).fetchone()
        return row["status"] if row else None

    def list_pending(self) -> list[dict[str, Any]]:
        """Return all pending intercepts as a list of dicts."""
        rows = self._conn.execute(
            """
            SELECT call_id, tool_name, agent_id, arguments, created_at
            FROM hitl_intercepts
            WHERE status = 'pending'
            ORDER BY created_at
            """
        ).fetchall()
        result = []
        for row in rows:
            result.append({
                "call_id":    row["call_id"],
                "tool_name":  row["tool_name"],
                "agent_id":   row["agent_id"],
                "arguments":  json.loads(row["arguments"]),
                "created_at": row["created_at"],
            })
        return result

    def list_all(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return the most recent intercepts regardless of status."""
        rows = self._conn.execute(
            """
            SELECT call_id, tool_name, agent_id, arguments, status, created_at, resolved_at
            FROM hitl_intercepts
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Async wait
    # ------------------------------------------------------------------

    async def wait_for_decision(
        self,
        call_id: str,
        poll_interval: float | None = None,
        timeout: float | None = None,
    ) -> str:
        """
        Async-poll the database until a human decision is recorded.

        Returns
        -------
        str
            The decision: ``"approved"`` or ``"rejected"``.

        Raises
        ------
        TimeoutError
            If no decision arrives within *timeout* seconds.
        """
        interval = poll_interval or self.poll_interval
        deadline = time.monotonic() + (timeout or self.default_timeout)

        while True:
            status = self.get_status(call_id)
            if status is not None and status != "pending":
                return status

            if time.monotonic() >= deadline:
                # Auto-reject on timeout to unblock the agent loop.
                self.resolve(call_id, "rejected")
                logger.warning(
                    "HITL intercept timed out after %.0fs, auto-rejecting: call_id=%s",
                    timeout or self.default_timeout,
                    call_id,
                )
                return "rejected"

            await asyncio.sleep(interval)
