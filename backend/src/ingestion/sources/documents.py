"""Documents domain ingestion source — Aadhaar, PAN, DigiLocker."""

from __future__ import annotations

from src.core.logging import get_logger
from src.ingestion.sources.base import BaseIngestionSource, IngestSpec

log = get_logger("ingestion.sources.documents")


class DocumentsSource(BaseIngestionSource):
    domain = "documents"
    name = "documents"

    def seed_documents(self) -> list[IngestSpec]:
        d, lang = self.domain, "en"
        specs = [
            IngestSpec(d, lang, "Updating your Aadhaar details",
                       source_url="https://uidai.gov.in/",
                       section="UIDAI",
                       text=("Aadhaar details such as address can be updated online on the UIDAI Self Service "
                             "Update Portal using an OTP sent to your registered mobile number, or in person at "
                             "an Aadhaar Seva Kendra. Name, date of birth, and biometric updates may require a "
                             "visit. Never share your Aadhaar OTP with anyone — UIDAI never asks for it by call.")),
            IngestSpec(d, lang, "Applying for a PAN card",
                       source_url="https://www.incometax.gov.in/",
                       section="Income Tax Department",
                       text=("A Permanent Account Number (PAN) is issued by the Income Tax Department and can be "
                             "applied for online via the NSDL/Protean or UTIITSL portals, or instant e-PAN using "
                             "Aadhaar on the income-tax e-filing portal. You need proof of identity, address, and "
                             "date of birth. e-PAN via Aadhaar is free and issued quickly.")),
            IngestSpec(d, lang, "DigiLocker — storing official documents",
                       source_url="https://www.digilocker.gov.in/",
                       section="DigiLocker",
                       text=("DigiLocker is a government platform to store and share issued documents such as "
                             "driving licence, vehicle RC, and academic certificates digitally. Sign up with your "
                             "Aadhaar-linked mobile number. Documents fetched from issuers in DigiLocker are "
                             "legally at par with the original physical documents.")),
        ]
        log.info("seed_documents_loaded", domain=d, docs=len(specs))
        return specs

    def official_sources(self) -> list[IngestSpec]:
        specs = [IngestSpec(self.domain, "en", "DigiLocker", source="https://www.digilocker.gov.in/")]
        log.info("official_sources_loaded", domain=self.domain, docs=len(specs))
        return specs


log.debug("source_loaded", domain="documents")
