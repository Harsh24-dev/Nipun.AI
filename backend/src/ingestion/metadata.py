"""
Rich chunk metadata — the single source of truth for what we tag every vector with.

A consistent, rich payload on each chunk powers two things:
  * CITATIONS  — title, author, source_url, chapter/section, page → precise references.
  * FILTERED RETRIEVAL / ROUTING — domain, subject, level, book_id, owner_id, visibility
    → a query about one book/subject/user doesn't pull noise from another.

`classify_document()` auto-derives domain / subject / level from the text with the fast
LLM when they aren't supplied, degrading to keyword heuristics when the LLM is off.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

import structlog

log = structlog.get_logger("ingestion.metadata")

LEVELS = ("beginner", "intermediate", "advanced", "academic")
VISIBILITY_PUBLIC = "public"
VISIBILITY_PRIVATE = "private"


@dataclass
class DocumentMetadata:
    """Document-level metadata shared by every chunk of a document/book."""
    title: str
    domain: str
    language: str
    source: str = ""
    source_url: str = ""
    author: str = ""
    subject: str = ""
    level: str = ""                 # one of LEVELS
    publication_year: int | None = None
    book_id: str = ""               # stable id for a book/document (dedup + filter)
    document_id: str = ""           # user-doc id (empty for public corpus)
    session_id: str = ""            # chat session that owns this doc ("" = account-wide)
    owner_id: str = ""              # user id for private docs ("" = public corpus)
    visibility: str = VISIBILITY_PUBLIC
    license: str = ""
    isbn: str = ""
    kind: str = "document"          # document | book | user_upload
    extra: dict = field(default_factory=dict)

    def as_payload_base(self) -> dict:
        d = asdict(self)
        extra = d.pop("extra", {}) or {}
        return {k: v for k, v in {**d, **extra}.items() if v not in (None, "")}


def build_chunk_payload(meta: DocumentMetadata, chunk) -> dict:
    """Merge document-level metadata with per-chunk fields into a Qdrant payload.
    `chunk` is an ingestion.chunker.Chunk (text, chunk_index, section, page_number)."""
    payload = meta.as_payload_base()
    payload.update({
        "text": getattr(chunk, "text", ""),
        "chunk_index": getattr(chunk, "chunk_index", 0),
        "section": getattr(chunk, "section", None) or payload.get("section"),
        "page_number": getattr(chunk, "page_number", None),
        "active": True,
    })
    # `source` defaults to the title so citations always have a label.
    payload.setdefault("source", meta.title)
    return {k: v for k, v in payload.items() if v is not None}


def citation_for(payload: dict) -> dict:
    """Build a rich citation object from a chunk payload (used in response cards)."""
    ref = payload.get("section") or ""
    if payload.get("page_number"):
        ref = f"{ref} p.{payload['page_number']}".strip()
    return {
        "text": payload.get("title") or payload.get("source") or "Source",
        "author": payload.get("author", ""),
        "url": payload.get("source_url", ""),
        "reference": ref,
        "subject": payload.get("subject", ""),
        "level": payload.get("level", ""),
    }


# ── Auto-classification ────────────────────────────────────────────────────────

_DOMAIN_HINTS = {
    "legal": ("section", "act", "ipc", "court", "law", "constitution", "petition"),
    "farming": ("crop", "soil", "mandi", "irrigation", "kharif", "rabi", "fertiliser"),
    "health": ("patient", "disease", "symptom", "treatment", "medicine", "clinical"),
    "finance": ("tax", "investment", "loan", "gst", "interest", "portfolio", "sebi"),
    "student": ("exam", "syllabus", "chapter", "textbook", "ncert", "physics", "chemistry"),
    "scheme": ("yojana", "scheme", "beneficiary", "subsidy", "eligibility"),
}
_LEVEL_HINTS = {
    "academic": ("theorem", "hypothesis", "et al", "journal", "abstract", "proof"),
    "advanced": ("advanced", "in-depth", "derivation", "specialised"),
    "beginner": ("introduction", "basics", "beginner", "for dummies", "getting started"),
}

_CLASSIFY_SYSTEM = """Classify a document excerpt for an Indian knowledge base.
Return ONLY JSON: {"domain": "<one of: legal, farming, student, health, scheme, finance,
career, governance, jobs, travel, documents, general>", "subject": "<short subject/topic>",
"level": "<beginner|intermediate|advanced|academic>"}"""


def _heuristic_classify(text: str) -> dict:
    t = (text or "").lower()
    domain = "general"
    best = 0
    for dom, hints in _DOMAIN_HINTS.items():
        score = sum(1 for h in hints if h in t)
        if score > best:
            best, domain = score, dom
    level = "intermediate"
    for lvl, hints in _LEVEL_HINTS.items():
        if any(h in t for h in hints):
            level = lvl
            break
    return {"domain": domain, "subject": "", "level": level}


async def classify_document(text: str, correlation_id: str = "") -> dict:
    """Return {domain, subject, level}. Uses the fast LLM when available, else heuristics."""
    from src.config import settings

    sample = (text or "")[:3000]
    if not sample.strip():
        return {"domain": "general", "subject": "", "level": "intermediate"}
    if not settings.RAG_GRADE_USE_LLM:   # reuse the "LLM available" signal
        return _heuristic_classify(sample)
    try:
        from src.llm.router import route_completion

        resp = await route_completion(
            messages=[{"role": "system", "content": _CLASSIFY_SYSTEM},
                      {"role": "user", "content": sample}],
            override_tier="fast", correlation_id=correlation_id,
        )
        content = resp.content.strip().strip("`").replace("json", "", 1).strip()
        parsed = json.loads(content)
        return {
            "domain": parsed.get("domain", "general") or "general",
            "subject": parsed.get("subject", "") or "",
            "level": parsed.get("level", "intermediate") or "intermediate",
        }
    except Exception as exc:
        log.warning("classify_document_failed", error=str(exc), correlation_id=correlation_id)
        return _heuristic_classify(sample)
