"""
ironclaw.ace.schema
~~~~~~~~~~~~~~~~~~~
Agent Creation Engine — unified AgentSpec schema.

All three intake channels (CLI, Conversational Orchestrator, GUI Builder)
resolve to a single AgentSpec JSON object.  This module defines the
authoritative Pydantic models.

Example spec (minimal)
----------------------
::

    {
      "agentId": "support-bot",
      "persona": {
        "name": "Support Bot",
        "systemPrompt": "You are a helpful support agent."
      },
      "model": {
        "provider": "anthropic",
        "model": "claude-sonnet-4-6",
        "credentials": {"apiKey": "env:ANTHROPIC_API_KEY"}
      },
      "tools": [{"name": "web_search", "enabled": true}]
    }

Credential references
---------------------
Credentials are **never** embedded as plaintext.  Use one of:
  - ``"env:VAR_NAME"``   — resolved from the server's environment
  - ``"secret:path"``   — reserved for future secret-store integration
"""

from __future__ import annotations

import re
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Pydantic is optional (not in core deps) — provide a graceful fallback.
# ---------------------------------------------------------------------------

try:
    from pydantic import BaseModel, Field, field_validator, model_validator
    _PYDANTIC = True
except ImportError:  # pragma: no cover
    # Minimal shim so the module is importable without pydantic
    class BaseModel:  # type: ignore[no-redef]
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

        def model_dump(self, **_):
            return self.__dict__.copy()

        @classmethod
        def model_validate(cls, data):
            return cls(**data)

    def Field(default=None, **_):  # type: ignore[misc]
        return default

    def field_validator(*args, **kwargs):  # type: ignore[misc]
        def decorator(fn):
            return fn
        return decorator

    def model_validator(**kwargs):  # type: ignore[misc]
        def decorator(fn):
            return fn
        return decorator

    _PYDANTIC = False


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ProviderID(str, Enum):
    anthropic  = "anthropic"
    openai     = "openai"
    gemini     = "gemini"
    cohere     = "cohere"
    bedrock    = "bedrock"
    groq       = "groq"
    mistral    = "mistral"
    together   = "together"
    perplexity = "perplexity"
    xai        = "xai"
    fireworks  = "fireworks"
    deepseek   = "deepseek"
    cerebras   = "cerebras"
    lmstudio   = "lmstudio"
    ollama     = "ollama"


class MemoryType(str, Enum):
    in_memory = "in_memory"
    sqlite    = "sqlite"
    none      = "none"


class IsolationType(str, Enum):
    none       = "none"
    subprocess = "subprocess"
    docker     = "docker"


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------

class PersonaSpec(BaseModel):
    """Who the agent is."""
    name: str = Field(default="Assistant", description="Display name")
    systemPrompt: str = Field(
        default="You are a helpful assistant.",
        description="System / developer prompt injected at conversation start",
    )
    avatar: Optional[str] = Field(default=None, description="URL or emoji for UI display")

    if _PYDANTIC:
        @field_validator("name")
        @classmethod
        def _name_length(cls, v: str) -> str:
            if not 1 <= len(v) <= 128:
                raise ValueError("name must be 1–128 characters")
            return v

        @field_validator("systemPrompt")
        @classmethod
        def _prompt_length(cls, v: str) -> str:
            if len(v) > 32_000:
                raise ValueError("systemPrompt must not exceed 32 000 characters")
            return v


class ModelSpec(BaseModel):
    """Which LLM to use and how to authenticate."""
    provider: str = Field(description="Provider ID, e.g. 'anthropic', 'openai', 'ollama'")
    model: Optional[str] = Field(default=None, description="Model identifier; defaults to provider default")
    credentials: Dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Credential references — values must be 'env:VAR' or 'secret:path'. "
            "Never embed raw API keys here."
        ),
    )
    parameters: Dict[str, Any] = Field(
        default_factory=dict,
        description="Extra kwargs forwarded to the provider constructor (base_url, timeout, etc.)",
    )

    if _PYDANTIC:
        @field_validator("credentials")
        @classmethod
        def _validate_credentials(cls, creds: Dict[str, str]) -> Dict[str, str]:
            pattern = re.compile(r"^(env:[A-Z_][A-Z0-9_]*|secret:.+)$")
            for key, val in creds.items():
                if not pattern.match(val):
                    raise ValueError(
                        f"Credential '{key}' value must be 'env:VAR_NAME' or 'secret:path', "
                        f"got: {val!r}"
                    )
            return creds


class ToolConfig(BaseModel):
    """Configuration for a single tool bundle."""
    name: str = Field(description="Tool bundle name: web, filesystem, shell, or custom skill name")
    enabled: bool = Field(default=True)
    config: Dict[str, Any] = Field(
        default_factory=dict,
        description="Bundle-specific config (allowed_roots, allowed_commands, blocked_domains, etc.)",
    )


