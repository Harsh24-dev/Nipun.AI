"""Health domain ingestion source — Ayushman Bharat, immunization, nutrition."""

from __future__ import annotations

from src.core.logging import get_logger
from src.ingestion.sources.base import BaseIngestionSource, IngestSpec

log = get_logger("ingestion.sources.health")


class HealthSource(BaseIngestionSource):
    domain = "health"
    name = "health"

    def seed_documents(self) -> list[IngestSpec]:
        d, lang = self.domain, "en"
        specs = [
            IngestSpec(d, lang, "Ayushman Bharat PM-JAY — health cover",
                       source_url="https://pmjay.gov.in/",
                       section="Ayushman Bharat",
                       text=("Ayushman Bharat PM-JAY provides eligible families health cover of up to ₹5 lakh "
                             "per family per year for secondary and tertiary hospitalisation at empanelled "
                             "public and private hospitals. Eligibility is based on the SECC database; the "
                             "scheme is cashless and paperless at the point of care. Check eligibility on the "
                             "official PM-JAY portal or at a Common Service Centre. This is general "
                             "information, not medical advice.")),
            IngestSpec(d, lang, "Universal Immunization Programme — child vaccination",
                       source_url="https://www.mohfw.gov.in/",
                       section="Universal Immunization Programme",
                       text=("India's Universal Immunization Programme provides free vaccines to children "
                             "against diseases including tuberculosis (BCG), polio, diphtheria, pertussis, "
                             "tetanus, hepatitis B, and measles-rubella. Vaccination is given at government "
                             "health centres per the national immunization schedule. Consult a licensed "
                             "medical professional for your child's specific schedule.")),
            IngestSpec(d, lang, "Anaemia and iron-rich nutrition — general information",
                       source_url="https://www.mohfw.gov.in/",
                       section="MoHFW",
                       text=("Anaemia, often due to iron deficiency, is common among women and children in "
                             "India. Iron-rich foods include green leafy vegetables, jaggery, legumes, and "
                             "fortified cereals; vitamin-C-rich foods aid iron absorption. Government "
                             "programmes provide iron-folic-acid supplements. For diagnosis and treatment, "
                             "consult a licensed doctor — this is informational only, not a prescription.")),
        ]
        log.info("seed_documents_loaded", domain=d, docs=len(specs))
        return specs

    def official_sources(self) -> list[IngestSpec]:
        specs = [
            IngestSpec(self.domain, "en", "Ministry of Health & Family Welfare",
                       source="https://www.mohfw.gov.in/"),
        ]
        log.info("official_sources_loaded", domain=self.domain, docs=len(specs))
        return specs


log.debug("source_loaded", domain="health")
