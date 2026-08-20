"""
Generate a downloadable DELIVERABLE (slide deck / document) to explain an answer.

This is the "make me a file" capability — like generating a PPTX or DOCX with charts and
pictures when that explains something better than a text card. The AGENT decides when to use
it (for a study summary, a plan, a comparison, a report). Flow:

  1. The LLM writes a structured spec (title, sections, bullets, chart data, image search terms)
     for the topic — grounded in the conversation/knowledge, never invented numbers.
  2. Images are fetched best-effort (Openverse) and charts rendered (matplotlib).
  3. filegen builds the real .pptx/.docx bytes; file_store holds them for download.
  4. A `document` card is returned with a download link AND an inline summary, so the answer is
     useful even if the file can't be produced (libraries missing → graceful text fallback).
"""

from __future__ import annotations

import json

import structlog

from src.core.runtime_context import runtime_prompt_header
from src.llm.router import route_completion
from src.synthesis import filegen
from src.synthesis.file_store import store_file

log = structlog.get_logger("synthesis.deliverable")

_SPEC_SYSTEM = """You are designing a {fmt_name} to explain a topic clearly and attractively for
an ordinary Indian user. Produce a STRUCTURED SPEC (not prose). Rules:
- 4-7 sections, each with a short heading and 3-6 concise bullet points in simple language.
- Give EVERY section a `notes` field: 2-4 sentences, in plain {language}, that EXPLAIN the
  slide as if speaking to the user — what it means and why it matters. This is the spoken
  explanation that accompanies the bullets, not a repeat of them.
- Add a `chart` to a section ONLY when there is real quantitative data to show (from the
  conversation/knowledge or well-established facts) — never invent numbers. type is
  "bar", "line", or "pie"; labels and values must be equal length.
- Add an `image_query` (2-4 words) to 1-3 sections where a picture/diagram would aid
  understanding (e.g. a concept, place, or process). Leave it out otherwise.
- Write in {language}.
Respond with STRICT JSON only:
{{"title": "...", "subtitle": "...",
  "sections": [{{"heading": "...", "bullets": ["..."], "notes": "...", "paragraphs": ["..."],
    "chart": {{"type": "bar", "title": "...", "labels": ["..."], "values": [1,2],
              "series_label": "..."}},
    "image_query": "..."}}]}}
Include `chart`/`image_query`/`paragraphs` only where they apply; ALWAYS include `notes`."""


async def _fetch_image_bytes(query: str) -> bytes | None:
    """Best image for a slide/section via the shared Google-first chain (Google → Wikipedia),
    and — when the specific image isn't available online — GENERATE one (if configured). So
    generated decks get relevant, good pictures, and a bespoke illustration when needed."""
    try:
        from src.synthesis.resources import image_bytes_for
        got = await image_bytes_for(query, allow_generate=True)
        return got[0] if got else None
    except Exception as exc:
        log.debug("deliverable_image_failed", query=query, error=str(exc))
        return None


async def _build_spec(topic: str, fmt: str, profile: dict, context_text: str,
                      language: str, correlation_id: str) -> dict | None:
    fmt_name = "slide deck (presentation)" if fmt == "pptx" else "document/report"
    try:
        result = await route_completion(
            messages=[
                {"role": "system",
                 "content": runtime_prompt_header(profile, language)
                            + _SPEC_SYSTEM.format(fmt_name=fmt_name, language=language)},
                {"role": "user",
                 "content": f"TOPIC / REQUEST: {topic}\n\nRELEVANT CONTEXT (use, don't invent):\n"
                            f"{context_text[:2500] or '(none)'}"},
            ],
            complexity="multi_step", override_tier="primary", correlation_id=correlation_id,
        )
        content = result.content.strip()
        if "```" in content:
            content = content.split("```")[1].split("```")[0].replace("json", "", 1).strip()
        spec = json.loads(content)
        return spec if isinstance(spec, dict) and spec.get("sections") else None
    except Exception as exc:
        log.warning("deliverable_spec_failed", error=str(exc), correlation_id=correlation_id)
        return None


def _slug(title: str, fmt: str) -> str:
    base = "".join(c if c.isalnum() or c in " -_" else "" for c in (title or "nipun"))[:50].strip()
    return (base.replace(" ", "_") or "nipun") + "." + fmt


