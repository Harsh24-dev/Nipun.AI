"""
L1/L2 — Session & Profile Cache (Redis).
  L1: Semantic response cache — avoid calling LLM for near-duplicate queries
  L2: User session + profile cache
"""

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any

import numpy as np
import structlog

from src.config import settings
from src.core.metrics import CACHE_HITS, CACHE_MISSES
from src.db.redis import delete, exists, get_json, get_redis, set_json

log = structlog.get_logger("memory.session")


# ── L2: Session & Profile Cache ───────────────────────────────────────────────

def _session_key(user_id: str) -> str:
    return f"session:{user_id}"


def _profile_key(user_id: str) -> str:
    return f"profile:{user_id}"


async def get_session(user_id: str) -> dict | None:
    data = await get_json(_session_key(user_id))
    if data:
        CACHE_HITS.labels(service="memory", cache_type="session").inc()
    else:
        CACHE_MISSES.labels(service="memory", cache_type="session").inc()
    return data


async def set_session(user_id: str, session: dict) -> None:
    await set_json(_session_key(user_id), session, ttl=settings.CACHE_SESSION_TTL)


async def get_profile(user_id: str) -> dict | None:
    data = await get_json(_profile_key(user_id))
    if data:
        CACHE_HITS.labels(service="memory", cache_type="profile").inc()
    return data


async def set_profile(user_id: str, profile: dict) -> None:
    await set_json(_profile_key(user_id), profile, ttl=settings.CACHE_PROFILE_TTL)


async def update_profile(user_id: str, patch: dict) -> dict:
    profile = await get_profile(user_id) or {}
    profile.update(patch)
    await set_profile(user_id, profile)
    return profile


async def invalidate_profile(user_id: str) -> None:
    """Drop the cached profile so the next read reloads fresh from Postgres.
    Call this whenever the DB profile changes (e.g. PATCH /profile)."""
    await delete(_profile_key(user_id))


# Stable, reusable facts the assistant is allowed to LEARN from conversation and persist
# durably (so it remembers you across sessions, like a good assistant). Only long-lived
# identity/agronomic facts — never transient, query-specific details. Mapped to the exact
# columns in `users` / `user_profiles`.
_LEARNABLE_USER_SCALARS = ("state", "district", "occupation")          # users (TEXT)
_LEARNABLE_USER_ARRAYS = ("interests",)                                # users (TEXT[])
_LEARNABLE_PROFILE_SCALARS = ("soil_type",)                            # user_profiles (TEXT)
_LEARNABLE_PROFILE_NUMERIC = ("land_size_acres",)                      # user_profiles (NUMERIC)
_LEARNABLE_PROFILE_ARRAYS = ("current_crops", "active_schemes")        # user_profiles (TEXT[])
LEARNABLE_FACT_KEYS = (
    _LEARNABLE_USER_SCALARS + _LEARNABLE_USER_ARRAYS + _LEARNABLE_PROFILE_SCALARS
    + _LEARNABLE_PROFILE_NUMERIC + _LEARNABLE_PROFILE_ARRAYS
)


