"""
ironclaw.cli.commands.gateway
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
``ironclaw gateway`` subcommand tree.

Commands
--------
ironclaw gateway list
    Show all registered gateways and their status.

ironclaw gateway connect telegram --token TOKEN [--webhook-url URL]
                                   [--allow-chats ID ...]
ironclaw gateway connect whatsapp --access-token TOKEN
                                   --phone-id ID --verify-token TOKEN
                                   [--app-secret SECRET]
                                   [--allow-numbers NUMBER ...]
ironclaw gateway connect imessage [--interval SECONDS]
                                   [--allow-handles HANDLE ...]
                                   [--sms-fallback]

ironclaw gateway status
    Alias for ``gateway list`` (shows running/stopped per gateway + session count).
"""

from __future__ import annotations

import argparse

from ironclaw.cli.client import IronClawClient, APIError, ServerUnavailableError
from ironclaw.cli import fmt


# ---------------------------------------------------------------------------
# Subparser registration
# ---------------------------------------------------------------------------

def register(sub: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    p = sub.add_parser("gateway", help="Manage messaging gateways")
    s = p.add_subparsers(dest="gateway_cmd", metavar="<command>")
    s.required = True

    # list / status (aliases)
    s.add_parser("list",   help="List registered gateways")
    s.add_parser("status", help="Show gateway status (alias for list)")

    # connect
    pc = s.add_parser("connect", help="Connect a new messaging gateway")
    ps = pc.add_subparsers(dest="platform", metavar="<platform>")
    ps.required = True

    # telegram
    pt = ps.add_parser("telegram", help="Connect a Telegram bot")
    pt.add_argument("--token",       required=True, help="Telegram bot token")
    pt.add_argument("--webhook-url", default=None,  help="Public HTTPS webhook URL (omit for polling)")
    pt.add_argument("--allow-chats", nargs="*", default=[], metavar="CHAT_ID",
                    help="Allowed chat IDs (omit to allow all)")

    # whatsapp
    pw = ps.add_parser("whatsapp", help="Connect a WhatsApp Cloud API number")
    pw.add_argument("--access-token",  required=True, help="Meta access token")
    pw.add_argument("--phone-id",      required=True, help="WhatsApp phone number ID")
    pw.add_argument("--verify-token",  required=True, help="Webhook verify token")
    pw.add_argument("--app-secret",    default="",    help="Meta app secret (for signature validation)")
    pw.add_argument("--allow-numbers", nargs="*", default=[], metavar="NUMBER",
                    help="Allowed phone numbers (omit to allow all)")

    # imessage
    pi = ps.add_parser("imessage", help="Connect iMessage (macOS only)")
    pi.add_argument("--interval",      type=float, default=3.0,
                    help="Poll interval in seconds (default 3)")
    pi.add_argument("--allow-handles", nargs="*", default=[], metavar="HANDLE",
                    help="Allowed phone numbers/emails (omit to allow all)")
    pi.add_argument("--sms-fallback",  action="store_true",
                    help="Fall back to SMS if iMessage fails")


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def dispatch(args: argparse.Namespace, client: IronClawClient) -> int:
    cmd = args.gateway_cmd
    as_json = getattr(args, "json", False)

    try:
        if cmd in ("list", "status"):
            return _status(client, as_json)
        if cmd == "connect":
            return _connect(args, client, as_json)
    except ServerUnavailableError as e:
        fmt.error(str(e))
        return 1
    except APIError as e:
        fmt.error(str(e))
        return 1

    fmt.error(f"Unknown gateway command: {cmd}")
    return 1


# ---------------------------------------------------------------------------
# Implementations
# ---------------------------------------------------------------------------

def _status(client: IronClawClient, as_json: bool) -> int:
    data = client.gateway_status()
    if as_json:
        fmt.json_out(data)
        return 0

    running = data.get("running", False)
    gateways = data.get("gateways", [])
    sessions = data.get("sessions", 0)

    print(f"Daemon: {fmt.fmt_status(running)}  |  active sessions: {fmt.bold(str(sessions))}")
    print()

    if not gateways:
        fmt.info("No gateways registered. Use `ironclaw gateway connect` to add one.")
        return 0

    fmt.table(
        [
            {
                "platform": g.get("platform", "?"),
                "status":   "running" if g.get("running") else "stopped",
            }
            for g in gateways
        ],
        headers=["platform", "status"],
    )
    return 0


def _connect(args: argparse.Namespace, client: IronClawClient, as_json: bool) -> int:
    platform = args.platform

    if platform == "telegram":
        payload = {
            "token":            args.token,
            "webhook_url":      args.webhook_url,
            "allowed_chat_ids": args.allow_chats,
        }
        result = client.connect_telegram(payload)

    elif platform == "whatsapp":
        payload = {
            "access_token":    args.access_token,
            "phone_number_id": args.phone_id,
            "verify_token":    args.verify_token,
            "app_secret":      args.app_secret,
            "allowed_numbers": args.allow_numbers,
        }
        result = client.connect_whatsapp(payload)

    elif platform == "imessage":
        payload = {
            "poll_interval":   args.interval,
            "allowed_handles": args.allow_handles,
            "sms_fallback":    args.sms_fallback,
        }
        result = client.connect_imessage(payload)

    else:
        fmt.error(f"Unknown platform: {platform}")
        return 1

    if as_json:
        fmt.json_out(result)
        return 0

    mode = result.get("mode", "?")
    status = result.get("status", "?")
    fmt.success(f"{platform.capitalize()} gateway {status} ({mode} mode)")
    return 0
