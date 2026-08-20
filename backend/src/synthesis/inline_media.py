"""
Inline media — put pictures and charts RIGHT WHERE they help, not in a bottom section.

The generator marks, inside its Markdown answer, the spots where a visual aids understanding:
  * a picture:  ![caption](img://<focused search terms>)
  * a chart:    a fenced ```chart { "type": "...", "labels": [...], "values": [...] } ``` block

This module resolves those markers in place:
  - `img://` → the best REAL, relevant image for those terms (Google-first chain; a specific
    illustration is generated when nothing suitable exists online), or the marker is dropped.
  - ```chart``` → a rendered chart image (matplotlib) as a data-URI, or dropped if the data is
    invalid.
So the finished Markdown has each visual next to the text it explains, and the frontend's
Markdown renderer shows them inline. Also acts as a lightweight relevance check: a marker that
can't be resolved to something real and on-topic is removed rather than shown broken.
"""

from __future__ import annotations

import json
import re

import structlog

log = structlog.get_logger("synthesis.inline_media")

_IMG_MARKER = re.compile(r"!\[([^\]]*)\]\(img://([^)]+)\)")
_CHART_BLOCK = re.compile(r"```chart\s*\n(.*?)```", re.DOTALL)
# A node-and-arrow DIAGRAM the model can draw for "how X works" answers. Rendered natively by
# the frontend's SVG DiagramCard — keyless, crisp, and no heavy base64 image. Shape:
#   ```diagram
#   {"title":"...","nodes":[{"id":"a","label":"..."}],"edges":[{"from":"a","to":"b","label":"..."}]}
#   ```
_DIAGRAM_BLOCK = re.compile(r"```diagram\s*\n(.*?)```", re.DOTALL)
# A rich EMBED the answer wants shown inline (rendered as its own component by the UI, right
# where the marker sits): currently a downloadable deliverable, e.g. [[file:pptx:the water cycle]].
_FILE_MARKER = re.compile(r"\[\[file:(pptx|docx):([^\]]+)\]\]", re.IGNORECASE)
_MAX_INLINE = 4   # cap visuals so an answer isn't overwhelmed
_MAX_EMBEDS = 2   # cap heavy embeds (generated files) per answer


def _data_uri(data: bytes, mime: str) -> str:
    import base64
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


async def _resolve_charts(md: str) -> str:
    from src.synthesis import filegen
    if "```chart" not in md:
        return md
    matches = list(_CHART_BLOCK.finditer(md))
    out, last = [], 0
    for m in matches:
        out.append(md[last:m.start()])
        last = m.end()
        try:
            spec = json.loads(m.group(1).strip())
            png = filegen.render_chart_png(spec)
            if png:
                title = spec.get("title", "chart")
                out.append(f"\n\n![{title}]({_data_uri(png, 'image/png')})\n\n")
            # invalid/unavailable → drop the block silently (answer text still stands)
        except Exception as exc:
            log.debug("inline_chart_failed", error=str(exc))
    out.append(md[last:])
    return "".join(out)


def _valid_diagram(spec) -> dict | None:
    """Sanitise a model-supplied diagram spec into {nodes, edges} the SVG DiagramCard accepts,
    or None if it isn't a usable graph. Keeps only nodes with an id+label and edges whose
    endpoints both exist — so a malformed block is dropped, never rendered broken."""
    if not isinstance(spec, dict):
        return None
    nodes, edges = spec.get("nodes"), spec.get("edges") or []
    if not isinstance(nodes, list):
        return None
    clean_nodes, ids = [], set()
    for n in nodes:
        if isinstance(n, dict) and n.get("id") not in (None, "") and n.get("label"):
            nid = str(n["id"])
            clean_nodes.append({"id": nid, "label": str(n["label"])[:60]})
            ids.add(nid)
    if len(clean_nodes) < 2:
        return None
    clean_edges = []
    for e in edges if isinstance(edges, list) else []:
        if not isinstance(e, dict):
            continue
        frm = str(e.get("from") or e.get("source") or "")
        to = str(e.get("to") or e.get("target") or "")
        if frm in ids and to in ids and frm != to:
            edge = {"from": frm, "to": to}
            if e.get("label"):
                edge["label"] = str(e["label"])[:40]
            clean_edges.append(edge)
    return {"nodes": clean_nodes, "edges": clean_edges}


