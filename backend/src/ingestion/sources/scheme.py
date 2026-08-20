"""Scheme domain ingestion source — PM-KISAN, PMAY, Sukanya Samriddhi, pensions."""

from __future__ import annotations

from src.core.logging import get_logger
from src.ingestion.sources.base import BaseIngestionSource, IngestSpec

log = get_logger("ingestion.sources.scheme")


class SchemeSource(BaseIngestionSource):
    domain = "scheme"
    name = "scheme"

    def seed_documents(self) -> list[IngestSpec]:
        d, lang = self.domain, "en"
        specs = [
            IngestSpec(d, lang, "PM-KISAN — income support for farmers",
                       source_url="https://pmkisan.gov.in/",
                       section="PM-KISAN",
                       text=("Under PM-KISAN, eligible landholding farmer families receive ₹6,000 per year "
                             "paid in three equal instalments of ₹2,000, credited directly to their bank "
                             "account via DBT. Registration is done through the PM-KISAN portal or the nearest "
                             "Common Service Centre, with Aadhaar and bank details. Certain income-tax payers "
                             "and institutional landholders are excluded.")),
            IngestSpec(d, lang, "Pradhan Mantri Awas Yojana (PMAY) — housing",
                       source_url="https://pmaymis.gov.in/",
                       section="PM Awas Yojana",
                       text=("Pradhan Mantri Awas Yojana aims to provide affordable housing. Under the credit-"
                             "linked subsidy component, eligible beneficiaries get an interest subsidy on home "
                             "loans; the rural component (PMAY-G) provides assistance to build a pucca house. "
                             "Eligibility depends on income category and not already owning a pucca house. "
                             "Verify details on the official PMAY portal before applying.")),
            IngestSpec(d, lang, "Sukanya Samriddhi Yojana — girl child savings",
                       source_url="https://www.nsiindia.gov.in/",
                       section="Sukanya Samriddhi",
                       text=("Sukanya Samriddhi Yojana is a small-savings scheme for a girl child under age 10. "
                             "A guardian can open one account per girl (maximum two per family) at a post "
                             "office or authorised bank with a minimum ₹250 and maximum ₹1.5 lakh per year. "
                             "The account matures 21 years from opening and interest is tax-free.")),
        ]
        log.info("seed_documents_loaded", domain=d, docs=len(specs))
        return specs

    def official_sources(self) -> list[IngestSpec]:
        specs = [
            IngestSpec(self.domain, "en", "myScheme portal",
                       source="https://www.myscheme.gov.in/"),
        ]
        log.info("official_sources_loaded", domain=self.domain, docs=len(specs))
        return specs


log.debug("source_loaded", domain="scheme")
