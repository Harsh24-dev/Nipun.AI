"""Farming domain ingestion source — seasons, MSP, KCC, crop insurance, soil health."""

from __future__ import annotations

from src.core.logging import get_logger
from src.ingestion.sources.base import BaseIngestionSource, IngestSpec

log = get_logger("ingestion.sources.farming")


class FarmingSource(BaseIngestionSource):
    domain = "farming"
    name = "farming"

    def seed_documents(self) -> list[IngestSpec]:
        d, lang = self.domain, "en"
        specs = [
            IngestSpec(d, lang, "Cropping seasons — Kharif, Rabi, Zaid",
                       source_url="https://agricoop.gov.in/",
                       section="Cropping seasons",
                       text=("Indian agriculture has three cropping seasons. Kharif crops are sown with the "
                             "monsoon (June-July) and harvested in September-October - e.g. paddy, maize, "
                             "cotton, soybean. Rabi crops are sown in October-December and harvested in "
                             "spring - e.g. wheat, mustard, gram. Zaid crops grow in the short summer season "
                             "between Rabi and Kharif - e.g. watermelon, cucumber, fodder.")),
            IngestSpec(d, lang, "Minimum Support Price (MSP) and mandi price",
                       source_url="https://agmarknet.gov.in/",
                       section="MSP",
                       text=("The Minimum Support Price (MSP) is the guaranteed price at which the government "
                             "procures certain crops, announced by the CACP before each season. The mandi "
                             "(market) price is the actual prevailing price at the local APMC market, which "
                             "varies daily and can be checked on the Agmarknet portal. For a price query, "
                             "compare both the MSP and the current mandi price.")),
            IngestSpec(d, lang, "Kisan Credit Card (KCC)",
                       source_url="https://www.pmkisan.gov.in/kcc",
                       section="Kisan Credit Card",
                       text=("The Kisan Credit Card (KCC) gives farmers short-term credit for crop cultivation "
                             "and allied activities at a concessional interest rate, with interest subvention "
                             "for prompt repayment. Farmers can apply through their bank with land records and "
                             "identity documents. It also covers post-harvest and consumption needs.")),
            IngestSpec(d, lang, "Pradhan Mantri Fasal Bima Yojana (PMFBY) — crop insurance",
                       source_url="https://pmfby.gov.in/",
                       section="PMFBY",
                       text=("Pradhan Mantri Fasal Bima Yojana (PMFBY) provides crop insurance against yield "
                             "loss from natural calamities, pests, and disease. Farmers pay a low premium — 2% "
                             "for Kharif, 1.5% for Rabi, and 5% for commercial/horticultural crops — and the "
                             "government subsidises the rest. Enrolment is via banks or the PMFBY portal. "
                             "For technical advice, contact your nearest KVK.")),
        ]
        log.info("seed_documents_loaded", domain=d, docs=len(specs))
        return specs

    def official_sources(self) -> list[IngestSpec]:
        specs = [
            IngestSpec(self.domain, "en", "Agmarknet mandi prices",
                       source="https://agmarknet.gov.in/"),
        ]
        log.info("official_sources_loaded", domain=self.domain, docs=len(specs))
        return specs


log.debug("source_loaded", domain="farming")
