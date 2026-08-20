"""Tests for the per-domain ingestion source registry and seed packs."""

from src.ingestion.sources import (
    INGESTION_SOURCES,
    get_sources,
    registered_domains,
)
from src.ingestion.sources.base import IngestSpec
from src.language.constants import SUPPORTED_DOMAINS


def test_registered_domains_have_collections():
    # Every domain we ingest into must have a Qdrant collection (be in SUPPORTED_DOMAINS).
    for domain in registered_domains():
        assert domain in SUPPORTED_DOMAINS, f"{domain} has no collection"


def test_every_source_yields_seed_docs():
    for domain, sources in INGESTION_SOURCES.items():
        assert sources, f"{domain} has no sources"
        for src in sources:
            specs = src.seed_documents()
            assert specs, f"{domain}/{src.name} has an empty seed pack"


def test_seed_specs_are_wellformed():
    for domain, sources in INGESTION_SOURCES.items():
        for src in sources:
            for spec in src.seed_documents():
                assert isinstance(spec, IngestSpec)
                assert spec.domain == domain          # spec domain matches its source
                assert spec.text and spec.text.strip()  # seed packs are inline text
                assert spec.title
                assert spec.source_url                 # citation url present


def test_discover_offline_vs_online():
    src = get_sources("legal")[0]
    offline = src.discover(online=False)
    online = src.discover(online=True)
    assert len(online) >= len(offline)                # online adds official URLs
    assert all(s.is_inline() for s in offline)        # offline is seed-only


def test_legal_seed_contains_expected_citations():
    # The legal seed pack must literally carry its section citations (so retrieval
    # + citation-validity checks can hit them).
    text = " ".join(s.text or "" for s in get_sources("legal")[0].seed_documents())
    assert "Section 302" in text
    assert "Section 437 CrPC" in text
    assert "15100" in text  # NALSA helpline surfaced


def test_get_sources_unknown_domain():
    assert get_sources("nonexistent") == []
