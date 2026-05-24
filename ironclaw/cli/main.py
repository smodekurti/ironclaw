"""
ironclaw.cli.main
~~~~~~~~~~~~~~~~~
IronClaw command-line interface.

Full command tree
-----------------
  ironclaw [--server URL] [--json] [--log-level LEVEL]
  ├── agent   list | create | delete | show | chat | run | history | clear
  ├── gateway list | status | connect telegram|whatsapp|imessage
  ├── session list | clear | clear-all
  ├── orch    summary | pipeline | parallel
  ├── state   list | get | set | delete
  ├── audit   tail | search | verify | export
  ├── config  show | init | set
  ├── serve   [--host] [--port] [--reload]
  └── info

All management commands (agent/gateway/session/orch/state/audit) require a
running IronClaw server.  Start one with:

    ironclaw serve

Then in another terminal:

    ironclaw agent list
    ironclaw agent create --id mybot --provider anthropic --tools web
    ironclaw agent chat mybot
"""

from __future__ import annotations

import argparse
import logging
import sys

from ironclaw.cli import fmt


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def _setup_logging(level: str) -> None:
    logging.basicConfig(
        format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
        datefmt="%H:%M:%S",
        level=getattr(logging, level.upper(), logging.WARNING),
    )


# ---------------------------------------------------------------------------
# `info` command (no server required)
# ---------------------------------------------------------------------------

def _cmd_info(_args: argparse.Namespace) -> int:
    import importlib.metadata
    try:
        version = importlib.metadata.version("ironclaw")
    except Exception:
        version = "(development)"

    fmt.section("IronClaw Framework")
    fmt.key_value({
        "version": version,
        "python":  sys.version.split()[0],
    }, indent=2)

    # Show active env config if available
    try:
        from ironclaw.config import IronClawConfig
        cfg = IronClawConfig.load()
        print()
        fmt.section("Configuration")
        fmt.key_value({
            "default_provider":  cfg.default_provider,
            "default_model":     cfg.default_model,
            "audit_log_path":    cfg.audit_log_path or "(stderr only)",
            "guard_block_thresh": cfg.guard_block_threshold,
            "guard_warn_thresh":  cfg.guard_warn_threshold,
            "sandbox_timeout":   cfg.sandbox_timeout,
        }, indent=2)
    except Exception:
        pass

    return 0


# ---------------------------------------------------------------------------
# `serve` command (no server required — starts the server)
# ---------------------------------------------------------------------------

def _cmd_serve(args: argparse.Namespace) -> int:
    try:
        from ironclaw.web.server import serve
    except ImportError:
        fmt.error(
            "Web server dependencies missing.\n"
            "  Install them with: pip install 'ironclaw[web]'"
        )
        return 1

    tunnel_url = None
    if getattr(args, "tunnel", False):
        try:
            from pyngrok import ngrok
            tunnel = ngrok.connect(args.port, bind_tls=True)
            tunnel_url = tunnel.public_url
            fmt.success(f"ngrok tunnel established: {tunnel_url}")
        except ImportError:
            fmt.error("pyngrok not installed. Install with: pip install pyngrok")
            return 1
        except Exception as e:
            fmt.error(f"Failed to start ngrok tunnel: {e}")
            return 1

    fmt.success(
        f"Starting IronClaw server at http://{args.host}:{args.port}"
    )
    if tunnel_url:
        fmt.info(f"Public webhook URL: {tunnel_url}")
    fmt.info("Web UI available at the same address.")
    fmt.info("Stop with Ctrl+C\n")
    serve(host=args.host, port=args.port, reload=args.reload)
    return 0


# ---------------------------------------------------------------------------
# Build the top-level parser
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ironclaw",
        description="IronClaw — secure-by-design agentic AI framework",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Quick start:\n"
            "  ironclaw serve                          # start the server\n"
            "  ironclaw agent create --id mybot --provider anthropic\n"
            "  ironclaw agent chat mybot               # interactive chat\n"
            "\n"
            "Documentation: https://github.com/your-org/ironclaw"
        ),
    )

    parser.add_argument(
        "--server", "-s",
        metavar="URL",
        default=None,
        help="IronClaw server URL (default: $IRONCLAW_SERVER or http://localhost:7432)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output raw JSON instead of formatted text",
    )
    parser.add_argument(
        "--log-level",
        metavar="LEVEL",
        default="WARNING",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging verbosity (default: WARNING)",
    )

    sub = parser.add_subparsers(dest="command", metavar="<command>")
    sub.required = True

    # Register all command groups
    from ironclaw.cli.commands import (
        agent, gateway, session, orch, state, audit, config_cmd,
        providers, skills, setup, user,
    )
    agent.register(sub)
    gateway.register(sub)
    session.register(sub)
    orch.register(sub)
    state.register(sub)
    audit.register(sub)
    config_cmd.register(sub)
    providers.register(sub)
    skills.register(sub)
    setup.register(sub)
    user.register(sub)

    # serve
    p_serve = sub.add_parser("serve", help="Start the IronClaw web server")
    p_serve.add_argument("--host",   default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    p_serve.add_argument("--port",   type=int, default=7432, help="Port (default: 7432)")
    p_serve.add_argument("--reload", action="store_true",   help="Enable auto-reload for development")
    p_serve.add_argument("--tunnel", action="store_true",   help="Start a secure ngrok tunnel to localhost")

    # info
    sub.add_parser("info", help="Show framework version and configuration")

    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    _setup_logging(args.log_level)

    # Commands that don't need a running server
    if args.command == "serve":
        sys.exit(_cmd_serve(args))

    if args.command == "info":
        sys.exit(_cmd_info(args))

    # Commands that talk directly to LLMs / local files (no server)
    no_server_cmds = {"config", "providers", "skills", "setup", "user"}
    if args.command in no_server_cmds:
        from ironclaw.cli.commands import config_cmd, providers, skills, setup, user
        direct_map = {
            "config":    config_cmd.dispatch,
            "providers": providers.dispatch,
            "skills":    skills.dispatch,
            "setup":     setup.dispatch,
            "user":      user.dispatch,
        }
        sys.exit(direct_map[args.command](args, None))  # type: ignore[arg-type]

    # All other commands talk to the running server
    from ironclaw.cli.client import make_client, require_server
    client = make_client(args)
    require_server(client)

    from ironclaw.cli.commands import agent, gateway, session, orch, state, audit

    dispatch_map = {
        "agent":   agent.dispatch,
        "gateway": gateway.dispatch,
        "session": session.dispatch,
        "orch":    orch.dispatch,
        "state":   state.dispatch,
        "audit":   audit.dispatch,
    }

    handler = dispatch_map.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(1)

    sys.exit(handler(args, client))


if __name__ == "__main__":
    main()
