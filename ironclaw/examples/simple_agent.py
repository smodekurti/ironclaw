"""
examples/simple_agent.py
~~~~~~~~~~~~~~~~~~~~~~~~
Minimal single-agent example with web search capability.

Run:
    export ANTHROPIC_API_KEY=sk-ant-...
    python examples/simple_agent.py
"""

import asyncio

from ironclaw import AgentBuilder


async def main() -> None:
    agent = (
        AgentBuilder("assistant")
        .with_name("IronClaw Assistant")
        .with_system_prompt(
            "You are a helpful assistant with access to web search. "
            "Always cite your sources."
        )
        .with_anthropic(model="claude-sonnet-4-6")
        .with_capabilities(["web:search", "web:fetch"])
        .with_web_tools()
        .with_guard(block_threshold=0.75)
        .with_audit_log("logs/simple_agent_audit.jsonl")
        .build()
    )

    questions = [
        "What is the latest version of Python?",
        "What are the key differences between async and sync programming?",
    ]

    for q in questions:
        print(f"\nQ: {q}")
        reply = await agent.run(q)
        print(f"A: {reply.content}")


if __name__ == "__main__":
    asyncio.run(main())
