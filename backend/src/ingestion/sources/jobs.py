"""Jobs/Employment domain ingestion source — MGNREGA, NCS."""

from __future__ import annotations

from src.core.logging import get_logger
from src.ingestion.sources.base import BaseIngestionSource, IngestSpec

log = get_logger("ingestion.sources.jobs")


class JobsSource(BaseIngestionSource):
    domain = "jobs"
    name = "jobs"

    def seed_documents(self) -> list[IngestSpec]:
        d, lang = self.domain, "en"
        specs = [
            IngestSpec(d, lang, "MGNREGA — guaranteed rural employment",
                       source_url="https://nrega.nic.in/",
                       section="MGNREGA",
                       text=("The Mahatma Gandhi National Rural Employment Guarantee Act (MGNREGA) guarantees "
                             "at least 100 days of wage employment in a financial year to every rural household "
                             "whose adults volunteer for unskilled manual work. Apply for a job card at the Gram "
                             "Panchayat; wages are paid into the worker's bank/post-office account. No fee is "
                             "required to apply.")),
            IngestSpec(d, lang, "National Career Service (NCS) — job search and counselling",
                       source_url="https://www.ncs.gov.in/",
                       section="National Career Service",
                       text=("The National Career Service (NCS) portal offers free registration for jobseekers, "
                             "job matching, career counselling, and links to skill training. Genuine government "
                             "recruitment never asks for a fee to apply — treat any such demand as a scam.")),
        ]
        log.info("seed_documents_loaded", domain=d, docs=len(specs))
        return specs

    def official_sources(self) -> list[IngestSpec]:
        specs = [IngestSpec(self.domain, "en", "MGNREGA portal", source="https://nrega.nic.in/")]
        log.info("official_sources_loaded", domain=self.domain, docs=len(specs))
        return specs


log.debug("source_loaded", domain="jobs")
