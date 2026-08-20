"""Finance domain ingestion source — UPI, credit score, tax, savings, scams."""

from __future__ import annotations

from src.core.logging import get_logger
from src.ingestion.sources.base import BaseIngestionSource, IngestSpec

log = get_logger("ingestion.sources.finance")


class FinanceSource(BaseIngestionSource):
    domain = "finance"
    name = "finance"

    def seed_documents(self) -> list[IngestSpec]:
        d, lang = self.domain, "en"
        specs = [
            IngestSpec(d, lang, "UPI safety — never share your PIN or OTP",
                       source_url="https://www.npci.org.in/what-we-do/upi/product-overview",
                       section="NPCI UPI",
                       text=("UPI (Unified Payments Interface) by NPCI lets you send money instantly using a "
                             "UPI PIN. You NEVER need to enter your UPI PIN to RECEIVE money — anyone asking "
                             "you to enter a PIN or share an OTP 'to receive' funds is running a scam. Never "
                             "share your OTP, UPI PIN, or card CVV with anyone, including callers claiming to "
                             "be from your bank.")),
            IngestSpec(d, lang, "Credit score (CIBIL) basics",
                       source_url="https://www.rbi.org.in/",
                       section="Credit score",
                       text=("A credit score (e.g. CIBIL) ranges from 300 to 900 and reflects your credit "
                             "repayment history. A score above 750 is generally considered good and improves "
                             "loan and credit-card eligibility. You are entitled to one free credit report per "
                             "year from each credit bureau. Paying EMIs and card bills on time and keeping "
                             "credit utilisation low improves the score.")),
            IngestSpec(d, lang, "Income Tax Return (ITR) filing basics",
                       source_url="https://www.incometax.gov.in/",
                       section="Income Tax Dept",
                       text=("Individuals whose income exceeds the basic exemption limit must file an Income "
                             "Tax Return (ITR) on the Income Tax Department e-filing portal. The usual due date "
                             "for individuals not requiring audit is 31 July of the assessment year. Salaried "
                             "taxpayers commonly use ITR-1 (Sahaj). Keep Form 16 and interest certificates "
                             "ready. This is general information, not personalised tax advice.")),
            IngestSpec(d, lang, "Public Provident Fund (PPF)",
                       source_url="https://www.nsiindia.gov.in/",
                       section="PPF",
                       text=("The Public Provident Fund (PPF) is a government-backed long-term savings scheme "
                             "with a 15-year lock-in and tax-free interest. The minimum yearly deposit is ₹500 "
                             "and the maximum is ₹1.5 lakh. Contributions qualify for deduction under Section "
                             "80C. Consult a SEBI-registered advisor for investment decisions.")),
        ]
        log.info("seed_documents_loaded", domain=d, docs=len(specs))
        return specs

    def official_sources(self) -> list[IngestSpec]:
        specs = [
            IngestSpec(self.domain, "en", "NPCI UPI product overview",
                       source="https://www.npci.org.in/what-we-do/upi/product-overview"),
        ]
        log.info("official_sources_loaded", domain=self.domain, docs=len(specs))
        return specs


log.debug("source_loaded", domain="finance")
