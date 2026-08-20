"""
General agentic task executor — a reason-act-observe loop over the real tools.

Instead of a hand-written function per task, this lets the model ACCOMPLISH an open-ended
task by itself: it thinks, calls the right tool(s) from the live registry (web search, job
search, scholar, books, weather, prices, fetch-a-page, …), reads the results, and repeats
until it can produce a useful, grounded result. New tools registered anywhere become usable
here automatically — no orchestrator changes.

Protocol is a portable JSON "action" loop (works across providers, incl. Gemini), not
provider-specific function-calling. Safety is preserved: tools are read-only and their output
is untrusted DATA (the MCP layer scans it); the agent never handles credentials, and anything
that would move money / submit / book is described as a step for the user to confirm — the
real PREPARE→CONFIRM→EXECUTE boundary is unchanged.
"""

from __future__ import annotations

import json

import structlog

from src.agents.base import extract_json_object
from src.core.runtime_context import runtime_prompt_header
from src.llm.router import route_completion

log = structlog.get_logger("agents.agentic")

# Tools the agent may call. Read-only, safe-to-call-without-confirmation MCP tools, described
# for the model. Kept data-driven: anything registered read-only is offered, so a new tool is
# available to the agent the moment it exists.
_TASK_TOOL_HINTS = {
    "web_search": '{"query": "<what to search the web for>"}',
    "web_fetch": '{"url": "<http(s) url to read>"}',
    "job_search": '{"query": "<role/title>", "location": "<city or Remote>"}',
    "scholar": '{"query": "<topic>"}',
    "books": '{"query": "<subject/career>"}',
    "weather": '{"location": "<city>"}',
    "mandi_prices": '{"commodity": "<crop>"}',
    "finance": '{"query": "<company/ticker/topic>"}',
    "news": '{"query": "<topic>"}',
}


def _available_tools() -> dict:
    """Read-only tools from the live registry, with a description + input hint."""
    from src.mcp.tools import _TOOLS

    out = {}
    for name, tool in _TOOLS.items():
        if not getattr(tool, "read_only", False):
            continue
        out[name] = {
            "description": tool.description,
            "input": _TASK_TOOL_HINTS.get(name, '{"query": "<input>"}'),
            "tool": tool,
        }
    return out


def _system_prompt(tools: dict, max_steps: int, language: str) -> str:
    lines = "\n".join(f'- {n}: {t["description"]} — input: {t["input"]}' for n, t in tools.items())
    lines += ('\n- generate_file: create a downloadable PPTX slide deck or DOCX document (with '
              'charts + pictures) when a FILE explains the answer better than text — input: '
              '{"format": "pptx|docx", "topic": "<what the file should cover>"}')
    return (
        "You are Nipun.AI's task executor. ACCOMPLISH the user's task yourself by thinking and "
        "USING TOOLS to get real, current information — never invent openings, prices, links, "
        "papers, or facts; get them from a tool.\n\n"
        "THE USER is an ordinary Indian citizen speaking in plain, natural language (often "
        "indirect, emotional, with typos, or mixing Hindi/English). Interpret what they REALLY "
        "need and just do it. INFER sensible defaults from what you know about them and the "
        "conversation instead of interrogating them; ask (via a step) only when you are truly "
        "blocked on something you cannot reasonably infer. Deliver something useful on the first "
        "reply, not a list of questions.\n\n"
        "YOU MAY CREATE A FILE: when a slide deck or document would explain the answer far better "
        "than plain text (a study summary, a plan, a comparison, a report), call `generate_file` "
        "— it produces a real, downloadable, attractive PPTX/DOCX with charts and images. Use it "
        "when it genuinely helps; otherwise just answer.\n\n"
        f"TOOLS you can call:\n{lines}\n\n"
        "Work in steps. Respond with EXACTLY ONE JSON object per step, nothing else:\n"
        '  to use a tool  → {"thought": "why", "tool": "<name>", "tool_input": { ... }}\n'
        '  when finished  → {"thought": "why done", "final": {"title": "short title", '
        '"summary": "the helpful result for the user", "steps": [{"title": "...", "desc": "..."}], '
        '"sources": [{"text": "name", "url": "..."}]}}\n\n'
        "RULES:\n"
        "- Prefer finishing as soon as you have enough to be genuinely useful; do not loop needlessly.\n"
        f"- Use at most {max_steps} tool calls.\n"
        "- NEVER ask for or handle a password, OTP, PIN, card, or captcha. For anything that would "
        "submit/pay/book, put it in `steps` as an action the USER confirms — do not attempt it.\n"
        f"- Write the final summary and steps in {language}.\n"
        "- Ground factual claims in tool results and cite them in `sources`."
    )


