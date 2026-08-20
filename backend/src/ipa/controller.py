"""
Controller — the single entry point that EXECUTES a planned task on the right surface.

    web    → the Playwright browser agent (src.ipa.agent.run_task)
    app    → in-app actions applied by the client (src.ipa.executors.app)
    device → safe sandboxed local file actions (src.ipa.executors.device)

Everything upstream (plan → one form → live stream → pause/stop/human-in-loop) and downstream
(recipe + profile learning) is shared, so adding a new surface is just another executor here.
"""

from __future__ import annotations

import asyncio
import sys
import threading

from src.core.logging import get_ipa_logger
from src.ipa.schemas import RunStatus, event
from src.ipa.session import TaskSession

log = get_ipa_logger("ipa.controller")


def run_in_worker(session: TaskSession) -> None:
    """Run the task on a DEDICATED thread with its own Proactor event loop, then return.

    Why a thread: on Windows, uvicorn with --reload runs on a SelectorEventLoop, which CANNOT
    spawn the Playwright browser subprocess (it raises NotImplementedError — the empty-error task
    failure). A ProactorEventLoop can. `session.main_loop` is the WebSocket's loop; the agent emits
    events back to it thread-safely, and control flags are plain bools, so the two loops cooperate.
    """
    def _target() -> None:
        loop = asyncio.ProactorEventLoop() if sys.platform == "win32" else asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        session.agent_loop = loop   # so the WebSocket can forward user clicks/keys to the browser
        log.info("ipa_worker_started", task_id=session.task_id, user_id=session.user_id,
                 loop_type=type(loop).__name__)
        try:
            loop.run_until_complete(execute(session))
        except Exception as exc:   # pragma: no cover - defensive
            import traceback
            log.error("ipa_worker_crashed", task_id=session.task_id, error=str(exc),
                      error_type=type(exc).__name__, trace=traceback.format_exc()[-900:])
        finally:
            try:
                loop.close()
            except Exception as exc:
                log.debug("ipa_worker_loop_close_error", task_id=session.task_id,
                          error=str(exc), error_type=type(exc).__name__)
            log.info("ipa_worker_finished", task_id=session.task_id)

    log.info("ipa_worker_launch", task_id=session.task_id, user_id=session.user_id)
    threading.Thread(target=_target, name=f"ipa-{session.task_id[:8]}", daemon=True).start()


async def _compare_and_choose(session: TaskSession) -> None:
    """For a comparable web task: gather the few best TRUSTED options across sources, show them,
    and wait for the user to pick one — then point the run at that option's site. Best-effort: if
    nothing credible is found, proceed with the planned target (no fake options are ever shown)."""
    from src.ipa.compare import gather_options, is_comparable
    if not is_comparable(session.goal):
        log.debug("ipa_compare_skipped", task_id=session.task_id, reason="not_comparable")
        return
    session.status = RunStatus.COMPARING
    log.info("ipa_compare_start", task_id=session.task_id, goal=(session.goal or "")[:120])
    await session.emit(event("status", session.task_id, status=session.status.value))
    await session.emit(event("message", session.task_id,
                             text="Comparing the best options across trusted sources…"))
    options = await gather_options(session.goal, session.answers, correlation_id=session.task_id)
    if not options:
        log.info("ipa_compare_no_options", task_id=session.task_id)
        return
    session.status = RunStatus.AWAITING_CHOICE
    log.info("ipa_compare_awaiting_choice", task_id=session.task_id, options=len(options))
    await session.emit(event("options", session.task_id, options=options,
                             note="Pick one to proceed — these are from reputable sources only."))
    ok = await session.wait_for_choice()
    if session.stopped or not ok:
        log.info("ipa_compare_abandoned", task_id=session.task_id, stopped=session.stopped)
        return
    ch = session.chosen_option or {}
    if ch.get("url"):
        session.plan.start_url = ch["url"]
        session.plan.target = {"name": ch.get("provider") or ch.get("name", ""),
                               "why": ch.get("why", ""), "url": ch["url"]}
        log.info("ipa_compare_chosen", task_id=session.task_id,
                 provider=ch.get("provider") or ch.get("name", ""), url=ch["url"][:120])
        await session.emit(event("message", session.task_id,
                                 text=f"Proceeding on {ch.get('provider') or ch.get('name', 'your choice')}"))


async def execute(session: TaskSession) -> None:
    """Dispatch the run to the executor for this task's surface. Never raises."""
    surface = (session.plan.surface if session.plan else "web") or "web"
    log.info("ipa_execute", task_id=session.task_id, user_id=session.user_id, surface=surface)
    try:
        if surface == "web":
            await _compare_and_choose(session)
            if session.stopped:
                log.info("ipa_execute_stopped", task_id=session.task_id, surface=surface)
                return
        if surface == "app":
            from src.ipa.executors.app import run as run_app
            log.info("ipa_execute_dispatch", task_id=session.task_id, surface="app")
            await run_app(session)
        elif surface == "device":
            from src.ipa.executors.device import run as run_device
            log.info("ipa_execute_dispatch", task_id=session.task_id, surface="device")
            await run_device(session)
        else:
            from src.ipa.agent import run_task as run_web
            log.info("ipa_execute_dispatch", task_id=session.task_id, surface="web")
            await run_web(session)
        log.info("ipa_execute_done", task_id=session.task_id, surface=surface,
                 status=session.status.value)
    except Exception as exc:
        import traceback
        log.error("ipa_execute_failed", task_id=session.task_id, surface=surface,
                  error=str(exc), error_type=type(exc).__name__,
                  trace=traceback.format_exc()[-900:])
        session.status = RunStatus.FAILED
        await session.emit(event("error", session.task_id, message=str(exc)[:200]))
