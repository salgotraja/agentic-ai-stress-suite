"""Article 9 reranker comparison on held-out questions and real candidates.

Replaces the first benchmark, which ranked the gold document plus 19 random
distractors for questions that were also used in training. Here every
reranker reorders the same frozen top-20 chunks from the hybrid retriever
(results/data/article_09/candidates_*.json) for the questions that
datasets/dl_training_split.json assigns to test.

Rows:
  retriever         the retriever's own RRF order, no reranker
  stock_l6          cross-encoder/ms-marco-MiniLM-L-6-v2, PyTorch, untrained
  trained_l6_seedN  the same model fine-tuned on train-split pairs
  stock_l12         cross-encoder/ms-marco-MiniLM-L-12-v2, PyTorch
  flashrank_l12     FlashRank ms-marco-MiniLM-L-12-v2, the stack's reranker,
                    an INT8-quantised ONNX file run by onnxruntime

Quality uses the Article 1 definitions at document level. Timing runs every
model on CPU with the same thread count, one 20-pair batch per call, model
order rotated per query and pass.

Usage:
    uv run python benchmarks/benchmark_article_09_rerankers.py --seeds 13 21 42
"""

from __future__ import annotations

import argparse
import importlib.metadata as metadata
import json
import platform
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.article_09_eval import paired_summary, score_ranking  # noqa: E402
from benchmarks.build_article_09_candidates import load_candidates  # noqa: E402
from scripts.prepare_dl_training_data import load_questions  # noqa: E402

CANDIDATES = PROJECT_ROOT / "results" / "data" / "article_09" / "candidates_2026-10-10.json"
SPLIT_MANIFEST = PROJECT_ROOT / "datasets" / "dl_training_split.json"
L6 = "cross-encoder/ms-marco-MiniLM-L-6-v2"
L12 = "cross-encoder/ms-marco-MiniLM-L-12-v2"
FLASHRANK_MODEL = "ms-marco-MiniLM-L-12-v2"
TRAINED_DIR = PROJECT_ROOT / "models" / "cross_encoder_finetuned"
METRICS = ("recall_at_5", "mrr", "hit_at_1")

Scorer = Callable[[str, list[str]], list[float]]


def _cross_encoder_scorer(name_or_path: str) -> tuple[Scorer, Any]:
    from sentence_transformers import CrossEncoder

    model = CrossEncoder(name_or_path, num_labels=1, device="cpu")

    def score(query: str, texts: list[str]) -> list[float]:
        return [float(x) for x in model.predict([[query, t] for t in texts], batch_size=32)]

    return score, model


def _flashrank_scorer(threads: int) -> tuple[Scorer, dict[str, Any]]:
    import onnxruntime as ort
    from flashrank import Ranker, RerankRequest

    ranker = Ranker(
        model_name=FLASHRANK_MODEL, cache_dir=str(PROJECT_ROOT / "models" / "flashrank")
    )
    onnx_file = next(Path(ranker.model_dir).glob("*.onnx"))
    options = ort.SessionOptions()
    options.intra_op_num_threads = threads
    options.inter_op_num_threads = 1
    ranker.session = ort.InferenceSession(str(onnx_file), sess_options=options)

    def score(query: str, texts: list[str]) -> list[float]:
        passages = [{"id": i, "text": t} for i, t in enumerate(texts)]
        ranked = ranker.rerank(RerankRequest(query=query, passages=passages))
        by_id = {int(p["id"]): float(p["score"]) for p in ranked}
        return [by_id[i] for i in range(len(texts))]

    info = {"onnx_file": onnx_file.name, "onnx_bytes": onnx_file.stat().st_size}
    return score, info


def _rank_docs(candidates: list[dict[str, Any]], scores: list[float] | None) -> list[str]:
    if scores is None:
        return [c["doc"] for c in candidates]
    order = sorted(range(len(candidates)), key=lambda i: (-scores[i], i))
    return [candidates[i]["doc"] for i in order]


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=PROJECT_ROOT, capture_output=True, text=True, check=False
    ).stdout.strip()


