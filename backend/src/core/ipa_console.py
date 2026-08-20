"""
Human-readable browser-run flow — the "what did the agent do" view for IPA.

Prints ONE clean, scannable block per browser-automation task to ipa.log: a header with the
goal + start URL, one line per checklist step as it runs, an indented line per action (and each
hand-off / resume), and a footer with the final status, elapsed time, action count, and result
URL. This is the IPA parallel to core.flow_console (flow.log) — read ipa.log to understand what a
task run did end-to-end without wading through the structured ipa.debug.log.

Everything here is best-effort and never raises — readability must never break a run. Glyphs are
limited to the cp1252-safe set (· » « × –) so Windows consoles/files don't choke; arrows are ASCII
"->" for the same reason.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from src.config import settings

_log = logging.getLogger("ipa_flow")   # → ipa.log: the readable per-task browser-run story

# task_id -> {"t0": monotonic_start, "actions": int} so the footer can report elapsed + count
# without threading state through the agent loop. Best-effort; entries are dropped on task_end.
_runs: dict[str, dict[str, Any]] = {}


def _short(v: str | None) -> str:
    return (v or "")[:8] or "--------"


def _dur(seconds: float | None) -> str:
    if seconds is None:
        return ""
    ms = seconds * 1000
    return f"{ms / 1000:.1f}s" if ms >= 1000 else f"{int(ms)}ms"


def _clip(text: str | None, n: int = 60) -> str:
    t = " ".join((text or "").split())
    return t[:n]


# ── Task lifecycle ──────────────────────────────────────────────────────────────

def task_start(task_id: str, user_id: str, goal: str, start_url: str = "") -> None:
    if not settings.IPA_CONSOLE_ENABLED:
        return
    try:
        _runs[task_id] = {"t0": time.monotonic(), "actions": 0}
        _log.info("")
        _log.info(f"» TASK  {_short(task_id)}  user={_short(user_id)}")
        _log.info(f'    "{_clip(goal, 140)}"')
        if start_url:
            _log.info(f"    -> {_clip(start_url, 120)}")
    except Exception:
        pass


def replay(task_id: str, host: str, used: int) -> None:
    """A proven recipe is being replayed deterministically (the fast path, no per-step LLM)."""
    if not settings.IPA_CONSOLE_ENABLED:
        return
    try:
        _log.info(f"  ~ replay  proven recipe for {_clip(host, 40)} (used {used}x before)")
    except Exception:
        pass


def step_start(task_id: str, step_id: Any, title: str, sensitive: bool = False) -> None:
    if not settings.IPA_CONSOLE_ENABLED:
        return
    try:
        tag = " [sensitive]" if sensitive else ""
        _log.info(f"  · step {step_id}  {_clip(title, 70)}{tag}")
    except Exception:
        pass


def action(task_id: str, atype: str, target: str = "", outcome: str = "",
           thought: str = "") -> None:
    if not settings.IPA_CONSOLE_ENABLED:
        return
    try:
        r = _runs.get(task_id)
        if r is not None:
            r["actions"] += 1
        tgt = f' "{_clip(target, 40)}"' if target else ""
        res = f" -> {_clip(outcome, 40)}" if outcome else ""
        _log.info(f"      {atype}{tgt}{res}")
        if thought:
            _log.info(f"        ({_clip(thought, 90)})")
    except Exception:
        pass


def handoff(task_id: str, kind: str, reason: str = "") -> None:
    """Control handed to the human (login / OTP / payment / final-submit / stuck)."""
    if not settings.IPA_CONSOLE_ENABLED:
        return
    try:
        _log.info(f"      -- hand-off [{kind}] {_clip(reason, 90)}".rstrip())
    except Exception:
        pass


def resumed(task_id: str) -> None:
    if not settings.IPA_CONSOLE_ENABLED:
        return
    try:
        _log.info("      -- resumed (human done)")
    except Exception:
        pass


def step_done(task_id: str, step_id: Any, status: str) -> None:
    if not settings.IPA_CONSOLE_ENABLED:
        return
    try:
        mark = "×" if status == "failed" else "·"
        _log.info(f"  {mark} step {step_id}  {status}")
    except Exception:
        pass


def note(task_id: str, message: str) -> None:
    """A free-form one-liner in the story (divergence, timeout, warning …)."""
    if not settings.IPA_CONSOLE_ENABLED:
        return
    try:
        _log.info(f"    · {_clip(message, 120)}")
    except Exception:
        pass


def task_end(task_id: str, status: str, success: bool, url: str = "",
             title: str = "") -> None:
    if not settings.IPA_CONSOLE_ENABLED:
        return
    try:
        r = _runs.pop(task_id, None)
        elapsed = _dur(time.monotonic() - r["t0"]) if r else ""
        actions = r["actions"] if r else 0
        parts = [status]
        if elapsed:
            parts.append(elapsed)
        parts.append(f"{actions} actions")
        _log.info(f"« RESULT  {' · '.join(parts)}")
        if url:
            _log.info(f"    -> {_clip(url, 120)}")
        _log.info("")
    except Exception:
        pass
