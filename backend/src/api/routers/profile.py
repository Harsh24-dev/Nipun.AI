"""User profile — get and update the current user's profile."""

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.api.deps import get_current_user
from src.db.postgres import execute, fetchrow
from src.memory.session import invalidate_profile

log = structlog.get_logger("api.profile")
router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────
# Stable identity/preference fields only. One-off, query-specific details (land size,
# soil, income band, etc.) are NOT stored here — they are asked for at answer time via
# a clarify form (see src/agents/clarify.py) and used just for that turn.

class ProfileOut(BaseModel):
    id: str
    name: str | None
    email: str | None
    phone: str | None
    language: str
    state: str | None
    district: str | None
    occupation: str | None
    bio: str | None
    interests: list[str]
    ai_model: str
    theme: str
    role: str
    is_active: bool
    created_at: str
    # Appearance / UI + onboarding preferences (synced across devices).
    ui_preset: str
    motif: str
    text_scale: str
    high_contrast: bool
    voice_enabled: bool
    festive_accents: bool
    age_band: str | None
    gender: str | None
    languages_known: list[str]
    onboarded: bool


class UpdateProfileRequest(BaseModel):
    name: str | None = Field(None, max_length=100)
    language: str | None = Field(None, description="ISO 639-1 language code")
    state: str | None = Field(None, max_length=100)
    district: str | None = Field(None, max_length=100)
    occupation: str | None = Field(None, max_length=100)
    bio: str | None = Field(None, max_length=500)
    interests: list[str] | None = None
    ai_model: str | None = Field(None, pattern="^(auto|speed|deep)$")
    theme: str | None = Field(None, max_length=50)
    # Appearance / UI + onboarding preferences.
    ui_preset: str | None = Field(None, max_length=50)
    motif: str | None = Field(None, max_length=50)
    text_scale: str | None = Field(None, pattern="^(S|M|L|XL)$")
    high_contrast: bool | None = None
    voice_enabled: bool | None = None
    festive_accents: bool | None = None
    age_band: str | None = Field(None, max_length=20)
    gender: str | None = Field(None, max_length=40)
    languages_known: list[str] | None = None
    onboarded: bool | None = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get(
    "/profile",
    response_model=ProfileOut,
    summary="Get profile",
    description="Return the authenticated user's full profile.",
    tags=["profile"],
)
async def get_profile(user: dict = Depends(get_current_user)) -> ProfileOut:
    log.debug("profile_fetch", user_id=user["user_id"])
    row = await fetchrow(
        """
        SELECT id, name, email, phone, language, state, district, occupation,
               bio, interests, ai_model, theme, role, is_active, created_at,
               ui_preset, motif, text_scale, high_contrast, voice_enabled,
               festive_accents, age_band, gender, languages_known, onboarded
        FROM users WHERE id = $1::uuid
        """,
        user["user_id"],
    )
    if not row:
        log.warning("profile_not_found", user_id=user["user_id"])
        raise HTTPException(status_code=404, detail="User not found.")
    return ProfileOut(
        id=str(row["id"]),
        name=row["name"],
        email=row["email"],
        phone=row["phone"],
        language=row["language"],
        state=row["state"],
        district=row["district"],
        occupation=row["occupation"],
        bio=row["bio"],
        interests=list(row["interests"] or []),
        ai_model=row["ai_model"],
        theme=row["theme"],
        role=row["role"],
        is_active=row["is_active"],
        created_at=row["created_at"].isoformat(),
        ui_preset=row["ui_preset"],
        motif=row["motif"],
        text_scale=row["text_scale"],
        high_contrast=row["high_contrast"],
        voice_enabled=row["voice_enabled"],
        festive_accents=row["festive_accents"],
        age_band=row["age_band"],
        gender=row["gender"],
        languages_known=list(row["languages_known"] or []),
        onboarded=bool(row["onboarded"]),
    )


@router.patch(
    "/profile",
    response_model=ProfileOut,
    summary="Update profile",
    description="Update the authenticated user's profile. Only provided fields are changed.",
    tags=["profile"],
)
async def update_profile(
    req: UpdateProfileRequest,
    user: dict = Depends(get_current_user),
) -> ProfileOut:
    user_id = user["user_id"]
    field_map = {
        "name": req.name,
        "language": req.language,
        "state": req.state,
        "district": req.district,
        "occupation": req.occupation,
        "bio": req.bio,
        "interests": req.interests,
        "ai_model": req.ai_model,
        "theme": req.theme,
        "ui_preset": req.ui_preset,
        "motif": req.motif,
        "text_scale": req.text_scale,
        "high_contrast": req.high_contrast,
        "voice_enabled": req.voice_enabled,
        "festive_accents": req.festive_accents,
        "age_band": req.age_band,
        "gender": req.gender,
        "languages_known": req.languages_known,
        "onboarded": req.onboarded,
    }
    updates = [(col, val) for col, val in field_map.items() if val is not None]

    if updates:
        set_clause = ", ".join(f"{col} = ${i + 2}" for i, (col, _) in enumerate(updates))
        params: list[Any] = [user_id] + [val for _, val in updates]
        await execute(
            f"UPDATE users SET {set_clause}, updated_at = NOW() WHERE id = $1::uuid",
            *params,
        )
        # DB is the source of truth — drop the stale cache so the next query reloads it.
        await invalidate_profile(user_id)
        log.info("profile_updated", user_id=user_id, fields=[c for c, _ in updates])

    return await get_profile(user)
