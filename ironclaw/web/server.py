"""
ironclaw.web.server
~~~~~~~~~~~~~~~~~~~
FastAPI web server that exposes IronClaw agents through a REST + SSE API.

Routes
------
GET  /                         → serve the SPA (ui.html)
GET  /api/agents               → list registered agents
POST /api/agents               → create & register a new agent
DELETE /api/agents/{id}        → unregister an agent
GET  /api/agents/{id}/history  → conversation history
POST /api/agents/{id}/clear    → clear conversation history

POST /api/agents/{id}/chat     → send a message (returns SSE stream)
     Emits: data: {"type":"token","text":"..."}\n\n
             data: {"type":"done","message":{...}}\n\n
             data: {"type":"error","message":"..."}\n\n

GET  /api/audit                → last N audit entries (?n=100)
GET  /api/audit/search         → search audit (?event=tool_call_start)

POST /api/orchestrator/pipeline   → run a named pipeline
POST /api/orchestrator/parallel   → run agents in parallel
GET  /api/orchestrator/summary    → fleet summary

GET  /api/state                → shared state snapshot
DELETE /api/state/{key}        → delete a state key

Start:
    pip install fastapi uvicorn[standard]
    ironclaw serve            # via CLI
    # or directly:
    python -m ironclaw.web.server
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

class APIKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.url.path.startswith("/api/"):
            expected = os.environ.get("IRONCLAW_API_KEY")
            if expected:
                auth = request.headers.get("Authorization", "")
                if auth.startswith("Bearer "):
                    auth = auth[7:]
                if auth != expected:
                    return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        return await call_next(request)

from ironclaw.builder import AgentBuilder
from ironclaw.core.hitl import HITLStore, configure_hitl
from ironclaw.core.orchestrator import Orchestrator
from ironclaw.exceptions import (
    AgentNotFoundError,
    InjectionDetectedError,
    IronClawError,
)
from ironclaw.memory.shared import SharedStateStore
from ironclaw.security.audit import AuditLog
from ironclaw.security.policy import SecurityPolicy
from ironclaw.core.scheduler import CronScheduler

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy singletons — created inside lifespan, not at import time.
# This prevents SQLite / file-system side-effects when the module is merely
# imported by tests or other tooling.
# ---------------------------------------------------------------------------

_audit: AuditLog = None          # type: ignore[assignment]
_shared: SharedStateStore = None  # type: ignore[assignment]
_policy: SecurityPolicy = None    # type: ignore[assignment]
_orch: Orchestrator = None        # type: ignore[assignment]
_scheduler: CronScheduler = None  # type: ignore[assignment]
_hitl: HITLStore = None           # type: ignore[assignment]


def _init_singletons() -> None:
    """Initialise all server-wide singletons.  Called once inside lifespan."""
    global _audit, _shared, _policy, _orch, _scheduler, _hitl

    audit_path = os.environ.get("IRONCLAW_AUDIT_LOG", "logs/web_audit.jsonl")
    shared_db  = os.environ.get("IRONCLAW_SHARED_STATE_DB", "logs/shared_state.db")
    hitl_db    = os.environ.get("IRONCLAW_HITL_DB", "logs/hitl.db")

    os.makedirs("logs", exist_ok=True)

    _audit     = AuditLog(path=audit_path)
    _shared    = SharedStateStore(db_path=shared_db)
    _policy    = SecurityPolicy()
    _orch      = Orchestrator(policy=_policy, audit_log=_audit, shared_state=_shared)
    _scheduler = CronScheduler(_orch)

    # SQLite-backed HITL store — shared across all uvicorn workers via the DB.
    _hitl = HITLStore(db_path=hitl_db)
    configure_hitl(_hitl)   # wire into agent.py's _get_hitl()


# ---------------------------------------------------------------------------
# Lifespan — replaces deprecated @app.on_event("startup"/"shutdown")
# ---------------------------------------------------------------------------

@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Startup and shutdown logic wired via the modern lifespan protocol."""
    _init_singletons()
    _scheduler.start()
    await _init_ace()
    yield
    _scheduler.stop()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="IronClaw Control Panel", version="0.2.0", lifespan=_lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(APIKeyMiddleware)


