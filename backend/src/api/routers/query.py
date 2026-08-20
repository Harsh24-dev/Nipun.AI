import asyncio
import time
import uuid
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from src.agents.orchestrator import process_query
from src.api.deps import get_current_user, rate_limit_check
from src.api.schemas import ErrorResponse, RateLimitErrorResponse
from src.core.logging import trace_flow
from src.core.metrics import WS_CONNECTIONS
from src.db.postgres import fetchval
from src.db.redis import incr_with_expiry
from src.config import settings

log = structlog.get_logger("api.query")
router = APIRouter()

# Fields added or finalized AFTER the draft answer is generated (by cite_claims / verify_claims /
# finalize): attribution, the calibrated reliability verdict, disclaimers, and the TTS text. These
# are streamed to the client as a `card_patch` so the already-delivered draft card upgrades in
# place — no full re-render, no flicker, and earlier streamed content is preserved.
_CARD_PATCH_FIELDS = (
    "summary", "sources", "citations", "citation_coverage", "reliability", "confidence",
    "low_confidence", "abstained", "disclaimer", "speech_text", "embeds", "resources",
    "mission", "plan",
)


async def _session_owner_ok(session_id: str, user_id: str) -> bool:
    """Session ownership guard. Returns True if the session belongs to the user OR does not
    exist yet (a fresh, not-yet-persisted id is created for this user on first turn); False
    only when the session already exists and is owned by a DIFFERENT user.

    Fails OPEN on a lookup error (e.g. malformed id / DB hiccup) — ownership enforcement must
    not turn a transient DB issue into a hard block; the row's user_id column keeps writes scoped.
    """
    try:
        owner = await fetchval("SELECT user_id FROM sessions WHERE id = $1::uuid", session_id)
    except Exception as exc:
        log.warning("session_owner_check_failed_fail_open", session_id=session_id, error=str(exc))
        return True
    return owner is None or str(owner) == str(user_id)


async def _llm_rate_exceeded(user_id: str, correlation_id: str) -> bool:
    """Per-user LLM rate gate shared by REST and WS. FAILS OPEN (returns False) when Redis is
    unavailable so a Redis outage cannot take the query path down."""
    try:
        count = await incr_with_expiry(f"rate:llm:{user_id}", ttl_seconds=60)
    except Exception as exc:
        log.warning(
            "llm_rate_limit_redis_error_fail_open",
            user_id=user_id,
            correlation_id=correlation_id,
            error=str(exc),
        )
        return False
    return count > settings.RATE_LIMIT_LLM_PER_MINUTE


def _stream_chunks(text: str, size: int = 3) -> list[str]:
    """Split a finished answer into small word-groups so the WebSocket can 'type out'
    the REAL final answer for a smooth reveal — instead of streaming a separate,
    throwaway preview that then gets replaced by a different card."""
    if not text:
        return []
    words = text.split(" ")
    chunks: list[str] = []
    buf: list[str] = []
    for w in words:
        buf.append(w)
        if len(buf) >= size:
            chunks.append(" ".join(buf) + " ")
            buf = []
    if buf:
        chunks.append(" ".join(buf))
    return chunks


class QueryRequest(BaseModel):
    query: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="User's question in any supported Indian language or English.",
        examples=["मुझे पीएम किसान योजना के बारे में बताएं", "What is the eligibility for PM Awas Yojana?"],
    )
    session_id: str | None = Field(
        None,
        description="UUID v4 for conversation continuity. A new session is created if omitted.",
        examples=["550e8400-e29b-41d4-a716-446655440000"],
    )
    document_id: str | None = Field(
        None,
        description=("Optional. When set, the answer is grounded ONLY in this uploaded document "
                     "(must belong to you — enforced by an owner filter at the vector layer)."),
    )
    clarifications: dict[str, Any] | None = Field(
        None,
        description=("Answers to a prior `clarify` form, as {field_name: value}. Used only for "
                     "this turn to personalize the answer — not stored. Resend the original "
                     "query together with these."),
        examples=[{"land_size": "5 acres", "soil_type": "Black", "location": "Nashik"}],
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "query": "मुझे पीएम किसान योजना के बारे में बताएं",
                    "session_id": "550e8400-e29b-41d4-a716-446655440000",
                }
            ]
        }
    }


class QueryResponse(BaseModel):
    correlation_id: str = Field(..., description="Unique ID for this request, echoed from `X-Correlation-ID` header or auto-generated.")
    response_card: dict[str, Any] = Field(..., description="Structured response card produced by the domain agent.")
    session_id: str = Field(..., description="Session UUID. Pass this back in subsequent requests to maintain conversation history.")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "correlation_id": "550e8400-e29b-41d4-a716-446655440000",
                    "session_id": "661f9511-f3ac-52e5-b827-557766551111",
                    "response_card": {
                        "domain": "scheme",
                        "answer": "पीएम किसान योजना के तहत किसानों को ₹6,000 प्रति वर्ष मिलते हैं।",
                        "sources": [],
                        "followups": ["क्या मैं इसके लिए आवेदन कर सकता हूँ?"],
                    },
                }
            ]
        }
    }


