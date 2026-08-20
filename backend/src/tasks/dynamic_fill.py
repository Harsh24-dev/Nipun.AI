"""
Fill a form on ANY site the user names — the open-ended counterpart to the fixed-service
FormAssistants. Flow (all read-only, no submission, no credentials):

  1. FETCH   the page the user pointed at (raw HTML).
  2. ANALYZE its real form fields (form_analyzer — deterministic, never invents a field).
  3. MAP     the user's OWN details onto the safe fields with the LLM (strictly no invention).
  4. HAND OFF a filled, reviewable package + the site link; credentials/OTP/captcha/submit
     stay as the user's own steps.

Stateless and per-call: every argument is passed in, nothing is shared between users, so it
is safe under concurrency (see the multi-user design notes in the repo).
"""

from __future__ import annotations

import json
import re

import structlog

from src.core.runtime_context import runtime_prompt_header
from src.execution.guards import scan_for_credentials
from src.llm.router import route_completion
from src.tasks.form_analyzer import extract_form_fields, html_has_form

log = structlog.get_logger("tasks.dynamic_fill")

_URL_RE = re.compile(r"https?://[^\s<>\"')]+", re.IGNORECASE)
_MAX_FIELDS = 40   # cap prompt size on huge pages

_MAP_SYSTEM = """You map a user's OWN details onto the fields of a web form they asked Nipun to
fill. You are given the form's fields (name + human label + type) and everything Nipun knows
about the user (profile + answers + conversation). Return a value for a field ONLY when the
user's data clearly provides it.

HARD RULES:
- Use ONLY the provided user data. NEVER invent, guess, or fabricate a value (no made-up
  names, numbers, dates, addresses, IDs).
- If you are not confident a field's value is present in the user data, leave that field OUT.
- Never output a password, OTP, PIN, card number, CVV, captcha, or any secret — even if it
  somehow appears in the data.
- Match by meaning: e.g. a field labelled "Applicant's full name" maps to the user's name;
  "Mobile"/"Contact no." maps to their phone.

Respond with STRICT JSON only: {"values": {"<field_name>": "<value>", ...}}. Empty object if
nothing can be confidently filled."""


def find_url(text: str) -> str:
    """First http(s) URL in the text, or '' — the site the user wants filled."""
    m = _URL_RE.search(text or "")
    return m.group(0).rstrip(".,);") if m else ""


def _site_name(url: str) -> str:
    m = re.match(r"https?://([^/]+)", url or "")
    return (m.group(1).replace("www.", "") if m else url) or "the site"


