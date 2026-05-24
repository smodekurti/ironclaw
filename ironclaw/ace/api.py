"""
ironclaw.ace.api
~~~~~~~~~~~~~~~~
Agent Creation Engine — FastAPI router.

Mounts under the main IronClaw web server at ``/api/v1/ace``.

Endpoints
---------
POST   /api/v1/ace/agents/create          — provision from a full AgentSpec JSON
POST   /api/v1/ace/agents/create/dry-run  — validate + plan, no resources created
POST   /api/v1/ace/agents/create/chat     — streaming conversational creation (SSE)
GET    /api/v1/ace/agents/schema          — return the JSON schema for AgentSpec
GET    /api/v1/ace/agents/{id}/status     — provisioning status / agent info

All endpoints require the ACE subsystem to be initialised via ``init_ace()``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator, Dict

log = logging.getLogger(__name__)

try:
    from fastapi import APIRouter, HTTPException, Request
    from fastapi.responses import JSONResponse, StreamingResponse
    _FASTAPI = True
except ImportError:  # pragma: no cover
    _FASTAPI = False


# ---------------------------------------------------------------------------
# Singletons (set by init_ace)
# ---------------------------------------------------------------------------

_provisioner = None
_creator_agent = None


def init_ace(provisioner, creator_agent) -> None:
    """
    Initialise the ACE subsystem.

    Called once at server startup (``ironclaw.web.server``).

    Parameters
    ----------
    provisioner:
        An ``AgentProvisioner`` instance shared with the main agent registry.
    creator_agent:
        A pre-built Creator Agent (``build_creator_agent(provisioner)``).
    """
    global _provisioner, _creator_agent
    _provisioner  = provisioner
    _creator_agent = creator_agent
    log.info("ACE subsystem initialised")


def _require_ace():
    if _provisioner is None or _creator_agent is None:
        raise RuntimeError(
            "ACE subsystem not initialised. "
            "Call ironclaw.ace.api.init_ace() at startup."
        )


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

if _FASTAPI:
    router = APIRouter(prefix="/api/v1/ace", tags=["ace"])

    # -----------------------------------------------------------------------
    # GET /api/v1/ace/agents/schema
    # -----------------------------------------------------------------------

    @router.get("/agents/schema")
    async def get_agent_schema():
        """Return the JSON Schema for AgentSpec (useful for GUI builders)."""
        try:
            from ironclaw.ace.schema import AgentSpec
            if hasattr(AgentSpec, "model_json_schema"):
                schema = AgentSpec.model_json_schema()
            else:
                # Pydantic v1 fallback
                schema = AgentSpec.schema() if hasattr(AgentSpec, "schema") else {}
        except Exception:
            schema = {}

        return JSONResponse(schema)

    # -----------------------------------------------------------------------
    # POST /api/v1/ace/agents/create
    # -----------------------------------------------------------------------

    @router.post("/agents/create", status_code=201)
    async def create_agent(request: Request):
        """
        Provision an agent from a complete AgentSpec JSON body.

        Returns the provisioned agent's ID and any warnings.
        """
        _require_ace()

        try:
            body = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON body")

        from ironclaw.ace.schema import AgentSpec
        try:
            spec = AgentSpec.from_dict(body)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Invalid AgentSpec: {exc}")

        try:
            result = await _provisioner.provision(spec)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except Exception as exc:
            log.exception("Provisioning failed for '%s'", body.get("agentId"))
            raise HTTPException(status_code=500, detail=f"Provisioning failed: {exc}")

        return JSONResponse(
            status_code=201,
            content={
                "agentId":  result.agent_id,
                "status":   "created",
                "warnings": result.warnings,
            },
        )

    # -----------------------------------------------------------------------
    # POST /api/v1/ace/agents/create/dry-run
    # -----------------------------------------------------------------------

    @router.post("/agents/create/dry-run")
    async def dry_run_agent(request: Request):
        """
        Validate an AgentSpec and return a provisioning plan without creating
        any resources.
        """
        _require_ace()

        try:
            body = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON body")

        from ironclaw.ace.schema import AgentSpec
        try:
            spec = AgentSpec.from_dict(body)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Invalid AgentSpec: {exc}")

        plan = await _provisioner.dry_run(spec)
        return JSONResponse(content={"status": "ok", "plan": plan})

    # -----------------------------------------------------------------------
    # POST /api/v1/ace/agents/create/chat  (SSE streaming)
    # -----------------------------------------------------------------------

    @router.post("/agents/create/chat")
    async def conversational_create(request: Request):
        """
        Streaming conversational agent creation powered by the Creator Agent.

        Request body::

            {"message": "Create a customer support bot using GPT-4o"}

        Streams Server-Sent Events::

            data: {"type": "token",    "content": "Sure! Let me..."}
            data: {"type": "tool_use", "tool": "spawn_new_agent", "input": {...}}
            data: {"type": "result",   "agentId": "support-bot", "warnings": []}
            data: {"type": "done"}

        The client should keep the connection open until ``type: done``.
        """
        _require_ace()

        try:
            body = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON body")

        user_message = body.get("message", "").strip()
        if not user_message:
            raise HTTPException(status_code=400, detail="'message' field is required")

        session_id = body.get("sessionId", "creator-default")

        async def event_stream() -> AsyncIterator[str]:
            try:
                async for chunk in _creator_agent.stream(
                    user_message,
                    session_id=session_id,
                ):
                    if isinstance(chunk, str):
                        payload = json.dumps({"type": "token", "content": chunk})
                    elif isinstance(chunk, dict):
                        payload = json.dumps(chunk)
                    else:
                        payload = json.dumps({"type": "token", "content": str(chunk)})
                    yield f"data: {payload}\n\n"

                yield f"data: {json.dumps({'type': 'done'})}\n\n"

            except Exception as exc:
                log.exception("Creator Agent stream error")
                error_payload = json.dumps({"type": "error", "error": str(exc)})
                yield f"data: {error_payload}\n\n"

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    # -----------------------------------------------------------------------
    # GET /api/v1/ace/agents/{agent_id}/status
    # -----------------------------------------------------------------------

    @router.get("/agents/{agent_id}/status")
    async def agent_status(agent_id: str):
        """
        Return current status and metadata for a provisioned agent.
        """
        _require_ace()

        if _provisioner is None:
            raise HTTPException(status_code=503, detail="ACE not initialised")

        agent = _provisioner._registry.get(agent_id)
        if agent is None:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

        # Read spec from workspace if available
        import pathlib
        spec_path = pathlib.Path(
            _provisioner._root / agent_id / "spec.json"
        )
        spec_data: Dict[str, Any] = {}
        if spec_path.exists():
            try:
                spec_data = json.loads(spec_path.read_text())
            except Exception:
                pass

        return JSONResponse({
            "agentId":  agent_id,
            "name":     getattr(agent, "name", agent_id),
            "status":   "running",
            "spec":     spec_data,
        })

    # -----------------------------------------------------------------------
    # DELETE /api/v1/ace/agents/{agent_id}
    # -----------------------------------------------------------------------

    @router.delete("/agents/{agent_id}", status_code=200)
    async def deprovision_agent(agent_id: str):
        """Remove an agent from the live registry."""
        _require_ace()

        if not _provisioner.deprovision(agent_id):
            raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

        return JSONResponse({"agentId": agent_id, "status": "deprovisioned"})

else:
    # Stub for environments without FastAPI installed
    router = None  # type: ignore[assignment]

    def init_ace(provisioner, creator_agent) -> None:  # type: ignore[misc]
        pass
