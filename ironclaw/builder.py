"""
ironclaw.builder
~~~~~~~~~~~~~~~~
Fluent AgentBuilder — assembles an Agent from composable pieces.

Usage
-----
::

    from ironclaw import AgentBuilder

    agent = (
        AgentBuilder("researcher")
        .with_name("Research Assistant")
        .with_system_prompt("You are a diligent research assistant.")
        .with_anthropic(model="claude-sonnet-4-6")
        .with_capabilities(["web:search", "web:fetch"])
        .with_web_tools()
        .with_audit_log("logs/audit.jsonl", hmac_secret="s3cr3t")
        .build()
    )
"""

from __future__ import annotations

import pathlib

from ironclaw.core.agent import Agent
from ironclaw.memory.conversation import InMemoryConversation, SQLiteConversation
from ironclaw.security.audit import AuditLog
from ironclaw.security.guard import PromptGuard
from ironclaw.tools.permissions import CapabilitySet
from ironclaw.tools.registry import ToolRegistry
from ironclaw.tools.sandbox import Sandbox

_DEFAULT_MEMORY_ROOT = pathlib.Path.home() / ".ironclaw" / "memory"


class AgentBuilder:
    """Fluent builder for Agent instances."""

    def __init__(self, agent_id: str) -> None:
        self._id = agent_id
        self._name = agent_id
        self._system_prompt = "You are a helpful assistant."
        self._provider = None
        self._capabilities: list[str] = []
        self._registry = ToolRegistry()
        self._memory = None   # resolved in build() — defaults to SQLite
        self._guard = PromptGuard()
        self._sandbox = Sandbox()
        self._audit_log: AuditLog | None = None
        self._max_iterations = 10
        self._user_profile = None  # UserProfile | None

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    def with_name(self, name: str) -> "AgentBuilder":
        self._name = name
        return self

    def with_system_prompt(self, prompt: str) -> "AgentBuilder":
        self._system_prompt = prompt
        return self

    def with_max_iterations(self, n: int) -> "AgentBuilder":
        self._max_iterations = n
        return self

    # ------------------------------------------------------------------
    # Providers
    # ------------------------------------------------------------------

    def with_anthropic(
        self,
        model: str = "claude-sonnet-4-6",
        api_key: str | None = None,
    ) -> "AgentBuilder":
        from ironclaw.providers.anthropic import AnthropicProvider
        self._provider = AnthropicProvider(api_key=api_key, model=model)
        return self

    def with_openai(
        self,
        model: str = "gpt-4o",
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> "AgentBuilder":
        from ironclaw.providers.openai import OpenAIProvider
        self._provider = OpenAIProvider(api_key=api_key, model=model, base_url=base_url)
        return self

    def with_ollama(
        self,
        model: str = "llama3",
        base_url: str = "http://localhost:11434/v1",
    ) -> "AgentBuilder":
        from ironclaw.providers.ollama import OllamaProvider
        self._provider = OllamaProvider(model=model, base_url=base_url)
        return self

    def with_provider(self, provider) -> "AgentBuilder":
        """Use any custom LLMProvider instance."""
        self._provider = provider
        return self

    # ------------------------------------------------------------------
    # Capabilities
    # ------------------------------------------------------------------

    def with_capabilities(self, grants: list[str]) -> "AgentBuilder":
        self._capabilities.extend(grants)
        return self

    def with_all_capabilities(self) -> "AgentBuilder":
        self._capabilities = ["*"]
        return self

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

    def with_web_tools(self, blocked_domains: list[str] | None = None) -> "AgentBuilder":
        from ironclaw.tools.builtins.web import register_web_tools
        register_web_tools(self._registry, blocked_domains=blocked_domains)
        return self

    def with_filesystem_tools(self, allowed_roots: list[str] | None = None) -> "AgentBuilder":
        from ironclaw.tools.builtins.filesystem import register_filesystem_tools
        register_filesystem_tools(self._registry, allowed_roots=allowed_roots)
        return self

    def with_shell_tools(
        self,
        allowed_commands: list[str] | None = None,
        work_dir: str | None = None,
    ) -> "AgentBuilder":
        from ironclaw.tools.builtins.shell import register_shell_tools
        register_shell_tools(self._registry, allowed_commands=allowed_commands, work_dir=work_dir)
        return self

    def with_tool_registry(self, registry: ToolRegistry) -> "AgentBuilder":
        self._registry = registry
        return self

    def with_skill(self, skill) -> "AgentBuilder":
        """
        Load a skill into the agent.

        *skill* can be:
        - a ``SkillManifest`` instance (already loaded)
        - a string skill name (looked up in the built-in registry)
        - a path to a SKILL.md file
        """
        from ironclaw.skills.manifest import SkillManifest
        if isinstance(skill, str):
            # Could be a name or a path
            import pathlib
            p = pathlib.Path(skill)
            if p.exists():
                manifest = SkillManifest.from_file(str(p))
            else:
                # Look up in built-in registry
                from ironclaw.skills.registry import SkillRegistry
                builtin_dir = pathlib.Path(__file__).parent / "skills" / "builtin"
                reg = SkillRegistry()
                reg.add_directory(str(builtin_dir))
                manifest = reg.get(skill)
                if manifest is None:
                    raise ValueError(f"Skill '{skill}' not found in built-in registry")
        elif isinstance(skill, SkillManifest):
            manifest = skill
        else:
            raise TypeError(f"Expected str or SkillManifest, got {type(skill)}")

        # Inject skill context into the system prompt
        skill_block = (
            f"\n\n## Skill: {manifest.name}\n"
            f"{manifest.description}\n\n"
            f"### Instructions\n{manifest.body}"
        )
        self._system_prompt += skill_block
        return self

    # ------------------------------------------------------------------
    # Security
    # ------------------------------------------------------------------

    def with_guard(
        self,
        block_threshold: float = 0.75,
        warn_threshold: float = 0.45,
        max_length: int = 32_000,
    ) -> "AgentBuilder":
        self._guard = PromptGuard(
            block_threshold=block_threshold,
            warn_threshold=warn_threshold,
            max_length=max_length,
        )
        return self

    def with_audit_log(
        self,
        path: str | None = None,
        hmac_secret: str | None = None,
    ) -> "AgentBuilder":
        self._audit_log = AuditLog(path=path, hmac_secret=hmac_secret)
        return self

    def with_sandbox(
        self,
        timeout: float = 30.0,
        max_output_chars: int = 64_000,
    ) -> "AgentBuilder":
        self._sandbox = Sandbox(timeout=timeout, max_output_chars=max_output_chars)
        return self

    # ------------------------------------------------------------------
    # User profile
    # ------------------------------------------------------------------

    def with_user_profile(self, profile=None) -> "AgentBuilder":
        """
        Attach a UserProfile to this agent.

        The profile is automatically injected into the system prompt so the
        agent always knows who it is talking to and must respect the user's
        dos, don'ts, and preferences.

        *profile* can be:
        - A ``UserProfile`` instance
        - ``None`` — loads the global profile from ``~/.ironclaw/user_profile.json``
        - ``"auto"`` — same as None (explicit opt-in to auto-loading)
        - A path string to a custom JSON file
        """
        if profile is None or profile == "auto":
            from ironclaw.user.store import UserProfileStore
            self._user_profile = UserProfileStore.global_profile()
        elif isinstance(profile, str):
            from ironclaw.user.profile import UserProfile
            import json
            self._user_profile = UserProfile.from_dict(
                json.loads(pathlib.Path(profile).read_text())
            )
        else:
            self._user_profile = profile
        return self

    def without_user_profile(self) -> "AgentBuilder":
        """Explicitly opt out of user profile injection."""
        self._user_profile = False  # False = opted out
        return self

    # ------------------------------------------------------------------
    # Memory
    # ------------------------------------------------------------------

    def with_memory(self, memory) -> "AgentBuilder":
        self._memory = memory
        return self

    def with_sqlite_memory(
        self,
        db_path: str | None = None,
        session_id: str = "default",
    ) -> "AgentBuilder":
        db = db_path or str(_DEFAULT_MEMORY_ROOT / f"{self._id}.db")
        self._memory = SQLiteConversation(db_path=db, session_id=session_id, agent_id=self._id)
        return self

    def with_in_memory(self) -> "AgentBuilder":
        """Opt into ephemeral in-memory conversation (not persisted)."""
        self._memory = InMemoryConversation()
        return self

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build(self) -> Agent:
        if self._provider is None:
            raise ValueError(
                "No LLM provider configured. Call .with_anthropic(), .with_openai(), etc."
            )

        # ---- Default memory: SQLite at ~/.ironclaw/memory/{agent_id}.db ----
        if self._memory is None:
            _DEFAULT_MEMORY_ROOT.mkdir(parents=True, exist_ok=True)
            db_path = str(_DEFAULT_MEMORY_ROOT / f"{self._id}.db")
            memory = SQLiteConversation(
                db_path=db_path,
                session_id="default",
                agent_id=self._id,
            )
        else:
            memory = self._memory

        # ---- User profile injection ----
        system_prompt = self._system_prompt
        if self._user_profile is None:
            # Auto-load global profile if one exists
            from ironclaw.user.store import UserProfileStore
            profile = UserProfileStore.global_profile()
            if not profile.is_empty():
                block = profile.to_system_prompt_block()
                system_prompt = system_prompt + "\n\n" + block
        elif self._user_profile is not False:
            # Explicit profile was supplied
            block = self._user_profile.to_system_prompt_block()
            if block:
                system_prompt = system_prompt + "\n\n" + block

        return Agent(
            agent_id=self._id,
            name=self._name,
            system_prompt=system_prompt,
            provider=self._provider,
            tools=self._registry,
            capabilities=CapabilitySet(self._capabilities),
            memory=memory,
            guard=self._guard,
            sandbox=self._sandbox,
            max_iterations=self._max_iterations,
        )
