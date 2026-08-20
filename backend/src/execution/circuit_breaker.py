"""
Per-session circuit breakers.

Bounds tool/agent call rates per session to contain runaway loops or abuse. Uses a
simple in-process sliding window (sufficient per worker); swap for Redis when scaling
horizontally. Tripping raises CircuitOpenError.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

import structlog

from src.config import settings
from src.core.metrics import CIRCUIT_BREAKER_TRIPS

log = structlog.get_logger("execution.circuit_breaker")


class CircuitOpenError(Exception):
    """Raised when a session exceeds its allowed call rate for a kind of call."""


class CircuitBreaker:
    def __init__(self, window_seconds: int = 60) -> None:
        self._window = window_seconds
        self._events: dict[tuple[str, str], deque[float]] = defaultdict(deque)

    def _limit(self, kind: str) -> int:
        if kind == "agent":
            return settings.CIRCUIT_BREAKER_AGENT_CALLS_PER_MIN
        return settings.CIRCUIT_BREAKER_TOOL_CALLS_PER_MIN

    def check(self, session_id: str, kind: str = "tool", *, now: float | None = None) -> None:
        """Record a call and raise CircuitOpenError if the rate limit is exceeded (in-process)."""
        now = time.time() if now is None else now
        key = (session_id, kind)
        q = self._events[key]
        cutoff = now - self._window
        while q and q[0] < cutoff:
            q.popleft()
        limit = self._limit(kind)
        if len(q) >= limit:
            CIRCUIT_BREAKER_TRIPS.labels(kind=kind).inc()
            log.warning("circuit_open", session_id=session_id, kind=kind, limit=limit)
            raise CircuitOpenError(f"{kind} call rate exceeded ({limit}/min) for session")
        q.append(now)

    async def check_async(self, session_id: str, kind: str = "tool", *, now: float | None = None) -> None:
        """Redis-backed rate check so the per-session limit is UNIFORM across all uvicorn workers
        and replicas (the in-process window counted per-worker, so N workers allowed N× the rate).
        Uses an atomic per-minute INCR+EXPIRE bucket. Fails over to the in-process window when Redis
        is unavailable, so the limit is still enforced per worker rather than dropped entirely."""
        limit = self._limit(kind)
        try:
            from src.db.redis import incr_with_expiry
            count = await incr_with_expiry(f"nipun:cb:{kind}:{session_id}", self._window)
        except Exception as exc:
            log.debug("circuit_breaker_redis_unavailable_fallback", error=str(exc))
            self.check(session_id, kind, now=now)
            return
        if count > limit:
            CIRCUIT_BREAKER_TRIPS.labels(kind=kind).inc()
            log.warning("circuit_open", session_id=session_id, kind=kind, limit=limit, backend="redis")
            raise CircuitOpenError(f"{kind} call rate exceeded ({limit}/min) for session")

    def reset(self, session_id: str, kind: str | None = None) -> None:
        if kind is None:
            for k in list(self._events):
                if k[0] == session_id:
                    del self._events[k]
        else:
            self._events.pop((session_id, kind), None)


# Module-level singleton.
breaker = CircuitBreaker()
