import os
import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from ironclaw.ace.schema import (
    AgentSpec, PersonaSpec, ModelSpec, ToolConfig, MemorySpec, SecuritySpec,
    IsolationSpec, SchedulingSpec, MetadataSpec, UserProfileSpec, ProviderID,
    MemoryType, IsolationType, ResourceLimits
)
from ironclaw.ace.provisioner import AgentProvisioner, resolve_credential, _DockerSandbox, ProvisionResult
from ironclaw.skills.manifest import SkillManifest, _split_frontmatter, _parse_yaml_frontmatter, _validate
from ironclaw.skills.registry import SkillRegistry, _tokenise, _keyword_select, _llm_select

# -----------------------------------------------------------------------------
# ACE Schema Tests
# -----------------------------------------------------------------------------

def test_schema_minimal():
    spec = AgentSpec.minimal("test-bot", "openai", api_key_env="OPENAI_API_KEY")
    assert spec.agentId == "test-bot"
    assert spec.model.provider == "openai"
    assert "apiKey" in spec.model.credentials
    assert spec.model.credentials["apiKey"] == "env:OPENAI_API_KEY"

def test_schema_generate_id():
    spec = AgentSpec.minimal("my-bot", "openai")
    gen_id = spec.generate_id()
    assert gen_id.startswith("my-bot-")
    assert len(gen_id) > len("my-bot-")

def test_schema_user_profile():
    up = UserProfileSpec(name="Alice", role="Admin", useGlobal=False)
    profile = up.to_user_profile()
    assert profile.name == "Alice"
    assert profile.role == "Admin"

    up_global = UserProfileSpec(useGlobal=True)
    with patch("ironclaw.user.store.UserProfileStore.global_profile") as mock_gp:
        mock_gp.return_value = "global_prof"
        assert up_global.to_user_profile() == "global_prof"

# -----------------------------------------------------------------------------
# ACE Provisioner Tests
# -----------------------------------------------------------------------------

def test_resolve_credential():
    assert resolve_credential("env:MY_VAR", {"MY_VAR": "secret123"}) == "secret123"
    with pytest.raises(EnvironmentError):
        resolve_credential("env:MISSING_VAR", {})
    with pytest.raises(NotImplementedError):
        resolve_credential("secret:path")
    with pytest.raises(ValueError):
        resolve_credential("unknown:ref")

@pytest.fixture
def provisioner(tmp_path):
    return AgentProvisioner(workspace_root=str(tmp_path), registry={})

@pytest.mark.asyncio
async def test_provisioner_dry_run(provisioner):
    spec = AgentSpec.minimal("dry-run-bot", "openai")
    plan = await provisioner.dry_run(spec)
    assert plan["agentId"] == "dry-run-bot"
    assert plan["provider"] == "openai"
    assert not plan["alreadyExists"]

@pytest.mark.asyncio
async def test_provisioner_provision(provisioner, monkeypatch):
    monkeypatch.setenv("DUMMY_KEY", "123")
    spec = AgentSpec.minimal("live-bot", "openai", api_key_env="DUMMY_KEY")
    spec.memory.type = MemoryType.none
    spec.isolation.type = IsolationType.none
    
    with patch("ironclaw.builder.AgentBuilder.build", return_value="agent_instance"), \
         patch("ironclaw.providers.factory.PROVIDER_CATALOGUE", {"openai": MagicMock()}), \
         patch("ironclaw.providers.factory.make_provider"):
        result = await provisioner.provision(spec)
        assert result.success
        assert result.agent_id == "live-bot"
        assert result.agent == "agent_instance"
        
        # Test deprovision
        assert provisioner.deprovision("live-bot") is True
        assert provisioner.deprovision("live-bot") is False

@pytest.mark.asyncio
async def test_provisioner_provision_docker_unavailable(provisioner, monkeypatch):
    monkeypatch.setenv("DUMMY_KEY", "123")
    spec = AgentSpec.minimal("docker-bot", "openai", api_key_env="DUMMY_KEY")
    spec.isolation.type = IsolationType.docker
    spec.isolation.image = "python:3.12"
    spec.memory.type = MemoryType.in_memory

    with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError), \
         patch("ironclaw.builder.AgentBuilder.build"), \
         patch("ironclaw.providers.factory.PROVIDER_CATALOGUE", {"openai": MagicMock()}), \
         patch("ironclaw.providers.factory.make_provider"):
        result = await provisioner.provision(spec)
        assert any("Docker is not available" in w for w in result.warnings)

