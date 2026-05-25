import pytest
from fastapi.testclient import TestClient
from ironclaw.web.server import app

client = TestClient(app)

def test_api_agents():
    response = client.get("/api/agents")
    # Expect 401 if APIKeyMiddleware is active, or 200 if no auth header required in test config
    assert response.status_code in [200, 401]

def test_skill_install():
    res = client.post("/api/skills/install", json={"url": "https://agentskills.io/test-skill"})
    assert res.status_code in [200, 401]

def test_audit_sessions():
    res = client.get("/api/audit/sessions/test1234")
    assert res.status_code in [200, 401]
