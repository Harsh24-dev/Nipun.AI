"""
Form-assist — the digital-divide feature.

Millions of Indians (senior citizens, low-literacy users) can't navigate multi-page
government/private forms. This layer does the hard part FOR them: it collects the needed
details once (via the clarify form), auto-fills everything it can from their profile +
answers, and hands back a COMPLETED, reviewable application — leaving the user with only
the things an agent must never do for them: **payment, OTP, PIN, password, biometric,
and the final e-sign/submit tap.**

Safety is structural, not aspirational:
  * `assert_no_credentials` (from execution.guards) rejects any payload containing an
    OTP / PIN / password / card / CVV / Aadhaar / PAN — the agent literally cannot accept
    them, so it can never fill them into a form.
  * Every service declares `user_only_steps` — the steps the USER performs. Payment/OTP
    always live there, never in the auto-filled data.
  * This module only PREPARES a filled package. Real submission to an external portal is a
    separate, gated step (execution.executor: EXECUTION_ENABLED + a registered handler),
    added one integration at a time — so nothing is ever submitted silently.

Examples covered: RTI application, doctor appointment, train booking, bail-application
assembly, generic document application. Each is a `FormAssistant` registered alongside the
existing task assistants, so it's reachable via /tasks/preview immediately.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog

from src.execution.guards import scan_for_credentials
from src.tasks.assistants import TaskAssistant

log = structlog.get_logger("tasks.forms")


@dataclass
class FieldSpec:
    key: str                 # where the value comes from in profile/answers
    label: str               # human label on the form
    required: bool = True
    example: str = ""


@dataclass
class FormAssistant(TaskAssistant):
    """A service whose form the agent fills on the user's behalf — except credentials."""

    service: str = "form"
    title: str = "Form assistance"
    portal_name: str = ""
    portal_url: str = ""
    autofill: list[FieldSpec] = field(default_factory=list)
    # Steps only the USER can/should do. Payment/OTP/password ALWAYS belong here.
    user_only_steps: list[str] = field(default_factory=list)

    def __post_init__(self):
        self.name = f"form_{self.service}"
        self.description = f"Fill the {self.title} for you (everything except payment/OTP)."

    def _preview(self, params: dict) -> dict:
        # `params` carries the user's known profile + the answers they gave to the clarify
        # form. run() has already asserted there are NO credentials in it.
        profile = params.get("profile") or {}
        answers = params.get("answers") or {}
        data = {**profile, **answers}

        filled: list[dict] = []
        missing: list[str] = []
        for spec in self.autofill:
            value = data.get(spec.key)
            if value in (None, "", [], {}):
                if spec.required:
                    missing.append(spec.label)
                continue
            # Defence in depth: never surface a value that scans as a credential.
            if scan_for_credentials(f"{spec.label} {value}"):
                continue
            filled.append({"label": spec.label, "value": value})

        # `missing` is derived from STATIC per-service field specs — a PRIOR/HINT of what the
        # form usually needs, NOT a check against the live portal's current form. So even when
        # nothing is missing by our specs we cannot honestly guarantee the portal is satisfied.
        specs_satisfied = not missing
        # This static path never inspects the live form, so it must never claim a confident
        # handoff. `ready_for_handoff` stays False unless something actually verified the live
        # form (kept as a hook for a future live-verification caller). This is the fix for the
        # false-ready bug: static specs are advisory, not a guarantee.
        verified = bool(params.get("_live_verified"))
        ready = specs_satisfied and verified

        steps = [{"title": s, "desc": "You do this — we never see it.", "status": "pending"}
                 for s in self.user_only_steps]

        live_caveat = (" The live portal may ask for additional fields — please review the page "
                       "before you submit.")
        if specs_satisfied:
            summary = (
                f"I've filled your {self.title} with the details you gave. Please review the "
                f"entries, then complete only the steps below — payment, OTP, and password are "
                f"done by YOU on the official portal. I never see or ask for them." + live_caveat
            )
        else:
            summary = (
                f"I've started your {self.title}. I still need: {', '.join(missing)}. "
                f"Share these and I'll fill everything I can, leaving only payment/OTP to you." + live_caveat
            )

        card = {
            "cardType": "step_action",
            "title": (f"{self.title} — details filled, review on the portal" if specs_satisfied
                      else f"{self.title} — a few details left"),
            "summary": summary,
            "filled_form": {"service": self.service, "fields": filled},
            "missing_fields": missing or None,
            "steps": steps or None,
            "portal": {"name": self.portal_name, "url": self.portal_url} if self.portal_url else None,
            "ready_for_handoff": ready,
            "disclaimer": ("For your safety, this assistant NEVER asks for or enters your OTP, PIN, "
                           "password, card, or bank details — you complete those yourself on the "
                           "official site. These entries are prepared from the details you gave and "
                           "the form's usual layout; the live portal may require additional fields, "
                           "so review the page before submitting."),
        }
        log.info("form_assist_prepared", service=self.service, ready=ready,
                 specs_satisfied=specs_satisfied, filled=len(filled), missing=len(missing))
        return card


