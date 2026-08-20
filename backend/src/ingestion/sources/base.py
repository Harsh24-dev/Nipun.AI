"""
Per-domain ingestion sources.

Each domain has an ingestion "source agent" that knows WHERE its corpus comes from:
  - `seed_documents()`  — a small curated, offline pack of accurate, citable content
    so the domain corpus is never empty (works with no network). Doubles as the
    retrieval corpus the eval golden sets check against.
  - `official_sources()` — public official URLs/PDFs pulled only on an --online run.

Everything a source yields is DATA fed through the normal parse→chunk→index pipeline.
Web/PDF content is NEVER treated as instructions.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.core.logging import get_logger

log = get_logger("ingestion.sources.base")


@dataclass
class IngestSpec:
    """One document to ingest. Provide EITHER inline `text` OR a `source` url/path."""

    domain: str
    language: str
    title: str
    source: str | None = None       # http(s) url or local file path
    text: str | None = None         # inline content (offline seed packs)
    source_url: str = ""            # canonical url shown as the citation
    section: str | None = None
    metadata: dict = field(default_factory=dict)

    def is_inline(self) -> bool:
        inline = self.text is not None
        log.debug("ingest_spec_is_inline", domain=self.domain, title=self.title, inline=inline)
        return inline


class BaseIngestionSource:
    """A domain's ingestion source. Subclasses override the two provider methods."""

    domain: str = "general"
    name: str = "base"

    def seed_documents(self) -> list[IngestSpec]:
        """Offline, curated seed pack. Override in subclasses."""
        log.debug("seed_documents_base_empty", domain=self.domain, source=self.name)
        return []

    def official_sources(self) -> list[IngestSpec]:
        """Public official URLs, pulled only on --online runs. Override in subclasses."""
        log.debug("official_sources_base_empty", domain=self.domain, source=self.name)
        return []

    def discover(self, online: bool = False) -> list[IngestSpec]:
        log.info("discover_start", domain=self.domain, source=self.name, online=online)
        specs = list(self.seed_documents())
        seed_count = len(specs)
        if online:
            specs.extend(self.official_sources())
        log.info(
            "discover_complete",
            domain=self.domain,
            source=self.name,
            online=online,
            seed=seed_count,
            official=len(specs) - seed_count,
            total=len(specs),
        )
        return specs
