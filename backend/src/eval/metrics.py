"""
Pure metric functions for the eval harness.

All functions here are deterministic and infra-free so they can be unit-tested.
"""

from __future__ import annotations

import math
import re

from src.core.logging import get_logger

log = get_logger("eval.metrics")


def precision_at_k(retrieved_ids: list[str], relevant_ids: list[str], k: int) -> float:
    """Fraction of the top-k retrieved ids that are relevant."""
    if k <= 0:
        log.debug("precision_at_k_invalid_k", k=k)
        return 0.0
    top = retrieved_ids[:k]
    if not top:
        log.debug("precision_at_k_empty", k=k)
        return 0.0
    relevant = set(relevant_ids)
    hits = sum(1 for cid in top if cid in relevant)
    score = hits / len(top)
    log.debug("precision_at_k", k=k, hits=hits, considered=len(top), score=round(score, 4))
    return score


def recall_at_k(retrieved_ids: list[str], relevant_ids: list[str], k: int) -> float:
    """Fraction of relevant ids that appear in the top-k."""
    relevant = set(relevant_ids)
    if not relevant:
        log.debug("recall_at_k_no_relevant", k=k)
        return 1.0  # nothing to find → trivially satisfied
    top = set(retrieved_ids[:k])
    score = len(top & relevant) / len(relevant)
    log.debug("recall_at_k", k=k, matched=len(top & relevant), relevant=len(relevant),
              score=round(score, 4))
    return score


def ndcg_at_k(retrieved_ids: list[str], relevant_ids: list[str], k: int = 10) -> float:
    """
    Normalised Discounted Cumulative Gain with binary relevance.
    DCG = Σ rel_i / log2(i+2);  IDCG = DCG of the ideal ranking.
    """
    relevant = set(relevant_ids)
    if not relevant:
        log.debug("ndcg_at_k_no_relevant", k=k)
        return 1.0
    dcg = 0.0
    for i, cid in enumerate(retrieved_ids[:k]):
        if cid in relevant:
            dcg += 1.0 / math.log2(i + 2)
    ideal_hits = min(len(relevant), k)
    idcg = sum(1.0 / math.log2(i + 2) for i in range(ideal_hits))
    score = dcg / idcg if idcg > 0 else 0.0
    log.debug("ndcg_at_k", k=k, dcg=round(dcg, 4), idcg=round(idcg, 4), score=round(score, 4))
    return score


# ── Citations ─────────────────────────────────────────────────────────────────

def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def citation_present(produced_citations: list[str], expected: str | None) -> bool:
    """
    True if the expected citation appears (normalised substring) in any of the
    produced citation strings. If there is no expected citation, this is vacuously
    True (nothing required).
    """
    if not expected:
        return True
    exp = _normalize(expected)
    present = any(exp in _normalize(c) for c in produced_citations)
    log.debug("citation_present", present=present, produced=len(produced_citations))
    return present


def citation_wellformed(expected: str | None) -> bool:
    """
    Structural check that an expected citation looks like a real authoritative
    reference (a section/act, a scheme/programme, a govt authority, or a URL),
    not free text.
    """
    if not expected:
        return True
    e = expected.strip()
    # An all-caps alpha token of length >= 2 is almost always an authority/acronym
    # (RBI, SEBI, IRDAI, CIBIL, NPCI, MSP, PPF, KCC, NSP, NMMS, PMFBY, NCERT, UPI).
    if any(t.isupper() and len(t) >= 2 for t in re.findall(r"[A-Za-z]+", e)):
        return True
    patterns = [
        r"\bsection\s+\d+", r"\bdhara\s+\d+", r"धारा\s*\d+", r"\barticle\s+\d+",
        r"\b(ipc|crpc|bns|bnss|rti|cpc|ni\s*act)\b",
        r"\bpm[-\s]?\w+", r"\byojana\b", r"\bscheme\b", r"\bact\b", r"https?://",
        # authorities / programmes that may be title-cased (no all-caps token)
        r"\bayushman\b", r"\bmohfw\b", r"\bimmuni[sz]ation\b", r"\bincome\s+tax\b",
        r"\bministry\b", r"\bdepartment\b", r"\bprovident\s+fund\b", r"\bscholarship\b",
    ]
    wellformed = any(re.search(p, e, re.IGNORECASE) for p in patterns)
    log.debug("citation_wellformed", wellformed=wellformed)
    return wellformed


def abstention_correct(predicted_abstain: bool, should_abstain: bool) -> bool:
    correct = bool(predicted_abstain) == bool(should_abstain)
    log.debug("abstention_correct", predicted=bool(predicted_abstain),
              expected=bool(should_abstain), correct=correct)
    return correct


def faithfulness_from_facts(answer_text: str, key_facts: list[str]) -> float:
    """
    Lightweight, infra-free faithfulness proxy: fraction of key facts whose
    salient tokens appear in the answer. Used as a fallback when the LLM judge is
    unavailable. The LLM judge (run.py) is preferred when API keys are present.
    """
    if not key_facts:
        return 1.0
    ans = _normalize(answer_text)
    if not ans:
        log.debug("faithfulness_empty_answer", key_facts=len(key_facts))
        return 0.0
    covered = 0
    for fact in key_facts:
        tokens = [t for t in re.findall(r"[a-z0-9ऀ-ൿ]+", _normalize(fact)) if len(t) > 2]
        if not tokens:
            covered += 1
            continue
        present = sum(1 for t in tokens if t in ans)
        if present / len(tokens) >= 0.5:
            covered += 1
    score = covered / len(key_facts)
    log.debug("faithfulness_from_facts", covered=covered, key_facts=len(key_facts),
              score=round(score, 4))
    return score


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0
