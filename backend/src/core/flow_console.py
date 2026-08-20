"""
Human-readable request flow — the "what is happening right now" view.

Prints ONE clean, scannable block per query to the console (and flow.log): a header with the
query, a single line per pipeline step as it completes (with its timing + key result), and a
footer with the final answer + reliability + cost. Driven from the orchestrator's traced_node
wrapper, so no per-node wiring is needed.

Everything here is best-effort and never raises — readability must never break the request.
Glyphs are limited to the cp1252-safe set (· » « – ) so Windows consoles don't choke.
"""

from __future__ import annotations

import logging
from typing import Any

from src.config import settings

_log = logging.getLogger("flow")       # → flow.log: the readable per-request flow
_term = logging.getLogger("terminal")  # → console: only API + LLM call heartbeat

# Plumbing nodes with nothing worth a line — folded into their neighbours' timing.
_SKIP = {"embed_query", "assemble_context", "clarify_check"}

_LABELS = {
    "understand": "understand", "plan_route": "plan", "retrieve": "retrieve",
    "grade_documents": "grade", "live_augment": "live-web", "rewrite_query": "rewrite",
    "generate": "generate", "generate_simple": "answer", "cite_claims": "cite",
    "verify_claims": "verify", "multi_hop": "multi-hop", "task_execute": "task",
    "finalize": "finalize", "safe_response": "safety",
}


def _short(cid: str | None) -> str:
    return (cid or "")[:8] or "--------"


def _dur(ms: float | None) -> str:
    if ms is None:
        return ""
    return f"{ms / 1000:.1f}s" if ms >= 1000 else f"{int(ms)}ms"


def _detail(node: str, state: dict, result: dict) -> str:
    """The one salient fact each step produced, in plain words."""
    r = result or {}

    def g(key: str, default: Any = None) -> Any:
        return r.get(key, state.get(key, default))

    if node == "understand":
        return f"{g('domain', 'general')} · {g('complexity', 'simple')} · route={g('route', 'agentic_rag')} · {g('language', 'en')}"
    if node == "plan_route":
        mode = (r.get("mission") or {}).get("mode")
        return f"route={g('route')}" + (f" · {mode}" if mode else "")
    if node == "retrieve":
        return f"pool={len(g('knowledge_pool', []) or [])} · live={'on' if g('live_augmented') else 'off'}"
    if node == "grade_documents":
        return f"kept={len(g('knowledge', []) or [])} · sufficient={'yes' if g('sufficient') else 'no'}"
    if node == "live_augment":
        return f"pool={len(g('knowledge_pool', []) or [])}"
    if node == "rewrite_query":
        return f"loop #{g('rag_loops', 0)} · \"{(g('retrieval_query', '') or '')[:40]}\""
    if node == "generate":
        return f"agent={state.get('domain', '')} · card={(r.get('response_card') or {}).get('cardType', 'answer')}"
    if node == "generate_simple":
        return "simple reply"
    if node == "cite_claims":
        cov = r.get("citation_coverage")
        base = f"citations={len(r.get('citations', []) or [])}"
        return base + (f" · coverage={int(cov * 100)}%" if cov is not None else "")
    if node == "verify_claims":
        return f"confidence={float(g('confidence', 0) or 0):.2f} · unsupported={len(g('unsupported_claims', []) or [])}"
    if node == "finalize":
        card = r.get("response_card") or {}
        rel = card.get("reliability") or {}
        out = f"reliability={rel.get('band')}" if rel.get("band") else "done"
        if rel.get("score") is not None:
            out += f" {int(rel['score'] * 100)}%"
        if card.get("abstained"):
            out += " · ABSTAINED"
        return out
    if node == "safe_response":
        return f"tag={state.get('safety_tag', '')}"
    return ""


# ── Terminal heartbeat — the ONLY thing on the console: API + LLM calls ─────────

def api_call(method: str, path: str, status: int, ms: float) -> None:
    if not settings.TERMINAL_ENABLED:
        return
    try:
        _term.info(f"API  {method:<5} {path:<28} {status}  {_dur(ms)}")
    except Exception:
        pass


def llm_call(step: str, model: str, in_tok: int, out_tok: int, ms: float,
             failed: bool = False, error: str = "") -> None:
    if not settings.TERMINAL_ENABLED:
        return
    try:
        head = f"LLM  {(step or '-'):<12} {(model or '?'):<22}"
        if failed:
            _term.info(f"{head} FAILED: {(error or '')[:80]}")
        else:
            _term.info(f"{head} in={in_tok:,} out={out_tok:,}  {_dur(ms)}")
    except Exception:
        pass


# ── Flow.log — the readable per-request story (file only) ───────────────────────

def query_start(cid: str, user_id: str, query: str) -> None:
    if not settings.FLOW_CONSOLE_ENABLED:
        return
    try:
        _log.info("")
        _log.info(f"» QUERY  {_short(cid)}  user={_short(user_id)}")
        _log.info(f"    \"{(query or '').strip()[:140]}\"")
    except Exception:
        pass


def node_flow(node: str, state: dict, result: dict | None, ms: float, tokens: int = 0) -> None:
    if not settings.FLOW_CONSOLE_ENABLED or node in _SKIP:
        return
    try:
        label = _LABELS.get(node, node)
        detail = _detail(node, state, result or {})
        tok = f"  {tokens:,}tok" if tokens else ""
        _log.info(f"  · {label:<11} {_dur(ms):>6}  {detail}{tok}".rstrip())
    except Exception:
        pass


def node_error(node: str, cid: str, error: str, error_type: str = "") -> None:
    """A step raised — mark it loudly in the flow so a failure is obvious at a glance."""
    if not settings.FLOW_CONSOLE_ENABLED:
        return
    try:
        label = _LABELS.get(node, node)
        kind = f" [{error_type}]" if error_type else ""
        _log.info(f"  × {label:<11}  FAILED{kind}: {(error or '')[:160]}")
    except Exception:
        pass


def query_end(cid: str, card: dict, metrics: dict) -> None:
    if not settings.FLOW_CONSOLE_ENABLED:
        return
    try:
        card = card or {}
        rel = card.get("reliability") or {}
        band, score = rel.get("band"), rel.get("score")
        verdict = f"{band} {int(score * 100)}%" if band and score is not None else card.get("cardType", "answer")
        answer = (card.get("summary") or card.get("title") or "").replace("\n", " ").strip()[:160]
        _log.info(
            f"« ANSWER  {verdict} · {_dur(metrics.get('total_latency_ms'))} · "
            f"{metrics.get('total_llm_calls', 0)} calls · {metrics.get('total_tokens', 0):,} tok"
        )
        _log.info(f"    \"{answer}\"")
        _log.info("")
    except Exception:
        pass
