"""Career domain ingestion source — reskilling, apprenticeships, resume basics."""

from __future__ import annotations

from src.core.logging import get_logger
from src.ingestion.sources.base import BaseIngestionSource, IngestSpec

log = get_logger("ingestion.sources.career")


class CareerSource(BaseIngestionSource):
    domain = "career"
    name = "career"

    def seed_documents(self) -> list[IngestSpec]:
        d, lang = self.domain, "en"
        specs = [
            IngestSpec(d, lang, "National Apprenticeship Promotion Scheme (NAPS)",
                       source_url="https://www.apprenticeshipindia.gov.in/",
                       section="NAPS",
                       text=("The National Apprenticeship Promotion Scheme (NAPS) promotes apprenticeship "
                             "training and provides a stipend to apprentices, part of which is shared by the "
                             "government. Candidates register on the apprenticeshipindia.gov.in portal, choose "
                             "a trade, and are matched with establishments. It builds hands-on, employable skills.")),
            IngestSpec(d, lang, "Resume basics for entry-level jobs in India",
                       source_url="https://www.ncs.gov.in/",
                       section="National Career Service",
                       text=("A strong entry-level resume is one page: clear contact details, a short "
                             "objective, education, skills, and any projects or internships. Tailor the skills "
                             "to the job, use action verbs, and keep formatting simple. The National Career "
                             "Service (NCS) portal offers free career counselling and job matching.")),
        ]
        log.info("seed_documents_loaded", domain=d, docs=len(specs))
        return specs

    def official_sources(self) -> list[IngestSpec]:
        specs = [IngestSpec(self.domain, "en", "National Career Service", source="https://www.ncs.gov.in/")]
        log.info("official_sources_loaded", domain=self.domain, docs=len(specs))
        return specs


log.debug("source_loaded", domain="career")
