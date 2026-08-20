"""
Per-user preference learning.

Learn a small preference vector from the feedback table (+1/-1) — preferred length,
formality, language variant, and modality — and store it on the user profile so the
explanation planner can inject it. Best-effort: needs Postgres; degrades to a no-op.
"""

from __future__ import annotations

import structlog

log = structlog.get_logger("synthesis.preferences")


def _aggregate(rows: list[dict]) -> dict:
    """Turn feedback rows into a coarse preference vector."""
    prefs: dict = {}
    length_score = 0
    for r in rows:
        rating = r.get("rating", 0) or 0
        card = r.get("response_card") or {}
        modality = card.get("cardType")
        depth = card.get("depth")
        length = len(card.get("summary") or "")
        # Reward the modality/depth of up-voted answers; penalise down-voted.
        if modality:
            prefs.setdefault("_modality_votes", {})
            prefs["_modality_votes"][modality] = prefs["_modality_votes"].get(modality, 0) + rating
        if depth:
            prefs.setdefault("_depth_votes", {})
            prefs["_depth_votes"][depth] = prefs["_depth_votes"].get(depth, 0) + rating
        length_score += rating * (1 if length > 400 else -1)

    if prefs.get("_modality_votes"):
        best = max(prefs["_modality_votes"], key=prefs["_modality_votes"].get)
        if prefs["_modality_votes"][best] > 0:
            prefs["modality"] = best
    if prefs.get("_depth_votes"):
        best = max(prefs["_depth_votes"], key=prefs["_depth_votes"].get)
        if prefs["_depth_votes"][best] > 0:
            prefs["goal"] = "master" if best == "mastery" else "understand"
    prefs["preferred_length"] = "long" if length_score > 0 else "short"
    # strip internal tallies
    return {k: v for k, v in prefs.items() if not k.startswith("_")}


async def learn_preferences(user_id: str) -> dict:
    """Recompute and persist a user's preference vector. Returns the vector (or {})."""
    try:
        from src.db.postgres import execute, fetch

        rows = await fetch(
            """
            SELECT f.rating, t.response_card
            FROM feedback f
            LEFT JOIN task_history t ON t.correlation_id = f.correlation_id
            WHERE f.user_id = $1
            ORDER BY f.created_at DESC
            LIMIT 100
            """,
            user_id,
        )
        prefs = _aggregate([dict(r) for r in rows])
        if prefs:
            await execute(
                """
                UPDATE user_profiles
                SET preferences = COALESCE(preferences, '{}'::jsonb) || $2::jsonb,
                    updated_at = NOW()
                WHERE user_id = $1
                """,
                user_id, __import__("json").dumps(prefs),
            )
        log.info("preferences_learned", user_id=user_id, prefs=prefs)
        return prefs
    except Exception as exc:
        log.debug("learn_preferences_skipped", error=str(exc))
        return {}
