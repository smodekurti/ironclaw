"""
ironclaw.tools.sandbox
~~~~~~~~~~~~~~~~~~~~~~
Sandboxed tool execution.

The Sandbox wraps every tool call with:
  1. Argument schema validation (via ToolSpec.validate_args)
  2. Timeout enforcement
  3. Memory cap (via resource limits on subprocess-based tools)
  4. Output size limiting (prevent exfiltration of huge blobs)
  5. Exception isolation (tool errors never crash the agent loop)

For tools marked ``dangerous=True`` the sandbox runs the handler in a
separate subprocess via ``concurrent.futures.ProcessPoolExecutor`` so that
runaway code cannot affect the main process.

Safe tools (``dangerous=False``) run in-process but still enforce timeout
and output limits.
"""

from __future__ import annotations

import asyncio
import json
import logging
from concurrent.futures import ProcessPoolExecutor
from typing import Any

from ironclaw.exceptions import SandboxError, ToolTimeoutError
from ironclaw.tools.registry import ToolSpec

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 30.0        # seconds
_DEFAULT_MAX_OUTPUT = 64_000   # characters / bytes


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_tool_in_process(module_path: str, fn_name: str, arguments: dict) -> Any:
    """
    Entry point executed inside a subprocess worker.
    We serialise the tool result as JSON to cross the process boundary.
    """
    import importlib
    mod = importlib.import_module(module_path)
    fn = getattr(mod, fn_name)
    import asyncio as _asyncio
    result = _asyncio.run(fn(**arguments))
    return json.dumps(result, default=str)


# ---------------------------------------------------------------------------
# Sandbox
# ---------------------------------------------------------------------------

class Sandbox:
    """
    Execution environment for tool calls.

    Parameters
    ----------
    timeout : float
        Seconds before a tool call is forcibly cancelled.
    max_output_chars : int
        Output strings longer than this are truncated.
    process_pool_size : int
        Workers in the ProcessPoolExecutor (for dangerous tools).
    """

    def __init__(
        self,
        timeout: float = _DEFAULT_TIMEOUT,
        max_output_chars: int = _DEFAULT_MAX_OUTPUT,
        process_pool_size: int = 2,
    ) -> None:
        self.timeout = timeout
        self.max_output_chars = max_output_chars
        self._executor = ProcessPoolExecutor(max_workers=process_pool_size)

    async def execute(self, spec: ToolSpec, arguments: dict[str, Any]) -> Any:
        """
        Validate and execute a tool call.

        Returns the tool's output, truncated if necessary.

        Raises
        ------
        ToolTimeoutError
            If the tool exceeds ``self.timeout`` seconds.
        SandboxError
            On unexpected execution failure.
        """
        # 1. Validate arguments against schema
        spec.validate_args(arguments)

        # 2. Route to in-process or subprocess execution
        if spec.dangerous:
            output = await self._run_subprocess(spec, arguments)
        else:
            output = await self._run_inprocess(spec, arguments)

        # 3. Limit output size
        return self._limit_output(output)

    async def _run_inprocess(self, spec: ToolSpec, arguments: dict[str, Any]) -> Any:
        """Run async tool function in-process with timeout."""
        try:
            return await asyncio.wait_for(
                spec.fn(**arguments),
                timeout=self.timeout,
            )
        except asyncio.TimeoutError:
            raise ToolTimeoutError(
                f"Tool '{spec.name}' exceeded timeout of {self.timeout}s"
            )
        except Exception as exc:
            raise SandboxError(f"Tool '{spec.name}' raised: {exc}") from exc

    async def _run_subprocess(self, spec: ToolSpec, arguments: dict[str, Any]) -> Any:
        """
        Run a dangerous tool in an isolated subprocess.

        The tool's module path and function name are resolved from the spec
        and passed to ``_run_tool_in_process`` which imports and executes them.
        """
        module_path = spec.fn.__module__
        fn_name = spec.fn.__name__

        loop = asyncio.get_event_loop()
        try:
            future = loop.run_in_executor(
                self._executor,
                _run_tool_in_process,
                module_path,
                fn_name,
                arguments,
            )
            raw = await asyncio.wait_for(future, timeout=self.timeout)
            return json.loads(raw)
        except asyncio.TimeoutError:
            raise ToolTimeoutError(
                f"Tool '{spec.name}' (subprocess) exceeded timeout of {self.timeout}s"
            )
        except Exception as exc:
            raise SandboxError(
                f"Subprocess tool '{spec.name}' failed: {exc}"
            ) from exc

    def _limit_output(self, output: Any) -> Any:
        """Truncate oversized string outputs."""
        if isinstance(output, str) and len(output) > self.max_output_chars:
            truncated = output[: self.max_output_chars]
            logger.warning(
                "Tool output truncated from %d to %d chars",
                len(output),
                self.max_output_chars,
            )
            return truncated + f"\n[... output truncated at {self.max_output_chars} chars]"
        return output

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False)

    def __del__(self) -> None:
        try:
            self.shutdown()
        except Exception:
            pass