@router.post(
    "/query",
    response_model=QueryResponse,
    responses={
        200: {"description": "Query processed successfully"},
        401: {
            "description": "Missing or invalid Bearer token",
            "model": ErrorResponse,
        },
        429: {
            "description": "LLM rate limit exceeded (20 req / min / user)",
            "model": RateLimitErrorResponse,
        },
        422: {"description": "Request body validation error"},
    },
    summary="Submit a query",
    description=(
        "Submit a natural-language query and receive a structured **response card** from the appropriate "
        "domain agent (farming, finance, legal, scheme, student, or general).\n\n"
        "The response is always written in the language of your query (the orchestrator "
        "detects it automatically; you can also ask in-line, e.g. 'answer in Tamil'). "
        "The resolved language is returned on `response_card.language`, and a plain-text "
        "`response_card.speech_text` is provided for voice/TTS read-out.\n\n"
        "Pass `session_id` to maintain multi-turn conversation context.\n\n"
        "**Rate limit:** 20 LLM requests per minute per user. "
        "Use the WebSocket endpoint `/ws/{session_id}` for streaming token responses."
    ),
)
async def handle_query(
    request: QueryRequest,
    user: dict = Depends(get_current_user),
    _: None = Depends(rate_limit_check),
    x_correlation_id: Annotated[str | None, Header()] = None,
) -> QueryResponse:
    correlation_id = x_correlation_id or str(uuid.uuid4())
    session_id = request.session_id or str(uuid.uuid4())
    user_id = user["user_id"]

    # Session ownership: a caller-supplied session_id must not belong to another user.
    if request.session_id and not await _session_owner_ok(request.session_id, user_id):
        log.warning("session_ownership_violation", user_id=user_id, session_id=request.session_id, channel="rest")
        raise HTTPException(
            status_code=403,
            detail={"code": "SESSION_FORBIDDEN", "message": "This session does not belong to you."},
        )

    if await _llm_rate_exceeded(user_id, correlation_id):
        raise HTTPException(
            status_code=429,
            detail={
                "code": "LLM_RATE_LIMITED",
                "message": "बहुत अनुरोध आए। 1 मिनट बाद प्रयास करें।",
                "message_en": "Too many requests. Please wait 1 minute.",
                "correlation_id": correlation_id,
            },
        )

    log.info(
        "query_received",
        user_id=user_id,
        session_id=session_id,
        query_length=len(request.query),
        correlation_id=correlation_id,
    )
    # Flow trace: the ACTUAL query text that entered the pipeline (request start).
    trace_flow(
        "http_query_received",
        correlation_id=correlation_id,
        channel="rest",
        user_id=user_id,
        session_id=session_id,
        query=request.query,
    )

    # BACKPRESSURE: take a global in-flight slot (Redis-backed, shared across workers/replicas). At
    # capacity we shed load with a 503 "busy" instead of piling every request onto a saturated event
    # loop / provider quota. Fail-open when Redis is down (acquire returns granted=True, token=None).
    from src.core.concurrency import acquire_slot, release_slot

    granted, slot = await acquire_slot(time.time())
    if not granted:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "BUSY",
                "message": "अभी बहुत लोड है। कृपया कुछ ही क्षण बाद पुनः प्रयास करें।",
                "message_en": "We're at capacity right now. Please retry in a few seconds.",
                "correlation_id": correlation_id,
            },
        )
    try:
        # HARD TIMEOUT so a single stuck dependency can't hold a connection open indefinitely.
        response_card = await asyncio.wait_for(
            process_query(
                query=request.query,
                session_id=session_id,
                user_id=user_id,
                correlation_id=correlation_id,
                document_id=request.document_id,
                clarifications=request.clarifications,
            ),
            timeout=settings.REQUEST_HARD_TIMEOUT,
        )
    except asyncio.TimeoutError:
        log.warning("query_hard_timeout", user_id=user_id, session_id=session_id,
                    timeout_s=settings.REQUEST_HARD_TIMEOUT, correlation_id=correlation_id)
        raise HTTPException(
            status_code=504,
            detail={
                "code": "TIMEOUT",
                "message": "इसमें अपेक्षा से अधिक समय लग रहा है। कृपया पुनः प्रयास करें।",
                "message_en": "This is taking longer than expected. Please try again.",
                "correlation_id": correlation_id,
            },
        )
    finally:
        await release_slot(slot)

    # Flow trace: the ACTUAL response card returned to the client (request end).
    trace_flow(
        "http_query_response",
        correlation_id=correlation_id,
        channel="rest",
        session_id=session_id,
        response_card=response_card,
    )

    return QueryResponse(
        correlation_id=correlation_id,
        response_card=response_card,
        session_id=session_id,
    )


