"""Student domain ingestion source — NCERT concepts, scholarships."""

from __future__ import annotations

from src.core.logging import get_logger
from src.ingestion.sources.base import BaseIngestionSource, IngestSpec

log = get_logger("ingestion.sources.student")


class StudentSource(BaseIngestionSource):
    domain = "student"
    name = "student"

    def seed_documents(self) -> list[IngestSpec]:
        d, lang = self.domain, "en"
        specs = [
            IngestSpec(d, lang, "NCERT Class 10 Science — Newton's laws of motion",
                       source_url="https://ncert.nic.in/",
                       section="NCERT Class 10 Science",
                       text=("Newton's three laws of motion: (1) an object stays at rest or in uniform motion "
                             "unless acted on by a net external force (inertia); (2) force equals mass times "
                             "acceleration, F = ma; (3) every action has an equal and opposite reaction. A "
                             "common example: a ball rolling on the ground slows and stops because of the "
                             "unbalanced force of friction.")),
            IngestSpec(d, lang, "NCERT Class 10 Mathematics — quadratic formula",
                       source_url="https://ncert.nic.in/",
                       section="NCERT Class 10 Mathematics",
                       text=("A quadratic equation ax^2 + bx + c = 0 (a not 0) can be solved with the "
                             "quadratic formula x = (-b +/- sqrt(b^2 - 4ac)) / 2a. The discriminant "
                             "D = b^2 - 4ac tells the nature of the roots: D > 0 gives two distinct real "
                             "roots, D = 0 gives two equal real roots, and D < 0 gives no real roots.")),
            IngestSpec(d, lang, "National Scholarship Portal (NSP)",
                       source_url="https://scholarships.gov.in/",
                       section="National Scholarship Portal",
                       text=("The National Scholarship Portal (NSP) is a single-window platform for central and "
                             "state government scholarships, including pre-matric and post-matric schemes for "
                             "SC/ST/OBC/minority and merit-cum-means scholarships. Students apply online with "
                             "Aadhaar, bank details, and institution verification during the annual window.")),
        ]
        log.info("seed_documents_loaded", domain=d, docs=len(specs))
        return specs

    def official_sources(self) -> list[IngestSpec]:
        specs = [
            IngestSpec(self.domain, "en", "NCERT",
                       source="https://ncert.nic.in/textbook.php"),
        ]
        log.info("official_sources_loaded", domain=self.domain, docs=len(specs))
        return specs


log.debug("source_loaded", domain="student")