def _data_uri(data: bytes, mime: str) -> str:
    import base64
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def _img_mime(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"GIF":
        return "image/gif"
    if data[:2] == b"\xff\xd8":
        return "image/jpeg"
    return "image/png"


def _build_preview(spec: dict, fmt: str) -> dict:
    """An inline, renderable preview of the SAME content as the file — each section becomes a
    'slide' with its heading, bullets, the chart (as a PNG data-URI) and any picture — so the
    UI can show the deck/document without a binary viewer."""
    slides = [{"heading": spec.get("title", ""), "subtitle": spec.get("subtitle", ""),
               "bullets": [], "is_title": True}]
    for sec in spec.get("sections", []):
        slide = {
            "heading": sec.get("heading", ""),
            "bullets": [str(b) for b in (sec.get("bullets") or [])]
                       + [str(p) for p in (sec.get("paragraphs") or [])],
            # The spoken explanation for THIS slide/page — shown as text alongside it.
            "notes": str(sec.get("notes") or ""),
        }
        png = filegen.render_chart_png(sec.get("chart")) if sec.get("chart") else None
        if png:
            slide["chart"] = _data_uri(png, "image/png")
        if sec.get("image_bytes"):
            try:
                slide["image"] = _data_uri(sec["image_bytes"], _img_mime(sec["image_bytes"]))
            except Exception:
                pass
        slides.append(slide)
    return {"format": fmt, "slides": slides}


async def generate_deliverable(
    topic: str, fmt: str, owner_id: str, profile: dict | None = None,
    context_text: str = "", language: str = "en", correlation_id: str = "",
) -> dict | None:
    """Produce a downloadable file card for `topic`. `fmt` in {'pptx','docx'}. Returns a
    `document` card (with a download link when possible) or None to let the caller fall back."""
    fmt = (fmt or "pptx").lower()
    if fmt not in filegen.FORMATS:
        fmt = "pptx"
    avail = filegen.libraries_available()
    if not avail.get(fmt):
        # Libraries not installed — tell the caller so it degrades to a normal text answer.
        log.info("deliverable_unavailable", fmt=fmt, correlation_id=correlation_id)
        return None

    spec = await _build_spec(topic, fmt, profile or {}, context_text, language, correlation_id)
    if not spec:
        return None
    spec.setdefault("author", "Nipun.AI")

    # Fetch images for sections that asked for one (best-effort, in parallel).
    import asyncio
    img_sections = [s for s in spec.get("sections", []) if s.get("image_query")]
    if img_sections:
        imgs = await asyncio.gather(*[_fetch_image_bytes(s["image_query"]) for s in img_sections],
                                    return_exceptions=True)
        for s, b in zip(img_sections, imgs):
            if isinstance(b, (bytes, bytearray)) and b:
                s["image_bytes"] = bytes(b)

    built = filegen.build(fmt, spec)
    if not built:
        return None
    data, mime = built
    filename = _slug(spec.get("title", topic), fmt)
    file_id = await store_file(owner_id, filename, mime, data)

    # An inline summary so the answer is complete even without downloading.
    outline = "\n".join(f"- **{s.get('heading','')}**" for s in spec.get("sections", [])[:8])
    summary = (f"I've prepared a {'presentation' if fmt == 'pptx' else 'document'} — "
               f"**{spec.get('title', topic)}**.\n\n{spec.get('subtitle','')}\n\n{outline}")
    card = {
        "cardType": "document",
        "language": language,
        "title": spec.get("title", topic),
        "summary": summary,
        # Inline, renderable preview of every slide/page (heading + bullets + chart image +
        # picture + the text explanation), so the UI shows the file's content, not just a link.
        "preview": _build_preview(spec, fmt),
    }
    if file_id:
        card["file_url"] = f"/files/{file_id}"
        card["filename"] = filename
        card["download"] = {"url": f"/files/{file_id}", "filename": filename,
                            "format": fmt.upper(), "mime": mime}
    else:
        card["summary"] += "\n\n_(Could not create the download link right now — the content is above.)_"
    log.info("deliverable_generated", fmt=fmt, has_file=bool(file_id),
             sections=len(spec.get("sections", [])), correlation_id=correlation_id)
    return card
