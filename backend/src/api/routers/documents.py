"""
User document API — upload a file, then query against it.

RBAC: every endpoint is scoped to the authenticated owner. A user can only list, read,
query, or delete their OWN documents (enforced in Postgres by owner_id AND at the vector
layer by the owner_id filter on retrieval). Admin/backend corpus is separate and shared.
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from src.api.deps import get_current_user, require_admin
from src.api.rbac import assert_owner
from src.config import settings
from src.core.logging import trace_flow
from src.db.postgres import execute, fetch, fetchrow, fetchval
from src.ingestion.metadata import citation_for  # noqa: F401  (re-exported for callers)
from src.ingestion.user_docs import ALLOWED_MIME, delete_user_document, ingest_user_document

log = structlog.get_logger("api.documents")
router = APIRouter()


async def _load_owned_doc(document_id: str, user: dict) -> dict:
    """Fetch a document row and assert the caller owns it (404 otherwise)."""
    row = await fetchrow(
        "SELECT * FROM user_documents WHERE id = $1::uuid", document_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Document not found.")
    assert_owner(row["owner_id"], user, resource="document")
    return dict(row)


@router.post("/documents", summary="Upload a document to query against", tags=["documents"])
async def upload_document(
    file: UploadFile = File(...),
    title: str | None = Form(None),
    language: str | None = Form(None),
    domain: str | None = Form(None),
    session_id: str | None = Form(
        None, description="Scope the doc to this chat session (deleted with the session). "
                          "Omit for an account-wide document."),
    user: dict = Depends(get_current_user),
) -> dict:
    owner_id = user["user_id"]

    if file.content_type not in ALLOWED_MIME:
        raise HTTPException(status_code=415,
                            detail=f"Unsupported type '{file.content_type}'. Allowed: {sorted(ALLOWED_MIME)}")

    # If a session is given, it must belong to the caller (RBAC).
    if session_id:
        owns = await fetchval(
            "SELECT 1 FROM sessions WHERE id=$1::uuid AND user_id=$2::uuid", session_id, owner_id)
        if not owns:
            raise HTTPException(status_code=404, detail="Session not found.")

    content = await file.read()
    size = len(content)
    if size == 0:
        raise HTTPException(status_code=400, detail="Empty file.")
    if size > settings.UPLOAD_MAX_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File exceeds {settings.UPLOAD_MAX_MB} MB.")

    # Per-user quota (RBAC/abuse guard).
    count = await fetchval("SELECT COUNT(*) FROM user_documents WHERE owner_id = $1::uuid", owner_id)
    if count and count >= settings.USER_DOC_QUOTA:
        raise HTTPException(status_code=409, detail=f"Document quota reached ({settings.USER_DOC_QUOTA}).")

    document_id = str(uuid.uuid4())
    doc_title = title or file.filename or "Uploaded document"
    await execute(
        """
        INSERT INTO user_documents (id, owner_id, session_id, title, filename, mime_type,
                                    language, domain, status, size_bytes)
        VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6, $7, $8, 'processing', $9)
        """,
        document_id, owner_id, session_id, doc_title, file.filename, file.content_type,
        (language or "en"), domain, size,
    )
    trace_flow("document_upload", correlation_id=document_id, owner_id=owner_id,
               session_id=session_id, filename=file.filename, mime=file.content_type, size_bytes=size)

    try:
        result = await ingest_user_document(
            owner_id=owner_id, document_id=document_id, filename=file.filename or doc_title,
            content=content, mime_type=file.content_type, title=doc_title,
            language=language, domain=domain, session_id=session_id or "",
            correlation_id=document_id,
        )
    except Exception as exc:
        log.exception("user_doc_ingest_failed", document_id=document_id, error=str(exc))
        await execute("UPDATE user_documents SET status='failed', error=$2, updated_at=NOW() WHERE id=$1::uuid",
                      document_id, str(exc)[:500])
        raise HTTPException(status_code=500, detail="Failed to process the document.") from exc

    if result["status"] != "ready":
        await execute("UPDATE user_documents SET status='failed', error=$2, updated_at=NOW() WHERE id=$1::uuid",
                      document_id, result.get("reason", "unknown"))
        raise HTTPException(status_code=422, detail=f"Could not index document: {result.get('reason')}")

    await execute(
        """UPDATE user_documents SET status='ready', chunk_count=$2, domain=$3, subject=$4,
           level=$5, language=$6, source_hash=$7, updated_at=NOW() WHERE id=$1::uuid""",
        document_id, result["chunk_count"], result["domain"], result["subject"],
        result["level"], result["language"], result["source_hash"],
    )
    log.info("document_uploaded", document_id=document_id, owner_id=owner_id, chunks=result["chunk_count"])
    return {
        "document_id": document_id, "title": doc_title, "status": "ready",
        "chunk_count": result["chunk_count"], "domain": result["domain"],
        "subject": result["subject"], "level": result["level"], "language": result["language"],
    }


@router.post(
    "/admin/documents",
    summary="[Admin] Upload a document into the shared corpus (all users)",
    description=("Admin-only. The uploaded file is embedded locally and indexed into the "
                 "**shared public corpus** so it grounds answers for **every** user's queries "
                 "(unlike `/documents`, which is private to the uploader). Domain / subject / "
                 "level are auto-classified when omitted."),
    tags=["admin"],
)
async def admin_upload_document(
    file: UploadFile = File(..., description="pdf / txt / md / html / docx"),
    title: str | None = Form(None),
    domain: str | None = Form(None, description="Corpus domain, e.g. legal, health, scheme. Auto-classified if omitted."),
    language: str | None = Form(None, description="ISO code; auto-detected if omitted."),
    author: str | None = Form(None),
    subject: str | None = Form(None),
    level: str | None = Form(None, description="beginner|intermediate|advanced|academic"),
    admin: dict = Depends(require_admin),
) -> dict:
    if file.content_type not in ALLOWED_MIME:
        raise HTTPException(status_code=415,
                            detail=f"Unsupported type '{file.content_type}'. Allowed: {sorted(ALLOWED_MIME)}")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file.")
    if len(content) > settings.UPLOAD_MAX_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File exceeds {settings.UPLOAD_MAX_MB} MB.")

    from src.ingestion.admin_docs import ingest_admin_document

    correlation_id = str(uuid.uuid4())
    try:
        result = await ingest_admin_document(
            filename=file.filename or (title or "corpus-doc"), content=content,
            mime_type=file.content_type, title=title or (file.filename or "Corpus document"),
            domain=domain, language=language, author=author or "", subject=subject or "",
            level=level or "", correlation_id=correlation_id,
        )
    except Exception as exc:
        log.exception("admin_doc_ingest_failed", error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to ingest the document.") from exc

    if result.get("status") not in ("success", "skipped"):
        raise HTTPException(status_code=422, detail=f"Could not index: {result.get('reason')}")
    log.info("admin_document_ingested", admin_id=admin["user_id"], domain=result.get("domain"),
             chunks=result.get("chunks", 0), correlation_id=correlation_id)
    return {"status": result.get("status"), "visibility": "public", "domain": result.get("domain"),
            "language": result.get("language"), "subject": result.get("subject"),
            "level": result.get("level"), "chunks": result.get("chunks", 0),
            "correlation_id": correlation_id}


@router.get("/documents", summary="List my uploaded documents", tags=["documents"])
async def list_documents(user: dict = Depends(get_current_user)) -> dict:
    rows = await fetch(
        """SELECT id, title, filename, status, domain, subject, level, language,
                  chunk_count, size_bytes, created_at
           FROM user_documents WHERE owner_id = $1::uuid ORDER BY created_at DESC""",
        user["user_id"],
    )
    return {"documents": [
        {"document_id": str(r["id"]), "title": r["title"], "filename": r["filename"],
         "status": r["status"], "domain": r["domain"], "subject": r["subject"],
         "level": r["level"], "language": r["language"], "chunk_count": r["chunk_count"],
         "size_bytes": r["size_bytes"], "created_at": r["created_at"].isoformat()}
        for r in rows
    ]}


@router.get("/documents/{document_id}", summary="Get document metadata", tags=["documents"])
async def get_document(document_id: str, user: dict = Depends(get_current_user)) -> dict:
    row = await _load_owned_doc(document_id, user)
    return {"document_id": str(row["id"]), "title": row["title"], "status": row["status"],
            "domain": row["domain"], "subject": row["subject"], "level": row["level"],
            "language": row["language"], "chunk_count": row["chunk_count"]}


@router.delete("/documents/{document_id}", status_code=204, summary="Delete a document", tags=["documents"])
async def delete_document(document_id: str, user: dict = Depends(get_current_user)) -> None:
    row = await _load_owned_doc(document_id, user)
    try:
        await delete_user_document(str(row["owner_id"]), document_id, row["language"] or "en")
    except Exception as exc:
        log.warning("user_doc_vector_delete_failed", document_id=document_id, error=str(exc))
    await execute("DELETE FROM user_documents WHERE id = $1::uuid", document_id)
    log.info("document_deleted", document_id=document_id, owner_id=user["user_id"])


class DocQueryRequest(BaseModel):
    query: str
    session_id: str | None = None


@router.post("/documents/{document_id}/query", summary="Ask a question about this document only", tags=["documents"])
async def query_document(document_id: str, request: DocQueryRequest,
                         user: dict = Depends(get_current_user)) -> dict:
    """Answer strictly from THIS uploaded document (RBAC-checked). Cross-lingual: the
    doc can be in a different language than the question."""
    row = await _load_owned_doc(document_id, user)
    if row["status"] != "ready":
        raise HTTPException(status_code=409, detail=f"Document is '{row['status']}', not ready.")

    from src.agents.orchestrator import process_query

    correlation_id = str(uuid.uuid4())
    session_id = request.session_id or str(uuid.uuid4())
    card = await process_query(
        query=request.query, session_id=session_id, user_id=user["user_id"],
        correlation_id=correlation_id, document_id=document_id,
    )
    return {"correlation_id": correlation_id, "session_id": session_id,
            "document_id": document_id, "response_card": card}
