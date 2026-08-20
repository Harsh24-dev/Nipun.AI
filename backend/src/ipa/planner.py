"""
Task planner — the goal → (checklist + one consolidated form + start URL).

A single fast-LLM call produces everything the run needs up-front, so the user answers ONE form
instead of a drip of clarifications: an ordered, verifiable checklist; the exact inputs to
collect; and where on the web to begin. Sensitive steps (login / OTP / payment / final submit)
are flagged so the agent knows to hand those to the user.
"""

from __future__ import annotations

import json

from src.core.logging import get_ipa_logger
from src.core.runtime_context import runtime_prompt_header
from src.ipa.schemas import ChecklistStep, FormField, TaskPlan
from src.llm.router import route_completion

log = get_ipa_logger("ipa.planner")

_PLANNER_SYSTEM = """You plan how an AGENT will EXECUTE a real task for an Indian user, across the
right surface, then hand off the sensitive parts. Produce a concrete, executable plan.

First choose the SURFACE:
- "web"    → the task is done on a website (book, apply, search-and-act, fill a form online).
- "app"    → the task changes THIS assistant app (open a screen, change a setting like theme or
             language, update the user's profile).
- "device" → the task is a local file/device action (create/save/read a file). Rare.

Return STRICT JSON only:
{
  "surface": "web|app|device",
  "start_url": "for web: the best public website (full https URL); else \"\"",
  "chosen_target": {"name": "the site/app you picked", "why": "one line: why this target"},
  "summary": "one line describing what will be done",
  "steps": [{"title": "short imperative step", "detail": "what happens", "sensitive": false}],
  "actions": [ /* for app/device ONLY — ordered machine actions, see below */ ],
  "form_fields": [{"name": "snake_case", "label": "question", "type": "text|number|select|date",
                   "options": ["..."], "required": true}]
}

RULES (all surfaces):
- steps: 3-9 ordered, individually-verifiable actions. The LAST step before anything irreversible
  is a review/verify step.
- sensitive=true for ANY login / OTP / password / payment / final submit — the agent PAUSES and
  hands these to the user. NEVER put passwords/OTPs/card/CVV in form_fields.
- form_fields: every input needed to run the automatable steps. Prefer select/date with options.

MOST tasks are WEB. Choose "app" ONLY when the user is clearly changing THIS assistant (its
settings, theme, language, or their profile) — NOT for anything done on a website. Booking,
buying, applying, filling a portal, searching-and-acting → always "web".

WEB: give a REAL start_url (train→https://www.irctc.co.in, flights/hotels→makemytrip/goibibo,
shopping→amazon.in, jobs→the named portal; if the user named a site/URL, use it). NEVER leave
start_url empty for web. steps must be concrete BROWSER actions the agent performs (open the
site, search X, open the best result, fill a field, choose an option, review) — do NOT write
"ask the user …" steps; every input you need goes in form_fields instead. Leave "actions" empty —
web actions are decided live from the page.

APP: leave start_url "". Fill "actions" with items from this exact vocabulary:
  {"type":"navigate","path":"/settings|/home|/workspace|/onboarding"}
  {"type":"set_setting","key":"theme|language|voice","value":"..."}   (theme: light|dark; voice: on|off)
  {"type":"update_profile","field":"state|district|occupation|...","value":"..."}
  {"type":"open_url","url":"https://..."}

DEVICE: leave start_url "". Fill "actions" with ONLY safe file actions (sandboxed):
  {"type":"write_file","path":"name.txt","content":"..."}   {"type":"read_file","path":"name.txt"}
  {"type":"list_dir","path":"."}
  Never request shell commands, installs, or system changes.

Keep labels short and in simple language."""


def _clean_json(text: str) -> str:
    t = (text or "").strip()
    if "```" in t:
        t = t.split("```")[1].split("```")[0].replace("json", "", 1).strip()
    if not t.startswith("{"):
        s, e = t.find("{"), t.rfind("}")
        if s != -1 and e > s:
            t = t[s:e + 1]
    return t


def _resolve_surface(goal: str, llm_surface: str, actions: list) -> str:
    """Trust the planner LLM's surface choice (it decides from the full prompt + context). The
    only guard — not a keyword list — is a validity check: 'app' and 'device' EXECUTE a concrete
    list of actions, so without any actions the plan is unusable there and we fall back to the
    web browser (the universal surface). This is what prevents a mis-planned task from no-op'ing."""
    if llm_surface in ("app", "device") and actions:
        return llm_surface
    return "web"


