"""Tests for cross-source corroboration (src/safety/corroboration.py).

The contract: count agreement per INDEPENDENT publisher, and never let mirrors of a
single origin masquerade as independent corroboration.
"""

from src.config import settings
from src.safety.corroboration import (
    _registrable_host,
    corroborate,
    independence_key,
)

CLAIM = "The last date to apply for the scheme is 31 March 2026"


def _chunk(url, text=CLAIM, source=""):
    return {"text": text, "source_url": url, "source": source, "relevance_score": 0.9}


# ── Publisher / independence keying ───────────────────────────────────────────

def test_registrable_host_strips_www_and_subdomains():
    assert _registrable_host("https://www.example.com/a") == "example.com"
    assert _registrable_host("https://blog.example.com/x") == "example.com"


def test_gov_subdomains_are_independent_publishers():
    # pib.gov.in and pmkisan.gov.in are DIFFERENT publishers — must not collapse to gov.in.
    assert _registrable_host("https://pib.gov.in/a") == "pib.gov.in"
    assert _registrable_host("https://pmkisan.gov.in/b") == "pmkisan.gov.in"
    assert _registrable_host("https://pib.gov.in/a") != _registrable_host("https://pmkisan.gov.in/b")


def test_independence_key_falls_back_to_source_name():
    assert independence_key({"source_url": "", "source": "Reuters"}) == "src:reuters"


# ── Corroboration logic ───────────────────────────────────────────────────────

def test_single_publisher_is_not_assessable():
    know = [_chunk("https://example.com/1"), _chunk("https://example.com/2")]
    r = corroborate([CLAIM], know)
    assert r.assessable is False
    assert r.independent_sources == 1


def test_citogenesis_mirrors_do_not_count_as_independent():
    # Same host repeated many times → still ONE witness, not corroboration.
    know = [_chunk("https://mirror.com/%d" % i) for i in range(5)]
    r = corroborate([CLAIM], know)
    assert r.independent_sources == 1
    assert r.assessable is False


def test_three_independent_sources_corroborate():
    know = [
        _chunk("https://a-news.com/x"),
        _chunk("https://b-portal.org/y"),
        _chunk("https://c-daily.net/z"),
    ]
    r = corroborate([CLAIM], know)
    assert r.assessable is True
    assert r.independent_sources == 3
    assert r.agreement == 1.0
    assert CLAIM in r.corroborated_claims
    assert r.strong is True


def test_contested_claim_when_only_one_supports():
    other = "An unrelated statement about something entirely different topic"
    know = [
        _chunk("https://a.com/x", text=CLAIM),
        _chunk("https://b.com/y", text=other),
        _chunk("https://c.com/z", text=other),
    ]
    r = corroborate([CLAIM], know)
    # Only one publisher backs CLAIM → contested, not corroborated.
    assert CLAIM in r.contested_claims
    assert r.strong is False


def test_disabled_returns_not_assessable(monkeypatch):
    monkeypatch.setattr(settings, "CORROBORATION_ENABLED", False)
    know = [_chunk("https://a.com/x"), _chunk("https://b.com/y"), _chunk("https://c.com/z")]
    assert corroborate([CLAIM], know).assessable is False
