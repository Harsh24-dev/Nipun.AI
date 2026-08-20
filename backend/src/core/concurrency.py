"""
Global in-flight concurrency gate (backpressure).

A cross-worker cap on how many queries are being processed at once, so a traffic spike degrades
gracefully — the caller gets a "busy, please retry" response — instead of collapsing the event
loop, the thread pools, and the upstream LLM/tool quota all at once.

Backed by a Redis sorted set of in-flight tokens scored by their acquire time:
  * ACQUIRE atomically prunes stale (crashed-holder) tokens by score, adds this request's token,
    and counts the set. Over the cap → the token is removed and the caller is told to retry.
  * RELEASE removes the token.
Because stale tokens are pruned by score on every acquire, a worker that crashes without releasing
cannot leak a slot forever — the slot self-heals after INFLIGHT_SLOT_TTL seconds.

Fail-OPEN: if Redis is unavailable the gate lets the request through (availability over strict
capping), mirroring the rest of the hot path's Redis-outage behaviour.
"""

from __future__ import annotations

import uuid

import structlog

from src.config import settings

log = structlog.get_logger("core.concurrency")

_INFLIGHT_KEY = "nipun:inflight:queries"


async def acquire_slot(now: float) -> tuple[bool, str | None]:
    """Try to take an in-flight slot. Returns (granted, token). `now` is a caller-supplied
    monotonic-ish timestamp (time.time()) — passed in so this module stays free of Date/now calls.

    granted=False means we are at capacity; the caller should return a busy response. On any Redis
    error we FAIL OPEN (granted=True, token=None) so a Redis blip can't take the API down."""
    cap = settings.MAX_INFLIGHT_QUERIES
    if not cap or cap <= 0:
        return True, None
    ttl = settings.INFLIGHT_SLOT_TTL
    token = str(uuid.uuid4())
    try:
        from src.db.redis import get_redis
        r = get_redis()
        pipe = r.pipeline()
        pipe.zremrangebyscore(_INFLIGHT_KEY, 0, now - ttl)   # drop crashed holders' stale slots
        pipe.zadd(_INFLIGHT_KEY, {token: now})
        pipe.zcard(_INFLIGHT_KEY)
        pipe.expire(_INFLIGHT_KEY, ttl * 2)
        results = await pipe.execute()
        count = results[2]
        if count > cap:
            # Over capacity — give the slot back and tell the caller to retry.
            try:
                await r.zrem(_INFLIGHT_KEY, token)
            except Exception:
                pass
            log.warning("inflight_cap_reached", count=count, cap=cap)
            return False, None
        return True, token
    except Exception as exc:
        log.debug("inflight_acquire_failed_fail_open", error=str(exc))
        return True, None


async def release_slot(token: str | None) -> None:
    """Release a previously-acquired slot. No-op for a None token (cap disabled / failed open)."""
    if not token:
        return
    try:
        from src.db.redis import get_redis
        await get_redis().zrem(_INFLIGHT_KEY, token)
    except Exception as exc:
        log.debug("inflight_release_failed", error=str(exc))
