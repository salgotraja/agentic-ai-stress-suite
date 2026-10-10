"""Robustness checks for the Article 9 held-out results.

--check ties: how much does the retriever-order baseline depend on RRF tie order?
--check stats: exact cluster sign-flip permutation tests with Holm correction,
  seed means for trained models, and a per-group breakdown (post hoc: the
  percentile-bootstrap rule in article_09_eval.paired_summary was in code
  before any model ran; this test was added after the results were seen).
--check components: rebuild the hybrid index and score its BM25, dense and
  fused lists separately on the test questions.

HybridSearchPipeline breaks tied RRF scores by the iteration order of random
chunk IDs, so the "no reranker" row in rerankers_<date>.json is one draw of
an arbitrary order. This script reshuffles every group of tied candidates
for the test questions and recomputes the baseline. Reranker rankings do not
depend on candidate order (ties in reranker scores aside), so their per-query
metrics are read from the reranker artifact unchanged.

Usage:
    uv run python benchmarks/article_09_tie_robustness.py --check all
"""

from __future__ import annotations

import argparse
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

from benchmarks.article_09_eval import (  # noqa: E402
    cluster_permutation_p,
    holm_adjust,
    paired_summary,
    score_ranking,
)
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


def tie_check() -> None:
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


EMBEDDERS = DATA / "embedders_2026-10-10.json"
RERANKER_FAMILY = [
    ("trained_l6", "stock_l6"),
    ("trained_l6", "flashrank_l12"),
    ("trained_l6", "retriever"),
    ("flashrank_l12", "retriever"),
    ("stock_l6", "retriever"),
    ("stock_l12", "retriever"),
    ("stock_l12", "stock_l6"),
    ("flashrank_l12", "stock_l12"),
]
OTHER = [
    ("dense_bge", "retriever"),
    ("trained_l6", "dense_bge"),
    ("flashrank_l12", "dense_bge"),
    ("stock_l6", "dense_bge"),
    ("embedder_answer", "dense_bge"),
    ("embedder_chunk", "dense_bge"),
]


def _seed_mean(rows: dict[str, Any], prefix: str, ids: list[str]) -> dict[str, dict[str, float]]:
    names = [k for k in rows if k.startswith(prefix) and "mean" not in k]
    return {i: {m: float(np.mean([rows[n][i][m] for n in names])) for m in METRICS} for i in ids}