# ---------------------------------------------------------------------------
# ACE subsystem — initialised on startup
# ---------------------------------------------------------------------------

async def _init_ace() -> None:
    """Wire up the Agent Creation Engine on server startup."""
    try:
        from ironclaw.ace.provisioner import AgentProvisioner
        from ironclaw.ace.orchestrator import build_creator_agent
        from ironclaw.ace.api import init_ace, router as ace_router

        # Shared registry with the main orchestrator
        provisioner = AgentProvisioner(
            registry=_orch._agents,  # shared live dict
        )

        # Choose provider for the Creator Agent (env override or default)
        creator_provider = os.environ.get("IRONCLAW_CREATOR_PROVIDER", "anthropic")
        creator_model    = os.environ.get("IRONCLAW_CREATOR_MODEL") or None

        try:
            creator_agent = build_creator_agent(
                provisioner,
                provider_id=creator_provider,
                model=creator_model,
            )
            init_ace(provisioner, creator_agent)
            app.include_router(ace_router)
            logger.info("ACE subsystem started (creator provider: %s)", creator_provider)
        except Exception as exc:
            logger.warning(
                "ACE Creator Agent could not start (provider '%s' may not be configured): %s. "
                "ACE API routes will still be available but conversational creation is disabled.",
                creator_provider, exc,
            )
            # Still register ACE provisioning routes even without a creator agent
            from ironclaw.ace.api import init_ace as _init, router as ace_router
            _init(provisioner, None)
            app.include_router(ace_router)

    except ImportError as exc:
        logger.warning("ACE subsystem could not be loaded: %s", exc)

_UI_PATH = Path(__file__).parent / "ui.html"

# Gateway daemon (populated lazily when gateways are configured)
_daemon: "GatewayDaemon | None" = None

def get_daemon() -> "GatewayDaemon":
    """Return the global GatewayDaemon, creating it if needed."""
    global _daemon
    if _daemon is None:
        from ironclaw.gateway.daemon import GatewayDaemon
        _daemon = GatewayDaemon(
            orchestrator=_orch,
            default_agent_id=os.environ.get("IRONCLAW_DEFAULT_AGENT", ""),
            session_db_path=os.environ.get("IRONCLAW_SESSION_DB") or None,
        )
    return _daemon

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class CreateAgentRequest(BaseModel):
    agent_id: str
    name: str = ""
    system_prompt: str = "You are a helpful assistant."
    provider: str = "anthropic"          # anthropic | openai | ollama
    model: str = "claude-sonnet-4-6"
    capabilities: list[str] = []
    tools: list[str] = []               # "web", "filesystem", "shell"
    allowed_roots: list[str] = []
    allowed_commands: list[str] = []
    api_key: str = ""


class ChatRequest(BaseModel):
    message: str
    session_id: str = ""


class PipelineRequest(BaseModel):
    steps: list[dict]   # [{"agent_id": "...", "template": null | "..."}]
    initial_input: str
    session_id: str = ""


class ParallelRequest(BaseModel):
    tasks: list[dict]   # [{"agent_id": "...", "input": "..."}]
    session_id: str = ""

class ScheduleRequest(BaseModel):
    agent_id: str
    message: str
    cron_expr: str
    job_id: str | None = None

class SkillInstallRequest(BaseModel):
    url: str

class HITLResolveRequest(BaseModel):
    decision: str  # "approved" or "rejected"


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
async def serve_ui():
    ui_file = Path(__file__).parent / "dashboard/dist/index.html"
    if ui_file.exists():
        return FileResponse(ui_file)
    from fastapi.responses import HTMLResponse
    return HTMLResponse("UI not built. Run 'npm run build' in ironclaw/web/dashboard.")