# Escaping-safe markers (no quotes/braces, so they never break the card's JSON). These REPLACE
# the old ```chart/```diagram JSON blocks, which the model frequently mis-escaped inside the
# summary string — dumping raw JSON into the answer.
_CHART_MARKER = re.compile(r"\[\[chart:\s*([a-zA-Z]+)\s*\|([^|\]]*)\|([^|\]]*)\|([^\]]*)\]\]")
_DIAGRAM_MARKER = re.compile(r"\[\[diagram:\s*([^\]]+?)\]\]", re.IGNORECASE | re.DOTALL)


# Rich interactive blocks the synthesis agent can place anywhere — escaping-safe (no quotes/
# braces). They render as their own colourful, animated components in the UI.
_KEYPOINTS_MARKER = re.compile(r"\[\[keypoints:\s*([^\]]+?)\]\]", re.IGNORECASE | re.DOTALL)
_CALLOUT_MARKER = re.compile(
    r"\[\[callout:\s*(tip|note|warning|success|info|key)\s*:\s*([^\]]+?)\]\]", re.IGNORECASE | re.DOTALL)
_STAT_MARKER = re.compile(r"\[\[stats:\s*([^\]]+?)\]\]", re.IGNORECASE | re.DOTALL)
# Colour swatches — "Name=#hex" pairs. Ideal for colours/palettes/themes (shows the ACTUAL
# colours), directly serving "support multiple colours, not just theme colours".
_SWATCH_MARKER = re.compile(r"\[\[swatches:\s*([^\]]+?)\]\]", re.IGNORECASE | re.DOTALL)
_HEX_RE = re.compile(r"^#?[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?$")


def _resolve_block_markers(md: str) -> tuple[str, list]:
    """Turn key-points / callout / stat / swatch markers into inline EMBEDS the UI renders as
    rich, colourful blocks. Returns (markdown, embeds)."""
    if not any(t in md.lower() for t in ("[[keypoints:", "[[callout:", "[[stats:", "[[swatches:")):
        return md, []
    embeds: list = []
    i = 0

    def kp(m):
        nonlocal i
        items = [x.strip() for x in re.split(r"[;\n]|•", m.group(1)) if x.strip()]
        if len(items) < 2:
            return m.group(0)
        eid = f"kp{i}"; i += 1
        embeds.append({"id": eid, "kind": "keypoints", "items": items[:8]})
        return f"\n\n[[embed:{eid}]]\n\n"

    def co(m):
        nonlocal i
        variant = m.group(1).lower()
        text = " ".join(m.group(2).split())
        if not text:
            return m.group(0)
        eid = f"co{i}"; i += 1
        embeds.append({"id": eid, "kind": "callout", "variant": variant, "text": text[:400]})
        return f"\n\n[[embed:{eid}]]\n\n"

    def st(m):
        nonlocal i
        # "label=value; label=value" → a row of colourful stat tiles.
        tiles = []
        for pair in re.split(r"[;\n]", m.group(1)):
            if "=" in pair:
                label, _, value = pair.partition("=")
                if label.strip() and value.strip():
                    tiles.append({"label": label.strip()[:40], "value": value.strip()[:24]})
        if len(tiles) < 2:
            return m.group(0)
        eid = f"st{i}"; i += 1
        embeds.append({"id": eid, "kind": "stats", "tiles": tiles[:5]})
        return f"\n\n[[embed:{eid}]]\n\n"

    def sw(m):
        nonlocal i
        colours = []
        for pair in re.split(r"[;\n]", m.group(1)):
            name, _, hexv = pair.partition("=")
            hexv = hexv.strip()
            if name.strip() and _HEX_RE.match(hexv):
                colours.append({"name": name.strip()[:30], "hex": "#" + hexv.lstrip("#")})
        if len(colours) < 2:
            return m.group(0)
        eid = f"sw{i}"; i += 1
        embeds.append({"id": eid, "kind": "swatches", "colours": colours[:10]})
        return f"\n\n[[embed:{eid}]]\n\n"

    md = _KEYPOINTS_MARKER.sub(kp, md)
    md = _CALLOUT_MARKER.sub(co, md)
    md = _STAT_MARKER.sub(st, md)
    md = _SWATCH_MARKER.sub(sw, md)
    return md, embeds


