"""
Task-run session: state, the live control channel, and the event stream.

One TaskSession per running task. The browser agent PUSHES events (screenshots, actions, step
updates) onto an asyncio queue; the WebSocket drains it to the UI. The UI PUSHES control commands
(pause / resume / take-over / resume-from-human / stop) back, which the agent checks between steps.

In-process by design: a browser session is pinned to the worker that launched it (a Playwright
page cannot be shared across processes), so the WS for a task must land on the same worker. For a
single-worker dev run this is automatic; for multi-worker, route by sticky task_id (documented).
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field

from src.core.logging import get_ipa_logger
from src.ipa.schemas import RunStatus, TaskPlan

log = get_ipa_logger("ipa.session")


@dataclass
class TaskSession:
    task_id: str
    user_id: str
    goal: str
    status: RunStatus = RunStatus.PLANNING
    plan: TaskPlan | None = None
    answers: dict = field(default_factory=dict)      # consolidated form answers
    trace: list = field(default_factory=list)        # generalized successful actions (for recipes)
    created_at: float = field(default_factory=time.time)

    chosen_option: dict = field(default_factory=dict)   # the option the user picked to proceed on
    # The WebSocket's event loop (set when the run is launched). The browser agent runs on a
    # SEPARATE thread + Proactor loop (uvicorn's --reload loop can't spawn a browser subprocess),
    # so events are delivered back to THIS loop's queue thread-safely.
    main_loop: object = None
    agent_loop: object = None   # the agent thread's Proactor loop (to forward user clicks/keys)
    browser: object = None      # the live BrowserSession (so a hand-off can remote-control it)

    # Control flags — plain bools, polled by the agent. Deliberately NOT asyncio.Event: the agent
    # runs on a different loop/thread than the WebSocket, and an asyncio.Event set on one loop does
    # not wake a waiter on another. Bool reads/writes are atomic under the GIL, so polling is safe.
    _paused: bool = False
    _stop: bool = False
    _human_flag: bool = False
    _answers_flag: bool = False
    _choice_flag: bool = False
    # Set once the agent has typed/selected into a form field this run. The deterministic
    # final-submit guard (src.ipa.agent._is_final_submit) uses it so the NEXT click inside a
    # non-GET form is treated as its submit and handed off to the human (fail-safe).
    _form_dirty: bool = False

    # Event stream (agent → WebSocket) and a rolling log for late subscribers.
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=256))
    history: list[dict] = field(default_factory=list)

    def _put(self, ev: dict) -> None:
        try:
            self.queue.put_nowait(ev)
        except asyncio.QueueFull:
            try:
                self.queue.get_nowait()
                self.queue.put_nowait(ev)
            except Exception:
                pass

    async def emit(self, ev: dict) -> None:
        """Publish an event to the live stream. When the agent runs on a different loop (its own
        Proactor thread), deliver to the WebSocket's queue on ITS loop via call_soon_threadsafe."""
        self.history.append(ev)
        if len(self.history) > 400:
            self.history = self.history[-400:]
        loop = self.main_loop
        if loop is not None:
            loop.call_soon_threadsafe(self._put, ev)
        else:
            self._put(ev)

    # ── Control surface (called from the WebSocket handler / main loop) ─────────
    def pause(self) -> None:
        log.info("task_paused", task_id=self.task_id)
        self._paused = True

    def resume(self) -> None:
        log.info("task_resumed", task_id=self.task_id)
        self._paused = False

    def stop(self) -> None:
        log.info("task_stopped", task_id=self.task_id, status=self.status.value)
        self._stop = True
        self._paused = False
        self._human_flag = self._answers_flag = self._choice_flag = True

    def submit_answers(self, answers: dict) -> None:
        # Never log the answer VALUES (they carry the user's personal task details) — only how many.
        log.info("task_answers_submitted", task_id=self.task_id, fields=len(answers or {}))
        self.answers = answers or {}
        self._answers_flag = True

    def choose_option(self, option: dict) -> None:
        log.info("task_option_chosen", task_id=self.task_id,
                 url=str((option or {}).get("url", ""))[:120])
        self.chosen_option = option or {}
        self._choice_flag = True

    def human_finished(self) -> None:
        """User finished a hand-off step (login/OTP/pay done, or 'I've taken over' resolved)."""
        log.info("task_human_finished", task_id=self.task_id)
        self._human_flag = True

    # ── Agent-side awaits (poll the flags; loop-agnostic) ──────────────────────
    @property
    def stopped(self) -> bool:
        return self._stop

    async def _wait_flag(self, attr: str, timeout: float) -> bool:
        waited = 0.0
        while not getattr(self, attr) and not self._stop and waited < timeout:
            await asyncio.sleep(0.2)
            waited += 0.2
        return getattr(self, attr) and not self._stop

    async def wait_if_paused(self) -> None:
        while self._paused and not self._stop:
            await asyncio.sleep(0.15)

    async def wait_for_answers(self, timeout: float = 900) -> bool:
        return await self._wait_flag("_answers_flag", timeout)

    async def wait_for_choice(self, timeout: float = 600) -> bool:
        return await self._wait_flag("_choice_flag", timeout)

    async def wait_for_human(self, timeout: float = 600) -> bool:
        """Block the agent while the user completes a sensitive/hand-off step."""
        self._human_flag = False
        return await self._wait_flag("_human_flag", timeout)