# ── Concrete services ─────────────────────────────────────────────────────────
# autofill keys map to profile fields + clarify answers; user_only_steps always own
# anything sensitive (payment / OTP / password / biometric / final submit).

RTI_FORM = FormAssistant(
    service="rti",
    title="RTI application",
    portal_name="RTI Online",
    portal_url="https://rtionline.gov.in/",
    autofill=[
        FieldSpec("name", "Applicant name"),
        FieldSpec("state", "State / public authority"),
        FieldSpec("address", "Address", required=False),
        FieldSpec("rti_subject", "Information sought (subject)"),
        FieldSpec("rti_details", "Details of information requested"),
        FieldSpec("bpl_status", "Below Poverty Line? (fee waiver)", required=False),
    ],
    user_only_steps=[
        "Pay the ₹10 RTI fee on the portal (net-banking/UPI/card)",
        "Enter the OTP sent to your phone to submit",
    ],
)

DOCTOR_APPOINTMENT_FORM = FormAssistant(
    service="doctor_appointment",
    title="doctor appointment booking",
    portal_name="ABHA / hospital portal",
    portal_url="https://abha.abdm.gov.in/",
    autofill=[
        FieldSpec("name", "Patient name"),
        FieldSpec("age", "Age"),
        FieldSpec("gender", "Gender", required=False),
        FieldSpec("department", "Department / speciality"),
        FieldSpec("preferred_date", "Preferred date"),
        FieldSpec("location", "City / hospital", required=False),
        FieldSpec("symptoms_summary", "Reason for visit", required=False),
    ],
    user_only_steps=[
        "Confirm the slot and pay the consultation fee (if any)",
        "Enter the OTP to confirm the booking",
    ],
)

TRAIN_BOOKING_FORM = FormAssistant(
    service="train_booking",
    title="train ticket booking",
    portal_name="IRCTC",
    portal_url="https://www.irctc.co.in/",
    autofill=[
        FieldSpec("name", "Passenger name"),
        FieldSpec("age", "Age"),
        FieldSpec("gender", "Gender", required=False),
        FieldSpec("from_station", "From station"),
        FieldSpec("to_station", "To station"),
        FieldSpec("travel_date", "Journey date"),
        FieldSpec("travel_class", "Class (e.g. 3A/SL)", required=False),
        FieldSpec("berth_preference", "Berth preference", required=False),
    ],
    user_only_steps=[
        "Review the auto-filled passenger details on IRCTC",
        "Make the payment (UPI/card/net-banking) yourself",
        "Enter the OTP to confirm the ticket",
    ],
)

BAIL_APPLICATION_FORM = FormAssistant(
    service="bail_application",
    title="bail application draft",
    portal_name="eCourts",
    portal_url="https://ecourts.gov.in/",
    autofill=[
        FieldSpec("name", "Applicant / accused name"),
        FieldSpec("state", "State / court"),
        FieldSpec("fir_number", "FIR number", required=False),
        FieldSpec("police_station", "Police station", required=False),
        FieldSpec("sections", "Sections / offence", required=False),
        FieldSpec("grounds", "Grounds for bail"),
    ],
    user_only_steps=[
        "Have a lawyer review and sign the draft (bail needs a legal professional)",
        "File through the advocate / eCourts and pay any court fee yourself",
    ],
)

DOCUMENT_APPLICATION_FORM = FormAssistant(
    service="document_application",
    title="government document application",
    portal_name="official portal",
    portal_url="",
    autofill=[
        FieldSpec("name", "Full name"),
        FieldSpec("age", "Age", required=False),
        FieldSpec("state", "State"),
        FieldSpec("district", "District", required=False),
        FieldSpec("document_type", "Document"),
        FieldSpec("action", "Requested action (new/update/reprint)"),
        FieldSpec("purpose", "Purpose", required=False),
    ],
    user_only_steps=[
        "Upload your supporting documents on the portal",
        "Pay the applicable fee and complete OTP/e-sign yourself",
    ],
)


_FORMS: dict[str, FormAssistant] = {
    f.name: f for f in (
        RTI_FORM, DOCTOR_APPOINTMENT_FORM, TRAIN_BOOKING_FORM,
        BAIL_APPLICATION_FORM, DOCUMENT_APPLICATION_FORM,
    )
}


def register_form(form: FormAssistant) -> FormAssistant:
    """Register a form assistant so it is resolvable by name AND routable by the
    orchestrator's `select_assistant` (which looks in the shared assistant registry)."""
    from src.tasks.assistants import register_assistant

    _FORMS[form.name] = form
    register_assistant(form)   # also make it selectable via select_assistant / get_assistant
    return form


def get_form_assistant(name: str) -> FormAssistant | None:
    return _FORMS.get(name) or _FORMS.get(f"form_{name}")


def list_form_assistants() -> list[dict]:
    return [{"name": f.name, "service": f.service, "title": f.title,
             "portal": f.portal_url, "user_only_steps": f.user_only_steps}
            for f in _FORMS.values()]
