"""Schemas for the evaluation harness."""

from __future__ import annotations

from pydantic import BaseModel, Field

from src.core.logging import get_logger

log = get_logger("eval.schemas")


class GoldenExample(BaseModel):
    """One labelled example in a per-domain golden set (JSONL line)."""

    id: str
    domain: str
    language: str = "en"
    query: str

    # Retrieval labels — ids of chunks/docs that SHOULD be retrieved for this query.
    relevant_doc_ids: list[str] = Field(default_factory=list)

    # Faithfulness labels — atomic facts a correct answer must contain (grounded).
    key_facts: list[str] = Field(default_factory=list)

    # Citation label — the authoritative citation a correct answer must cite
    # (e.g. "Section 302 IPC", "PM-KISAN"). Optional.
    expected_citation: str | None = None

    # Abstention label — True when there is NO reliable source and the system
    # SHOULD abstain rather than answer.
    should_abstain: bool = False

    # A short reference answer (used for offline self-consistency + LLM faithfulness).
    reference_answer: str | None = None


class DomainReport(BaseModel):
    """Aggregated metrics for one domain."""

    domain: str
    n_examples: int
    # Offline (no infra needed)
    citation_format_validity: float | None = None
    abstention_label_sanity: float | None = None
    # Live (needs infra / API keys)
    precision_at_k: float | None = None
    ndcg_at_10: float | None = None
    faithfulness: float | None = None
    abstention_correctness: float | None = None
    citation_validity: float | None = None
    live_evaluated: bool = False
    notes: list[str] = Field(default_factory=list)


class EvalReport(BaseModel):
    domains: list[DomainReport]
    live_mode: bool
    total_examples: int


log.debug("eval_schemas_loaded", models=3)
