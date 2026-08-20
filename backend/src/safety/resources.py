"""
Official crisis / safety resources.

PRINCIPLE: we NEVER hardcode unverified helpline numbers. The only established
baseline is NALSA free legal aid (15100). Any other number is surfaced ONLY if it
has been explicitly configured (verified) via settings; otherwise we point the
user to the relevant official channel by name and let them find the current number.

This module is data-driven so verified numbers can be added later (config/.env)
without touching handler logic.
"""

from __future__ import annotations

from src.config import settings
from src.core.logging import get_logger

log = get_logger("safety.resources")

# Safety tags produced by the intake pre-screen.
SAFETY_TAGS = (
    "normal",
    "self_harm",
    "medical_emergency",
    "child_safety",
    "fraud_scam",
    "harmful_instructions",
)

NON_NORMAL_TAGS = tuple(t for t in SAFETY_TAGS if t != "normal")

log.debug(
    "safety_resources_loaded",
    safety_tags=len(SAFETY_TAGS),
    non_normal_tags=len(NON_NORMAL_TAGS),
)


def _configured_number(value: str) -> str | None:
    value = (value or "").strip()
    return value or None


def crisis_resources(tag: str) -> list[dict[str, str]]:
    """
    Return a list of official resource pointers for a safety tag.

    Each item: {"name": <official channel>, "number": <verified number or "">,
    "url": <official url or "">}. Numbers are included ONLY when configured
    (i.e. verified by the operator); otherwise the user is pointed to the channel.
    """
    log.debug("crisis_resources_lookup", tag=tag)
    mental_health = _configured_number(settings.CRISIS_HELPLINE_MENTAL_HEALTH)
    emergency = _configured_number(settings.CRISIS_HELPLINE_EMERGENCY)
    nalsa = _configured_number(settings.NALSA_LEGAL_AID_HELPLINE)
    # Log only WHETHER each helpline is configured — never the numbers themselves.
    log.debug(
        "crisis_resources_config",
        tag=tag,
        mental_health_configured=mental_health is not None,
        emergency_configured=emergency is not None,
        nalsa_configured=nalsa is not None,
    )

    if tag == "self_harm":
        resources = [
            {
                "name": "Ministry of Health & Family Welfare — mental health helplines",
                "number": mental_health or "",
                "url": "https://www.mohfw.gov.in/",
            },
            {
                "name": "Nearest government hospital / district mental health programme",
                "number": "",
                "url": "",
            },
        ]
        log.info("crisis_resources_resolved", tag=tag, count=len(resources))
        return resources

    if tag == "medical_emergency":
        resources = [
            {
                "name": "Local emergency services / nearest hospital",
                "number": emergency or "",
                "url": "",
            },
        ]
        log.info("crisis_resources_resolved", tag=tag, count=len(resources))
        return resources

    if tag == "child_safety":
        resources = [
            {
                "name": "Ministry of Women & Child Development — child protection services",
                "number": "",
                "url": "https://wcd.nic.in/",
            },
        ]
        log.info("crisis_resources_resolved", tag=tag, count=len(resources))
        return resources

    if tag == "fraud_scam":
        resources = [
            {
                "name": "National Cyber Crime Reporting Portal",
                "number": "",
                "url": "https://cybercrime.gov.in/",
            },
            {
                "name": "NALSA free legal aid",
                "number": nalsa or "",
                "url": "https://nalsa.gov.in/",
            },
        ]
        log.info("crisis_resources_resolved", tag=tag, count=len(resources))
        return resources

    if tag == "harmful_instructions":
        log.info("crisis_resources_resolved", tag=tag, count=0)
        return []

    log.warning("crisis_resources_unknown_tag", tag=tag, count=0)
    return []


def has_verified_number(tag: str) -> bool:
    """True if at least one configured (verified) number exists for this tag."""
    verified = any(r.get("number") for r in crisis_resources(tag))
    log.debug("has_verified_number", tag=tag, verified=verified)
    return verified