class MemorySpec(BaseModel):
    """Conversation memory backend."""
    type: MemoryType = Field(default=MemoryType.in_memory)
    dbPath: Optional[str] = Field(
        default=None,
        description="Required when type='sqlite'. Absolute path to the SQLite database file.",
    )
    sessionId: str = Field(default="default")
    maxTokens: Optional[int] = Field(
        default=None,
        description="Soft limit on memory context window (tokens). None = unlimited.",
    )

    if _PYDANTIC:
        @model_validator(mode="after")
        def _sqlite_needs_path(self) -> "MemorySpec":
            if self.type == MemoryType.sqlite and not self.dbPath:
                raise ValueError("dbPath is required when memory type is 'sqlite'")
            return self


class SecuritySpec(BaseModel):
    """Security policy applied to the agent."""
    capabilities: List[str] = Field(
        default_factory=list,
        description=(
            "Granted capability tokens. Supports wildcards: 'web:*', 'file:read', '*'. "
            "Empty list = no tools permitted."
        ),
    )
    guardBlockThreshold: float = Field(default=0.75, ge=0.0, le=1.0)
    guardWarnThreshold: float = Field(default=0.45, ge=0.0, le=1.0)
    maxPromptLength: int = Field(default=32_000, gt=0)
    hmacSecret: Optional[str] = Field(
        default=None,
        description="env: reference for audit log HMAC secret. e.g. 'env:IRONCLAW_HMAC_SECRET'",
    )
    auditLogPath: Optional[str] = Field(default=None)

    if _PYDANTIC:
        @model_validator(mode="after")
        def _threshold_order(self) -> "SecuritySpec":
            if self.guardWarnThreshold >= self.guardBlockThreshold:
                raise ValueError("guardWarnThreshold must be less than guardBlockThreshold")
            return self


class ResourceLimits(BaseModel):
    """Resource constraints for isolated execution."""
    cpuShares: int = Field(default=512, gt=0, description="Docker CPU shares (relative weight)")
    memoryMb: int = Field(default=512, gt=0, description="Memory limit in megabytes")
    diskMb: int = Field(default=1024, gt=0, description="Disk quota in megabytes")
    networkAccess: bool = Field(default=False, description="Allow outbound network from container")
    timeoutSeconds: int = Field(default=30, gt=0)


class IsolationSpec(BaseModel):
    """Execution isolation strategy."""
    type: IsolationType = Field(default=IsolationType.none)
    image: Optional[str] = Field(
        default=None,
        description="Docker image to use when type='docker'. e.g. 'python:3.12-slim'",
    )
    limits: ResourceLimits = Field(default_factory=ResourceLimits)
    workspaceMount: Optional[str] = Field(
        default=None,
        description="Host directory mounted into the container at /workspace",
    )

    if _PYDANTIC:
        @model_validator(mode="after")
        def _docker_needs_image(self) -> "IsolationSpec":
            if self.type == IsolationType.docker and not self.image:
                raise ValueError("image is required when isolation type is 'docker'")
            return self


class SchedulingSpec(BaseModel):
    """Optional autonomous scheduling."""
    enabled: bool = Field(default=False)
    cron: Optional[str] = Field(
        default=None,
        description="Cron expression for scheduled runs. e.g. '0 9 * * 1-5' (weekdays at 9am)",
    )
    triggerOnMessage: bool = Field(
        default=True,
        description="Run the agent when a gateway message arrives (default behavior)",
    )
    maxConcurrentRuns: int = Field(default=1, gt=0)

    if _PYDANTIC:
        @model_validator(mode="after")
        def _cron_when_enabled(self) -> "SchedulingSpec":
            if self.enabled and not self.cron and not self.triggerOnMessage:
                raise ValueError(
                    "When scheduling is enabled, either cron or triggerOnMessage must be set"
                )
            return self


class MetadataSpec(BaseModel):
    """Free-form metadata for UI, search, and auditing."""
    tags: List[str] = Field(default_factory=list)
    description: Optional[str] = Field(default=None, max_length=1024)
    owner: Optional[str] = Field(default=None, description="Owner email or username")
    environment: str = Field(
        default="production",
        description="Deployment environment label: development, staging, production",
    )
    createdBy: str = Field(
        default="user",
        description="Intake channel that created this spec: cli, gui, conversational",
    )
    version: str = Field(default="1.0.0")


# ---------------------------------------------------------------------------
# User profile spec (inline in AgentSpec — mirrors ironclaw.user.profile)
# ---------------------------------------------------------------------------

