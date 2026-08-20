"""
Adaptive-explanation synthesis.

Before writing prose, build an ExplanationPlan tuned to the user: persona, depth,
teaching format, modality, and the one key takeaway. Prose is the DEFAULT modality — a
visual is chosen ONLY when it carries meaning prose can't, and rejected-visual decisions
are logged. The plan is injected into generation, and its affordances (key_takeaway,
explain_differently, understanding_check) are attached to the delivered card.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import structlog

from src.core.metrics import EXPLANATION_DEPTH_TOTAL, EXPLANATION_MODALITY_TOTAL

log = structlog.get_logger("synthesis.explanation")

PERSONAS = ("student", "professional_reskilling", "professional_task", "mentee", "general")
DEPTHS = ("quick", "working", "mastery")
FORMATS = ("analogy", "worked_example", "concrete_first", "socratic", "contrast", "plain_explanation")
MODALITIES = ("prose", "step_cards", "comparison_table", "timeline", "diagram",
              "illustrative_diagram", "map", "interactive_widget", "mindmap", "whiteboard")


@dataclass
class LearnerProfile:
    persona: str = "general"
    prior_knowledge: str = "unknown"       # low | medium | high | unknown
    goal: str = "understand"
    language: str = "en"
    reading_level: str = "simple"          # simple | standard | expert
    # STATE assumptions made when memory was thin (surfaced for transparency).
    assumptions: list[str] = field(default_factory=list)


@dataclass
class ExplanationPlan:
    learner: LearnerProfile
    depth: str = "working"
    teaching_format: str = "plain_explanation"
    modality: str = "prose"
    key_takeaway: str = ""
    rejected_visual: str | None = None     # which visual was considered but rejected + why

    def to_dict(self) -> dict:
        return {
            "persona": self.learner.persona,
            "reading_level": self.learner.reading_level,
            "depth": self.depth,
            "teaching_format": self.teaching_format,
            "modality": self.modality,
            "assumptions": self.learner.assumptions,
        }


# ── Learner profile (from L2/L4 memory + preferences) ─────────────────────────

def learner_from_profile(profile: dict, language: str) -> LearnerProfile:
    prefs = (profile or {}).get("preferences", {}) or {}
    occupation = (profile or {}).get("occupation", "") or ""
    assumptions: list[str] = []

    persona = prefs.get("persona")
    if not persona:
        if re.search(r"student|class \d+|exam|board", occupation, re.IGNORECASE):
            persona = "student"
        elif occupation:
            persona = "professional_task"
        else:
            persona = "general"
            assumptions.append("assumed a general audience (no persona in profile)")

    reading_level = prefs.get("reading_level")
    if not reading_level:
        reading_level = "simple" if persona in ("student", "general") else "standard"
        assumptions.append(f"assumed '{reading_level}' reading level")

    return LearnerProfile(
        persona=persona,
        prior_knowledge=prefs.get("prior_knowledge", "unknown"),
        goal=prefs.get("goal", "understand"),
        language=prefs.get("language_variant", language),
        reading_level=reading_level,
        assumptions=assumptions,
    )


# ── Modality selection (prose-first; escalate only when it carries meaning) ────

def _choose_modality(query: str, domain: str, persona: str, prefs: dict) -> tuple[str, str | None]:
    q = query.lower()
    # Explicit preference wins.
    if prefs.get("modality") in MODALITIES:
        return prefs["modality"], None

    # A mind map / brainstorm board are their OWN card formats now — match them BEFORE the
    # generic diagram catch so an explicit request lands on the right renderer.
    if re.search(r"\bmind ?maps?\b", q):
        return "mindmap", None
    if re.search(r"\b(white ?board|brainstorm|sticky ?notes?|ideas? ?board|board of ideas)\b", q):
        return "whiteboard", None

    # EXPLICIT user request for a visual ALWAYS wins — if the user asks to "explain with
    # graphs / a diagram / visually / a picture / a chart / a flowchart", give them a diagram.
    # (Videos & images are added separately as study resources, so a request for them still
    # returns a diagram here to accompany the explanation.)
    if re.search(r"\b(diagram|flow ?charts?|graphs?|charts?|visual(?:ly|i[sz]e|isation|ization)?|"
                 r"picture|image|illustrat|infographic|draw|schematic)\b", q):
        return "diagram", None

    if re.search(r"\bcompare|versus|\bvs\b|difference between\b", q):
        return "comparison_table", None
    if re.search(r"\bstep|how (do|to)|process|procedure|apply\b", q):
        return "step_cards", None
    if re.search(r"\btimeline|roadmap|schedule|plan over\b", q) or (domain == "career" and "roadmap" in q):
        return "timeline", None
    if re.search(r"\bnear me|location|where is|route|map\b", q):
        return "map", None
    if re.search(r"\bcalculat|emi|eligibility|how much (tax|interest)\b", q):
        return "interactive_widget", None
    # Conceptual explanations a diagram genuinely helps with: how things work, relationships,
    # flows, stages/phases, cycles, structures — common in study/learning questions.
    if re.search(r"\bhow does .* work|relationship|\bflow\b|architecture|stages?|phases?|"
                 r"\bcycle\b|life ?cycle|structure of|components? of|types? of\b", q):
        return "diagram", None
    return "prose", None


def _choose_depth(query: str, goal: str) -> str:
    q = query.lower()
    if re.search(r"\bin detail|deeply|master|thorough|everything about\b", q) or goal == "master":
        return "mastery"
    if re.search(r"\bquick|briefly|in short|tl;?dr|just tell me\b", q):
        return "quick"
    return "working"


def _choose_format(query: str, persona: str, domain: str) -> str:
    q = query.lower()
    if persona == "mentee":
        return "socratic"
    if re.search(r"\bcompare|versus|difference\b", q):
        return "contrast"
    if re.search(r"\bexample|calculate|worked\b", q) or domain in ("student", "finance"):
        return "worked_example"
    if domain in ("student", "general", "health"):
        return "concrete_first"
    return "plain_explanation"


def build_explanation_plan(query: str, domain: str, profile: dict, language: str) -> ExplanationPlan:
    """Deterministic, offline explanation planning (no LLM needed)."""
    learner = learner_from_profile(profile, language)
    prefs = (profile or {}).get("preferences", {}) or {}
    modality, rejected = _choose_modality(query, domain, learner.persona, prefs)
    depth = _choose_depth(query, learner.goal)
    fmt = _choose_format(query, learner.persona, domain)

    plan = ExplanationPlan(
        learner=learner, depth=depth, teaching_format=fmt, modality=modality,
        rejected_visual=rejected,
    )
    EXPLANATION_MODALITY_TOTAL.labels(modality=modality).inc()
    EXPLANATION_DEPTH_TOTAL.labels(depth=depth).inc()
    if rejected:
        log.info("visual_rejected", reason=rejected, query_preview=query[:60])
    log.info("explanation_planned", modality=modality, depth=depth, teaching_format=fmt,
             persona=learner.persona, reading_level=learner.reading_level)
    return plan


# ── Prompt injection + card enrichment ────────────────────────────────────────

def synthesis_directive(plan: ExplanationPlan) -> str:
    """A block appended to the generation system prompt to steer HOW to explain."""
    lvl = {"simple": "short sentences, everyday words, one concrete example",
           "standard": "clear sentences, some domain terms explained",
           "expert": "precise, technical vocabulary is fine"}[plan.learner.reading_level]
    depth = {"quick": "answer briefly; offer to go deeper",
             "working": "give a working understanding with an example",
             "mastery": "explain thoroughly with the underlying reasoning"}[plan.depth]
    return (
        f"\n\nEXPLANATION STYLE (adapt HOW you explain so the user truly UNDERSTANDS):\n"
        f"- Audience: {plan.learner.persona}; reading level: {plan.learner.reading_level} "
        f"({lvl}).\n- Depth: {plan.depth} — {depth}.\n"
        f"- Teaching format: {plan.teaching_format} (concrete before abstract).\n"
        f"- STRUCTURE for understanding: open with a one-line plain-language answer; then a "
        f"real, relatable example or analogy; then the 'why it matters' / how it's used; keep "
        f"paragraphs short and use bullets/numbered steps for anything with parts or a sequence.\n"
        f"- Define any unavoidable jargon in-line, in brackets, the first time it appears.\n"
        f"- Prefer showing over telling: if a comparison, sequence, or relationship is involved, "
        f"lay it out as a table/steps/diagram rather than dense prose.\n"
        f"- End with one clear key takeaway. Never exceed what was asked; offer the next level."
    )


# ── Modality → card directive ─────────────────────────────────────────────────
# When the planner picks a visual modality, tell the model EXACTLY how to shape the
# card so the frontend can render it. Every visual card must ALSO fill `summary` with
# the plain-text explanation, so the answer stays fully readable even if the visual is
# empty or unsupported. Shapes here match the frontend card renderers 1:1.
_MODALITY_CARD_SCHEMAS: dict[str, str] = {
    "comparison_table": (
        '"cardType":"comparison_table" and '
        '"comparison_table":{"columns":["Option","Cost","Time","Best for"],'
        '"rows":[{"Option":"…","Cost":"…","Time":"…","Best for":"…"}]}'
    ),
    "timeline": (
        '"cardType":"timeline" and '
        '"timeline":[{"date":"Step/When","title":"…","description":"…"}]'
    ),
    "diagram": (
        '"cardType":"diagram" and '
        '"diagram":{"nodes":[{"id":"a","label":"…"},{"id":"b","label":"…"}],'
        '"edges":[{"from":"a","to":"b","label":"optional"}]}'
    ),
    "illustrative_diagram": (
        '"cardType":"diagram" and '
        '"diagram":{"nodes":[{"id":"a","label":"…"}],"edges":[{"from":"a","to":"b"}]}'
    ),
    "map": (
        '"cardType":"map" and '
        '"map_data":{"center":[lat,lng],"zoom":12,'
        '"markers":[{"lat":0.0,"lng":0.0,"label":"…","description":"…"}]} '
        "(only if you know real coordinates — otherwise use a normal answer)"
    ),
    "interactive_widget": (
        '"cardType":"interactive_widget" and '
        '"widget":{"kind":"emi|sip|simple_interest","title":"…",'
        '"inputs":[{"name":"principal","label":"…","default":100000}]}'
    ),
    "mindmap": (
        '"cardType":"mindmap" and '
        '"mindmap_nodes":[{"id":"root","label":"Central topic","connections":["a","b"]},'
        '{"id":"a","label":"Branch A","connections":[]},{"id":"b","label":"Branch B","connections":[]}] '
        "(the FIRST node is the centre; use 5-9 short-labelled nodes; every id referenced in "
        "connections MUST also appear as a node)"
    ),
    "whiteboard": (
        '"cardType":"whiteboard" and either '
        '"steps":[{"title":"Idea / point","desc":"one short line"}] OR '
        '"options":["idea one","idea two","idea three"] '
        "(each becomes a sticky note — use for a brainstorm / idea board / a set of parallel points)"
    ),
}


def modality_directive(plan: ExplanationPlan) -> str:
    """Steer the generation toward the card type the planner chose (visual modalities
    only). Prose / step_cards are already handled by the domain prompts, so they add
    nothing here."""
    schema = _MODALITY_CARD_SCHEMAS.get(plan.modality)
    if not schema:
        return ""
    return (
        f"\n\nPREFERRED CARD FORMAT: this answer is well-suited to a **{plan.modality}**. "
        f"If — and only if — the content genuinely fits, return that card: set {schema}. "
        "ALWAYS also fill `summary` with the full plain-text explanation, so the answer is "
        "complete on its own; the visual only supplements it. If the format does not fit, "
        "ignore this and return a normal answer card."
    )


# ── Response layout blueprint (the synthesis agent composes STRUCTURE per query type) ──
# The single directive that turns a wall of text into a rich, scannable, INTERACTIVE response:
# it gives the model a block vocabulary and a per-question-type layout, so graphs/diagrams/
# swatches/key-points/callouts land in the RIGHT sequence and place. All markers are plain-text
# (no quotes/braces) so they never break the card JSON.
_LAYOUT_DIRECTIVE = (
    "\n\nCOMPOSE A RICH, SCANNABLE RESPONSE — NEVER a wall of text. Break the answer into SHORT "
    "prose (1-3 sentences per paragraph) plus interactive blocks placed exactly where they help. "
    "Choose the STRUCTURE that fits the question type:\n"
    "- Concept / 'how X works': one-line answer → [[diagram: A -> B -> C]] of the real flow → "
    "3-5 [[keypoints: …]] → a [[callout:tip: …]].\n"
    "- Choose / recommend / 'which should I…' — INCLUDING colours, products, options: one-line "
    "framing → for COLOURS give real swatches [[swatches: Sky Blue=#87CEEB; Sage=#9CAF88; …]]; for "
    "other choices short labelled options or a comparison → [[keypoints: pick X when…; pick Y "
    "when…]] → [[callout:tip: …]].\n"
    "- Compare A vs B: a comparison_table card → [[keypoints: …]] of pros/cons → "
    "[[callout:key: your recommendation]].\n"
    "- How-to / steps: numbered steps → [[callout:warning: common pitfall]] → [[keypoints: …]].\n"
    "- Data / numbers / prices: [[stats: Label=Value; Label=Value]] tiles and/or "
    "[[chart: bar | Title | a,b | 1,2]] → 1-2 lines of context → [[callout:note: source/caveat]].\n"
    "- Simple fact: a direct 2-4 sentence answer; add ONE block only if it truly helps.\n"
    "- CONCRETE subject (a place, monument, animal, plant, food, object, product, real-world "
    "thing): include a real PHOTO with ![caption](img://the subject) so the user can SEE it, "
    "alongside the explanation.\n\n"
    "BLOCK SYNTAX (each on its own line; plain text, NO quotes or braces so the JSON never breaks; "
    "never use ``` code fences for a visual):\n"
    "  [[keypoints: point one; point two; point three]]\n"
    "  [[callout:tip|note|warning|success|key: a short highlighted message]]\n"
    "  [[stats: Label=Value; Label=Value]]\n"
    "  [[swatches: Name=#hex; Name=#hex]]   (real colours — use for palettes/colour advice)\n"
    "  [[diagram: A -> B -> C]]   (branches: A -> B; A -> C)\n"
    "  [[chart: bar|line|pie | Title | comma labels | comma values]]   (only real numbers)\n"
    "  ![short caption](img://2-5 focused search words)\n"
    "Use 2-4 blocks in a normal answer (more in a rich one), and make it colourful and enjoyable "
    "to read. Keep the JSON valid: blocks live INSIDE the `summary` string as plain text."
)


def layout_directive() -> str:
    """The block vocabulary + per-question-type layout the synthesis agent follows."""
    return _LAYOUT_DIRECTIVE


def _explain_differently_options(language: str) -> list[str]:
    return ["simpler", "deeper", "with_example", f"in_{language.split('+')[0]}"]


def enrich_card(card: dict, plan: ExplanationPlan, query: str, domain: str,
                is_trivial: bool = False) -> dict:
    """Attach adaptive-explanation affordances to a generated card (declarative)."""
    card["depth"] = plan.depth
    card["teaching_format"] = plan.teaching_format
    if plan.learner.assumptions:
        card.setdefault("assumptions", plan.learner.assumptions)

    # key_takeaway: prefer a model-provided one, else derive from the summary.
    if not card.get("key_takeaway"):
        summary = (card.get("summary") or "").strip()
        if summary:
            first = re.split(r"(?<=[.!?।])\s+", summary)[0]
            card["key_takeaway"] = first[:200]

    if not is_trivial:
        card["explain_differently"] = _explain_differently_options(plan.learner.language or card.get("language", "en"))
        # A light, skippable self-check — students get a question.
        if plan.learner.persona == "student" and not card.get("understanding_check"):
            card["understanding_check"] = "Want a quick self-check question to test your understanding?"
    return card