async def persist_profile_facts(user_id: str, facts: dict) -> dict:
    """Durably persist conversation-learned stable facts to Postgres, then refresh cache.

    - Scalars use COALESCE so we FILL EMPTY fields but never clobber a value the user
      already has (conversation is lower-authority than an explicit profile edit).
    - Array fields (interests/crops/schemes) are UNION-merged, de-duplicated.
    Only whitelisted keys are written. Best-effort: returns {} and logs on any failure."""
    facts = {k: v for k, v in (facts or {}).items()
             if k in LEARNABLE_FACT_KEYS and v not in (None, "", [], {})}
    if not facts:
        return {}

    def _as_array(v):
        if isinstance(v, (list, tuple, set)):
            return [str(x).strip() for x in v if str(x).strip()]
        return [str(v).strip()] if str(v).strip() else []

    try:
        from src.db.postgres import execute

        # users table — scalars (fill-empty) + arrays (union-merge)
        await execute(
            """
            UPDATE users SET
                state       = COALESCE(state, $2),
                district    = COALESCE(district, $3),
                occupation  = COALESCE(occupation, $4),
                interests   = ARRAY(SELECT DISTINCT unnest(COALESCE(interests, '{}') || $5::text[])),
                updated_at  = NOW()
            WHERE id = $1::uuid
            """,
            user_id,
            facts.get("state"), facts.get("district"), facts.get("occupation"),
            _as_array(facts.get("interests")),
        )

        land = facts.get("land_size_acres")
        try:
            land_val = float(land) if land is not None else None
        except (TypeError, ValueError):
            land_val = None

        # user_profiles — UPSERT: fill-empty scalars, union-merge arrays
        await execute(
            """
            INSERT INTO user_profiles (user_id, soil_type, land_size_acres, current_crops, active_schemes)
            VALUES ($1::uuid, $2, $3, $4::text[], $5::text[])
            ON CONFLICT (user_id) DO UPDATE SET
                soil_type       = COALESCE(user_profiles.soil_type, EXCLUDED.soil_type),
                land_size_acres = COALESCE(user_profiles.land_size_acres, EXCLUDED.land_size_acres),
                current_crops   = ARRAY(SELECT DISTINCT unnest(
                                      COALESCE(user_profiles.current_crops, '{}') || EXCLUDED.current_crops)),
                active_schemes  = ARRAY(SELECT DISTINCT unnest(
                                      COALESCE(user_profiles.active_schemes, '{}') || EXCLUDED.active_schemes)),
                updated_at      = NOW()
            """,
            user_id,
            facts.get("soil_type"), land_val,
            _as_array(facts.get("current_crops")), _as_array(facts.get("active_schemes")),
        )

        await invalidate_profile(user_id)   # next read reloads the enriched profile
        log.info("profile_facts_persisted", user_id=user_id, keys=sorted(facts.keys()))
        return facts
    except Exception as exc:
        log.warning("profile_facts_persist_failed", user_id=user_id, error=str(exc))
        return {}


# Fields loaded from Postgres into the profile dict every agent receives. Keeping this
# list in one place documents exactly what personal data feeds answer generation. Only
# STABLE, reusable facts live here (identity + long-lived preferences). Transient,
# query-specific details are gathered per-turn via a clarify form, not stored.
_PROFILE_SELECT = """
    SELECT u.name, u.language, u.state, u.district, u.occupation, u.gender,
           u.bio, u.interests,
           p.land_size_acres, p.soil_type, p.current_crops, p.active_schemes,
           p.preferences
    FROM users u
    LEFT JOIN user_profiles p ON p.user_id = u.id
    WHERE u.id = $1::uuid
"""


def _row_to_profile(row: Any) -> dict:
    """Map a users ⨝ user_profiles row into the clean profile dict agents consume.
    Empty/None values are dropped so each agent's `.get(field, default)` fallback works."""
    prefs = row["preferences"]
    if isinstance(prefs, str):
        try:
            prefs = json.loads(prefs)
        except (TypeError, ValueError):
            prefs = {}
    land = row["land_size_acres"]
    profile = {
        "name": row["name"],
        "language": row["language"],
        "state": row["state"],
        "district": row["district"],
        "occupation": row["occupation"],
        "gender": row["gender"],
        "bio": row["bio"],
        "interests": list(row["interests"] or []),
        # Long-lived agronomic facts (only if the user chose to save them).
        "land_size_acres": float(land) if land is not None else None,
        "soil_type": row["soil_type"],
        "current_crops": list(row["current_crops"] or []),
        "active_schemes": list(row["active_schemes"] or []),
        # Learned adaptive-explanation preferences
        "preferences": prefs or {},
    }
    return {k: v for k, v in profile.items() if v not in (None, "", [], {})}


