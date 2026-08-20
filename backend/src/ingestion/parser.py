"""
Document parser — PDF, HTML, plain text → clean text + metadata.
"""

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

import structlog

log = structlog.get_logger("ingestion.parser")


@dataclass
class ParsedDocument:
    text: str
    title: str
    source_url: str
    source_hash: str
    domain: str
    language: str
    page_count: int = 1
    metadata: dict = field(default_factory=dict)


def _hash_content(content: str | bytes) -> str:
    if isinstance(content, str):
        content = content.encode()
    return hashlib.sha256(content).hexdigest()[:16]


def _clean_text(text: str) -> str:
    # Remove excessive whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    # Remove page numbers (common in PDFs)
    text = re.sub(r"\n\s*\d+\s*\n", "\n", text)
    return text.strip()


def parse_pdf(path: str | Path, domain: str, language: str, source_url: str = "") -> ParsedDocument:
    from pypdf import PdfReader

    log.info("parse_pdf_start", path=str(path), domain=domain, language=language)
    reader = PdfReader(str(path))
    pages_text = []
    for page in reader.pages:
        pages_text.append(page.extract_text() or "")

    full_text = "\n\n".join(pages_text)
    title = Path(path).stem.replace("_", " ").replace("-", " ").title()

    doc = ParsedDocument(
        text=_clean_text(full_text),
        title=title,
        source_url=source_url or str(path),
        source_hash=_hash_content(full_text),
        domain=domain,
        language=language,
        page_count=len(reader.pages),
    )
    log.info("parse_pdf_complete", title=title, pages=doc.page_count, chars=len(doc.text))
    return doc


def parse_html(html: str, domain: str, language: str, source_url: str = "") -> ParsedDocument:
    from bs4 import BeautifulSoup

    log.info("parse_html_start", source_url=source_url, domain=domain, language=language)
    soup = BeautifulSoup(html, "lxml")

    # Remove navigation, ads, scripts
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form"]):
        tag.decompose()

    title_tag = soup.find("title") or soup.find("h1")
    title = title_tag.get_text(strip=True) if title_tag else "Untitled"

    # Extract main content
    main = soup.find("main") or soup.find("article") or soup.find("body")
    text = main.get_text(separator="\n") if main else soup.get_text(separator="\n")

    doc = ParsedDocument(
        text=_clean_text(text),
        title=title[:200],
        source_url=source_url,
        source_hash=_hash_content(html),
        domain=domain,
        language=language,
    )
    log.info("parse_html_complete", title=doc.title, chars=len(doc.text), source_url=source_url)
    return doc


def parse_text(text: str, title: str, domain: str, language: str, source_url: str = "") -> ParsedDocument:
    log.debug("parse_text", title=title, domain=domain, language=language, chars=len(text))
    return ParsedDocument(
        text=_clean_text(text),
        title=title,
        source_url=source_url,
        source_hash=_hash_content(text),
        domain=domain,
        language=language,
    )