async def _resolve_chart_markers(md: str) -> str:
    """[[chart: bar | Title | a,b,c | 1,2,3]] → a rendered chart image inline."""
    if "[[chart:" not in md.lower():
        return md
    from src.synthesis import filegen
    out, last = [], 0
    for m in _CHART_MARKER.finditer(md):
        out.append(md[last:m.start()])
        last = m.end()
        ctype = m.group(1).lower().strip()
        title = m.group(2).strip()
        labels = [x.strip() for x in m.group(3).split(",") if x.strip()]
        try:
            values = [float(x.strip()) for x in m.group(4).split(",") if x.strip()]
        except ValueError:
            values = []
        if labels and len(labels) == len(values):
            spec = {"type": ctype if ctype in ("bar", "line", "pie") else "bar",
                    "title": title, "labels": labels, "values": values}
            png = filegen.render_chart_png(spec)
            if png:
                out.append(f"\n\n![{title or 'chart'}]({_data_uri(png, 'image/png')})\n\n")
        # invalid → drop the marker
    out.append(md[last:])
    return "".join(out)


def _parse_diagram_flow(spec: str) -> dict | None:
    """Turn 'A -> B -> C; B -> D' into {nodes, edges} for the SVG DiagramCard."""
    label_to_id: dict[str, str] = {}
    nodes: list[dict] = []
    edges: list[dict] = []

    def nid(label: str) -> str | None:
        label = " ".join((label or "").split())[:60]
        if not label:
            return None
        if label not in label_to_id:
            label_to_id[label] = f"n{len(label_to_id)}"
            nodes.append({"id": label_to_id[label], "label": label})
        return label_to_id[label]

    for chain in re.split(r"[;\n]", spec or ""):
        parts = [p for p in re.split(r"->|→|-\s*>", chain) if p.strip()]
        for a, b in zip(parts, parts[1:]):
            ia, ib = nid(a), nid(b)
            if ia and ib and ia != ib and not any(e["from"] == ia and e["to"] == ib for e in edges):
                edges.append({"from": ia, "to": ib})
    if len(nodes) < 2:
        return None
    return {"nodes": nodes, "edges": edges}


def _resolve_diagram_markers(md: str) -> tuple[str, list]:
    """[[diagram: A -> B; B -> C]] → an inline native SVG diagram embed."""
    if "[[diagram:" not in md.lower():
        return md, []
    embeds: list = []
    out, last = [], 0
    for i, m in enumerate(_DIAGRAM_MARKER.finditer(md)):
        out.append(md[last:m.start()])
        last = m.end()
        spec = _parse_diagram_flow(m.group(1))
        if spec:
            eid = f"flowmk{i}"
            embeds.append({"id": eid, "kind": "diagram", "title": "How it works", "diagram": spec})
            out.append(f"\n\n[[embed:{eid}]]\n\n")
    out.append(md[last:])
    return "".join(out), embeds


def _resolve_diagrams(md: str) -> tuple[str, list]:
    """Turn ```diagram {json}``` blocks into inline EMBEDS (native SVG node/arrow diagrams),
    referenced from the text by [[embed:id]]. Returns (markdown, embeds)."""
    if "```diagram" not in md:
        return md, []
    embeds: list = []
    out, last = [], 0
    for i, m in enumerate(_DIAGRAM_BLOCK.finditer(md)):
        out.append(md[last:m.start()])
        last = m.end()
        try:
            raw = json.loads(m.group(1).strip())
        except Exception:
            raw = None
        spec = _valid_diagram(raw)
        if spec:
            eid = f"diagram{i}"
            title = (raw.get("title") if isinstance(raw, dict) else "") or "How it works"
            embeds.append({"id": eid, "kind": "diagram", "title": str(title)[:60], "diagram": spec})
            out.append(f"\n\n[[embed:{eid}]]\n\n")
        # invalid → drop the block silently (the prose still stands)
    out.append(md[last:])
    return "".join(out), embeds


