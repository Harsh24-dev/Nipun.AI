import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from src.api.deps import get_current_user
from src.api.schemas import ErrorResponse
from src.db.postgres import execute

log = structlog.get_logger("api.feedback")
router = APIRouter()


class FeedbackRequest(BaseModel):
    task_id: str | None = Field(
        None,
        description="UUID of the agent task to rate (optional).",
        examples=["661f9511-f3ac-52e5-b827-557766551111"],
    )
    correlation_id: str | None = Field(
        None,
        description="Correlation ID returned in the `/query` response.",
        examples=["550e8400-e29b-41d4-a716-446655440000"],
    )
    rating: int = Field(
        ...,
        ge=-1,
        le=1,
        description="`-1` = thumbs down · `0` = neutral · `+1` = thumbs up",
        examples=[1],
    )
    comment: str | None = Field(
        None,
        max_length=500,
        description="Optional free-text comment (max 500 characters).",
        examples=["Very helpful answer about PM Kisan!"],
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "correlation_id": "550e8400-e29b-41d4-a716-446655440000",
                    "rating": 1,
                    "comment": "Very helpful answer about PM Kisan!",
                }
            ]
        }
    }


class FeedbackResponse(BaseModel):
    status: str = Field(..., description="Always `ok` on success.")

    model_config = {"json_schema_extra": {"examples": [{"status": "ok"}]}}


@router.post(
    "/feedback",
    response_model=FeedbackResponse,
    responses={
        200: {"description": "Feedback recorded"},
        401: {
            "description": "Missing or invalid Bearer token",
            "model": ErrorResponse,
        },
        422: {"description": "Request body validation error"},
    },
    summary="Submit feedback",
    description=(
        "Record a thumbs-up (`+1`), thumbs-down (`-1`), or neutral (`0`) rating for a response. "
        "At least one of `task_id` or `correlation_id` should be provided to link the rating to a specific response."
    ),
)
async def submit_feedback(
    request: FeedbackRequest,
    user: dict = Depends(get_current_user),
) -> FeedbackResponse:
    user_id = user["user_id"]
    await execute(
        """
        INSERT INTO feedback (user_id, task_id, correlation_id, rating, comment)
        VALUES ($1::uuid, $2::uuid, $3, $4, $5)
        """,
        user_id,
        request.task_id,
        request.correlation_id,
        request.rating,
        request.comment,
    )
    log.info(
        "feedback_submitted",
        user_id=user_id,
        rating=request.rating,
        correlation_id=request.correlation_id,
    )
    # Relearn the user's preference vector from their feedback (best-effort).
    try:
        from src.synthesis.preferences import learn_preferences
        await learn_preferences(user_id)
    except Exception as exc:
        log.debug("preference_learning_skipped", error=str(exc))
    return FeedbackResponse(status="ok")


class ExplainDifferentlyRequest(BaseModel):
    mode: str = Field(..., description="simpler | deeper | with_example | in_<language>")
    correlation_id: str | None = Field(None, description="Correlation ID of the original response.")


@router.post("/explain-differently", summary="Track an explain-differently click")
async def explain_differently(
    request: ExplainDifferentlyRequest,
    user: dict = Depends(get_current_user),
) -> dict:
    """
    Record that the user asked for the answer to be explained differently. The frontend
    then re-issues a `/query` with the adjusted intent; this only tracks the signal.
    """
    from src.core.metrics import EXPLAIN_DIFFERENTLY_CLICKS

    mode = request.mode if request.mode.startswith("in_") else request.mode
    label = "in_language" if mode.startswith("in_") else mode
    EXPLAIN_DIFFERENTLY_CLICKS.labels(mode=label).inc()
    log.info("explain_differently", user_id=user["user_id"], mode=request.mode,
             correlation_id=request.correlation_id)
    return {"status": "ok"}
