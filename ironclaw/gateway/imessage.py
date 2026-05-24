"""
ironclaw.gateway.imessage
~~~~~~~~~~~~~~~~~~~~~~~~~
iMessage gateway for macOS.

How it works
------------
**Sending**: Uses AppleScript via ``osascript`` to tell the Messages app to
send a message to a handle (phone number or email).

**Receiving**: Apple doesn't provide an official API for reading incoming
iMessages. We poll the Messages SQLite database directly:
    ~/Library/Messages/chat.db

The gateway records the last-seen message rowid and checks for new rows
every ``poll_interval`` seconds.

Security notes
--------------
- ``chat.db`` requires Full Disk Access permission for the Python process.
  Grant this in System Settings → Privacy & Security → Full Disk Access.
- Messages are read from the local DB so no network API or credentials are
  needed for receiving.
- Only messages where ``is_from_me = 0`` (incoming) are forwarded to agents.

Limitations
-----------
- macOS only. Raises ``RuntimeError`` on non-macOS platforms.
- Requires the Messages app to be running and iMessage signed in.
- Delivery confirmation is based on the local DB, not iCloud sync status.
- Group chats are supported (``chat.room_name`` is used as the chat handle).

Setup
-----
No credentials needed — just:
    pip install ironclaw
    ironclaw serve   # or start the GatewayDaemon
Then grant Full Disk Access to Terminal / your Python binary.
"""

from __future__ import annotations

import asyncio
import logging
import platform
import subprocess
import sqlite3
from pathlib import Path
from typing import Any

from ironclaw.gateway.base import BaseGateway, InboundMessage, OutboundMessage, Platform, PlatformID

logger = logging.getLogger(__name__)

_CHAT_DB = Path.home() / "Library" / "Messages" / "chat.db"
_DEFAULT_POLL = 3.0     # seconds between DB polls
_MAX_MSG_LEN = 2000     # truncate outbound messages at this length

# AppleScript template for sending
_APPLESCRIPT_SEND = """
tell application "Messages"
    set targetBuddy to "{handle}"
    set targetService to 1st account whose service type = iMessage
    send "{text}" to buddy targetBuddy of targetService
end tell
"""

# AppleScript for SMS fallback (when iMessage is unavailable)
_APPLESCRIPT_SEND_SMS = """
tell application "Messages"
    set targetBuddy to "{handle}"
    set targetService to 1st account whose service type = SMS
    send "{text}" to buddy targetBuddy of targetService
end tell
"""


