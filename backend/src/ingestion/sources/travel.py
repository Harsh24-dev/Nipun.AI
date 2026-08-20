"""Travel/Transport domain ingestion source — IRCTC train booking basics."""

from __future__ import annotations

from src.core.logging import get_logger
from src.ingestion.sources.base import BaseIngestionSource, IngestSpec

log = get_logger("ingestion.sources.travel")


class TravelSource(BaseIngestionSource):
    domain = "travel"
    name = "travel"

    def seed_documents(self) -> list[IngestSpec]:
        d, lang = self.domain, "en"
        specs = [
            IngestSpec(d, lang, "IRCTC — booking train tickets online",
                       source_url="https://www.irctc.co.in/",
                       section="IRCTC",
                       text=("Indian Railways e-tickets are booked on the official IRCTC website or app after "
                             "creating an account. Search by source, destination, and date; select a train and "
                             "class; enter passenger details; and pay online. A valid photo ID is required "
                             "during the journey. Tatkal booking opens one day before travel. Only use the "
                             "official IRCTC site to avoid fraud.")),
            IngestSpec(d, lang, "Documents to carry while travelling in India",
                       source_url="https://www.india.gov.in/",
                       section="Travel documents",
                       text=("For domestic train and flight travel, carry a government photo ID (Aadhaar, "
                             "voter ID, driving licence, or passport) matching the ticket. For flights, reach "
                             "the airport well before departure for security checks. Keep digital copies in "
                             "DigiLocker as a backup.")),
        ]
        log.info("seed_documents_loaded", domain=d, docs=len(specs))
        return specs

    def official_sources(self) -> list[IngestSpec]:
        specs = [IngestSpec(self.domain, "en", "IRCTC", source="https://www.irctc.co.in/")]
        log.info("official_sources_loaded", domain=self.domain, docs=len(specs))
        return specs


log.debug("source_loaded", domain="travel")
