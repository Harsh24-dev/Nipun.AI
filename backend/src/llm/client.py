"""
LiteLLM-based multi-provider LLM client.
Swap any model by changing .env — zero code changes.
"""

import time
from collections.abc import AsyncGenerator
from typing import Any

import litellm
import structlog
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.config import settings
from src.core.logging import trace_flow
from src.core.metering import current_step, record_llm
from src.core.metrics import LLM_DURATION, LLM_ERRORS, LLM_TOKENS

log = structlog.get_logger("llm.client")


def _flatten_messages(messages: list[dict[str, str]]) -> str:
    """Compact single-string rendering of a prompt for the chat trace."""
    return " || ".join(
        f"{m.get('role', '?')}: {m.get('content', '')}" for m in messages
    )

# Configure LiteLLM with all available API keys
litellm.anthropic_key = settings.ANTHROPIC_API_KEY or None
litellm.openai_key = settings.OPENAI_API_KEY or None
litellm.gemini_key = settings.GOOGLE_API_KEY or None
litellm.groq_key = settings.GROQ_API_KEY or None
litellm.cohere_key = settings.COHERE_API_KEY or None
litellm.drop_params = True   # silently drop unsupported params per provider
litellm.set_verbose = False


class LLMResponse:
    def __init__(self, content: str, model: str, provider: str, input_tokens: int, output_tokens: int):
        self.content = content
        self.model = model
        self.provider = provider
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


def _resolve_model_string(provider: str, model: str) -> str:
    """Build the model string LiteLLM expects for each provider."""
    # LiteLLM provider prefixes:
    # anthropic: no prefix needed (e.g. "claude-sonnet-4-6")
    # openai: no prefix needed (e.g. "gpt-4o")
    # google: "gemini/" prefix (e.g. "gemini/gemini-1.5-flash")
    # groq: "groq/" prefix
    # ollama: "ollama/" prefix
    # mistral: "mistral/" prefix
    prefix_map = {
        "google": "gemini/",
        "groq": "groq/",
        "ollama": "ollama/",
        "mistral": "mistral/",
        "cohere": "command-",  # special case handled below
    }
    if provider in ("anthropic", "openai"):
        return model
    if provider == "cohere":
        return f"cohere/{model}"
    prefix = prefix_map.get(provider, f"{provider}/")
    if model.startswith(prefix):
        return model
    return f"{prefix}{model}"


# Retry on transient provider errors. Resolve the exception classes via getattr so a name that is
# absent in the installed litellm version (e.g. APITimeoutError vs Timeout) doesn't crash EVERY
# LLM call at import/decoration time — which is exactly what broke the agent's decisions.
_RETRYABLE_LLM_ERRORS = tuple(
    e for e in (
        getattr(litellm, "APIConnectionError", None),
        getattr(litellm, "RateLimitError", None),
        getattr(litellm, "Timeout", None),
        getattr(litellm, "APITimeoutError", None),
        getattr(litellm, "ServiceUnavailableError", None),
    ) if isinstance(e, type)
) or (Exception,)


@retry(
    retry=retry_if_exception_type(_RETRYABLE_LLM_ERRORS),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    stop=stop_after_attempt(3),
    reraise=True,
)
async def call_llm(
    messages: list[dict[str, str]],
    provider: str,
    model: str,
    max_tokens: int = 2048,
    temperature: float = 0.3,
    correlation_id: str = "",
    **kwargs: Any,
) -> LLMResponse:
    model_str = _resolve_model_string(provider, model)
    start = time.perf_counter()

    log.info(
        "llm_call_start",
        model=model_str,
        provider=provider,
        message_count=len(messages),
        correlation_id=correlation_id,
    )
    # Flow trace: the ACTUAL prompt (system + history + user) sent to the model.
    # `step` = the pipeline node/agent this call belongs to (understand, grade_documents,
    # generate, verify_claims, …) so each request/response is attributable to its producer.
    trace_flow(
        "llm_request",
        correlation_id=correlation_id,
        node=current_step(),
        model=model_str,
        provider=provider,
        max_tokens=max_tokens,
        temperature=temperature,
        prompt=_flatten_messages(messages),
    )

    try:
        response = await litellm.acompletion(
            model=model_str,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=kwargs.pop("timeout", settings.LLM_REQUEST_TIMEOUT),
            **kwargs,
        )

        duration_ms = (time.perf_counter() - start) * 1000
        content = response.choices[0].message.content or ""
        input_tokens = response.usage.prompt_tokens if response.usage else 0
        output_tokens = response.usage.completion_tokens if response.usage else 0

        LLM_DURATION.labels(model=model, provider=provider).observe(duration_ms)
        LLM_TOKENS.labels(model=model, provider=provider, direction="input").inc(input_tokens)
        LLM_TOKENS.labels(model=model, provider=provider, direction="output").inc(output_tokens)

        # Per-request metering: attribute this call's tokens + latency to the active step.
        step = current_step()
        record_llm(
            model=model, provider=provider, duration_ms=duration_ms,
            input_tokens=input_tokens, output_tokens=output_tokens, step=step,
        )

        log.info(
            "llm_call_complete",
            model=model_str,
            provider=provider,
            step=step,
            duration_ms=round(duration_ms, 2),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            correlation_id=correlation_id,
        )
        # Flow trace: the ACTUAL text the model generated, tagged with its producing step.
        trace_flow(
            "llm_response",
            correlation_id=correlation_id,
            node=step,
            model=model_str,
            provider=provider,
            duration_ms=round(duration_ms, 2),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            response=content,
        )
        # Clean terminal heartbeat line.
        from src.core.flow_console import llm_call
        llm_call(step, model, input_tokens, output_tokens, duration_ms)

        return LLMResponse(
            content=content,
            model=model,
            provider=provider,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    except Exception as exc:
        duration_ms = (time.perf_counter() - start) * 1000
        error_type = type(exc).__name__
        LLM_ERRORS.labels(model=model, provider=provider, error_type=error_type).inc()
        log.error(
            "llm_call_failed",
            model=model_str,
            provider=provider,
            error=str(exc),
            error_type=error_type,
            duration_ms=round(duration_ms, 2),
            correlation_id=correlation_id,
        )
        from src.core.flow_console import llm_call
        llm_call(current_step(), model, 0, 0, duration_ms, failed=True, error=str(exc))
        raise


@retry(
    retry=retry_if_exception_type(_RETRYABLE_LLM_ERRORS),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    stop=stop_after_attempt(3),
    reraise=True,
)
async def _open_stream(model_str: str, messages, max_tokens, temperature, **kwargs):
    return await litellm.acompletion(
        model=model_str,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
        stream=True,
        timeout=kwargs.pop("timeout", settings.LLM_REQUEST_TIMEOUT),
        **kwargs,
    )


async def stream_llm(
    messages: list[dict[str, str]],
    provider: str,
    model: str,
    max_tokens: int = 2048,
    temperature: float = 0.3,
    **kwargs: Any,
) -> AsyncGenerator[str, None]:
    """Yield text tokens as they stream from the LLM."""
    model_str = _resolve_model_string(provider, model)

    # Opening the stream is retried on transient errors (mid-stream failures are not, to
    # avoid re-emitting already-yielded tokens).
    response = await _open_stream(model_str, messages, max_tokens, temperature, **kwargs)

    async for chunk in response:
        delta = chunk.choices[0].delta
        if delta and delta.content:
            yield delta.content
