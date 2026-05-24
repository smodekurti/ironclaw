"""
ironclaw.cli.commands.orch
~~~~~~~~~~~~~~~~~~~~~~~~~~~
``ironclaw orch`` subcommand tree.

Commands
--------
ironclaw orch summary
    Print fleet status (agent count, per-agent metadata).

ironclaw orch pipeline --steps agent1[:"template"] agent2 ...
                        --input "initial message"
                        [--session SESSION_ID]
    Run a sequential pipeline: output of step N feeds step N+1.
    Template can embed {input} and {previous}.

ironclaw orch parallel --tasks agent1:"msg1" agent2:"msg2" ...
                        [--session SESSION_ID]
    Run multiple agents in parallel and print all results.
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
    p = sub.add_parser("orch", help="Orchestrator operations")
    s = p.add_subparsers(dest="orch_cmd", metavar="<command>")
    s.required = True

    # summary
    s.add_parser("summary", help="Show fleet summary")

    # pipeline
    pp = s.add_parser("pipeline", help="Run a sequential agent pipeline")
    pp.add_argument(
        "--steps", nargs="+", required=True, metavar="AGENT[:TEMPLATE]",
        help=(
            "Ordered agent IDs. Optionally append a colon and a Jinja-like "
            "template using {input} / {previous}. "
            "Example: researcher 'writer:Expand this: {previous}'"
        ),
    )
    pp.add_argument("--input",   required=True, dest="initial_input",
                    help="Initial message fed to the first agent")
    pp.add_argument("--session", default="", dest="session_id")

    # parallel
    ppa = s.add_parser("parallel", help="Run agents in parallel")
    ppa.add_argument(
        "--tasks", nargs="+", required=True, metavar="AGENT:MSG",
        help="Pairs of agent_id:message. Example: agent1:'summarise X' agent2:'analyse Y'",
    )
    ppa.add_argument("--session", default="", dest="session_id")


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def dispatch(args: argparse.Namespace, client: IronClawClient) -> int:
    cmd = args.orch_cmd
    as_json = getattr(args, "json", False)

    try:
        if cmd == "summary":
            return _summary(client, as_json)
        if cmd == "pipeline":
            return _pipeline(args, client, as_json)
        if cmd == "parallel":
            return _parallel(args, client, as_json)
    except ServerUnavailableError as e:
        fmt.error(str(e))
        return 1
    except APIError as e:
        fmt.error(str(e))
        return 1

    fmt.error(f"Unknown orch command: {cmd}")
    return 1


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_step(token: str) -> dict:
    """Parse 'agent_id' or 'agent_id:template' into a step dict."""
    if ":" in token:
        agent_id, template = token.split(":", 1)
        return {"agent_id": agent_id.strip(), "template": template.strip()}
    return {"agent_id": token.strip(), "template": None}


def _parse_task(token: str) -> dict:
    """Parse 'agent_id:message' into a task dict."""
    if ":" in token:
        agent_id, message = token.split(":", 1)
        return {"agent_id": agent_id.strip(), "input": message.strip()}
    return {"agent_id": token.strip(), "input": ""}


# ---------------------------------------------------------------------------
# Implementations
# ---------------------------------------------------------------------------

def _summary(client: IronClawClient, as_json: bool) -> int:
    data = client.orch_summary()
    if as_json:
        fmt.json_out(data)
        return 0

    agents = data.get("agents", [])
    fmt.section("Orchestrator Summary")
    fmt.key_value({
        "registered agents": len(agents),
    }, indent=2)

    if agents:
        print()
        fmt.table(
            agents,
            headers=["agent_id", "name", "provider", "model"],
            max_col_width=36,
        )
    return 0


def _pipeline(args: argparse.Namespace, client: IronClawClient, as_json: bool) -> int:
    steps = [_parse_step(s) for s in args.steps]
    result = client.orch_pipeline(steps, args.initial_input, args.session_id)

    if as_json:
        fmt.json_out(result)
        return 0

    results = result.get("results", [])
    fmt.section("Pipeline Results")
    for i, r in enumerate(results):
        agent_id = r.get("agent_id", f"step-{i}")
        content  = r.get("content", "")
        print(f"\n{fmt.bold(fmt.colored(f'[{i+1}] {agent_id}', 'bcyan'))}")
        print(content)
    return 0


def _parallel(args: argparse.Namespace, client: IronClawClient, as_json: bool) -> int:
    tasks = [_parse_task(t) for t in args.tasks]
    result = client.orch_parallel(tasks, args.session_id)

    if as_json:
        fmt.json_out(result)
        return 0

    results = result.get("results", [])
    fmt.section("Parallel Results")
    for i, r in enumerate(results):
        agent_id = r.get("agent_id", f"task-{i}")
        content  = r.get("content", "")
        print(f"\n{fmt.bold(fmt.colored(f'[{agent_id}]', 'bmagenta'))}")
        print(content)
    return 0