async def plan_task(goal: str, profile: dict, correlation_id: str = "", history: str = "") -> TaskPlan:
    """Build the checklist + consolidated form + start URL for a task. Never raises — returns a
    minimal generic plan on failure so the run can still proceed."""
    log.info("ipa_plan_start", goal=(goal or "")[:120], correlation_id=correlation_id,
             has_history=bool(history))
    ctx = f"\nRECENT CONVERSATION (resolve 'it'/'this'):\n{history}" if history else ""

    # TARGET SELECTION — give the planner a grounded shortlist of the best websites/apps for this
    # task (curated India-first catalog), so it CHOOSES a real, reliable destination instead of
    # guessing a URL. A proven recipe's site is added as the top candidate (it worked before).
    from src.ipa.targets import candidates as target_candidates
    cands = list(target_candidates(goal))
    log.debug("ipa_plan_candidates", candidates=len(cands), correlation_id=correlation_id)
    recipe = None
    try:
        from src.ipa.recipes import find_recipe
        recipe = await find_recipe(goal)
        if recipe and recipe.get("start_url"):
            cands.insert(0, {"name": f"{recipe['host']} (proven, used {recipe.get('success_count', 1)}×)",
                             "url": recipe["start_url"], "note": "succeeded for a similar task before",
                             "official": True})
            log.info("recipe_seeded_plan", host=recipe.get("host"), score=recipe.get("score"),
                     correlation_id=correlation_id)
    except Exception as exc:
        log.debug("recipe_seed_skipped", error=str(exc), error_type=type(exc).__name__,
                  correlation_id=correlation_id)
    cand_lines = "\n".join(
        f"- {c['name']}: {c['url']}  ({c.get('note', '')}{'; OFFICIAL' if c.get('official') else ''})"
        for c in cands[:6])
    recipe_block = (
        "\n\nCANDIDATE TARGETS (choose the BEST for this task — prefer the official/authoritative "
        "and India-first option, or a proven one; you may pick a better site you know). Put the "
        "chosen site in start_url and name it in chosen_target:\n" + cand_lines
    )

    try:
        log.debug("ipa_plan_llm_call", correlation_id=correlation_id)
        resp = await route_completion(
            messages=[
                {"role": "system", "content": runtime_prompt_header(profile, "en") + _PLANNER_SYSTEM},
                {"role": "user", "content": f"TASK: {goal}{ctx}{recipe_block}"},
            ],
            override_tier="primary", correlation_id=correlation_id,
        )
        data = json.loads(_clean_json(resp.content))
    except Exception as exc:
        log.warning("ipa_plan_failed", error=str(exc), error_type=type(exc).__name__,
                    correlation_id=correlation_id)
        data = {}

    steps: list[ChecklistStep] = []
    for i, s in enumerate(data.get("steps", []) or [], 1):
        if not isinstance(s, dict) or not s.get("title"):
            continue
        steps.append(ChecklistStep(
            id=i, title=str(s["title"])[:80], detail=str(s.get("detail", ""))[:200],
            sensitive=bool(s.get("sensitive")),
        ))
    fields: list[FormField] = []
    for f in data.get("form_fields", []) or []:
        if not isinstance(f, dict) or not f.get("name") or not f.get("label"):
            continue
        # Hard safety: never collect credentials/payment secrets in the up-front form.
        if any(w in str(f["name"]).lower() for w in ("password", "otp", "pin", "cvv", "card", "aadhaar")):
            continue
        ftype = f.get("type") if f.get("type") in ("text", "number", "select", "date") else "text"
        opts = [str(o) for o in f.get("options", [])][:10] if isinstance(f.get("options"), list) else []
        fields.append(FormField(
            name=str(f["name"])[:40], label=str(f["label"])[:80], type=ftype,
            options=opts, required=bool(f.get("required", True)),
        ))

    llm_surface = data.get("surface") if data.get("surface") in ("web", "app", "device") else "web"
    actions = [a for a in (data.get("actions") or []) if isinstance(a, dict) and a.get("type")][:20]
    surface = _resolve_surface(goal, llm_surface, actions)
    if surface != llm_surface:
        log.warning("ipa_plan_surface_fallback", llm_surface=llm_surface, surface=surface,
                    actions=len(actions), correlation_id=correlation_id)

    if not steps and surface == "web":   # generic safe fallback (web only)
        log.warning("ipa_plan_fallback_steps", surface="web", correlation_id=correlation_id)
        steps = [
            ChecklistStep(1, "Open the website", "Navigate to the relevant site"),
            ChecklistStep(2, "Find the task section", "Locate where the task is done"),
            ChecklistStep(3, "Fill in the details", "Enter the information you provided"),
            ChecklistStep(4, "Review before finishing", "Show you the result to confirm"),
            ChecklistStep(5, "You complete login/payment/submit", "Sensitive final step", sensitive=True),
        ]
    elif not steps:   # app/device: derive a step per action so progress is visible
        steps = [ChecklistStep(i, str(a.get("type", "action")).replace("_", " ").title(),
                               json.dumps({k: v for k, v in a.items() if k != "type"})[:120])
                 for i, a in enumerate(actions, 1)] or [ChecklistStep(1, "Apply change", "")]

    start_url = str(data.get("start_url") or "").strip()
    # For web, never end up with an empty/invalid URL — fall back to the best curated candidate
    # (which is the proven recipe's site when one exists), then to search.
    if surface == "web" and not start_url.startswith(("http://", "https://")):
        start_url = (cands[0]["url"] if cands else "https://www.google.com")
        log.warning("ipa_plan_start_url_fallback", start_url=start_url[:120],
                    correlation_id=correlation_id)

    ct = data.get("chosen_target") if isinstance(data.get("chosen_target"), dict) else {}
    target = {
        "name": str(ct.get("name", ""))[:60] or (cands[0]["name"] if cands and surface == "web" else ""),
        "why": str(ct.get("why", ""))[:160],
        "url": start_url if surface == "web" else "",
        "alternatives": [{"name": c["name"], "url": c["url"]} for c in cands[1:4]] if surface == "web" else [],
    }
    log.info("ipa_plan_built", correlation_id=correlation_id, surface=surface,
             start_url=(start_url or "")[:120], steps=len(steps), form_fields=len(fields),
             actions=len(actions), target=target.get("name", ""), seeded_by_recipe=bool(recipe))
    return TaskPlan(
        goal=goal, start_url=start_url, steps=steps, form_fields=fields,
        summary=str(data.get("summary", ""))[:200] or f"Plan to: {goal}",
        surface=surface, actions=actions, target=target,
    )
