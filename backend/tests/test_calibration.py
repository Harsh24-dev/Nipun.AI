"""Tests for the pure calibration metrics (src/eval/calibration.py)."""

import math

from src.eval.calibration import (
    band_precision,
    brier_score,
    compute_report,
    expected_calibration_error,
    suggest_threshold,
)


def test_perfect_calibration_has_zero_ece():
    # Scores exactly match empirical accuracy in each bin.
    scores = [0.0, 0.0, 1.0, 1.0]
    labels = [0, 0, 1, 1]
    assert expected_calibration_error(scores, labels) == 0.0
    assert brier_score(scores, labels) == 0.0


def test_overconfident_model_has_high_ece():
    # Always says 0.9 but is only right half the time → ECE ≈ 0.4.
    scores = [0.9] * 10
    labels = [1, 0] * 5
    ece = expected_calibration_error(scores, labels)
    assert 0.35 <= ece <= 0.45


def test_brier_penalises_confident_mistakes():
    assert brier_score([0.99], [0]) > brier_score([0.6], [0])


def test_band_precision_counts_correct_fraction():
    # Two high-band (>=0.75) answers, one correct → precision 0.5.
    scores = [0.8, 0.9, 0.4]
    labels = [1, 0, 0]
    bp = band_precision(scores, labels)
    assert bp["high"]["n"] == 2
    assert bp["high"]["precision"] == 0.5
    assert bp["low"]["n"] == 1


def test_empty_band_precision_is_nan():
    bp = band_precision([0.8], [1])
    assert math.isnan(bp["very_low"]["precision"])
    assert bp["very_low"]["n"] == 0


def test_suggest_threshold_finds_precision_cut():
    # High scorers are all correct; a 0.9-precision cut should sit among them.
    scores = [0.95, 0.9, 0.85, 0.2, 0.1]
    labels = [1, 1, 1, 0, 0]
    cut = suggest_threshold(scores, labels, target_precision=0.9)
    assert cut is not None
    assert cut >= 0.85


def test_suggest_threshold_none_when_unreachable():
    scores = [0.9, 0.8, 0.7]
    labels = [0, 0, 0]  # never correct → no cut reaches 90% precision
    assert suggest_threshold(scores, labels, target_precision=0.9) is None


def test_compute_report_shape():
    r = compute_report([0.8, 0.3, 0.9], [1, 0, 1], live_mode=True)
    assert r.n == 3
    assert r.ece is not None and r.brier is not None
    assert "high" in r.bands


def test_compute_report_empty():
    r = compute_report([], [], live_mode=True)
    assert r.n == 0
    assert r.ece is None
    assert r.notes