_ASSETS_PATH = Path(__file__).parent / "dashboard/dist/assets"
if _ASSETS_PATH.exists():
    app.mount("/assets", StaticFiles(directory=_ASSETS_PATH), name="assets")


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------

@app.get("/api/agents")
async def list_agents():
    return _orch.summary()


@app.post("/api/agents", status_code=201)
async def create_agent(req: CreateAgentRequest):
    if req.agent_id in _orch.agent_ids:
        raise HTTPException(400, f"Agent '{req.agent_id}' already exists")

    try:
        builder = (
            AgentBuilder(req.agent_id)
            .with_name(req.name or req.agent_id)
            .with_system_prompt(req.system_prompt)
            .with_capabilities(req.capabilities)
            .with_guard()
        )

        # Provider — use the factory so all 15+ providers work, not just 3.
        try:
            from ironclaw.providers.factory import make_provider
            provider = make_provider(
                req.provider,
                model=req.model or None,
                api_key=req.api_key or None,
            )
            builder.with_provider(provider)
        except (ValueError, ImportError) as exc:
            raise HTTPException(400, str(exc))

        # Tools
        if "web" in req.tools:
            builder.with_web_tools()
        if "filesystem" in req.tools:
            builder.with_filesystem_tools(allowed_roots=req.allowed_roots or None)
        if "shell" in req.tools:
            builder.with_shell_tools(
                allowed_commands=req.allowed_commands or None
            )

        agent = builder.build()
        _orch.register(agent)

    except IronClawError as e:
        raise HTTPException(400, str(e))

    return {
        "agent_id": req.agent_id,
        "name": req.name or req.agent_id,
        "capabilities": req.capabilities,
        "tools": req.tools,
        "provider": req.provider,
        "model": req.model,
    }


@app.delete("/api/agents/{agent_id}")
async def delete_agent(agent_id: str):
    try:
        _orch.unregister(agent_id)
    except AgentNotFoundError:
        raise HTTPException(404, f"Agent '{agent_id}' not found")
    return {"deleted": agent_id}


@app.get("/api/agents/{agent_id}/history")
async def get_history(agent_id: str, limit: int = 50):
    try:
        agent = _orch.get_agent(agent_id)
    except AgentNotFoundError:
        raise HTTPException(404, f"Agent '{agent_id}' not found")
    msgs = agent.memory.history(limit=limit)
    return {"messages": [m.to_dict() for m in msgs]}


@app.post("/api/agents/{agent_id}/clear")
async def clear_history(agent_id: str):
    try:
        agent = _orch.get_agent(agent_id)
    except AgentNotFoundError:
        raise HTTPException(404, f"Agent '{agent_id}' not found")
    agent.memory.clear()
    return {"cleared": agent_id}


# ---------------------------------------------------------------------------
# Chat (SSE streaming)
# ---------------------------------------------------------------------------

@app.post("/api/agents/{agent_id}/chat")
async def chat(agent_id: str, req: ChatRequest):
    try:
        agent = _orch.get_agent(agent_id)
    except AgentNotFoundError:
        raise HTTPException(404, f"Agent '{agent_id}' not found")

    async def event_stream():
        try:
            collected: list[str] = []
            # Real token-by-token streaming via provider.stream() for the
            # final text response; tool-call rounds run complete() internally.
            async for chunk in agent.stream(req.message):
                collected.append(chunk)
                payload = json.dumps({"type": "token", "text": chunk})
                yield f"data: {payload}\n\n"

            full_content = "".join(collected)
            done_payload = json.dumps({
                "type": "done",
                "message": {"role": "assistant", "content": full_content},
            })
            yield f"data: {done_payload}\n\n"

        except InjectionDetectedError as e:
            err = json.dumps({"type": "error", "message": f"Blocked: {e}"})
            yield f"data: {err}\n\n"
        except IronClawError as e:
            err = json.dumps({"type": "error", "message": str(e)})
            yield f"data: {err}\n\n"
        except Exception as e:
            logger.exception("Unexpected error in chat stream")
            err = json.dumps({"type": "error", "message": f"Internal error: {e}"})
            yield f"data: {err}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

