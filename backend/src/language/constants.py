from dataclasses import dataclass

from src.core.logging import get_logger

log = get_logger("language.constants")


@dataclass(frozen=True)
class LanguageInfo:
    code: str           # BCP-47 code
    name_en: str        # English name
    name_native: str    # Native script name
    script: str         # Unicode script name
    iso639_1: str       # ISO 639-1 code


LANGUAGES: dict[str, LanguageInfo] = {
    "en": LanguageInfo("en",  "English",   "English",   "Latin",      "en"),
    "hi": LanguageInfo("hi",  "Hindi",     "हिन्दी",    "Devanagari", "hi"),
    "pa": LanguageInfo("pa",  "Punjabi",   "ਪੰਜਾਬੀ",    "Gurmukhi",   "pa"),
    "ta": LanguageInfo("ta",  "Tamil",     "தமிழ்",      "Tamil",      "ta"),
    "te": LanguageInfo("te",  "Telugu",    "తెలుగు",     "Telugu",     "te"),
    "mr": LanguageInfo("mr",  "Marathi",   "मराठी",     "Devanagari", "mr"),
    "gu": LanguageInfo("gu",  "Gujarati",  "ગુજરાતી",   "Gujarati",   "gu"),
}

# Code-switched variants (detected but map to a base language pair)
CODE_SWITCHED: dict[str, tuple[str, str]] = {
    "hi+en": ("hi", "en"),   # Hinglish
    "pa+en": ("pa", "en"),   # Punglish
    "ta+en": ("ta", "en"),   # Tamilish / Tanglish
    "te+en": ("te", "en"),   # Tenglish
    "mr+en": ("mr", "en"),   # Manglish (Marathi)
    "gu+en": ("gu", "en"),   # Gujarish
}

# Unicode code-point ranges for each script block
# Used for script-level analysis (code-switching detection)
SCRIPT_RANGES: dict[str, list[tuple[int, int]]] = {
    "latin":      [(0x0041, 0x005A), (0x0061, 0x007A)],   # A-Z, a-z
    "devanagari": [(0x0900, 0x097F)],
    "gurmukhi":   [(0x0A00, 0x0A7F)],
    "gujarati":   [(0x0A80, 0x0AFF)],
    "tamil":      [(0x0B80, 0x0BFF)],
    "telugu":     [(0x0C00, 0x0C7F)],
}

# Script → primary language(s) — used when lingua is uncertain
SCRIPT_TO_LANG: dict[str, list[str]] = {
    "latin":      ["en"],
    "devanagari": ["hi", "mr"],   # need further vocab disambiguation
    "gurmukhi":   ["pa"],
    "gujarati":   ["gu"],
    "tamil":      ["ta"],
    "telugu":     ["te"],
}

# ONE Qdrant collection per domain — ALL languages live in the same collection.
# BGE-M3 embeds every language into a single shared vector space, and retrieval is
# cross-lingual (a Hindi query can match English/Tamil docs), so splitting by language
# only forced a slow 7-way fan-out with approximate merged top-k. Language is kept as an
# indexed payload field for optional language-scoped filtering. `lang` is accepted but
# ignored for backward compatibility with existing call sites.
def collection_name(domain: str, lang: str | None = None) -> str:
    """e.g. collection_name('legal') → 'legal' (holds hi, en, ta, … together)."""
    log.debug("collection_name_resolved", domain=domain, lang=lang, collection=domain)
    return domain


def es_index_name(domain: str) -> str:
    index = f"nipun_ai_{domain}"
    log.debug("es_index_name_resolved", domain=domain, index=index)
    return index


SUPPORTED_DOMAINS = [
    "legal", "farming", "student", "health", "scheme", "booking", "finance", "general",
    # additional domains (each gets its own Qdrant collections per language)
    "career", "governance", "jobs", "travel", "documents",
]

log.debug(
    "language_constants_loaded",
    languages=len(LANGUAGES),
    code_switched=len(CODE_SWITCHED),
    script_ranges=len(SCRIPT_RANGES),
    script_to_lang=len(SCRIPT_TO_LANG),
    supported_domains=len(SUPPORTED_DOMAINS),
)
