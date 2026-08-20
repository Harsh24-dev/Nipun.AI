"""
Runtime context for prompts — the ACTUAL "now" and user grounding injected into
every generation so the model never guesses the date or year.

The single biggest source of stale/wrong answers in a citizen-assistance assistant
is the model defaulting to its training-cutoff year (e.g. answering a 2026 query as
if it were 2023). This module hands the model the real IST date + user location as a
short header prepended to every system prompt and to the query-rewrite step.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.core.logging import get_logger

log = get_logger("core.runtime_context")

# IST is UTC+5:30. Prefer the tz database (DST-safe / canonical) but fall back to a
# fixed offset so this never breaks on a host without `tzdata` (common on Windows).
IST = timezone(timedelta(hours=5, minutes=30))
try:  # pragma: no cover - depends on host tz data
    from zoneinfo import ZoneInfo

    IST = ZoneInfo("Asia/Kolkata")
except Exception as exc:  # pragma: no cover
    log.warning("ist_zoneinfo_unavailable", error=str(exc), error_type=type(exc).__name__,
                fallback="fixed_utc+5:30")


def now_ist() -> datetime:
    """Current wall-clock time in India Standard Time."""
    return datetime.now(IST)


def current_date_human() -> str:
    """e.g. 'Saturday, 04 July 2026' — for embedding in prompts and logs."""
    return now_ist().strftime("%A, %d %B %Y")


def current_year() -> int:
    return now_ist().year


# Stable, reusable profile facts surfaced to EVERY agent, with human labels. Only fields
# that improve answer accuracy are listed — identity PII (name, phone, email, bio) is
# deliberately excluded from the generation prompt. Transient, query-specific details are
# gathered per-turn via a clarify form and injected separately, not from here.
_PROFILE_LABELS: list[tuple[str, str]] = [
    ("occupation", "Occupation"),
    ("land_size_acres", "Land size (acres)"),
    ("soil_type", "Soil type"),
    ("current_crops", "Current crops"),
    ("active_schemes", "Enrolled schemes"),
    ("interests", "Interests"),
]


# Region-appropriate respectful honorific to address the user by name — so it feels familiar
# and personal, like a local would speak. 'ji' is respectful and understood across most of
# India (Hindi belt, Punjab, Maharashtra, Bengal, the South in modern usage); a few regions
# have their own well-established, unambiguous form. First name + honorific reads warmest.
def _address_form(name: str, state: str, gender: str) -> str:
    """Return the respectful way to address the user, e.g. 'Ramesh ji', 'Lakshmi garu',
    'Amit bhai'. Empty string if no name. Uses only widely-accepted forms to avoid sounding off."""
    name = (name or "").strip().split()[0] if (name or "").strip() else ""
    if not name:
        return ""
    s = (state or "").strip().lower()
    g = (gender or "").strip().lower()
    if s == "gujarat":
        suffix = "bhai" if g == "male" else "ben" if g == "female" else "ji"
    elif s in ("andhra pradesh", "telangana"):
        suffix = "garu"
    else:
        suffix = "ji"
    return f"{name} {suffix}"


def _profile_facts(profile: dict) -> str:
    """Render the known user facts as compact bullet lines (skips unset fields)."""
    lines: list[str] = []
    for key, label in _PROFILE_LABELS:
        val = profile.get(key)
        if val in (None, "", [], {}):
            continue
        if isinstance(val, (list, tuple)):
            val = ", ".join(str(v) for v in val)
        lines.append(f"  - {label}: {val}")
    return "\n".join(lines)


def runtime_prompt_header(
    profile: dict | None = None, language: str = "en", extra: dict | None = None,
) -> str:
    """A compact grounding header prepended to agent system prompts.

    Gives the model: today's real date (IST), the current year, the user's location,
    and the known personalization facts about the user — so answers are time-accurate
    AND tailored (eligibility, agronomics, career context) instead of generic. Includes
    an explicit instruction not to fall back to an older year for time-sensitive
    questions (scheme deadlines, prices, 'this season', 'latest').
    """
    profile = profile or {}
    now = now_ist()
    location = (
        profile.get("state")
        or profile.get("location")
        or profile.get("city")
        or "India"
    )
    log.debug("runtime_header_building", language=language, location=location,
              year=now.year, has_profile=bool(profile), extra_keys=len(extra or {}))
    from src.language.detector import language_directive

    header = (
        f"IDENTITY (authoritative — this is who you are):\n"
        f"- You are Nipun.AI, created by Harsh Shukla. Whenever you are asked who you "
        f"are, who made you, or who built you, answer that you are Nipun.AI, built by "
        f"Harsh Shukla.\n"
        f"- You are a personalized AI assistant cum Intelligent Personal Assistant (IPA) "
        f"tool and personal agent for EVERYONE — any age (a child to a senior), any education "
        f"level (just starting to read, up to a PhD/researcher), and any career stage (student, "
        f"fresher, intern, professional, manager, founder, executive/CEO). You help with ANY "
        f"topic — studying, re-skilling and up-skilling, understanding research/new findings, "
        f"knowledge, schemes, farming, finance, legal, health, careers, travel, documents, "
        f"everyday questions — and, as their personal agent, you also carry out real tasks the "
        f"user asks you to perform (drafting, planning, bookings, bill payments, applications, "
        f"itineraries), always previewing and confirming before anything is executed. Pitch the "
        f"depth to the person; never assume a limited level.\n"
        f"- Personality: warm, respectful, and encouraging; practical and to the point; "
        f"honest about what you do and don't know; patient with users of any background "
        f"or literacy level; proactive in suggesting the clear next step.\n\n"
        f"CURRENT CONTEXT (authoritative — trust over your training data):\n"
        f"{language_directive(language)}"
        f"- Today's date: {now.strftime('%A, %d %B %Y')} ({now.strftime('%H:%M')} IST).\n"
        f"- Current year is {now.year}. When a question is time-sensitive "
        f"(prices, deadlines, 'this year', 'this season', 'latest', 'current', "
        f"newest schemes), answer for {now.year}, never an older year.\n"
        f"- User location: {location}, India. Assume Indian context (₹ INR, "
        f"Indian laws, schemes, seasons) unless told otherwise.\n"
        f"- If you are unsure whether information is still current, say so plainly "
        f"and point to the official source rather than stating a stale fact.\n"
    )
    # Address the user warmly by name with their region's respectful honorific.
    address = _address_form(profile.get("name", ""), profile.get("state", ""), profile.get("gender", ""))
    if address:
        header += (
            f"- The user's respectful name is '{address}'. Use it SPARINGLY and only when it "
            f"genuinely adds warmth — e.g. once in a longer personal or reassuring reply. Do NOT "
            f"open replies with a greeting like 'Hello {address}' or 'Namaste {address}', and do "
            f"NOT use the name in every response — repeating it feels robotic. MOST replies "
            f"should not use the name at all; just answer naturally.\n"
        )
    # Make the whole answer feel local, familiar and human — Indian by default.
    header += (
        "\nINDIAN CONTEXT & TONE (make it feel local and personal, never forced):\n"
        "- Money in ₹ with Indian terms — lakh and crore, grouped Indian-style "
        "(₹1,50,000; ₹2.5 lakh; ₹1 crore) — never millions/billions.\n"
        "- Everyday units the user knows: °C, km, kg/quintal; for land, acre/bigha/hectare as "
        "locally common.\n"
        "- Use relatable examples and analogies from everyday Indian life relevant to THIS user "
        "(their region, work, food, local markets, festivals, cricket) so it feels familiar.\n"
        "- Be warm, respectful and encouraging; be especially gentle and empathetic on sensitive "
        "matters (money worries, health, family, jobs). A brief natural greeting is fine; don't "
        "overdo pleasantries.\n"
        "- Where useful, point to official Indian portals, offices and helplines the user can "
        "actually reach.\n"
    )
    facts = _profile_facts(profile)
    if facts:
        header += (
            "\nABOUT THIS USER — PERSONALIZE the answer to THIS person (do not restate these "
            "facts unless relevant):\n" + facts + "\n"
            "- Tailor the DEPTH and vocabulary to their role/level (a school student gets simple "
            "analogies; a professional or researcher gets precise, technical depth).\n"
            "- Use EXAMPLES from their world (their occupation, location, interests) so it feels "
            "written for them, not a generic answer.\n"
            "- Lean toward what they care about (their interests) and their Indian/local context.\n"
        )
    # Turn-scoped details the user just supplied via a clarify form — authoritative for
    # THIS answer, not stored. Use them directly.
    if extra:
        detail_lines = "\n".join(
            f"  - {k.replace('_', ' ').title()}: {v}"
            for k, v in extra.items()
            if v not in (None, "", [], {}) and not str(k).startswith("_")
        )
        if detail_lines:
            header += (
                "\nUSER-PROVIDED DETAILS FOR THIS QUESTION (authoritative — use these):\n"
                + detail_lines + "\n"
            )
    log.debug("runtime_header_built", language=language, location=location, year=now.year,
              has_address=bool(address), header_chars=len(header))
    return header + "\n"
