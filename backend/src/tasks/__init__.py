"""Task assistants.

Two families, one lookup:
  * preview assistants (assistants.py) — read-only plans/previews.
  * form assistants (forms.py) — fill a real service form on the user's behalf, leaving
    only payment/OTP/password to the user (the digital-divide feature).
Both are credential-safe (never accept OTP/PIN/password) and never submit anything by
themselves — real submission is a separate, gated execution step.
"""

from src.tasks.assistants import TaskAssistant
from src.tasks.assistants import get_assistant as _get_preview_assistant
from src.tasks.assistants import list_assistants as _list_preview_assistants
from src.tasks.forms import FormAssistant, get_form_assistant, list_form_assistants

# Importing this module registers the career/jobs assistants (résumé, tailored CV, job
# application, learning roadmap) into the shared registry so they are routable.
from src.tasks import career  # noqa: F401,E402  (import for its registration side effect)


def get_assistant(name: str) -> TaskAssistant | None:
    """Resolve a task by name across both preview and form assistants."""
    return _get_preview_assistant(name) or get_form_assistant(name)


def list_assistants() -> list[dict]:
    """All available task assistants (preview + form-assist)."""
    return _list_preview_assistants() + list_form_assistants()


__all__ = [
    "TaskAssistant", "FormAssistant",
    "get_assistant", "list_assistants",
    "get_form_assistant", "list_form_assistants",
]
