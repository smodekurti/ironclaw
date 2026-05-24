"""
ironclaw.tools.registry
~~~~~~~~~~~~~~~~~~~~~~~
Tool registry with JSON-Schema validation.

Every callable tool is registered as a ToolSpec, which carries:
  - name        : unique snake_case identifier
  - description : shown to the LLM so it knows what the tool does
  - parameters  : JSON Schema for argument validation
  - fn          : the actual async callable
  - requires    : minimum capability string required (default: same as name)

The registry exposes ``schemas_for(capabilities)`` which returns only the
tool schemas the agent is permitted to see — limiting information leakage.
"""

from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

import jsonschema

from ironclaw.exceptions import ToolNotFoundError, ToolSchemaError
from ironclaw.tools.permissions import CapabilitySet

logger = logging.getLogger(__name__)


@dataclass
class ToolSpec:
    """Metadata + implementation for one callable tool."""

    name: str
    description: str
    parameters: dict[str, Any]            # JSON Schema object
    fn: Callable[..., Any]
    requires: str = ""                     # capability string; defaults to name
    dangerous: bool = False                # hint to the sandbox

    def __post_init__(self) -> None:
        if not self.requires:
            self.requires = self.name

    def validate_args(self, arguments: dict[str, Any]) -> None:
        """Raise ToolSchemaError if *arguments* don't match the schema."""
        try:
            jsonschema.validate(instance=arguments, schema=self.parameters)
        except jsonschema.ValidationError as exc:
            raise ToolSchemaError(
                f"Tool '{self.name}' argument validation failed: {exc.message}"
            ) from exc


class ToolRegistry:
    """
    Central registry for all tools available to agents.

    Usage
    -----
    ::

        registry = ToolRegistry()

        @registry.tool(
            name="web_search",
            description="Search the web and return top results.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "max_results": {"type": "integer", "default": 5},
                },
                "required": ["query"],
            },
            requires="web:search",
        )
        async def web_search(query: str, max_results: int = 5) -> list[dict]:
            ...
    """

    def __init__(self) -> None:
        self._specs: dict[str, ToolSpec] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, spec: ToolSpec) -> None:
        """Register a ToolSpec directly."""
        if spec.name in self._specs:
            logger.warning("Overwriting existing tool '%s'", spec.name)
        self._specs[spec.name] = spec
        logger.debug("Tool registered: %s (requires=%s)", spec.name, spec.requires)

    def tool(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        requires: str = "",
        dangerous: bool = False,
    ) -> Callable:
        """Decorator factory for registering tools inline."""

        def decorator(fn: Callable) -> Callable:
            if not inspect.iscoroutinefunction(fn):
                raise TypeError(
                    f"Tool '{name}': handler must be an async function (async def)"
                )
            spec = ToolSpec(
                name=name,
                description=description,
                parameters=parameters,
                fn=fn,
                requires=requires or name,
                dangerous=dangerous,
            )
            self.register(spec)
            return fn

        return decorator

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def get(self, name: str) -> ToolSpec | None:
        return self._specs.get(name)

    def require(self, name: str) -> ToolSpec:
        spec = self.get(name)
        if spec is None:
            raise ToolNotFoundError(name)
        return spec

    # ------------------------------------------------------------------
    # Schema export
    # ------------------------------------------------------------------

    def schemas_for(self, capabilities: CapabilitySet) -> list[dict[str, Any]]:
        """
        Return OpenAI-compatible tool schemas for all tools the agent can use.

        Only tools whose ``requires`` capability is granted are included —
        the agent cannot even *see* tools it cannot call.
        """
        schemas = []
        for spec in self._specs.values():
            if capabilities.allows(spec.requires):
                schemas.append(self._to_openai_schema(spec))
        return schemas

    def all_schemas(self) -> list[dict[str, Any]]:
        """Return schemas for all registered tools (admin use)."""
        return [self._to_openai_schema(s) for s in self._specs.values()]

    @staticmethod
    def _to_openai_schema(spec: ToolSpec) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.parameters,
            },
        }

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def tool_names(self) -> list[str]:
        return sorted(self._specs.keys())

    def __len__(self) -> int:
        return len(self._specs)

    def __repr__(self) -> str:
        return f"<ToolRegistry tools={self.tool_names}>"
