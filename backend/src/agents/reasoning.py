"""
Reasoning — make answer generation deliberate instead of one-shot.

Two capabilities, both cheap and both degrade safely to a no-op:

- reasoning_directive(plan): turns the *selected* Plan into an explicit "approach" the
  generator must follow. Previously the planner computed a plan and then threw it away —
  the answer never used it. Now the plan actually steers how the answer is composed.

- reflect_and_improve(...): a single fast self-critique AFTER a draft is written. It asks,
  as a careful reviewer would, whether the draft truly ANSWERS the question, is complete,
  and uses the retrieved evidence — a check distinct from claim/grounding verification
  (which only checks that stated facts are supported, not that the answer is any good).
  If it finds a concrete gap it rewrites the answer ONCE, grounded in the same sources.
  The improved draft still flows through downstream claim verification, so this can't
  smuggle in unsupported facts.

Everything here is gated by settings and never raises — on any error the original draft is
returned unchanged.
"""

from __future__ import annotations

import json

import structlog

from src.agents.base import extract_json_object
from src.config import settings

log = structlog.get_logger("agents.reasoning")


def reasoning_directive(plan: dict | None) -> str:
    """Render the chosen plan as an approach the generator should reason through before
    writing. Returns '' when there is no useful multi-step plan (e.g. simple answers)."""
    if not plan:
        return ""
    steps = plan.get("steps") or []
    if len(steps) < 1:
        return ""
    lines = []
    for i, s in enumerate(steps, 1):
        desc = (s.get("description") or "").strip()
        if not desc:
            continue
        why = (s.get("rationale") or "").strip()
        lines.append(f"  {i}. {desc}" + (f" — {why}" if why else ""))
    if not lines:
        return ""
    body = "\n".join(lines)
    return (
        "\n\nHOW TO APPROACH THIS (reason through these steps internally to build a "
        "complete, well-structured answer — do NOT print the steps themselves):\n"
        f"{body}\n"
    )


def quality_directive(domain: str, complexity: str = "simple") -> str:
    """A compact instruction that bakes the reviewer's and critic's concerns straight into
    the generation prompt — so the answer is complete, on-point and (in high-stakes domains)
    safe WITHOUT spending extra LLM calls on separate reflect/critic passes. This is the
    default path; the standalone reflect/critic agents remain available as opt-in quality
    boosts (settings.REASONING_REFLECT_ENABLED / CRITIC_ENABLED)."""
    base = ("\n\nBEFORE writing, think it through so the answer is COMPLETE and GROUNDED: "
            "cover every step and key caveat the question needs (a partial answer is a wrong "
            "answer), and back every factual claim with the sources above — never invent "
            "specifics, figures, names, dates, or citations.")
    if (domain or "").lower() in ("health", "legal", "finance"):
        base += (" This is a high-stakes topic: avoid absolute/unsafe advice, state important "
                 "risks, and add a brief 'verify officially / consult a professional' caution.")
    return base


_REFLECT_SYSTEM = """You are a meticulous reviewer checking a draft answer BEFORE it is sent
to a user of an Indian citizen-assistance assistant. Judge only these things:
- Does the draft directly ANSWER the user's actual question (not a related one)?
- Is it COMPLETE for a helpful reply (no obviously missing step, caveat, or key detail)?
- Does it correctly use the SOURCES provided (and avoid inventing specifics)?

If the draft is already good, say so and change nothing. If — and only if — there is a
concrete, fixable gap, rewrite the answer text so it is complete and directly on-point,
using ONLY the sources and well-established general knowledge (never invent figures, names,
dates, or citations). Keep the user's language and keep it concise.

Respond ONLY as JSON:
{"needs_improvement": true/false, "reason": "one short line",
 "improved_answer": "the full rewritten answer text, or empty string if no change"}"""