def stats_check() -> None:
    provenance = git_provenance()
    split = {
        q["id"]: q
        for q in json.loads((PROJECT_ROOT / "datasets/dl_training_split.json").read_text())[
            "questions"
        ]
    }
    rr = json.loads(RERANKERS.read_text())["per_query"]
    emb = json.loads(EMBEDDERS.read_text())["per_query"]
    ids = list(rr["retriever"])
    groups = [split[i]["group"] for i in ids]
    rows: dict[str, dict[str, dict[str, float]]] = {
        "retriever": rr["retriever"],
        "stock_l6": rr["stock_l6"],
        "trained_l6": _seed_mean(rr, "trained_l6_seed", ids),
        "stock_l12": rr["stock_l12"],
        "flashrank_l12": rr["flashrank_l12"],
        "dense_bge": emb["stock"],
        "embedder_answer": _seed_mean(emb, "answer_seed", ids),
        "embedder_chunk": _seed_mean(emb, "chunk_seed", ids),
    }

    def compare(b: str, a: str, metric: str) -> dict[str, Any]:
        av = [rows[a][i][metric] for i in ids]
        bv = [rows[b][i][metric] for i in ids]
        out = paired_summary(av, bv, groups=groups)
        out["permutation_p"] = cluster_permutation_p([y - x for x, y in zip(av, bv)], groups)
        return out

    comparisons: dict[str, Any] = {}
    for metric in ("mrr", "recall_at_5"):
        fam = {f"{b}_minus_{a}": compare(b, a, metric) for b, a in RERANKER_FAMILY}
        adj = holm_adjust({k: v["permutation_p"] for k, v in fam.items()})
        for k, v in fam.items():
            v["holm_p_reranker_family"] = adj[k]
        other = {f"{b}_minus_{a}": compare(b, a, metric) for b, a in OTHER}
        comparisons[metric] = {**fam, **other}

    per_group = {}
    for g in sorted(set(groups)):
        sel = [i for i, gid in zip(ids, groups) if gid == g]
        per_group[str(g)] = {
            "questions": len(sel),
            "mrr": {
                name: round(float(np.mean([rows[name][i]["mrr"] for i in sel])), 4) for name in rows
            },
        }
    result = {
        "provenance": {**provenance, "rerankers": RERANKERS.name, "embedders": EMBEDDERS.name},
        "method": {
            "ci95": "percentile bootstrap over questions, 10000 resamples, seed 0",
            "ci95_group": "percentile bootstrap over whole question groups, 10000 resamples",
            "permutation_p": "exact two-sided cluster sign-flip test, all 2**G sign patterns",
            "holm": "Holm step-down over the 8 reranker comparisons, per metric",
            "pre_registered": "the percentile rule (both CIs exclude zero) was in code before "
            "any model ran; the permutation test and Holm correction were added after",
            "trained_rows": "per-question mean over seeds 13, 21, 42",
            "dense_bge": "stock BGE over plain-text chunks, full corpus (embedders artifact)",
        },
        "test_questions": len(ids),
        "test_groups": len(set(groups)),
        "means": {
            name: {m: round(float(np.mean([rows[name][i][m] for i in ids])), 4) for m in METRICS}
            for name in rows
        },
        "comparisons": comparisons,
        "per_group": per_group,
    }
    out = DATA / "stats_2026-10-10.json"
    out.write_text(json.dumps(result, indent=2) + "\n")
    print(f"Wrote {out}")


def components_check() -> None:
    from benchmarks.build_article_09_candidates import (
        COLLECTION,
        DOCS_DIR,
        TOP_K,
        chunk_key,
        doc_of,
    )
    from src.core.config import get_settings
    from src.rag.hybrid_search import HybridSearchPipeline

    provenance = git_provenance()
    settings = get_settings()
    settings.use_reranking = False
    pipeline = HybridSearchPipeline(collection_name=COLLECTION, settings=settings)
    pipeline.build_index(pipeline.load_documents(DOCS_DIR))
    split = json.loads((PROJECT_ROOT / "datasets/dl_training_split.json").read_text())
    test = {q["id"] for q in split["questions"] if q["split"] == "test"}
    per_query: dict[str, dict[str, dict[str, float]]] = {"bm25": {}, "dense": {}, "rrf": {}}
    for item in load_questions():
        if item["id"] not in test:
            continue
        q, src = item["query"], item["source_docs"]
        lists = {
            "bm25": [doc_of(chunk_key(n)) for n, _ in pipeline.retrieve_bm25(q, TOP_K)],
            "dense": [doc_of(chunk_key(n.node)) for n in pipeline.retrieve_dense(q, TOP_K)],
            "rrf": [doc_of(chunk_key(n.node)) for n in pipeline.retrieve(q, TOP_K)],
        }
        for name, docs in lists.items():
            per_query[name][item["id"]] = score_ranking(src, docs)
    result = {
        "provenance": {
            **provenance,
            "retriever": "HybridSearchPipeline rebuilt, reranking off, each list at top 20",
            "note": "dense embeds file-path metadata; rrf tie order is not reproducible",
        },
        "test_questions": len(per_query["rrf"]),
        "means": {
            name: {m: round(float(np.mean([v[m] for v in row.values()])), 4) for m in METRICS}
            for name, row in per_query.items()
        },
        "per_query": per_query,
    }
    out = DATA / "baseline_components_2026-10-10.json"
    out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result["means"], indent=1))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", choices=["ties", "stats", "components", "all"], default="all")
    args = parser.parse_args()
    if args.check in ("ties", "all"):
        tie_check()
    if args.check in ("stats", "all"):
        stats_check()
    if args.check in ("components", "all"):
        components_check()


if __name__ == "__main__":
    main()
