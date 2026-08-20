"""
User document ingestion — parse an uploaded file, embed it LOCALLY (BGE-M3), and index
it into the caller's private `user_documents` collection (one shared collection; the
owner_id payload filter provides isolation, language is a payload field).

Isolation (RBAC): every chunk is tagged owner_id=<uploader> and document_id=<doc>, and
retrieval always filters by owner_id — so an uploaded file is only ever visible to the
user who uploaded it. Rich metadata (title/author/subject/level/section/page) is attached
for good citations and precise per-document routing.
"""

from __future__ import annotations

import os
import tempfile
import uuid

import structlog
from qdrant_client.models import PointStruct, SparseVector

from src.core.logging import trace_flow
from src.db.qdrant import delete_by_filter, upsert_points, user_collection_name
from src.ingestion.chunker import chunk_text
from src.ingestion.metadata import DocumentMetadata, VISIBILITY_PRIVATE, build_chunk_payload, classify_document
from src.ingestion.parser import _hash_content, parse_html, parse_pdf, parse_text
from src.language.detector import detect_language
from src.llm.embeddings import embed_texts_async

log = structlog.get_logger("ingestion.user_docs")

# Accepted upload types → parser hint.
ALLOWED_MIME = {
    "application/pdf": "pdf",
    "text/plain": "text",
    "text/markdown": "text",
    "text/html": "html",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
}


def _parse_bytes(content: bytes, kind: str, filename: str, domain: str, language: str) -> str:
    """Extract clean text from uploaded bytes. Returns the document text."""
    if kind == "pdf":
        fd, path = tempfile.mkstemp(suffix=".pdf")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(content)
            return parse_pdf(path, domain, language, source_url=filename).text
        finally:
            if os.path.exists(path):
                os.unlink(path)
    if kind == "html":
        return parse_html(content.decode("utf-8", errors="ignore"), domain, language, source_url=filename).text
    if kind == "docx":
        return _parse_docx(content)
    return parse_text(content.decode("utf-8", errors="ignore"), filename, domain, language).text


def _parse_docx(content: bytes) -> str:
    try:
        import io
        from docx import Document  # python-docx

        doc = Document(io.BytesIO(content))
        return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except Exception as exc:
        log.warning("docx_parse_failed", error=str(exc))
        return ""


async def ingest_user_document(
    *,
    owner_id: str,
    document_id: str,
    filename: str,
    content: bytes,
    mime_type: str,
    title: str = "",
    language: str | None = None,
    domain: str | None = None,
    author: str = "",
    session_id: str = "",
    correlation_id: str = "",
) -> dict:
    """Parse → classify → chunk → local-embed → index one uploaded document. Returns a
    status dict {status, chunk_count, domain, subject, level, language, source_hash}."""
    kind = ALLOWED_MIME.get(mime_type, "text")
    title = title or filename or "Uploaded document"
    lang0 = (language or "").split("+")[0]

    text = _parse_bytes(content, kind, filename, domain or "documents", lang0 or "en")
    if not text.strip():
        return {"status": "failed", "reason": "no_text_extracted", "chunk_count": 0}

    lang = lang0 or detect_language(text[:500]).split("+")[0] or "en"
    source_hash = _hash_content(text)

    # Auto-derive domain / subject / level when not provided (better routing + citations).
    cls = await classify_document(text, correlation_id)
    dom = domain or cls["domain"]
    subject, level = cls["subject"], cls["level"]

    chunks = chunk_text(text)
    if not chunks:
        return {"status": "failed", "reason": "no_chunks", "chunk_count": 0}

    meta = DocumentMetadata(
        title=title, domain=dom, language=lang, source=title, source_url=filename,
        author=author, subject=subject, level=level, book_id=document_id,
        document_id=document_id, session_id=session_id or "", owner_id=owner_id,
        visibility=VISIBILITY_PRIVATE, kind="user_upload",
    )

    # Local BGE-M3 embeddings (dense + sparse).
    embed_result = await embed_texts_async([c.text for c in chunks])
    points: list[PointStruct] = []
    for i, chunk in enumerate(chunks):
        sparse = embed_result.sparse[i] if embed_result.sparse else {}
        payload = build_chunk_payload(meta, chunk)
        points.append(PointStruct(
            id=str(uuid.uuid4()),
            vector={
                "dense": embed_result.dense[i],
                "sparse": SparseVector(indices=[int(k) for k in sparse], values=list(sparse.values())),
            },
            payload=payload,
        ))

    await upsert_points(user_collection_name(), points)
    log.info("user_document_indexed", owner_id=owner_id, document_id=document_id,
             chunks=len(points), domain=dom, language=lang, correlation_id=correlation_id)
    trace_flow("user_document_indexed", correlation_id=correlation_id, owner_id=owner_id,
               document_id=document_id, title=title, domain=dom, subject=subject,
               level=level, language=lang, chunks=len(points))
    return {"status": "ready", "chunk_count": len(points), "domain": dom,
            "subject": subject, "level": level, "language": lang, "source_hash": source_hash}


async def delete_user_document(owner_id: str, document_id: str, language: str | None = None) -> None:
    """Remove one document's chunks from Qdrant (owner-scoped)."""
    await delete_by_filter(user_collection_name(),
                           {"owner_id": owner_id, "document_id": document_id})


async def session_has_documents(owner_id: str, session_id: str) -> bool:
    """Cheap check: does this session have any ready uploaded docs? (avoids a wasted
    vector search on every normal query)."""
    if not session_id:
        return False
    try:
        from src.db.postgres import fetchval

        n = await fetchval(
            "SELECT COUNT(*) FROM user_documents WHERE owner_id=$1::uuid AND session_id=$2::uuid AND status='ready'",
            owner_id, session_id,
        )
        return bool(n)
    except Exception:
        return False


async def delete_session_documents(owner_id: str, session_id: str) -> None:
    """Purge ALL chunks for a session's uploaded docs from Qdrant. Called when a session
    is deleted, so no orphaned vectors remain."""
    await delete_by_filter(user_collection_name(),
                           {"owner_id": owner_id, "session_id": session_id})
    log.info("session_documents_purged", owner_id=owner_id, session_id=session_id)