async def reflect_and_improve(
    query: str,
    draft_text: str,
    knowledge_text: str,
    language: str,
    complexity: str = "simple",
    correlation_id: str = "",
) -> tuple[str, bool]:
    """Critique the draft once and return (possibly-improved text, changed?).

    Gated to non-trivial queries to bound latency. Never raises."""
    if not settings.REASONING_REFLECT_ENABLED:
        return draft_text, False
    if complexity not in ("multi_step", "action"):
        return draft_text, False
    draft_text = (draft_text or "").strip()
    if len(draft_text) < 40:                      # nothing meaningful to reflect on
        return draft_text, False
    try:
        from src.llm.router import route_completion

        resp = await route_completion(
            messages=[
                {"role": "system", "content": _REFLECT_SYSTEM},
                {"role": "user",
                 "content": (f"Answer in {language}.\nUSER QUESTION: {query}\n\n"
                             f"SOURCES:\n{knowledge_text or '(none provided)'}\n\n"
                             f"DRAFT ANSWER:\n{draft_text}")},
            ],
            override_tier="fast",
            correlation_id=correlation_id,
        )
        content = extract_json_object(resp.content)
        data = json.loads(content)
        improved = str(data.get("improved_answer") or "").strip()
        if data.get("needs_improvement") and improved and improved != draft_text:
            log.info("answer_reflected", changed=True, reason=data.get("reason"),
                     correlation_id=correlation_id)
            return improved, True
        log.info("answer_reflected", changed=False, correlation_id=correlation_id)
        return draft_text, False
    except Exception as exc:
        log.warning("reflect_failed", error=str(exc), correlation_id=correlation_id)
        return draft_text, False


_CRITIC_SYSTEM = """You are a strict domain reviewer doing a FINAL accuracy-and-safety check on
a draft answer in a HIGH-STAKES domain (health, legal, or finance) for an Indian citizen.
A wrong or unsafe answer here can cause real harm, so be adversarial.

Check for: factual errors, unsafe or absolute advice, missing critical caveats or risks,
claims not supported by the sources, and anything that should carry a "consult a
professional / verify officially" caution. Use ONLY the provided sources plus well-
established general knowledge — never invent specifics.

If the draft is accurate and safe, keep it. Otherwise rewrite it to be correct and safe,
adding the necessary caution briefly and in the user's language. Do NOT pad it out.

Respond ONLY as JSON:
{"safe_and_accurate": true/false, "issue": "one short line",
 "corrected_answer": "the full corrected answer, or empty string if no change"}"""


async def critique_answer(
    query: str,
    draft_text: str,
    knowledge_text: str,
    language: str,
    domain: str = "general",
    correlation_id: str = "",
) -> tuple[str, bool]:
    """Independent adversarial review for high-stakes domains. Returns (possibly-corrected
    text, changed?). Gated to CRITIC_DOMAINS; degrades to the draft on any error. The
    corrected text still passes downstream claim verification, so it can't add unsupported
    facts."""
    if not settings.CRITIC_ENABLED or (domain or "").lower() not in settings.CRITIC_DOMAINS:
        return draft_text, False
    draft_text = (draft_text or "").strip()
    if len(draft_text) < 40:
        return draft_text, False
    try:
        from src.llm.router import route_completion

        resp = await route_completion(
            messages=[
                {"role": "system", "content": _CRITIC_SYSTEM},
                {"role": "user",
                 "content": (f"Answer in {language}.\nDOMAIN: {domain}\nUSER QUESTION: {query}\n\n"
                             f"SOURCES:\n{knowledge_text or '(none provided)'}\n\n"
                             f"DRAFT ANSWER:\n{draft_text}")},
            ],
            override_tier="fast",
            correlation_id=correlation_id,
        )
        content = extract_json_object(resp.content)
        data = json.loads(content)
        corrected = str(data.get("corrected_answer") or "").strip()
        if not data.get("safe_and_accurate") and corrected and corrected != draft_text:
            log.info("answer_critiqued", changed=True, domain=domain, issue=data.get("issue"),
                     correlation_id=correlation_id)
            return corrected, True
        log.info("answer_critiqued", changed=False, domain=domain, correlation_id=correlation_id)
        return draft_text, False
    except Exception as exc:
        log.warning("critique_failed", error=str(exc), correlation_id=correlation_id)
        return draft_text, False
