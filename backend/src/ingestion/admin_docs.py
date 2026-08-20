"""
Admin / backend corpus upload — files an admin uploads become part of the SHARED
public corpus, so they ground answers for ALL users' queries (unlike private user
uploads, which are owner-filtered).

Chunks are embedded locally (BGE-M3) and written to the public `{domain}_{language}`
collections with visibility='public' and NO owner_id — exactly like the seed/book
corpus — plus a rich metadata payload for citation + filtered retrieval.
"""

from __future__ import annotations

import structlog

from src.core.logging import trace_flow
from src.ingestion.metadata import classify_document
from src.ingestion.parser import _hash_content
from src.ingestion.pipeline import ingest_spec
from src.ingestion.sources.base import IngestSpec
from src.ingestion.user_docs import _parse_bytes
from src.language.detector import detect_language

log = structlog.get_logger("ingestion.admin_docs")


async def ingest_admin_document(
    *,
    filename: str,
    content: bytes,
    mime_type: str,
    title: str = "",
    domain: str | None = None,
    language: str | None = None,
    author: str = "",
    subject: str = "",
    level: str = "",
    correlation_id: str = "",
) -> dict:
    """Parse → classify → chunk → local-embed → index one admin-uploaded doc into the
    SHARED public corpus. Returns the pipeline status dict."""
    from src.ingestion.user_docs import ALLOWED_MIME

    kind = ALLOWED_MIME.get(mime_type, "text")
    title = title or filename or "Corpus document"
    lang0 = (language or "").split("+")[0]

    text = _parse_bytes(content, kind, filename, domain or "general", lang0 or "en")
    if not text.strip():
        return {"status": "failed", "reason": "no_text_extracted", "chunks": 0}

    lang = lang0 or detect_language(text[:500]).split("+")[0] or "en"

    # Auto-classify domain / subject / level when not supplied.
    cls = await classify_document(text, correlation_id)
    dom = domain or cls["domain"]
    subject = subject or cls["subject"]
    level = level or cls["level"]
    book_id = f"corpus:{_hash_content(filename + title)}"

    log.info("admin_doc_ingest_start", title=title[:80], domain=dom, language=lang,
             subject=subject, level=level, correlation_id=correlation_id)
    trace_flow("admin_doc_ingest_start", correlation_id=correlation_id, title=title,
               domain=dom, language=lang, subject=subject, level=level, author=author)

    spec = IngestSpec(
        domain=dom, language=lang, title=title, text=text, source_url=filename,
        metadata={"kind": "document", "source": title, "author": author, "subject": subject,
                  "level": level, "book_id": book_id, "visibility": "public"},
    )
    result = await ingest_spec(spec)
    log.info("admin_doc_ingest_done", title=title[:80], domain=dom, status=result.get("status"),
             chunks=result.get("chunks", 0), correlation_id=correlation_id)
    trace_flow("admin_doc_ingest_done", correlation_id=correlation_id, title=title,
               status=result.get("status"), chunks=result.get("chunks", 0), domain=dom)
    return {**result, "domain": dom, "language": lang, "subject": subject, "level": level}
