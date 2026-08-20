"""
Eval runner — `make eval` / `python -m src.eval.run`.

Loads per-domain JSONL golden sets and computes:
  OFFLINE (always, no infra):
    - citation_format_validity  — golden citations are well-formed & self-consistent
    - abstention_label_sanity   — should-abstain labels are internally consistent
  LIVE (needs Qdrant + LLM keys):
    - precision@k, nDCG@10      — retrieval quality vs relevant_doc_ids
    - faithfulness              — produced answer grounded in key_facts (LLM judge)
    - abstention_correctness    — abstain decisions match should_abstain
    - citation_validity         — produced answer cites the expected source

Degrades gracefully: when infra/keys are absent, live metrics are skipped (not
faked) and the report says so. Results are written to Prometheus eval gauges.
"""

from __future__ import annotations

import argparse
import asyncio

import structlog

from src.config import settings
from src.core.metrics import (
    EVAL_ABSTENTION_CORRECTNESS,
    EVAL_CITATION_VALIDITY,
    EVAL_FAITHFULNESS,
    EVAL_NDCG_AT_10,
    EVAL_PRECISION_AT_K,
)
from src.eval import metrics as M
from src.eval.datasets import available_domains, load_domain
from src.eval.schemas import DomainReport, EvalReport, GoldenExample

log = structlog.get_logger("eval.run")


# ── Live-mode detection ───────────────────────────────────────────────────────

def _has_llm_key() -> bool:
    return any([
        settings.ANTHROPIC_API_KEY, settings.OPENAI_API_KEY, settings.GOOGLE_API_KEY,
        settings.GROQ_API_KEY, settings.MISTRAL_API_KEY, settings.COHERE_API_KEY,
    ])


async def _qdrant_reachable() -> bool:
    try:
        from qdrant_client import AsyncQdrantClient

        client = AsyncQdrantClient(
            url=f"http://{settings.QDRANT_HOST}:{settings.QDRANT_PORT}",
            api_key=settings.QDRANT_API_KEY or None,
            timeout=3,
        )
        await client.get_collections()
        await client.close()
        return True
    except Exception:
        return False


async def detect_live() -> tuple[bool, list[str]]:
    reasons: list[str] = []
    has_key = _has_llm_key()
    if not has_key:
        reasons.append("no LLM API key configured")
    reachable = await _qdrant_reachable()
    if not reachable:
        reasons.append("Qdrant not reachable")
    return (has_key and reachable), reasons


# ── Offline metrics ───────────────────────────────────────────────────────────

def evaluate_offline(domain: str, examples: list[GoldenExample]) -> DomainReport:
    report = DomainReport(domain=domain, n_examples=len(examples))
    if not examples:
        report.notes.append("empty golden set")
        return report

    cited = [e for e in examples if e.expected_citation]
    if cited:
        ok = sum(
            1 for e in cited
            if M.citation_wellformed(e.expected_citation)
            and M.citation_present([e.reference_answer or ""], e.expected_citation)
        )
        report.citation_format_validity = ok / len(cited)

    def _label_ok(e: GoldenExample) -> bool:
        if e.should_abstain:
            return not e.relevant_doc_ids  # should-abstain ⇒ no gold sources
        return bool(e.key_facts or e.relevant_doc_ids or e.reference_answer)

    report.abstention_label_sanity = sum(1 for e in examples if _label_ok(e)) / len(examples)
    return report


# ── Live metrics ──────────────────────────────────────────────────────────────

def _chunk_identifiers(chunk) -> set[str]:
    ids = {chunk.chunk_id, chunk.source, chunk.source_url}
    if chunk.section:
        ids.add(chunk.section)
    return {i for i in ids if i}


async def _llm_faithfulness(answer: str, key_facts: list[str], correlation_id: str) -> float | None:
    if not (settings.EVAL_USE_LLM_FAITHFULNESS and key_facts and answer):
        return None
    try:
        import json as _json

        from src.llm.router import route_completion

        facts = "\n".join(f"- {f}" for f in key_facts)
        result = await route_completion(
            messages=[
                {"role": "system", "content": (
                    "You are a strict faithfulness judge. Given an ANSWER and a list of "
                    "KEY FACTS, report the fraction of key facts that the answer states or "
                    "clearly supports (not contradicts). Respond ONLY as JSON: "
                    '{"supported": <int>, "total": <int>}.'
                )},
                {"role": "user", "content": f"ANSWER:\n{answer}\n\nKEY FACTS:\n{facts}"},
            ],
            override_tier="fast",
            correlation_id=correlation_id,
        )
        content = result.content.strip().strip("`").replace("json", "", 1).strip()
        parsed = _json.loads(content)
        total = int(parsed.get("total", len(key_facts))) or len(key_facts)
        return max(0.0, min(1.0, int(parsed.get("supported", 0)) / total))
    except Exception as exc:
        log.warning("llm_faithfulness_failed", error=str(exc))
        return None


