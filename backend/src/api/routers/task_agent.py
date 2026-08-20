"""
IPA task-agent API.

  POST /task/start           → plan a task (checklist + consolidated form) and return a task_id.
  WS   /ws/task/{task_id}    → live run: streams screenshots/steps/actions, receives controls
                               (submit answers → start, pause, resume, stop, I've-done-it).

The browser session is pinned to the worker that runs it, so the WS for a task must reach the
same worker (trivially true for a single-worker dev run).
"""

from __future__ import annotations

import asyncio
import hashlib

import structlog
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from src.api.deps import get_current_user
from src.ipa.controller import run_in_worker
from src.ipa.planner import plan_task
from src.ipa.schemas import RunStatus, event
from src.ipa.session import create_session, load_session, persist_session

log = structlog.get_logger("api.task_agent")
router = APIRouter()

# Keep strong refs to background run tasks so the loop doesn't garbage-collect them mid-run.
_RUNS: set[asyncio.Task] = set()

# ── STICKY-ROUTING REQUIREMENT (read before changing control flow) ────────────────────────────
# The live browser (a Playwright Chromium page + its Proactor agent thread) exists ONLY in the
# memory of the uvicorn worker that launched the run — it CANNOT be shared across processes. So:
#   • The WebSocket for a task (and every control op: pause / resume / stop / take-over /
#     I've-done-it) MUST reach the SAME worker that owns the browser, or it will hit a hydrated
#     session that has no `browser`/`agent_loop` and the command will silently no-op.
#   • Deployments MUST route /ws/task/{task_id} with sticky affinity by task_id (or run a single
#     worker). Session METADATA (plan / answers / status) is mirrored to Redis so any worker can
#     answer /task/start idempotency and reject a duplicate launch, but the ACTING browser stays
#     put. When a control op lands on a non-owning worker we detect it (no local browser) and tell
#     the client instead of pretending it worked — see task_socket.
#
# Terminal statuses — a run in one of these is finished and a fresh /task/start may proceed.
_TERMINAL = {RunStatus.DONE, RunStatus.FAILED, RunStatus.STOPPED}
# Idempotency window for dedup of (user_id, goal). Rapid double-taps / retries within this window
# return the EXISTING task instead of minting a new uuid4 and launching a second browser.
_IDEM_WINDOW_S = 120
_IDEM_KEY = "nipun:task_idem:{user_id}:{goal_hash}"


class TaskStartRequest(BaseModel):
    goal: str = Field(..., min_length=3, max_length=1000)


def _idem_key(user_id: str, goal: str) -> str:
    gh = hashlib.sha256(" ".join((goal or "").lower().split()).encode("utf-8")).hexdigest()[:16]
    return _IDEM_KEY.format(user_id=user_id, goal_hash=gh)


@router.post("/task/start", summary="Plan a browser task and get a live-run task_id")
async def start_task(req: TaskStartRequest, user: dict = Depends(get_current_user)) -> dict:
    """Create a run session and produce its checklist + consolidated form. Nothing runs yet —
    the user reviews the plan, fills the form, then execution starts over the WebSocket.

    IDEMPOTENT: a repeat of the same (user_id, goal) within a short window returns the EXISTING
    task (if it is still alive / not terminal) instead of minting a new uuid4 and — worse — later
    launching a second live browser for what the user thinks is one task."""
    user_id = user["user_id"]
    key = _idem_key(user_id, req.goal)

    # Dedup: if a recent, still-active task for this exact goal exists, hand it back unchanged.
    try:
        from src.db.redis import get_json
        prior = await get_json(key)
    except Exception:
        prior = None
    if prior and prior.get("task_id"):
        existing = await load_session(prior["task_id"])
        if existing is not None and existing.user_id == user_id and existing.status not in _TERMINAL:
            log.info("task_start_deduped", task_id=existing.task_id, user_id=user_id,
                     status=existing.status.value)
            return {"task_id": existing.task_id,
                    "plan": existing.plan.to_dict() if existing.plan else None,
                    "status": existing.status.value, "deduped": True}

    session = create_session(user_id=user_id, goal=req.goal)
    profile = user.get("profile", {}) if isinstance(user, dict) else {}
    session.plan = await plan_task(req.goal, profile, correlation_id=session.task_id)
    session.status = RunStatus.AWAITING_INPUT
    await persist_session(session)   # so the WebSocket can find it even after a reload / on another worker
    try:
        from src.db.redis import set_json
        await set_json(key, {"task_id": session.task_id}, ttl=_IDEM_WINDOW_S)
    except Exception:
        pass
    return {"task_id": session.task_id, "plan": session.plan.to_dict(),
            "status": session.status.value}


