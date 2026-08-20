"""Governance/Grievance domain ingestion source — CPGRAMS, certificates."""

from __future__ import annotations

from src.core.logging import get_logger
from src.ingestion.sources.base import BaseIngestionSource, IngestSpec

log = get_logger("ingestion.sources.governance")


class GovernanceSource(BaseIngestionSource):
    domain = "governance"
    name = "governance"

    def seed_documents(self) -> list[IngestSpec]:
        d, lang = self.domain, "en"
        specs = [
            IngestSpec(d, lang, "CPGRAMS — lodging a public grievance",
                       source_url="https://pgportal.gov.in/",
                       section="CPGRAMS",
                       text=("The Centralised Public Grievance Redress and Monitoring System (CPGRAMS) lets "
                             "citizens lodge grievances against central and state government departments online "
                             "at pgportal.gov.in. Register, select the concerned department, describe the "
                             "grievance, and track it with the registration number. There is an appeal option "
                             "if you are not satisfied with the resolution.")),
            IngestSpec(d, lang, "Applying for common certificates (income, caste, domicile)",
                       source_url="https://www.india.gov.in/",
                       section="Citizen services",
                       text=("Income, caste, and domicile certificates are issued by the state revenue "
                             "department, usually via the state e-district portal or the local Tehsil/SDM "
                             "office. Typical documents include identity proof, address proof, and a self-"
                             "declaration. Processing time and fees vary by state; check your state e-district portal.")),
        ]
        log.info("seed_documents_loaded", domain=d, docs=len(specs))
        return specs

    def official_sources(self) -> list[IngestSpec]:
        specs = [IngestSpec(self.domain, "en", "CPGRAMS portal", source="https://pgportal.gov.in/")]
        log.info("official_sources_loaded", domain=self.domain, docs=len(specs))
        return specs


log.debug("source_loaded", domain="governance")
