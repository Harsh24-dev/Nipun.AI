"""Legal domain ingestion source — IPC/CrPC/BNS, RTI, consumer, cheque bounce."""

from __future__ import annotations

from src.core.logging import get_logger
from src.ingestion.sources.base import BaseIngestionSource, IngestSpec

log = get_logger("ingestion.sources.legal")


class LegalSource(BaseIngestionSource):
    domain = "legal"
    name = "legal"

    def seed_documents(self) -> list[IngestSpec]:
        d, lang = self.domain, "en"
        specs = [
            IngestSpec(d, lang, "IPC Section 302 — Punishment for murder",
                       source_url="https://www.indiacode.nic.in/ipc-302",
                       section="Section 302 IPC",
                       text=("Section 302 of the Indian Penal Code (IPC) prescribes the punishment for "
                             "murder: death or imprisonment for life, and a fine. Murder under Section 302 "
                             "is a cognizable, non-bailable offence triable by a Court of Session. Bail is "
                             "not a matter of right and is decided by the Sessions Court or High Court under "
                             "Section 437 CrPC and Section 439 CrPC.")),
            IngestSpec(d, lang, "CrPC Section 437 — Bail in non-bailable offences",
                       source_url="https://www.indiacode.nic.in/crpc-437",
                       section="Section 437 CrPC",
                       text=("Section 437 of the Code of Criminal Procedure (CrPC) governs when bail may be "
                             "granted in a non-bailable offence by a court other than the High Court or Court "
                             "of Session. Special consideration is given to persons under 16, women, and the "
                             "sick or infirm. For anticipatory bail before arrest, Section 438 CrPC applies.")),
            IngestSpec(d, lang, "Right to Information Act, 2005 — filing an application",
                       source_url="https://rti.gov.in/",
                       section="RTI Act 2005",
                       text=("Under the Right to Information Act, 2005, any citizen may request information "
                             "from a public authority by applying to its Public Information Officer (PIO) with "
                             "a fee of ₹10. The PIO must reply within 30 days. If information concerns life or "
                             "liberty, the reply is due within 48 hours. A first appeal lies to the First "
                             "Appellate Authority, then a second appeal to the Information Commission.")),
            IngestSpec(d, lang, "Section 138 Negotiable Instruments Act — cheque bounce",
                       source_url="https://www.indiacode.nic.in/ni-138",
                       section="Section 138 NI Act",
                       text=("Section 138 of the Negotiable Instruments Act, 1881 makes dishonour of a cheque "
                             "for insufficiency of funds a criminal offence. The payee must send a written "
                             "demand notice within 30 days of the cheque return memo; if the drawer fails to "
                             "pay within 15 days, a complaint may be filed within one month. Free legal aid is "
                             "available from NALSA — helpline 15100.")),
        ]
        log.info("seed_documents_loaded", domain=d, docs=len(specs))
        return specs

    def official_sources(self) -> list[IngestSpec]:
        d = self.domain
        specs = [
            IngestSpec(d, "en", "Indian Penal Code 1860",
                       source="https://www.indiacode.nic.in/bitstream/123456789/2263/1/A1860-45.pdf"),
        ]
        log.info("official_sources_loaded", domain=d, docs=len(specs))
        return specs


log.debug("source_loaded", domain="legal")
