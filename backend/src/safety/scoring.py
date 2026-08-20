"""
Answer-reliability scoring — the trust layer for EVERY delivered answer.

Design goal (why this module exists): the pipeline must NEVER silently drop a good
answer just because the static knowledge base was thin. Instead of a single
grounding number gating abstention, we compute a calibrated, multi-signal
*reliability score* for every answer, attach it to the response card, and let the UI
mark low-reliability answers ("unsure of this — please verify") rather than hiding them.

The score is a weighted blend of FOUR orthogonal signals, each in [0, 1]:

  grounding         — fraction of the answer's atomic claims entailed by evidence
                      (the primary factual-accuracy signal, from verify_claims)
  evidence_strength — how much genuinely relevant evidence backs the answer
                      (chunk count × reranker relevance)
  source_authority  — quality of the cited sources (official gov / .gov.in / .nic.in
                      and known credible domains score highest)
  coverage          — retrieval health: did we find sufficient material without an
                      excessive rewrite chase; was it freshened with live data

Calibration guards keep the score HONEST and CONSERVATIVE:
  • hallucination veto — evidence was present but grounded NOTHING → hard cap (a real
    contradiction signal must never read as "reliable").
  • unverifiable cap   — essentially no evidence and no source (a parametric answer)
    can be "medium" at best, never "high": we genuinely could not check it.
  • conversational bypass — greetings/small-talk carry no factual claims, so a
    reliability badge would be noise; these are marked not-applicable.

No score is ever *literally* 100% accurate — that is not physically possible for an
open-domain answer. What this system guarantees instead is that the score is (a)
deterministic and reproducible, (b) monotonic in each signal, and (c) conservative:
when we cannot verify, the score drops and the UI warns. That is the honest,
world-class contract — high precision on "this is reliable", and never a confident
green badge on an unverifiable claim.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import structlog

from src.config import settings

log = structlog.get_logger("safety.scoring")

if TYPE_CHECKING:
    from src.safety.corroboration import CorroborationResult

# ── Signal weights ────────────────────────────────────────────────────────────
# Two "is it actually true?" signals (grounding + corroboration) carry 0.60 of the
# weight; three "how good was the evidence pool?" signals carry 0.40. Weights are
# RENORMALISED over whichever signals are applicable for a given answer, so a
# not-assessable signal (e.g. corroboration when there's only one publisher) never
# silently drags the score down — its weight is redistributed, not counted as zero.
_W_GROUNDING = 0.38
_W_CORROBORATION = 0.22
_W_AUTHORITY = 0.16
_W_EVIDENCE = 0.14
_W_COVERAGE = 0.10
# Citation coverage — the fraction of the answer's claims the citation agent could back
# with at least one credible source. Applicable only when the citation agent ran; its
# weight is redistributed (renormalised) when it didn't, so the score is unchanged when
# the feature is off.
_W_CITATION = 0.12

# ── Authority patterns ────────────────────────────────────────────────────────
# Official Indian government + established institutional domains. A source whose URL
# host matches one of these is treated as authoritative; anything else is "general".
_AUTHORITATIVE_HOST_SUFFIXES = (
    ".gov.in", ".nic.in", ".gov", ".gob", ".edu", ".ac.in", ".res.in",
    ".rbi.org.in", ".sebi.gov.in", "who.int", ".who.int", ".un.org",
)
# Substrings that mark an authoritative source even without a clean URL (e.g. a
# citation whose "source" is a named portal). Kept lowercase for matching.
_AUTHORITATIVE_NAME_HINTS = (
    "gov.in", "nic.in", "reserve bank", "rbi", "sebi", "nalsa", "supreme court",
    "high court", "ministry of", "government of india", "gazette", "agmarknet",
    "data.gov.in", "official", "who", "world health", "ncert", "ugc", "aicte",
)

_SCHEME_URL = re.compile(r"https?://", re.IGNORECASE)


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


@dataclass
class ReliabilityScore:
    """The delivery-ready trust verdict for one answer."""

    score: float                       # calibrated composite, 0..1
    band: str                          # high | medium | low | very_low | not_applicable
    label: str                         # short human-facing label for the badge
    warn: bool                         # True → UI shows an "unsure of this answer" alert
    applicable: bool = True            # False for conversational/no-claim answers
    signals: dict[str, float] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    unsupported_claims: list[str] = field(default_factory=list)

    def to_card(self) -> dict:
        """Serialize into the response-card `reliability` object the frontend reads."""
        return {
            "score": round(self.score, 3),
            "band": self.band,
            "label": self.label,
            "warn": self.warn,
            "applicable": self.applicable,
            "signals": {k: round(v, 3) for k, v in self.signals.items()},
            "reasons": self.reasons,
            "unsupported_claims": self.unsupported_claims[:8],
        }


# ── Per-signal computation ────────────────────────────────────────────────────

def _host_matches_suffix(host: str, suffix: str) -> bool:
    """True only on a real domain match: host IS the domain or a subdomain of it.

    Guards against the `endswith` foot-gun where a bare suffix like "who.int" would
    otherwise also match "notwho.int". Works uniformly whether the configured suffix
    has a leading dot (".gov.in") or not ("who.int")."""
    bare = suffix.lstrip(".")
    return host == bare or host.endswith("." + bare)


def _is_authoritative(source: str, url: str) -> bool:
    host = ""
    if url:
        try:
            host = (urlparse(url).hostname or "").lower()
        except ValueError:
            host = ""
    if host and any(_host_matches_suffix(host, s) for s in _AUTHORITATIVE_HOST_SUFFIXES):
        return True
    blob = f"{source} {url}".lower()
    return any(h in blob for h in _AUTHORITATIVE_NAME_HINTS)


def _evidence_strength(knowledge: list[dict]) -> tuple[float, int, float]:
    """Blend how MANY relevant chunks we kept with HOW relevant they are.

    Returns (strength, chunk_count, mean_relevance). Saturates at 3 chunks so a
    corpus dump does not inflate the score past a genuinely well-supported answer."""
    if not knowledge:
        return 0.0, 0, 0.0
    n = len(knowledge)
    scores = [_clamp(float(k.get("relevance_score") or 0.0)) for k in knowledge]
    mean_rel = sum(scores) / len(scores) if scores else 0.0
    count_factor = _clamp(n / 3.0)          # 1 chunk → .33, 2 → .67, 3+ → 1.0
    strength = 0.5 * count_factor + 0.5 * mean_rel
    return _clamp(strength), n, mean_rel


def _source_authority(knowledge: list[dict], card_sources: list[dict]) -> tuple[float, int, int]:
    """Score citation quality. Returns (authority, n_sources, n_authoritative).

    Having ANY citation is a positive baseline (0.4); authoritative citations push
    toward 1.0. No citation at all → 0.0 (the answer stands on parametric knowledge)."""
    seen: list[tuple[str, str]] = []
    for k in knowledge or []:
        seen.append((str(k.get("source") or ""), str(k.get("source_url") or "")))
    for s in card_sources or []:
        if isinstance(s, dict):
            seen.append((str(s.get("text") or s.get("name") or ""), str(s.get("url") or "")))
        elif isinstance(s, str):
            seen.append((s, ""))
    # De-duplicate on (name, url).
    uniq = list({(a, b) for a, b in seen if (a or b)})
    if not uniq:
        return 0.0, 0, 0
    n_auth = sum(1 for a, b in uniq if _is_authoritative(a, b))
    auth_fraction = n_auth / len(uniq)
    authority = _clamp(0.4 + 0.6 * auth_fraction)
    return authority, len(uniq), n_auth


def _coverage(sufficient: bool, rag_loops: int, live_augmented: bool) -> float:
    """Retrieval health. Sufficient evidence found fast → high; a long rewrite chase
    or an insufficient stop → lower. A live-data top-up nudges it up (fresh sourcing)."""
    base = 0.8 if sufficient else 0.4
    base -= 0.1 * max(0, int(rag_loops))
    if live_augmented:
        base += 0.1
    return _clamp(base)


# ── Public entrypoint ─────────────────────────────────────────────────────────

def score_answer(
    *,
    grounding: float,
    unsupported_claims: list[str],
    knowledge: list[dict],
    card_sources: list[dict] | None = None,
    sufficient: bool = False,
    rag_loops: int = 0,
    live_augmented: bool = False,
    conversational: bool = False,
    had_claims: bool = True,
    corroboration: "CorroborationResult | None" = None,
    citation_coverage: float | None = None,
) -> ReliabilityScore:
    """Compute the calibrated reliability verdict for one answer.

    grounding          — verify_claims confidence (fraction of claims entailed), 0..1.
    unsupported_claims — the claims evidence did NOT back (surfaced to the user).
    knowledge          — graded chunks used for generation (carry relevance_score/source).
    card_sources       — sources the card itself cites (folded into authority).
    corroboration      — independent-source agreement (see safety/corroboration.py); when
                         assessable it becomes a signal and can lift the unverifiable cap.
    citation_coverage  — fraction of the answer's claims the citation agent backed with a
                         found source (see agents/citation.py); None when it did not run.
    conversational     — True for simple/greeting answers (reliability not applicable).
    had_claims         — False when the answer made no checkable factual claim.
    """
    card_sources = card_sources or []

    # Conversational / no-claim answers: a reliability badge would be noise. Mark
    # not-applicable so the UI can skip the warning entirely.
    if conversational or not had_claims:
        return ReliabilityScore(
            score=1.0, band="not_applicable", label="Conversational",
            warn=False, applicable=False,
            signals={}, reasons=[], unsupported_claims=[],
        )

    g = _clamp(grounding)
    e, n_chunks, mean_rel = _evidence_strength(knowledge)
    a, n_sources, n_auth = _source_authority(knowledge, card_sources)
    c = _coverage(sufficient, rag_loops, live_augmented)
    corr_assessable = bool(corroboration and corroboration.assessable)
    corr_score = _clamp(corroboration.score) if corr_assessable else 0.0
    cite_assessable = citation_coverage is not None
    cite_score = _clamp(citation_coverage) if cite_assessable else 0.0

    # Weighted blend with RENORMALISATION over applicable signals only. Corroboration
    # is applicable only when there were ≥2 independent publishers to compare; citation
    # coverage only when the citation agent ran.
    weighted = [
        (g, _W_GROUNDING, True),
        (corr_score, _W_CORROBORATION, corr_assessable),
        (cite_score, _W_CITATION, cite_assessable),
        (a, _W_AUTHORITY, True),
        (e, _W_EVIDENCE, True),
        (c, _W_COVERAGE, True),
    ]
    active = [(v, w) for v, w, ok in weighted if ok]
    total_w = sum(w for _, w in active) or 1.0
    composite = sum(v * w for v, w in active) / total_w

    reasons: list[str] = []

    # ── Calibration guards ────────────────────────────────────────────────────
    evidence_present = n_chunks > 0
    strong_corroboration = bool(corroboration and corroboration.strong)

    # Hallucination veto: evidence WAS retrieved but entailed nothing → contradiction.
    # This wins over everything (even corroboration) — a contradicted answer is not safe.
    if evidence_present and g <= 0.0:
        composite = min(composite, 0.30)
        reasons.append("The retrieved sources do not support the answer's claims.")
    else:
        # Unverifiable cap: no evidence and no citation → honest parametric answer. It
        # may be correct, but we could not check it, so it can never read as "high" …
        if not evidence_present and n_sources == 0:
            composite = min(composite, 0.60)
            reasons.append("Based on general knowledge — no source was available to verify this.")
        # … UNLESS several independent publishers corroborate it. This is the
        # triangulation lift: no official document, but many independents agree → the
        # claim is highly probable, so let it clear into the reliable band.
        if strong_corroboration:
            composite = max(composite, 0.72)

    composite = _clamp(composite)

    # ── Band + warn ───────────────────────────────────────────────────────────
    hi = settings.RELIABILITY_HIGH_THRESHOLD
    warn_t = settings.RELIABILITY_WARN_THRESHOLD
    low_t = settings.RELIABILITY_LOW_THRESHOLD
    if composite >= hi:
        band, label = "high", "Reliable"
    elif composite >= warn_t:
        band, label = "medium", "Fairly reliable — verify key details"
    elif composite >= low_t:
        band, label = "low", "Low confidence — please verify"
    else:
        band, label = "very_low", "Unverified — treat with caution"
    warn = composite < warn_t

    # ── Explanatory reasons (help the user judge) ─────────────────────────────
    if n_auth:
        reasons.append(
            f"Grounded in {n_auth} official/authoritative "
            f"source{'s' if n_auth != 1 else ''}."
        )
    elif n_sources:
        reasons.append(f"Cites {n_sources} source{'s' if n_sources != 1 else ''} (none official).")
    if corr_assessable and corroboration.corroborated_claims:
        reasons.append(
            f"Corroborated by {corroboration.independent_sources} independent "
            f"sources on {len(corroboration.corroborated_claims)} of "
            f"{len(corroboration.corroborated_claims) + len(corroboration.contested_claims)} key points."
        )
    if cite_assessable:
        pct = round(cite_score * 100)
        reasons.append(f"Found a supporting source for {pct}% of the answer's claims.")
    if unsupported_claims:
        reasons.append(
            f"{len(unsupported_claims)} claim{'s' if len(unsupported_claims) != 1 else ''} "
            f"could not be matched to a source."
        )
    if warn:
        reasons.append("Please double-check important facts against an official source.")

    signals = {
        "grounding": g,
        "source_authority": a,
        "evidence_strength": e,
        "coverage": c,
    }
    if corr_assessable:
        signals["corroboration"] = corr_score
    if cite_assessable:
        signals["citation_coverage"] = cite_score

    log.info(
        "reliability_scored",
        score=round(composite, 4), band=band, warn=warn,
        signals={k: round(v, 4) for k, v in signals.items()},
        unsupported=len(unsupported_claims or []), reasons=reasons,
    )
    return ReliabilityScore(
        score=composite, band=band, label=label, warn=warn, applicable=True,
        signals=signals,
        reasons=reasons,
        unsupported_claims=list(unsupported_claims or []),
    )
