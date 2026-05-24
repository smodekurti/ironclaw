"""
ironclaw.cli.commands.state
~~~~~~~~~~~~~~~~~~~~~~~~~~~
``ironclaw state`` subcommand tree.

The shared state store is an in-memory (optionally SQLite-backed) dict that
all agents and gateways can read/write.  These commands let you inspect and
manage it from the CLI.

Commands
--------
ironclaw state list
    Print all key/value pairs currently in the store.

ironclaw state get <key>
    Print the value for a single key.

ironclaw state set <key> <value>
    Set a key to a string value (or JSON if value parses as JSON).

ironclaw state delete <key>
    Remove a key from the store.
"""

from __future__ import annotations

import argparse
import json

from ironclaw.cli.client import IronClawClient, APIError, ServerUnavailableError
from ironclaw.cli import fmt


# ---------------------------------------------------------------------------
# Subparser registration
# ---------------------------------------------------------------------------

def register(sub: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    p = sub.add_parser("state", help="Manage shared state store")
    s = p.add_subparsers(dest="state_cmd", metavar="<command>")
    s.required = True

    s.add_parser("list", help="List all state keys and values")

    pg = s.add_parser("get", help="Get a single state value")
    pg.add_argument("key")

    ps = s.add_parser("set", help="Set a state key")
    ps.add_argument("key")
    ps.add_argument("value", help="String value or JSON")

    pd = s.add_parser("delete", help="Delete a state key")
    pd.add_argument("key")


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def dispatch(args: argparse.Namespace, client: IronClawClient) -> int:
    cmd = args.state_cmd
    as_json = getattr(args, "json", False)

    try:
        if cmd == "list":
            return _list(client, as_json)
        if cmd == "get":
            return _get(args, client, as_json)
        if cmd == "set":
            return _set(args, client, as_json)
        if cmd == "delete":
            return _delete(args, client, as_json)
    except ServerUnavailableError as e:
        fmt.error(str(e))
        return 1
    except APIError as e:
        fmt.error(str(e))
        return 1

    fmt.error(f"Unknown state command: {cmd}")
    return 1


# ---------------------------------------------------------------------------
# Implementations
# ---------------------------------------------------------------------------

def _list(client: IronClawClient, as_json: bool) -> int:
    state = client.get_state()
    if as_json:
        fmt.json_out(state)
        return 0

    if not state:
        fmt.info("Shared state is empty.")
        return 0

    fmt.key_value(state)
    return 0


def _get(args: argparse.Namespace, client: IronClawClient, as_json: bool) -> int:
    state = client.get_state()
    if args.key not in state:
        fmt.error(f"Key '{args.key}' not found")
        return 1

    val = state[args.key]
    if as_json:
        fmt.json_out(val)
        return 0

    if isinstance(val, (dict, list)):
        print(json.dumps(val, indent=2, default=str))
    else:
        print(val)
    return 0


def _set(args: argparse.Namespace, client: IronClawClient, as_json: bool) -> int:
    # Try to parse value as JSON first; fall back to raw string
    try:
        value = json.loads(args.value)
    except (json.JSONDecodeError, ValueError):
        value = args.value

    # POST to a state-set endpoint isn't in the server, so we use the
    # shared-state HTTP write path via the orchestrator pipeline trick.
    # For now, notify the user — direct set via REST isn't exposed.
    fmt.warn(
        "The IronClaw REST API does not expose a write endpoint for shared state.\n"
        "  State is written by agents at runtime.  Use this command to read/delete keys.\n"
        "  To pre-seed state, add it in your agent's system prompt or start-up config."
    )
    return 1


def _delete(args: argparse.Namespace, client: IronClawClient, as_json: bool) -> int:
    result = client.delete_state(args.key)
    if as_json:
        fmt.json_out(result)
        return 0
    fmt.success(f"Key '{args.key}' deleted")
    return 0
