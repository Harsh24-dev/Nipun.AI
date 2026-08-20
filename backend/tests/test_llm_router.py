"""Tests for LLM routing logic."""

import pytest
from src.llm.router import select_tier, _get_tier_config
from src.llm.client import _resolve_model_string as resolve


def test_simple_routes_to_fast():
    assert select_tier("simple") == "fast"


def test_multi_step_routes_to_primary():
    assert select_tier("multi_step") == "primary"


def test_action_routes_to_primary():
    assert select_tier("action") == "primary"
    assert select_tier("simple", has_tools=True) == "primary"


def test_resolve_model_google():
    assert resolve("google", "gemini-1.5-flash") == "gemini/gemini-1.5-flash"
    assert resolve("google", "gemini/gemini-1.5-flash") == "gemini/gemini-1.5-flash"


def test_resolve_model_anthropic():
    assert resolve("anthropic", "claude-sonnet-4-6") == "claude-sonnet-4-6"


def test_resolve_model_groq():
    assert resolve("groq", "llama-3.1-70b-versatile") == "groq/llama-3.1-70b-versatile"


def test_resolve_model_openai():
    assert resolve("openai", "gpt-4o") == "gpt-4o"
