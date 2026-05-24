"""
ironclaw.cli.client
~~~~~~~~~~~~~~~~~~~
HTTP client for the IronClaw REST API.

All management CLI commands talk to a running IronClaw server through this
client.  The server URL is resolved in this order:

  1. --server flag passed on the command line
  2. IRONCLAW_SERVER env var
  3. Default: http://localhost:7432

If the server is unreachable, ``ServerUnavailableError`` is raised with a
helpful message telling the user to run ``ironclaw serve``.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

_DEFAULT_SERVER = "http://localhost:7432"


class ServerUnavailableError(Exception):
    """Raised when the IronClaw server cannot be reached."""


class APIError(Exception):
    """Raised when the server returns an error response."""
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"HTTP {status}: {detail}")
        self.status = status
        self.detail = detail


class IronClawClient:
    """
    Thin synchronous HTTP client for the IronClaw REST API.

    Uses only the stdlib (urllib) so there are no extra dependencies
    beyond what the framework already requires.
    """

    def __init__(self, server_url: str = _DEFAULT_SERVER, timeout: float = 30.0) -> None:
        self.base = server_url.rstrip("/")
        self.timeout = timeout

    # ------------------------------------------------------------------
    # Core request
    # ------------------------------------------------------------------

    def request(
        self,
        method: str,
        path: str,
        body: Any = None,
        params: dict[str, str] | None = None,
    ) -> Any:
        url = self.base + path
        if params:
            url += "?" + urllib.parse.urlencode(params)

        data: bytes | None = None
        headers: dict[str, str] = {}
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            body_bytes = e.read()
            try:
                detail = json.loads(body_bytes).get("detail", body_bytes.decode())
            except Exception:
                detail = body_bytes.decode(errors="replace")
            raise APIError(e.code, detail) from e
        except (urllib.error.URLError, ConnectionRefusedError, OSError) as e:
            raise ServerUnavailableError(
                f"Cannot reach IronClaw server at {self.base}\n"
                f"  → Start it with: ironclaw serve\n"
                f"  → Or point to a remote server: ironclaw --server http://host:port ..."
            ) from e

    def get(self, path: str, params: dict[str, str] | None = None) -> Any:
        return self.request("GET", path, params=params)

    def post(self, path: str, body: Any = None) -> Any:
        return self.request("POST", path, body=body)

    def delete(self, path: str) -> Any:
        return self.request("DELETE", path)

    # ------------------------------------------------------------------
    # Convenience: check server is up
    # ------------------------------------------------------------------

    def ping(self) -> bool:
        try:
            self.get("/api/orchestrator/summary")
            return True
        except (ServerUnavailableError, APIError):
            return False

    # ------------------------------------------------------------------
    # Typed API helpers
    # ------------------------------------------------------------------

    # --- Agents ---
    def list_agents(self) -> list[dict]:
        return self.get("/api/agents").get("agents", [])

    def create_agent(self, payload: dict) -> dict:
        return self.post("/api/agents", payload)

    def delete_agent(self, agent_id: str) -> dict:
        return self.delete(f"/api/agents/{agent_id}")

    def get_history(self, agent_id: str, limit: int = 50) -> list[dict]:
        return self.get(f"/api/agents/{agent_id}/history", {"limit": str(limit)}).get("messages", [])

    def clear_history(self, agent_id: str) -> dict:
        return self.post(f"/api/agents/{agent_id}/clear")

    def chat_sync(self, agent_id: str, message: str, session_id: str = "") -> str:
        """
        Send a message and collect the full streamed reply synchronously.
        Reads SSE stream line-by-line until a 'done' event.
        """
        url = f"{self.base}/api/agents/{agent_id}/chat"
        body = json.dumps({"message": message, "session_id": session_id}).encode()
        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            full_text = ""
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                for raw_line in resp:
                    line = raw_line.decode("utf-8", errors="replace").rstrip("\n\r")
                    if not line.startswith("data: "):
                        continue
                    try:
                        evt = json.loads(line[6:])
                    except json.JSONDecodeError:
                        continue
                    if evt.get("type") == "token":
                        full_text += evt.get("text", "")
                    elif evt.get("type") == "done":
                        return evt.get("message", {}).get("content", full_text)
                    elif evt.get("type") == "error":
                        raise APIError(0, evt.get("message", "unknown error"))
            return full_text
        except (urllib.error.URLError, ConnectionRefusedError) as e:
            raise ServerUnavailableError(str(e)) from e

    # --- Gateways ---
    def gateway_status(self) -> dict:
        return self.get("/api/gateways")

    def connect_telegram(self, payload: dict) -> dict:
        return self.post("/api/gateways/telegram", payload)

    def connect_whatsapp(self, payload: dict) -> dict:
        return self.post("/api/gateways/whatsapp", payload)

    def connect_imessage(self, payload: dict) -> dict:
        return self.post("/api/gateways/imessage", payload)

    # --- Sessions (via shared state) ---
    def get_state(self) -> dict:
        return self.get("/api/state")

    def delete_state(self, key: str) -> dict:
        return self.delete(f"/api/state/{key}")

    # --- Orchestrator ---
    def orch_summary(self) -> dict:
        return self.get("/api/orchestrator/summary")

    def orch_pipeline(self, steps: list, initial_input: str, session_id: str = "") -> dict:
        return self.post("/api/orchestrator/pipeline", {
            "steps": steps,
            "initial_input": initial_input,
            "session_id": session_id,
        })

    def orch_parallel(self, tasks: list, session_id: str = "") -> dict:
        return self.post("/api/orchestrator/parallel", {
            "tasks": tasks,
            "session_id": session_id,
        })

    # --- ACE: Agent Creation Engine ---

    def create_agent_from_spec(self, spec: dict) -> dict:
        """POST a full AgentSpec to the ACE create endpoint."""
        return self.post("/api/v1/ace/agents/create", spec)

    def dry_run_agent_spec(self, spec: dict) -> dict:
        """POST a full AgentSpec to the ACE dry-run endpoint."""
        return self.post("/api/v1/ace/agents/create/dry-run", spec)

    def ace_agent_status(self, agent_id: str) -> dict:
        """GET ACE agent status."""
        return self.get(f"/api/v1/ace/agents/{agent_id}/status")

    def chat_sync_ace(self, message: str, session_id: str = "creator-default") -> str:
        """
        Send a message to the Creator Agent and return the full reply.
        Reads the SSE stream from /api/v1/ace/agents/create/chat.
        """
        url = f"{self.base}/api/v1/ace/agents/create/chat"
        body = json.dumps({"message": message, "sessionId": session_id}).encode()
        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            full_text = ""
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                for raw_line in resp:
                    line = raw_line.decode("utf-8", errors="replace").rstrip("\n\r")
                    if not line.startswith("data: "):
                        continue
                    try:
                        evt = json.loads(line[6:])
                    except json.JSONDecodeError:
                        continue
                    evt_type = evt.get("type")
                    if evt_type == "token":
                        full_text += evt.get("content", "")
                        # Print tokens as they arrive
                        import sys
                        print(evt.get("content", ""), end="", flush=True)
                    elif evt_type == "result":
                        agent_id = evt.get("agentId")
                        if agent_id:
                            full_text += f"\n\n✓ Agent '{agent_id}' created."
                    elif evt_type == "done":
                        print()  # newline after streaming
                        return full_text
                    elif evt_type == "error":
                        raise APIError(0, evt.get("error", "unknown error"))
            print()
            return full_text
        except (urllib.error.URLError, ConnectionRefusedError) as e:
            raise ServerUnavailableError(str(e)) from e

    # --- Audit ---
    def audit_tail(self, n: int = 100) -> list[dict]:
        return self.get("/api/audit", {"n": str(n)}).get("entries", [])

    def audit_search(self, event: str | None = None, agent_id: str | None = None, n: int = 200) -> list[dict]:
        params: dict[str, str] = {"n": str(n)}
        if event:
            params["event"] = event
        if agent_id:
            params["agent_id"] = agent_id
        return self.get("/api/audit/search", params).get("entries", [])


def make_client(args: Any) -> IronClawClient:
    """Build an IronClawClient from parsed CLI args."""
    url = getattr(args, "server", None) or os.environ.get("IRONCLAW_SERVER") or _DEFAULT_SERVER
    return IronClawClient(server_url=url)


def require_server(client: IronClawClient) -> None:
    """Exit with a friendly message if the server is not reachable."""
    if not client.ping():
        print(f"\033[1;31mError:\033[0m IronClaw server not reachable at {client.base}")
        print("  Start it with:  \033[1mironclaw serve\033[0m")
        sys.exit(1)
