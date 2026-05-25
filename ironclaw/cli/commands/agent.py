"""
ironclaw.cli.commands.agent
~~~~~~~~~~~~~~~~~~~~~~~~~~~
``ironclaw agent`` subcommand tree.

Commands
--------
ironclaw agent list
    List all registered agents.

ironclaw agent create [options]
    Register a new agent (flags or --file spec.json).

ironclaw agent create-chat
    Interactively design and create an agent through conversation.

ironclaw agent export <agent_id>
    Export an agent's spec as JSON.

ironclaw agent delete <agent_id>
    Unregister an agent.

ironclaw agent show <agent_id>
    Show detailed info + recent history for an agent.

ironclaw agent chat <agent_id>
    Interactive REPL-style chat with an agent.

ironclaw agent run <agent_id> -m "message"
    Send a single message and print the reply.

ironclaw agent history <agent_id>
    Print conversation history.

ironclaw agent clear <agent_id>
    Clear an agent's conversation memory.
"""

from __future__ import annotations

import argparse
import json
import sys

from ironclaw.cli.client import IronClawClient, APIError, ServerUnavailableError
from ironclaw.cli import fmt


# ---------------------------------------------------------------------------
# Subparser registration
# ---------------------------------------------------------------------------

def register(sub: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    p = sub.add_parser("agent", help="Manage agents")
    s = p.add_subparsers(dest="agent_cmd", metavar="<command>")
    s.required = True

    # list
    s.add_parser("list", help="List all registered agents")

    # create
    pc = s.add_parser("create", help="Create and register a new agent")
    # ACE spec file (new way)
    pc.add_argument(
        "--file", "-f", metavar="SPEC.json",
        help="Path to an AgentSpec JSON file (ACE format). Takes precedence over flags.",
    )
    pc.add_argument(
        "--dry-run", action="store_true", default=False,
        help="Validate and show what would be created without actually creating the agent",
    )
    pc.add_argument(
        "--set", nargs="*", metavar="KEY=VALUE", default=[],
        help="Override spec fields: --set agentId=mybot model.provider=openai",
    )
    # Legacy flag-based creation
    pc.add_argument("--id",       default="",  dest="agent_id", help="Unique agent identifier")
    pc.add_argument("--name",     default="",     help="Human-readable name")
    pc.add_argument("--prompt",   default="You are a helpful assistant.",
                    dest="system_prompt", help="System prompt")
    pc.add_argument("--provider", default="anthropic",
                    help="LLM provider (anthropic, openai, ollama, groq, …)")
    pc.add_argument("--model",    default="", help="Model name (default: provider default)")
    pc.add_argument("--caps",     nargs="*", default=[], metavar="CAP",
                    help="Capabilities e.g. web:* file:read")
    pc.add_argument("--tools",    nargs="*", default=[], metavar="TOOL",
                    choices=["web", "filesystem", "shell"],
                    help="Built-in tool bundles")
    pc.add_argument("--roots",    nargs="*", default=[], metavar="PATH",
                    help="Allowed filesystem roots (filesystem tool)")
    pc.add_argument("--cmds",     nargs="*", default=[], metavar="CMD",
                    help="Allowed shell commands (shell tool)")
    pc.add_argument("--api-key",  default="", dest="api_key",
                    help="Provider API key env var reference, e.g. env:ANTHROPIC_API_KEY")

    # create-chat — conversational ACE
    pcc = s.add_parser("create-chat", help="Design and create an agent through conversation")
    pcc.add_argument("--session", default="creator-default", dest="session_id",
                     help="Creator Agent session ID")

    # export
    pex = s.add_parser("export", help="Export an agent's spec as JSON")
    pex.add_argument("agent_id", help="Agent to export")
    pex.add_argument("--output", "-o", metavar="FILE",
                     help="Write to file instead of stdout")

    # delete
    pd = s.add_parser("delete", help="Unregister an agent")
    pd.add_argument("agent_id", help="Agent to delete")

    # show
    ps = s.add_parser("show", help="Show agent details and recent history")
    ps.add_argument("agent_id", help="Agent to inspect")
    ps.add_argument("--limit", type=int, default=10,
                    help="Number of history messages to show (default 10)")

    # chat
    pch = s.add_parser("chat", help="Interactive chat with an agent")
    pch.add_argument("agent_id", help="Agent to chat with")
    pch.add_argument("--session", default="", dest="session_id",
                     help="Session ID for multi-turn memory")

    # run
    pr = s.add_parser("run", help="Send a single message and print the reply")
    pr.add_argument("agent_id", help="Agent to message")
    pr.add_argument("-m", "--message", required=True, help="Message text")
    pr.add_argument("--session", default="", dest="session_id")

    # history
    ph = s.add_parser("history", help="Print conversation history")
    ph.add_argument("agent_id")
    ph.add_argument("--limit", type=int, default=50)

    # clear
    pcl = s.add_parser("clear", help="Clear an agent's conversation memory")
    pcl.add_argument("agent_id")


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def dispatch(args: argparse.Namespace, client: IronClawClient) -> int:
    cmd = args.agent_cmd
    as_json = getattr(args, "json", False)

    try:
        if cmd == "list":
            return _list(client, as_json)
        if cmd == "create":
            return _create(args, client, as_json)
        if cmd == "create-chat":
            return _create_chat(args, client)
        if cmd == "export":
            return _export(args, client, as_json)
        if cmd == "delete":
            return _delete(args, client, as_json)
        if cmd == "show":
            return _show(args, client, as_json)
        if cmd == "chat":
            return _chat(args, client)
        if cmd == "run":
            return _run(args, client, as_json)
        if cmd == "history":
            return _history(args, client, as_json)
        if cmd == "clear":
            return _clear(args, client, as_json)
    except ServerUnavailableError as e:
        fmt.error(str(e))
        return 1
    except APIError as e:
        fmt.error(str(e))
        return 1

    fmt.error(f"Unknown agent command: {cmd}")
    return 1


# ---------------------------------------------------------------------------
# Implementations
# ---------------------------------------------------------------------------

def _list(client: IronClawClient, as_json: bool) -> int:
    data = client.list_agents()
    agents = data if isinstance(data, list) else data.get("agents", [])

    if as_json:
        fmt.json_out(agents)
        return 0

    if not agents:
        fmt.info("No agents registered. Use `ironclaw agent create` to add one.")
        return 0

    fmt.table(
        agents,
        headers=["agent_id", "name", "provider", "model"],
        max_col_width=36,
    )
    return 0


def _apply_set_overrides(spec: dict, set_args: list[str]) -> dict:
    """
    Apply ``--set KEY=VALUE`` overrides to a spec dict.

    Supports dotted paths: ``--set model.provider=openai``
    """
    for item in (set_args or []):
        if "=" not in item:
            fmt.warning(f"  Ignoring malformed --set arg: {item!r} (expected KEY=VALUE)")
            continue
        key, _, value = item.partition("=")
        parts = key.split(".")
        target = spec
        for part in parts[:-1]:
            target = target.setdefault(part, {})
        target[parts[-1]] = value
    return spec


def _create(args: argparse.Namespace, client: IronClawClient, as_json: bool) -> int:
    # ----------------------------------------------------------------
    # ACE path: --file spec.json
    # ----------------------------------------------------------------
    if getattr(args, "file", None):
        import json as _json
        try:
            with open(args.file) as fh:
                spec = _json.load(fh)
        except Exception as exc:
            fmt.error(f"Cannot read spec file: {exc}")
            return 1

        # Apply --set overrides
        spec = _apply_set_overrides(spec, args.set)

        endpoint = "/api/v1/ace/agents/create/dry-run" if args.dry_run else "/api/v1/ace/agents/create"
        try:
            result = client.post(endpoint, spec)
        except APIError as exc:
            fmt.error(str(exc))
            return 1

        if as_json:
            fmt.json_out(result)
            return 0

        if args.dry_run:
            fmt.section("Dry-run plan")
            plan = result.get("plan", result)
            fmt.key_value({
                "agentId":       plan.get("agentId"),
                "provider":      plan.get("provider"),
                "model":         plan.get("model"),
                "memory":        plan.get("memoryType"),
                "isolation":     plan.get("isolationType"),
                "tools":         ", ".join(plan.get("toolBundles", [])) or "—",
                "skills":        ", ".join(plan.get("skills", [])) or "—",
                "capabilities":  ", ".join(plan.get("capabilities", [])) or "—",
                "workspace":     plan.get("workspacePath"),
                "alreadyExists": plan.get("alreadyExists"),
            }, indent=2)
            warnings = plan.get("warnings", [])
            if warnings:
                print()
                for w in warnings:
                    fmt.warning(f"  ⚠  {w}")
        else:
            fmt.success(f"Agent '{result.get('agentId')}' created via ACE")
            warnings = result.get("warnings", [])
            if warnings:
                for w in warnings:
                    fmt.warning(f"  ⚠  {w}")
        return 0

    # ----------------------------------------------------------------
    # Legacy flags path
    # ----------------------------------------------------------------
    if not args.agent_id:
        fmt.error("--id is required when not using --file")
        return 1

    payload = {
        "agent_id":      args.agent_id,
        "name":          args.name,
        "system_prompt": args.system_prompt,
        "provider":      args.provider,
        "model":         args.model or "claude-sonnet-4-6",
        "capabilities":  args.caps,
        "tools":         args.tools,
        "allowed_roots": args.roots,
        "allowed_commands": args.cmds,
        "api_key":       args.api_key,
    }

    if getattr(args, "dry_run", False):
        # Build a minimal AgentSpec for dry-run
        from ironclaw.ace.schema import AgentSpec
        try:
            spec = AgentSpec.minimal(
                args.agent_id,
                args.provider,
                system_prompt=args.system_prompt,
                model=args.model or None,
            )
            plan = None
            import asyncio
            from ironclaw.ace.provisioner import AgentProvisioner
            provisioner = AgentProvisioner()
            plan = asyncio.run(provisioner.dry_run(spec))
        except Exception as exc:
            fmt.error(f"Dry run failed: {exc}")
            return 1
        if as_json:
            fmt.json_out(plan)
        else:
            fmt.section("Dry-run plan")
            fmt.key_value(plan, indent=2)
        return 0

    result = client.create_agent(payload)

    if as_json:
        fmt.json_out(result)
        return 0

    fmt.success(f"Agent '{result.get('agent_id')}' created")
    fmt.key_value({
        "name":     result.get("name"),
        "provider": result.get("provider"),
        "model":    result.get("model"),
        "tools":    ", ".join(result.get("tools", [])) or "—",
    }, indent=2)
    return 0


def _create_chat(args: argparse.Namespace, client: IronClawClient) -> int:
    """
    Interactive conversational agent creation via the Creator Agent (ACE).

    Streams SSE from /api/v1/ace/agents/create/chat.
    """
    print(fmt.bold("IronClaw Creator Agent"))
    print(fmt.dim("  Describe the agent you want to build. Type 'exit' to quit.\n"))

    session_id = args.session_id
    while True:
        try:
            user_input = input(fmt.colored("You: ", "byellow"))
        except (KeyboardInterrupt, EOFError):
            print()
            fmt.info("Session ended.")
            return 0

        if user_input.strip().lower() in ("exit", "quit", "q"):
            fmt.info("Session ended.")
            return 0
        if not user_input.strip():
            continue

        try:
            print(fmt.colored("Creator: ", "bcyan"), end="", flush=True)
            # Use the streaming SSE endpoint
            reply = client.chat_sync_ace(user_input, session_id=session_id)
            print(reply)
        except APIError as e:
            fmt.error(str(e))
        except ServerUnavailableError as e:
            fmt.error(str(e))
            return 1

    return 0


def _export(args: argparse.Namespace, client: IronClawClient, as_json: bool) -> int:
    """Export an agent's spec from the ACE registry."""
    try:
        result = client.get(f"/api/v1/ace/agents/{args.agent_id}/status")
    except APIError:
        # Fall back to legacy endpoint
        try:
            result = client.get(f"/api/agents/{args.agent_id}")
        except APIError as exc:
            fmt.error(str(exc))
            return 1

    spec = result.get("spec", result)
    output = json.dumps(spec, indent=2)

    if hasattr(args, "output") and args.output:
        with open(args.output, "w") as fh:
            fh.write(output)
        fmt.success(f"Spec written to {args.output}")
    else:
        print(output)
    return 0


def _delete(args: argparse.Namespace, client: IronClawClient, as_json: bool) -> int:
    result = client.delete_agent(args.agent_id)
    if as_json:
        fmt.json_out(result)
        return 0
    fmt.success(f"Agent '{args.agent_id}' deleted")
    return 0


def _show(args: argparse.Namespace, client: IronClawClient, as_json: bool) -> int:
    # Get list to find agent details
    summary = client.list_agents()
    agents = summary if isinstance(summary, list) else summary.get("agents", [])
    agent_info = next((a for a in agents if a.get("agent_id") == args.agent_id), None)

    history = client.get_history(args.agent_id, limit=args.limit)

    if as_json:
        fmt.json_out({"agent": agent_info, "history": history})
        return 0

    if agent_info:
        fmt.section(f"Agent: {args.agent_id}")
        fmt.key_value(agent_info, indent=2)

    if history:
        fmt.section("Recent History")
        for msg in history:
            role = msg.get("role", "?")
            content = str(msg.get("content", ""))
            ts = fmt.fmt_ts(msg.get("timestamp"))
            role_color = "bcyan" if role == "assistant" else "byellow"
            prefix = fmt.colored(f"  [{role:9s}]", role_color)
            print(f"{prefix}  {fmt.truncate(content, 80)}  {ts}")
    else:
        fmt.info("No history yet.")

    return 0


def _chat(args: argparse.Namespace, client: IronClawClient) -> int:
    """Interactive REPL chat loop."""
    print(fmt.bold(f"Chatting with agent '{args.agent_id}'"))
    print(fmt.dim("  Type your message and press Enter. Ctrl+C or 'exit' to quit.\n"))

    session_id = args.session_id
    while True:
        try:
            user_input = input(fmt.colored("You: ", "byellow"))
        except (KeyboardInterrupt, EOFError):
            print()
            fmt.info("Goodbye.")
            return 0

        if user_input.strip().lower() in ("exit", "quit", "q"):
            fmt.info("Goodbye.")
            return 0
        if not user_input.strip():
            continue

        try:
            print(fmt.colored("Agent: ", "bcyan"), end="", flush=True)
            reply = client.chat_sync(args.agent_id, user_input, session_id=session_id)
            print(reply)
        except APIError as e:
            fmt.error(str(e))
        except ServerUnavailableError as e:
            fmt.error(str(e))
            return 1

    return 0


def _run(args: argparse.Namespace, client: IronClawClient, as_json: bool) -> int:
    reply = client.chat_sync(args.agent_id, args.message, session_id=args.session_id)
    if as_json:
        fmt.json_out({"agent_id": args.agent_id, "reply": reply})
        return 0
    print(reply)
    return 0


def _history(args: argparse.Namespace, client: IronClawClient, as_json: bool) -> int:
    history = client.get_history(args.agent_id, limit=args.limit)
    if as_json:
        fmt.json_out(history)
        return 0

    if not history:
        fmt.info("No history.")
        return 0

    for msg in history:
        role = msg.get("role", "?")
        content = str(msg.get("content", ""))
        ts = fmt.fmt_ts(msg.get("timestamp"))
        role_color = "bcyan" if role == "assistant" else "byellow"
        role_str = fmt.colored(f"[{role}]", role_color)
        print(f"{role_str}  {content}")
        if ts:
            print(f"        {ts}")
    return 0


def _clear(args: argparse.Namespace, client: IronClawClient, as_json: bool) -> int:
    result = client.clear_history(args.agent_id)
    if as_json:
        fmt.json_out(result)
        return 0
    fmt.success(f"History cleared for '{args.agent_id}'")
    return 0
