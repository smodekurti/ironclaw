"""
ironclaw.cli.commands.session
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
``ironclaw session`` subcommand tree.

Sessions are stored in the server's SharedStateStore under gateway-session
keys. This command group lets you inspect and clean up active sessions.

Commands
--------
ironclaw session list
    List all active gateway sessions (platform, sender, agent, message count).

ironclaw session clear <session_key>
    Delete a specific session from the shared state store.

ironclaw session clear-all
    Delete all keys that look like session entries.
"""

from __future__ import annotations

import argparse

from ironclaw.cli.client import IronClawClient, APIError, ServerUnavailableError
from ironclaw.cli import fmt


# ---------------------------------------------------------------------------
# Subparser registration
# ---------------------------------------------------------------------------

def register(sub: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    p = sub.add_parser("session", help="Manage gateway sessions")
    s = p.add_subparsers(dest="session_cmd", metavar="<command>")
    s.required = True

    s.add_parser("list", help="List all active sessions")

    pc = s.add_parser("clear", help="Delete a specific session key")
    pc.add_argument("key", help="Session key to delete")

    s.add_parser("clear-all", help="Delete all session entries from shared state")


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def dispatch(args: argparse.Namespace, client: IronClawClient) -> int:
    cmd = args.session_cmd
    as_json = getattr(args, "json", False)

    try:
        if cmd == "list":
            return _list(client, as_json)
        if cmd == "clear":
            return _clear(args, client, as_json)
        if cmd == "clear-all":
            return _clear_all(client, as_json)
    except ServerUnavailableError as e:
        fmt.error(str(e))
        return 1
    except APIError as e:
        fmt.error(str(e))
        return 1

    fmt.error(f"Unknown session command: {cmd}")
    return 1


# ---------------------------------------------------------------------------
# Implementations
# ---------------------------------------------------------------------------

def _list(client: IronClawClient, as_json: bool) -> int:
    state = client.get_state()

    # Sessions are stored under keys like "session:<platform>:<sender_id>"
    sessions = {k: v for k, v in state.items() if k.startswith("session:")}

    if as_json:
        fmt.json_out(sessions)
        return 0

    if not sessions:
        fmt.info("No active sessions found in shared state.")
        return 0

    rows = []
    for key, val in sessions.items():
        parts = key.split(":", 2)
        platform = parts[1] if len(parts) > 1 else "?"
        sender   = parts[2] if len(parts) > 2 else "?"
        if isinstance(val, dict):
            agent_id = val.get("agent_id", "?")
            msg_count = str(val.get("message_count", "?"))
        else:
            agent_id = "?"
            msg_count = "?"
        rows.append({
            "key":      key,
            "platform": platform,
            "sender":   sender,
            "agent":    agent_id,
            "messages": msg_count,
        })

    fmt.table(rows, headers=["key", "platform", "sender", "agent", "messages"])
    return 0


def _clear(args: argparse.Namespace, client: IronClawClient, as_json: bool) -> int:
    result = client.delete_state(args.key)
    if as_json:
        fmt.json_out(result)
        return 0
    fmt.success(f"Session '{args.key}' deleted")
    return 0


def _clear_all(client: IronClawClient, as_json: bool) -> int:
    state = client.get_state()
    session_keys = [k for k in state if k.startswith("session:")]

    if not session_keys:
        fmt.info("No session keys found.")
        return 0

    deleted = []
    for key in session_keys:
        client.delete_state(key)
        deleted.append(key)

    if as_json:
        fmt.json_out({"deleted": deleted})
        return 0

    fmt.success(f"Deleted {len(deleted)} session(s)")
    return 0
