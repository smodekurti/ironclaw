"""
ironclaw.ace.provisioner
~~~~~~~~~~~~~~~~~~~~~~~~
Agent Creation Engine — five-stage provisioning pipeline.

Stages
------
1. **validate**   — schema validation, ID collision check
2. **workspace**  — create per-agent directories and config files
3. **memory**     — initialise the memory backend
4. **isolation**  — set up the execution sandbox (subprocess or Docker)
5. **register**   — add the agent to the live registry, return Agent instance

Usage
-----
::

    from ironclaw.ace.schema import AgentSpec
    from ironclaw.ace.provisioner import AgentProvisioner

    spec = AgentSpec.minimal("mybot", "anthropic", api_key_env="ANTHROPIC_API_KEY")
    provisioner = AgentProvisioner()
    agent = await provisioner.provision(spec)
"""

from __future__ import annotations

import asyncio
import logging
import os
import pathlib
import json
import textwrap
from typing import Any, Callable, Dict, Optional

from ironclaw.ace.schema import AgentSpec, IsolationType, MemoryType

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Result object
# ---------------------------------------------------------------------------

class ProvisionResult:
    """Returned by AgentProvisioner.provision()."""

    def __init__(
        self,
        *,
        agent_id: str,
        agent,                          # ironclaw.core.agent.Agent
        spec: AgentSpec,
        workspace: pathlib.Path,
        warnings: list[str],
    ) -> None:
        self.agent_id  = agent_id
        self.agent     = agent
        self.spec      = spec
        self.workspace = workspace
        self.warnings  = warnings
        self.success   = True

    def __repr__(self) -> str:
        return f"<ProvisionResult id={self.agent_id!r} warnings={self.warnings}>"


# ---------------------------------------------------------------------------
# Credential resolver
# ---------------------------------------------------------------------------

def resolve_credential(ref: str, env: Dict[str, str] | None = None) -> str:
    """
    Resolve a credential reference to its actual value.

    Supports:
    - ``env:VAR_NAME``  — reads from ``os.environ`` (or supplied *env* dict)
    - ``secret:path``   — reserved; raises NotImplementedError for now
    """
    env = env or os.environ  # type: ignore[assignment]

    if ref.startswith("env:"):
        var = ref[4:]
        val = env.get(var)
        if not val:
            raise EnvironmentError(
                f"Credential reference '{ref}' requires environment variable {var!r} "
                f"but it is not set."
            )
        return val

    if ref.startswith("secret:"):
        raise NotImplementedError(
            "secret: credential references are not yet supported. "
            "Use env: references for now."
        )

    raise ValueError(f"Unknown credential reference format: {ref!r}")


# ---------------------------------------------------------------------------
# Provisioner
# ---------------------------------------------------------------------------

