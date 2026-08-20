"""Tests for the eval harness pure metric functions."""

import math

from src.eval.metrics import (
    abstention_correct,
    citation_present,
    citation_wellformed,
    faithfulness_from_facts,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)


def test_precision_at_k_basic():
    retrieved = ["a", "b", "c", "d"]
    relevant = ["b", "d"]
    assert precision_at_k(retrieved, relevant, 4) == 0.5
    assert precision_at_k(retrieved, relevant, 2) == 0.5   # a,b → 1 hit / 2
    assert precision_at_k(retrieved, relevant, 1) == 0.0   # a → miss


def test_precision_at_k_empty():
    assert precision_at_k([], ["a"], 5) == 0.0
    assert precision_at_k(["a"], ["a"], 0) == 0.0


def test_recall_at_k():
    assert recall_at_k(["a", "b"], ["a", "b", "c"], 2) == 2 / 3
    assert recall_at_k(["x"], [], 5) == 1.0  # nothing to find


def test_ndcg_perfect_ranking_is_one():
    retrieved = ["a", "b", "c"]
    relevant = ["a", "b", "c"]
    assert math.isclose(ndcg_at_k(retrieved, relevant, 10), 1.0)


def test_ndcg_worse_ranking_is_lower():
    good = ndcg_at_k(["a", "x", "y"], ["a"], 10)      # relevant at rank 1
    bad = ndcg_at_k(["x", "y", "a"], ["a"], 10)       # relevant at rank 3
    assert good > bad
    assert 0.0 < bad < 1.0


def test_ndcg_no_relevant_is_one():
    assert ndcg_at_k(["a", "b"], [], 10) == 1.0


def test_citation_present():
    assert citation_present(["Section 302 IPC", "CrPC 437"], "section 302 ipc")
    assert not citation_present(["CrPC 437"], "Section 302 IPC")
    assert citation_present([], None)  # nothing required


def test_citation_wellformed():
    assert citation_wellformed("Section 437 CrPC")
    assert citation_wellformed("PM-KISAN")
    assert citation_wellformed("https://nalsa.gov.in")
    assert citation_wellformed("Ayushman Bharat")
    assert not citation_wellformed("just some free text")
    assert citation_wellformed(None)


def test_abstention_correct():
    assert abstention_correct(True, True)
    assert abstention_correct(False, False)
    assert not abstention_correct(True, False)


def test_faithfulness_from_facts():
    answer = "PM-KISAN gives farmers six thousand rupees per year in three instalments."
    facts = ["PM-KISAN gives farmers ₹6,000 per year", "paid in three instalments"]
    score = faithfulness_from_facts(answer, facts)
    assert score >= 0.5
    assert faithfulness_from_facts("", facts) == 0.0
    assert faithfulness_from_facts("anything", []) == 1.0
