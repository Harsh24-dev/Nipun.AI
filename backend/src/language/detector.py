"""
Language detection for 7 Indian languages + English, with code-switching support.

Strategy:
  1. Script-range analysis  → fast, catches pure-script text and code-switching
  2. lingua-py detection    → probabilistic, handles ambiguous Devanagari (hi vs mr)

Returns a language code like "hi", "ta", "hi+en" (Hinglish), etc.
"""

import re
from functools import lru_cache

import structlog

from src.language.constants import (
    LANGUAGES,
    SCRIPT_RANGES,
    SCRIPT_TO_LANG,
)

log = structlog.get_logger("language.detector")

# Minimum fraction of a script to be considered "present" in text
_SCRIPT_THRESHOLD = 0.10


def _analyse_scripts(text: str) -> dict[str, float]:
    """Return fraction of alphabetic characters belonging to each script."""
    counts: dict[str, int] = {s: 0 for s in SCRIPT_RANGES}
    total = 0

    for char in text:
        if not char.isalpha():
            continue
        cp = ord(char)
        total += 1
        for script, ranges in SCRIPT_RANGES.items():
            if any(lo <= cp <= hi for lo, hi in ranges):
                counts[script] += 1
                break

    if total == 0:
        return {s: 0.0 for s in SCRIPT_RANGES}
    return {s: c / total for s, c in counts.items()}


def _detect_code_switch(script_fracs: dict[str, float]) -> str | None:
    """
    If text has >= 10% Latin AND >= 10% of an Indic script → code-switched.
    Returns code like "hi+en", "ta+en" or None.
    """
    latin_frac = script_fracs.get("latin", 0.0)
    if latin_frac < _SCRIPT_THRESHOLD:
        return None

    indic_scripts = {s: f for s, f in script_fracs.items() if s != "latin" and f >= _SCRIPT_THRESHOLD}
    if not indic_scripts:
        return None

    dominant_indic = max(indic_scripts, key=indic_scripts.get)  # type: ignore[arg-type]
    primary_langs = SCRIPT_TO_LANG.get(dominant_indic, [])
    if not primary_langs:
        return None

    # For Devanagari (hi vs mr) we'll refine via lingua below;
    # for code-switching we just pick hi as default
    base = primary_langs[0]
    return f"{base}+en"


@lru_cache(maxsize=1)
def get_detector():
    """Build the lingua detector once and cache it (loads language models ~200ms)."""
    from lingua import Language, LanguageDetectorBuilder

    lang_map = {
        "en": Language.ENGLISH,
        "hi": Language.HINDI,
        "pa": Language.PUNJABI,
        "ta": Language.TAMIL,
        "te": Language.TELUGU,
        "mr": Language.MARATHI,
        "gu": Language.GUJARATI,
    }
    lingua_langs = list(lang_map.values())
    detector = LanguageDetectorBuilder.from_languages(*lingua_langs).with_minimum_relative_distance(0.15).build()
    return detector, lang_map


def detect_language(text: str) -> str:
    """
    Detect the language of text. Returns a BCP-47 code.

    Examples:
      "खेती में कौन सी फसल लगाएं" → "hi"
      "tell me about bail" → "en"
      "bail kaise milti hai yaar" → "hi+en"
      "என்ன செய்வது" → "ta"
    """
    if not text or not text.strip():
        return "en"

    text_sample = text[:500]

    # Step 1: Script analysis
    script_fracs = _analyse_scripts(text_sample)
    dominant_scripts = {s: f for s, f in script_fracs.items() if f >= _SCRIPT_THRESHOLD}

    # Pure Latin → likely English
    if dominant_scripts == {"latin": script_fracs["latin"]} or (
        not dominant_scripts and script_fracs.get("latin", 0) > 0.5
    ):
        return "en"

    # Unambiguous single Indic script (not Devanagari)
    for script, langs in SCRIPT_TO_LANG.items():
        if script == "devanagari":
            continue
        if script in dominant_scripts and len(langs) == 1:
            # Check for code-switching
            cs = _detect_code_switch(script_fracs)
            return cs if cs else langs[0]

    # Code-switching check
    cs = _detect_code_switch(script_fracs)
    if cs:
        return cs

    # Step 2: lingua for Devanagari disambiguation (hi vs mr) and edge cases
    try:
        detector, lang_map = get_detector()
        result = detector.detect_language_of(text_sample)
        if result is not None:
            reverse_map = {v: k for k, v in lang_map.items()}
            detected = reverse_map.get(result, "hi")
            log.debug("language_detected", text_preview=text_sample[:50], language=detected)
            return detected
    except Exception as exc:
        log.warning("lingua_detection_failed", error=str(exc))

    # Fallback: if Devanagari dominant, return hi
    if script_fracs.get("devanagari", 0) >= _SCRIPT_THRESHOLD:
        return "hi"

    return "en"