@router.websocket("/ws/{session_id}")
async def websocket_stream(
    websocket: WebSocket,
    session_id: str,
):
    """
    **WebSocket** — streaming token responses.

    ### Connection flow
    1. Connect to `ws://<host>/ws/{session_id}`
    2. Send auth message: `{"token": "<jwt>"}`
    3. Send query messages: `{"query": "your question"}`
    4. Receive a stream of typed events:

    | Event type | Payload | Description |
    |------------|---------|-------------|
    | `thinking` | `{correlation_id}` | Agent started processing |
    | `token` | `{content: str}` | Incremental token from LLM |
    | `card` | `{data: ResponseCard}` | Final structured response |
    | `done` | `{correlation_id}` | Stream complete |
    | `error` | `{code?, message}` | Error during processing |
    """
    await websocket.accept()
    WS_CONNECTIONS.inc()

    try:
        auth_msg = await websocket.receive_json()
        token = auth_msg.get("token", "")

        from src.api.deps import validate_token
        try:
            user = validate_token(token)
        except Exception:
            await websocket.send_json({"type": "error", "code": "UNAUTHORIZED"})
            await websocket.close(code=1008)
            return

        user_id = user["user_id"]

        # Session ownership: the path session_id must not belong to another user.
        if not await _session_owner_ok(session_id, user_id):
            log.warning("session_ownership_violation", user_id=user_id, session_id=session_id, channel="websocket")
            await websocket.send_json({"type": "error", "code": "SESSION_FORBIDDEN"})
            await websocket.close(code=1008)   # policy violation
            return

        while True:
            data = await websocket.receive_json()
            query = data.get("query", "").strip()
            if not query:
                continue

            correlation_id = str(uuid.uuid4())

            # Same per-user LLM rate limit as REST, applied per received message
            # (fails open on Redis error). Reuses the shared rate:llm:<user_id> key.
            if await _llm_rate_exceeded(user_id, correlation_id):
                await websocket.send_json({
                    "type": "error",
                    "code": "LLM_RATE_LIMITED",
                    "message": "Too many requests. Please wait 1 minute.",
                    "correlation_id": correlation_id,
                })
                continue

            trace_flow(
                "ws_query_received",
                correlation_id=correlation_id,
                channel="websocket",
                user_id=user_id,
                session_id=session_id,
                query=query,
            )

            await websocket.send_json({"type": "thinking", "correlation_id": correlation_id})

            # STREAM THE REAL ANSWER EARLY: deliver the draft card the moment generation produces
            # it (typed out for a smooth reveal), THEN let the citation + verification steps finish
            # and patch the SAME card in place with finalized sources + reliability — no re-render,
            # no flicker, earlier content preserved. This cuts perceived latency by the whole
            # cite+verify tail. Hard-abstain mode must wait for the final verdict before showing
            # anything, so it falls back to deliver-once.
            streamed = {"done": False}

            async def _deliver_early(draft: dict) -> None:
                text = draft.get("summary") or draft.get("speech_text") or draft.get("title") or ""
                for chunk in _stream_chunks(text):
                    await websocket.send_json({"type": "token", "content": chunk})
                    await asyncio.sleep(0.01)   # smooth reveal; negligible added latency
                await websocket.send_json({"type": "card", "data": draft})
                streamed["done"] = True

            stream_ok = not settings.ABSTAIN_ON_LOW_CONFIDENCE
            response_card = await process_query(
                query=query,
                session_id=session_id,
                user_id=user_id,
                correlation_id=correlation_id,
                on_early_card=_deliver_early if stream_ok else None,
            )

            trace_flow(
                "ws_query_response",
                correlation_id=correlation_id,
                channel="websocket",
                session_id=session_id,
                response_card=response_card,
            )

            if stream_ok and streamed["done"]:
                # Upgrade the already-streamed draft with finalized attribution + reliability.
                patch = {k: response_card[k] for k in _CARD_PATCH_FIELDS
                         if isinstance(response_card, dict) and k in response_card}
                await websocket.send_json({"type": "card_patch", "data": patch})
            else:
                # No early delivery (hard-abstain mode, or an early card never materialised) —
                # deliver the final card once, typed out.
                answer_text = (response_card.get("summary") or response_card.get("speech_text") or "")
                for chunk in _stream_chunks(answer_text):
                    await websocket.send_json({"type": "token", "content": chunk})
                    await asyncio.sleep(0.01)
                await websocket.send_json({"type": "card", "data": response_card})

            await websocket.send_json({"type": "done", "correlation_id": correlation_id})

    except WebSocketDisconnect:
        log.info("websocket_disconnected", session_id=session_id)
    except Exception as exc:
        log.error("websocket_error", error=str(exc), session_id=session_id)
        try:
            await websocket.send_json({"type": "error", "message": str(exc)})
        except Exception:
            pass
    finally:
        WS_CONNECTIONS.dec()