class AgentProvisioner:
    """
    Provisions agents from AgentSpec objects.

    Parameters
    ----------
    workspace_root:
        Base directory for per-agent workspaces.
        Defaults to ``~/.ironclaw/agents``.
    registry:
        Running agent registry (``{agent_id: Agent}``).  If None, a fresh
        dict is used — useful for standalone use and testing.
    on_progress:
        Optional callback ``fn(stage: str, message: str)`` called as each
        stage begins, for streaming progress to callers.
    """

    def __init__(
        self,
        workspace_root: str | None = None,
        registry: Dict[str, Any] | None = None,
        on_progress: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        self._root = pathlib.Path(workspace_root or os.path.expanduser("~/.ironclaw/agents"))
        self._root.mkdir(parents=True, exist_ok=True)
        self._registry: Dict[str, Any] = registry if registry is not None else {}
        self._on_progress = on_progress or (lambda stage, msg: None)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def provision(self, spec: AgentSpec) -> ProvisionResult:
        """
        Run all five provisioning stages and return a ProvisionResult.

        Raises
        ------
        ValueError
            If validation fails or the agent ID is already registered.
        """
        warnings: list[str] = []

        # Stage 1 — Validate
        self._progress("validate", f"Validating spec for agent '{spec.agentId}'")
        self._stage_validate(spec)

        # Stage 2 — Workspace
        self._progress("workspace", f"Creating workspace for '{spec.agentId}'")
        workspace = self._stage_workspace(spec)

        # Stage 3 — Memory
        self._progress("memory", f"Initialising {spec.memory.type.value} memory backend")
        memory = self._stage_memory(spec, workspace)

        # Stage 4 — Isolation
        self._progress("isolation", f"Setting up {spec.isolation.type.value} isolation")
        sandbox = await self._stage_isolation(spec, workspace, warnings)

        # Stage 5 — Register
        self._progress("register", f"Building and registering agent '{spec.agentId}'")
        agent = self._stage_register(spec, memory, sandbox, warnings)

        result = ProvisionResult(
            agent_id=spec.agentId,
            agent=agent,
            spec=spec,
            workspace=workspace,
            warnings=warnings,
        )
        log.info("Provisioned agent '%s' with %d warning(s)", spec.agentId, len(warnings))
        return result

    async def dry_run(self, spec: AgentSpec) -> Dict[str, Any]:
        """
        Validate and plan without actually creating any resources.

        Returns a dict describing what *would* be created.
        """
        self._stage_validate(spec)  # raises on error
        workspace = self._root / spec.agentId
        return {
            "agentId":         spec.agentId,
            "provider":        spec.model.provider,
            "model":           spec.model.model,
            "memoryType":      spec.memory.type.value,
            "isolationType":   spec.isolation.type.value,
            "toolBundles":     [t.name for t in spec.tools if t.enabled],
            "skills":          spec.skills,
            "capabilities":    spec.security.capabilities,
            "workspacePath":   str(workspace),
            "alreadyExists":   spec.agentId in self._registry,
            "warnings":        self._preflight_warnings(spec),
        }

    def deprovision(self, agent_id: str) -> bool:
        """Remove an agent from the registry (does not delete workspace files)."""
        if agent_id not in self._registry:
            return False
        del self._registry[agent_id]
        log.info("Deprovisioned agent '%s'", agent_id)
        return True

    # ------------------------------------------------------------------
    # Stage implementations
    # ------------------------------------------------------------------

    def _stage_validate(self, spec: AgentSpec) -> None:
        """Stage 1: schema + business rule validation."""
        if spec.agentId in self._registry:
            raise ValueError(
                f"Agent '{spec.agentId}' is already registered. "
                "Use a different ID or deprovision the existing agent first."
            )
        # Provider must be known
        from ironclaw.providers.factory import PROVIDER_CATALOGUE
        if spec.model.provider not in PROVIDER_CATALOGUE:
            raise ValueError(
                f"Unknown provider '{spec.model.provider}'. "
                f"Supported: {sorted(PROVIDER_CATALOGUE.keys())}"
            )
        # Credential references must resolve (warn only — don't fail at spec time)
        for key, ref in spec.model.credentials.items():
            if ref.startswith("env:"):
                var = ref[4:]
                if not os.environ.get(var):
                    log.warning(
                        "Credential '%s' references env var '%s' which is not currently set.",
                        key, var,
                    )

    def _stage_workspace(self, spec: AgentSpec) -> pathlib.Path:
        """Stage 2: create per-agent workspace directory tree."""
        ws = self._root / spec.agentId
        ws.mkdir(parents=True, exist_ok=True)
        (ws / "logs").mkdir(exist_ok=True)
        (ws / "memory").mkdir(exist_ok=True)
        (ws / "skills").mkdir(exist_ok=True)

        # Write the spec to disk for auditing / restart
        spec_path = ws / "spec.json"
        spec_path.write_text(json.dumps(spec.to_dict(), indent=2, default=str))
        log.debug("Workspace created at %s", ws)
        return ws

    def _stage_memory(self, spec: AgentSpec, workspace: pathlib.Path):
        """Stage 3: construct the memory backend."""
        mem_spec = spec.memory

        if mem_spec.type == MemoryType.none:
            from ironclaw.memory.conversation import InMemoryConversation
            return InMemoryConversation()  # ephemeral, no state saved

        if mem_spec.type == MemoryType.in_memory:
            from ironclaw.memory.conversation import InMemoryConversation
            return InMemoryConversation()

        if mem_spec.type == MemoryType.sqlite:
            from ironclaw.memory.conversation import SQLiteConversation
            import pathlib
            default_db = pathlib.Path.home() / ".ironclaw" / "memory" / f"{spec.agentId}.db"
            db_path = mem_spec.dbPath or str(default_db)
            return SQLiteConversation(
                db_path=db_path,
                session_id=mem_spec.sessionId,
                agent_id=spec.agentId,
            )

        raise ValueError(f"Unknown memory type: {mem_spec.type}")

    async def _stage_isolation(
        self,
        spec: AgentSpec,
        workspace: pathlib.Path,
        warnings: list[str],
    ):
        """Stage 4: configure sandbox / isolation."""
        from ironclaw.tools.sandbox import Sandbox
        iso = spec.isolation

        if iso.type == IsolationType.none:
            return Sandbox(timeout=float(iso.limits.timeoutSeconds))

        if iso.type == IsolationType.subprocess:
            return Sandbox(timeout=float(iso.limits.timeoutSeconds))

        if iso.type == IsolationType.docker:
            # Check Docker availability
            try:
                proc = await asyncio.create_subprocess_exec(
                    "docker", "info",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await proc.wait()
                docker_ok = proc.returncode == 0
            except FileNotFoundError:
                docker_ok = False

            if not docker_ok:
                warnings.append(
                    "Docker isolation requested but Docker is not available. "
                    "Falling back to subprocess isolation."
                )
                return Sandbox(timeout=float(iso.limits.timeoutSeconds))

            # Docker is available — return a Docker-aware sandbox wrapper
            return _DockerSandbox(
                image=iso.image or "python:3.12-slim",
                workspace=str(workspace),
                limits=iso.limits,
            )

        raise ValueError(f"Unknown isolation type: {iso.type}")

    def _stage_register(self, spec: AgentSpec, memory, sandbox, warnings: list[str]):
        """Stage 5: build the Agent and add it to the registry."""
        from ironclaw.builder import AgentBuilder
        from ironclaw.providers.factory import make_provider

        # Resolve credentials
        resolved_creds: Dict[str, str] = {}
        for key, ref in spec.model.credentials.items():
            try:
                resolved_creds[key] = resolve_credential(ref)
            except EnvironmentError as exc:
                warnings.append(str(exc))

        # Build provider
        provider_kwargs = dict(spec.model.parameters)
        if "apiKey" in resolved_creds:
            provider_kwargs["api_key"] = resolved_creds["apiKey"]
        if "baseUrl" in resolved_creds:
            provider_kwargs["base_url"] = resolved_creds["baseUrl"]

        provider = make_provider(
            spec.model.provider,
            model=spec.model.model,
            **provider_kwargs,
        )

        # Build agent via fluent builder
        builder = (
            AgentBuilder(spec.agentId)
            .with_name(spec.persona.name)
            .with_system_prompt(spec.persona.systemPrompt)
            .with_provider(provider)
            .with_capabilities(spec.security.capabilities)
            .with_memory(memory)
            .with_sandbox(timeout=float(spec.isolation.limits.timeoutSeconds))
        )

        # User profile
        if spec.userProfile is not None:
            user_profile = spec.userProfile.to_user_profile()
            builder = builder.with_user_profile(user_profile)
        # else: builder will auto-load global profile at build() time

        # Audit log
        if spec.security.auditLogPath:
            hmac_secret: str | None = None
            if spec.security.hmacSecret:
                try:
                    hmac_secret = resolve_credential(spec.security.hmacSecret)
                except Exception:
                    pass
            builder = builder.with_audit_log(
                path=spec.security.auditLogPath,
                hmac_secret=hmac_secret,
            )

        # Guard
        builder = builder.with_guard(
            block_threshold=spec.security.guardBlockThreshold,
            warn_threshold=spec.security.guardWarnThreshold,
            max_length=spec.security.maxPromptLength,
        )

        # Tool bundles
        for tool_cfg in spec.tools:
            if not tool_cfg.enabled:
                continue
            cfg = tool_cfg.config
            if tool_cfg.name == "web":
                builder = builder.with_web_tools(blocked_domains=cfg.get("blockedDomains"))
            elif tool_cfg.name == "filesystem":
                builder = builder.with_filesystem_tools(allowed_roots=cfg.get("allowedRoots"))
            elif tool_cfg.name == "shell":
                builder = builder.with_shell_tools(
                    allowed_commands=cfg.get("allowedCommands"),
                    work_dir=cfg.get("workDir"),
                )
            else:
                warnings.append(
                    f"Unknown tool bundle '{tool_cfg.name}' — skipped. "
                    "Custom tool bundles must be registered before provisioning."
                )

        # Skills
        if spec.skills:
            try:
                from ironclaw.skills.registry import SkillRegistry
                skill_reg = SkillRegistry()
                skill_reg.add_directory(
                    str(pathlib.Path(__file__).parent.parent / "skills" / "builtin")
                )
                for skill_name in spec.skills:
                    skill = skill_reg.get(skill_name)
                    if skill is None:
                        warnings.append(f"Skill '{skill_name}' not found — skipped.")
                    else:
                        builder = builder.with_skill(skill)
            except Exception as exc:
                warnings.append(f"Could not load skills: {exc}")

        agent = builder.build()
        self._registry[spec.agentId] = agent
        return agent

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _progress(self, stage: str, message: str) -> None:
        log.debug("[ACE:%s] %s", stage, message)
        self._on_progress(stage, message)

    def _preflight_warnings(self, spec: AgentSpec) -> list[str]:
        """Pre-flight checks for dry_run."""
        warnings: list[str] = []
        for key, ref in spec.model.credentials.items():
            if ref.startswith("env:") and not os.environ.get(ref[4:]):
                warnings.append(f"env var {ref[4:]!r} (for credential '{key}') is not set")
        if spec.isolation.type == IsolationType.docker:
            warnings.append(
                "Docker availability will be checked at provision time"
            )
        return warnings


# ---------------------------------------------------------------------------
# Docker sandbox wrapper (thin shim — real Docker integration is pluggable)
# ---------------------------------------------------------------------------

class _DockerSandbox:
    """
    Minimal Docker-aware sandbox wrapper returned by the isolation stage.
    Delegates dangerous tool execution to ``docker run`` subprocesses.

    Implements the same ``execute(spec, arguments)`` interface as
    ``ironclaw.tools.sandbox.Sandbox`` so that Agent._execute_tool()
    can call it without knowing the isolation strategy.
    """

    def __init__(self, image: str, workspace: str, limits) -> None:
        self.image     = image
        self.workspace = workspace
        self.limits    = limits
        self.timeout   = float(limits.timeoutSeconds)
        self.max_output_chars = 64_000

    async def execute(self, spec, arguments: dict) -> Any:
        """
        Execute a tool inside a Docker container with hard resource limits.

        The container receives a JSON payload on stdin describing the tool
        call, runs it through a minimal Python dispatcher, and returns a
        JSON result on stdout.  This provides:

        - Memory cap (``--memory``)
        - CPU weight (``--cpu-shares``)
        - Network isolation (``--network none`` unless ``networkAccess=True``)
        - PID limit (``--pids-limit``)
        - No privilege escalation (``--security-opt no-new-privileges``)
        - Execution timeout (``asyncio.wait_for``)

        Falls back to the standard in-process ``Sandbox`` if Docker is not
        available on the host, logging a warning in that case.
        """
        import shutil as _shutil

        # Fast-path: if docker binary isn't on PATH, fall back immediately.
        if not _shutil.which("docker"):
            log.warning(
                "_DockerSandbox: docker not found on PATH, falling back to in-process Sandbox"
            )
            from ironclaw.tools.sandbox import Sandbox
            fallback = Sandbox(timeout=self.timeout, max_output_chars=self.max_output_chars)
            return await fallback.execute(spec, arguments)

        payload = json.dumps({"tool_name": spec.name, "arguments": arguments})

        # Inline Python executor injected as a -c script into the container.
        # Keeps zero external dependencies — only stdlib required.
        executor = textwrap.dedent("""\
            import sys, json, subprocess, os, shlex

            raw = sys.stdin.read()
            payload = json.loads(raw)
            tool_name = payload.get("tool_name", "")
            args = payload.get("arguments", {})
            result = None

            # Dispatch heuristics based on tool name patterns.
            # Tools that escape the pattern fall through to a safe echo.
            name_lower = tool_name.lower()

            if any(k in name_lower for k in ("shell", "exec", "run", "bash", "cmd")):
                cmd = args.get("command") or args.get("cmd") or args.get("script") or ""
                if isinstance(cmd, list):
                    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
                else:
                    proc = subprocess.run(
                        cmd, shell=True, capture_output=True, text=True, timeout=25
                    )
                result = proc.stdout
                if proc.returncode != 0:
                    result += proc.stderr

            elif any(k in name_lower for k in ("read", "cat", "open", "load")):
                path = args.get("path") or args.get("file") or args.get("filename") or ""
                try:
                    with open(path) as fh:
                        result = fh.read()
                except Exception as e:
                    result = f"Error reading {path!r}: {e}"

            elif any(k in name_lower for k in ("write", "save", "create")):
                path = args.get("path") or args.get("file") or args.get("filename") or ""
                content = args.get("content") or args.get("text") or ""
                try:
                    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
                    with open(path, "w") as fh:
                        fh.write(content)
                    result = f"Written {len(content)} bytes to {path!r}"
                except Exception as e:
                    result = f"Error writing {path!r}: {e}"

            elif any(k in name_lower for k in ("list", "ls", "dir")):
                path = args.get("path") or args.get("directory") or "."
                try:
                    entries = os.listdir(path)
                    result = "\\n".join(sorted(entries))
                except Exception as e:
                    result = f"Error listing {path!r}: {e}"

            else:
                result = (
                    f"Tool '{tool_name}' executed in Docker sandbox. "
                    f"Arguments: {json.dumps(args)}"
                )

            out = json.dumps({"result": str(result) if result is not None else ""})
            sys.stdout.write(out)
        """)

        # Build docker run command.
        docker_cmd: list[str] = [
            "docker", "run",
            "--rm",
            "--interactive",
            "--memory", f"{self.limits.memoryMb}m",
            "--memory-swap", f"{self.limits.memoryMb}m",   # disable swap
            "--cpu-shares", str(self.limits.cpuShares),
            "--pids-limit", "64",
            "--security-opt", "no-new-privileges",
        ]

        if not self.limits.networkAccess:
            docker_cmd += ["--network", "none"]

        if self.workspace:
            docker_cmd += [
                "--volume", f"{self.workspace}:/workspace:rw",
                "--workdir", "/workspace",
            ]

        docker_cmd += [self.image, "python3", "-c", executor]

        try:
            proc = await asyncio.create_subprocess_exec(
                *docker_cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(input=payload.encode()),
                    timeout=self.timeout,
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                raise RuntimeError(
                    f"Docker execution timed out after {self.timeout:.0f}s "
                    f"(tool={spec.name!r})"
                )

        except FileNotFoundError:
            # docker binary disappeared between the which() check and now — very rare.
            log.warning("_DockerSandbox: docker not found, falling back to in-process Sandbox")
            from ironclaw.tools.sandbox import Sandbox
            fallback = Sandbox(timeout=self.timeout, max_output_chars=self.max_output_chars)
            return await fallback.execute(spec, arguments)

        if proc.returncode != 0:
            stderr_text = stderr_bytes.decode(errors="replace")
            if self.max_output_chars:
                stderr_text = stderr_text[: self.max_output_chars]
            raise RuntimeError(
                f"Docker container exited with code {proc.returncode}: {stderr_text}"
            )

        raw_stdout = stdout_bytes.decode(errors="replace")
        if self.max_output_chars:
            raw_stdout = raw_stdout[: self.max_output_chars]

        try:
            output = json.loads(raw_stdout)
            return output.get("result", "")
        except (json.JSONDecodeError, ValueError):
            return raw_stdout

    def tool_schema_extras(self) -> dict:
        return {
            "docker_image": self.image,
            "memory_mb": self.limits.memoryMb,
            "cpu_shares": self.limits.cpuShares,
        }
