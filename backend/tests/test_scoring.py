"""Tests for the answer-reliability scoring engine (src/safety/scoring.py).

These lock in the CALIBRATION CONTRACT: the score is monotonic in each signal,
conservative when evidence is missing, and never green-badges an unverifiable or
contradicted answer.
"""

import pytest

from src.config import settings
from src.safety.scoring import ReliabilityScore, _is_authoritative, score_answer

GOV_CHUNK = {
    "text": "PM-KISAN gives eligible farmers Rs 6000 per year.",
    "source": "PM-KISAN portal",
    "source_url": "https://pmkisan.gov.in/",
    "relevance_score": 0.9,
}
WEB_CHUNK = {
    "text": "Some blog post about farming schemes.",
    "source": "randomblog.com",
    "source_url": "https://randomblog.com/post",
    "relevance_score": 0.4,
}


def _score(**kw) -> ReliabilityScore:
    base = dict(grounding=0.8, unsupported_claims=[], knowledge=[GOV_CHUNK], sufficient=True)
    base.update(kw)
    return score_answer(**base)


# ── Authority detection ───────────────────────────────────────────────────────

def test_authority_detects_gov_domains():
    assert _is_authoritative("PM-KISAN", "https://pmkisan.gov.in/")
    assert _is_authoritative("RBI notification", "https://rbi.org.in/x")
    assert _is_authoritative("Ministry of Finance", "")  # name hint, no URL
    assert not _is_authoritative("randomblog.com", "https://randomblog.com/post")


# ── Bands + warn flag ─────────────────────────────────────────────────────────

def test_strong_answer_is_high_and_no_warn():
    r = _score(grounding=0.9, knowledge=[GOV_CHUNK, GOV_CHUNK, GOV_CHUNK])
    assert r.band == "high"
    assert r.warn is False
    assert r.score >= settings.RELIABILITY_HIGH_THRESHOLD


def test_thin_ungrounded_answer_warns_but_is_not_dropped():
    # No evidence, no source, low grounding → warns, but still returns a score (never None).
    r = score_answer(grounding=0.2, unsupported_claims=["a", "b"], knowledge=[])
    assert isinstance(r, ReliabilityScore)
    assert r.warn is True
    assert r.band in ("low", "very_low")


def test_monotonic_in_grounding():
    lo = _score(grounding=0.2)
    hi = _score(grounding=0.95)
    assert hi.score > lo.score


def test_monotonic_in_source_authority():
    gov = _score(knowledge=[GOV_CHUNK])
    web = _score(knowledge=[WEB_CHUNK])
    assert gov.signals["source_authority"] > web.signals["source_authority"]
    assert gov.score > web.score


# ── Calibration guards ────────────────────────────────────────────────────────

def test_hallucination_veto_caps_score():
    # Evidence present but grounding 0.0 → contradiction → hard cap at 0.30.
    r = score_answer(grounding=0.0, unsupported_claims=["x"], knowledge=[GOV_CHUNK], sufficient=True)
    assert r.score <= 0.30
    assert r.warn is True
    assert any("do not support" in reason for reason in r.reasons)


def test_unverifiable_answer_capped_at_medium():
    # No evidence, no source, but decent parametric grounding → never "high".
    r = score_answer(grounding=1.0, unsupported_claims=[], knowledge=[], card_sources=[])
    assert r.score <= 0.60
    assert r.band != "high"
    assert any("general knowledge" in reason for reason in r.reasons)


def test_coverage_penalises_long_rewrite_chase():
    fast = _score(rag_loops=0)
    chased = _score(rag_loops=3)
    assert chased.signals["coverage"] < fast.signals["coverage"]


# ── Cross-source corroboration lift ───────────────────────────────────────────

def _independent_pool(claim, n=3):
    hosts = ["https://a-news.com/x", "https://b-portal.org/y", "https://c-daily.net/z",
             "https://d-times.com/w"]
    return [{"text": claim, "source_url": hosts[i], "source": "", "relevance_score": 0.8}
            for i in range(n)]


def test_strong_corroboration_lifts_unofficial_answer():
    from src.safety.corroboration import corroborate

    claim = "The scheme deadline is 31 March 2026 for all applicants nationwide"
    pool = _independent_pool(claim, n=3)
    corr = corroborate([claim], pool)
    assert corr.strong is True
    # No official/authoritative source, moderate grounding — but 3 independents agree.
    r = score_answer(
        grounding=0.5, unsupported_claims=[], knowledge=pool,
        sufficient=True, corroboration=corr,
    )
    assert r.score >= 0.72                       # lifted into the reliable range
    assert r.warn is False
    assert "corroboration" in r.signals
    assert any("independent sources" in reason for reason in r.reasons)


def test_corroboration_does_not_override_hallucination_veto():
    from src.safety.corroboration import corroborate

    claim = "A contradicted claim stated by several unrelated independent websites here"
    pool = _independent_pool(claim, n=3)
    corr = corroborate([claim], pool)
    # grounding 0.0 with evidence present = contradiction → veto still caps at 0.30.
    r = score_answer(grounding=0.0, unsupported_claims=[claim], knowledge=pool,
                     sufficient=True, corroboration=corr)
    assert r.score <= 0.30
    assert r.warn is True


# ── Conversational bypass ─────────────────────────────────────────────────────

def test_conversational_answer_not_applicable():
    r = score_answer(grounding=0.0, unsupported_claims=[], knowledge=[], conversational=True)
    assert r.applicable is False
    assert r.band == "not_applicable"
    assert r.warn is False


def test_no_claims_answer_not_applicable():
    r = score_answer(grounding=0.0, unsupported_claims=[], knowledge=[], had_claims=False)
    assert r.applicable is False
    assert r.warn is False


# ── Serialization ─────────────────────────────────────────────────────────────

def test_to_card_shape():
    card = _score().to_card()
    assert set(card) >= {"score", "band", "label", "warn", "applicable", "signals", "reasons"}
    assert 0.0 <= card["score"] <= 1.0
