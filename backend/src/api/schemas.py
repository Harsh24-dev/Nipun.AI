"""Shared Pydantic schemas used across API routers."""

from typing import Any, Literal

from pydantic import BaseModel

from src.core.logging import get_logger

log = get_logger("api.schemas")

# ── ResponseCard — matches the frontend ResponseCard TypeScript interface ──────

CardType = Literal[
    "answer", "step_action", "plan", "document", "price_table",
    "weather", "scheme_list", "clarify", "whiteboard", "browser",
    "mindmap", "timeline", "code_editor", "error",
    # adaptive-explanation declarative modalities
    "diagram", "illustrative_diagram", "comparison_table", "map", "interactive_widget",
    # rich media (rendered by the frontend Video/Book cards)
    "video", "book",
]


class SourceItem(BaseModel):
    text: str
    url: str | None = None


class StepItem(BaseModel):
    title: str
    desc: str
    duration: str | None = None
    status: Literal["pending", "active", "done"] = "pending"


class PriceItem(BaseModel):
    crop: str
    price: str
    change: Literal["up", "down", "flat"] = "flat"
    rate: str


class ForecastDay(BaseModel):
    day: str
    temp: str
    condition: str


class WeatherData(BaseModel):
    temp: str
    condition: str
    forecast: list[ForecastDay] = []
    alerts: list[str] | None = None


class SchemeItem(BaseModel):
    name: str
    eligible: bool
    benefit: str
    criteria: str
    link: str | None = None


class MindMapNode(BaseModel):
    id: str
    label: str
    x: float
    y: float
    connections: list[str] = []


class FormField(BaseModel):
    name: str
    label: str
    type: Literal["text", "number", "select", "multiselect"] = "text"
    options: list[str] | None = None
    required: bool = True
    placeholder: str | None = None


class ClarifyForm(BaseModel):
    """Typed form carried by a `clarify` card — asks the user for the specific details
    needed to answer well. Answers come back in the next request's `clarifications`."""
    submitLabel: str = "Submit"
    fields: list[FormField] = []


class ResponseCard(BaseModel):
    cardType: CardType = "answer"
    language: str = "en"
    title: str
    summary: str | None = None

    # Conditional by cardType
    steps: list[StepItem] | None = None
    plan_rows: list[dict[str, Any]] | None = None
    plan_cols: list[str] | None = None
    prices: list[PriceItem] | None = None
    weather: WeatherData | None = None
    schemes: list[SchemeItem] | None = None
    options: list[str] | None = None
    code: str | None = None
    codeLanguage: str | None = None
    mindmap_nodes: list[MindMapNode] | None = None
    url: str | None = None

    # Ask-back clarification (cardType == "clarify") — a typed form the user fills in.
    form: ClarifyForm | None = None

    disclaimer: str | None = None
    sources: list[SourceItem] | None = None

    # Verification & safety
    confidence: float | None = None        # calibrated reliability score 0..1
    abstained: bool | None = None          # True when GROUNDED-OR-ABSTAIN abstained
    safety_tag: str | None = None          # set when a safe-path handler produced this card
    # DELIVER-WITH-SCORE — the multi-signal reliability verdict (see src/safety/scoring.py).
    # The answer is always delivered; the UI badges it and warns when `warn` is set.
    reliability: dict | None = None        # {score, band, label, warn, applicable, signals, reasons, unsupported_claims}
    low_confidence: bool | None = None     # flat mirror of reliability.warn for minimal clients

    # Adaptive-explanation synthesis — all declarative for the frontend
    key_takeaway: str | None = None        # the one thing the user must not miss
    explain_differently: list[str] | None = None   # simpler | deeper | with_example | in_<lang>
    understanding_check: str | None = None # optional light, skippable self-check question
    depth: str | None = None               # quick | working | mastery
    teaching_format: str | None = None     # analogy | worked_example | concrete_first | ...
    diagram: dict | None = None            # declarative diagram spec {nodes, edges}
    map_data: dict | None = None           # declarative map spec {center, zoom, markers}
    widget: dict | None = None             # declarative interactive widget spec {kind, inputs}
    comparison_table: dict | None = None   # declarative table spec {columns, rows}
    timeline: list[dict] | None = None     # declarative timeline [{date, title, description}]
    # Rich media
    video_url: str | None = None           # cardType == "video" — YouTube/Vimeo/mp4 link
    book: dict | None = None               # cardType == "book" — {title, author, content, chapters}

    # Pass-through extras (correlation_id, domain-specific fields)
    model_config = {"extra": "allow"}


class ErrorDetail(BaseModel):
    code: str
    message: str
    correlation_id: str | None = None

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "code": "INVALID_TOKEN",
                    "message": "Token signature verification failed",
                    "correlation_id": "550e8400-e29b-41d4-a716-446655440000",
                }
            ]
        }
    }


class ErrorResponse(BaseModel):
    error: ErrorDetail

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "error": {
                        "code": "INVALID_TOKEN",
                        "message": "Token signature verification failed",
                        "correlation_id": "550e8400-e29b-41d4-a716-446655440000",
                    }
                }
            ]
        }
    }


class RateLimitErrorDetail(BaseModel):
    code: str
    message: str
    message_en: str
    correlation_id: str | None = None


class RateLimitErrorResponse(BaseModel):
    detail: RateLimitErrorDetail

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "detail": {
                        "code": "LLM_RATE_LIMITED",
                        "message": "बहुत अनुरोध आए। 1 मिनट बाद प्रयास करें।",
                        "message_en": "Too many requests. Please wait 1 minute.",
                        "correlation_id": "550e8400-e29b-41d4-a716-446655440000",
                    }
                }
            ]
        }
    }


log.debug("api_schemas_loaded", card_types=len(CardType.__args__))
