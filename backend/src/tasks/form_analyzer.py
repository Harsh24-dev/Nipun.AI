"""
Dynamic form analysis — detect the fields of a form on ANY site the user names.

The hardcoded FormAssistants (RTI, train, ITR, job application) know their fields ahead of
time. This module handles the open case: the user points at an arbitrary page and asks Nipun
to fill its form. We fetch the page, parse its real `<input>/<select>/<textarea>` fields
(with their labels), and classify which are safe to auto-fill vs. which the user must do
themselves (password, OTP, captcha, card, etc.). The actual value-mapping (field → the user's
detail) is done by the LLM in `dynamic_fill.py`; this module is the pure, deterministic
extraction + safety classification, so it is easy to test and never invents a field.

Limitation: this reads server-rendered HTML. Forms rendered entirely by client-side
JavaScript may expose no fields here; callers degrade gracefully (ask the user for the values
and still hand back a filled package) rather than guessing.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

from src.core.logging import get_logger

log = get_logger("tasks.form_analyzer")

# Field types/names that Nipun must NEVER auto-fill — the user does these themselves.
# Matched against the field's type, name, id, and label (case-insensitive substring).
_SENSITIVE = (
    "password", "passwd", "pwd", "otp", "one-time", "one time", "pin", "cvv", "cvc",
    "card number", "cardnumber", "card-no", "creditcard", "credit-card", "captcha",
    "security code", "security-code", "security question", "secret", "mpin", "upi pin",
    "aadhaar", "aadhar", "pan number", "pan-no", "passport number", "biometric",
)

# Non-data input types that are not user-fillable text fields.
_SKIP_TYPES = {"submit", "button", "reset", "image", "hidden", "file"}

log.debug("form_analyzer_loaded", sensitive_patterns=len(_SENSITIVE),
          skip_types=len(_SKIP_TYPES))


class _FormParser(HTMLParser):
    """Extracts form controls and their associated <label> text from raw HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.fields: list[dict] = []
        self._labels_by_for: dict[str, str] = {}
        self._cur_label_for: str | None = None
        self._cur_label_text: list[str] = []
        self._cur_select: dict | None = None
        self._cur_option_text: list[str] = []
        self._in_option = False

    # --- labels ---
    def handle_starttag(self, tag: str, attrs_list: list) -> None:
        attrs = {k.lower(): (v or "") for k, v in attrs_list}
        if tag == "label":
            self._cur_label_for = attrs.get("for")
            self._cur_label_text = []
        elif tag in ("input", "textarea"):
            self._add_field(tag, attrs)
        elif tag == "select":
            self._cur_select = {"tag": "select", "attrs": attrs, "options": []}
        elif tag == "option" and self._cur_select is not None:
            self._in_option = True
            self._cur_option_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "label":
            text = " ".join(" ".join(self._cur_label_text).split())
            if self._cur_label_for and text:
                self._labels_by_for[self._cur_label_for] = text
            self._cur_label_for = None
            self._cur_label_text = []
        elif tag == "option" and self._in_option and self._cur_select is not None:
            opt = " ".join(" ".join(self._cur_option_text).split())
            if opt:
                self._cur_select["options"].append(opt)
            self._in_option = False
        elif tag == "select" and self._cur_select is not None:
            self._add_field("select", self._cur_select["attrs"],
                            options=self._cur_select["options"])
            self._cur_select = None

    def handle_data(self, data: str) -> None:
        if self._cur_label_for is not None:
            self._cur_label_text.append(data)
        if self._in_option:
            self._cur_option_text.append(data)

    # --- field assembly ---
    def _add_field(self, tag: str, attrs: dict, options: list | None = None) -> None:
        _default = {"textarea": "textarea", "select": "select"}.get(tag, "text")
        ftype = (attrs.get("type") or _default).lower()
        if ftype in _SKIP_TYPES:
            return
        name = attrs.get("name") or attrs.get("id") or ""
        if not name:
            return
        label = (self._labels_by_for.get(attrs.get("id", "")) or attrs.get("aria-label")
                 or attrs.get("placeholder") or attrs.get("title") or name)
        self.fields.append({
            "name": name,
            "id": attrs.get("id", ""),
            "type": ftype,
            "label": " ".join(str(label).split())[:120],
            "placeholder": attrs.get("placeholder", ""),
            "required": ("required" in attrs) or (attrs.get("aria-required") == "true"),
            "options": options or [],
        })


def is_sensitive_field(field: dict) -> bool:
    """True when a field must be left to the user (credentials, OTP, captcha, card, etc.)."""
    # NOTE: only field metadata (type/name/label) is inspected here — never entered values.
    if field.get("type") == "password":
        log.debug("sensitive_field_detected", name=field.get("name", ""),
                  label=field.get("label", ""), reason="password_type")
        return True
    hay = f"{field.get('type','')} {field.get('name','')} {field.get('id','')} {field.get('label','')}".lower()
    match = next((s for s in _SENSITIVE if s in hay), None)
    if match is not None:
        log.debug("sensitive_field_detected", name=field.get("name", ""),
                  label=field.get("label", ""), pattern=match)
        return True
    return False


def extract_form_fields(html: str) -> list[dict]:
    """Parse raw HTML into a de-duplicated list of fillable form fields.

    Each field: {name, id, type, label, placeholder, required, options, sensitive}.
    Sensitive fields are kept (so callers can show them as user-only steps) but flagged.
    """
    if not html:
        log.debug("extract_form_fields_empty_html")
        return []
    log.debug("extract_form_fields_start", html_len=len(html))
    parser = _FormParser()
    try:
        parser.feed(html)
    except Exception as exc:
        # Malformed markup — salvage what was parsed before the error.
        log.warning("extract_form_fields_parse_error", error=str(exc),
                    error_type=type(exc).__name__, parsed_so_far=len(parser.fields))
    seen: set[str] = set()
    out: list[dict] = []
    for f in parser.fields:
        key = (f["name"] or f["id"]).lower()
        if not key or key in seen:
            continue
        seen.add(key)
        f["sensitive"] = is_sensitive_field(f)
        out.append(f)
    # Log COUNTS and field names/labels only — never any entered value/secret.
    sensitive = [f for f in out if f.get("sensitive")]
    log.info("form_analyzed", raw_fields=len(parser.fields), fields=len(out),
             sensitive=len(sensitive),
             sensitive_names=[f.get("name", "") for f in sensitive])
    return out


# Rough detector: does this text/HTML even contain a form? Avoids an LLM call on a page
# that has none (likely JS-rendered), so the caller can degrade gracefully.
_HAS_FORM_RE = re.compile(r"<(form|input|select|textarea)\b", re.IGNORECASE)


def html_has_form(html: str) -> bool:
    result = bool(html and _HAS_FORM_RE.search(html))
    log.debug("html_has_form", has_form=result, html_len=len(html) if html else 0)
    return result