async def load_profile(user_id: str) -> dict:
    """The full, generation-ready user profile.

    Redis cache in front of a `users ⨝ user_profiles` read. Previously the pipeline
    read the cache ONLY — which was never populated by the DB — so agents almost always
    received an empty profile and lost all personalization. This loads from Postgres on
    a cache miss and warms the cache. Returns {} when the user is unknown or on error.
    """
    cached = await get_profile(user_id)
    if cached:
        return cached
    CACHE_MISSES.labels(service="memory", cache_type="profile").inc()
    try:
        from src.db.postgres import fetchrow

        row = await fetchrow(_PROFILE_SELECT, user_id)
    except Exception as exc:
        log.warning("profile_db_load_failed", user_id=user_id, error=str(exc))
        return {}
    if not row:
        return {}
    profile = _row_to_profile(row)
    try:
        await set_profile(user_id, profile)   # warm the cache for subsequent turns
    except Exception as exc:  # pragma: no cover - cache warming is best-effort
        log.warning("profile_cache_warm_failed", user_id=user_id, error=str(exc))
    return profile


# ── L1: Semantic Response Cache ───────────────────────────────────────────────
# Cache LLM responses for semantically similar queries using vector cosine similarity.
# Key: "sem_cache:{user_id}" → list of {query_embedding, response_card, created_at}

_SEM_CACHE_KEY_PREFIX = "sem_cache"
_MAX_ENTRIES_PER_USER = 100


async def semantic_cache_get(user_id: str, query_embedding: list[float]) -> dict | None:
    """
    Check if a semantically similar query has been answered before.
    Returns cached response_card if cosine similarity > threshold.

    Storage is a Redis LIST (one JSON entry per element) so writes are an atomic LPUSH append —
    two concurrent turns for the same user can't clobber each other's entries (the old code did a
    non-atomic get-all → append → set-all read-modify-write, last-writer-wins).
    """
    key = f"{_SEM_CACHE_KEY_PREFIX}:{user_id}"
    try:
        raw = await get_redis().lrange(key, 0, _MAX_ENTRIES_PER_USER - 1)
    except Exception:
        raw = None   # WRONGTYPE (legacy blob key) or Redis error → treat as a miss
    entries = []
    for x in (raw or []):
        try:
            entries.append(json.loads(x))
        except (TypeError, ValueError):
            continue
    if not entries:
        CACHE_MISSES.labels(service="memory", cache_type="semantic").inc()
        return None

    query_vec = np.array(query_embedding, dtype=np.float32)
    query_norm = np.linalg.norm(query_vec)
    if query_norm == 0:
        return None

    best_score = 0.0
    best_entry = None

    for entry in entries:
        cached_vec = np.array(entry["embedding"], dtype=np.float32)
        cosine_sim = float(np.dot(query_vec, cached_vec) / (query_norm * np.linalg.norm(cached_vec) + 1e-8))
        if cosine_sim > best_score:
            best_score = cosine_sim
            best_entry = entry

    threshold = settings.SEMANTIC_CACHE_SIMILARITY_THRESHOLD
    if best_score >= threshold and best_entry:
        CACHE_HITS.labels(service="memory", cache_type="semantic").inc()
        log.info("semantic_cache_hit", user_id=user_id, similarity=round(best_score, 4))
        return best_entry["response_card"]

    CACHE_MISSES.labels(service="memory", cache_type="semantic").inc()
    return None


async def semantic_cache_set(
    user_id: str, query_embedding: list[float], response_card: dict
) -> None:
    key = f"{_SEM_CACHE_KEY_PREFIX}:{user_id}"
    entry = json.dumps({
        "embedding": query_embedding,
        "response_card": response_card,
        "created_at": time.time(),
    })
    ttl = settings.CACHE_LLM_RESPONSE_TTL

    async def _push() -> None:
        # Atomic append + cap + TTL refresh — no read-modify-write, so concurrent same-user
        # writes cannot clobber one another. Newest at the head; LTRIM bounds the list length.
        r = get_redis()
        pipe = r.pipeline()
        pipe.lpush(key, entry)
        pipe.ltrim(key, 0, _MAX_ENTRIES_PER_USER - 1)
        pipe.expire(key, ttl)
        await pipe.execute()

    try:
        await _push()
    except Exception as exc:
        # A legacy build stored this key as a single JSON blob (string); LPUSH then raises
        # WRONGTYPE. Drop the stale key and retry once so the list format takes over cleanly.
        try:
            await get_redis().delete(key)
            await _push()
        except Exception:
            log.debug("semantic_cache_set_failed", user_id=user_id, error=str(exc))