def _cpu_name() -> str:
    out = subprocess.run(
        ["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True, check=False
    )
    return out.stdout.strip() or platform.processor()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, nargs="+", default=[13, 21, 42])
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--timing-passes", type=int, default=3)
    args = parser.parse_args()

    import torch

    torch.set_num_threads(args.threads)

    split = json.loads(SPLIT_MANIFEST.read_text())
    meta = {q["id"]: q for q in split["questions"]}
    questions = {q["id"]: q for q in load_questions()}
    test_ids = [qid for qid in questions if meta[qid]["split"] == "test"]
    groups = [meta[qid]["group"] for qid in test_ids]
    train_docs = {
        d for qid, q in questions.items() if meta[qid]["split"] == "train" for d in q["source_docs"]
    }
    seen = {qid: bool(set(questions[qid]["source_docs"]) & train_docs) for qid in test_ids}
    candidates = load_candidates(CANDIDATES)

    scorers: dict[str, Scorer] = {}
    scorers["stock_l6"], _ = _cross_encoder_scorer(L6)
    for seed in args.seeds:
        scorers[f"trained_l6_seed{seed}"], _ = _cross_encoder_scorer(
            str(TRAINED_DIR / f"seed{seed}")
        )
    scorers["stock_l12"], _ = _cross_encoder_scorer(L12)
    scorers["flashrank_l12"], flashrank_info = _flashrank_scorer(args.threads)

    rows = ["retriever", *scorers]
    per_query: dict[str, dict[str, dict[str, float]]] = {r: {} for r in rows}
    for qid in test_ids:
        q = questions[qid]
        texts = [c["text"] for c in candidates[qid]]
        for row in rows:
            scores = None if row == "retriever" else scorers[row](q["query"], texts)
            per_query[row][qid] = score_ranking(
                q["source_docs"], _rank_docs(candidates[qid], scores)
            )

    trained_rows = [f"trained_l6_seed{s}" for s in args.seeds]
    per_query["trained_l6_seed_mean"] = {
        qid: {m: float(np.mean([per_query[r][qid][m] for r in trained_rows])) for m in METRICS}
        for qid in test_ids
    }

    def summary(row: str, ids: list[str]) -> dict[str, float]:
        return {m: round(float(np.mean([per_query[row][i][m] for i in ids])), 4) for m in METRICS}

    seen_ids = [i for i in test_ids if seen[i]]
    unseen_ids = [i for i in test_ids if not seen[i]]
    quality = {
        row: {
            "all": summary(row, test_ids),
            "source_doc_seen_in_train": summary(row, seen_ids),
            "source_doc_unseen_in_train": summary(row, unseen_ids),
        }
        for row in per_query
    }
    recall_at_20 = float(
        np.mean(
            [
                len(set(questions[i]["source_docs"]) & {c["doc"] for c in candidates[i]})
                / len(questions[i]["source_docs"])
                for i in test_ids
            ]
        )
    )

    comparisons_spec = [
        ("stock_l6", "retriever"),
        ("stock_l12", "retriever"),
        ("flashrank_l12", "retriever"),
        ("trained_l6_seed_mean", "retriever"),
        ("trained_l6_seed_mean", "stock_l6"),
        *[(r, "stock_l6") for r in trained_rows],
        ("trained_l6_seed_mean", "flashrank_l12"),
        ("stock_l12", "stock_l6"),
        ("flashrank_l12", "stock_l12"),
    ]
    comparisons = {
        f"{b}_minus_{a}": {
            m: paired_summary(
                [per_query[a][i][m] for i in test_ids],
                [per_query[b][i][m] for i in test_ids],
                groups=groups,
            )
            for m in ("mrr", "recall_at_5")
        }
        for b, a in comparisons_spec
    }

    timed = ["stock_l6", trained_rows[0], "stock_l12", "flashrank_l12"]
    for name in timed:
        for qid in test_ids[:5]:
            scorers[name](questions[qid]["query"], [c["text"] for c in candidates[qid]])
    latencies: dict[str, list[float]] = {name: [] for name in timed}
    for p in range(args.timing_passes):
        for n, qid in enumerate(test_ids):
            texts = [c["text"] for c in candidates[qid]]
            shift = (n + p) % len(timed)
            for name in timed[shift:] + timed[:shift]:
                t0 = time.perf_counter()
                scorers[name](questions[qid]["query"], texts)
                latencies[name].append((time.perf_counter() - t0) * 1000)
    timing = {
        name: {
            "median_ms": round(float(np.median(v)), 2),
            "p90_ms": round(float(np.percentile(v, 90)), 2),
            "n_calls": len(v),
        }
        for name, v in latencies.items()
    }

    run_date = datetime.now(UTC).date().isoformat()
    result = {
        "provenance": {
            "git_commit": _git("rev-parse", "HEAD"),
            "git_dirty": bool(_git("status", "--porcelain", "--untracked-files=no")),
            "run_date": run_date,
            "candidates": str(CANDIDATES.relative_to(PROJECT_ROOT)),
            "split_manifest": str(SPLIT_MANIFEST.relative_to(PROJECT_ROOT)),
            "trained_seeds": args.seeds,
            "hardware": f"{_cpu_name()}, macOS {platform.mac_ver()[0]}",
            "versions": {
                pkg: metadata.version(pkg)
                for pkg in ("torch", "sentence-transformers", "onnxruntime", "flashrank")
            },
            "flashrank": flashrank_info,
        },
        "definitions": {
            "recall_at_5": "fraction of a question's source_docs among the documents of the top 5 chunks",
            "mrr": "1 / rank of the first chunk from a source document, 0 if none in the 20",
            "hit_at_1": "top chunk comes from a source document",
            "ci95": "paired percentile bootstrap over questions, 10000 resamples",
            "ci95_group": "paired bootstrap resampling whole question groups",
            "established": "both intervals exclude zero",
        },
        "test_questions": len(test_ids),
        "test_groups": len(set(groups)),
        "test_questions_source_doc_seen_in_train": len(seen_ids),
        "candidate_recall_at_20": round(recall_at_20, 4),
        "quality": quality,
        "comparisons": comparisons,
        "timing": {
            "device": "cpu",
            "threads": args.threads,
            "batch": "one call per question, 20 (query, chunk) pairs, max_length 512",
            "passes": args.timing_passes,
            "warmup_calls_per_model": 5,
            "models": timing,
        },
        "per_query": per_query,
    }
    out_dir = PROJECT_ROOT / "results" / "data" / "article_09"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"rerankers_{run_date}.json"
    out.write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps({"quality": {r: quality[r]["all"] for r in quality}, "timing": timing}, indent=1)
    )
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
