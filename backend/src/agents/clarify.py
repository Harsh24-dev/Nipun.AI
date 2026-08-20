"""
Ask-back clarification — gather the specific facts a good answer needs BY ASKING,
not by pre-storing them.

Philosophy (per product direction): information needed only for one or two answers
should be asked for at answer time via a short FORM, then used just for that turn —
not persisted in the database "just in case". This is how a good assistant behaves:
when a request is under-specified for a personalized recommendation (crop advice with
no land/soil/location) or a task needs inputs (plan a trip), it asks a couple of
targeted questions instead of guessing.

How it works:
  * A small registry maps (domain, intent/keywords) → the slots needed for a good answer.
  * A slot is already "satisfied" if the user's stable profile has it OR the query text
    clearly provides it — so we never ask for what we already know.
  * If required slots remain unfilled, we return a `clarify` card carrying a typed form
    of ONLY the missing fields (capped at CLARIFY_MAX_FIELDS).
  * The frontend renders the form; the answers come back on the next /query call in
    `clarifications` and are folded into that turn's context (see orchestrator).

Deterministic and side-effect free — easy to test and cheap to run (no LLM call).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

import structlog

from src.config import settings

log = structlog.get_logger("agents.clarify")


@dataclass
class Slot:
    name: str
    label: str
    type: str = "text"                       # text | number | select | multiselect
    options: list[str] = field(default_factory=list)
    required: bool = True
    placeholder: str = ""
    # A slot is satisfied (so we DON'T ask) if any of these profile keys is set …
    profile_keys: tuple[str, ...] = ()
    # … or if the query already contains one of these patterns.
    query_patterns: tuple[str, ...] = ()

    def satisfied_by(
        self, query: str, profile: dict,
        answered: dict | None = None, history_text: str = "",
    ) -> bool:
        """A slot is satisfied — so we DON'T ask — when the detail is already known from
        ANY source the user has given us: their stable profile, an answer they gave earlier
        this conversation (``answered``), the current query, or something they said in a
        recent turn (``history_text``). This is what stops the assistant re-asking what it
        was just told."""
        for key in self.profile_keys:
            if profile.get(key) not in (None, "", [], {}):
                return True
        # Already answered this slot (by name or a mapped profile key) earlier this session.
        answered = answered or {}
        if answered.get(self.name) not in (None, "", [], {}):
            return True
        if any(answered.get(k) not in (None, "", [], {}) for k in self.profile_keys):
            return True
        # Present in the current query OR anywhere in the recent conversation text.
        haystack = f"{query}  {history_text}".lower()
        return any(re.search(p, haystack) for p in self.query_patterns)

    def to_field(self) -> dict:
        f = {"name": self.name, "label": self.label, "type": self.type,
             "required": self.required}
        if self.options:
            f["options"] = self.options
        if self.placeholder:
            f["placeholder"] = self.placeholder
        return f


# Money like "5 lakh", "₹50000", "2 crore", "10,000 rupees".
_MONEY = r"(₹|rs\.?|\binr\b|\d[\d,]*\s*(lakh|lac|crore|cr|thousand|k|rupees?|/-))"
_LAND = r"\d+\s*(acres?|bigha|hectares?|ha|guntha|katha)"
_DURATION = r"\b\d+\s*(years?|yrs?|months?|weeks?|days?)\b"
_PLACE_HINT = r"\b(in|at|near|for|from)\s+[a-z]"
_AGE = r"\b(\d{1,2})\s*(years?\s*old|yrs?\s*old|y/?o)\b|\bage\s*(is\s*)?\d{1,2}\b"


def _has(q: str, *words: str) -> bool:
    return any(w in q for w in words)


# A query that is purely informational/definitional ("what is X", "explain X") wants an
# ANSWER, not a form — never interrupt it with clarification. Actionable/personalized
# requests ("should I…", "for me", "I want/need/have", "plan…", "recommend") are the ones
# where a couple of details make the answer materially better.
_INFO_PATTERNS = (
    # A direct question opener (including contractions like "what's", "how's") — the user wants an
    # ANSWER to what they asked, not to fill a form first.
    r"^\s*(what'?s?|who'?s?|whom|when|where|why|which|how'?s?|whats|hows)\b",
    # Explanatory / predictive / estimative asks anywhere in the query — "expected", "how likely",
    # "predict", "based on current stats" etc. want a reasoned answer, not clarification.
    r"\b(explain|define|meaning of|difference between|tell me about|full form|what do you mean|"
    r"expected|will i|how likely|likelihood|chances? of|predict|estimate|forecast|projection|"
    r"based on (my|current|the)|how many|how much|how do i)\b",
    # Anything phrased as a question.
    r"\?\s*$",
)
_ACTION_MARKERS = (
    r"\b(should i|for me|help me|i want|i need|i have|i am planning|planning to|"
    r"plan (a|my|our)|recommend|suggest|best .*(for me|option|choice)|which (one|is best)|"
    r"eligible|apply|book|i earn|my (land|farm|budget|income|crop))\b",
)


def _looks_informational(query: str) -> bool:
    q = (query or "").lower()
    if any(re.search(p, q) for p in _ACTION_MARKERS):
        return False
    return any(re.search(p, q) for p in _INFO_PATTERNS)


# ── Reusable slots ────────────────────────────────────────────────────────────
_S_LOCATION = Slot("location", "Your district / state", "text",
                   placeholder="e.g. Nashik, Maharashtra",
                   profile_keys=("state", "district", "location"), query_patterns=(_PLACE_HINT,))
_S_STATE = Slot("state", "Your state", "text", placeholder="e.g. Bihar",
                profile_keys=("state",), query_patterns=(_PLACE_HINT,))
_S_AGE = Slot("age", "Your age", "number", query_patterns=(_AGE,), profile_keys=("age",))
_S_GENDER = Slot("gender", "Gender", "select",
                 options=["Male", "Female", "Other", "Prefer not to say"], profile_keys=("gender",))
_S_CATEGORY = Slot("category", "Social category", "select",
                   options=["General", "OBC", "SC", "ST", "EWS"], profile_keys=("category",))
_S_INCOME = Slot("annual_income", "Annual family income", "select",
                 options=["Below ₹1 lakh", "₹1–2.5 lakh", "₹2.5–5 lakh", "₹5–8 lakh", "Above ₹8 lakh"],
                 profile_keys=("annual_income", "income_bracket"))
_S_EDUCATION = Slot("education_level", "Highest education", "select",
                    options=["Below 10th", "10th", "12th", "ITI/Diploma", "Graduate", "Postgraduate", "PhD"],
                    profile_keys=("education_level",))

# ── Per-domain slot registry (intent/keyword aware) ───────────────────────────

_FARMING_CROP = [
    _S_LOCATION,
    Slot("land_size", "Land size", "text", placeholder="e.g. 5 acres",
         profile_keys=("land_size_acres",), query_patterns=(_LAND,)),
    Slot("soil_type", "Soil type", "select",
         options=["Alluvial", "Black", "Red", "Sandy", "Loamy", "Clay", "Laterite", "Not sure"],
         profile_keys=("soil_type",), query_patterns=(r"\bsoil\b", r"\balluvial\b")),
    Slot("water_source", "Irrigation / water source", "select", required=False,
         options=["Rainfed", "Canal", "Borewell", "Well", "Drip", "Sprinkler"],
         query_patterns=(r"\b(rainfed|canal|borewell|drip|irrigat)\b",)),
]
_FARMING_PEST = [
    Slot("crop", "Which crop", "text", placeholder="e.g. cotton",
         profile_keys=("current_crops",)),
    Slot("symptom", "What are you seeing", "text",
         placeholder="e.g. yellow leaves, holes, white spots"),
    _S_LOCATION,
]

_FINANCE_INVEST = [
    Slot("amount", "Amount to invest", "text", placeholder="e.g. ₹5 lakh", query_patterns=(_MONEY,)),
    Slot("horizon", "For how long?", "select",
         options=["Less than 1 year", "1–3 years", "3–5 years", "5+ years"],
         query_patterns=(_DURATION, r"\b(short|long)[- ]term\b")),
    Slot("risk", "Risk you're comfortable with", "select",
         options=["Low (safety first)", "Medium (balanced)", "High (growth)"],
         query_patterns=(r"\b(low|medium|high|safe|aggressive)\s*risk\b", r"\brisk[- ]free\b")),
    Slot("mode", "Preference", "select", required=False,
         options=["No preference", "Online / app", "Bank / offline", "Government schemes only"]),
]
_FINANCE_LOAN = [
    Slot("loan_purpose", "Loan for", "select",
         options=["Home", "Vehicle", "Business", "Education", "Agriculture", "Personal", "Gold"]),
    Slot("amount", "Loan amount needed", "text", placeholder="e.g. ₹3 lakh", query_patterns=(_MONEY,)),
    Slot("tenure", "Repayment period", "select",
         options=["Up to 1 year", "1–3 years", "3–5 years", "5–15 years", "15+ years"],
         query_patterns=(_DURATION,)),
    Slot("monthly_income", "Monthly income", "text", required=False, placeholder="e.g. ₹30,000"),
]
_FINANCE_INSURANCE = [
    Slot("insurance_type", "Type of insurance", "select",
         options=["Health", "Life / Term", "Vehicle", "Crop", "Accident", "Home"]),
    _S_AGE,
    Slot("cover_for", "Cover for", "select",
         options=["Just me", "Me + spouse", "Whole family", "Parents"]),
]
_FINANCE_TAX = [
    Slot("annual_income", "Annual income", "text", placeholder="e.g. ₹9 lakh", query_patterns=(_MONEY,)),
    Slot("regime", "Tax regime", "select", options=["Old regime", "New regime", "Not sure"]),
    Slot("deductions", "Investments/deductions you have", "text", required=False,
         placeholder="e.g. 80C, home loan, HRA"),
]

_LEGAL = [
    Slot("matter_type", "Type of matter", "select",
         options=["Property/land", "Family/marriage", "Consumer", "Employment", "Criminal",
                  "Tenancy/rent", "Cheque/loan", "Other"]),
    _S_STATE,
    Slot("stage", "Current stage", "select",
         options=["Just need to understand my rights", "Received a notice", "Want to file a complaint",
                  "Case already filed", "Court hearing ongoing"]),
]

_SCHEME = [_S_AGE, _S_GENDER, _S_CATEGORY, _S_INCOME,
           Slot("occupation", "Occupation", "text", required=False,
                profile_keys=("occupation",), placeholder="e.g. farmer, student")]

_CAREER = [
    Slot("current_status", "Current status", "select",
         options=["Student", "Working", "Unemployed", "Self-employed / business"]),
    _S_EDUCATION,
    Slot("experience_years", "Years of experience", "select", required=False,
         options=["None / fresher", "0–2 years", "2–5 years", "5–10 years", "10+ years"]),
    Slot("goal", "What you want", "text", placeholder="e.g. switch to IT, government job, higher pay"),
]

_JOBS = [
    _S_EDUCATION,
    _S_LOCATION,
    Slot("job_type", "Job type", "select", options=["Government", "Private", "Either"]),
    Slot("sector", "Preferred field", "text", required=False, placeholder="e.g. banking, teaching, IT"),
]

_STUDENT_LEARN = [
    Slot("level", "Your level", "select",
         options=["Class 6–10", "Class 11–12", "Undergraduate", "Postgraduate", "PhD / researcher",
                  "Self-learner"],
         profile_keys=("education_level",)),
    Slot("purpose", "Purpose", "select",
         options=["Exam preparation", "School/college project", "Just curious", "Deep research", "Career/skill"]),
    Slot("depth", "How deep", "select",
         options=["Simple basics", "Working knowledge", "In-depth / advanced"]),
    Slot("subject", "Topic / subject", "text", required=False, placeholder="e.g. machine learning"),
]

_DOCUMENTS = [
    Slot("document_type", "Which document", "select",
         options=["Aadhaar", "PAN", "Passport", "Driving Licence", "Ration Card", "Voter ID",
                  "Birth Certificate", "Income Certificate", "Caste Certificate", "Domicile", "Other"]),
    Slot("action", "What you need", "select",
         options=["Apply new", "Update/correct", "Lost/reprint", "Link/verify", "Check status"]),
    _S_STATE,
]

_GOVERNANCE = [
    Slot("service", "Which service / issue", "text", placeholder="e.g. pension not received, water supply"),
    _S_STATE,
    Slot("department", "Department (if known)", "text", required=False,
         placeholder="e.g. municipal, revenue, electricity"),
]

_TRAVEL_PLAN = [
    Slot("destination", "Destination", "text", placeholder="e.g. Manali",
         query_patterns=(r"\bto\s+[a-z]",)),
    Slot("dates", "When / how many days", "text", placeholder="e.g. 5 days in December",
         query_patterns=(r"\b(\d+\s*(day|days|night|week))\b",
                         r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)")),
    Slot("budget", "Budget", "text", placeholder="e.g. ₹20,000", query_patterns=(_MONEY,)),
    Slot("travelers", "Who's travelling", "text", required=False, placeholder="e.g. 2 adults, 1 child"),
    Slot("origin", "Travelling from", "text", required=False,
         profile_keys=("state", "district"), placeholder="e.g. Pune"),
]

_BOOKING = [
    Slot("what", "What to book", "text", placeholder="e.g. train ticket, doctor appointment"),
    Slot("when", "Date / time", "text", placeholder="e.g. 12 Aug, morning", query_patterns=(_DURATION,)),
    Slot("where", "From → to / location", "text", required=False, placeholder="e.g. Delhi to Jaipur"),
    Slot("quantity", "How many", "text", required=False, placeholder="e.g. 2 tickets"),
]

_SHOPPING = [
    Slot("budget", "Your budget", "text", placeholder="e.g. ₹20,000", query_patterns=(_MONEY,)),
    Slot("brand_preference", "Any brand preference", "text", required=False,
         placeholder="e.g. Samsung, or no preference"),
    Slot("priority", "What matters most", "select", required=False,
         options=["Lowest price", "Best reviews/quality", "Fast delivery", "Long warranty"]),
    Slot("must_haves", "Any must-have features", "text", required=False,
         placeholder="e.g. 5G, 8GB RAM, front-load"),
]


def slots_for(domain: str, intent: str, query: str) -> list[Slot]:
    """Return the candidate slots for a query, or [] when clarification doesn't apply.

    Intent/keyword-aware: each domain routes to the slot set matching the query's task
    (e.g. finance → invest vs loan vs insurance vs tax). Returning [] hands off to the
    LLM expert intake (for CLARIFY_LLM_DOMAINS) or answers directly."""
    d, i, q = (domain or "").lower(), (intent or "").lower(), (query or "").lower()

    if d == "farming":
        if _has(q, "pest", "disease", "insect", "fungus", "rot", "dying", "yellow leaf",
                "spots", "bug", "worm") or "pest" in i:
            return _FARMING_PEST
        if _has(q, "crop", "sow", "grow", "plant", "cultivat", "harvest", "which crop",
                "what to grow", "season") or "crop" in i:
            return _FARMING_CROP
        return []

    if d == "finance":
        if _has(q, "loan", "emi", "borrow", "credit", "mudra", "kisan credit"):
            return _FINANCE_LOAN
        if _has(q, "insurance", "insure", "policy", "premium", "cover", "bima"):
            return _FINANCE_INSURANCE
        if _has(q, "tax", "itr", "80c", "deduction", "return filing", "income tax"):
            return _FINANCE_TAX
        if _has(q, "invest", "mutual fund", "sip", "where should i put", "grow my money",
                "savings", "fd", "ppf", "stock", "shares") or "invest" in i:
            return _FINANCE_INVEST
        return []

    if d == "legal" and _has(q, "case", "court", "rights", "sue", "legal", "notice", "dispute",
                             "complaint", "fir", "divorce", "property", "cheque", "fraud", "police"):
        return _LEGAL

    if d == "scheme" and _has(q, "eligib", "qualify", "which scheme", "yojana", "scheme for me",
                              "am i eligible", "benefit", "subsidy", "apply for"):
        return _SCHEME

    if d == "career" and _has(q, "career", "job change", "switch", "upskill", "course", "growth",
                              "should i", "future", "salary", "promotion", "guidance"):
        return _CAREER

    if d == "jobs" and _has(q, "job", "vacancy", "recruitment", "hiring", "apply", "opening",
                            "sarkari", "naukri", "employment"):
        return _JOBS

    if d == "student" and _has(q, "learn", "explain", "study", "understand", "research", "prepare",
                               "exam", "teach", "concept", "how does", "what is", "syllabus"):
        return _STUDENT_LEARN

    if d == "documents" and _has(q, "document", "aadhaar", "pan", "passport", "licence", "license",
                                 "certificate", "ration", "voter", "apply", "renew", "correction"):
        return _DOCUMENTS

    if d == "governance" and _has(q, "grievance", "complaint", "service", "pension", "not received",
                                  "portal", "department", "municipal", "corruption", "delay"):
        return _GOVERNANCE

    if d == "travel" or _has(q, "trip", "itinerary", "tour", "vacation", "holiday", "visit"):
        return _TRAVEL_PLAN

    # Shopping can arrive under any domain (usually general) — trigger on intent keywords.
    if _has(q, "buy", "best product", "which phone", "which laptop", "cheapest", "best price",
            "should i buy", "recommend a", "compare price", "best deal", "shopping", "purchase"):
        return _SHOPPING

    if d == "booking" or _has(q, "book", "reserve", "appointment", "ticket", "slot"):
        return _BOOKING

    return []


_SKIP_LABEL = "Skip & get a general answer"


def _build_clarify_card(fields: list[dict], language: str, summary: str | None = None) -> dict:
    """Assemble a deliverable `clarify` card from a list of form-field dicts.

    The form is always SKIPPABLE — a prominent "get a general answer" path means the user
    never hits a dead-end and leaves. Fields are concrete selects/options wherever possible
    so answering is one tap, not typing."""
    return {
        "cardType": "clarify",
        "language": language,
        "title": "Want a tailored answer?",
        "summary": summary or (
            "Answer a couple of quick details for a personalized answer — or skip for a "
            "general one. Your answers are used only for this reply and not saved."
        ),
        "form": {
            "submitLabel": "Get my tailored answer",
            "fields": fields,
            "allowSkip": True,
            "skipLabel": _SKIP_LABEL,
        },
        # Quick-reply hints for clients that don't render the form — the skip option is
        # always present so there is always a one-tap way forward.
        "options": [f["label"] for f in fields] + [_SKIP_LABEL],
        "confidence": 1.0,
        "abstained": False,
        "clarify": True,
    }


def assess_clarification(
    query: str, domain: str, intent: str, profile: dict, language: str = "en",
    correlation_id: str = "", answered: dict | None = None, history_text: str = "",
) -> dict | None:
    """Fast, deterministic clarification via the slot registry (no LLM). Returns a
    `clarify` card when required details are missing, else None.

    `answered` holds details the user has already given this conversation and `history_text`
    is the recent conversation text — both count as "known" so we never re-ask them."""
    if not settings.CLARIFY_ENABLED:
        return None
    # Never interrupt a purely informational/definitional question with a form.
    if _looks_informational(query):
        return None
    profile = profile or {}
    answered = answered or {}
    slots = slots_for(domain, intent, query)
    if not slots:
        return None

    missing = [s for s in slots
               if s.required and not s.satisfied_by(query, profile, answered, history_text)]
    if not missing:
        return None

    # Include a couple of useful optional slots if we're already asking, but stay capped.
    optional = [s for s in slots
                if not s.required and not s.satisfied_by(query, profile, answered, history_text)]
    chosen = (missing + optional)[: settings.CLARIFY_MAX_FIELDS]
    log.info("clarification_requested", method="rules", domain=domain, intent=intent,
             asked=[s.name for s in chosen], correlation_id=correlation_id)
    return _build_clarify_card([s.to_field() for s in chosen], language)


# ── Dynamic expert intake (LLM) ───────────────────────────────────────────────
# When the deterministic registry doesn't cover a query, a fast-LLM "expert" decides
# whether a few targeted questions would materially improve the answer — the way a
# senior doctor takes a history, an advisor scopes risk/horizon, or a research mentor
# pitches depth to the learner's level. This is the shift from "RAG bot" to "expert".

_EXPERT_PERSONAS: dict[str, str] = {
    "health": "a careful senior physician taking a brief patient history before advising",
    "finance": "a SEBI-registered financial advisor scoping an investment before recommending",
    "legal": "a senior advocate scoping the facts of a matter before advising",
    "farming": "an experienced agronomist advising a farmer on their specific plot",
    "career": "a seasoned career counsellor understanding the person before guiding",
    "student": "a research mentor gauging the learner's level and purpose before teaching",
    "scheme": "a welfare officer checking eligibility details before recommending schemes",
    "jobs": "an employment counsellor matching the person to the right openings",
    "documents": "a facilitation-centre officer scoping exactly what document help is needed",
    "governance": "a public-grievance officer capturing the details needed to help",
    "travel": "an expert travel planner scoping the trip before building an itinerary",
    "booking": "a booking concierge confirming the exact details before proceeding",
    "general": "a domain expert who asks only what is essential before answering",
}

_INTAKE_SYSTEM = """You are {persona}. Read the user's request. Decide whether asking a
FEW specific questions would MATERIALLY change your answer's accuracy or safety — exactly
as a good expert asks before advising. If you can already answer well, DO NOT ask.

