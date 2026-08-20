"""
Read-only task assistants.

Each assistant PREVIEWS a task and returns a human-readable summary card — NONE performs
a real transaction. They reuse the Plan + confirmation-preview idea: the user sees exactly
what would happen before anything is executed (execution is a later, gated step).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import structlog

from src.execution.guards import assert_no_credentials

log = structlog.get_logger("tasks.assistants")


class TaskAssistant(ABC):
    name: str = "base_task"
    description: str = ""
    # Optional: a specialized system prompt the orchestrator uses to LLM-compile this task's
    # OUTPUT (e.g. write a tailored résumé, a re-skilling roadmap) instead of the generic
    # step-plan compiler. `{domain}` and `{language}` are filled in. When empty, the generic
    # task compiler is used and `_preview()` is the fallback. Keeps content generation
    # declarative and per-assistant — no orchestrator changes to add a new content task.
    compile_prompt: str = ""

    @abstractmethod
    def _preview(self, params: dict) -> dict:
        ...

    def run(self, params: dict) -> dict:
        assert_no_credentials(params)   # read-only tasks never handle credentials either
        card = self._preview(params)
        card.setdefault("cardType", "step_action")
        card.setdefault("preview_only", True)
        card.setdefault("disclaimer", "This is a preview. Nothing is booked, paid, or submitted "
                                      "until you explicitly confirm.")
        return card


class FindDeals(TaskAssistant):
    name = "find_deals"
    description = "Find deals/offers for a product (preview)."

    def _preview(self, params: dict) -> dict:
        item = params.get("item", "the item")
        return {
            "title": f"Deal search plan for {item}",
            "summary": f"I would search trusted marketplaces for current offers on {item} and show a "
                       f"comparison. I will not buy anything.",
            "steps": [
                {"title": "Search", "desc": f"Look up current prices for {item}", "status": "pending"},
                {"title": "Compare", "desc": "Rank by price, rating, delivery", "status": "pending"},
                {"title": "Show", "desc": "Present options for you to choose", "status": "pending"},
            ],
        }


class BuildItinerary(TaskAssistant):
    name = "build_itinerary"
    description = "Build a travel itinerary (preview)."

    def _preview(self, params: dict) -> dict:
        src = params.get("from", "origin")
        dst = params.get("to", "destination")
        days = params.get("days", "a few")
        return {
            "cardType": "timeline",
            "title": f"Itinerary: {src} → {dst} ({days} days)",
            "summary": f"A day-by-day plan from {src} to {dst}. Bookings are NOT made — this is a plan you can review.",
            "steps": [
                {"title": "Day 1", "desc": f"Travel {src} → {dst}, check-in", "status": "pending"},
                {"title": "Day 2", "desc": "Local sightseeing", "status": "pending"},
            ],
        }


class AssembleITRDraft(TaskAssistant):
    name = "assemble_itr_draft"
    description = "Assemble an income-tax return DRAFT (preview, not filed)."

    def _preview(self, params: dict) -> dict:
        return {
            "title": "ITR draft assembly plan",
            "summary": "I would organise your declared income and deductions into a draft summary for your "
                       "review. I will NOT file anything, and I never ask for passwords or OTPs. Consult a "
                       "tax professional before filing.",
            "steps": [
                {"title": "Collect", "desc": "List income sources and 80C deductions you provide", "status": "pending"},
                {"title": "Summarise", "desc": "Produce a draft figure for your review", "status": "pending"},
            ],
        }


class PrepareBillPayment(TaskAssistant):
    name = "prepare_bill_payment"
    description = "Prepare (but never execute) a bill payment (preview)."

    def _preview(self, params: dict) -> dict:
        biller = params.get("biller", "the biller")
        amount = params.get("amount", "the amount")
        return {
            "title": f"Bill payment plan: {biller}",
            "summary": f"I would prepare a payment of {amount} to {biller} for your review. I will NEVER ask "
                       f"for your OTP, PIN, card, or bank details, and nothing is paid until you confirm in a "
                       f"secure, official channel.",
            "steps": [
                {"title": "Verify biller", "desc": f"Confirm {biller} details", "status": "pending"},
                {"title": "Prepare", "desc": f"Draft a payment of {amount}", "status": "pending"},
                {"title": "Confirm", "desc": "You approve in the official app", "status": "pending"},
            ],
        }


class DynamicFormAssistant(TaskAssistant):
    """Fill a form on ANY site the user names. The real work (fetch → analyze the page's
    fields → map the user's details → hand off) is async and lives in `dynamic_fill.py`; the
    orchestrator runs it. This preview is the fallback shown when no site URL is available
    yet, prompting the user for one."""
    name = "form_dynamic"
    description = "Fill a form on any website the user specifies (fills all but login/OTP/submit)."

    def _preview(self, params: dict) -> dict:
        return {
            "cardType": "step_action",
            "title": "Fill a form on a website",
            "summary": "Tell me the website (paste its link) whose form you want filled, and I'll "
                       "read the form, fill in your details accurately, and hand it back for you to "
                       "review — you keep the login, OTP, and final submit.",
            "steps": [
                {"title": "Share the site", "desc": "Paste the page link with the form", "status": "pending"},
                {"title": "I analyse & fill", "desc": "Read the fields and fill your details", "status": "pending"},
                {"title": "You submit", "desc": "Review, then log in / OTP / submit yourself", "status": "pending"},
            ],
        }


class PlanTask(TaskAssistant):
    name = "plan_task"
    description = "Break a general task into a plan (preview)."

    def _preview(self, params: dict) -> dict:
        goal = params.get("goal", "your task")
        return {
            "title": f"Plan for: {goal}",
            "summary": f"Here is a step-by-step plan for {goal}. Nothing is executed automatically.",
            "steps": [
                {"title": "Step 1", "desc": "Understand requirements", "status": "pending"},
                {"title": "Step 2", "desc": "Gather what's needed", "status": "pending"},
                {"title": "Step 3", "desc": "Do it (with your confirmation)", "status": "pending"},
            ],
        }


_ASSISTANTS: dict[str, TaskAssistant] = {
    a.name: a for a in (FindDeals(), BuildItinerary(), AssembleITRDraft(), PrepareBillPayment(),
                        DynamicFormAssistant(), PlanTask())
}


def register_assistant(assistant: TaskAssistant) -> TaskAssistant:
    """Plug in a new task assistant (e.g. a payment or shopping assistant in a later phase).
    Once registered it is selectable by the orchestrator with no core changes."""
    _ASSISTANTS[assistant.name] = assistant
    return assistant


def get_assistant(name: str) -> TaskAssistant | None:
    return _ASSISTANTS.get(name)


def list_assistants() -> list[dict]:
    return [{"name": a.name, "description": a.description} for a in _ASSISTANTS.values()]


# ── Domain/intent → assistant routing ─────────────────────────────────────────────
# Which assistant compiles a given task. Keep this data-driven so new integrations only add
# a row (and their assistant), never touch the orchestrator. `select_assistant` always
# returns something (falls back to the generic planner) so a task is never a dead end.

def _kw(query: str, *words: str) -> bool:
    q = (query or "").lower()
    return any(w in q for w in words)


def _match_assistant(domain: str, text: str) -> TaskAssistant | None:
    """Keyword/domain match for a specific assistant, or None if nothing specific fits."""
    d, q = (domain or "").lower(), (text or "").lower()
    # Site-specific form fill: the user named a page/URL to fill → the generic dynamic filler
    # reads THAT page's real fields. Checked first so "fill the form on <url>" is literal.
    if ("http://" in q or "https://" in q) and _kw(q, "fill", "form", "apply", "submit", "enter", "register"):
        return _ASSISTANTS.get("form_dynamic")
    if _kw(q, "fill this form", "fill the form", "fill out the form", "fill a form", "form on this site",
           "form on the site", "fill up the form"):
        return _ASSISTANTS.get("form_dynamic")
    if _kw(q, "bill", "pay ", "payment", "recharge", "electricity bill", "utility"):
        return _ASSISTANTS.get("prepare_bill_payment")
    if _kw(q, "itr", "income tax return", "file tax", "tax return"):
        return _ASSISTANTS.get("assemble_itr_draft")
    # Apply to a job — fill the application, hand off login/upload/submit to the user.
    if _kw(q, "apply") and _kw(q, "job", "jobs", "position", "role", "opening", "vacancy",
                               "naukri", "linkedin", "posting"):
        return _ASSISTANTS.get("form_job_application")
    # Tailor an existing CV to a specific role (check before the generic résumé builder).
    if _kw(q, "tailor", "customize", "customise", "match", "optimi") and \
            _kw(q, "cv", "resume", "résumé", "biodata"):
        return _ASSISTANTS.get("tailor_resume")
    if _kw(q, "resume", "résumé", "cv", "curriculum vitae", "biodata", "bio-data"):
        return _ASSISTANTS.get("build_resume")
    # Re-skilling / learning roadmap for a chosen skill.
    if _kw(q, "reskill", "re-skill", "upskill", "up-skill", "learning plan", "study plan",
           "roadmap", "skill up", "how to become", "prepare for", "learn a new skill"):
        return _ASSISTANTS.get("learning_plan")
    # Dedicated government/service form assistants. These live in tasks.forms (not _ASSISTANTS)
    # and are fetched lazily to avoid an import cycle. Keywords are specific so a generic
    # request is never hijacked; each fills the form and hands off login/OTP/payment/submit.
    from src.tasks.forms import get_form_assistant

    if _kw(q, "rti", "right to information", "information request under"):
        return get_form_assistant("rti")
    if _kw(q, "train ticket", "book a train", "book train", "irctc", "railway ticket", "railway booking"):
        return get_form_assistant("train_booking")
    if _kw(q, "doctor appointment", "book a doctor", "opd appointment", "consult a doctor", "appointment with a doctor"):
        return get_form_assistant("doctor_appointment")
    if _kw(q, "bail application", "anticipatory bail", "apply for bail", "bail petition"):
        return get_form_assistant("bail_application")
    if _kw(q, "birth certificate", "death certificate", "caste certificate", "income certificate",
           "domicile certificate", "ration card", "voter id", "document application"):
        return get_form_assistant("document_application")

    if d == "travel" or _kw(q, "itinerary", "trip", "tour", "travel plan"):
        return _ASSISTANTS.get("build_itinerary")
    if _kw(q, "buy", "deal", "offer", "cheapest", "best price", "shopping", "purchase", "discount"):
        return _ASSISTANTS.get("find_deals")
    return None


def select_assistant(domain: str, intent: str, query: str, context: str = "") -> TaskAssistant:
    """Pick the best assistant to compile this task.

    The CURRENT message wins: a self-contained request routes on its own. Only when the
    current message is a bare follow-up ("fill it for me", "yes, go ahead") that matches
    nothing specific do we fall back to `context` (the recent conversation) to resolve which
    task the user means — so a follow-up inherits the task under discussion, while a new,
    specific request is never hijacked by an earlier topic. Extensible: later phases register
    a payment-gateway / shopping-portal assistant and add a branch (or a registry row)."""
    return (
        _match_assistant(domain, query)
        or (_match_assistant(domain, context) if context else None)
        or _ASSISTANTS["plan_task"]
    )
