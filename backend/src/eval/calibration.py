"""
Reliability-score calibration harness — `python -m src.eval.calibration`.

"Is the reliability score ACTUALLY accurate?" A score is well-calibrated when answers
it labels 80%-reliable are correct ~80% of the time. This module measures that.

Pure metrics (infra-free, unit-tested):
  • expected_calibration_error (ECE) — the headline number: mean gap between predicted
    confidence and observed correctness across bins. Lower is better (0 = perfect).
  • brier_score — mean squared error of the probability estimate. Lower is better.
  • band_precision — for each delivered band (high/medium/low/very_low), what fraction
    of answers were actually correct. "high" should be near-1.0; that is the promise the
    green badge makes to the user.
  • reliability_diagram_rows — per-bin table (predicted vs actual) for eyeballing.
  • suggest_threshold — the lowest score cut that still hits a target precision, so the
    HIGH/WARN thresholds can be tuned to data instead of guessed.

Runner (needs infra + an LLM key, like eval.run): sends each golden example through the
real pipeline, reads the delivered reliability score, and labels the answer correct when
it is faithful to the example's key_facts. Degrades to a report-that-says-why when infra
is absent — it never fabricates a calibration number.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass, field

import structlog

from src.config import settings

log = structlog.get_logger("eval.calibration")


# ── Pure metrics ──────────────────────────────────────────────────────────────

def _pairs(scores: list[float], labels: list[int]) -> list[tuple[float, int]]:
    if len(scores) != len(labels):
        raise ValueError("scores and labels must be the same length")
    return [(max(0.0, min(1.0, float(s))), 1 if y else 0) for s, y in zip(scores, labels)]


def expected_calibration_error(scores: list[float], labels: list[int], n_bins: int = 10) -> float:
    """ECE = Σ_b (|b| / N) · |acc(b) − conf(b)|, equal-width bins over [0, 1]."""
    data = _pairs(scores, labels)
    if not data:
        return 0.0
    n = len(data)
    ece = 0.0
    for b in range(n_bins):
        lo, hi = b / n_bins, (b + 1) / n_bins
        # Last bin is closed on the right so score == 1.0 lands somewhere.
        bucket = [(s, y) for s, y in data if (lo <= s < hi or (b == n_bins - 1 and s == 1.0))]
        if not bucket:
            continue
        conf = sum(s for s, _ in bucket) / len(bucket)
        acc = sum(y for _, y in bucket) / len(bucket)
        ece += (len(bucket) / n) * abs(acc - conf)
    return ece


def brier_score(scores: list[float], labels: list[int]) -> float:
    data = _pairs(scores, labels)
    if not data:
        return 0.0
    return sum((s - y) ** 2 for s, y in data) / len(data)


def _band_of(score: float) -> str:
    if score >= settings.RELIABILITY_HIGH_THRESHOLD:
        return "high"
    if score >= settings.RELIABILITY_WARN_THRESHOLD:
        return "medium"
    if score >= settings.RELIABILITY_LOW_THRESHOLD:
        return "low"
    return "very_low"


def band_precision(scores: list[float], labels: list[int]) -> dict[str, dict[str, float]]:
    """Per-band {precision, n}. Precision = fraction of answers in that band that were
    actually correct — the concrete meaning of each badge."""
    data = _pairs(scores, labels)
    out: dict[str, dict[str, float]] = {}
    for band in ("high", "medium", "low", "very_low"):
        bucket = [y for s, y in data if _band_of(s) == band]
        if bucket:
            out[band] = {"precision": sum(bucket) / len(bucket), "n": float(len(bucket))}
        else:
            out[band] = {"precision": float("nan"), "n": 0.0}
    return out


def reliability_diagram_rows(scores: list[float], labels: list[int], n_bins: int = 10):
    """Return [(lo, hi, mean_conf, empirical_acc, n), ...] for the printed diagram."""
    data = _pairs(scores, labels)
    rows = []
    for b in range(n_bins):
        lo, hi = b / n_bins, (b + 1) / n_bins
        bucket = [(s, y) for s, y in data if (lo <= s < hi or (b == n_bins - 1 and s == 1.0))]
        if not bucket:
            rows.append((lo, hi, float("nan"), float("nan"), 0))
            continue
        conf = sum(s for s, _ in bucket) / len(bucket)
        acc = sum(y for _, y in bucket) / len(bucket)
        rows.append((lo, hi, conf, acc, len(bucket)))
    return rows


def suggest_threshold(scores: list[float], labels: list[int], target_precision: float = 0.9) -> float | None:
    """Lowest score cut t such that precision over {score ≥ t} ≥ target_precision.
    Returns None if no cut reaches the target (not enough correct high-score answers)."""
    data = sorted(_pairs(scores, labels), key=lambda p: p[0], reverse=True)
    best: float | None = None
    correct = 0
    for i, (s, y) in enumerate(data, start=1):
        correct += y
        if correct / i >= target_precision:
            best = s  # keep lowering the cut as long as precision holds
    return best


@dataclass
class CalibrationReport:
    n: int = 0
    ece: float | None = None
    brier: float | None = None
    bands: dict[str, dict[str, float]] = field(default_factory=dict)
    diagram: list = field(default_factory=list)
    suggested_high_cut: float | None = None
    live_mode: bool = False
    notes: list[str] = field(default_factory=list)


def compute_report(scores: list[float], labels: list[int], live_mode: bool = True) -> CalibrationReport:
    r = CalibrationReport(n=len(scores), live_mode=live_mode)
    if not scores:
        r.notes.append("no (score, correctness) samples collected")
        return r
    r.ece = expected_calibration_error(scores, labels)
    r.brier = brier_score(scores, labels)
    r.bands = band_precision(scores, labels)
    r.diagram = reliability_diagram_rows(scores, labels)
    r.suggested_high_cut = suggest_threshold(scores, labels, target_precision=0.9)
    return r


# ── Runner (live) ─────────────────────────────────────────────────────────────

async def _correctness_label(answer: str, key_facts: list[str], cid: str) -> int | None:
    """1 if the answer is faithful to the key facts, else 0. None when unjudgeable."""
    if not key_facts or not answer:
        return None
    from src.eval import metrics as M
    from src.eval.run import _llm_faithfulness

    f = await _llm_faithfulness(answer, key_facts, cid)
    if f is None:
        f = M.faithfulness_from_facts(answer, key_facts)
    return 1 if f >= 0.5 else 0


async def collect_samples() -> tuple[list[float], list[int], list[str]]:
    """Run every golden example through the pipeline; return (scores, labels, notes)."""
    from src.agents.orchestrator import process_query
    from src.eval.datasets import available_domains, load_domain

    scores: list[float] = []
    labels: list[int] = []
    notes: list[str] = []
    for domain in available_domains():
        for e in load_domain(domain):
            if e.should_abstain:
                continue  # no correct answer exists → not a calibration sample
            cid = f"calib-{e.id}"
            try:
                card = await process_query(query=e.query, session_id=cid, user_id="calib", correlation_id=cid)
            except Exception as exc:
                notes.append(f"{e.id}: pipeline error {exc}")
                continue
            score = card.get("confidence")
            if score is None:
                continue
            answer = card.get("summary") or card.get("title") or ""
            label = await _correctness_label(answer, e.key_facts, cid)
            if label is None:
                continue
            scores.append(float(score))
            labels.append(int(label))
    return scores, labels, notes


async def run_calibration(live: bool | None = None) -> CalibrationReport:
    from src.eval.run import detect_live

    if live is None:
        live, reasons = await detect_live()
        if not live:
            r = CalibrationReport(live_mode=False)
            r.notes.append("offline: " + "; ".join(reasons))
            r.notes.append("calibration needs the live pipeline (infra + LLM key) to produce answers")
            return r
    if not live:
        r = CalibrationReport(live_mode=False)
        r.notes.append("offline mode forced — no samples generated")
        return r

    scores, labels, notes = await collect_samples()
    report = compute_report(scores, labels, live_mode=True)
    report.notes.extend(notes)
    return report


def _fmt(v) -> str:
    if v is None or (isinstance(v, float) and v != v):  # None or NaN
        return "  -  "
    return f"{v:.3f}"


def print_report(r: CalibrationReport) -> None:
    print("\n" + "=" * 78)
    mode = "LIVE" if r.live_mode else "OFFLINE (no samples)"
    print(f"  Reliability Calibration   |   mode: {mode}   |   {r.n} samples")
    print("=" * 78)
    if not r.n:
        for n in r.notes:
            print(f"  · {n}")
        print("=" * 78 + "\n")
        return
    print(f"  ECE (expected calibration error, lower=better): {_fmt(r.ece)}")
    print(f"  Brier score (lower=better):                     {_fmt(r.brier)}")
    print(f"  Suggested HIGH cut for 90% precision:           {_fmt(r.suggested_high_cut)}")
    print("-" * 78)
    print("  Per-band precision (fraction actually correct):")
    for band in ("high", "medium", "low", "very_low"):
        b = r.bands.get(band, {})
        print(f"    {band:<9} precision={_fmt(b.get('precision')):>7}   n={int(b.get('n', 0)):>4}")
    print("-" * 78)
    print("  Reliability diagram  [score bin] pred → actual (n):")
    for lo, hi, conf, acc, n in r.diagram:
        if n:
            print(f"    [{lo:.1f}-{hi:.1f}]  {_fmt(conf)} → {_fmt(acc)}  (n={n})")
    if r.notes:
        print("-" * 78)
        for n in r.notes[:10]:
            print(f"  note: {n}")
    print("=" * 78 + "\n")


def main() -> None:
    try:
        import sys

        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    parser = argparse.ArgumentParser(description="Nipun.AI reliability calibration")
    parser.add_argument("--offline", action="store_true", help="skip live sampling")
    args = parser.parse_args()
    report = asyncio.run(run_calibration(live=False if args.offline else None))
    print_report(report)


if __name__ == "__main__":
    main()
