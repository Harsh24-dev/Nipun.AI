"""
VerificationSafetyGate — the single choke point EVERY response passes through
before delivery.

Responsibilities:
  (a) verify_claims  — check each factual claim against retrieved evidence and
      compute an aggregate confidence.
  (b) decide_abstain — abstain below CONFIDENCE_ABSTAIN_THRESHOLD.
  (c) apply_disclaimers — attach the domain disclaimer centrally (not in prompts).
  (d) safety_filter  — replace unsafe responses with safe-path handler cards.

This file implements (c) disclaimers + (b) abstain plumbing + (d) filter. (a)
verify_claims is a documented passthrough stub — it computes a coarse confidence
from whether the draft is backed by any sources, and leaves atomic claim
extraction + per-claim entailment checking as an explicit TODO.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog

from src.config import settings
from src.core.metrics import (
    ABSTENTIONS_TOTAL,
    RELIABILITY_BAND_TOTAL,
    RELIABILITY_SCORE,
    SAFETY_GATE_TOTAL,
)
from src.safety.handlers import build_safe_card
from src.safety.scoring import ReliabilityScore

log = structlog.get_logger("safety.gate")

# Domain disclaimers attached centrally by the gate — NEVER baked into agent prompts.
_DISCLAIMERS: dict[str, str] = {
    "legal": (
        "This is general legal information, not legal advice. Please consult a lawyer for "
        "your specific case. Free legal aid is available from NALSA — helpline 15100."
    ),
    "finance": (
        "This is general financial information, not personalised investment advice. "
        "Consult a SEBI-registered advisor before making investment decisions. Never share "
        "your OTP, PIN, or password with anyone."
    ),
    "health": (
        "This is general health information, not a medical diagnosis or prescription. "
        "Please consult a licensed medical professional for your specific situation."
    ),
    "scheme": (
        "Scheme eligibility and benefits change over time. Verify details on the official "
        "government portal before applying."
    ),
    "career": (
        "This is general guidance, not a guarantee of any outcome. Verify course and "
        "eligibility details with the official institution."
    ),
}


@dataclass
class VerificationResult:
    supported: list[str] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)
    confidence: float = 0.0
    # Marker so callers/telemetry know claim-level checking isn't active yet.
    method: str = "phase0_passthrough"


class VerificationSafetyGate:
    """Stateless gate. Instantiate once and call per response."""

    def verify_claims(self, draft: dict, sources: list[dict]) -> VerificationResult:
        """
        Check the draft's factual claims against retrieved evidence.

        Passthrough heuristic — confidence is derived from whether the draft
        is backed by any sources at all. This is NOT claim-level verification.

        TODO: extract atomic factual claims from the draft, check each against
        its cited chunk via NLI/entailment, mark unsupported claims, and compute an
        aggregate confidence from the supported/unsupported ratio.
        """
        has_sources = bool(sources) or bool(draft.get("sources"))
        summary = (draft.get("summary") or "").strip()
        has_content = len(summary) > 0 or bool(draft.get("steps") or draft.get("schemes"))

        if not has_content:
            confidence = 0.0
        elif has_sources:
            confidence = 0.75          # grounded-ish; refined per-claim later
        else:
            confidence = 0.35          # no sources → low confidence, likely abstain

        return VerificationResult(confidence=confidence)

    def decide_abstain(self, confidence: float) -> bool:
        """True when confidence is below the configured abstention threshold."""
        return confidence < settings.CONFIDENCE_ABSTAIN_THRESHOLD

    def attach_reliability(self, card: dict, reliability: ReliabilityScore) -> dict:
        """DELIVER-WITH-SCORE: stamp the calibrated reliability verdict onto the card
        instead of dropping the answer. The UI reads `reliability` + `low_confidence`
        to badge the answer and (when `warn`) show an 'unsure of this answer' notice."""
        card["confidence"] = round(reliability.score, 3)
        card["reliability"] = reliability.to_card()
        # Flat mirror of the warn bit so even a minimal client can gate a banner on it.
        card["low_confidence"] = bool(reliability.warn)
        card.setdefault("abstained", False)
        RELIABILITY_SCORE.observe(reliability.score)
        RELIABILITY_BAND_TOTAL.labels(band=reliability.band).inc()
        log.info(
            "reliability_scored",
            score=round(reliability.score, 3),
            band=reliability.band,
            warn=reliability.warn,
        )
        return card

    def apply_disclaimers(self, card: dict, domain: str) -> dict:
        """Attach the domain disclaimer centrally if one exists and none is set."""
        disclaimer = _DISCLAIMERS.get(domain)
        if disclaimer and not card.get("disclaimer"):
            card["disclaimer"] = disclaimer
            SAFETY_GATE_TOTAL.labels(outcome="disclaimer_attached").inc()
        return card

    def build_abstention_card(self, domain: str, language: str, correlation_id: str = "") -> dict:
        """
        Build a GROUNDED-OR-ABSTAIN card: we lack a reliable source, so we say so and
        point to an official channel instead of guessing.
        """
        from src.language.detector import fallback_message

        card = {
            "cardType": "answer",
            "language": language,
            "title": fallback_message(language, "abstain_title"),
            "summary": fallback_message(language, "abstain_summary"),
            "abstained": True,
            "confidence": 0.0,
            "sources": None,
            "correlation_id": correlation_id,
        }
        card = self.apply_disclaimers(card, domain)
        ABSTENTIONS_TOTAL.labels(domain=domain).inc()
        SAFETY_GATE_TOTAL.labels(outcome="abstained").inc()
        log.info("gate_abstained", domain=domain, correlation_id=correlation_id)
        return card

    def safety_filter(self, card: dict, prescreen_tag: str, language: str, correlation_id: str = "") -> dict:
        """
        If the pre-screen flagged a non-normal tag, replace the card with the
        corresponding safe-path handler card. Returns the (possibly replaced) card.
        """
        if prescreen_tag and prescreen_tag != "normal":
            return build_safe_card(prescreen_tag, language, correlation_id)
        return card

    def finalize(
        self,
        card: dict,
        domain: str,
        language: str,
        sources: list[dict] | None = None,
        prescreen_tag: str = "normal",
        correlation_id: str = "",
        verification: VerificationResult | None = None,
        reliability: ReliabilityScore | None = None,
    ) -> dict:
        """
        Run the full gate over a generated card and return the delivery-ready card.

        Order: safety filter → score reliability → attach-score-or-(optionally)-abstain
        → disclaimers.

        DELIVER-WITH-SCORE (default): a thin knowledge base no longer blocks a good
        answer. When a `reliability` verdict is provided, it is stamped onto the card
        (score + band + warn flag) and the answer is ALWAYS delivered; the UI marks
        low-reliability answers. Set ABSTAIN_ON_LOW_CONFIDENCE=True to restore the old
        hard block (kept for high-stakes deployments that prefer silence to a warned
        answer).

        Safety filtering (crisis/harm) is unconditional and unaffected — an unsafe
        query never gets a normal answer regardless of the scoring mode.
        """
        # (d) safety filter first — an unsafe query never gets a normal answer.
        filtered = self.safety_filter(card, prescreen_tag, language, correlation_id)
        if filtered is not card:
            return filtered

        # Confidence: prefer the rich reliability score; fall back to claim-verification
        # confidence, then the passthrough heuristic.
        result = verification or self.verify_claims(card, sources or [])
        confidence = reliability.score if reliability is not None else result.confidence

        # Optional hard block (off by default): high-stakes mode that still abstains.
        if settings.ABSTAIN_ON_LOW_CONFIDENCE and self.decide_abstain(confidence):
            return self.build_abstention_card(domain, language, correlation_id)

        # DELIVER-WITH-SCORE: attach the calibrated reliability verdict (or, absent one,
        # the coarse confidence) and always keep the answer.
        if reliability is not None:
            card = self.attach_reliability(card, reliability)
        else:
            card["confidence"] = round(confidence, 3)
            card.setdefault("abstained", False)

        # (c) disclaimers
        card = self.apply_disclaimers(card, domain)
        SAFETY_GATE_TOTAL.labels(outcome="answered").inc()
        return card


# Module-level singleton (stateless).
gate = VerificationSafetyGate()
