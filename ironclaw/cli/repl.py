"""
ironclaw.cli.repl
~~~~~~~~~~~~~~~~~
Interactive REPL for IronClaw agents.

Features
--------
- Coloured role indicators
- ``/quit``  — exit
- ``/clear`` — clear conversation history
- ``/history`` — show recent conversation
- ``/state``   — show shared state
- ``/audit``   — show last 10 audit entries
- ``/help``    — list commands
"""

from __future__ import annotations

import asyncio
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ironclaw.core.agent import Agent


_RESET = "\033[0m"
_BOLD = "\033[1m"
_CYAN = "\033[1;36m"
_GREEN = "\033[1;32m"
_YELLOW = "\033[1;33m"
_RED = "\033[1;31m"
_DIM = "\033[2m"

_COMMANDS = {
    "/quit":    "Exit the REPL",
    "/exit":    "Exit the REPL",
    "/clear":   "Clear conversation history",
    "/history": "Show recent conversation (last 10 messages)",
    "/state":   "Show current shared state",
    "/audit":   "Show last 10 audit log entries",
    "/help":    "Show this help",
}


class REPL:
    """
    Interactive command-line REPL for a single agent.

    Parameters
    ----------
    agent : Agent
        The agent to chat with.
    """

    def __init__(self, agent: "Agent") -> None:
        self.agent = agent

    async def run(self) -> None:
        self._banner()
        while True:
            try:
                user_input = input(f"{_CYAN}You{_RESET} › ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nBye!")
                break

            if not user_input:
                continue

            if user_input.startswith("/"):
                if self._handle_command(user_input):
                    break
                continue

            await self._chat(user_input)

    async def _chat(self, text: str) -> None:
        try:
            print(f"{_DIM}…thinking…{_RESET}", end="\r", flush=True)
            reply = await self.agent.run(text)
            print(" " * 20, end="\r")  # clear spinner
            print(f"{_GREEN}{self.agent.name}{_RESET} › {reply.content}\n")
        except Exception as exc:
            print(f"{_RED}Error:{_RESET} {exc}\n")

    def _handle_command(self, cmd: str) -> bool:
        """Returns True if the REPL should exit."""
        parts = cmd.strip().split()
        base = parts[0].lower()

        if base in ("/quit", "/exit"):
            print("Bye!")
            return True

        elif base == "/clear":
            self.agent.memory.clear()
            print(f"{_YELLOW}Conversation cleared.{_RESET}\n")

        elif base == "/history":
            msgs = self.agent.memory.history(limit=10)
            if not msgs:
                print(f"{_DIM}(empty){_RESET}\n")
            for m in msgs:
                role_col = _CYAN if m.role.value == "user" else _GREEN
                print(f"  {role_col}{m.role.value:12}{_RESET} {m.content[:120]}")
            print()

        elif base == "/state":
            if self.agent._context and self.agent._context.shared_state:
                snap = self.agent._context.shared_state.snapshot()
                if snap:
                    for k, v in snap.items():
                        print(f"  {_BOLD}{k}{_RESET}: {v}")
                else:
                    print(f"  {_DIM}(empty){_RESET}")
            else:
                print(f"  {_DIM}(no shared state){_RESET}")
            print()

        elif base == "/audit":
            if self.agent._context and self.agent._context.audit_log:
                entries = self.agent._context.audit_log.tail(10)
                for e in entries:
                    ts = e.get("ts", "")[-12:-1]
                    event = e.get("event", "?")
                    print(f"  {_DIM}{ts}{_RESET}  {_YELLOW}{event}{_RESET}")
            else:
                print(f"  {_DIM}(no audit log attached){_RESET}")
            print()

        elif base == "/help":
            print(f"\n{_BOLD}Available commands:{_RESET}")
            for cmd_name, desc in _COMMANDS.items():
                print(f"  {_CYAN}{cmd_name:<12}{_RESET}  {desc}")
            print()

        else:
            print(f"{_RED}Unknown command:{_RESET} {cmd}  (type /help)\n")

        return False

    def _banner(self) -> None:
        print(f"\n{_BOLD}IronClaw{_RESET} — Secure Agentic Framework")
        print(f"  Agent : {_GREEN}{self.agent.name}{_RESET} ({self.agent.agent_id})")
        print(f"  Model : {self.agent.provider.model}")
        caps = sorted(self.agent.capabilities.granted)
        print(f"  Caps  : {', '.join(caps) or '(none)'}")
        print(f"\nType {_CYAN}/help{_RESET} for commands, {_CYAN}/quit{_RESET} to exit.\n")
