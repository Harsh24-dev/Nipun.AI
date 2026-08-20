"""
Device executor — local file actions, SAFE BY CONSTRUCTION.

This deliberately does NOT run shell commands, install software, or touch the OS. It performs only
an allowlist of file operations, and only INSIDE a sandbox directory — any path that escapes the
sandbox (via `..`, absolute paths, symlinks) is rejected. It is also OFF by default
(DEVICE_EXECUTION_ENABLED). This is the correct boundary for a server process: executing arbitrary
device commands from a natural-language web request would be a remote-code-execution hole.

Real user-device control (open your apps, drive your desktop) belongs in a separate local
companion the user explicitly installs; this module is the safe seam it would plug into.
"""

from __future__ import annotations

from pathlib import Path

from src.config import settings
from src.core.logging import get_ipa_logger
from src.ipa.schemas import RunStatus, StepStatus, event
from src.ipa.session import TaskSession

log = get_ipa_logger("ipa.executors.device")

_ALLOWED = {"write_file", "read_file", "list_dir"}


def _sandbox_root() -> Path:
    root = settings.DEVICE_SANDBOX_DIR or str(Path(__file__).resolve().parents[3] / "device_sandbox")
    p = Path(root).resolve()
    p.mkdir(parents=True, exist_ok=True)
    log.debug("device_sandbox_root", root=str(p))
    return p


def _safe_path(root: Path, rel: str) -> Path | None:
    """Resolve `rel` under `root`, rejecting anything that escapes the sandbox."""
    try:
        target = (root / (rel or "").lstrip("/\\")).resolve()
        target.relative_to(root)     # raises if outside root
        return target
    except Exception as exc:
        log.warning("device_path_rejected", rel=rel, error=str(exc),
                    error_type=type(exc).__name__)
        return None


async def _do(root: Path, action: dict) -> str:
    atype = action.get("type")
    log.debug("device_do", type=atype, path=action.get("path"))
    if atype == "list_dir":
        p = _safe_path(root, action.get("path", "."))
        if not p or not p.exists():
            log.info("device_list_dir_missing", path=action.get("path"))
            return "path not found"
        entries = sorted(c.name for c in p.iterdir())[:50]
        log.info("device_list_dir", path=action.get("path"), entries=len(entries))
        return "contents: " + ", ".join(entries) or "(empty)"
    if atype == "read_file":
        p = _safe_path(root, action.get("path", ""))
        if not p or not p.is_file():
            log.info("device_read_file_missing", path=action.get("path"))
            return "file not found"
        content = p.read_text(encoding="utf-8", errors="replace")[:500]
        # Never log file contents — only the fact of the read + its size.
        log.info("device_read_file", name=p.name, chars=len(content))
        return "read: " + content
    if atype == "write_file":
        p = _safe_path(root, action.get("path", ""))
        if not p:
            log.warning("device_write_file_rejected", path=action.get("path"),
                        reason="outside_sandbox")
            return "invalid path (outside sandbox)"
        p.parent.mkdir(parents=True, exist_ok=True)
        size = len(str(action.get("content", "")))
        p.write_text(str(action.get("content", "")), encoding="utf-8")
        # Never log file contents — only the target name + written size.
        log.info("device_write_file", name=p.name, chars=size)
        return f"wrote {p.name} ({size} chars)"
    log.warning("device_unsupported_action", type=atype)
    return f"unsupported action: {atype}"


async def run(session: TaskSession) -> None:
    session.status = RunStatus.RUNNING
    await session.emit(event("status", session.task_id, status=session.status.value))
    log.info("device_run_start", task_id=session.task_id, user_id=session.user_id,
             enabled=settings.DEVICE_EXECUTION_ENABLED,
             actions=len(session.plan.actions or []))

    if not settings.DEVICE_EXECUTION_ENABLED:
        log.warning("device_run_disabled", task_id=session.task_id)
        for s in session.plan.steps:
            s.status = StepStatus.SKIPPED
        await session.emit(event("message", session.task_id,
                                 text="Device tasks are disabled on this server for safety. Enable "
                                      "DEVICE_EXECUTION_ENABLED (sandboxed file actions only), or use "
                                      "a local companion for full device control."))
        session.status = RunStatus.FAILED
        await session.emit(event("done", session.task_id, status=session.status.value, success=False))
        return

    root = _sandbox_root()
    await session.emit(event("message", session.task_id, text=f"Working in sandbox: {root}"))
    steps = session.plan.steps
    ok_count = 0
    for i, action in enumerate(session.plan.actions or []):
        if session.stopped:
            log.info("device_run_stopped", task_id=session.task_id, index=i)
            break
        await session.wait_if_paused()
        step = steps[i] if i < len(steps) else None
        if step:
            step.status = StepStatus.RUNNING
            await session.emit(event("step", session.task_id, step_id=step.id,
                                     status=step.status.value, title=step.title))
        atype = action.get("type")
        if atype not in _ALLOWED:
            log.warning("device_action_skipped", task_id=session.task_id, type=atype,
                        step_id=step.id if step else None, reason="not_allowlisted")
            outcome = "skipped (not an allowed file action)"
            ok = False
        else:
            try:
                outcome = await _do(root, action)
                ok = "not found" not in outcome and "invalid" not in outcome
            except Exception as exc:
                log.error("device_action_failed", task_id=session.task_id, type=atype,
                          step_id=step.id if step else None,
                          error=str(exc), error_type=type(exc).__name__)
                outcome, ok = f"failed: {str(exc)[:120]}", False
        if ok:
            ok_count += 1
        log.info("device_action_done", task_id=session.task_id, type=atype,
                 step_id=step.id if step else None, ok=ok)
        await session.emit(event("action", session.task_id, action=action, outcome=outcome,
                                 thought=f"{action.get('type')} {action.get('path','')}"))
        session.trace.append({"surface": "device", "action": {k: v for k, v in action.items() if k != "content"}})
        if step:
            step.status = StepStatus.DONE if ok else StepStatus.FAILED
            await session.emit(event("step", session.task_id, step_id=step.id,
                                     status=step.status.value, title=step.title))

    session.status = RunStatus.STOPPED if session.stopped else RunStatus.DONE
    log.info("device_run_end", task_id=session.task_id, status=session.status.value,
             ok=ok_count, actions=len(session.plan.actions or []))
    await session.emit(event("done", session.task_id, status=session.status.value,
                             success=session.status == RunStatus.DONE))
