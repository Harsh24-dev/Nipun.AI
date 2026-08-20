"""
Per-domain ingestion source registry.

Maps each domain to its ingestion source agent(s). New domains (career, governance,
jobs, travel, documents) plug in here once their Qdrant collections exist (added with
their agents) — the runner skips any domain without a collection.
"""

from __future__ import annotations

from src.ingestion.sources.base import BaseIngestionSource, IngestSpec
from src.ingestion.sources.career import CareerSource
from src.ingestion.sources.documents import DocumentsSource
from src.ingestion.sources.farming import FarmingSource
from src.ingestion.sources.finance import FinanceSource
from src.ingestion.sources.general import GeneralSource
from src.ingestion.sources.governance import GovernanceSource
from src.ingestion.sources.health import HealthSource
from src.ingestion.sources.jobs import JobsSource
from src.ingestion.sources.legal import LegalSource
from src.ingestion.sources.scheme import SchemeSource
from src.ingestion.sources.student import StudentSource
from src.ingestion.sources.travel import TravelSource

# domain -> ordered list of source agents
INGESTION_SOURCES: dict[str, list[BaseIngestionSource]] = {
    "legal": [LegalSource()],
    "finance": [FinanceSource()],
    "health": [HealthSource()],
    "scheme": [SchemeSource()],
    "farming": [FarmingSource()],
    "student": [StudentSource()],
    "career": [CareerSource()],
    "governance": [GovernanceSource()],
    "jobs": [JobsSource()],
    "travel": [TravelSource()],
    "documents": [DocumentsSource()],
    "general": [GeneralSource()],
}


def get_sources(domain: str) -> list[BaseIngestionSource]:
    return INGESTION_SOURCES.get(domain, [])


def registered_domains() -> list[str]:
    return list(INGESTION_SOURCES.keys())


__all__ = [
    "INGESTION_SOURCES",
    "BaseIngestionSource",
    "IngestSpec",
    "get_sources",
    "registered_domains",
]
