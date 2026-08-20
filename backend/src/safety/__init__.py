"""
Safety & verification package.

- prescreen: intake SafetyPreScreen (crisis/harm tagging)
- handlers:  safe-response cards for non-normal tags
- gate:      VerificationSafetyGate — the single pre-delivery choke point
- resources: official crisis resources (no unverified numbers hardcoded)
"""

from src.safety.gate import VerificationSafetyGate, gate
from src.safety.prescreen import PreScreenResult, prescreen
from src.safety.resources import NON_NORMAL_TAGS, SAFETY_TAGS

__all__ = [
    "NON_NORMAL_TAGS",
    "SAFETY_TAGS",
    "PreScreenResult",
    "VerificationSafetyGate",
    "gate",
    "prescreen",
]