def detect_language_confidence(text: str) -> tuple[str, float]:
    """Returns (language_code, confidence_0_to_1)."""
    try:
        detector, lang_map = get_detector()
        results = detector.compute_language_confidence_values(text[:500])
        if results:
            reverse_map = {v: k for k, v in lang_map.items()}
            best = results[0]
            lang = reverse_map.get(best.language, "en")
            return lang, best.value
    except Exception:
        pass
    return detect_language(text), 0.8


def is_code_switched(text: str) -> bool:
    lang = detect_language(text)
    return "+" in lang


# ── Response-language resolution (authoritative, per-turn) ────────────────────
#
# The response MUST be written in the language the user wants. Priority:
#   1. an explicit caller override (the `language` field in the API request), then
#   2. an in-text request ("answer in Tamil", "मुझे तमिल में बताओ"), then
#   3. the language the query itself is written in (deterministic detection).
# The response language is NEVER an LLM guess — that was the bug that made every
# farming answer come back in Hindi regardless of the question's language.

_NAME_TO_CODE: dict[str, str] = {info.name_en.lower(): code for code, info in LANGUAGES.items()}

# Language name aliases (English + native + common transliterations) → code.
_LANG_ALIASES: dict[str, str] = {
    "english": "en", "angrezi": "en", "अंग्रेजी": "en", "इंग्लिश": "en",
    "hindi": "hi", "हिंदी": "hi", "हिन्दी": "hi",
    "punjabi": "pa", "panjabi": "pa", "ਪੰਜਾਬੀ": "pa", "पंजाबी": "pa",
    "tamil": "ta", "தமிழ்": "ta", "तमिल": "ta",
    "telugu": "te", "తెలుగు": "te", "तेलुगु": "te",
    "marathi": "mr", "मराठी": "mr",
    "gujarati": "gu", "ગુજરાતી": "gu", "गुजराती": "gu",
}

# Cue words that signal the user is REQUESTING an output language (not just naming a
# place/topic). Kept intentionally specific to avoid firing on e.g. "Tamil Nadu".
_LANG_REQUEST_CUES = re.compile(
    r"(reply|answer|respond|explain|write|translate|convert|speak|tell me|"
    r"language|bhasha|भाषा|जवाब|उत्तर|बता|बोल|लिख|समझा|jawab|jvab|batao|bolo|likho|"
    r"\bमें\b|\bमे\b|\bme\b|\bmein\b)",
    re.IGNORECASE,
)


def detect_requested_language(query: str) -> str | None:
    """If the query explicitly asks for a specific output language, return its code.

    Conservative: an alias must appear next to a request cue, so "answer in Tamil"
    matches but "schemes in Tamil Nadu" does not.
    """
    if not query:
        return None
    q = query.lower()
    for alias, code in _LANG_ALIASES.items():
        idx = q.find(alias.lower())
        if idx == -1:
            continue
        window = q[max(0, idx - 32): idx + len(alias) + 18]
        if _LANG_REQUEST_CUES.search(window):
            return code
    return None


