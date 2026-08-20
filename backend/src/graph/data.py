"""
Structured seed records for the legal + scheme knowledge graphs.

Curated from authoritative sources (section numbering, official eligibility tables).
Each record is validated against the allowlists in schema.py before it enters the graph.
"""

from __future__ import annotations

from src.core.logging import get_logger

log = get_logger("graph.data")

# Section -belongs_to-> Act ; Section -related_to-> [Sections]
LEGAL_SECTIONS: list[dict] = [
    {"section": "302", "act": "IPC", "title": "Punishment for murder", "related": ["300", "304", "307"]},
    {"section": "300", "act": "IPC", "title": "Murder", "related": ["302", "304"]},
    {"section": "304", "act": "IPC", "title": "Culpable homicide not amounting to murder", "related": ["300", "302"]},
    {"section": "307", "act": "IPC", "title": "Attempt to murder", "related": ["302"]},
    {"section": "498A", "act": "IPC", "title": "Cruelty by husband or relatives", "related": ["406"]},
    {"section": "437", "act": "CrPC", "title": "Bail in non-bailable offence", "related": ["438", "439"]},
    {"section": "438", "act": "CrPC", "title": "Anticipatory bail", "related": ["437", "439"]},
    {"section": "439", "act": "CrPC", "title": "Special powers of High Court/Sessions on bail", "related": ["437", "438"]},
    {"section": "154", "act": "CrPC", "title": "Information in cognizable cases (FIR)", "related": ["156"]},
    {"section": "138", "act": "Negotiable Instruments Act", "title": "Dishonour of cheque", "related": []},
]

# Section -amended_by-> Amendment
LEGAL_AMENDMENTS: list[dict] = [
    {"section": "498A", "act": "IPC", "amendment": "Criminal Law (Second Amendment) Act 1983"},
]

# Scheme -administered_by-> Ministry ; -requires-> [Criteria] ; -excludes-> [Schemes]
SCHEMES: list[dict] = [
    {"scheme": "PM-KISAN", "ministry": "Ministry of Agriculture & Farmers Welfare",
     "requires": ["landholding farmer family", "not an income-tax payer"],
     "excludes": [], "benefit": "₹6,000/year"},
    {"scheme": "Ayushman Bharat", "ministry": "Ministry of Health & Family Welfare",
     "requires": ["family in SECC deprivation categories"],
     "excludes": [], "benefit": "₹5 lakh/family/year health cover"},
    {"scheme": "PM Awas Yojana", "ministry": "Ministry of Housing & Urban Affairs",
     "requires": ["does not own a pucca house", "income within EWS/LIG/MIG limits"],
     "excludes": [], "benefit": "Housing / interest subsidy"},
    {"scheme": "Sukanya Samriddhi Yojana", "ministry": "Ministry of Finance",
     "requires": ["girl child under 10 years"], "excludes": [], "benefit": "Tax-free small savings"},
    {"scheme": "MGNREGA", "ministry": "Ministry of Rural Development",
     "requires": ["rural household", "adult willing to do unskilled manual work"],
     "excludes": [], "benefit": "100 days guaranteed wage employment"},
]

log.debug("graph_seed_data_loaded", legal_sections=len(LEGAL_SECTIONS),
          legal_amendments=len(LEGAL_AMENDMENTS), schemes=len(SCHEMES))
