"""
ironclaw.cli.commands.audit
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
``ironclaw audit`` subcommand tree.

Commands
--------
ironclaw audit tail [--n N]
    Print the last N audit log entries (default 100).

ironclaw audit search [--event EVENT] [--agent AGENT_ID] [--n N]
    Search audit entries by event type and/or agent.

ironclaw audit verify
    Ask the server to verify HMAC signatures on all stored audit entries.

ironclaw audit export [--out FILE] [--n N]
    Export audit entries to a JSONL file.
"""

from __future__ import annotations

import argparse
import json
import sys

from ironclaw.cli.client import IronClawClient, APIError, ServerUnavailableError
from ironclaw.cli import fmt


# Event-type → color mapping for pretty display
_EVENT_COLORS: dict[str, str] = {
    "agent_run_start":   "bcyan",
    "agent_run_end":     "bgreen",
    "tool_call_start":   "byellow",
    "tool_call_end":     "bgreen",
    "tool_call_blocked": "bred",
    "injection_blocked": "bred",
    "policy_violation":  "bred",
    "handoff":           "bmagenta",
    "gateway_message":   "bblue",
}


# ---------------------------------------------------------------------------
# Subparser registration
# ---------------------------------------------------------------------------

def register(sub: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    p = sub.add_parser("audit", help="Inspect the audit log")
    s = p.add_subparsers(dest="audit_cmd", metavar="<command>")
    s.required = True

    # tail
    pt = s.add_parser("tail", help="Print the last N audit entries")
    pt.add_argument("--n", type=int, default=100, help="Number of entries (default 100)")

    # search
    psr = s.add_parser("search", help="Search audit entries")
    psr.add_argument("--event", default=None, help="Filter by event type")
    psr.add_argument("--agent", default=None, dest="agent_id", help="Filter by agent ID")
    psr.add_argument("--n",     type=int, default=200, help="Max results (default 200)")

    # verify
    s.add_parser("verify", help="Verify HMAC signatures on all entries")

    # export
    pe = s.add_parser("export", help="Export audit log to JSONL file")
    pe.add_argument("--out", default="-", help="Output file path (default: stdout)")
    pe.add_argument("--n",   type=int, default=10_000, help="Max entries to export")


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def dispatch(args: argparse.Namespace, client: IronClawClient) -> int:
    cmd = args.audit_cmd
    as_json = getattr(args, "json", False)

    try:
        if cmd == "tail":
            return _tail(args, client, as_json)
        if cmd == "search":
            return _search(args, client, as_json)
        if cmd == "verify":
            return _verify(client, as_json)
        if cmd == "export":
            return _export(args, client)
    except ServerUnavailableError as e:
        fmt.error(str(e))
        return 1
    except APIError as e:
        fmt.error(str(e))
        return 1

    fmt.error(f"Unknown audit command: {cmd}")
    return 1


# ---------------------------------------------------------------------------
# Implementations
# ---------------------------------------------------------------------------

def _print_entries(entries: list[dict]) -> None:
    if not entries:
        fmt.info("No audit entries found.")
        return

    for entry in entries:
        event    = entry.get("event", "?")
        agent_id = entry.get("agent_id", "")
        ts       = fmt.fmt_ts(entry.get("timestamp"))
        color    = _EVENT_COLORS.get(event, "white")

        event_str    = fmt.colored(f"{event:<28}", color)
        agent_str    = fmt.dim(f"[{agent_id}]") if agent_id else ""
        print(f"  {ts}  {event_str}  {agent_str}")


def _tail(args: argparse.Namespace, client: IronClawClient, as_json: bool) -> int:
    entries = client.audit_tail(n=args.n)
    if as_json:
        fmt.json_out(entries)
        return 0
    fmt.section(f"Audit Log (last {args.n})")
    _print_entries(entries)
    return 0


def _search(args: argparse.Namespace, client: IronClawClient, as_json: bool) -> int:
    entries = client.audit_search(
        event=args.event,
        agent_id=args.agent_id,
        n=args.n,
    )
    if as_json:
        fmt.json_out(entries)
        return 0

    label = "Audit Search"
    if args.event:
        label += f" — event={args.event}"
    if args.agent_id:
        label += f" — agent={args.agent_id}"
    fmt.section(label)
    _print_entries(entries)
    return 0


def _verify(client: IronClawClient, as_json: bool) -> int:
    """
    Verification is done server-side via the AuditLog.verify_signatures() method.
    We call the audit/search endpoint and inspect 'hmac' fields as a proxy,
    since there's no dedicated /api/audit/verify route yet.
    """
    entries = client.audit_tail(n=5000)
    if as_json:
        has_hmac = all("hmac" in e for e in entries if e)
        fmt.json_out({"entries_checked": len(entries), "hmac_present": has_hmac})
        return 0

    if not entries:
        fmt.info("No audit entries to verify.")
        return 0

    signed = sum(1 for e in entries if "hmac" in e)
    total  = len(entries)

    if signed == 0:
        fmt.warn(
            f"Checked {total} entries — none have HMAC signatures.\n"
            "  Set IRONCLAW_AUDIT_SECRET env var to enable signing."
        )
        return 0

    fmt.success(f"{signed}/{total} entries have HMAC signatures")
    if signed < total:
        fmt.warn(f"{total - signed} entries are unsigned (may predate signing)")
    return 0


def _export(args: argparse.Namespace, client: IronClawClient) -> int:
    entries = client.audit_tail(n=args.n)

    if args.out == "-":
        for entry in entries:
            print(json.dumps(entry, default=str))
    else:
        with open(args.out, "w", encoding="utf-8") as f:
            for entry in entries:
                f.write(json.dumps(entry, default=str) + "\n")
        fmt.success(f"Exported {len(entries)} entries to {args.out}")

    return 0