def normalize_language(code: str | None) -> str:
    """Canonical response-language code.

    Strips code-switching suffixes ("hi+en" → "hi"), region tags ("en-IN" → "en"),
    accepts full English names ("Hindi" → "hi"), validates against supported
    languages, and falls back to "en".
    """
    if not code:
        return "en"
    base = str(code).strip().lower()
    base = base.split("+")[0].split("-")[0].split("_")[0].strip()
    if base in LANGUAGES:
        return base
    if base in _NAME_TO_CODE:
        return _NAME_TO_CODE[base]
    if base in _LANG_ALIASES:
        return _LANG_ALIASES[base]
    return "en"


def resolve_response_language(query: str, hint: str | None = None) -> str:
    """The language the response MUST be written in.

    A valid, explicit caller hint wins (the user picked a language in the UI); else
    an explicit in-text language request wins; else the language is detected from the
    query text itself. The result is always a supported base code
    (en, hi, pa, ta, te, mr, gu).
    """
    if hint:
        cleaned = str(hint).strip().lower()
        if cleaned not in ("", "auto", "detect", "none"):
            norm = normalize_language(hint)
            if norm in LANGUAGES:
                return norm
    requested = detect_requested_language(query)
    if requested:
        return requested
    return normalize_language(detect_language(query))


def language_directive(code: str) -> str:
    """A strong, unambiguous instruction to write the ENTIRE response in one language.

    Prepended to every generation prompt so the model cannot drift into another
    language — it must match the resolved response language exactly.
    """
    info = LANGUAGES.get(normalize_language(code), LANGUAGES["en"])
    return (
        f"- RESPONSE LANGUAGE (MANDATORY): Write your ENTIRE response — the title, "
        f"summary, every step, label, option, and disclaimer — in {info.name_en} "
        f"({info.name_native}) and NOTHING else. Do NOT switch to Hindi or English "
        f"unless {info.name_en} IS that language. Keep proper nouns, scheme names, "
        f"place names, and numbers as-is.\n"
    )


