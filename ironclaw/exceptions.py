"""
ironclaw.exceptions
~~~~~~~~~~~~~~~~~~~
IronClaw exception hierarchy.

All framework exceptions inherit from IronClawError so callers can catch
the entire family with a single except clause.
"""


class IronClawError(Exception):
    """Base class for all IronClaw exceptions."""


# --- Agent / Orchestrator ------------------------------------------------

class AgentNotFoundError(IronClawError):
    def __init__(self, agent_id: str) -> None:
        super().__init__(f"Agent not found: '{agent_id}'")
        self.agent_id = agent_id


class OrchestratorError(IronClawError):
    """Generic orchestrator error."""


# --- Security ------------------------------------------------------------

class InjectionDetectedError(IronClawError):
    """Raised when the PromptGuard blocks a message."""


class CapabilityDeniedError(IronClawError):
    """Raised when an agent attempts to call a tool it lacks capability for."""


class PolicyViolationError(IronClawError):
    """Raised by SecurityPolicy when a rule is violated."""


# --- Tools ---------------------------------------------------------------

class ToolNotFoundError(IronClawError):
    def __init__(self, name: str) -> None:
        super().__init__(f"Tool not found in registry: '{name}'")
        self.tool_name = name


class ToolSchemaError(IronClawError):
    """Raised when tool arguments fail JSON Schema validation."""


class SandboxError(IronClawError):
    """Raised when a sandboxed tool call fails unexpectedly."""


class ToolTimeoutError(IronClawError):
    """Raised when a tool call exceeds its timeout."""


# --- Providers -----------------------------------------------------------

class ProviderError(IronClawError):
    """Raised when an LLM provider call fails."""


class ProviderRateLimitError(ProviderError):
    """Raised on 429 / rate-limit responses from the LLM API."""


# --- Configuration -------------------------------------------------------

class ConfigError(IronClawError):
    """Raised on invalid or missing configuration."""