async def evaluate_live(domain: str, examples: list[GoldenExample], report: DomainReport) -> None:
    from src.retrieval.hybrid import retrieve

    p_at_k, ndcgs, faiths, abst, cites = [], [], [], [], []
    retrieved_any = False

    for e in examples:
        cid = f"eval-{e.id}"
        # Retrieval metrics
        try:
            chunks = await retrieve(query=e.query, language=e.language, domain=e.domain, correlation_id=cid)
            retrieved_ids: list[str] = []
            for c in chunks:
                idents = _chunk_identifiers(c)
                # represent each chunk by whichever identifier matches the gold set (if any)
                match = next((i for i in idents if i in set(e.relevant_doc_ids)), c.chunk_id)
                retrieved_ids.append(match)
            if chunks:
                retrieved_any = True
            if e.relevant_doc_ids:
                p_at_k.append(M.precision_at_k(retrieved_ids, e.relevant_doc_ids, settings.EVAL_RETRIEVAL_TOP_K))
                ndcgs.append(M.ndcg_at_k(retrieved_ids, e.relevant_doc_ids, 10))
        except Exception as exc:
            log.warning("eval_retrieve_failed", id=e.id, error=str(exc))

        # Answer-level metrics
        try:
            from src.agents.orchestrator import process_query

            card = await process_query(query=e.query, session_id=cid, user_id="eval", correlation_id=cid)
            answer = card.get("summary") or card.get("title") or ""
            produced_cites = [s.get("text", "") for s in (card.get("sources") or [])]

            f = await _llm_faithfulness(answer, e.key_facts, cid)
            if f is None:
                f = M.faithfulness_from_facts(answer, e.key_facts)
            faiths.append(f)
            abst.append(1.0 if M.abstention_correct(bool(card.get("abstained")), e.should_abstain) else 0.0)
            if e.expected_citation and not e.should_abstain:
                cites.append(1.0 if M.citation_present(produced_cites, e.expected_citation) else 0.0)
        except Exception as exc:
            log.warning("eval_answer_failed", id=e.id, error=str(exc))

    report.live_evaluated = True
    if p_at_k:
        report.precision_at_k = M.mean(p_at_k)
    if ndcgs:
        report.ndcg_at_10 = M.mean(ndcgs)
    if faiths:
        report.faithfulness = M.mean(faiths)
    if abst:
        report.abstention_correctness = M.mean(abst)
    if cites:
        report.citation_validity = M.mean(cites)
    if not retrieved_any:
        report.notes.append("retrieval returned nothing — corpus likely not seeded for this domain")


# ── Orchestration ─────────────────────────────────────────────────────────────

def _publish_gauges(r: DomainReport) -> None:
    if r.precision_at_k is not None:
        EVAL_PRECISION_AT_K.labels(domain=r.domain).set(r.precision_at_k)
    if r.ndcg_at_10 is not None:
        EVAL_NDCG_AT_10.labels(domain=r.domain).set(r.ndcg_at_10)
    if r.faithfulness is not None:
        EVAL_FAITHFULNESS.labels(domain=r.domain).set(r.faithfulness)
    if r.abstention_correctness is not None:
        EVAL_ABSTENTION_CORRECTNESS.labels(domain=r.domain).set(r.abstention_correctness)
    # Prefer live citation validity; fall back to the offline citation-quality proxy.
    citation = r.citation_validity if r.citation_validity is not None else r.citation_format_validity
    if citation is not None:
        EVAL_CITATION_VALIDITY.labels(domain=r.domain).set(citation)


async def run_eval(live: bool | None = None) -> EvalReport:
    domains = available_domains()
    if live is None:
        live, reasons = await detect_live()
        if not live:
            log.info("eval_offline_mode", reasons=reasons)

    reports: list[DomainReport] = []
    total = 0
    for domain in domains:
        examples = load_domain(domain)
        total += len(examples)
        report = evaluate_offline(domain, examples)
        if live and examples:
            try:
                await evaluate_live(domain, examples, report)
            except Exception as exc:
                report.notes.append(f"live eval error: {exc}")
        _publish_gauges(report)
        reports.append(report)

    return EvalReport(domains=reports, live_mode=bool(live), total_examples=total)


def _fmt(v: float | None) -> str:
    return f"{v:.3f}" if isinstance(v, float) else "  -  "


def print_report(report: EvalReport) -> None:
    mode = "LIVE (infra + LLM)" if report.live_mode else "OFFLINE (no infra - live metrics skipped)"
    print("\n" + "=" * 92)
    print(f"  Nipun.AI - Eval Report   |   mode: {mode}   |   {report.total_examples} examples")
    print("=" * 92)
    header = f"{'domain':<10} {'n':>3} {'P@k':>7} {'nDCG10':>7} {'faith':>7} {'abst_ok':>7} {'cite':>7}  notes"
    print(header)
    print("-" * 92)
    for r in report.domains:
        cite = r.citation_validity if r.citation_validity is not None else r.citation_format_validity
        note = "; ".join(r.notes)
        print(
            f"{r.domain:<10} {r.n_examples:>3} {_fmt(r.precision_at_k):>7} {_fmt(r.ndcg_at_10):>7} "
            f"{_fmt(r.faithfulness):>7} {_fmt(r.abstention_correctness):>7} {_fmt(cite):>7}  {note}"
        )
    print("-" * 92)
    if not report.live_mode:
        print("  Offline: 'cite' column shows citation-format validity of the golden set itself.")
        print("  Start infra (make infra) + set an LLM key, then re-run for retrieval/faithfulness.")
    print("=" * 92 + "\n")


def main() -> None:
    # Windows consoles default to cp1252; force UTF-8 so the report never crashes.
    try:
        import sys

        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="Nipun.AI eval harness")
    parser.add_argument("--offline", action="store_true", help="force offline mode (skip live metrics)")
    parser.add_argument("--live", action="store_true", help="force live mode (assume infra present)")
    args = parser.parse_args()
    live: bool | None = None
    if args.offline:
        live = False
    elif args.live:
        live = True
    report = asyncio.run(run_eval(live=live))
    print_report(report)


if __name__ == "__main__":
    main()
