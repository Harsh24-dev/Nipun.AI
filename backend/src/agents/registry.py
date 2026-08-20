"""
Agent Registry — maps domain strings to agent instances.
Add a new agent: create the class, import it here, add to REGISTRY.
"""

import structlog

from src.agents.base import BaseAgent
from src.agents.domains.booking import BookingAgent
from src.agents.domains.career import CareerAgent
from src.agents.domains.documents import DocumentsAgent
from src.agents.domains.farming import FarmingAgent
from src.agents.domains.finance import FinanceAgent
from src.agents.domains.general import GeneralAgent
from src.agents.domains.governance import GovernanceAgent
from src.agents.domains.health import HealthAgent
from src.agents.domains.jobs import JobsAgent
from src.agents.domains.legal import LegalAgent
from src.agents.domains.scheme import SchemeAgent
from src.agents.domains.student import StudentAgent
from src.agents.domains.travel import TravelAgent

# Single instance per agent (stateless — safe to share)
REGISTRY: dict[str, BaseAgent] = {
    "legal":      LegalAgent(),
    "farming":    FarmingAgent(),
    "scheme":     SchemeAgent(),
    "student":    StudentAgent(),
    "finance":    FinanceAgent(),
    "health":     HealthAgent(),      # real agent (was a general stub)
    "career":     CareerAgent(),
    "booking":    BookingAgent(),     # promoted from stub
    "governance": GovernanceAgent(),
    "jobs":       JobsAgent(),
    "travel":     TravelAgent(),
    "documents":  DocumentsAgent(),
    "general":    GeneralAgent(),
}


log = structlog.get_logger("agents.registry")


def get_agent(domain: str) -> BaseAgent:
    agent = REGISTRY.get(domain)
    if agent is None:
        # An unknown domain means classification produced something outside the 13 —
        # worth seeing in the logs, since it silently falls back to the general agent.
        log.warning("agent_domain_fallback", requested_domain=domain, used="general")
        return REGISTRY["general"]
    return agent
