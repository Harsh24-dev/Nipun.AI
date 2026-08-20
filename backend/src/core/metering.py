"""
Per-request token + latency metering.

Every user query fans out into many LLM calls across many pipeline steps
(prescreen → classify → grade → generate → verify → …). This module accumulates,
for the lifetime of ONE request, the tokens and latency of each call and attributes
it to the step it happened in, so we can report:

  * per-step latency + token consumption
  * total latency (wall-clock) + total token consumption for the whole response

It is contextvar-based, so concurrent requests never mix: each request gets its own
`RequestMeter` bound to the async context, and every `call_llm` records into whichever
meter (and step) is active in its context. Recording is best-effort and never raises —
metering must never break the request path.
"""

from __future__ import annotations

import contextvars
import time
from dataclasses import dataclass, field

from src.core.logging import get_logger

log = get_logger("core.metering")

# ── Records ───────────────────────────────────────────────────────────────────


@dataclass
class LLMCallRecord:
    step: str
    model: str
    provider: str
    duration_ms: float
    input_tokens: int
    output_tokens: int


@dataclass
class StepTiming:
    step: str
    duration_ms: float


@dataclass
class RequestMeter:
    correlation_id: str = ""
    wall_start: float = field(default_factory=time.perf_counter)
    llm_calls: list[LLMCallRecord] = field(default_factory=list)
    step_timings: list[StepTiming] = field(default_factory=list)

    def record_llm(
        self, step: str, model: str, provider: str,
        duration_ms: float, input_tokens: int, output_tokens: int,
    ) -> None:
        self.llm_calls.append(LLMCallRecord(
            step=step, model=model, provider=provider, duration_ms=duration_ms,
            input_tokens=input_tokens, output_tokens=output_tokens,
        ))

    def record_step(self, step: str, duration_ms: float) -> None:
        self.step_timings.append(StepTiming(step=step, duration_ms=duration_ms))

    def wall_ms(self) -> float:
        return (time.perf_counter() - self.wall_start) * 1000

    def summary(self) -> dict:
        """Aggregate totals + a per-step breakdown, ready to log or return in a card."""
        by_step: dict[str, dict] = {}
        for c in self.llm_calls:
            s = by_step.setdefault(c.step, {
                "step": c.step, "llm_calls": 0, "llm_latency_ms": 0.0,
                "input_tokens": 0, "output_tokens": 0, "tokens": 0, "wall_ms": 0.0,
            })
            s["llm_calls"] += 1
            s["llm_latency_ms"] += c.duration_ms
            s["input_tokens"] += c.input_tokens
            s["output_tokens"] += c.output_tokens
            s["tokens"] += c.input_tokens + c.output_tokens
        for t in self.step_timings:
            s = by_step.setdefault(t.step, {
                "step": t.step, "llm_calls": 0, "llm_latency_ms": 0.0,
                "input_tokens": 0, "output_tokens": 0, "tokens": 0, "wall_ms": 0.0,
            })
            # A step may run multiple times (RAG loops) — sum its wall time.
            s["wall_ms"] += t.duration_ms

        for s in by_step.values():
            s["llm_latency_ms"] = round(s["llm_latency_ms"], 2)
            s["wall_ms"] = round(s["wall_ms"], 2)

        total_in = sum(c.input_tokens for c in self.llm_calls)
        total_out = sum(c.output_tokens for c in self.llm_calls)
        total_llm_ms = sum(c.duration_ms for c in self.llm_calls)
        result = {
            "correlation_id": self.correlation_id,
            "total_latency_ms": round(self.wall_ms(), 2),
            "total_llm_latency_ms": round(total_llm_ms, 2),
            "total_llm_calls": len(self.llm_calls),
            "total_input_tokens": total_in,
            "total_output_tokens": total_out,
            "total_tokens": total_in + total_out,
            "by_step": sorted(by_step.values(), key=lambda s: s["wall_ms"], reverse=True),
        }
        log.info(
            "request_metered",
            correlation_id=self.correlation_id,
            total_latency_ms=result["total_latency_ms"],
            total_llm_latency_ms=result["total_llm_latency_ms"],
            total_llm_calls=result["total_llm_calls"],
            total_tokens=result["total_tokens"],
            steps=len(by_step),
        )
        return result


# ── Context binding ───────────────────────────────────────────────────────────

_meter_var: contextvars.ContextVar[RequestMeter | None] = contextvars.ContextVar(
    "nipun_request_meter", default=None
)
_step_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "nipun_current_step", default="request"
)


def begin_request(correlation_id: str = "") -> RequestMeter:
    """Start a fresh meter for the current request context and return it."""
    meter = RequestMeter(correlation_id=correlation_id)
    _meter_var.set(meter)
    _step_var.set("request")
    log.info("request_meter_started", correlation_id=correlation_id)
    return meter


def get_meter() -> RequestMeter | None:
    return _meter_var.get()


def current_step() -> str:
    return _step_var.get()


def set_step(name: str) -> contextvars.Token:
    """Mark the current pipeline step; returns a token to restore the previous one."""
    log.debug("step_set", step=name)
    return _step_var.set(name)


def reset_step(token: contextvars.Token) -> None:
    try:
        _step_var.reset(token)
    except Exception as exc:  # pragma: no cover - best-effort
        log.debug("reset_step_failed", error=str(exc), error_type=type(exc).__name__)


def record_llm(
    model: str, provider: str, duration_ms: float,
    input_tokens: int, output_tokens: int, step: str | None = None,
) -> None:
    """Attribute one LLM call's tokens+latency to the active request + step."""
    meter = _meter_var.get()
    if meter is None:
        log.debug("record_llm_no_meter", model=model, provider=provider)
        return
    try:
        active_step = step or _step_var.get()
        meter.record_llm(
            step=active_step, model=model, provider=provider,
            duration_ms=duration_ms, input_tokens=input_tokens, output_tokens=output_tokens,
        )
        log.debug("llm_call_recorded", step=active_step, model=model, provider=provider,
                  duration_ms=round(duration_ms, 2), input_tokens=input_tokens,
                  output_tokens=output_tokens, correlation_id=meter.correlation_id)
    except Exception as exc:  # pragma: no cover - best-effort
        log.warning("record_llm_failed", error=str(exc), error_type=type(exc).__name__)


def record_step(step: str, duration_ms: float) -> None:
    meter = _meter_var.get()
    if meter is None:
        log.debug("record_step_no_meter", step=step)
        return
    try:
        meter.record_step(step, duration_ms)
        log.debug("step_recorded", step=step, duration_ms=round(duration_ms, 2),
                  correlation_id=meter.correlation_id)
    except Exception as exc:  # pragma: no cover - best-effort
        log.warning("record_step_failed", error=str(exc), error_type=type(exc).__name__)


def step_token_snapshot() -> tuple[int, int, int, float]:
    """(input_tokens, output_tokens, llm_calls, llm_ms) accumulated so far — used to
    compute a single node's delta by diffing an enter/exit snapshot."""
    meter = _meter_var.get()
    if meter is None:
        return (0, 0, 0, 0.0)
    return (
        sum(c.input_tokens for c in meter.llm_calls),
        sum(c.output_tokens for c in meter.llm_calls),
        len(meter.llm_calls),
        sum(c.duration_ms for c in meter.llm_calls),
    )
