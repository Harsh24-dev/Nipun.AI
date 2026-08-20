"""
Cross-source corroboration — "do INDEPENDENT sources agree?"

The intuition (and it is a sound one): when the static knowledge base has no
authoritative document for a query, a fact stated identically by several *independent*
sources is very likely correct. This is triangulation — the same principle journalism
and intelligence analysis use.

The one trap this module is built to avoid is FALSE corroboration ("citogenesis"):
fifty blogs all copying one wrong Wikipedia sentence are NOT fifty independent
witnesses — they are one. So corroboration here is counted per *independent publisher*,
keyed by the registrable host of the source URL (and the tool family for tool output
without a URL). Two chunks from the same host count once.

For each atomic claim in the answer we count how many independent publishers state it;
a claim backed by ≥ CORROBORATION_MIN_SOURCES independent publishers is "corroborated".
The aggregate feeds the reliability score as its own signal and, when strong, lets a
well-corroborated answer read as reliable even without a single official document.

Entailment here is deterministic token-overlap (cheap, always available, no LLM call) —
the claims themselves were already extracted by verify_claims, so this adds no LLM cost.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

import structlog

from src.config import settings

log = structlog.get_logger("safety.corroboration")

# Public suffixes we must NOT treat as the registrable domain — otherwise every
# "*.gov.in" or "*.co.in" site would collapse into ONE publisher and destroy the
# independence count. We keep the label *before* these as part of the key.
_MULTI_LABEL_SUFFIXES = (
    "gov.in", "nic.in", "co.in", "ac.in", "res.in", "org.in", "net.in", "edu.in",
    "co.uk", "org.uk", "gov.uk", "com.au", "co.jp",
)

_TOKEN = re.compile(r"[a-z0-9ऀ-ൿ]+")


def _tokens(text: str) -> list[str]:
    return [t for t in _TOKEN.findall((text or "").lower()) if len(t) > 2]


def _registrable_host(url: str) -> str:
    """Best-effort registrable domain, e.g.
       https://www.pib.gov.in/x → pib.gov.in ; https://blog.example.com → example.com.
    Keeps enough labels to distinguish independent publishers under multi-label TLDs."""
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        host = ""
    if not host:
        return ""
    if host.startswith("www."):
        host = host[4:]
    labels = host.split(".")
    for suffix in _MULTI_LABEL_SUFFIXES:
        s = suffix.split(".")
        if labels[-len(s):] == s and len(labels) > len(s):
            return ".".join(labels[-(len(s) + 1):])  # publisher label + multi-label TLD
    # Default: last two labels (example.com).
    return ".".join(labels[-2:]) if len(labels) >= 2 else host


def independence_key(chunk: dict) -> str:
    """A stable key for the INDEPENDENT publisher behind a chunk. Distinct hosts →
    distinct keys; live-tool chunks without a URL fall back to their source/tool name."""
    host = _registrable_host(str(chunk.get("source_url") or ""))
    if host:
        return f"host:{host}"
    source = str(chunk.get("source") or "").strip().lower()
    if source:
        return f"src:{source}"
    return f"tool:{chunk.get('retrieval_method') or chunk.get('chunk_id') or 'unknown'}"


def _claim_supported_by(claim: str, texts: list[str]) -> bool:
    """Deterministic entailment: ≥ 60% of the claim's salient tokens appear in the
    combined text of a single publisher. Stricter than the 50% grounding check because
    corroboration should demand a clearer match before counting a second witness."""
    toks = _tokens(claim)
    if not toks:
        return False
    blob = " ".join(texts).lower()
    present = sum(1 for t in toks if t in blob)
    return present / len(toks) >= 0.6


@dataclass
class CorroborationResult:
    score: float = 0.0                 # 0..1 corroboration confidence
    independent_sources: int = 0       # distinct independent publishers in the pool
    agreement: float = 0.0             # fraction of claims backed by ≥ min independents
    corroborated_claims: list[str] = field(default_factory=list)
    contested_claims: list[str] = field(default_factory=list)
    assessable: bool = False           # False when there was nothing to corroborate
    method: str = "overlap"

    @property
    def strong(self) -> bool:
        """Multiple independent publishers agree on most claims → 'highly probable'."""
        return (
            self.assessable
            and self.independent_sources >= settings.CORROBORATION_MIN_SOURCES
            and self.agreement >= settings.CORROBORATION_AGREEMENT_THRESHOLD
        )


def _support_to_score(n_independent: int) -> float:
    """Diminishing-returns map from #independent supporters to a per-claim score."""
    if n_independent <= 0:
        return 0.0
    if n_independent == 1:
        return 0.5      # one witness — better than nothing, far from confirmed
    if n_independent == 2:
        return 0.8      # two independent witnesses agree
    return 1.0          # three or more → confirmed


def corroborate(claims: list[str], knowledge: list[dict]) -> CorroborationResult:
    """Measure independent-source agreement for a set of claims over a knowledge pool.

    claims    — the answer's atomic claims (reuse verify_claims' supported+unsupported).
    knowledge — the FULL retrieved pool (static + live), each carrying source/source_url.
    """
    if not settings.CORROBORATION_ENABLED or not claims or not knowledge:
        return CorroborationResult(assessable=False)

    # Group chunk texts by independent publisher.
    groups: dict[str, list[str]] = {}
    for k in knowledge:
        groups.setdefault(independence_key(k), []).append(str(k.get("text") or ""))
    n_groups = len(groups)
    if n_groups < 2:
        # Only one publisher (or none) — corroboration is not meaningful here.
        return CorroborationResult(independent_sources=n_groups, assessable=False)

    per_claim_scores: list[float] = []
    corroborated: list[str] = []
    contested: list[str] = []
    min_needed = settings.CORROBORATION_MIN_SOURCES
    for claim in claims:
        supporters = sum(1 for texts in groups.values() if _claim_supported_by(claim, texts))
        per_claim_scores.append(_support_to_score(supporters))
        if supporters >= min_needed:
            corroborated.append(claim)
        elif supporters <= 1:
            contested.append(claim)

    score = sum(per_claim_scores) / len(per_claim_scores) if per_claim_scores else 0.0
    agreement = len(corroborated) / len(claims) if claims else 0.0
    log.info(
        "corroboration_measured",
        independent_sources=n_groups, claims=len(claims),
        corroborated=len(corroborated), contested=len(contested),
        score=round(score, 4), agreement=round(agreement, 4),
    )
    return CorroborationResult(
        score=score,
        independent_sources=n_groups,
        agreement=agreement,
        corroborated_claims=corroborated,
        contested_claims=contested,
        assessable=True,
        method="overlap",
    )
