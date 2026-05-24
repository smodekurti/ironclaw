import pytest
import asyncio
from ironclaw.core.agent import Agent
from ironclaw.core.context import ExecutionContext
from ironclaw.memory.shared import SharedStateStore
from ironclaw.memory.conversation import InMemoryConversation
from ironclaw.security.guard import PromptGuard
from ironclaw.tools.registry import ToolRegistry
from ironclaw.tools.permissions import CapabilitySet
from ironclaw.tools.sandbox import Sandbox
from ironclaw.providers.base import LLMProvider, LLMResponse
from ironclaw.core.message import Message, Role, ToolCall

class MockProvider(LLMProvider):
    async def complete(self, messages, tools=None, **kwargs):
        return LLMResponse(content="Hello", tool_calls=[])
    def supports_tools(self): return True
    def supports_vision(self): return False

@pytest.mark.asyncio
async def test_agent_execution_loop():
    provider = MockProvider()
    memory = InMemoryConversation()
    guard = PromptGuard()
    tools = ToolRegistry()
    caps = CapabilitySet(grants=["*"])
    sandbox = Sandbox()
    
    agent = Agent(
        agent_id="test_agent",
        name="Test",
        system_prompt="You are a test",
        provider=provider,
        tools=tools,
        capabilities=caps,
        memory=memory,
        guard=guard,
        sandbox=sandbox
    )
    
    reply = await agent.run("Hi")
    assert reply.role == Role.ASSISTANT
    assert reply.content == "Hello"
    
    history = memory.history()
    assert len(history) == 2
    assert history[0].role == Role.USER
    assert history[-1].role == Role.ASSISTANT

def test_shared_state_store():
    store = SharedStateStore(db_path=":memory:")
    store.set("key", "value", ns="test")
    assert store.get("key", ns="test") == "value"
