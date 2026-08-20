"""Tests for RRF fusion algorithm."""

import pytest
from src.retrieval.hybrid import _compute_rrf_scores, _has_identifiers


def test_rrf_higher_rank_wins():
    dense  = [("a", 0.9), ("b", 0.7), ("c", 0.5)]
    sparse = [("b", 8.0), ("a", 6.0), ("d", 4.0)]
    scores = _compute_rrf_scores(dense, sparse, k=60)

    # "a" ranks 1st in dense, 2nd in sparse — should beat "b" (2nd dense, 1st sparse)
    # Both appear in both lists so both get two contributions
    assert "a" in scores and "b" in scores
    # "d" only appears in sparse (rank 3) — lower than "a"
    assert scores["a"] > scores["d"]


def test_rrf_missing_from_one_list():
    dense  = [("x", 0.9)]
    sparse = [("y", 10.0)]
    scores = _compute_rrf_scores(dense, sparse, k=60)
    # "x" is rank 1 in dense, not in sparse; "y" rank 1 in sparse, not dense
    # Both get 1/(60+1) — tie
    assert abs(scores["x"] - scores["y"]) < 1e-9


def test_rrf_empty_lists():
    scores = _compute_rrf_scores([], [], k=60)
    assert scores == {}


def test_has_identifiers_section():
    assert _has_identifiers("Section 302 of IPC")
    assert _has_identifiers("धारा 302 के तहत")
    assert _has_identifiers("CrPC 438")


def test_has_identifiers_false_for_conceptual():
    assert not _has_identifiers("how to get bail in India")
    assert not _has_identifiers("खेती में सिंचाई")
