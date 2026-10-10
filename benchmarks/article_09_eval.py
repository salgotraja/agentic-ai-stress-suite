"""Held-out evaluation helpers for Article 9.

The first Article 9 run split training rows after expanding each question into
several (query, positive, negative) triples, so every validation question also
appeared in training. These helpers split by question group before any pair is
built, and score retrieval with the same document-level Recall@K and MRR that
Articles 1 to 3 use (src/core/benchmarking.py).
"""

from __future__ import annotations

import itertools
import random
import re
from collections.abc import Sequence
from typing import Any

import numpy as np

QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "


def normalize_question(text: str) -> str:
    """Lowercase, drop punctuation, collapse whitespace."""
    cleaned = re.sub(r"[^a-z0-9 ]+", " ", text.lower())
    return " ".join(cleaned.split())


def group_questions(
    questions: Sequence[str],
    source_sets: Sequence[frozenset[str]],
    similarity: np.ndarray,
    threshold: float,
) -> list[int]:
    """Union-find over questions; returns a group id per question.

    Two questions share a group when their normalised text is equal, when the
    cosine similarity of their question embeddings is at least ``threshold``,
    or when they carry the identical set of source documents. Paraphrases and
    same-label questions therefore cannot straddle the train/test boundary.
    """
    n = len(questions)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    normalised = [normalize_question(q) for q in questions]
    for i in range(n):
        for j in range(i + 1, n):
            if (
                normalised[i] == normalised[j]
                or similarity[i, j] >= threshold
                or source_sets[i] == source_sets[j]
            ):
                parent[find(i)] = find(j)

    roots: dict[int, int] = {}
    return [roots.setdefault(find(i), len(roots)) for i in range(n)]


def split_groups(group_ids: Sequence[int], test_fraction: float, seed: int) -> list[str]:
    """Assign whole groups to "test" until test_fraction of questions is reached."""
    groups = sorted(set(group_ids))
    random.Random(seed).shuffle(groups)
    sizes = {g: sum(1 for x in group_ids if x == g) for g in groups}
    target = test_fraction * len(group_ids)
    test_groups: set[int] = set()
    count = 0
    for g in groups:
        if count >= target:
            break
        test_groups.add(g)
        count += sizes[g]
    return ["test" if g in test_groups else "train" for g in group_ids]


def recall_at_k(expected: Sequence[str], retrieved_docs: Sequence[str], k: int) -> float:
    """Fraction of expected documents among the documents of the top-k chunks."""
    expected_set = set(expected)
    if not expected_set:
        return float("nan")
    return len(expected_set & set(retrieved_docs[:k])) / len(expected_set)


def reciprocal_rank(expected: Sequence[str], retrieved_docs: Sequence[str]) -> float:
    """1 / position of the first chunk whose document is expected, else 0."""
    expected_set = set(expected)
    for position, doc in enumerate(retrieved_docs, start=1):
        if doc in expected_set:
            return 1.0 / position
    return 0.0


def score_ranking(expected: Sequence[str], ranked_docs: Sequence[str]) -> dict[str, float]:
    """Per-query metrics for one ranked list of chunk documents."""
    return {
        "recall_at_5": recall_at_k(expected, ranked_docs, 5),
        "mrr": reciprocal_rank(expected, ranked_docs),
        "hit_at_1": 1.0 if ranked_docs and ranked_docs[0] in set(expected) else 0.0,
    }


def paired_summary(
    a: Sequence[float],
    b: Sequence[float],
    groups: Sequence[int] | None = None,
    n_boot: int = 10000,
    seed: int = 0,
) -> dict[str, Any]:
    """Paired difference b - a with percentile bootstrap 95% CIs.

    ``ci95`` resamples queries. When ``groups`` is given, ``ci95_group``
    resamples whole question groups instead: paraphrases in one group are not
    independent, so this interval is the honest one when groups are large.
    """
    diffs = np.asarray(b, dtype=float) - np.asarray(a, dtype=float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(diffs), size=(n_boot, len(diffs)))
    lo, hi = np.percentile(diffs[idx].mean(axis=1), [2.5, 97.5])
    out: dict[str, Any] = {
        "n": len(diffs),
        "mean_diff": float(diffs.mean()),
        "ci95": [float(lo), float(hi)],
        "wins": int((diffs > 0).sum()),
        "ties": int((diffs == 0).sum()),
        "losses": int((diffs < 0).sum()),
    }
    if groups is not None:
        gids = np.asarray(groups)
        unique = np.unique(gids)
        sums = np.array([diffs[gids == g].sum() for g in unique])
        counts = np.array([(gids == g).sum() for g in unique])
        pick = rng.integers(0, len(unique), size=(n_boot, len(unique)))
        boot = sums[pick].sum(axis=1) / counts[pick].sum(axis=1)
        glo, ghi = np.percentile(boot, [2.5, 97.5])
        out["n_groups"] = len(unique)
        out["ci95_group"] = [float(glo), float(ghi)]
        lo, hi = min(lo, glo), max(hi, ghi)
    out["established"] = bool(lo > 0 or hi < 0)
    return out


def build_reranker_pairs(
    query: str,
    sources: Sequence[str],
    candidates: Sequence[dict[str, str]],
    max_positives: int,
    max_negatives: int,
) -> list[dict[str, Any]]:
    """(query, chunk, label) pairs from one query's retrieved candidates.

    Positives are candidate chunks from any listed source document. Negatives
    are the highest-ranked candidates whose document is not a listed source,
    so no labelled source is ever trained as a negative.
    """
    source_set = set(sources)
    positives = [c for c in candidates if c["doc"] in source_set][:max_positives]
    negatives = [c for c in candidates if c["doc"] not in source_set][:max_negatives]
    pairs = [{"sentence1": query, "sentence2": c["text"], "label": 1.0} for c in positives]
    pairs += [{"sentence1": query, "sentence2": c["text"], "label": 0.0} for c in negatives]
    return pairs


def cluster_permutation_p(diffs: Sequence[float], groups: Sequence[int]) -> float:
    """Exact two-sided sign-flip test of the mean paired difference, flipping whole groups.

    Under the null, each group's differences are symmetric around zero, so the
    sign of every group's sum can be flipped. With G groups there are 2**G
    flips; the smallest attainable p-value is 2 / 2**G.
    """
    d = np.asarray(diffs, dtype=float)
    gids = np.asarray(groups)
    sums = np.array([d[gids == g].sum() for g in np.unique(gids)])
    signs = np.array(list(itertools.product((1.0, -1.0), repeat=len(sums))))
    observed = abs(d.sum())
    return float(np.mean(np.abs(signs @ sums) >= observed - 1e-12))


def holm_adjust(p_values: dict[str, float]) -> dict[str, float]:
    """Holm step-down adjusted p-values for one family of comparisons."""
    ordered = sorted(p_values.items(), key=lambda kv: kv[1])
    m = len(ordered)
    adjusted: dict[str, float] = {}
    running = 0.0
    for rank, (key, p) in enumerate(ordered):
        running = max(running, min(1.0, (m - rank) * p))
        adjusted[key] = running
    return adjusted
