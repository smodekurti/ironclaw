import os
import pytest
from fastapi.testclient import TestClient

# Point I/O to temp paths so module-level init doesn't write to the project dir.
os.environ.setdefault("IRONCLAW_SHARED_STATE_DB", "/tmp/ironclaw_test_shared.db")
os.environ.setdefault("IRONCLAW_AUDIT_LOG", "/tmp/ironclaw_test_audit.jsonl")
os.environ.setdefault("IRONCLAW_HITL_DB", "/tmp/ironclaw_test_hitl.db")

from ironclaw.web.server import app


def test_api_agents():
    # Use TestClient as a context manager so the lifespan (startup/shutdown) runs.
    with TestClient(app) as client:
        response = client.get("/api/agents")
        # Expect 401 if APIKeyMiddleware is active, or 200 if no auth required in test config
        assert response.status_code in [200, 401]


def test_skill_install():
    with TestClient(app) as client:
        res = client.post("/api/skills/install", json={"url": "https://agentskills.io/test-skill"})
        # 200 = installed, 400 = git clone failed (URL unreachable in CI), 401 = auth required
        assert res.status_code in [200, 400, 401]


def test_audit_sessions():
    with TestClient(app) as client:
        res = client.get("/api/audit/sessions/test1234")
        assert res.status_code in [200, 401]
