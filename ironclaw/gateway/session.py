"""
ironclaw.gateway.session
~~~~~~~~~~~~~~~~~~~~~~~~
Per-sender session management.

Each unique (platform, sender_id) pair gets its own ``GatewaySession`` that
tracks which IronClaw agent is handling it, conversation context, and rate
limits.  Sessions persist in memory and optionally in SQLite.

Design goals
------------
- New senders are auto-provisioned (session created on first message).
- The "current agent" for a session is set by the router; users can switch
  agents mid-conversation by prefixing their message with ``/agent <id>``.
- Sessions carry their own ConversationMemory so each sender has an isolated
  history — two users talking to the same agent see different contexts.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ironclaw.gateway.base import PlatformID
from ironclaw.memory.conversation import InMemoryConversation

logger = logging.getLogger(__name__)


@dataclass
class GatewaySession:
    """State for one sender across all interactions."""
    platform_id: PlatformID
    agent_id: str                    # currently assigned IronClaw agent
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_active: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    message_count: int = 0
    memory: InMemoryConversation = field(default_factory=InMemoryConversation)
    metadata: dict[str, Any] = field(default_factory=dict)

    def touch(self) -> None:
        self.last_active = datetime.now(timezone.utc)
        self.message_count += 1


class SessionStore:
    """
    Thread-safe session store.

    Parameters
    ----------
    default_agent_id : str
        Agent assigned to new sessions before the router makes a decision.
    db_path : str | Path | None
        SQLite path for persistent metadata (conversation history stays
        in-memory for speed).  ``None`` → fully in-memory.
    """

    def __init__(
        self,
        default_agent_id: str = "",
        db_path: str | Path | None = None,
    ) -> None:
        self._default_agent = default_agent_id
        self._sessions: dict[PlatformID, GatewaySession] = {}
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None

        if db_path:
            path = Path(db_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(path), check_same_thread=False)
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    platform TEXT NOT NULL,
                    sender_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    message_count INTEGER DEFAULT 0,
                    metadata TEXT DEFAULT '{}',
                    created_at TEXT,
                    last_active TEXT,
                    PRIMARY KEY (platform, sender_id)
                )
            """)
            self._conn.commit()
            self._load_from_db()

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def get_or_create(self, platform_id: PlatformID) -> GatewaySession:
        """Return the session for *platform_id*, creating one if needed."""
        with self._lock:
            if platform_id not in self._sessions:
                session = GatewaySession(
                    platform_id=platform_id,
                    agent_id=self._default_agent,
                )
                self._sessions[platform_id] = session
                self._persist(session)
                logger.info("New session: %s → agent=%s", platform_id, self._default_agent)
            return self._sessions[platform_id]

    def get(self, platform_id: PlatformID) -> GatewaySession | None:
        with self._lock:
            return self._sessions.get(platform_id)

    def update_agent(self, platform_id: PlatformID, agent_id: str) -> None:
        """Reassign the agent handling this session."""
        with self._lock:
            session = self.get_or_create(platform_id)
            session.agent_id = agent_id
            self._persist(session)
            logger.info("Session %s reassigned to agent=%s", platform_id, agent_id)

    def all_sessions(self) -> list[GatewaySession]:
        with self._lock:
            return list(self._sessions.values())

    def active_count(self) -> int:
        with self._lock:
            return len(self._sessions)

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _persist(self, session: GatewaySession) -> None:
        if not self._conn:
            return
        self._conn.execute(
            """
            INSERT OR REPLACE INTO sessions
            (platform, sender_id, agent_id, message_count, metadata, created_at, last_active)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session.platform_id.platform.value,
                session.platform_id.sender_id,
                session.agent_id,
                session.message_count,
                json.dumps(session.metadata),
                session.created_at.isoformat(),
                session.last_active.isoformat(),
            ),
        )
        self._conn.commit()

    def _load_from_db(self) -> None:
        if not self._conn:
            return
        from ironclaw.gateway.base import Platform
        rows = self._conn.execute(
            "SELECT platform, sender_id, agent_id, message_count, metadata FROM sessions"
        ).fetchall()
        for platform_str, sender_id, agent_id, msg_count, meta_str in rows:
            try:
                pid = PlatformID(Platform(platform_str), sender_id)
            except ValueError:
                pid = PlatformID(Platform.UNKNOWN, sender_id)
            session = GatewaySession(
                platform_id=pid,
                agent_id=agent_id,
                message_count=msg_count,
                metadata=json.loads(meta_str or "{}"),
            )
            self._sessions[pid] = session
        logger.debug("Loaded %d sessions from DB", len(self._sessions))
