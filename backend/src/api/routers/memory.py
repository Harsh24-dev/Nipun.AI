"""
User memory API — view / add / edit / delete the assistant's long-term memories about you,
the way ChatGPT's "Manage memory" and Claude's memory settings work. Everything is strictly
owner-scoped: a user can only ever see or touch their own memories.
"""

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.api.deps import get_current_user
from src.memory import user_memory

log = structlog.get_logger("api.memory")
router = APIRouter(prefix="/memory", tags=["memory"])


class MemoryOut(BaseModel):
    id: str
    content: str
    kind: str
    pinned: bool
    created_at: str
    updated_at: str


class MemoryCreate(BaseModel):
    content: str = Field(..., min_length=3, max_length=500,
                         description="The fact to remember, one short sentence.",
                         examples=["Preparing for the UPSC 2026 exam"])
    kind: str = Field("fact", description="fact | preference | goal | context")
    pinned: bool = Field(False, description="Pin to always inject and never auto-evict.")


class MemoryUpdate(BaseModel):
    content: str | None = Field(None, min_length=3, max_length=500)
    pinned: bool | None = None


@router.get("", summary="List everything the assistant remembers about you")
async def list_my_memories(user=Depends(get_current_user)) -> list[MemoryOut]:
    return await user_memory.list_memories(user["user_id"])


@router.post("", summary="Add a memory", status_code=201)
async def add_my_memory(body: MemoryCreate, user=Depends(get_current_user)) -> MemoryOut:
    stored = await user_memory.add_memory(
        user_id=user["user_id"], content=body.content, kind=body.kind, pinned=body.pinned,
    )
    if not stored:
        raise HTTPException(status_code=500, detail="Could not save memory")
    # add_memory returns a compact dict; re-read for a full row on new inserts.
    for m in await user_memory.list_memories(user["user_id"]):
        if m["id"] == stored["id"]:
            return m
    raise HTTPException(status_code=500, detail="Could not save memory")


@router.patch("/{memory_id}", summary="Edit or pin a memory")
async def edit_my_memory(memory_id: str, body: MemoryUpdate, user=Depends(get_current_user)) -> dict:
    ok = await user_memory.update_memory(
        user["user_id"], memory_id, content=body.content, pinned=body.pinned,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"status": "updated", "id": memory_id}


@router.delete("/{memory_id}", summary="Forget one memory")
async def delete_my_memory(memory_id: str, user=Depends(get_current_user)) -> dict:
    ok = await user_memory.delete_memory(user["user_id"], memory_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"status": "deleted", "id": memory_id}


@router.delete("", summary="Forget everything (clear all memories)")
async def clear_my_memories(user=Depends(get_current_user)) -> dict:
    count = await user_memory.clear_memories(user["user_id"])
    log.info("memories_cleared", user_id=user["user_id"], count=count)
    return {"status": "cleared", "deleted": count}
