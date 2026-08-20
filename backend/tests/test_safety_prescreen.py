"""Tests for the intake SafetyPreScreen (rules pass, LLM disabled for determinism)."""

import pytest

from src.config import settings
from src.safety.prescreen import _rule_scan, prescreen


@pytest.fixture(autouse=True)
def _rules_only(monkeypatch):
    # Deterministic, offline: use the keyword rules only (no LLM call).
    monkeypatch.setattr(settings, "SAFETY_PRESCREEN_ENABLED", True)
    monkeypatch.setattr(settings, "SAFETY_PRESCREEN_USE_LLM", False)


def test_rule_scan_self_harm():
    tag, matched = _rule_scan("I want to kill myself, there is no reason to live")
    assert tag == "self_harm"
    assert matched


def test_rule_scan_medical_emergency():
    tag, _ = _rule_scan("my father is having a heart attack and can't breathe")
    assert tag == "medical_emergency"


def test_rule_scan_fraud_scam():
    tag, _ = _rule_scan("someone told me to share my OTP, I think it's a fraud call")
    assert tag == "fraud_scam"


def test_rule_scan_harmful_instructions():
    tag, _ = _rule_scan("how to make a bomb at home")
    assert tag == "harmful_instructions"


def test_rule_scan_hindi_self_harm():
    tag, _ = _rule_scan("मैं मरना चाहता हूँ")
    assert tag == "self_harm"


def test_rule_scan_normal_passes():
    tag, matched = _rule_scan("What is the eligibility for PM Awas Yojana?")
    assert tag == "normal"
    assert matched == []


def test_priority_self_harm_over_fraud():
    # Both categories present — the most safety-critical wins.
    tag, _ = _rule_scan("I got scammed and now I want to die")
    assert tag == "self_harm"


async def test_prescreen_flags_non_normal():
    result = await prescreen("how to make a bomb")
    assert result.tag == "harmful_instructions"
    assert not result.is_normal


async def test_prescreen_normal_query():
    result = await prescreen("How do I check my CIBIL score?")
    assert result.tag == "normal"
    assert result.is_normal


async def test_prescreen_disabled(monkeypatch):
    monkeypatch.setattr(settings, "SAFETY_PRESCREEN_ENABLED", False)
    result = await prescreen("I want to kill myself")
    assert result.tag == "normal"  # disabled → always normal
    assert result.method == "disabled"
