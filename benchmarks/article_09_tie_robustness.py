"""How much does the retriever-order baseline depend on RRF tie order?

HybridSearchPipeline breaks tied RRF scores by the iteration order of random
chunk IDs, so the "no reranker" row in rerankers_<date>.json is one draw of
an arbitrary order. This script reshuffles every group of tied candidates
for the test questions and recomputes the baseline. Reranker rankings do not
depend on candidate order (ties in reranker scores aside), so their per-query
metrics are read from the reranker artifact unchanged.

Usage:
    uv run python benchmarks/article_09_tie_robustness.py
"""

from __future__ import annotations

import json
import random
import sys
from itertools import groupby
from pathlib import Path
from typing import Any

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.article_09_eval import score_ranking  # noqa: E402
from benchmarks.benchmark_custom_embeddings import git_provenance  # noqa: E402
from benchmarks.build_article_09_candidates import load_candidates  # noqa: E402
from scripts.prepare_dl_training_data import load_questions  # noqa: E402

DATA = PROJECT_ROOT / "results" / "data" / "article_09"
CANDIDATES = DATA / "candidates_2026-10-10.json"
RERANKERS = DATA / "rerankers_2026-10-10.json"
SHUFFLES = 1000
METRICS = ("recall_at_5", "mrr", "hit_at_1")


def shuffle_ties(ranked: list[dict[str, Any]], rng: random.Random) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for _, group in groupby(ranked, key=lambda c: c["rrf_score"]):
        block = list(group)
        rng.shuffle(block)
        out += block
    return out


def main() -> None:
    provenance = git_provenance()
    split = {
        q["id"]: q
        for q in json.loads((PROJECT_ROOT / "datasets/dl_training_split.json").read_text())[
            "questions"
        ]
    }
    questions = {q["id"]: q for q in load_questions()}
    test_ids = [i for i in questions if split[i]["split"] == "test"]
    candidates = load_candidates(CANDIDATES)
    rerankers = json.loads(RERANKERS.read_text())["per_query"]

    tied_questions = sum(
        1 for i in test_ids if len({c["rrf_score"] for c in candidates[i]}) < len(candidates[i])
    )
    rng = random.Random(0)
    draws: dict[str, list[float]] = {m: [] for m in METRICS}
    for _ in range(SHUFFLES):
        per_q = [
            score_ranking(
                questions[i]["source_docs"], [c["doc"] for c in shuffle_ties(candidates[i], rng)]
            )
            for i in test_ids
        ]
        for m in METRICS:
            draws[m].append(float(np.mean([p[m] for p in per_q])))

    def spread(values: list[float]) -> dict[str, float]:
        arr = np.asarray(values)
        return {
            "min": round(float(arr.min()), 4),
            "p2_5": round(float(np.percentile(arr, 2.5)), 4),
            "median": round(float(np.median(arr)), 4),
            "p97_5": round(float(np.percentile(arr, 97.5)), 4),
            "max": round(float(arr.max()), 4),
        }

    reranker_means = {
        row: {
            m: round(float(np.mean([rerankers[row][i][m] for i in test_ids])), 4) for m in METRICS
        }
        for row in ("retriever", "stock_l6", "trained_l6_seed_mean", "stock_l12", "flashrank_l12")
    }
    result = {
        "provenance": {
            **provenance,
            "candidates": str(CANDIDATES.relative_to(PROJECT_ROOT)),
            "rerankers": str(RERANKERS.relative_to(PROJECT_ROOT)),
        },
        "shuffles": SHUFFLES,
        "test_questions": len(test_ids),
        "test_questions_with_tied_rrf_scores": tied_questions,
        "retriever_baseline_under_tie_shuffles": {m: spread(draws[m]) for m in METRICS},
        "recorded_means": reranker_means,
        "share_of_shuffles_where_baseline_mrr_exceeds": {
            row: round(float(np.mean([d > reranker_means[row]["mrr"] for d in draws["mrr"]])), 4)
            for row in ("stock_l6", "trained_l6_seed_mean", "stock_l12", "flashrank_l12")
        },
    }
    out = DATA / "tie_robustness_2026-10-10.json"
    out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
