"""
Career & jobs task assistants — for students and working professionals.

Four capabilities, all consistent with the app's safety model (preview → confirm, and the
agent NEVER handles a login, password, OTP, or the final submit):

  * ResumeBuilder      — draft a professional résumé/CV from the user's background.
  * TailorResume       — rewrite that CV to match ONE specific job's requirements.
  * JobApplicationForm — fill every field of a job application it safely can, attach the
    tailored CV, deep-link to the portal, and leave login/upload/submit to the user.
  * LearningPlanBuilder — a re-skilling roadmap for a chosen skill, grounded in real
    courses / books / research (the live scholar + books tools enrich it at query time).

The three content assistants declare a `compile_prompt`, so the orchestrator LLM-generates
tailored content (real bullet points, a roadmap) rather than a generic step list; their
`_preview()` stays as a safe, offline fallback. The application assistant is a FormAssistant
whose structured fill is used directly (no free-text generation).
"""

from __future__ import annotations

from src.core.logging import get_logger
from src.tasks.assistants import TaskAssistant, register_assistant
from src.tasks.forms import FieldSpec, FormAssistant, register_form

log = get_logger("tasks.career")

# ── Shared JSON schema note appended to every content compile prompt ───────────
# The orchestrator already prepends the runtime header (real date, user profile) and the
# recent conversation. Each prompt below only has to describe the OUTPUT it should produce.
_STRICT_JSON = (
    "\nRespond with STRICT JSON only (no markdown fences), matching this ResponseCard:\n"
    '{{"cardType": "document|timeline|step_action", "language": "{language}", '
    '"title": "concrete title", "summary": "the main content in clean, readable text '
    '(use short lines / bullet dashes; NEVER invent facts, degrees, or employers the user '
    'did not provide)", "steps": [{{"title": "section or phase", "desc": "content", '
    '"status": "pending"}}], "sources": [{{"text": "name", "url": "optional"}}]}}\n'
    "Include ONLY keys relevant to the chosen cardType."
)


class ResumeBuilder(TaskAssistant):
    name = "build_resume"
    description = "Draft a professional résumé / CV from the user's background."
    compile_prompt = (
        "You are an expert résumé writer for the Indian job market (domain: {domain}). "
        "Using ONLY the details the user has provided (profile + answers + conversation), "
        "write a clean, ATS-friendly one-page résumé. Include, when the data exists: a crisp "
        "professional summary (2-3 lines), key skills, work experience as strong achievement "
        "bullets (action verb + impact, quantify where the user gave numbers), education, and "
        "certifications/projects. Do NOT fabricate employers, dates, degrees, or metrics that "
        "were not provided — if a section has no data, omit it and note what to add. Use "
        "cardType 'document'. Write in {language}." + _STRICT_JSON
    )

    def _preview(self, params: dict) -> dict:
        return {
            "cardType": "document",
            "title": "Résumé draft",
            "summary": "I'll draft a professional, ATS-friendly résumé from your background. "
                       "Share your target role, work history (with dates), education, and key "
                       "skills, and I'll assemble it — you review and edit before using it.",
            "steps": [
                {"title": "Collect", "desc": "Role, experience, education, skills", "status": "pending"},
                {"title": "Draft", "desc": "Assemble a one-page résumé for your review", "status": "pending"},
            ],
        }


class TailorResume(TaskAssistant):
    name = "tailor_resume"
    description = "Rewrite the user's CV to match a specific job's requirements."
    compile_prompt = (
        "You are an expert résumé writer (domain: {domain}). The user wants their CV tailored "
        "to ONE specific job. From the job's requirements (role, must-have skills, "
        "responsibilities — given in the details/conversation) and the user's real background, "
        "produce: (1) a tailored professional summary aimed at this role, (2) a reordered key-"
        "skills line that surfaces the overlapping skills first, (3) achievement bullets "
        "rephrased to mirror the job's language WITHOUT inventing experience the user lacks, "
        "and (4) a 4-6 line cover note. Honestly flag any must-have the user does not yet meet "
        "and suggest how to close it. Never fabricate. Use cardType 'document'. Write in "
        "{language}." + _STRICT_JSON
    )

    def _preview(self, params: dict) -> dict:
        return {
            "cardType": "document",
            "title": "Tailored CV",
            "summary": "Share (or point me to) the job role and its key requirements and I'll "
                       "tailor your CV and a short cover note to match it — honestly, without "
                       "inventing experience you don't have.",
            "steps": [
                {"title": "Job details", "desc": "Role + must-have skills/responsibilities", "status": "pending"},
                {"title": "Tailor", "desc": "Rewrite CV + cover note to match", "status": "pending"},
            ],
        }


