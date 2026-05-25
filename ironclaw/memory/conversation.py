"""
ironclaw.memory.conversation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Conversation history store.

Supports two backends:
  - ``InMemoryConversation``  — fast, no persistence, suitable for short tasks
  - ``SQLiteConversation``    — persists across restarts, suitable for long-running agents

Both respect a ``max_messages`` sliding window so the context window never
grows unboundedly.  When the window is exceeded the oldest non-system messages
are evicted (system messages are always kept).
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

from ironclaw.core.message import Message, Role
from ironclaw.memory.base import MemoryBackend

_DEFAULT_MAX = 200  # messages before eviction kicks in


class InMemoryConversation(MemoryBackend):
    """
    Volatile in-memory conversation store.

    Parameters
    ----------
    max_messages : int
        Maximum messages to retain.  Oldest non-system messages are dropped
        when the limit is exceeded.
    """

    def __init__(self, max_messages: int = _DEFAULT_MAX) -> None:
        self.max_messages = max_messages
        self._messages: list[Message] = []
        self._lock = threading.Lock()

    def append(self, message: Message) -> None:
        with self._lock:
            self._messages.append(message)
            self._evict()

    def history(self, limit: int | None = None) -> list[Message]:
        with self._lock:
            msgs = list(self._messages)
        return msgs[-limit:] if limit else msgs

    def clear(self) -> None:
        with self._lock:
            self._messages.clear()

    def __len__(self) -> int:
        return len(self._messages)

    def _evict(self) -> None:
        """Remove oldest non-system messages when over limit."""
        while len(self._messages) > self.max_messages:
            for i, msg in enumerate(self._messages):
                if msg.role != Role.SYSTEM:
                    self._messages.pop(i)
                    break
            else:
                break  # only system messages left — stop


# Use the in-memory store as the default alias
ConversationMemory = InMemoryConversation


class SQLiteConversation(MemoryBackend):
    """
    SQLite-backed persistent conversation store.

    Messages are serialised as JSON and stored with their agent_id and
    session_id so multiple agents can share one database file.

    Parameters
    ----------
    db_path : str | Path
        Path to the SQLite database file.
    session_id : str
        Scope messages to this session.
    agent_id : str
        Scope messages to this agent.
    max_messages : int
        Retention limit per (session_id, agent_id) pair.
    """

    _CREATE_TABLE = """
        CREATE TABLE IF NOT EXISTS messages (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            session   TEXT NOT NULL,
            agent     TEXT NOT NULL,
            role      TEXT NOT NULL,
            content   TEXT NOT NULL,
            payload   TEXT NOT NULL,
            ts        TEXT NOT NULL
        )
    """
    _CREATE_IDX = "CREATE INDEX IF NOT EXISTS idx_session_agent ON messages (session, agent)"

    def __init__(
        self,
        db_path: str | Path,
        session_id: str = "default",
        agent_id: str = "",
        max_messages: int = _DEFAULT_MAX,
    ) -> None:
        self._db = Path(db_path)
        self._db.parent.mkdir(parents=True, exist_ok=True)
        self._session = session_id
        self._agent = agent_id
        self.max_messages = max_messages
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self._db), check_same_thread=False)
        self._conn.execute(self._CREATE_TABLE)
        self._conn.execute(self._CREATE_IDX)
        self._conn.commit()

    def append(self, message: Message) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO messages (session, agent, role, content, payload, ts) VALUES (?,?,?,?,?,?)",
                (
                    self._session,
                    self._agent,
                    message.role.value,
                    message.content,
                    json.dumps(message.to_dict()),
                    message.timestamp.isoformat(),
                ),
            )
            self._conn.commit()
            self._evict()

    def history(self, limit: int | None = None) -> list[Message]:
        with self._lock:
            if limit:
                rows = self._conn.execute(
                    "SELECT payload FROM messages WHERE session=? AND agent=? ORDER BY id DESC LIMIT ?",
                    (self._session, self._agent, limit),
                ).fetchall()
                rows = list(reversed(rows))
            else:
                rows = self._conn.execute(
                    "SELECT payload FROM messages WHERE session=? AND agent=? ORDER BY id ASC",
                    (self._session, self._agent),
                ).fetchall()

        messages = []
        for (payload,) in rows:
            try:
                data = json.loads(payload)
                msg = Message(
                    role=Role(data["role"]),
                    content=data["content"],
                    agent_id=data.get("agent_id", ""),
                    message_id=data["message_id"],
                )
                messages.append(msg)
            except Exception:
                pass
        return messages

    def clear(self) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM messages WHERE session=? AND agent=?",
                (self._session, self._agent),
            )
            self._conn.commit()

    def __len__(self) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM messages WHERE session=? AND agent=?",
                (self._session, self._agent),
            ).fetchone()
            return row[0] if row else 0

    def _evict(self) -> None:
        """Keep only the most recent max_messages rows."""
        self._conn.execute(
            """
            DELETE FROM messages
            WHERE session=? AND agent=? AND id NOT IN (
                SELECT id FROM messages
                WHERE session=? AND agent=?
                ORDER BY id DESC
                LIMIT ?
            )
            """,
            (self._session, self._agent, self._session, self._agent, self.max_messages),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
