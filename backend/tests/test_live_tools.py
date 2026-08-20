"""Tests for the live-data tool layer + orchestrator augmentation routing (offline).

No network: tool calls are monkeypatched. These verify tool SELECTION, result→chunk
conversion, the needs_live_data heuristic, and that the RAG loop routes to
`live_augment` exactly when the static index can't ground the answer."""

import pytest

from src.config import settings
from src.mcp.base import ToolResult
from src.mcp.live import aggregator
from src.mcp.live.aggregator import _select_tools, _to_chunks, needs_live_data
from src.mcp.live.research import _expand_career


# ── needs_live_data heuristic ──────────────────────────────────────────────────

def test_needs_live_data_time_sensitive():
    assert needs_live_data("what is the price of onion today", "farming", "")
    assert needs_live_data("latest news on budget", "general", "")
    assert needs_live_data("highest moving stock right now", "finance", "")


def test_needs_live_data_research_and_books():
    assert needs_live_data("best books to become a doctor", "student", "")
    assert needs_live_data("latest research findings on diabetes", "health", "")


def test_needs_live_data_static_query_false():
    assert not needs_live_data("what is section 302 of IPC", "legal", "")


# ── tool selection ─────────────────────────────────────────────────────────────

def test_select_always_includes_web_search():
    names = [n for n, _ in _select_tools("anything at all", "general", "")]
    assert names[0] == "web_search"


def test_select_finance_for_stock_query():
    names = [n for n, _ in _select_tools("highest moving stock today", "finance", "")]
    assert "finance" in names


def test_select_books_and_scholar_for_career_query():
    names = [n for n, _ in _select_tools("best books to become an engineer", "student", "")]
    assert "books" in names and "scholar" in names


def test_select_weather_and_mandi():
    assert "weather" in [n for n, _ in _select_tools("weather in Pune", "general", "")]
    assert "mandi_prices" in [n for n, _ in _select_tools("wheat mandi price", "farming", "")]


# ── career seed expansion ──────────────────────────────────────────────────────

def test_expand_career_adds_seeds():
    expanded = _expand_career("books to become a doctor")
    assert "NEET" in expanded or "physiology" in expanded


def test_expand_career_noop_for_plain_subject():
    assert _expand_career("history of the Mughal empire") == "history of the Mughal empire"


# ── result → chunk conversion ──────────────────────────────────────────────────

def test_to_chunks_from_results():
    result = ToolResult("web_search", "ok", data={"results": [
        {"title": "T1", "url": "http://a", "content": "alpha", "source": "SrcA"},
        {"title": "T2", "url": "http://b", "content": "beta", "source": "SrcB"},
    ]})
    chunks = _to_chunks("web_search", result)
    assert len(chunks) == 2
    assert chunks[0]["source"] == "SrcA"
    assert chunks[0]["source_url"] == "http://a"
    assert chunks[0]["live"] is True


def test_to_chunks_falls_back_to_text():
    result = ToolResult("finance", "ok", data={}, text="AAPL 200 USD")
    chunks = _to_chunks("finance", result)
    assert len(chunks) == 1 and "AAPL" in chunks[0]["text"]


# ── aggregator with a fake tool (no network) ───────────────────────────────────

async def test_gather_live_knowledge_returns_cited_chunks(monkeypatch):
    class _FakeTool:
        read_only = True
        async def call(self, params):
            return ToolResult("web_search", "ok", data={"results": [
                {"title": "PM-KISAN", "url": "http://pmkisan", "content": "6000/year", "source": "gov"}]})

    monkeypatch.setattr("src.mcp.tools.get_tool", lambda name: _FakeTool())
    monkeypatch.setattr(settings, "WEB_TOOLS_ENABLED", True)
    chunks = await aggregator.gather_live_knowledge("pm kisan benefit", "scheme", "", "cid-1")
    assert chunks and chunks[0]["source"] == "gov"
    assert chunks[0]["source_url"] == "http://pmkisan"


async def test_gather_live_knowledge_disabled(monkeypatch):
    monkeypatch.setattr(settings, "WEB_TOOLS_ENABLED", False)
    assert await aggregator.gather_live_knowledge("q", "general") == []


# ── orchestrator routing ───────────────────────────────────────────────────────

def test_route_to_live_augment_when_insufficient(monkeypatch):
    from src.agents.orchestrator import _route_after_grade

    monkeypatch.setattr(settings, "WEB_TOOLS_ENABLED", True)
    monkeypatch.setattr(settings, "LIVE_AUGMENT_ENABLED", True)
    state = {"query": "highest moving stock", "domain": "finance", "intent": "",
             "sufficient": False, "knowledge": [], "rag_loops": 0, "live_augmented": False}
    assert _route_after_grade(state) == "live_augment"


def test_route_skips_live_augment_once_done(monkeypatch):
    from src.agents.orchestrator import _route_after_grade

    monkeypatch.setattr(settings, "WEB_TOOLS_ENABLED", True)
    monkeypatch.setattr(settings, "LIVE_AUGMENT_ENABLED", True)
    # Already augmented + still insufficient + no loop budget → generate (no infinite loop).
    state = {"query": "x", "domain": "general", "intent": "", "sufficient": False,
             "knowledge": [], "rag_loops": settings.RAG_MAX_LOOPS, "live_augmented": True}
    assert _route_after_grade(state) == "generate"


def test_route_generate_for_static_sufficient(monkeypatch):
    from src.agents.orchestrator import _route_after_grade

    monkeypatch.setattr(settings, "WEB_TOOLS_ENABLED", True)
    monkeypatch.setattr(settings, "LIVE_AUGMENT_ENABLED", True)
    # Static, sufficient, enough chunks, not live-y → straight to generate.
    state = {"query": "what is section 302 IPC", "domain": "legal", "intent": "",
             "sufficient": True, "knowledge": [{"text": "a"}, {"text": "b"}],
             "rag_loops": 0, "live_augmented": False}
    assert _route_after_grade(state) == "generate"
