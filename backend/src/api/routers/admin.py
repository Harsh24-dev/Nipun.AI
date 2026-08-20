"""
Admin API — user management and admin initialisation.

POST /admin/init        Create the first admin (one-time, no auth needed)
GET  /admin/users       List all users
GET  /admin/users/{id}  Get user detail
PATCH /admin/users/{id} Update user (role, is_active, etc.)
DELETE /admin/users/{id} Deactivate user
GET  /admin/users/{id}/sessions  User's session list
POST /admin/users/{id}/reset-password  Force password reset
"""

import asyncio
import uuid
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
import bcrypt
from pydantic import BaseModel, EmailStr, Field

from src.api.deps import get_current_user, require_admin
from src.db.postgres import execute, fetch, fetchrow, fetchval

log = structlog.get_logger("api.admin")
router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────

class AdminInitRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)


class AdminInitResponse(BaseModel):
    message: str
    user_id: str


class UserSummary(BaseModel):
    id: str
    name: str | None
    email: str | None
    phone: str | None
    role: str
    is_active: bool
    language: str
    state: str | None
    occupation: str | None
    created_at: str


class UserDetail(UserSummary):
    district: str | None
    bio: str | None
    interests: list[str]
    ai_model: str
    theme: str
    session_count: int


class UpdateUserRequest(BaseModel):
    name: str | None = Field(None, max_length=100)
    role: str | None = Field(None, pattern="^(user|admin)$")
    is_active: bool | None = None
    language: str | None = None
    state: str | None = None
    occupation: str | None = None


class ForceResetRequest(BaseModel):
    new_password: str = Field(..., min_length=6, max_length=128)


class MessageResponse(BaseModel):
    message: str


class SessionSummary(BaseModel):
    id: str
    title: str | None
    language: str
    domain: str | None
    turn_count: int
    started_at: str


# ── Admin Init ────────────────────────────────────────────────────────────────

@router.post(
    "/admin/init",
    response_model=AdminInitResponse,
    summary="Initialise first admin",
    description=(
        "One-time endpoint to create the first admin user. "
        "Returns 409 if any admin already exists. No authentication required."
    ),
    tags=["admin"],
)
async def admin_init(req: AdminInitRequest) -> AdminInitResponse:
    existing_admin = await fetchval("SELECT id FROM users WHERE role = 'admin' LIMIT 1")
    if existing_admin:
        raise HTTPException(
            status_code=409,
            detail="An admin user already exists. Use the login endpoint instead.",
        )

    existing_email = await fetchrow("SELECT id FROM users WHERE email = $1", req.email)
    if existing_email:
        raise HTTPException(status_code=409, detail="An account with this email already exists.")

    user_id = str(uuid.uuid4())
    password_hash = await asyncio.to_thread(
        lambda: bcrypt.hashpw(req.password.encode(), bcrypt.gensalt()).decode()
    )

    await execute(
        """
        INSERT INTO users (id, name, email, password_hash, role, language, created_at, updated_at)
        VALUES ($1::uuid, $2, $3, $4, 'admin', 'en', NOW(), NOW())
        """,
        user_id, req.name, req.email, password_hash,
    )

    log.info("admin_created", user_id=user_id, email=req.email)
    return AdminInitResponse(message="Admin user created successfully.", user_id=user_id)


# ── User List ─────────────────────────────────────────────────────────────────

@router.get(
    "/admin/users",
    response_model=list[UserSummary],
    summary="List all users",
    description="Paginated list of all registered users. Admin only.",
    tags=["admin"],
)
async def list_users(
    limit: int = 50,
    offset: int = 0,
    role: str | None = None,
    is_active: bool | None = None,
    _: dict = Depends(require_admin),
) -> list[UserSummary]:
    conditions = []
    params: list[Any] = []
    idx = 1

    if role is not None:
        conditions.append(f"role = ${idx}")
        params.append(role)
        idx += 1
    if is_active is not None:
        conditions.append(f"is_active = ${idx}")
        params.append(is_active)
        idx += 1

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params += [limit, offset]

    rows = await fetch(
        f"""
        SELECT id, name, email, phone, role, is_active, language, state, occupation, created_at
        FROM users {where}
        ORDER BY created_at DESC
        LIMIT ${idx} OFFSET ${idx + 1}
        """,
        *params,
    )
    return [
        UserSummary(
            id=str(r["id"]),
            name=r["name"],
            email=r["email"],
            phone=r["phone"],
            role=r["role"],
            is_active=r["is_active"],
            language=r["language"],
            state=r["state"],
            occupation=r["occupation"],
            created_at=r["created_at"].isoformat(),
        )
        for r in rows
    ]


# ── User Detail ───────────────────────────────────────────────────────────────

