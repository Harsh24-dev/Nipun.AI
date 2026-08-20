"""
Agentic job application — actually DO the work, don't just show a form.

When a user says "help me apply for a relevant job", they expect Nipun to act: understand
who they are, find real, currently-open, relevant roles, and prepare their application — not
return an empty form asking for details it can infer. This module:

  1. INFERS the target role + key skills + location from the user's message and profile
     (so "I'm an AI/ML student" → ML/AI roles, Python/ML skills — no dead-end questions).
  2. FINDS real openings via the job_search tool (portals + remote boards).
  3. PREPARES the application details it can fill from the profile, and hands off the parts
     only the user may do (login, OTP, upload, submit).

Read-only and credential-safe throughout; the final submit is always the user's.
"""

from __future__ import annotations

import json

import structlog

from src.core.runtime_context import runtime_prompt_header
from src.llm.router import route_completion

log = structlog.get_logger("tasks.job_apply")

_INFER_SYSTEM = """From the user's message and profile, infer what job they should apply to.
Use their stated field of study/work (e.g. "AI/ML student" → machine-learning / data roles).
Never invent personal facts. Respond with STRICT JSON only:
{"role": "<concise target role/title to search, e.g. 'Machine Learning Engineer'>",
 "skills": "<comma-separated key skills to highlight>",
 "location": "<preferred city/'Remote'/'' if unknown>",
 "level": "<intern|entry|mid|senior|'' if unknown>"}"""


async def _infer_target(query: str, profile: dict, answers: dict, language: str,
                        correlation_id: str) -> dict:
    """Infer role/skills/location so we never dead-end asking for what we can derive."""
    # Honour anything the user already gave.
    role = answers.get("target_role") or answers.get("role") or ""
    skills = answers.get("key_skills") or answers.get("skills") or ""
    location = answers.get("preferred_location") or profile.get("state") or profile.get("city") or ""
    if role and skills:
        return {"role": role, "skills": skills, "location": location, "level": ""}
    try:
        known = {k: v for k, v in {**profile, **answers}.items()
                 if v not in (None, "", [], {}) and not str(k).startswith("_")}
        result = await route_completion(
            messages=[
                {"role": "system", "content": runtime_prompt_header(profile, language) + _INFER_SYSTEM},
                {"role": "user", "content": f"MESSAGE: {query}\nPROFILE/ANSWERS: {json.dumps(known, ensure_ascii=False)}"},
            ],
            complexity="simple", correlation_id=correlation_id,
        )
        content = result.content.strip()
        if "```" in content:
            content = content.split("```")[1].split("```")[0].replace("json", "", 1).strip()
        data = json.loads(content)
        return {
            "role": role or data.get("role", "") or "relevant roles",
            "skills": skills or data.get("skills", ""),
            "location": location or data.get("location", ""),
            "level": data.get("level", ""),
        }
    except Exception as exc:
        log.warning("job_infer_failed", error=str(exc), correlation_id=correlation_id)
        return {"role": role or "relevant roles", "skills": skills, "location": location, "level": ""}


async def run_job_application(query: str, profile: dict, answers: dict, language: str = "en",
                              correlation_id: str = "") -> dict:
    """Find relevant openings and prepare the application. Returns a step_action card.
    Never raises — degrades to the prepared-application details if search is unavailable."""
    from src.mcp.tools import get_tool

    target = await _infer_target(query, profile, answers, language, correlation_id)
    role, skills, location = target["role"], target["skills"], target["location"]
    search_terms = " ".join(t for t in (target.get("level", ""), role) if t).strip() or role

    # FIND real openings.
    jobs: list[dict] = []
    tool = get_tool("job_search")
    if tool is not None:
        try:
            res = await tool.call({"query": search_terms, "location": location})
            if res.status == "ok":
                jobs = res.data.get("results", []) or []
        except Exception as exc:
            log.warning("job_search_failed", error=str(exc), correlation_id=correlation_id)

    # Application details Nipun can fill from what it knows (never credentials).
    prepared = {
        "Name": profile.get("name") or answers.get("name"),
        "Role applying for": role,
        "Key skills": skills,
        "Location": location or None,
    }
    prepared = {k: v for k, v in prepared.items() if v}

    steps = [
        {"title": (j.get("title") or "Opening")[:120],
         "desc": f"{(j.get('content') or '')[:160]} — Apply: {j.get('url', '')}".strip(" —"),
         "status": "pending"}
        for j in jobs[:6]
    ]
    # Then the user-only actions to finish any one of them.
    handoff = [
        {"title": "Pick a role above and open its apply link", "desc": "Opens the portal listing.", "status": "pending"},
        {"title": "Log in / create your account on the portal", "desc": "You do this — Nipun never sees it.", "status": "pending"},
        {"title": "Upload your résumé / tailored CV", "desc": "I can draft this for you — just ask.", "status": "pending"},
        {"title": "Review the pre-filled details, then submit + OTP yourself", "desc": "The final submit stays with you.", "status": "pending"},
    ]

    prepared_line = ("; ".join(f"{k}: {v}" for k, v in prepared.items())) or "your profile details"
    if jobs:
        summary = (f"I found {len(jobs)} current {role} opening(s){' near ' + location if location else ''} "
                   f"and prepared your application details ({prepared_line}). Pick one below and I'll fill "
                   f"everything except your login, OTP, and the final submit. Want me to tailor your CV to a "
                   f"specific one?")
    else:
        summary = (f"I've prepared your application as a {role} (highlighting {skills or 'your key skills'}). "
                   f"I couldn't pull live openings right now — open a portal like Naukri, LinkedIn, or the "
                   f"National Career Service and I'll fill every field for you except login/OTP/submit. Want your "
                   f"CV tailored for this role first?")

    return {
        "cardType": "step_action",
        "language": language,
        "title": f"Applying for: {role}",
        "summary": summary,
        "steps": (steps + handoff) if steps else handoff,
        "filled_form": {"service": "job_application", "fields": [{"label": k, "value": v} for k, v in prepared.items()]},
        "sources": [{"text": j.get("source", "Job portal"), "url": j.get("url", "")} for j in jobs[:6]],
        "ready_for_handoff": bool(jobs),
        "disclaimer": ("Nipun never asks for or enters your password, OTP, or the final submit — you complete "
                       "those on the official portal."),
    }