# ── Registry ────────────────────────────────────────────────────────────────
_SESSIONS: dict[str, TaskSession] = {}


def create_session(user_id: str, goal: str) -> TaskSession:
    task_id = str(uuid.uuid4())
    s = TaskSession(task_id=task_id, user_id=user_id, goal=goal)
    _SESSIONS[task_id] = s
    log.info("task_session_created", task_id=task_id, user_id=user_id)
    return s


def get_session(task_id: str) -> TaskSession | None:
    return _SESSIONS.get(task_id)


def drop_session(task_id: str) -> None:
    _SESSIONS.pop(task_id, None)


# ── Redis-backed metadata so the run survives a reload / reaches another worker ──
# A Playwright browser can't cross processes, but the session METADATA (plan, answers, status)
# can: /task/start persists it, and the WebSocket hydrates it if this process doesn't hold it in
# memory (e.g. after a --reload restart, or on a different uvicorn worker). The browser then runs
# on whichever worker owns the WebSocket. This is the fix for the "Task not found" failure.
_TASK_KEY = "nipun:task:{task_id}"


async def persist_session(session: TaskSession, ttl: int = 3600) -> None:
    try:
        from src.db.redis import set_json
        await set_json(_TASK_KEY.format(task_id=session.task_id), {
            "task_id": session.task_id, "user_id": session.user_id, "goal": session.goal,
            "status": session.status.value,
            "plan": session.plan.to_dict() if session.plan else None,
            "answers": session.answers,
        }, ttl=ttl)
        log.info("task_session_persisted", task_id=session.task_id,
                 status=session.status.value, ttl=ttl)
    except Exception as exc:
        log.debug("task_session_persist_skipped", error=str(exc), error_type=type(exc).__name__)


async def load_session(task_id: str) -> TaskSession | None:
    """Return the in-memory session, or reconstruct it from Redis (registering it in this process).
    None if it exists nowhere."""
    if task_id in _SESSIONS:
        log.debug("task_session_in_memory", task_id=task_id)
        return _SESSIONS[task_id]
    try:
        from src.db.redis import get_json
        from src.ipa.schemas import TaskPlan
        data = await get_json(_TASK_KEY.format(task_id=task_id))
        if not data:
            log.info("task_session_not_found", task_id=task_id)
            return None
        s = TaskSession(task_id=data["task_id"], user_id=data["user_id"], goal=data.get("goal", ""))
        if data.get("plan"):
            s.plan = TaskPlan.from_dict(data["plan"])
        s.answers = data.get("answers") or {}
        # Restore the persisted status. CRITICAL for multi-worker safety: without this a session
        # hydrated on a second worker defaulted to PLANNING, so a WS there would relaunch a SECOND
        # live browser for an ALREADY-RUNNING task. Restoring RUNNING lets the start/relaunch guard
        # (task_agent.task_socket) refuse the duplicate run. The live browser itself only exists on
        # the ORIGIN worker (a Playwright page can't cross processes) — see the sticky-routing note.
        try:
            s.status = RunStatus(data.get("status", "planning"))
        except ValueError:
            pass
        _SESSIONS[task_id] = s
        log.info("task_session_hydrated", task_id=task_id, status=s.status.value)
        return s
    except Exception as exc:
        log.debug("task_session_load_skipped", error=str(exc), error_type=type(exc).__name__)
        return None