@router.get(
    "/admin/users/{user_id}",
    response_model=UserDetail,
    summary="Get user detail",
    description="Full profile for any user. Admin only.",
    tags=["admin"],
)
async def get_user(user_id: str, _: dict = Depends(require_admin)) -> UserDetail:
    row = await fetchrow(
        """
        SELECT u.id, u.name, u.email, u.phone, u.role, u.is_active, u.language,
               u.state, u.district, u.occupation, u.bio, u.interests, u.ai_model,
               u.theme, u.created_at,
               COUNT(s.id) AS session_count
        FROM users u
        LEFT JOIN sessions s ON s.user_id = u.id
        WHERE u.id = $1::uuid
        GROUP BY u.id
        """,
        user_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="User not found.")
    return UserDetail(
        id=str(row["id"]),
        name=row["name"],
        email=row["email"],
        phone=row["phone"],
        role=row["role"],
        is_active=row["is_active"],
        language=row["language"],
        state=row["state"],
        district=row["district"],
        occupation=row["occupation"],
        bio=row["bio"],
        interests=list(row["interests"] or []),
        ai_model=row["ai_model"],
        theme=row["theme"],
        created_at=row["created_at"].isoformat(),
        session_count=int(row["session_count"]),
    )


# ── Update User ───────────────────────────────────────────────────────────────

@router.patch(
    "/admin/users/{user_id}",
    response_model=UserDetail,
    summary="Update user",
    description="Update any user's role, active status, or profile fields. Admin only.",
    tags=["admin"],
)
async def update_user(
    user_id: str,
    req: UpdateUserRequest,
    admin: dict = Depends(require_admin),
) -> UserDetail:
    row = await fetchrow("SELECT id FROM users WHERE id = $1::uuid", user_id)
    if not row:
        raise HTTPException(status_code=404, detail="User not found.")

    field_map = {
        "name": req.name,
        "role": req.role,
        "is_active": req.is_active,
        "language": req.language,
        "state": req.state,
        "occupation": req.occupation,
    }
    updates = [(col, val) for col, val in field_map.items() if val is not None]

    if updates:
        set_clause = ", ".join(f"{col} = ${i + 2}" for i, (col, _) in enumerate(updates))
        params: list[Any] = [user_id] + [val for _, val in updates]
        await execute(
            f"UPDATE users SET {set_clause}, updated_at = NOW() WHERE id = $1::uuid",
            *params,
        )
        log.info("admin_updated_user", admin_id=admin["user_id"], target_user=user_id)

    return await get_user(user_id, admin)


# ── Deactivate User ───────────────────────────────────────────────────────────

@router.delete(
    "/admin/users/{user_id}",
    response_model=MessageResponse,
    summary="Deactivate user",
    description="Soft-delete: sets is_active=false. Admin only. Cannot deactivate yourself.",
    tags=["admin"],
)
async def deactivate_user(
    user_id: str,
    admin: dict = Depends(require_admin),
) -> MessageResponse:
    if user_id == admin["user_id"]:
        raise HTTPException(status_code=400, detail="Cannot deactivate your own account.")

    row = await fetchrow("SELECT id FROM users WHERE id = $1::uuid", user_id)
    if not row:
        raise HTTPException(status_code=404, detail="User not found.")

    await execute(
        "UPDATE users SET is_active = FALSE, updated_at = NOW() WHERE id = $1::uuid",
        user_id,
    )
    log.info("user_deactivated", admin_id=admin["user_id"], target_user=user_id)
    return MessageResponse(message="User deactivated.")


# ── User Sessions ─────────────────────────────────────────────────────────────

@router.get(
    "/admin/users/{user_id}/sessions",
    response_model=list[SessionSummary],
    summary="Get user sessions",
    description="All conversation sessions for a specific user. Admin only.",
    tags=["admin"],
)
async def get_user_sessions(
    user_id: str,
    limit: int = 50,
    _: dict = Depends(require_admin),
) -> list[SessionSummary]:
    rows = await fetch(
        """
        SELECT id, title, language, domain, turn_count, started_at
        FROM sessions WHERE user_id = $1::uuid
        ORDER BY started_at DESC LIMIT $2
        """,
        user_id, limit,
    )
    return [
        SessionSummary(
            id=str(r["id"]),
            title=r["title"],
            language=r["language"],
            domain=r["domain"],
            turn_count=r["turn_count"],
            started_at=r["started_at"].isoformat(),
        )
        for r in rows
    ]


# ── Force Password Reset ──────────────────────────────────────────────────────

@router.post(
    "/admin/users/{user_id}/reset-password",
    response_model=MessageResponse,
    summary="Force password reset",
    description="Admin can set a new password for any user directly. Admin only.",
    tags=["admin"],
)
async def force_reset_password(
    user_id: str,
    req: ForceResetRequest,
    admin: dict = Depends(require_admin),
) -> MessageResponse:
    row = await fetchrow("SELECT id FROM users WHERE id = $1::uuid", user_id)
    if not row:
        raise HTTPException(status_code=404, detail="User not found.")

    password_hash = await asyncio.to_thread(
        lambda: bcrypt.hashpw(req.new_password.encode(), bcrypt.gensalt()).decode()
    )
    await execute(
        "UPDATE users SET password_hash = $1, updated_at = NOW() WHERE id = $2::uuid",
        password_hash, user_id,
    )
    log.info("admin_force_reset_password", admin_id=admin["user_id"], target_user=user_id)
    return MessageResponse(message="Password updated.")