@pytest.mark.asyncio
async def test_docker_sandbox():
    limits = ResourceLimits()
    sandbox = _DockerSandbox("python:3.12", "/tmp", limits)
    extras = sandbox.tool_schema_extras()
    assert extras["docker_image"] == "python:3.12"
    assert extras["memory_mb"] == 512
    with patch("ironclaw.ace.provisioner._DockerSandbox.run", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = "ok"
        assert await sandbox.run(lambda: 1) == "ok"

# -----------------------------------------------------------------------------
# ACE API Tests
# -----------------------------------------------------------------------------

def test_api_init():
    from ironclaw.ace.api import init_ace, _require_ace
    init_ace("prov", "creator")
    # should not raise
    _require_ace()
    
# -----------------------------------------------------------------------------
# Skills Manifest Tests
# -----------------------------------------------------------------------------

def test_split_frontmatter():
    text = "---\nname: foo\n---\nbody content"
    front, body = _split_frontmatter(text)
    assert "name: foo" in front
    assert "body content" in body

def test_parse_yaml_frontmatter():
    front = "name: test\ndescription: 'a test'\nmetadata:\n  author: 'me'"
    data = _parse_yaml_frontmatter(front)
    assert data["name"] == "test"
    assert data["description"] == "a test"
    assert data["metadata"]["author"] == "me"

def test_skill_manifest_from_file(tmp_path):
    skill_dir = tmp_path / "myskill"
    skill_dir.mkdir()
    md_file = skill_dir / "SKILL.md"
    md_file.write_text("---\nname: my-skill\ndescription: test desc\n---\nHello World")
    
    manifest = SkillManifest.from_file(md_file)
    assert manifest.name == "my-skill"
    assert manifest.description == "test desc"
    assert manifest.body == "Hello World"
    assert manifest.script_dir() == skill_dir / "scripts"

def test_manifest_validation():
    with pytest.raises(ValueError, match="'name' field is required"):
        _validate("", "desc", Path("."))
    with pytest.raises(ValueError, match="'description' field is required"):
        _validate("name", "", Path("."))
    with pytest.raises(ValueError, match="lowercase alphanumeric"):
        _validate("Invalid_Name", "desc", Path("."))

# -----------------------------------------------------------------------------
# Skills Registry Tests
# -----------------------------------------------------------------------------

def test_tokenise():
    tokens = _tokenise("Hello world, this is a test.")
    assert "hello" in tokens
    assert "world" in tokens
    assert "test" in tokens
    assert "this" not in tokens

def test_keyword_select():
    m1 = SkillManifest("python-runner", "Run python code")
    m2 = SkillManifest("web-search", "Search the web")
    res = _keyword_select("run some python code", [m1, m2], max_n=1, min_score=1)
    assert res == ["python-runner"]

@pytest.mark.asyncio
async def test_llm_select():
    m1 = SkillManifest("py", "Run python")
    
    class MockResp:
        content = "py"
    
    class MockProvider:
        async def complete(self, msgs):
            return MockResp()
            
    res = _llm_select("run it", [m1], MockProvider(), 1)
    assert res == ["py"]

def test_skill_registry(tmp_path):
    reg = SkillRegistry()
    
    # Setup dummy skill dir
    skill_dir = tmp_path / "test-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("---\nname: test-skill\ndescription: A test\n---\nBody")
    
    reg.add_directory(tmp_path)
    assert len(reg) == 1
    assert "test-skill" in reg.names
    
    summary = reg.summaries()
    assert summary[0]["name"] == "test-skill"
    
    prompt = reg.discovery_prompt()
    assert "test-skill" in prompt
    
    ctx = reg.context_for("I want to do a test")
    assert "test-skill" in ctx
    
    assert reg.remove("test-skill") is True
    assert len(reg) == 0

def test_skill_registry_install(tmp_path):
    skill_dir = tmp_path / "new-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("---\nname: new-skill\ndescription: new\n---\nHi")
    
    reg = SkillRegistry()
    reg.install_from_directory(skill_dir)
    assert "new-skill" in reg.names
