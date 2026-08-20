"""Tests for the VerificationSafetyGate (Phase 0 behaviour)."""

import pytest

from src.config import settings
from src.safety.gate import VerificationSafetyGate


@pytest.fixture
def gate():
    return VerificationSafetyGate()


def test_apply_disclaimers_legal(gate):
    card = {"cardType": "answer", "title": "x", "summary": "y"}
    out = gate.apply_disclaimers(card, "legal")
    assert "lawyer" in out["disclaimer"].lower()
    assert "15100" in out["disclaimer"]  # NALSA baseline surfaced


def test_apply_disclaimers_finance_and_health(gate):
    finance = gate.apply_disclaimers({"title": "x"}, "finance")
    assert "sebi" in finance["disclaimer"].lower()
    health = gate.apply_disclaimers({"title": "x"}, "health")
    assert "professional" in health["disclaimer"].lower()


def test_apply_disclaimers_does_not_overwrite(gate):
    card = {"title": "x", "disclaimer": "custom"}
    assert gate.apply_disclaimers(card, "legal")["disclaimer"] == "custom"


def test_apply_disclaimers_unknown_domain_noop(gate):
    card = {"title": "x"}
    assert "disclaimer" not in gate.apply_disclaimers(card, "farming")


def test_decide_abstain(gate, monkeypatch):
    monkeypatch.setattr(settings, "CONFIDENCE_ABSTAIN_THRESHOLD", 0.5)
    assert gate.decide_abstain(0.3)
    assert not gate.decide_abstain(0.8)
    assert not gate.decide_abstain(0.5)  # strictly below threshold abstains


def test_verify_claims_confidence(gate):
    grounded = gate.verify_claims({"summary": "answer text"}, [{"text": "src"}])
    assert grounded.confidence >= 0.5
    ungrounded = gate.verify_claims({"summary": "answer text"}, [])
    assert ungrounded.confidence < 0.5
    empty = gate.verify_claims({"summary": ""}, [])
    assert empty.confidence == 0.0


def test_safety_filter_replaces_unsafe(gate):
    card = {"cardType": "answer", "title": "normal answer"}
    out = gate.safety_filter(card, "self_harm", "en", "cid-1")
    assert out["safety_tag"] == "self_harm"
    assert out is not card


def test_safety_filter_passthrough_normal(gate):
    card = {"cardType": "answer", "title": "normal answer"}
    assert gate.safety_filter(card, "normal", "en") is card


def test_finalize_delivers_ungrounded_answer_by_default(gate, monkeypatch):
    """DELIVER-WITH-SCORE default: a thin/ungrounded answer is NOT dropped — it is
    delivered with a low confidence so the UI can warn instead of hiding it."""
    monkeypatch.setattr(settings, "ABSTAIN_ON_LOW_CONFIDENCE", False)
    card = {"cardType": "answer", "title": "x", "summary": "guessy answer"}
    out = gate.finalize(card, domain="legal", language="en", sources=[])
    assert out["abstained"] is False              # answer kept, not replaced
    assert out.get("summary") == "guessy answer"  # original content preserved
    assert "15100" in out.get("disclaimer", "")   # legal disclaimer still attached


def test_finalize_abstains_when_flag_enabled(gate, monkeypatch):
    """High-stakes mode (opt-in): the old hard block still works behind the flag."""
    monkeypatch.setattr(settings, "ABSTAIN_ON_LOW_CONFIDENCE", True)
    monkeypatch.setattr(settings, "CONFIDENCE_ABSTAIN_THRESHOLD", 0.5)
    card = {"cardType": "answer", "title": "x", "summary": "guessy answer"}
    out = gate.finalize(card, domain="legal", language="en", sources=[])
    assert out["abstained"] is True
    assert "15100" in out.get("disclaimer", "")


def test_finalize_answers_when_grounded(gate, monkeypatch):
    monkeypatch.setattr(settings, "ABSTAIN_ON_LOW_CONFIDENCE", True)
    monkeypatch.setattr(settings, "CONFIDENCE_ABSTAIN_THRESHOLD", 0.5)
    card = {"cardType": "answer", "title": "x", "summary": "grounded answer"}
    out = gate.finalize(card, domain="finance", language="en", sources=[{"text": "RBI"}])
    assert out["abstained"] is False
    assert out["confidence"] >= 0.5


def test_finalize_attaches_reliability(gate):
    """When a reliability verdict is supplied, the gate stamps it onto the card."""
    from src.safety.scoring import ReliabilityScore

    rel = ReliabilityScore(
        score=0.42, band="low", label="Low confidence — please verify",
        warn=True, signals={"grounding": 0.4}, reasons=["r"], unsupported_claims=["c"],
    )
    card = {"cardType": "answer", "title": "x", "summary": "answer"}
    out = gate.finalize(card, domain="general", language="en", reliability=rel)
    assert out["abstained"] is False
    assert out["confidence"] == 0.42
    assert out["low_confidence"] is True
    assert out["reliability"]["band"] == "low"
    assert out["reliability"]["warn"] is True


def test_finalize_safety_tag_wins_over_content(gate):
    card = {"cardType": "answer", "title": "x", "summary": "grounded", "sources": [{"text": "s"}]}
    out = gate.finalize(card, domain="health", language="en", sources=[{"text": "s"}], prescreen_tag="medical_emergency")
    assert out["safety_tag"] == "medical_emergency"