def _parse_action(text: str) -> dict | None:
    """Extract the single JSON action object from the model's reply. Tolerant of fences/prose."""
    # extract_json_object strips a leading ```json fence correctly and isolates the {...},
    # without the fragile split("```")[1] (IndexErrors on odd fences) / global replace("json").
    t = extract_json_object(text)
    try:
        return json.loads(t)
    except Exception:
        start, end = t.find("{"), t.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(t[start:end + 1])
            except Exception:
                return None
    return None


def _observation(tool_name: str, result) -> str:
    """Compact, model-friendly rendering of a tool result."""
    if result is None:
        return f"{tool_name}: no result."
    if result.status != "ok":
        return f"{tool_name}: {result.status} — {result.text[:200]}"
    rows = result.data.get("results") if isinstance(result.data, dict) else None
    if rows:
        lines = []
        for r in rows[:6]:
            title = r.get("title") or r.get("section") or ""
            url = r.get("url") or r.get("source_url") or ""
            snippet = (r.get("content") or "")[:180]
            lines.append(f"- {title} | {url} | {snippet}".strip(" |"))
        return f"{tool_name} results:\n" + "\n".join(lines)
    return f"{tool_name}: {result.text[:500]}"


async def run_agentic_task(
    query: str, profile: dict, context: dict, language: str = "en",
    correlation_id: str = "", history: str = "", max_steps: int = 4, owner_id: str = "",
) -> dict | None:
    """Drive the reason-act-observe loop and return a card dict, or None on total failure so
    the caller can fall back. Never raises."""
    tools = _available_tools()
    profile = profile or {}
    convo = f"\nRECENT CONVERSATION:\n{history}" if history else ""
    known = {k: v for k, v in (profile or {}).items()
             if v not in (None, "", [], {}) and not str(k).startswith("_")}
    messages = [
        {"role": "system",
         "content": runtime_prompt_header(profile, language) + "\n" + _system_prompt(tools, max_steps, language)},
        {"role": "user",
         "content": f"TASK: {query}{convo}\nWHAT I KNOW ABOUT THE USER: {json.dumps(known, ensure_ascii=False)}"},
    ]

    used_sources: list[dict] = []
    try:
        for step in range(max_steps + 1):
            resp = await route_completion(
                messages=messages, complexity="multi_step",
                override_tier="primary", correlation_id=correlation_id,
            )
            action = _parse_action(resp.content)
            if not action:
                log.warning("agentic_unparseable", step=step, correlation_id=correlation_id)
                break

            if "final" in action and isinstance(action["final"], dict):
                card = action["final"]
                card.setdefault("cardType", "step_action")
                card["language"] = language
                # Merge any sources the tools surfaced but the model forgot to cite.
                if used_sources and not card.get("sources"):
                    card["sources"] = used_sources[:6]
                log.info("agentic_finished", steps=step, correlation_id=correlation_id)
                return card

            tool_name = action.get("tool", "")
            messages.append({"role": "assistant", "content": json.dumps(action, ensure_ascii=False)})

            # Special action: build a downloadable deliverable and return it as the result.
            if tool_name == "generate_file":
                from src.synthesis.deliverable import generate_deliverable
                ti = action.get("tool_input") or {}
                ctx_text = "\n".join(m["content"] for m in messages if m["role"] == "user")[:2500]
                card = await generate_deliverable(
                    topic=ti.get("topic") or query, fmt=ti.get("format") or "pptx",
                    owner_id=owner_id, profile=profile, context_text=ctx_text,
                    language=language, correlation_id=correlation_id)
                if card:
                    log.info("agentic_generated_file", step=step, correlation_id=correlation_id)
                    return card
                messages.append({"role": "user", "content": "OBSERVATION: file generation is "
                                 "unavailable; give your FINAL answer as text now."})
                continue

            tool_entry = tools.get(tool_name)
            if not tool_entry or step == max_steps:
                # Unknown tool, or out of steps: ask the model to finalize now.
                messages.append({"role": "user",
                                 "content": "OBSERVATION: no more tool calls available. "
                                            "Give your FINAL answer now as the `final` JSON."})
                continue

            result = await tool_entry["tool"].call(action.get("tool_input") or {})
            obs = _observation(tool_name, result)
            for r in (result.data.get("results") if result and isinstance(result.data, dict) else []) or []:
                if r.get("url"):
                    used_sources.append({"text": r.get("source") or tool_name, "url": r["url"]})
            log.info("agentic_tool_call", tool=tool_name, status=getattr(result, "status", "?"),
                     step=step, correlation_id=correlation_id)
            messages.append({"role": "user", "content": f"OBSERVATION: {obs}"})
    except Exception as exc:
        log.warning("agentic_failed", error=str(exc), correlation_id=correlation_id)
    return None
