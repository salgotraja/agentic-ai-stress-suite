"""Tests for the Article 9 held-out evaluation helpers."""

from __future__ import annotations

import math

import numpy as np

from benchmarks.article_09_eval import (
    build_reranker_pairs,
    group_questions,
    normalize_question,
    paired_summary,
    recall_at_k,
    reciprocal_rank,
    split_groups,
)


def test_normalize_question_ignores_case_and_punctuation() -> None:
    assert normalize_question("What is  FastAPI?") == normalize_question("what is fastapi")


def test_group_questions_merges_paraphrases_and_identical_labels() -> None:
    questions = ["What is A?", "what is a", "Explain B", "Describe C", "Tell me about D"]
    sources = [
        frozenset({"a.md"}),
        frozenset({"x.md"}),
        frozenset({"b.md"}),
        frozenset({"c.md"}),
        frozenset({"b.md"}),
    ]
    sim = np.eye(5)
    sim[2, 3] = sim[3, 2] = 0.95
    groups = group_questions(questions, sources, sim, threshold=0.9)
    assert groups[0] == groups[1]  # same normalised text
    assert groups[2] == groups[3]  # embedding similarity
    assert groups[2] == groups[4]  # identical source set
    assert groups[0] != groups[2]


def test_split_groups_never_splits_a_group() -> None:
    group_ids = [0, 0, 1, 1, 1, 2, 3, 3, 4, 5]
    splits = split_groups(group_ids, test_fraction=0.4, seed=7)
    for g in set(group_ids):
        assert len({s for s, gid in zip(splits, group_ids) if gid == g}) == 1
    assert "test" in splits and "train" in splits


def test_split_groups_is_deterministic() -> None:
    group_ids = list(range(20))
    assert split_groups(group_ids, 0.4, 1) == split_groups(group_ids, 0.4, 1)


def test_recall_counts_each_expected_document_once() -> None:
    ranked = ["a.md", "a.md", "z.md", "b.md", "y.md", "c.md"]
    assert recall_at_k(["a.md", "b.md", "c.md"], ranked, 5) == 2 / 3
    assert math.isnan(recall_at_k([], ranked, 5))


def test_reciprocal_rank_uses_chunk_position() -> None:
    assert reciprocal_rank(["b.md"], ["a.md", "a.md", "b.md"]) == 1 / 3
    assert reciprocal_rank(["q.md"], ["a.md"]) == 0.0


def test_paired_summary_flags_a_consistent_gain() -> None:
    out = paired_summary([0.0] * 30, [1.0] * 30)
    assert out["wins"] == 30 and out["established"]
    flat = paired_summary([0.5, 1.0, 0.0, 1.0], [1.0, 0.5, 0.0, 1.0])
    assert flat["ties"] == 2 and not flat["established"]


def test_paired_summary_group_interval_requires_consistency_across_groups() -> None:
    # Group 0 gains, group 1 loses: query-level looks positive, groups do not agree.
    a = [0.0] * 12
    b = [1.0] * 10 + [-1.0] * 2
    out = paired_summary(a, b, groups=[0] * 10 + [1] * 2)
    assert out["n_groups"] == 2
    assert out["ci95_group"][0] < out["ci95"][0]
    assert not out["established"]


def test_reranker_pairs_never_label_a_listed_source_negative() -> None:
    candidates = [
        {"doc": "other.md", "text": "o1"},
        {"doc": "second_source.md", "text": "s2"},
        {"doc": "first_source.md", "text": "s1"},
        {"doc": "other2.md", "text": "o2"},
    ]
    pairs = build_reranker_pairs(
        "q", ["first_source.md", "second_source.md"], candidates, max_positives=4, max_negatives=4
    )
    negatives = {p["sentence2"] for p in pairs if p["label"] == 0.0}
    positives = {p["sentence2"] for p in pairs if p["label"] == 1.0}
    assert negatives == {"o1", "o2"}
    assert positives == {"s1", "s2"}


def test_cluster_permutation_p_is_exact_and_bounded_by_group_count() -> None:
    from benchmarks.article_09_eval import cluster_permutation_p

    # Three groups all positive: only the all-plus and all-minus flips reach |T|.
    p = cluster_permutation_p([1.0, 1.0, 2.0, 3.0], [0, 0, 1, 2])
    assert p == 2 / 8
    assert cluster_permutation_p([1.0, -1.0], [0, 1]) == 1.0


def test_holm_adjust_is_monotone_and_capped() -> None:
    from benchmarks.article_09_eval import holm_adjust

    adj = holm_adjust({"a": 0.01, "b": 0.04, "c": 0.5})
    assert abs(adj["a"] - 0.03) < 1e-12
    assert abs(adj["b"] - 0.08) < 1e-12
    assert adj["c"] == 0.5
    assert adj["a"] <= adj["b"] <= adj["c"]
