"""Typed structures shared across the IPA engine and the WebSocket protocol."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from src.core.logging import get_ipa_logger

log = get_ipa_logger("ipa.schemas")


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    NEEDS_HUMAN = "needs_human"     # sensitive step (login/OTP/pay) or agent stuck → user acts
    FAILED = "failed"
    SKIPPED = "skipped"


class RunStatus(str, Enum):
    PLANNING = "planning"
    AWAITING_INPUT = "awaiting_input"   # consolidated form is out, waiting for the user
    COMPARING = "comparing"             # gathering + ranking options across sources
    AWAITING_CHOICE = "awaiting_choice" # top options shown, waiting for the user to pick one
    RUNNING = "running"
    PAUSED = "paused"
    NEEDS_HUMAN = "needs_human"         # handed control to the user mid-run
    DONE = "done"
    FAILED = "failed"
    STOPPED = "stopped"


@dataclass
class ChecklistStep:
    id: int
    title: str
    detail: str = ""
    sensitive: bool = False            # login / OTP / payment / final submit → never automated
    status: StepStatus = StepStatus.PENDING

    def to_dict(self) -> dict:
        return {"id": self.id, "title": self.title, "detail": self.detail,
                "sensitive": self.sensitive, "status": self.status.value}

    @classmethod
    def from_dict(cls, d: dict) -> "ChecklistStep":
        try:
            status = StepStatus(d.get("status", "pending"))
        except ValueError as exc:
            log.warning("checklist_step_bad_status", value=d.get("status"),
                        error=str(exc), error_type=type(exc).__name__)
            status = StepStatus.PENDING
        return cls(id=int(d.get("id", 0)), title=d.get("title", ""), detail=d.get("detail", ""),
                   sensitive=bool(d.get("sensitive")), status=status)


@dataclass
class FormField:
    name: str
    label: str
    type: str = "text"                 # text | number | select | date | password-EXCLUDED
    options: list[str] = field(default_factory=list)
    required: bool = True
    placeholder: str = ""

    def to_dict(self) -> dict:
        d = {"name": self.name, "label": self.label, "type": self.type, "required": self.required}
        if self.options:
            d["options"] = self.options
        if self.placeholder:
            d["placeholder"] = self.placeholder
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "FormField":
        return cls(name=d.get("name", ""), label=d.get("label", ""), type=d.get("type", "text"),
                   options=list(d.get("options") or []), required=bool(d.get("required", True)),
                   placeholder=d.get("placeholder", ""))


@dataclass
class TaskPlan:
    goal: str
    start_url: str
    steps: list[ChecklistStep]
    form_fields: list[FormField]
    summary: str = ""
    # Which surface executes this task:
    #   web    → a real browser (Playwright) automates a website.
    #   app    → in-app actions (change a setting, update profile, navigate) applied by the client.
    #   device → local device actions (safe, allowlisted, sandboxed, opt-in — never arbitrary).
    surface: str = "web"
    # For app/device surfaces: the ordered actions to perform (each {type, ...}). Web derives its
    # actions live from the page, so this stays empty there.
    actions: list[dict] = field(default_factory=list)
    # The chosen target (which site/app was selected and WHY) + the alternatives considered — shown
    # to the user for transparency ("Using IRCTC — official Indian Railways booking").
    target: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "goal": self.goal, "start_url": self.start_url, "summary": self.summary,
            "surface": self.surface, "actions": self.actions, "target": self.target,
            "steps": [s.to_dict() for s in self.steps],
            "form_fields": [f.to_dict() for f in self.form_fields],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TaskPlan":
        plan = cls(
            goal=d.get("goal", ""), start_url=d.get("start_url", ""),
            steps=[ChecklistStep.from_dict(s) for s in (d.get("steps") or [])],
            form_fields=[FormField.from_dict(f) for f in (d.get("form_fields") or [])],
            summary=d.get("summary", ""), surface=d.get("surface", "web"),
            actions=list(d.get("actions") or []), target=dict(d.get("target") or {}),
        )
        log.debug("task_plan_from_dict", surface=plan.surface, steps=len(plan.steps),
                  form_fields=len(plan.form_fields), actions=len(plan.actions),
                  start_url=plan.start_url)
        return plan


@dataclass
class AgentAction:
    """One decision the agent made this turn."""
    type: str                          # click | type | select | scroll | navigate | wait | done | ask_human | fail
    index: int | None = None           # target element index (set-of-marks)
    text: str = ""                     # text to type / option to select / url to navigate
    thought: str = ""                  # short natural-language reasoning shown to the user
    reason: str = ""                   # why ask_human / fail (when applicable)

    def to_dict(self) -> dict:
        return {"type": self.type, "index": self.index, "text": self.text,
                "thought": self.thought, "reason": self.reason}


def event(kind: str, task_id: str, **data: Any) -> dict:
    """Build a WebSocket event envelope. `kind` is the event type the frontend switches on."""
    log.debug("event_built", kind=kind, task_id=task_id, fields=list(data.keys()))
    return {"type": kind, "task_id": task_id, "ts": round(time.time(), 3), **data}


log.debug("schemas_loaded", step_statuses=len(StepStatus), run_statuses=len(RunStatus))
