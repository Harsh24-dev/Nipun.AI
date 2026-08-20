"""
LLM Router — picks the right model tier based on query complexity.
All tiers configurable via .env with zero code changes.
"""

import time
from collections.abc import AsyncGenerator
from typing import Any, Literal

import structlog

from src.config import settings
from src.llm.client import LLMResponse, call_llm, stream_llm

log = structlog.get_logger("llm.router")

Tier = Literal["fast", "primary", "fallback"]


# ── Lightweight per-tier circuit breaker (fail-open) ──────────────────────────
# There was no breaker on the LLM path: if a tier's provider went down, every request still
# paid that tier's full timeout (and its internal retries) before falling back. We track
# consecutive failures per tier on a monotonic clock and, once a tier trips, route straight to
# its fallback for a short cooldown instead of hammering the dead tier every request. This only
# REORDERS/skips tiers — it never blocks or rejects a request. Fail-open: if the fallback also
# looks tripped we still attempt it (the except path below always tries the fallback).
_BREAKER_THRESHOLD = 3        # consecutive failures before a tier is tripped
_BREAKER_COOLDOWN = 30.0      # seconds to skip a tripped tier before probing it again
_tier_consec_fails: dict[str, int] = {}
_tier_open_until: dict[str, float] = {}


def _fallback_of(tier: Tier) -> Tier | None:
    """The next tier to try when `tier` fails/trips (mirrors the except-path logic)."""
    if tier == "fast":
        return "primary"
    if tier == "primary":
        return "fallback"
    return None


def _breaker_open(tier: Tier) -> bool:
    return time.monotonic() < _tier_open_until.get(tier, 0.0)


def _record_tier_success(tier: Tier) -> None:
    _tier_consec_fails[tier] = 0
    _tier_open_until[tier] = 0.0


def _record_tier_failure(tier: Tier) -> None:
    n = _tier_consec_fails.get(tier, 0) + 1
    _tier_consec_fails[tier] = n
    if n >= _BREAKER_THRESHOLD:
        _tier_open_until[tier] = time.monotonic() + _BREAKER_COOLDOWN
        log.warning("llm_breaker_tripped", tier=tier, consecutive_failures=n,
                    cooldown_s=_BREAKER_COOLDOWN)


def _get_tier_config(tier: Tier) -> tuple[str, str, int, float]:
    """Returns (provider, model, max_tokens, temperature) for a tier."""
    if tier == "fast":
        return (
            settings.LLM_FAST_PROVIDER,
            settings.LLM_FAST_MODEL,
            settings.LLM_FAST_MAX_TOKENS,
            settings.LLM_FAST_TEMPERATURE,
        )
    if tier == "primary":
        return (
            settings.LLM_PRIMARY_PROVIDER,
            settings.LLM_PRIMARY_MODEL,
            settings.LLM_PRIMARY_MAX_TOKENS,
            settings.LLM_PRIMARY_TEMPERATURE,
        )
    return (
        settings.LLM_FALLBACK_PROVIDER,
        settings.LLM_FALLBACK_MODEL,
        settings.LLM_FALLBACK_MAX_TOKENS,
        settings.LLM_FALLBACK_TEMPERATURE,
    )


def select_tier(complexity: str, has_tools: bool = False) -> Tier:
    """
    Routing logic:
      simple   → fast   (Gemini Flash — cheap, <500ms)
      multi_step → primary (Claude — accurate)
      action   → primary (Claude with tools)
    """
    if has_tools or complexity == "action":
        return "primary"
    if complexity == "multi_step":
        return "primary"
    return "fast"


async def route_completion(
    messages: list[dict[str, str]],
    complexity: str = "simple",
    has_tools: bool = False,
    correlation_id: str = "",
    override_tier: Tier | None = None,
    **kwargs: Any,
) -> LLMResponse:
    """
    Route a completion request to the appropriate model tier.
    Falls back to the next tier if the selected tier fails.
    """
    tier = override_tier or select_tier(complexity, has_tools)

    # Circuit breaker: if the selected tier is in a post-failure cooldown, skip it and route
    # straight to its fallback tier (fail-open — only when a fallback exists). This avoids paying
    # the dead tier's timeout on every request during an outage.
    _fb = _fallback_of(tier)
    if _fb is not None and _breaker_open(tier):
        log.warning(
            "llm_breaker_skip",
            skipped_tier=tier,
            routed_tier=_fb,
            correlation_id=correlation_id,
        )
        tier = _fb

    provider, model, max_tokens, temperature = _get_tier_config(tier)

    log.info(
        "llm_routed",
        tier=tier,
        provider=provider,
        model=model,
        complexity=complexity,
        has_tools=has_tools,
        correlation_id=correlation_id,
    )

    try:
        resp = await call_llm(
            messages=messages,
            provider=provider,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            correlation_id=correlation_id,
            **kwargs,
        )
        _record_tier_success(tier)
        return resp
    except Exception as exc:
        _record_tier_failure(tier)
        if tier == "fallback":
            raise

        fallback_tier: Tier = "primary" if tier == "fast" else "fallback"
        fb_provider, fb_model, fb_max_tokens, fb_temperature = _get_tier_config(fallback_tier)

        log.warning(
            "llm_tier_fallback",
            failed_tier=tier,
            fallback_tier=fallback_tier,
            error=str(exc),
            correlation_id=correlation_id,
        )

        try:
            resp = await call_llm(
                messages=messages,
                provider=fb_provider,
                model=fb_model,
                max_tokens=fb_max_tokens,
                temperature=fb_temperature,
                correlation_id=correlation_id,
                **kwargs,
            )
            _record_tier_success(fallback_tier)
            return resp
        except Exception:
            _record_tier_failure(fallback_tier)
            raise


async def route_stream(
    messages: list[dict[str, str]],
    complexity: str = "simple",
    correlation_id: str = "",
    **kwargs: Any,
) -> AsyncGenerator[str, None]:
    """Route a streaming completion to the appropriate tier."""
    tier = select_tier(complexity)
    provider, model, max_tokens, temperature = _get_tier_config(tier)

    log.info(
        "llm_stream_routed",
        tier=tier,
        model=model,
        complexity=complexity,
        correlation_id=correlation_id,
    )

    async for token in stream_llm(
        messages=messages,
        provider=provider,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        **kwargs,
    ):
        yield token
