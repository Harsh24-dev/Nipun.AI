"""
Document chunker — splits text into 512-token chunks with 50-token overlap.
Preserves section boundaries for legal and government documents.
"""

import re
from dataclasses import dataclass

import structlog

log = structlog.get_logger("ingestion.chunker")


@dataclass
class Chunk:
    text: str
    chunk_index: int
    section: str | None
    page_number: int | None
    token_estimate: int


# Section header patterns for Indian legal/govt documents
_SECTION_PATTERNS = [
    re.compile(r"^(Section|धारा|ধারা|பிரிவு)\s+\d+", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^(Chapter|अध्याय|अधिनियम)\s+[IVXLCDM\d]+", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^(Article|अनुच्छेद)\s+\d+", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^\d+\.\s+[A-Zऀ-ॿ]", re.MULTILINE),  # numbered clauses
]


# Hard ceiling on chunk size, in characters. The paragraph/sentence logic below can
# otherwise emit a single unbounded chunk when a passage has no sentence delimiters
# (tables, indexes, long unpunctuated lines — common in scraped books). At ~3 chars/token
# that would exceed the embedding model's 8192-token input limit and fail the whole
# document with a 400. 6000 chars ≈ 2000 tokens — safely under the limit.
_HARD_MAX_CHARS = 6000


def _estimate_tokens(text: str) -> int:
    # ~3.5 chars per token for mixed Indic+English text
    return len(text) // 3


def _hard_split(text: str) -> list[str]:
    """Break text that exceeds the hard ceiling into fixed-size character windows,
    preferring a whitespace boundary near the cut so words aren't sliced mid-token."""
    if len(text) <= _HARD_MAX_CHARS:
        return [text]
    parts: list[str] = []
    remaining = text
    while len(remaining) > _HARD_MAX_CHARS:
        cut = remaining.rfind(" ", 0, _HARD_MAX_CHARS)
        if cut < _HARD_MAX_CHARS // 2:   # no decent whitespace break → hard cut
            cut = _HARD_MAX_CHARS
        parts.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()
    if remaining:
        parts.append(remaining)
    return [p for p in parts if p]


def _find_section(text: str) -> str | None:
    for pattern in _SECTION_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(0).strip()[:100]
    return None


def chunk_text(
    text: str,
    chunk_tokens: int = 512,
    overlap_tokens: int = 50,
    page_number: int | None = None,
) -> list[Chunk]:
    """
    Split text into overlapping chunks.
    Tries to break at paragraph boundaries first, then sentence boundaries.
    """
    if not text.strip():
        log.debug("chunk_text_empty_input")
        return []

    target_chars = chunk_tokens * 3       # ~3 chars/token for Indic
    overlap_chars = overlap_tokens * 3

    # Split into paragraphs first
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]

    chunks: list[Chunk] = []
    buffer = ""
    idx = 0

    for para in paragraphs:
        if _estimate_tokens(buffer + para) <= chunk_tokens:
            buffer = (buffer + "\n\n" + para).strip()
        else:
            # Flush buffer as a chunk
            if buffer:
                chunks.append(Chunk(
                    text=buffer,
                    chunk_index=idx,
                    section=_find_section(buffer),
                    page_number=page_number,
                    token_estimate=_estimate_tokens(buffer),
                ))
                idx += 1
                # Keep overlap: last N chars of previous chunk
                buffer = buffer[-overlap_chars:].strip() + "\n\n" + para
            else:
                # Single paragraph exceeds limit — split by sentence
                sentences = re.split(r"(?<=[।.!?])\s+", para)
                for sent in sentences:
                    if _estimate_tokens(buffer + sent) <= chunk_tokens:
                        buffer = (buffer + " " + sent).strip()
                    else:
                        if buffer:
                            chunks.append(Chunk(
                                text=buffer,
                                chunk_index=idx,
                                section=_find_section(buffer),
                                page_number=page_number,
                                token_estimate=_estimate_tokens(buffer),
                            ))
                            idx += 1
                            buffer = buffer[-overlap_chars:].strip() + " " + sent
                        else:
                            buffer = sent

    if buffer.strip():
        chunks.append(Chunk(
            text=buffer.strip(),
            chunk_index=idx,
            section=_find_section(buffer),
            page_number=page_number,
            token_estimate=_estimate_tokens(buffer),
        ))

    # Safety net: enforce the hard ceiling on every chunk. The paragraph/sentence logic
    # above can emit an oversized chunk for text with no sentence delimiters; split any
    # such chunk so no single piece can exceed the embedding model's input limit.
    capped: list[Chunk] = []
    for c in chunks:
        pieces = _hard_split(c.text)
        if len(pieces) == 1:
            capped.append(c)
            continue
        for piece in pieces:
            capped.append(Chunk(
                text=piece,
                chunk_index=len(capped),
                section=c.section,
                page_number=c.page_number,
                token_estimate=_estimate_tokens(piece),
            ))
    # Re-number sequentially if the split path renumbered a subset.
    for i, c in enumerate(capped):
        c.chunk_index = i

    log.debug(
        "chunk_text_complete",
        input_chars=len(text),
        chunks=len(capped),
        chunk_tokens=chunk_tokens,
        overlap_tokens=overlap_tokens,
    )
    return capped