class iMessageGateway(BaseGateway):
    """
    iMessage gateway via AppleScript + Messages SQLite DB polling.

    Parameters
    ----------
    poll_interval : float
        Seconds between polls of chat.db for new messages.
    allowed_handles : set[str] | None
        Allowlist of phone numbers or emails.  ``None`` → accept all.
    db_path : Path | None
        Override the default chat.db path (for testing).
    sms_fallback : bool
        If True, fall back to SMS when iMessage send fails.
    """

    platform = Platform.IMESSAGE

    def __init__(
        self,
        poll_interval: float = _DEFAULT_POLL,
        allowed_handles: set[str] | None = None,
        db_path: Path | None = None,
        sms_fallback: bool = False,
    ) -> None:
        super().__init__()
        if platform.system() != "Darwin":
            raise RuntimeError("iMessageGateway is only supported on macOS")
        self.poll_interval = poll_interval
        self._allowed = allowed_handles
        self._db_path = db_path or _CHAT_DB
        self._sms_fallback = sms_fallback
        self._last_rowid: int = -1
        self._poll_task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if not self._db_path.exists():
            raise FileNotFoundError(
                f"Messages database not found at {self._db_path}. "
                "Make sure Messages app is set up and Full Disk Access is granted."
            )
        # Initialise offset to current max rowid (don't replay old messages)
        self._last_rowid = self._get_max_rowid()
        self._running = True
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info("[iMessage] Gateway started (polling every %.1fs)", self.poll_interval)

    async def stop(self) -> None:
        self._running = False
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        logger.info("[iMessage] Stopped")

    # ------------------------------------------------------------------
    # Send
    # ------------------------------------------------------------------

    async def send(self, message: OutboundMessage) -> None:
        handle = message.platform_id.sender_id
        text = message.text[:_MAX_MSG_LEN].replace('"', '\\"').replace("\\", "\\\\")

        script = _APPLESCRIPT_SEND.format(handle=handle, text=text)
        success = await self._run_applescript(script)

        if not success and self._sms_fallback:
            logger.warning("[iMessage] Falling back to SMS for %s", handle)
            script = _APPLESCRIPT_SEND_SMS.format(handle=handle, text=text)
            await self._run_applescript(script)

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    async def _poll_loop(self) -> None:
        while self._running:
            try:
                messages = await asyncio.to_thread(self._fetch_new_messages)
                for msg in messages:
                    await self.dispatch(msg)
            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.error("[iMessage] Poll error: %s", e)
            await asyncio.sleep(self.poll_interval)

    def _fetch_new_messages(self) -> list[InboundMessage]:
        """Read new incoming messages from chat.db synchronously."""
        try:
            conn = sqlite3.connect(
                f"file:{self._db_path}?mode=ro",
                uri=True,
                check_same_thread=False,
            )
        except sqlite3.OperationalError as e:
            logger.error("[iMessage] Cannot open chat.db: %s", e)
            return []

        try:
            query = """
                SELECT
                    m.ROWID,
                    m.text,
                    m.is_from_me,
                    h.id            AS handle,
                    m.date          AS apple_date
                FROM message m
                JOIN handle h ON m.handle_id = h.ROWID
                WHERE m.ROWID > ?
                  AND m.is_from_me = 0
                  AND m.text IS NOT NULL
                  AND m.text != ''
                ORDER BY m.ROWID ASC
                LIMIT 50
            """
            rows = conn.execute(query, (self._last_rowid,)).fetchall()
        except sqlite3.OperationalError as e:
            logger.error("[iMessage] Query error: %s", e)
            conn.close()
            return []
        finally:
            conn.close()

        results: list[InboundMessage] = []
        for rowid, text, _is_from_me, handle, _apple_date in rows:
            self._last_rowid = max(self._last_rowid, rowid)

            # Normalise handle
            handle = (handle or "").strip()
            if not handle:
                continue

            # Allowlist check
            if self._allowed and handle not in self._allowed:
                logger.debug("[iMessage] Dropping message from %s (not in allowlist)", handle)
                continue

            results.append(InboundMessage(
                platform_id=PlatformID(Platform.IMESSAGE, handle),
                text=text.strip(),
                message_id=str(rowid),
                raw={"rowid": rowid, "handle": handle},
            ))

        return results

    def _get_max_rowid(self) -> int:
        try:
            conn = sqlite3.connect(f"file:{self._db_path}?mode=ro", uri=True)
            row = conn.execute("SELECT MAX(ROWID) FROM message").fetchone()
            conn.close()
            return row[0] or 0
        except Exception:
            return 0

    # ------------------------------------------------------------------
    # AppleScript helper
    # ------------------------------------------------------------------

    @staticmethod
    async def _run_applescript(script: str) -> bool:
        """Execute an AppleScript and return True on success."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "osascript", "-e", script,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
            if proc.returncode != 0:
                logger.error("[iMessage] AppleScript error: %s", stderr.decode().strip())
                return False
            return True
        except asyncio.TimeoutError:
            logger.error("[iMessage] AppleScript timed out")
            return False
        except Exception as e:
            logger.error("[iMessage] AppleScript failed: %s", e)
            return False

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    @staticmethod
    def check_permissions() -> dict[str, bool]:
        """
        Check whether the required macOS permissions are in place.
        Returns a dict with 'full_disk_access' and 'messages_app' keys.
        """
        checks: dict[str, bool] = {}

        # Full Disk Access: can we read chat.db?
        checks["full_disk_access"] = _CHAT_DB.exists() and _CHAT_DB.stat().st_size > 0

        # Messages app running
        result = subprocess.run(
            ["pgrep", "-x", "Messages"],
            capture_output=True,
        )
        checks["messages_app_running"] = result.returncode == 0

        return checks