async def _resolve_images(md: str, owner_id: str = "") -> str:
    from src.synthesis.resources import best_image, image_bytes_for
    matches = list(_IMG_MARKER.finditer(md))
    if not matches:
        return md
    out, last, placed = [], 0, 0
    for m in matches:
        out.append(md[last:m.start()])
        last = m.end()
        caption, query = m.group(1), m.group(2).strip()
        if placed >= _MAX_INLINE:
            continue     # over budget → drop remaining markers
        try:
            img = await best_image(query)
            if img and (img.get("thumbnail") or img.get("url")):
                out.append(f"![{caption or img.get('title','')}]({img.get('thumbnail') or img['url']})")
                placed += 1
                continue
            # Nothing suitable online. Generating a stand-in (Pollinations/DALL·E) is opt-in only:
            # it is slow and can produce off-topic art, so by default we DROP the marker rather
            # than risk a wrong/weird image (the repeated horse/portrait problem).
            from src.config import settings
            if settings.INLINE_IMAGE_GENERATE:
                gen = await image_bytes_for(query, allow_generate=True)
                if gen:
                    data, mime = gen
                    out.append(f"![{caption}]({_data_uri(data, mime)})")
                    placed += 1
            # else: drop the marker (no broken/irrelevant image)
        except Exception as exc:
            log.debug("inline_image_failed", query=query[:60], error=str(exc))
    out.append(md[last:])
    return "".join(out)


async def _resolve_files(md: str, owner_id: str, language: str, context: str) -> tuple[str, list]:
    """Turn [[file:pptx|docx:topic]] markers into inline EMBEDS the UI renders in place (a
    download button + slide/page preview). Returns (markdown, embeds)."""
    matches = list(_FILE_MARKER.finditer(md))
    if not matches:
        return md, []
    from src.synthesis.deliverable import generate_deliverable

    embeds: list = []
    out, last, made = [], 0, 0
    for i, m in enumerate(matches):
        out.append(md[last:m.start()])
        last = m.end()
        fmt, topic = m.group(1).lower(), m.group(2).strip()
        if made >= _MAX_EMBEDS:
            continue
        try:
            card = await generate_deliverable(
                topic=topic, fmt=fmt, owner_id=owner_id, context_text=context,
                language=language)
            if card:
                eid = f"file{i}"
                embeds.append({"id": eid, "kind": "file", **card})
                out.append(f"\n\n[[embed:{eid}]]\n\n")   # UI renders the embed right here
                made += 1
        except Exception as exc:
            log.debug("inline_file_failed", topic=topic[:60], error=str(exc))
    out.append(md[last:])
    return "".join(out), embeds


# Explanatory answers that should always carry at least one visual.
_EXPLAIN_RE = re.compile(
    r"\b(explain|how (does|do|to)|what (is|are)|overview|introduction|guide|work|works|"
    r"working|process|architecture|concept|difference|compare|steps?|mechanism)\b", re.IGNORECASE)
# Queries/answers that describe a SEQUENCE — best shown as a flow diagram.
_PROCESS_RE = re.compile(
    r"\b(how (does|do|to)|works?|working|process|steps?|pipeline|life ?cycle|flow|"
    r"architecture|mechanism|stages?|phases?)\b", re.IGNORECASE)
# A numbered step heading in the answer. Matches the common formats models actually emit:
#   "1. Retrieval"   "### 2. Augmentation"   "#### Step 1: Prepare"   "**Phase 2 — Index**"
# The optional Step/Phase/Stage word and the ':' separator are what the old pattern missed
# (so "Step 1: …" headings never became a diagram).
_STEP_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:\*\*)?\s*(?:step|phase|stage)?\s*(\d+)\s*[.):\-—]\s*([^\n]{2,70})",
    re.IGNORECASE | re.MULTILINE,
)


def _extract_steps(summary: str) -> list[str]:
    """Pull an ordered list of short step labels from a numbered answer (a real flow), or []."""
    matches = _STEP_RE.findall(summary or "")
    if len(matches) < 2:
        return []
    try:
        if int(matches[0][0]) not in (0, 1):     # a genuine 1..n sequence
            return []
    except ValueError:
        return []
    labels: list[str] = []
    for _num, raw in matches[:6]:
        lbl = re.sub(r"[*`#]", "", raw).strip().strip(":").strip()
        lbl = re.split(r"[—:.(]| - ", lbl)[0].strip()      # keep the head phrase
        words = lbl.split()
        labels.append(" ".join(words[:6]) if len(words) > 6 else lbl)
    return [l for l in labels if l]


def _insert_after_intro(summary: str, block: str) -> str:
    """Place a visual block right after the answer's opening paragraph (not at the very top)."""
    parts = summary.split("\n\n", 1)
    return parts[0] + block + parts[1] if len(parts) == 2 else summary + block


