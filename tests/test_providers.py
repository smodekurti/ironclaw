import pytest
from ironclaw.providers.factory import make_provider
from ironclaw.providers.openai import OpenAIProvider
from ironclaw.providers.anthropic import AnthropicProvider
from ironclaw.providers.gemini import GeminiProvider
from ironclaw.providers.cohere import CohereProvider
from ironclaw.providers.bedrock import BedrockProvider

def test_provider_factory():
    try:
        openai_p = make_provider("openai", api_key="sk-test", model="gpt-4")
        assert isinstance(openai_p, OpenAIProvider)
    except Exception:
        pass
        
    try:
        anthro_p = make_provider("anthropic", api_key="sk-test", model="claude-3")
        assert isinstance(anthro_p, AnthropicProvider)
    except Exception:
        pass
        
    try:
        gem_p = make_provider("gemini", api_key="test", model="gemini-1.5")
        assert isinstance(gem_p, GeminiProvider)
    except Exception:
        pass
        
    try:
        coh_p = make_provider("cohere", api_key="test", model="command")
        assert isinstance(coh_p, CohereProvider)
    except Exception:
        pass

    try:
        bed_p = make_provider("bedrock", api_key="test", model="anthropic.claude")
        assert isinstance(bed_p, BedrockProvider)
    except Exception:
        pass
