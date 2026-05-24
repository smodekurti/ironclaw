"""
examples/multi_agent.py
~~~~~~~~~~~~~~~~~~~~~~~
Multi-agent pipeline: Researcher → Summariser → Writer.

The Orchestrator manages three agents:
  1. researcher  — web search, can fetch URLs
  2. summariser  — read-only, condenses research into key points
  3. writer      — file write access, formats the final report

Run:
    export ANTHROPIC_API_KEY=sk-ant-...
    python examples/multi_agent.py
"""

import asyncio

from ironclaw import AgentBuilder, Orchestrator
from ironclaw.security.audit import AuditLog
from ironclaw.security.policy import DenyAgents, RateLimit, SecurityPolicy


async def main() -> None:
    audit = AuditLog("logs/multi_agent_audit.jsonl")

    # --- Build agents ----------------------------------------------------

    researcher = (
        AgentBuilder("researcher")
        .with_name("Web Researcher")
        .with_system_prompt(
            "You are a web researcher. Search for accurate, up-to-date information. "
            "Return detailed findings with sources."
        )
        .with_anthropic()
        .with_capabilities(["web:search", "web:fetch"])
        .with_web_tools()
        .build()
    )

    summariser = (
        AgentBuilder("summariser")
        .with_name("Summariser")
        .with_system_prompt(
            "You receive raw research notes and distil them into a concise, "
            "structured list of key points. Be factual and precise."
        )
        .with_anthropic(model="claude-haiku-4-5-20251001")  # fast cheap model
        .with_capabilities([])  # no tools needed
        .build()
    )

    writer = (
        AgentBuilder("writer")
        .with_name("Report Writer")
        .with_system_prompt(
            "You are a professional report writer. Format the provided key points "
            "into a polished, well-structured Markdown report."
        )
        .with_anthropic()
        .with_capabilities(["file:write"])
        .with_filesystem_tools(allowed_roots=["/tmp/ironclaw_reports"])
        .build()
    )

    # --- Build orchestrator with policy ----------------------------------

    policy = SecurityPolicy()
    policy.add(DenyAgents({"untrusted"}))          # block any hypothetical bad agent
    policy.add(RateLimit(max_calls=30, window_seconds=60))

    orch = Orchestrator(policy=policy, audit_log=audit)
    orch.register(researcher)
    orch.register(summariser)
    orch.register(writer)

    # --- Run as pipeline -------------------------------------------------

    topic = "The current state of quantum computing and its implications for cryptography"

    print(f"Topic: {topic}\n")
    print("Step 1: Researching...")

    results = await orch.pipeline(
        steps=[
            ("researcher",  None),
            ("summariser",  "Summarise these research findings into key points:\n\n{previous}"),
            ("writer",      "Write a professional report based on these key points:\n\n{previous}"),
        ],
        initial_input=f"Research the following topic: {topic}",
    )

    for agent_id, msg in zip(["researcher", "summariser", "writer"], results):
        print(f"\n{'='*60}")
        print(f"[{agent_id.upper()}]\n{msg.content[:500]}{'...' if len(msg.content) > 500 else ''}")

    print(f"\n{'='*60}")
    print(f"Audit log written to: logs/multi_agent_audit.jsonl")
    print(f"Fleet summary: {orch.summary()}")


if __name__ == "__main__":
    asyncio.run(main())