Rules:
- Default to NOT asking. Only set need_clarification=true when a general answer would be
  materially wrong, unsafe, or useless without the detail. If a good general answer is
  possible, answer directly (need_clarification=false).
- Purely informational/definitional questions ("what is X", "explain X") → never ask.
- Ask at most {max_q} questions. Prefer `select`/`multiselect` with concrete options.
- Never ask for anything already stated in the request or in KNOWN ABOUT USER.
- Health: ask key symptoms, duration, severity, triggers/diet, existing conditions/meds.
- Research/learning: ask the learner's level (school/college/PhD), purpose, and desired
  depth so the answer is pitched correctly.
- Finance: ask amount, time horizon, risk comfort, and any constraints (e.g. online/offline).
- Keep questions short and in the user's language.
Respond ONLY as JSON:
{{"need_clarification": true/false, "reason": "one short line",
  "questions": [{{"name": "snake_case", "label": "question text", "type": "text|number|select|multiselect", "options": ["..."], "required": true/false}}]}}"""


def _normalize_field(q: dict) -> dict | None:
    name = str(q.get("name") or "").strip()
    label = str(q.get("label") or "").strip()
    if not name or not label:
        return None
    ftype = q.get("type") if q.get("type") in ("text", "number", "select", "multiselect") else "text"
    field_dict: dict = {"name": name, "label": label, "type": ftype,
                        "required": bool(q.get("required", True))}
    opts = q.get("options")
    if ftype in ("select", "multiselect") and isinstance(opts, list) and opts:
        field_dict["options"] = [str(o) for o in opts][:8]
    elif ftype in ("select", "multiselect"):
        field_dict["type"] = "text"   # a choice field with no options is just text
    return field_dict


def _known_about_user(profile: dict, answered: dict, history_text: str) -> str:
    """A compact, complete 'what we already know' brief for the intake LLM, drawn from
    the stable profile, everything the user has answered this conversation, and the
    recent conversation text — so the expert never asks for something already on record."""
    facts = {}
    for k, v in (profile or {}).items():
        if v not in (None, "", [], {}) and not str(k).startswith("_"):
            facts[k] = v
    # Session answers win over profile (more recent / correction).
    for k, v in (answered or {}).items():
        if v not in (None, "", [], {}) and not str(k).startswith("_"):
            facts[k] = v
    known = "; ".join(f"{k}={v}" for k, v in facts.items())
    recent = (history_text or "").strip()
    if recent:
        known = (known + " | " if known else "") + f'recently said: "{recent[:400]}"'
    return known or "(nothing known)"


# Sentinel returned by the intake helper when the LLM path could NOT reach a decision
# (disabled, unreachable, or errored) — as opposed to reaching the decision "don't ask"
# (None). plan_clarification uses this to know when it is safe to fall back to the canned
# slot registry WITHOUT overriding a genuine LLM decision.
_LLM_UNAVAILABLE = object()


async def _llm_intake_decision(
    query: str, domain: str, intent: str, profile: dict, language: str = "en",
    correlation_id: str = "", answered: dict | None = None, history_text: str = "",
):
    """Run the fast-LLM expert intake and report BOTH the outcome and whether the LLM
    actually decided. Returns:
      * a `clarify` card (dict) — the LLM decided targeted questions are needed;
      * ``None``               — the LLM successfully decided to answer directly (do NOT
                                 fall back to canned slots, that would override the model);
      * ``_LLM_UNAVAILABLE``   — the LLM path is disabled/unreachable/errored, so the
                                 caller may fall back to the deterministic slot registry.
    Never raises."""
    if not settings.CLARIFY_USE_LLM:
        return _LLM_UNAVAILABLE
    # A purely informational/definitional question wants an answer, not a form — this is a
    # deterministic "don't ask" decision that prevents over-asking, so we return None (not the
    # unavailable sentinel) and do NOT let canned slots re-introduce a form.
    if _looks_informational(query):
        return None
    try:
        from src.llm.router import route_completion

        persona = _EXPERT_PERSONAS.get(domain, _EXPERT_PERSONAS["general"])
        known = _known_about_user(profile or {}, answered or {}, history_text)
        resp = await route_completion(
            messages=[
                {"role": "system",
                 "content": _INTAKE_SYSTEM.format(persona=persona, max_q=settings.CLARIFY_MAX_FIELDS)},
                {"role": "user",
                 "content": f"Answer in {language}.\nQUESTION: {query}\nKNOWN ABOUT USER: {known}"},
            ],
            override_tier="fast",
            correlation_id=correlation_id,
        )
        content = resp.content.strip().strip("`").replace("json", "", 1).strip()
        data = json.loads(content)
        if not data.get("need_clarification"):
            return None
        fields = [f for f in (_normalize_field(q) for q in data.get("questions", []) if isinstance(q, dict)) if f]
        # Belt-and-suspenders: never render a field the user already answered this session,
        # even if the model asked for it anyway.
        known_names = {k for k, v in (answered or {}).items() if v not in (None, "", [], {})}
        fields = [f for f in fields if f["name"] not in known_names]
        fields = fields[: settings.CLARIFY_MAX_FIELDS]
        if not fields:
            # The model wanted to ask but nothing usable survived — treat as a decision to
            # answer directly rather than falling back to a canned form.
            return None
        log.info("clarification_requested", method="llm", domain=domain, intent=intent,
                 asked=[f["name"] for f in fields], reason=data.get("reason"),
                 correlation_id=correlation_id)
        return _build_clarify_card(fields, language)
    except Exception as exc:
        log.warning("llm_intake_failed", domain=domain, error=str(exc), correlation_id=correlation_id)
        return _LLM_UNAVAILABLE


async def llm_intake(
    query: str, domain: str, intent: str, profile: dict, language: str = "en",
    correlation_id: str = "", answered: dict | None = None, history_text: str = "",
) -> dict | None:
    """Ask a fast-LLM expert whether targeted questions are needed, and generate them.
    Returns a `clarify` card or None. Never raises — degrades to 'answer directly'.

    Thin wrapper over ``_llm_intake_decision`` that preserves the original ``dict | None``
    return shape (the unavailable sentinel collapses to None) for any external caller."""
    decision = await _llm_intake_decision(
        query, domain, intent, profile, language, correlation_id,
        answered=answered, history_text=history_text)
    return decision if isinstance(decision, dict) else None


async def plan_clarification(
    query: str, domain: str, intent: str, profile: dict, language: str = "en",
    correlation_id: str = "", answered: dict | None = None, history_text: str = "",
    allow_llm: bool = True,
) -> dict | None:
    """The clarification decision. The LLM expert intake is the PRIMARY decision-maker for
    ALL domains — the model, not a hardcoded per-domain checklist, decides what (if anything)
    still needs asking. The canned slot registry is only a FALLBACK, used when the LLM path is
    disabled/unreachable/errored (or when `allow_llm=False`). Returns a `clarify` card or None.

    `answered` (details already given this conversation) and `history_text` (recent
    conversation) are treated as already-known, so we never re-ask them. `allow_llm=False`
    disables the LLM expert-intake (used for follow-ups, where the topic is already established
    and the intake would otherwise re-ask what the prior turn covered) — in that case we use
    the deterministic slot registry alone."""
    if not settings.CLARIFY_ENABLED:
        return None
    # PRIMARY path: let the LLM expert decide, for every domain. A successful decision — whether
    # "ask these" (card) or "answer directly" (None) — is authoritative and is NOT second-guessed
    # by the canned slots. Only when the LLM path cannot decide do we fall back.
    if allow_llm:
        decision = await _llm_intake_decision(
            query, domain, intent, profile, language, correlation_id,
            answered=answered, history_text=history_text)
        if isinstance(decision, dict):
            return decision          # LLM chose to ask
        if decision is None:
            return None              # LLM decided to answer directly — do not override with slots
        # decision is _LLM_UNAVAILABLE → fall through to the deterministic fallback below.
    # FALLBACK: fast deterministic slot registry (zero latency). Used when the LLM is
    # unavailable/errored, or when the caller disabled the LLM path (follow-ups).
    return assess_clarification(query, domain, intent, profile, language, correlation_id,
                                answered=answered, history_text=history_text)
