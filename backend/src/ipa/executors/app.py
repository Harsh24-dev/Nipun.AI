"""
App executor — the agent acts on THIS assistant app: open a screen, change a setting (theme,
language, voice), update the user's profile, or open a link.

The backend decides the ordered actions; the CLIENT applies them (it owns the theme, routing and
local state), so each action is streamed as an `app_action` event the frontend handles. Profile
updates also persist server-side. Safe by construction — the vocabulary is a fixed allowlist, and
nothing here can touch the OS or run code.
"""

from __future__ import annotations

from src.core.logging import get_ipa_logger
from src.ipa.schemas import RunStatus, StepStatus, event
from src.ipa.session import TaskSession

log = get_ipa_logger("ipa.executors.app")

_ALLOWED = {"navigate", "set_setting", "update_profile", "open_url"}


def _resolve(action: dict, answers: dict) -> dict:
    """Fill any {value_key: <field>} placeholder from the user's form answers."""
    a = dict(action)
    vk = a.pop("value_key", None)
    if vk and answers.get(vk) is not None:
        a["value"] = answers[vk]
        log.debug("app_action_resolved", type=a.get("type"), value_key=vk)
    return a


async def _persist_profile(user_id: str, field: str, value) -> None:
    log.info("app_profile_persist", user_id=user_id, field=field)
    try:
        from src.memory.session import persist_profile_facts
        await persist_profile_facts(user_id, {field: value})
    except Exception as exc:
        log.warning("app_profile_persist_skipped", user_id=user_id, field=field,
                    error=str(exc), error_type=type(exc).__name__)


async def run(session: TaskSession) -> None:
    session.status = RunStatus.RUNNING
    await session.emit(event("status", session.task_id, status=session.status.value))
    await session.emit(event("message", session.task_id, text="Applying changes in the app…"))

    steps = session.plan.steps
    actions = session.plan.actions or []
    log.info("app_run_start", task_id=session.task_id, user_id=session.user_id,
             actions=len(actions), steps=len(steps))
    if not actions:
        log.warning("app_run_no_actions", task_id=session.task_id)
        await session.emit(event("message", session.task_id,
                                 text="No in-app changes to apply for this request."))
        session.status = RunStatus.FAILED
        await session.emit(event("done", session.task_id, status=session.status.value, success=False))
        return
    applied = 0
    for i, action in enumerate(actions):
        if session.stopped:
            log.info("app_run_stopped", task_id=session.task_id, index=i)
            break
        await session.wait_if_paused()
        step = steps[i] if i < len(steps) else None
        if step:
            step.status = StepStatus.RUNNING
            await session.emit(event("step", session.task_id, step_id=step.id,
                                     status=step.status.value, title=step.title))

        act = _resolve(action, session.answers)
        atype = act.get("type")
        if atype not in _ALLOWED:
            log.warning("app_action_skipped", task_id=session.task_id, type=atype,
                        step_id=step.id if step else None, reason="not_allowlisted")
            if step:
                step.status = StepStatus.SKIPPED
                await session.emit(event("step", session.task_id, step_id=step.id,
                                         status=step.status.value, title=step.title))
            continue

        # Profile changes are persisted server-side too (client reflects them live).
        if atype == "update_profile" and act.get("field"):
            await _persist_profile(session.user_id, act["field"], act.get("value"))

        # The client applies the action (theme/route/etc.) and reflects it immediately.
        log.info("app_action_applied", task_id=session.task_id, type=atype,
                 step_id=step.id if step else None)
        await session.emit(event("app_action", session.task_id, action=act,
                                 step_id=step.id if step else None))
        session.trace.append({"surface": "app", "action": act})
        applied += 1
        if step:
            step.status = StepStatus.DONE
            await session.emit(event("step", session.task_id, step_id=step.id,
                                     status=step.status.value, title=step.title))

    session.status = RunStatus.STOPPED if session.stopped else RunStatus.DONE
    log.info("app_run_end", task_id=session.task_id, status=session.status.value,
             applied=applied, actions=len(actions))
    await session.emit(event("done", session.task_id, status=session.status.value,
                             success=session.status == RunStatus.DONE))
    if session.status == RunStatus.DONE:
        from src.ipa.agent import _persist_success
        await _persist_success(session)
