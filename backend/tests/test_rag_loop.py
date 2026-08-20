"""Tests for the agentic-RAG loop building blocks (grading + verification, offline)."""

import pytest

from src.agents.grading import _heuristic_grade, _keyword_overlap, grade_documents
from src.config import settings
from src.safety.verification import _heuristic, verify_claims


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch):
    monkeypatch.setattr(settings, "RAG_GRADE_USE_LLM", False)
    monkeypatch.setattr(settings, "VERIFY_CLAIMS_USE_LLM", False)
    monkeypatch.setattr(settings, "RAG_SUFFICIENCY_MIN_CHUNKS", 1)


def test_keyword_overlap():
    assert _keyword_overlap("bail under section 302", "Section 302 IPC bail procedure") > 0.3
    assert _keyword_overlap("crop insurance premium", "unrelated legal text about tenancy") < 0.2


def test_heuristic_grade_keeps_relevant():
    knowledge = [
        {"text": "PM-KISAN gives farmers 6000 rupees per year", "source": "pmkisan"},
        {"text": "The Taj Mahal is in Agra", "source": "wiki"},
    ]
    result = _heuristic_grade("how much money does PM-KISAN give farmers", knowledge)
    assert result.kept
    assert result.sufficient
    assert any("PM-KISAN" in k["text"] for k in result.kept)


def test_heuristic_grade_floor_keeps_top_when_none_match():
    knowledge = [{"text": "completely unrelated content here", "source": "x"}]
    result = _heuristic_grade("quantum chromodynamics", knowledge)
    assert len(result.kept) == 1  # floor: keep top-1 rather than nothing


async def test_grade_documents_empty():
    result = await grade_documents("anything", [])
    assert result.kept == []
    assert not result.sufficient


async def test_grade_documents_heuristic_path():
    knowledge = [{"text": "Section 302 IPC punishes murder", "source": "ipc"}]
    result = await grade_documents("what is section 302 IPC", knowledge)
    assert result.method == "heuristic"
    assert result.kept


def test_verify_heuristic_supported():
    knowledge = [{"text": "PM-KISAN gives farmers six thousand rupees per year in three instalments."}]
    result = _heuristic("PM-KISAN gives farmers six thousand rupees per year.", "\n".join(k["text"] for k in knowledge))
    assert result.confidence >= 0.5
    assert not result.unsupported


def test_verify_no_evidence_is_not_verifiable_not_refuted():
    # With no evidence retrieved there is nothing to entail against. This must be treated
    # as "not verifiable from sources" (a modest confidence that clears the abstain
    # threshold) — NOT as "refuted" (0.0 → abstain). Regression guard for the bug where
    # good parametric answers were discarded whenever the knowledge base was thin.
    result = _heuristic("The scheme gives ten lakh rupees to everyone instantly.", "")
    assert result.method == "heuristic_no_evidence"
    assert result.confidence == settings.VERIFY_NO_EVIDENCE_CONFIDENCE
    assert result.confidence >= settings.CONFIDENCE_ABSTAIN_THRESHOLD  # does NOT abstain


def test_verify_evidence_present_but_ungrounded_abstains():
    # Evidence IS present (above VERIFY_MIN_EVIDENCE_CHARS) but supports none of the
    # claims → genuine hallucination signal → confidence 0.0 → abstain.
    evidence = (
        "PM-KISAN provides income support of six thousand rupees per year to eligible "
        "farmer families across India, paid in three equal instalments directly into "
        "their bank accounts. Eligibility is based on land-holding records maintained by "
        "the state governments, with several exclusion categories such as income-tax payers."
    )
    assert len(evidence) >= settings.VERIFY_MIN_EVIDENCE_CHARS
    result = _heuristic("Every citizen receives a free car and ten lakh rupees today.", evidence)
    assert result.confidence == 0.0  # nothing grounded → abstain


async def test_verify_claims_no_evidence_low_confidence():
    result = await verify_claims("Some confident but ungrounded factual statement about tax rates.", [])
    assert result.confidence < 0.75  # ungrounded → not high confidence, but answerable