class UserProfileSpec(BaseModel):
    """
    User identity and behavioural contract embedded in an AgentSpec.

    This is a spec-file representation of ``ironclaw.user.profile.UserProfile``.
    When present, it takes precedence over the global profile at
    ``~/.ironclaw/user_profile.json``.

    Set ``useGlobal: true`` to load the global profile from disk instead of
    embedding it in the spec.
    """
    useGlobal: bool = Field(
        default=False,
        description=(
            "If true, load the profile from ~/.ironclaw/user_profile.json "
            "instead of using the fields below."
        ),
    )
    name: str = Field(default="")
    email: str = Field(default="")
    role: str = Field(default="")
    organization: str = Field(default="")
    timezone: str = Field(default="")
    language: str = Field(default="English")
    dos: List[str] = Field(default_factory=list, description="Things the agent must always do")
    donts: List[str] = Field(default_factory=list, description="Things the agent must never do")
    preferences: Dict[str, Any] = Field(
        default_factory=dict,
        description="tone, verbosity, format, expertise_level, etc.",
    )
    context: str = Field(default="", description="Free-form background about the user")
    goals: List[str] = Field(default_factory=list)

    def to_user_profile(self):
        """Convert to a ``ironclaw.user.profile.UserProfile`` instance."""
        from ironclaw.user.profile import UserProfile
        if self.useGlobal:
            from ironclaw.user.store import UserProfileStore
            return UserProfileStore.global_profile()
        return UserProfile(
            name=self.name,
            email=self.email,
            role=self.role,
            organization=self.organization,
            timezone=self.timezone,
            language=self.language,
            dos=self.dos,
            donts=self.donts,
            preferences=dict(self.preferences),
            context=self.context,
            goals=self.goals,
        )


# ---------------------------------------------------------------------------
# Root schema
# ---------------------------------------------------------------------------

_AGENT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{0,62}[a-z0-9]$|^[a-z0-9]$")


class AgentSpec(BaseModel):
    """
    Unified Agent Creation Engine specification.

    This is the single source of truth consumed by AgentProvisioner.
    All intake channels (CLI ``--file spec.json``, GUI form, Creator Agent
    conversational flow) produce an AgentSpec before any provisioning occurs.
    """

    agentId: str = Field(
        description=(
            "Unique agent identifier. Lowercase alphanumeric + hyphens, 1–64 chars. "
            "Used as the primary key in the agent registry."
        )
    )
    persona: PersonaSpec = Field(default_factory=PersonaSpec)
    model: ModelSpec = Field(
        description="LLM provider and model configuration"
    )
    tools: List[ToolConfig] = Field(default_factory=list)
    skills: List[str] = Field(
        default_factory=list,
        description="Skill names to load (must exist in the skill registry)",
    )
    userProfile: Optional[UserProfileSpec] = Field(
        default=None,
        description=(
            "User identity and behavioural rules. If omitted, the global profile at "
            "~/.ironclaw/user_profile.json is used automatically if it exists."
        ),
    )
    memory: MemorySpec = Field(default_factory=MemorySpec)
    security: SecuritySpec = Field(default_factory=SecuritySpec)
    isolation: IsolationSpec = Field(default_factory=IsolationSpec)
    scheduling: SchedulingSpec = Field(default_factory=SchedulingSpec)
    metadata: MetadataSpec = Field(default_factory=MetadataSpec)

    if _PYDANTIC:
        @field_validator("agentId")
        @classmethod
        def _valid_agent_id(cls, v: str) -> str:
            if not _AGENT_ID_RE.match(v):
                raise ValueError(
                    f"agentId must be lowercase alphanumeric + hyphens, 1–64 chars. Got: {v!r}"
                )
            return v

    # ------------------------------------------------------------------
    # Factory helpers
    # ------------------------------------------------------------------

    @classmethod
    def from_dict(cls, data: dict) -> "AgentSpec":
        """Construct from a plain dict (e.g. parsed JSON/TOML)."""
        if _PYDANTIC:
            return cls.model_validate(data)
        return cls(**data)

    @classmethod
    def minimal(
        cls,
        agent_id: str,
        provider: str,
        system_prompt: str = "You are a helpful assistant.",
        model: str | None = None,
        api_key_env: str | None = None,
    ) -> "AgentSpec":
        """
        Convenience constructor for simple agents.

        ::

            spec = AgentSpec.minimal("mybot", "anthropic", api_key_env="ANTHROPIC_API_KEY")
        """
        creds: Dict[str, str] = {}
        if api_key_env:
            env_ref = api_key_env if api_key_env.startswith("env:") else f"env:{api_key_env}"
            creds["apiKey"] = env_ref

        return cls(
            agentId=agent_id,
            persona=PersonaSpec(systemPrompt=system_prompt),
            model=ModelSpec(provider=provider, model=model, credentials=creds),
            memory=MemorySpec(type=MemoryType.in_memory)
        )

    def to_dict(self) -> dict:
        """Serialise to a plain dict (JSON-safe)."""
        if _PYDANTIC:
            return self.model_dump()
        return self.__dict__.copy()

    def generate_id(self) -> str:
        """Return a unique variant of agentId with a short UUID suffix."""
        suffix = uuid.uuid4().hex[:6]
        base = self.agentId[:57]  # leave room for -xxxxxx
        return f"{base}-{suffix}"

    def __repr__(self) -> str:
        provider = self.model.provider if hasattr(self, "model") else "?"
        return f"<AgentSpec id={self.agentId!r} provider={provider!r}>"
