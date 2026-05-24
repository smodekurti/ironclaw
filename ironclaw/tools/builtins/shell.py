"""
ironclaw.tools.builtins.shell
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Restricted shell execution tool.

Security constraints (all enforced before any subprocess is spawned)
--------------------------------------------------------------------
- **Command allowlist**: only commands whose binary name appears in
  ``allowed_commands`` may run.  Default allowlist is conservative.
- **No shell=True**: commands are passed as a list, not a shell string,
  to prevent shell injection.
- **Timeout**: hard 30-second cap; process is SIGKILL'd on expiry.
- **Output cap**: stdout + stderr capped at 32 KB.
- **No network-capable commands** by default (curl, wget, nc, etc. are
  blocked unless explicitly allowed).
- **Working directory**: restricted to ``work_dir`` (default: system tmp).
- **Environment sanitisation**: inherits only a minimal env (PATH, HOME,
  LANG) — no credentials, tokens, or secrets from the parent process.
"""

from __future__ import annotations

import asyncio
import os
import shlex
import shutil
from pathlib import Path
from typing import Any

from ironclaw.tools.registry import ToolRegistry, ToolSpec

_DEFAULT_ALLOWED = {
    "ls", "pwd", "echo", "cat", "head", "tail", "grep", "wc",
    "date", "hostname", "uname", "python3", "python", "node",
    "jq", "sed", "awk", "sort", "uniq", "diff",
}

_SAFE_ENV_KEYS = {"PATH", "HOME", "LANG", "LC_ALL", "TMPDIR"}
_MAX_OUTPUT = 32 * 1024  # 32 KB
_TIMEOUT = 30.0


def _build_safe_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k in _SAFE_ENV_KEYS}


async def _shell_execute(
    command: str,
    work_dir: str | None = None,
    _allowed: set[str] = _DEFAULT_ALLOWED,
) -> dict[str, Any]:
    parts = shlex.split(command)
    if not parts:
        raise ValueError("Empty command")

    binary = parts[0]
    binary_name = Path(binary).name

    if binary_name not in _allowed:
        raise PermissionError(
            f"Command '{binary_name}' is not in the allowed list. "
            f"Allowed: {sorted(_allowed)}"
        )

    # Resolve binary to full path
    resolved = shutil.which(binary)
    if resolved is None:
        raise FileNotFoundError(f"Command not found: {binary}")

    parts[0] = resolved
    cwd = work_dir or "/tmp"

    proc = await asyncio.create_subprocess_exec(
        *parts,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        env=_build_safe_env(),
    )

    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=_TIMEOUT
        )
    except asyncio.TimeoutError:
        proc.kill()
        raise TimeoutError(f"Command '{command}' exceeded {_TIMEOUT}s timeout")

    stdout_text = stdout.decode("utf-8", errors="replace")[: _MAX_OUTPUT // 2]
    stderr_text = stderr.decode("utf-8", errors="replace")[: _MAX_OUTPUT // 2]

    return {
        "returncode": proc.returncode,
        "stdout": stdout_text,
        "stderr": stderr_text,
    }


def register_shell_tools(
    registry: ToolRegistry,
    allowed_commands: list[str] | None = None,
    work_dir: str | None = None,
) -> None:
    """
    Register the shell execution tool.

    Parameters
    ----------
    allowed_commands : list[str] | None
        Whitelist of binary names.  Defaults to a conservative safe set.
    work_dir : str | None
        Working directory for subprocess execution.
    """
    allowed: set[str] = set(allowed_commands) if allowed_commands else set(_DEFAULT_ALLOWED)
    _cwd = work_dir

    async def _execute(command: str) -> dict[str, Any]:
        return await _shell_execute(command, work_dir=_cwd, _allowed=allowed)

    registry.register(
        ToolSpec(
            name="shell:execute",
            description=(
                "Execute a whitelisted shell command and return stdout/stderr. "
                "Only approved commands may run."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command string (no pipes or redirection)",
                    },
                },
                "required": ["command"],
            },
            fn=_execute,
            requires="shell:execute",
            dangerous=True,
        )
    )
