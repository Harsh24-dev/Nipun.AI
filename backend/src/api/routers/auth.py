import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import structlog
import bcrypt
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr, Field

from src.config import settings
from src.db.postgres import execute, fetchrow

log = structlog.get_logger("api.auth")
router = APIRouter()


# ── helpers ───────────────────────────────────────────────────────────────────

def _hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def _verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def _create_token(user_id: str, email: str, name: str | None) -> str:
    from jose import jwt

    now = datetime.now(tz=timezone.utc)
    payload = {
        "sub": user_id,
        "email": email,
        "name": name or "",
        "iat": now,
        "exp": now + timedelta(hours=settings.JWT_EXPIRY_HOURS),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


# ── schemas ───────────────────────────────────────────────────────────────────

class SignupRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1)


class AuthResponse(BaseModel):
    token: str
    user: dict


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    new_password: str = Field(..., min_length=6, max_length=128)


class MessageResponse(BaseModel):
    message: str


# ── endpoints ─────────────────────────────────────────────────────────────────

@router.post(
    "/auth/signup",
    response_model=AuthResponse,
    summary="Sign up",
    description="Create a new account with name, email, and password. Returns a Bearer JWT.",
    tags=["auth"],
)
async def signup(req: SignupRequest) -> AuthResponse:
    log.info("signup_attempt", name=req.name)
    existing = await fetchrow("SELECT id FROM users WHERE email = $1", req.email)
    if existing:
        log.warning("signup_rejected_duplicate_email", name=req.name)
        raise HTTPException(status_code=409, detail="An account with this email already exists.")

    password_hash = await asyncio.to_thread(_hash_password, req.password)
    user_id = str(uuid.uuid4())

    await execute(
        """
        INSERT INTO users (id, name, email, password_hash, language, created_at, updated_at)
        VALUES ($1::uuid, $2, $3, $4, $5, NOW(), NOW())
        """,
        user_id,
        req.name,
        req.email,
        password_hash,
        settings.DEFAULT_LANGUAGE,
    )

    log.info("signup_success", user_id=user_id, name=req.name, language=settings.DEFAULT_LANGUAGE)
    token = _create_token(user_id, req.email, req.name)
    return AuthResponse(token=token, user={"id": user_id, "email": req.email, "name": req.name})


@router.post(
    "/auth/login",
    response_model=AuthResponse,
    summary="Log in",
    description="Authenticate with email and password. Returns a Bearer JWT.",
    tags=["auth"],
)
async def login(req: LoginRequest) -> AuthResponse:
    log.info("login_attempt")
    row = await fetchrow(
        "SELECT id, name, email, password_hash FROM users WHERE email = $1", req.email
    )
    if not row or not row["password_hash"]:
        log.warning("login_failed_user_not_found")
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    if not await asyncio.to_thread(_verify_password, req.password, row["password_hash"]):
        log.warning("login_failed_wrong_password", user_id=str(row["id"]))
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    token = _create_token(str(row["id"]), row["email"], row["name"])
    log.info("login_success", user_id=str(row["id"]), name=row["name"])
    return AuthResponse(
        token=token,
        user={"id": str(row["id"]), "email": row["email"], "name": row["name"] or ""},
    )


@router.post(
    "/auth/reset-password",
    response_model=MessageResponse,
    summary="Reset password",
    description="Update password directly by providing email and new password (dev mode — no OTP).",
    tags=["auth"],
)
async def reset_password(req: ResetPasswordRequest) -> MessageResponse:
    log.info("password_reset_attempt")

    # SECURITY: this endpoint resets a password given only {email, new_password},
    # with NO proof the caller owns the account → account takeover. Outside of local
    # development it MUST be refused until a real verified-token/OTP flow exists.
    #
    # TODO(auth): implement a proper self-service reset:
    #   1. POST /auth/forgot-password {email} → generate a single-use, short-TTL,
    #      cryptographically-random token, store its hash server-side, and EMAIL the
    #      token/link to the account's verified address (never return it in the response).
    #   2. POST /auth/reset-password {token, new_password} → verify the token hash + TTL,
    #      then update the password and invalidate the token.
    # Do NOT re-enable the no-proof flow below in staging/production.
    if settings.APP_ENV != "development":
        log.warning("password_reset_refused_no_verified_flow", app_env=settings.APP_ENV)
        raise HTTPException(
            status_code=403,
            detail=(
                "Unauthenticated password reset is disabled. A verified emailed-token/OTP "
                "reset flow is required and not yet implemented."
            ),
        )

    row = await fetchrow("SELECT id FROM users WHERE email = $1", req.email)
    if not row:
        log.warning("password_reset_user_not_found")
        raise HTTPException(status_code=404, detail="User not found.")

    password_hash = await asyncio.to_thread(_hash_password, req.new_password)
    await execute(
        "UPDATE users SET password_hash = $1, updated_at = NOW() WHERE email = $2",
        password_hash,
        req.email,
    )

    log.info("password_reset_success", user_id=str(row["id"]))
    return MessageResponse(message="Password updated successfully.")