# Localised fallback strings used when generation fails — so an error/greeting is
# never forced into Hindi for a non-Hindi user.
_FALLBACKS: dict[str, dict[str, str]] = {
    "error": {
        "en": "Sorry, something went wrong. Please try again.",
        "hi": "माफ़ करें, कुछ गड़बड़ हुई। कृपया फिर से कोशिश करें।",
        "pa": "ਮਾਫ਼ ਕਰਨਾ, ਕੁਝ ਗੜਬੜ ਹੋ ਗਈ। ਕਿਰਪਾ ਕਰਕੇ ਦੁਬਾਰਾ ਕੋਸ਼ਿਸ਼ ਕਰੋ।",
        "ta": "மன்னிக்கவும், ஏதோ தவறு நடந்தது. மீண்டும் முயற்சிக்கவும்.",
        "te": "క్షమించండి, ఏదో పొరపాటు జరిగింది. దయచేసి మళ్లీ ప్రయత్నించండి.",
        "mr": "क्षमस्व, काहीतरी चूक झाली. कृपया पुन्हा प्रयत्न करा.",
        "gu": "માફ કરશો, કંઈક ખોટું થયું. કૃપા કરીને ફરી પ્રયાસ કરો.",
    },
    "greeting": {
        "en": "Hello! How can I help you?",
        "hi": "नमस्ते! मैं आपकी कैसे मदद कर सकता हूँ?",
        "pa": "ਸਤ ਸ੍ਰੀ ਅਕਾਲ! ਮੈਂ ਤੁਹਾਡੀ ਕਿਵੇਂ ਮਦਦ ਕਰ ਸਕਦਾ ਹਾਂ?",
        "ta": "வணக்கம்! நான் உங்களுக்கு எப்படி உதவ முடியும்?",
        "te": "నమస్తే! నేను మీకు ఎలా సహాయం చేయగలను?",
        "mr": "नमस्कार! मी तुमची कशी मदत करू शकतो?",
        "gu": "નમસ્તે! હું તમારી કેવી રીતે મદદ કરી શકું?",
    },
    "abstain_title": {
        "en": "I don't have a reliable source for this",
        "hi": "मेरे पास इसका विश्वसनीय स्रोत नहीं है",
        "pa": "ਮੇਰੇ ਕੋਲ ਇਸ ਦਾ ਭਰੋਸੇਯੋਗ ਸਰੋਤ ਨਹੀਂ ਹੈ",
        "ta": "இதற்கு என்னிடம் நம்பகமான ஆதாரம் இல்லை",
        "te": "దీనికి నా వద్ద నమ్మదగిన మూలం లేదు",
        "mr": "माझ्याकडे याचा विश्वसनीय स्रोत नाही",
        "gu": "મારી પાસે આનો વિશ્વસનીય સ્રોત નથી",
    },
    "abstain_summary": {
        "en": ("I couldn't find a reliable, verified source to answer this accurately, so I'd "
               "rather not guess. Please check the relevant official government portal or a "
               "qualified professional for an authoritative answer."),
        "hi": ("मुझे इसका सटीक उत्तर देने के लिए कोई विश्वसनीय, सत्यापित स्रोत नहीं मिला, इसलिए मैं "
               "अनुमान नहीं लगाना चाहूँगा। कृपया संबंधित आधिकारिक सरकारी पोर्टल या किसी योग्य विशेषज्ञ "
               "से पुष्टि करें।"),
        "pa": ("ਮੈਨੂੰ ਇਸ ਦਾ ਸਹੀ ਜਵਾਬ ਦੇਣ ਲਈ ਕੋਈ ਭਰੋਸੇਯੋਗ ਸਰੋਤ ਨਹੀਂ ਮਿਲਿਆ, ਇਸ ਲਈ ਮੈਂ ਅੰਦਾਜ਼ਾ ਨਹੀਂ "
               "ਲਗਾਉਣਾ ਚਾਹੁੰਦਾ। ਕਿਰਪਾ ਕਰਕੇ ਸੰਬੰਧਿਤ ਅਧਿਕਾਰਤ ਸਰਕਾਰੀ ਪੋਰਟਲ ਜਾਂ ਕਿਸੇ ਯੋਗ ਮਾਹਰ ਤੋਂ ਪੁਸ਼ਟੀ ਕਰੋ।"),
        "ta": ("இதற்கு துல்லியமான பதிலளிக்க நம்பகமான ஆதாரம் கிடைக்கவில்லை, எனவே நான் யூகிக்க "
               "விரும்பவில்லை. தயவுசெய்து சம்பந்தப்பட்ட அதிகாரப்பூர்வ அரசு இணையதளம் அல்லது தகுதியான "
               "நிபுணரிடம் சரிபார்க்கவும்."),
        "te": ("దీనికి కచ్చితమైన సమాధానం ఇవ్వడానికి నమ్మదగిన మూలం దొరకలేదు, కాబట్టి నేను ఊహించడం "
               "ఇష్టం లేదు. దయచేసి సంబంధిత అధికారిక ప్రభుత్వ పోర్టల్ లేదా అర్హత గల నిపుణుడిని "
               "సంప్రదించండి."),
        "mr": ("याचे अचूक उत्तर देण्यासाठी मला विश्वसनीय स्रोत सापडला नाही, म्हणून मी अंदाज लावू "
               "इच्छित नाही. कृपया संबंधित अधिकृत सरकारी पोर्टल किंवा पात्र तज्ज्ञाकडे पडताळणी करा."),
        "gu": ("આનો ચોક્કસ જવાબ આપવા માટે મને કોઈ વિશ્વસનીય સ્રોત મળ્યો નથી, તેથી હું અનુમાન કરવા "
               "માંગતો નથી. કૃપા કરીને સંબંધિત અધિકૃત સરકારી પોર્ટલ અથવા લાયક નિષ્ણાતની ખાતરી કરો."),
    },
}


def fallback_message(code: str, key: str) -> str:
    """Localised fallback text (error/greeting) for the given language code."""
    lang = normalize_language(code)
    table = _FALLBACKS.get(key, {})
    return table.get(lang) or table.get("en", "")