@app.get("/api/audit")
async def get_audit(limit: int = 100, agent_id: str | None = None):
    if agent_id:
        results = _audit.search(agent_id=agent_id)
    else:
        results = _audit.search()
    # Return last N
    return {"events": results[-limit:]}

@app.get("/api/audit/sessions/{session_id}")
async def get_audit_session(session_id: str):
    events = _audit.search(session_id=session_id)
    return {"events": events, "count": len(events)}

# ---------------------------------------------------------------------------
# Skills API
# ---------------------------------------------------------------------------
@app.get("/api/skills")
async def list_skills():
    try:
        from ironclaw.skills.registry import SkillRegistry
        from ironclaw.cli.commands.skills import _DEFAULT_SKILL_DIR, _BUILTIN_DIR
        reg = SkillRegistry()
        reg.add_directory(_BUILTIN_DIR)
        reg.add_directory(_DEFAULT_SKILL_DIR)
        return {"skills": reg.summaries()}
    except Exception as e:
        logger.error(f"Failed to list skills: {e}")
        return {"skills": []}

@app.post("/api/skills/install")
async def install_skill(req: SkillInstallRequest):
    """
    Clone a skill repository and register it.

    Steps
    -----
    1. ``git clone --depth=1 <url>`` into ``~/.ironclaw/skills/<repo-name>/``
    2. Validate that ``SKILL.md`` exists and parses correctly.
    3. Register the skill in the global SkillRegistry.
    4. Return skill metadata on success; clean up the clone on any failure.
    """
    import shutil

    url = req.url.rstrip("/")
    if not url:
        raise HTTPException(400, "url must not be empty")

    # Derive the target directory name from the repo slug.
    repo_slug = url.split("/")[-1]
    if repo_slug.endswith(".git"):
        repo_slug = repo_slug[:-4]
    if not repo_slug:
        raise HTTPException(400, f"Could not determine repo name from URL: {url!r}")

    skill_base = Path.home() / ".ironclaw" / "skills"
    skill_base.mkdir(parents=True, exist_ok=True)
    target = skill_base / repo_slug

    if target.exists():
        raise HTTPException(
            400,
            f"Skill directory '{repo_slug}' already exists at {target}. "
            "Remove it first or use a different URL.",
        )

    # --- Clone ----------------------------------------------------------
    proc = await asyncio.create_subprocess_exec(
        "git", "clone", "--depth=1", "--", url, str(target),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr_bytes = await proc.communicate()

    if proc.returncode != 0:
        stderr_text = stderr_bytes.decode(errors="replace")[:500]
        raise HTTPException(400, f"git clone failed: {stderr_text}")

    # --- Validate SKILL.md ---------------------------------------------
    skill_md = target / "SKILL.md"
    if not skill_md.exists():
        shutil.rmtree(target, ignore_errors=True)
        raise HTTPException(
            400,
            "Repository cloned successfully but SKILL.md was not found in the root. "
            "This does not appear to be a valid IronClaw skill package.",
        )

    try:
        from ironclaw.skills.manifest import SkillManifest
        manifest = SkillManifest.from_file(skill_md)
    except Exception as exc:
        shutil.rmtree(target, ignore_errors=True)
        raise HTTPException(400, f"Invalid SKILL.md: {exc}")

    # --- Register in global SkillRegistry ------------------------------
    try:
        from ironclaw.skills.registry import SkillRegistry
        reg = SkillRegistry()
        reg.install_from_directory(target)
        logger.info(
            "Skill '%s' installed from %s into %s",
            manifest.name, url, target,
        )
    except Exception as exc:
        # Registry errors don't roll back the clone — skill is on disk and
        # can be discovered on next server restart.
        logger.warning("Skill '%s' cloned but registry registration failed: %s", manifest.name, exc)

    return {
        "status": "installed",
        "name": manifest.name,
        "description": manifest.description,
        "path": str(target),
    }

# ---------------------------------------------------------------------------
# HITL Intercept API
# ---------------------------------------------------------------------------

@app.get("/api/intercepts")
async def list_intercepts():
    """Return all pending HITL intercepts from the shared SQLite store."""
    return {"pending": _hitl.list_pending()}


@app.get("/api/intercepts/all")
async def list_all_intercepts(limit: int = 100):
    """Return recent intercepts regardless of status (for audit UI)."""
    return {"intercepts": _hitl.list_all(limit=limit)}


@app.post("/api/intercepts/{call_id}/resolve")
async def resolve_intercept(call_id: str, req: HITLResolveRequest):
    """
    Resolve a pending HITL intercept.

    The agent loop polls the SQLite store every 500 ms — it will pick up
    this decision within the next poll cycle regardless of which worker
    receives this request.
    """
    if req.decision not in ("approved", "rejected"):
        raise HTTPException(400, "decision must be 'approved' or 'rejected'")

    ok = _hitl.resolve(call_id, req.decision)
    if not ok:
        raise HTTPException(404, f"Intercept '{call_id}' not found or already resolved")

    return {"status": "resolved", "call_id": call_id, "decision": req.decision}


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

@app.get("/api/orchestrator/summary")
async def orchestrator_summary():
    return _orch.summary()


@app.post("/api/orchestrator/pipeline")
async def run_pipeline(req: PipelineRequest):
    steps = [(s["agent_id"], s.get("template")) for s in req.steps]
    try:
        results = await _orch.pipeline(steps, req.initial_input, req.session_id or None)
    except IronClawError as e:
        raise HTTPException(400, str(e))
    return {
        "results": [
            {"agent_id": steps[i][0], "content": r.content}
            for i, r in enumerate(results)
        ]
    }


@app.post("/api/orchestrator/parallel")
async def run_parallel(req: ParallelRequest):
    tasks = [(t["agent_id"], t["input"]) for t in req.tasks]
    try:
        results = await _orch.run_parallel(tasks, req.session_id or None)
    except IronClawError as e:
        raise HTTPException(400, str(e))
    return {
        "results": [
            {"agent_id": tasks[i][0], "content": r.content}
            for i, r in enumerate(results)
        ]
    }

@app.post("/api/jobs")
async def add_job(req: ScheduleRequest):
    job_id = _scheduler.add_job(req.agent_id, req.message, req.cron_expr, req.job_id)
    return {"status": "scheduled", "job_id": job_id}

@app.get("/api/jobs")
async def list_jobs():
    return {"jobs": _scheduler.list_jobs()}

@app.delete("/api/jobs/{job_id}")
async def delete_job(job_id: str):
    _scheduler.remove_job(job_id)
    return {"status": "deleted", "job_id": job_id}


# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------

@app.get("/api/state")
async def get_state():
    return _shared.snapshot()


@app.delete("/api/state/{key}")
async def delete_state(key: str):
    _shared.delete(key)
    return {"deleted": key}


# ---------------------------------------------------------------------------
# Gateway webhook routes
# ---------------------------------------------------------------------------

class TelegramWebhookSetup(BaseModel):
    token: str
    webhook_url: str | None = None
    allowed_chat_ids: list[str] = []

class WhatsAppWebhookSetup(BaseModel):
    access_token: str
    phone_number_id: str
    verify_token: str
    app_secret: str = ""
    allowed_numbers: list[str] = []

class iMessageSetup(BaseModel):
    poll_interval: float = 3.0
    allowed_handles: list[str] = []
    sms_fallback: bool = False


@app.post("/api/gateways/telegram")
async def setup_telegram(req: TelegramWebhookSetup):
    """Register and start a Telegram gateway."""
    from ironclaw.gateway.telegram import TelegramGateway
    gw = TelegramGateway(
        token=req.token,
        webhook_url=req.webhook_url or None,
        allowed_chat_ids=set(req.allowed_chat_ids) or None,
    )
    daemon = get_daemon()
    daemon.add(gw)
    daemon.start_background()
    return {"status": "started", "platform": "telegram", "mode": "webhook" if req.webhook_url else "polling"}


@app.post("/api/gateways/whatsapp")
async def setup_whatsapp(req: WhatsAppWebhookSetup):
    """Register a WhatsApp gateway (webhook mode)."""
    from ironclaw.gateway.whatsapp import WhatsAppGateway
    gw = WhatsAppGateway(
        access_token=req.access_token,
        phone_number_id=req.phone_number_id,
        verify_token=req.verify_token,
        app_secret=req.app_secret or None,
        allowed_numbers=set(req.allowed_numbers) or None,
    )
    daemon = get_daemon()
    daemon.add(gw)
    await gw.start()
    return {"status": "started", "platform": "whatsapp", "mode": "webhook"}


@app.post("/api/gateways/imessage")
async def setup_imessage(req: iMessageSetup):
    """Register and start an iMessage gateway (macOS only)."""
    try:
        from ironclaw.gateway.imessage import iMessageGateway
        gw = iMessageGateway(
            poll_interval=req.poll_interval,
            allowed_handles=set(req.allowed_handles) or None,
            sms_fallback=req.sms_fallback,
        )
        daemon = get_daemon()
        daemon.add(gw)
        daemon.start_background()
        return {"status": "started", "platform": "imessage", "mode": "polling"}
    except RuntimeError as e:
        raise HTTPException(400, str(e))


# Telegram webhook receiver
@app.post("/webhook/telegram")
async def telegram_webhook(update: dict):
    daemon = get_daemon()
    for gw in daemon._gateways:
        if gw.platform.value == "telegram":
            from ironclaw.gateway.telegram import TelegramGateway
            if isinstance(gw, TelegramGateway):
                await gw.handle_webhook(update)
                return {"ok": True}
    raise HTTPException(404, "Telegram gateway not registered")


# Telegram webhook verification (GET)
@app.get("/webhook/telegram")
async def telegram_webhook_verify():
    return {"ok": True}


# WhatsApp webhook verification (GET)
@app.get("/webhook/whatsapp")
async def whatsapp_verify(
    hub_mode: str | None = None,
    hub_verify_token: str | None = None,
    hub_challenge: str | None = None,
):
    from fastapi.responses import PlainTextResponse
    daemon = get_daemon()
    for gw in daemon._gateways:
        if gw.platform.value == "whatsapp":
            from ironclaw.gateway.whatsapp import WhatsAppGateway
            if isinstance(gw, WhatsAppGateway):
                challenge = gw.verify_webhook(
                    hub_mode or "", hub_verify_token or "", hub_challenge or ""
                )
                if challenge:
                    return PlainTextResponse(challenge)
    raise HTTPException(403, "Verification failed")


# WhatsApp webhook receiver (POST)
@app.post("/webhook/whatsapp")
async def whatsapp_webhook(payload: dict, request: Any = None):
    daemon = get_daemon()
    for gw in daemon._gateways:
        if gw.platform.value == "whatsapp":
            from ironclaw.gateway.whatsapp import WhatsAppGateway
            if isinstance(gw, WhatsAppGateway):
                await gw.handle_webhook(payload)
                return {"ok": True}
    raise HTTPException(404, "WhatsApp gateway not registered")


# Gateway status
@app.get("/api/gateways")
async def gateway_status():
    return get_daemon().status()


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def serve(host: str = "127.0.0.1", port: int = 7432, reload: bool = False):
    """Launch the IronClaw web server."""
    import uvicorn
    os.makedirs("logs", exist_ok=True)
    uvicorn.run(
        "ironclaw.web.server:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )


if __name__ == "__main__":
    serve()
