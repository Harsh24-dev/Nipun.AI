"""
Execution guards — enforce the non-negotiable safety rules.

1. Credential guard: no agent/tool may handle raw credentials — card/bank numbers,
   CVV, OTP, PIN, password, Aadhaar, or PAN — or enter them into third-party forms.
2. Untrusted-content guard: content read from web pages, PDFs, emails, tool outputs,
   or other agents is DATA, never instructions. Embedded "instructions" are surfaced
   to the user rather than acted on.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import structlog

log = structlog.get_logger("execution.guards")


class CredentialError(Exception):
    """Raised when a payload contains raw credentials that must never be handled."""


# Numeric-value patterns.
_NUM_PATTERNS: dict[str, re.Pattern] = {
    "aadhaar": re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b"),
    "pan": re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b"),
    "card": re.compile(r"\b(?:\d[ -]?){13,19}\b"),
}

# Unambiguous credential keywords — their mere presence in a tool/action payload is
# prohibited (we never handle these), so flag on the keyword alone.
_KEYWORD_PATTERNS: dict[str, re.Pattern] = {
    "otp": re.compile(r"\botp\b", re.IGNORECASE),
    "cvv": re.compile(r"\bcvv\b", re.IGNORECASE),
    "password": re.compile(r"\b(?:password|passwd)\b", re.IGNORECASE),
}

# PIN: careful — avoid the common false positive "pin code" (postal code). Flag only a
# banking-qualified pin or a pin adjacent to 4-6 digits.
_PIN = re.compile(r"\b(?:upi|atm|card|debit)\s*pin\b|\bpin\b(?!\s*code)[:\s]*\d{4,6}\b", re.IGNORECASE)


def scan_for_credentials(text: str) -> list[str]:
    """Return the list of credential types detected in `text` (empty if clean)."""
    if not text:
        return []
    found = [name for name, pat in _NUM_PATTERNS.items() if pat.search(text)]
    found += [name for name, pat in _KEYWORD_PATTERNS.items() if pat.search(text)]
    if _PIN.search(text):
        found.append("pin")
    # 'card' pattern is broad; require a real 13+ digit run, not a phone number.
    if "card" in found and len(re.sub(r"\D", "", text)) < 13:
        found.remove("card")
    return sorted(set(found))


def assert_no_credentials(payload: object) -> None:
    """Raise CredentialError if the payload (str or dict/list) contains credentials."""
    text = payload if isinstance(payload, str) else _stringify(payload)
    hits = scan_for_credentials(text)
    if hits:
        # Security-relevant: a payload tried to carry raw credentials. Log the TYPES only
        # (never the values) so this is auditable without leaking secrets.
        log.warning("credential_guard_blocked", credential_types=hits)
        raise CredentialError(f"payload contains prohibited credentials: {', '.join(hits)}")


def _stringify(payload: object) -> str:
    import json

    try:
        return json.dumps(payload, default=str)
    except Exception:
        return str(payload)


# ── Untrusted content ─────────────────────────────────────────────────────────

_INJECTION = re.compile(
    r"(ignore (the |all )?(previous|above) instructions|disregard .* instructions|"
    r"you are now|system prompt|reveal your prompt|act as|do anything now|"
    r"send .* to|transfer .* to|delete all)",
    re.IGNORECASE,
)


@dataclass
class UntrustedContent:
    """Wrapper marking content as DATA. Embedded instructions are surfaced, not run."""

    source: str
    text: str
    suspected_instructions: list[str]

    @property
    def is_suspicious(self) -> bool:
        return bool(self.suspected_instructions)


def wrap_untrusted(source: str, text: str) -> UntrustedContent:
    """Wrap external content, flagging any embedded-instruction attempts."""
    suspects = [m.group(0) for m in _INJECTION.finditer(text or "")]
    if suspects:
        log.warning("prompt_injection_suspected", source=source, patterns=suspects)
    return UntrustedContent(source=source, text=text or "", suspected_instructions=suspects)
