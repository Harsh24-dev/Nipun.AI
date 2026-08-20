"""General/fallback domain ingestion source — civic basics."""

from __future__ import annotations

from src.core.logging import get_logger
from src.ingestion.sources.base import BaseIngestionSource, IngestSpec

log = get_logger("ingestion.sources.general")


class GeneralSource(BaseIngestionSource):
    domain = "general"
    name = "general"

    def seed_documents(self) -> list[IngestSpec]:
        d, lang = self.domain, "en"
        specs = [
            IngestSpec(d, lang, "National emergency and citizen helplines",
                       source_url="https://www.india.gov.in/",
                       section="Citizen services",
                       text=("India's single emergency number is 112. Common citizen services are available "
                             "online at india.gov.in and through Common Service Centres (CSCs). Free legal aid "
                             "is provided by NALSA on helpline 15100. Always verify official information on "
                             "government (gov.in / nic.in) websites.")),
        ]
        log.info("seed_documents_loaded", domain=d, docs=len(specs))
        return specs


log.debug("source_loaded", domain="general")