async def ensure_visual(summary: str, query: str, title: str = "", owner_id: str = "") -> tuple[str, list]:
    """Guarantee an explanatory answer carries at least one relevant visual, and return
    (markdown, embeds).

    Preference order, most reliable first:
      1. A native SVG FLOW DIAGRAM built from the answer's OWN numbered steps — keyless, always
         on-topic (it IS the answer's content), crisp, and light (no base64). This is what makes
         'how does X work' answers reliably show a diagram.
      2. Otherwise, a real topic image searched on the DISAMBIGUATED title first (so an ambiguous
         word like 'rag' doesn't fetch ragtime music). Inserts nothing if none is found — a wrong
         or missing image is better than a broken one."""
    if not summary or "![" in summary or "[[embed:" in summary:   # already has a visual — leave it
        return summary, []
    q = (query or "")
    if not (_EXPLAIN_RE.search(q) or _EXPLAIN_RE.search(summary[:200])):
        return summary, []

    # 1) BEST — a native SVG flow diagram from the answer's own steps.
    if _PROCESS_RE.search(q) or _PROCESS_RE.search(summary[:400]):
        steps = _extract_steps(summary)
        if len(steps) >= 2:
            spec = {
                "nodes": [{"id": f"n{i}", "label": s} for i, s in enumerate(steps)],
                "edges": [{"from": f"n{i}", "to": f"n{i+1}"} for i in range(len(steps) - 1)],
            }
            eid = "flow0"
            embed = {"id": eid, "kind": "diagram",
                     "title": (title or "How it works").split("(")[0].strip()[:50] or "How it works",
                     "diagram": spec}
            return _insert_after_intro(summary, f"\n\n[[embed:{eid}]]\n\n"), [embed]

    # 2) Otherwise, a real topic image — searched on the DISAMBIGUATED title first.
    topic = (title or "").strip() or q
    try:
        from src.synthesis.resources import best_image
        img = (await best_image(f"{topic} diagram")
               or await best_image(topic)
               or (await best_image(f"{q} diagram") if q and q != topic else None))
        thumb = (img or {}).get("thumbnail") or (img or {}).get("url")
        if not thumb:
            return summary, []
        caption = (img or {}).get("title") or "Illustration"
        return _insert_after_intro(summary, f"\n\n![{caption}]({thumb})\n\n"), []
    except Exception as exc:
        log.debug("ensure_visual_failed", error=str(exc))
        return summary, []


async def resolve_inline_media(markdown: str, owner_id: str = "", language: str = "en",
                               context: str = "", query: str = "", title: str = "") -> tuple[str, list]:
    """Replace inline media markers with real content in place. Returns (markdown, embeds):
    - img:// and ```chart``` become inline images (in the markdown itself);
    - [[file:...]] becomes an inline EMBED (rich component) referenced by [[embed:id]], with
      the embed objects returned for the card to carry.
    Never raises; returns (original, []) on failure."""
    has_media = any(t in (markdown or "") for t in
                    ("img://", "[[chart:", "[[diagram:", "[[keypoints:", "[[callout:", "[[stats:",
                     "[[swatches:", "```chart", "```diagram", "[[file:"))
    md, embeds = markdown, []
    try:
        if has_media:
            # Rich interactive blocks (key-points / callouts / stats / swatches)…
            md, block_embeds = _resolve_block_markers(md)
            embeds.extend(block_embeds)
            # Escaping-safe chart/diagram markers…
            md = await _resolve_chart_markers(md)
            md, mk_dia = _resolve_diagram_markers(md)
            embeds.extend(mk_dia)
            # …then the legacy fenced-JSON forms (kept for backward compatibility).
            md = await _resolve_charts(md)
            md, dia_embeds = _resolve_diagrams(md)
            embeds.extend(dia_embeds)
            md = await _resolve_images(md, owner_id)
            md, file_embeds = await _resolve_files(md, owner_id, language, context or (markdown or "")[:2000])
            embeds.extend(file_embeds)
        # Guarantee a visual on explanatory answers even when the model emitted no markers —
        # only when nothing was resolved above, so we never double up.
        if not embeds and "![" not in md:
            md, fb_embeds = await ensure_visual(md, query, title=title, owner_id=owner_id)
            embeds.extend(fb_embeds)
    except Exception as exc:
        log.warning("inline_media_failed", error=str(exc))
        return markdown, embeds
    return md, embeds
