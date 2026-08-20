"""Tests for the citation agent (answer-first, cite-after attribution), offline."""

import pytest

from src.agents.citation import find_citations
from src.config import settings
from src.mcp.base import ToolResult
from src.safety.scoring import score_answer


class _FakeTool:
    """Stand-in for the web_search MCP tool: returns canned results, records calls."""

    def __init__(self, results):
        self._results = results
        self.calls = []

    async def call(self, params):
        self.calls.append(params.get("query"))
        return ToolResult("web_search", "ok", data={"results": self._results})


@pytest.fixture(autouse=True)
def _web_on(monkeypatch):
    monkeypatch.setattr(settings, "WEB_TOOLS_ENABLED", True)
    monkeypatch.setattr(settings, "CITATION_AGENT_ENABLED", True)
    monkeypatch.setattr(settings, "CITATION_MAX_CLAIMS", 6)


def _patch_tool(monkeypatch, tool):
    import src.mcp.tools as tools
    monkeypatch.setattr(tools, "get_tool", lambda name: tool if name == "web_search" else None)
    return tool


async def test_no_claims_not_assessable():
    result = await find_citations([], knowledge=[])
    assert not result.assessable
    assert result.coverage == 0.0


async def test_claim_already_grounded_skips_search(monkeypatch):
    tool = _patch_tool(monkeypatch, _FakeTool([]))
    knowledge = [{"text": "PM-KISAN gives eligible farmers six thousand rupees per year.",
                  "source": "pmkisan", "source_url": "https://pmkisan.gov.in"}]
    result = await find_citations(
        ["PM-KISAN gives farmers six thousand rupees per year"], knowledge=knowledge,
    )
    assert result.assessable
    assert result.claims_backed == 1
    assert result.coverage == 1.0
    assert result.new_chunks == []          # nothing searched — already grounded
    assert tool.calls == []                 # web_search never called
    assert result.citations[0]["via"] == "retrieved"


async def test_uncited_claim_gets_searched_citation(monkeypatch):
    tool = _patch_tool(monkeypatch, _FakeTool([
        {"title": "PM-KISAN scheme", "url": "https://pib.gov.in/x",
         "content": "PM-KISAN gives eligible farmers six thousand rupees per year in three instalments.",
         "source": "PIB"},
    ]))
    result = await find_citations(
        ["PM-KISAN gives farmers six thousand rupees per year"], knowledge=[],
    )
    assert result.coverage == 1.0
    assert result.claims_backed == 1
    assert len(result.new_chunks) == 1
    assert result.new_chunks[0]["source_url"] == "https://pib.gov.in/x"
    assert result.new_chunks[0]["retrieval_method"] == "citation_agent"
    assert result.citations[0]["backed"] is True
    assert result.citations[0]["via"] == "searched"
    assert tool.calls  # a search was performed


async def test_offtopic_result_does_not_count_as_citation(monkeypatch):
    _patch_tool(monkeypatch, _FakeTool([
        {"title": "Taj Mahal", "url": "https://wiki/x",
         "content": "The Taj Mahal is a marble mausoleum located in Agra.", "source": "Wikipedia"},
    ]))
    result = await find_citations(
        ["PM-KISAN gives farmers six thousand rupees per year"], knowledge=[],
    )
    assert result.coverage == 0.0
    assert result.new_chunks == []
    assert result.citations[0]["backed"] is False
    assert result.citations[0]["via"] == "unbacked"


async def test_partial_coverage(monkeypatch):
    _patch_tool(monkeypatch, _FakeTool([
        {"title": "PM-KISAN", "url": "https://pib.gov.in/x",
         "content": "PM-KISAN gives eligible farmers six thousand rupees per year.", "source": "PIB"},
    ]))
    # First claim is backed by the search result; the second is off-topic for it.
    result = await find_citations(
        ["PM-KISAN gives farmers six thousand rupees per year",
         "The scheme was launched by the finance ministry in nineteen ninety"],
        knowledge=[],
    )
    assert result.claims_total == 2
    assert 0.0 < result.coverage < 1.0


def test_scoring_uses_citation_coverage():
    knowledge = [{"text": "PM-KISAN gives farmers six thousand rupees.", "source": "PIB",
                  "source_url": "https://pib.gov.in", "relevance_score": 0.9}]
    with_cov = score_answer(
        grounding=0.8, unsupported_claims=[], knowledge=knowledge, citation_coverage=1.0,
    )
    without_cov = score_answer(
        grounding=0.8, unsupported_claims=[], knowledge=knowledge, citation_coverage=None,
    )
    assert "citation_coverage" in with_cov.signals
    assert "citation_coverage" not in without_cov.signals
    # A fully-cited answer should score at least as well as one with the signal absent.
    assert with_cov.score >= without_cov.score - 1e-9