@router.websocket("/ws/task/{task_id}")
async def task_socket(websocket: WebSocket, task_id: str):
    await websocket.accept()
    try:
        auth = await websocket.receive_json()
        from src.api.deps import validate_token
        try:
            user = validate_token(auth.get("token", ""))
        except Exception:
            await websocket.send_json({"type": "error", "message": "UNAUTHORIZED"})
            await websocket.close(code=1008)
            return

        session = await load_session(task_id)
        if session is None or session.user_id != user["user_id"]:
            await websocket.send_json({"type": "error", "message": "Task not found."})
            await websocket.close(code=1008)
            return

        # Send the plan + any events already produced (reconnect-friendly).
        await websocket.send_json(event("plan", task_id, plan=session.plan.to_dict() if session.plan else None,
                                        status=session.status.value))
        for ev in list(session.history):
            await websocket.send_json(ev)

        # A run is "already launched" for ANY non-initial, non-terminal status — not just RUNNING
        # (PAUSED / NEEDS_HUMAN / COMPARING / AWAITING_CHOICE all mean a browser run exists). Only
        # PLANNING / AWAITING_INPUT permit a launch. Restoring the persisted status (load_session)
        # makes this guard work across workers: a WS on a second worker sees the task is already
        # RUNNING and will NOT launch a duplicate, unstoppable browser run.
        _LAUNCHABLE = {RunStatus.PLANNING, RunStatus.AWAITING_INPUT}
        started = {"v": session.status not in _LAUNCHABLE}
        # Did WE launch the browser on THIS connection/worker? Only then can control ops reach it.
        launched_here = {"v": False}

        async def _warn_wrong_worker() -> None:
            # A control op reached a worker that does NOT hold this task's live browser (sticky
            # routing missed). We cannot pause/stop/forward-input from here — say so honestly
            # rather than silently no-op'ing.
            await websocket.send_json(event(
                "error", task_id,
                message="This control could not reach the worker running your task. Please reconnect."))

        async def pump_events():
            while True:
                ev = await session.queue.get()
                await websocket.send_json(ev)

        async def read_controls():
            while True:
                msg = await websocket.receive_json()
                action = msg.get("action")
                if action == "answers":
                    session.submit_answers(msg.get("data") or {})
                    if not started["v"]:
                        started["v"] = True
                        launched_here["v"] = True
                        # Remember this WebSocket's loop so the agent (running on its own Proactor
                        # thread) can stream events back here, then launch the run in that thread.
                        session.main_loop = asyncio.get_running_loop()
                        run_in_worker(session)
                    else:
                        # Already running (possibly on another worker) → do NOT launch a second
                        # browser for the same task; just record the (possibly updated) answers.
                        log.info("task_relaunch_suppressed", task_id=task_id,
                                 status=session.status.value)
                    continue
                # Every op below drives the LIVE run (flags polled by the agent, or the browser
                # itself). If the run was launched on ANOTHER worker we can't reach it from here —
                # warn instead of silently dropping the command (sticky routing must be fixed).
                if started["v"] and not launched_here["v"] and getattr(session, "browser", None) is None:
                    await _warn_wrong_worker()
                    continue
                if action == "pause":
                    session.pause()
                    await session.emit(event("status", task_id, status="paused"))
                elif action == "resume":
                    session.resume()
                    await session.emit(event("status", task_id, status="running"))
                elif action in ("user_click", "user_type", "user_key", "user_scroll"):
                    # Forward the user's input to the SAME server browser (remote control during a
                    # hand-off). The page lives on the agent thread's loop, so schedule it there.
                    loop = getattr(session, "agent_loop", None)
                    br = getattr(session, "browser", None)
                    d = msg.get("data") or {}
                    if loop is not None and br is not None:
                        if action == "user_click":
                            coro = br.user_click(d.get("x", 0), d.get("y", 0))
                        elif action == "user_type":
                            coro = br.user_type(d.get("text", ""))
                        elif action == "user_key":
                            coro = br.user_key(d.get("key", ""))
                        else:
                            coro = br.user_scroll(d.get("dy", 300))
                        try:
                            asyncio.run_coroutine_threadsafe(coro, loop)
                        except Exception:
                            pass
                elif action == "choose_option":
                    session.choose_option(msg.get("data") or {})
                elif action in ("human_done", "resume_from_human"):
                    session.human_finished()
                elif action == "stop":
                    session.stop()
                    await session.emit(event("status", task_id, status="stopped"))

        pe = asyncio.create_task(pump_events())
        rc = asyncio.create_task(read_controls())
        done, pending = await asyncio.wait({pe, rc}, return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
    except WebSocketDisconnect:
        log.info("task_ws_disconnected", task_id=task_id)
    except Exception as exc:
        log.error("task_ws_error", task_id=task_id, error=str(exc))
        try:
            await websocket.send_json({"type": "error", "message": str(exc)})
        except Exception:
            pass
