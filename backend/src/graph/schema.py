"""
Knowledge-graph schema + authoritative allowlists.

Graphs are built from STRUCTURED sources only and validated against authoritative
lists — we do NOT rely on free-form LLM entity extraction. Anything not on the
allowlist is rejected and logged.

Legal graph:  Section -belongs_to-> Act ; Section -related_to-> Section ; Section -amended_by-> Amendment
Scheme graph: Scheme -requires-> Criterion ; Scheme -excludes-> Scheme ;
              Scheme -administered_by-> Ministry ; Citizen -qualifies_for-> Scheme
"""

from __future__ import annotations

from src.core.logging import get_logger

log = get_logger("graph.schema")

# Authoritative act names (extend as the legal corpus grows).
VALID_ACTS: set[str] = {
    "IPC", "CrPC", "CPC", "BNS", "BNSS", "BSA",
    "Constitution of India", "RTI Act 2005", "Evidence Act",
    "Negotiable Instruments Act", "Consumer Protection Act 2019",
    "Hindu Marriage Act", "Motor Vehicles Act", "Information Technology Act 2000",
}

# Authoritative administering ministries/authorities.
VALID_MINISTRIES: set[str] = {
    "Ministry of Agriculture & Farmers Welfare",
    "Ministry of Health & Family Welfare",
    "Ministry of Housing & Urban Affairs",
    "Ministry of Finance",
    "Ministry of Rural Development",
    "Ministry of Women & Child Development",
    "Ministry of Education",
    "Ministry of Labour & Employment",
}


def is_valid_act(act: str) -> bool:
    valid = act in VALID_ACTS
    if not valid:
        log.warning("act_not_allowlisted", act=act)
    return valid


def is_valid_ministry(ministry: str) -> bool:
    valid = ministry in VALID_MINISTRIES
    if not valid:
        log.warning("ministry_not_allowlisted", ministry=ministry)
    return valid


log.debug("graph_schema_loaded", valid_acts=len(VALID_ACTS),
          valid_ministries=len(VALID_MINISTRIES))
