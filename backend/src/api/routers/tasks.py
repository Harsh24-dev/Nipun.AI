"""
Task + tool + execution API.

- GET  /tools           list MCP tools
- GET  /tasks           list read-only task assistants
- POST /tasks/preview   run a read-only assistant → preview card (no action taken)
- POST /tasks/prepare   PREPARE an action → confirmation token + preview
- POST /tasks/confirm   CONFIRM (execute) a prepared action
- POST /tasks/reject    reject a prepared action

Nothing is executed without an explicit /confirm call, and even then only if
EXECUTION_ENABLED and a handler is registered.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.api.deps import get_current_user
from src.execution.circuit_breaker import CircuitOpenError
from src.execution.executor import execute, prepare, reject
from src.execution.guards import CredentialError
from src.mcp import get_tool, list_tools
from src.tasks import get_assistant, list_assistants

log = structlog.get_logger("api.tasks")
router = APIRouter()


class PreviewRequest(BaseModel):
    task: str = Field(..., description="Task assistant name, e.g. find_deals, build_itinerary.")
    params: dict = Field(default_factory=dict)


class PrepareRequest(BaseModel):
    action: str = Field(..., description="Action to prepare (never executes on prepare).")
    params: dict = Field(default_factory=dict)
    session_id: str = Field(..., description="Session id (for the circuit breaker).")


class ConfirmRequest(BaseModel):
    token: str = Field(..., description="Token returned by /tasks/prepare.")


class ToolCallRequest(BaseModel):
    tool: str = Field(..., description="Tool name, e.g. web_search, finance, weather, scholar, books.")
    params: dict = Field(default_factory=dict, description="Tool parameters, e.g. {\"query\": \"...\"}.")


@router.get("/tools", summary="List MCP tools")
async def get_tools(user: dict = Depends(get_current_user)) -> dict:
    return {"tools": list_tools()}


@router.get("/agents", summary="List the agent capability catalogue the orchestrator uses")
async def get_agents(user: dict = Depends(get_current_user)) -> dict:
    """Every independent agent the Mission Controller can enlist — domain experts, planners,
    retrievers, verifiers, task assistants, the gated executor, etc. New integrations
    (payment gateway, shopping portal) appear here automatically once registered."""
    from src.agents.capabilities import manifest

    return {"agents": manifest()}


class IngestBooksRequest(BaseModel):
    topic: str = Field(..., description="Subject/career, e.g. 'books to become a doctor'.")
    domain: str | None = Field(None, description="Qdrant domain collection (default: student).")
    language: str = Field("en", description="Language code for the collection.")
    max_books: int | None = Field(None, description="Max open books to ingest.")
    run_now: bool = Field(False, description="Run inline instead of enqueuing to Celery.")


@router.post("/tools/ingest-books", summary="Download open books → local embeddings → Qdrant")
async def ingest_books(request: IngestBooksRequest, user: dict = Depends(get_current_user)) -> dict:
    """Discover openly-downloadable full-text books for a topic, embed them locally
    (BGE-M3) and index into Qdrant so answers come from the actual book content.
    Enqueues a background Celery job by default; set run_now to ingest inline."""
    if request.run_now:
        from src.ingestion.books import ingest_books_for_topic
        summary = await ingest_books_for_topic(
            request.topic, domain=request.domain, language=request.language, max_books=request.max_books)
        return {"mode": "inline", "summary": summary}
    try:
        from src.ingestion.tasks import ingest_books_topic
        async_result = ingest_books_topic.delay(
            request.topic, request.domain, request.language, request.max_books)
        return {"mode": "queued", "task_id": async_result.id, "topic": request.topic}
    except Exception as exc:  # broker unavailable → tell the caller to use run_now
        raise HTTPException(status_code=503,
                            detail=f"Task queue unavailable ({exc}); retry with run_now=true.") from exc


@router.post("/tools/call", summary="Call a read-only MCP tool (live data)")
async def call_tool(request: ToolCallRequest, user: dict = Depends(get_current_user)) -> dict:
    """Invoke a read-only tool directly (web_search, finance, weather, mandi_prices,
    news, scholar, books, ...). Write/action tools must go through PREPARE→CONFIRM."""
    tool = get_tool(request.tool)
    if tool is None:
        raise HTTPException(status_code=404, detail=f"Unknown tool '{request.tool}'")
    if not tool.read_only:
        raise HTTPException(status_code=400,
                            detail=f"'{request.tool}' is not read-only; use /tasks/prepare then /tasks/confirm.")
    result = await tool.call(request.params)
    return {"tool": result.tool, "status": result.status, "text": result.text,
            "data": result.data, "suspected_instructions": result.suspected_instructions}


@router.get("/tasks", summary="List read-only task assistants")
async def get_tasks(user: dict = Depends(get_current_user)) -> dict:
    return {"tasks": list_assistants()}


@router.post("/tasks/preview", summary="Preview a read-only task (no action taken)")
async def preview_task(request: PreviewRequest, user: dict = Depends(get_current_user)) -> dict:
    assistant = get_assistant(request.task)
    if assistant is None:
        raise HTTPException(status_code=404, detail=f"Unknown task '{request.task}'")
    try:
        card = assistant.run(request.params)
    except CredentialError as exc:
        raise HTTPException(status_code=400, detail=f"Credentials are never accepted: {exc}") from exc
    return {"card": card}


@router.post("/tasks/prepare", summary="PREPARE an action (returns a confirmation token)")
async def prepare_action(request: PrepareRequest, user: dict = Depends(get_current_user)) -> dict:
    try:
        prepared = await prepare(
            action=request.action, params=request.params,
            user_id=user["user_id"], session_id=request.session_id,
            correlation_id="",
        )
    except CredentialError as exc:
        raise HTTPException(status_code=400, detail=f"Credentials are never accepted: {exc}") from exc
    except CircuitOpenError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    return {"token": prepared.token, "preview": prepared.preview, "expires_at": prepared.expires_at}


@router.post("/tasks/confirm", summary="CONFIRM (execute) a prepared action")
async def confirm_action(request: ConfirmRequest, user: dict = Depends(get_current_user)) -> dict:
    try:
        result = await execute(token=request.token, user_id=user["user_id"], correlation_id="")
    except CircuitOpenError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    return {"status": result.status, "message": result.message, "result": result.result}


@router.post("/tasks/reject", summary="Reject a prepared action")
async def reject_action(request: ConfirmRequest, user: dict = Depends(get_current_user)) -> dict:
    await reject(request.token)
    return {"status": "rejected"}
