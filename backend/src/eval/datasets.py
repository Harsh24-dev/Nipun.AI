"""Golden-set loading for the eval harness."""

from __future__ import annotations

import json
from pathlib import Path

import structlog

from src.config import settings
from src.eval.schemas import GoldenExample

log = structlog.get_logger("eval.datasets")


def _golden_dir() -> Path:
    p = Path(settings.EVAL_GOLDEN_DIR)
    if not p.is_absolute():
        # resolve relative to the backend package root (parent of src/)
        p = Path(__file__).resolve().parents[2] / settings.EVAL_GOLDEN_DIR
    return p


def load_domain(domain: str) -> list[GoldenExample]:
    """Load one domain's JSONL golden set. Returns [] if the file is missing."""
    path = _golden_dir() / f"{domain}.jsonl"
    if not path.exists():
        log.warning("golden_set_missing", domain=domain, path=str(path))
        return []
    examples: list[GoldenExample] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            continue
        try:
            examples.append(GoldenExample.model_validate(json.loads(raw)))
        except Exception as exc:
            log.error("golden_line_invalid", domain=domain, lineno=lineno, error=str(exc))
    return examples


def available_domains() -> list[str]:
    """Domains that have a golden-set file present."""
    d = _golden_dir()
    if not d.exists():
        return []
    return sorted(p.stem for p in d.glob("*.jsonl"))


def load_all() -> dict[str, list[GoldenExample]]:
    return {domain: load_domain(domain) for domain in available_domains()}