async def fill_form_on_site(
    url: str, profile: dict, answers: dict, query: str, language: str = "en",
    correlation_id: str = "",
) -> dict:
    """Fetch → analyze → map → hand-off. Returns a step_action card. Never raises; on any
    failure returns a card that degrades gracefully (asks the user for the values)."""
    from src.mcp.live.http import get_text

    site = _site_name(url)
    portal = {"name": site, "url": url}
    disclaimer = ("For your safety, Nipun fills only non-sensitive fields. It NEVER enters your "
                  "password, OTP, PIN, card, captcha, or the final submit — you do those yourself "
                  "on the official site.")

    # 1. FETCH
    try:
        html = await get_text(url)
    except Exception as exc:
        log.warning("dynamic_fill_fetch_failed", url=url[:120], error=str(exc), correlation_id=correlation_id)
        html = None
    if not html or not html_has_form(html):
        return {
            "cardType": "step_action",
            "title": f"Fill the form on {site}",
            "summary": (f"I couldn't read a fillable form directly from {site} — the page may load "
                        f"its form with JavaScript, or need a login first. Tell me the fields it "
                        f"asks for (or the details to use) and I'll prepare every value for you to "
                        f"paste in; you'll still do the login, OTP, and submit yourself."),
            "portal": portal,
            "ready_for_handoff": False,
            "disclaimer": disclaimer,
        }

    # 2. ANALYZE
    fields = extract_form_fields(html)[:_MAX_FIELDS]
    safe = [f for f in fields if not f["sensitive"]]
    sensitive = [f for f in fields if f["sensitive"]]
    if not safe:
        return {
            "cardType": "step_action",
            "title": f"Fill the form on {site}",
            "summary": f"The form on {site} only has sensitive fields (like login/OTP) that you must "
                       f"enter yourself. I can't safely fill those. Open {site} and complete them.",
            "portal": portal,
            "steps": _user_only_steps(sensitive),
            "ready_for_handoff": False,
            "disclaimer": disclaimer,
        }

    # 3. MAP (LLM, strictly no invention)
    user_data = {**(profile or {}), **(answers or {})}
    user_data = {k: v for k, v in user_data.items()
                 if v not in (None, "", [], {}) and not str(k).startswith("_")}
    field_lines = "\n".join(
        f"- name={f['name']} | label=\"{f['label']}\" | type={f['type']}"
        f"{' | required' if f['required'] else ''}"
        f"{' | options=' + ', '.join(f['options'][:8]) if f['options'] else ''}"
        for f in safe
    )
    values: dict = {}
    try:
        result = await route_completion(
            messages=[
                {"role": "system",
                 "content": runtime_prompt_header(profile, language) + _MAP_SYSTEM},
                {"role": "user",
                 "content": f"FORM: {site}\nUSER GOAL: {query}\n\nFORM FIELDS:\n{field_lines}\n\n"
                            f"USER DATA (JSON):\n{json.dumps(user_data, ensure_ascii=False)}"},
            ],
            complexity="moderate",
            correlation_id=correlation_id,
        )
        content = result.content.strip()
        if "```" in content:
            content = content.split("```")[1].split("```")[0].replace("json", "", 1).strip()
        values = (json.loads(content) or {}).get("values", {}) or {}
    except Exception as exc:
        log.warning("dynamic_fill_map_failed", url=url[:120], error=str(exc), correlation_id=correlation_id)

    # 4. HAND OFF — assemble the filled package. Defence in depth: never surface a value that
    # scans as a credential, even if the model returned one.
    label_by_name = {f["name"]: f["label"] for f in safe}
    required_names = {f["name"] for f in safe if f["required"]}
    filled: list[dict] = []
    for name, val in values.items():
        if name not in label_by_name or val in (None, "", [], {}):
            continue
        if scan_for_credentials(f"{label_by_name[name]} {val}"):
            continue
        filled.append({"label": label_by_name[name], "value": val})

    filled_names = {f["name"] for f in safe if label_by_name[f["name"]] in {x["label"] for x in filled}}
    missing = [f["label"] for f in safe if f["required"] and f["name"] not in filled_names]

    ready = not missing
    if ready and filled:
        summary = (f"I've prepared {len(filled)} field(s) for the form on {site} from your details. "
                   f"Review them, then complete only the steps below yourself — login, OTP, captcha, "
                   f"and submit are always yours.")
    elif filled:
        summary = (f"I've filled {len(filled)} field(s) on {site} from your details. I still need: "
                   f"{', '.join(missing)}. Share these and I'll complete the rest; login/OTP/submit "
                   f"stay with you.")
    else:
        summary = (f"I found the form on {site} but don't yet have the details it needs "
                   f"({', '.join(missing) or 'the required fields'}). Share them and I'll fill it for "
                   f"you, leaving login/OTP/submit to you.")

    return {
        "cardType": "step_action",
        "title": f"Form on {site} — {'ready for your final steps' if ready else 'a few details needed'}",
        "summary": summary,
        "filled_form": {"service": site, "url": url, "fields": filled},
        "missing_fields": missing or None,
        "steps": _user_only_steps(sensitive),
        "portal": portal,
        "ready_for_handoff": ready,
        "disclaimer": disclaimer,
    }


def _user_only_steps(sensitive: list[dict]) -> list[dict]:
    steps = [{"title": f"Enter your {f['label']} yourself", "status": "pending",
              "desc": "Sensitive field — Nipun never sees or fills this."} for f in sensitive[:6]]
    steps.append({"title": "Review the prepared values, then submit the form yourself",
                  "desc": "You stay in control of the final submit.", "status": "pending"})
    return steps
