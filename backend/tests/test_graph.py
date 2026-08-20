"""Tests for the GraphRAG tier (Phase 4) — validation + fusion, offline (no Neo4j)."""

from src.graph import data
from src.graph.build import validate_legal, validate_schemes
from src.graph.retrieval import _extract_sections, graph_search, rrf_fuse
from src.graph.schema import is_valid_act, is_valid_ministry


def test_seed_legal_records_all_valid():
    accepted, rejects = validate_legal(data.LEGAL_SECTIONS)
    assert len(accepted) == len(data.LEGAL_SECTIONS)
    assert rejects == []


def test_seed_scheme_records_all_valid():
    accepted, rejects = validate_schemes(data.SCHEMES)
    assert len(accepted) == len(data.SCHEMES)
    assert rejects == []


def test_validate_legal_rejects_unknown_act():
    bad = [{"section": "1", "act": "Made Up Act"}, {"section": "302", "act": "IPC", "title": "x"}]
    accepted, rejects = validate_legal(bad)
    assert len(accepted) == 1
    assert len(rejects) == 1


def test_validate_scheme_rejects_unknown_ministry():
    bad = [{"scheme": "Fake", "ministry": "Ministry of Magic"}]
    accepted, rejects = validate_schemes(bad)
    assert accepted == []
    assert len(rejects) == 1


def test_allowlists():
    assert is_valid_act("IPC")
    assert not is_valid_act("Random Act")
    assert is_valid_ministry("Ministry of Finance")
    assert not is_valid_ministry("Ministry of Nothing")


def test_extract_sections():
    assert _extract_sections("what about Section 302 and section 438?") == ["302", "438"]
    assert _extract_sections("no sections here") == []


def test_rrf_fuse_merges_and_orders():
    vector = [{"chunk_id": "v1", "text": "a"}, {"chunk_id": "shared", "text": "b"}]
    graph = [{"chunk_id": "shared", "text": "b"}, {"chunk_id": "g1", "text": "c"}]
    fused = rrf_fuse(vector, graph)
    ids = [c["chunk_id"] for c in fused]
    assert "shared" in ids and "v1" in ids and "g1" in ids
    # 'shared' appears in both lists → highest fused score → ranked first
    assert ids[0] == "shared"
    assert len(ids) == 3  # deduped


async def test_graph_search_empty_when_unavailable():
    # Neo4j isn't initialised in tests → graph tier is unavailable → returns [].
    assert await graph_search("Section 302 IPC", "legal") == []