class LearningPlanBuilder(TaskAssistant):
    name = "learning_plan"
    description = "A re-skilling / upskilling roadmap for a chosen skill, grounded in real resources."
    compile_prompt = (
        "You are a career-development coach (domain: {domain}). Build a practical re-skilling "
        "roadmap for the skill/goal the user named, calibrated to their current level. Produce "
        "phased milestones (e.g. Foundations → Core → Applied → Portfolio), each with a "
        "realistic duration, concrete weekly actions, and what 'done' looks like. Recommend "
        "specific, real, well-known resources (courses, books, papers, docs) — if any are "
        "listed in the grounded knowledge/sources above, prefer and cite those; never invent "
        "titles, authors, or URLs. End with how to demonstrate the new skill (project / "
        "certification / contribution). Use cardType 'timeline'. Write in {language}."
        + _STRICT_JSON
    )

    def _preview(self, params: dict) -> dict:
        goal = params.get("skill") or params.get("goal") or "your target skill"
        log.debug("learning_plan_preview", has_skill=bool(params.get("skill")),
                  has_goal=bool(params.get("goal")))
        return {
            "cardType": "timeline",
            "title": f"Learning roadmap: {goal}",
            "summary": f"A phased plan to build {goal}, with milestones, timelines, and real "
                       f"courses/books/papers to study — plus a way to prove the skill at the end.",
            "steps": [
                {"title": "Foundations", "desc": "Core concepts and setup", "status": "pending"},
                {"title": "Applied practice", "desc": "Build and iterate on real exercises", "status": "pending"},
                {"title": "Demonstrate", "desc": "Project / certification to prove it", "status": "pending"},
            ],
        }


# Job application — fill everything except login/OTP/upload/submit (the digital-divide
# feature applied to hiring portals). The specific listing URL comes from the user / a
# job_search result and is surfaced on the card so they can open and finish it.
JOB_APPLICATION_FORM = FormAssistant(
    service="job_application",
    title="job application",
    portal_name="job portal",
    portal_url="",
    autofill=[
        FieldSpec("name", "Full name"),
        FieldSpec("email", "Email", required=False),
        FieldSpec("phone", "Phone", required=False),
        FieldSpec("target_role", "Role applying for"),
        FieldSpec("total_experience", "Total experience", required=False),
        FieldSpec("current_company", "Current/most recent employer", required=False),
        FieldSpec("key_skills", "Key skills"),
        FieldSpec("preferred_location", "Preferred location", required=False),
        FieldSpec("expected_ctc", "Expected CTC", required=False),
        FieldSpec("notice_period", "Notice period", required=False),
    ],
    user_only_steps=[
        "Log in to (or create) your account on the job portal — you do this, never Nipun",
        "Upload your résumé / tailored CV file to the application",
        "Review the auto-filled details, then click Submit yourself",
        "Enter any OTP the portal sends to confirm the application",
    ],
)


def register_career_assistants() -> None:
    """Register all career/jobs assistants so they are selectable by the orchestrator."""
    log.info("register_career_assistants_start")
    assistants = (ResumeBuilder(), TailorResume(), LearningPlanBuilder())
    try:
        for a in assistants:
            register_assistant(a)
            log.debug("assistant_registered", name=a.name)
        register_form(JOB_APPLICATION_FORM)
        log.debug("form_registered", service=JOB_APPLICATION_FORM.service,
                  autofill_fields=len(JOB_APPLICATION_FORM.autofill),
                  user_only_steps=len(JOB_APPLICATION_FORM.user_only_steps))
    except Exception as exc:
        log.error("register_career_assistants_failed",
                  error=str(exc), error_type=type(exc).__name__)
        raise
    log.info("register_career_assistants_done",
             assistants=len(assistants), forms=1)


register_career_assistants()
