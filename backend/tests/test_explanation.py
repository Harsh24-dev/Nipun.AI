"""Tests for adaptive-explanation synthesis (Phase 5) — offline, deterministic."""

from src.synthesis.explanation import (
    build_explanation_plan,
    enrich_card,
    learner_from_profile,
    synthesis_directive,
)
from src.synthesis.preferences import _aggregate


def test_learner_defaults_and_assumptions():
    learner = learner_from_profile({}, "hi")
    assert learner.persona == "general"
    assert learner.assumptions  # states its assumptions when the profile is thin


def test_learner_student_from_occupation():
    learner = learner_from_profile({"occupation": "Class 10 student"}, "en")
    assert learner.persona == "student"
    assert learner.reading_level == "simple"


def test_modality_prose_is_default_for_explain():
    plan = build_explanation_plan("explain what is inflation", "finance", {}, "en")
    assert plan.modality == "prose"
    assert plan.rejected_visual  # logs that a visual was considered but rejected


def test_modality_comparison_for_compare():
    plan = build_explanation_plan("compare PPF and NPS", "finance", {}, "en")
    assert plan.modality == "comparison_table"


def test_modality_steps_for_howto():
    plan = build_explanation_plan("how to apply for PM-KISAN", "scheme", {}, "en")
    assert plan.modality == "step_cards"


def test_modality_timeline_for_roadmap():
    plan = build_explanation_plan("give me a roadmap to become a data analyst", "career", {}, "en")
    assert plan.modality == "timeline"


def test_depth_quick_and_mastery():
    assert build_explanation_plan("briefly what is GST", "finance", {}, "en").depth == "quick"
    assert build_explanation_plan("explain GST in detail", "finance", {}, "en").depth == "mastery"


def test_preference_modality_wins():
    profile = {"preferences": {"modality": "diagram"}}
    plan = build_explanation_plan("how to apply for PM-KISAN", "scheme", profile, "en")
    assert plan.modality == "diagram"


def test_enrich_card_adds_affordances():
    plan = build_explanation_plan("explain compound interest", "finance", {}, "en")
    card = {"cardType": "answer", "language": "en", "title": "t",
            "summary": "Compound interest grows on interest. Over time it accelerates."}
    out = enrich_card(card, plan, "explain compound interest", "finance")
    assert out["key_takeaway"]
    assert "simpler" in out["explain_differently"]
    assert "in_en" in out["explain_differently"]


def test_enrich_card_student_gets_self_check():
    profile = {"occupation": "Class 10 student"}
    plan = build_explanation_plan("explain Newton's second law", "student", profile, "en")
    card = {"cardType": "answer", "language": "en", "title": "t", "summary": "F=ma."}
    out = enrich_card(card, plan, "explain Newton's second law", "student")
    assert out.get("understanding_check")


def test_synthesis_directive_reflects_reading_level():
    plan = build_explanation_plan("explain inflation", "finance", {"occupation": "student"}, "en")
    directive = synthesis_directive(plan)
    assert "reading level" in directive.lower()


def test_preference_aggregation():
    rows = [
        {"rating": 1, "response_card": {"cardType": "comparison_table", "depth": "working", "summary": "x" * 500}},
        {"rating": 1, "response_card": {"cardType": "comparison_table", "depth": "working", "summary": "y" * 500}},
    ]
    prefs = _aggregate(rows)
    assert prefs.get("modality") == "comparison_table"
    assert prefs.get("preferred_length") == "long"
