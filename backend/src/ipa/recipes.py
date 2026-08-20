"""
Task recipes — learn from a SUCCESSFUL run so the same kind of task runs better next time, for
ANY user.

A recipe captures only the reusable HOW: the site, the checklist, and the generalized sequence of
actions that worked (each action's typed value is stored as the FORM-FIELD NAME it came from, not
the literal value). So a run that booked Lucknow→Shimla teaches the agent how to drive that site;
another user booking Pune→Goa reuses the same steps with their own values. No personal data is
stored here — that lives privately in each user's profile.

All functions are best-effort and never raise: recipes make the agent smarter but are never on the
critical path.
"""

from __future__ import annotations

import json
import re
from urllib.parse import urlparse

from src.core.logging import get_ipa_logger

log = get_ipa_logger("ipa.recipes")

_STOP = {"the", "a", "an", "of", "to", "for", "from", "in", "on", "and", "or", "me", "my", "i",
         "please", "book", "do", "want", "need", "with", "at", "this", "that", "it", "help"}


def _keywords(goal: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", (goal or "").lower())
    return [w for w in words if w not in _STOP and len(w) > 2]


def _host(url: str) -> str:
    try:
        return urlparse(url or "").netloc.replace("www.", "").lower()
    except Exception:
        return ""


def _overlap(a: list[str], b: list[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def value_key(text: str, answers: dict) -> str | None:
    """If a typed/selected value equals one of the user's form answers, return that field NAME so
    the recipe stays personal-data-free and reusable (store the placeholder, not the value)."""
    t = (text or "").strip().lower()
    if not t:
        return None
    for k, v in (answers or {}).items():
        if str(v).strip().lower() == t:
            return k
    return None


async def save_recipe(host: str, goal: str, start_url: str, steps: list[dict],
                      trace: list[dict], form_fields: list[dict], created_by: str = "") -> None:
    """Record (or reinforce) a recipe from a successful run. Dedupes against a close existing
    recipe on the same host (increments its success_count) instead of piling up near-duplicates."""
    if not host or not trace:
        log.debug("recipe_save_noop", host=host, trace=len(trace or []))
        return
    try:
        from src.db.postgres import execute, fetch

        kws = _keywords(goal)
        kw_str = " ".join(kws)
        log.debug("recipe_save_start", host=host, steps=len(steps), trace=len(trace),
                  keywords=len(kws))
        rows = await fetch(
            "SELECT id, keywords FROM task_recipes WHERE host = $1 ORDER BY updated_at DESC LIMIT 20",
            host,
        )
        best_id, best = None, 0.0
        for r in rows:
            score = _overlap(kws, (r["keywords"] or "").split())
            if score > best:
                best, best_id = score, r["id"]
        if best_id is not None and best >= 0.7:
            await execute(
                "UPDATE task_recipes SET success_count = success_count + 1, updated_at = now(), "
                "steps = $2::jsonb, trace = $3::jsonb, form_fields = $4::jsonb WHERE id = $1",
                best_id, json.dumps(steps), json.dumps(trace), json.dumps(form_fields),
            )
            log.info("recipe_reinforced", host=host, recipe_id=str(best_id),
                     match_score=round(best, 2), steps=len(steps))
            return
        await execute(
            "INSERT INTO task_recipes (host, goal, keywords, start_url, steps, trace, form_fields, created_by) "
            "VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7::jsonb, $8::uuid)",
            host, goal[:400], kw_str, start_url, json.dumps(steps), json.dumps(trace),
            json.dumps(form_fields), created_by or None,
        )
        log.info("recipe_saved", host=host, goal=goal[:60], steps=len(steps), trace=len(trace))
    except Exception as exc:
        log.debug("recipe_save_skipped", error=str(exc), error_type=type(exc).__name__)


async def find_recipe(goal: str, start_url_hint: str = "") -> dict | None:
    """Best matching proven recipe for a new goal, or None. Used to seed the planner with a plan
    that already worked (higher accuracy), across ALL users."""
    try:
        from src.db.postgres import fetch

        kws = _keywords(goal)
        if not kws:
            log.debug("recipe_find_no_keywords", goal=(goal or "")[:60])
            return None
        host_hint = _host(start_url_hint)
        rows = await fetch(
            "SELECT host, goal, start_url, steps, trace, form_fields, success_count, keywords "
            "FROM task_recipes ORDER BY success_count DESC, updated_at DESC LIMIT 50"
        )
        best, best_score = None, 0.0
        for r in rows:
            score = _overlap(kws, (r["keywords"] or "").split())
            if host_hint and r["host"] == host_hint:
                score += 0.15
            if score > best_score:
                best_score, best = score, r
        if best is None or best_score < 0.34:
            log.info("recipe_find_no_match", candidates=len(rows),
                     best_score=round(best_score, 2), host_hint=host_hint)
            return None
        log.info("recipe_found", host=best["host"], score=round(best_score, 2),
                 success_count=best["success_count"], candidates=len(rows))
        return {
            "host": best["host"], "goal": best["goal"], "start_url": best["start_url"],
            "steps": best["steps"], "trace": best["trace"], "form_fields": best["form_fields"],
            "success_count": best["success_count"], "score": round(best_score, 2),
        }
    except Exception as exc:
        log.debug("recipe_find_skipped", error=str(exc), error_type=type(exc).__name__)
        return None
