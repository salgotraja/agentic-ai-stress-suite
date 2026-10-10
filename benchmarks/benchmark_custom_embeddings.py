"""Benchmark stock vs fine-tuned BGE-base-en-v1.5 on held-out questions - task 5.4.

The first version scored every question in article_01.json plus the golden
set, including the questions the model was trained on, against the first
2,000 characters of each document. This version scores only the questions
datasets/dl_training_split.json assigns to test, against every chunk the
series' retriever indexes (SentenceSplitter 500/50), with the Article 1
document-level Recall@5 and MRR.

Encoding: queries get the BGE retrieval instruction that LlamaIndex's
HuggingFaceEmbedding prepends for BGE models; chunks are encoded as plain
text. The pipeline also embeds file-path metadata with each chunk, which ties
its results to the checkout path; plain text keeps this comparison portable,
so the stock row here is close to, not identical with, the pipeline's dense
retriever.

Usage:
    uv run python benchmarks/benchmark_custom_embeddings.py \\
        --model answer_seed13=models/bge_answer_seed13 --model chunk_seed13=models/bge_chunk_seed13

Output:
    results/data/article_09/embedders_<date>.json
"""

from __future__ import annotations

import argparse
import importlib.metadata as metadata
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.article_09_eval import (  # noqa: E402
    QUERY_INSTRUCTION,
    paired_summary,
    score_ranking,
)
from benchmarks.build_article_09_candidates import corpus_chunks  # noqa: E402
from scripts.prepare_dl_training_data import load_questions  # noqa: E402

SPLIT_MANIFEST = PROJECT_ROOT / "datasets" / "dl_training_split.json"
STOCK = "BAAI/bge-base-en-v1.5"
METRICS = ("recall_at_5", "mrr", "hit_at_1")
TOP_N = 20


def dense_rankings(
    model: Any, queries: list[str], chunk_texts: list[str], chunk_docs: list[str]
) -> list[list[str]]:
    """Top-N chunk documents per query by cosine similarity."""
    q = model.encode(
        [QUERY_INSTRUCTION + x for x in queries],
        batch_size=32,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    c = model.encode(chunk_texts, batch_size=32, normalize_embeddings=True, show_progress_bar=False)
    sim = np.asarray(q) @ np.asarray(c).T
    top = np.argsort(-sim, axis=1, kind="stable")[:, :TOP_N]
    return [[chunk_docs[j] for j in row] for row in top]


def evaluate(
    model: Any,
    question_ids: list[str],
    questions: dict[str, dict[str, Any]],
    chunks: dict[str, dict[str, str]],
) -> dict[str, dict[str, float]]:
    """Per-question metrics for one model over the full chunk corpus."""
    keys = sorted(chunks)
    rankings = dense_rankings(
        model,
        [questions[i]["query"] for i in question_ids],
        [chunks[k]["text"] for k in keys],
        [chunks[k]["doc"] for k in keys],
    )
    return {
        qid: score_ranking(questions[qid]["source_docs"], ranked)
        for qid, ranked in zip(question_ids, rankings)
    }


def mean_metrics(per_query: dict[str, dict[str, float]], ids: list[str]) -> dict[str, float]:
    return {m: round(float(np.mean([per_query[i][m] for i in ids])), 4) for m in METRICS}


def git_provenance() -> dict[str, Any]:
    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=PROJECT_ROOT, capture_output=True, text=True, check=False
        ).stdout.strip()

    return {
        "git_commit": git("rev-parse", "HEAD"),
        "git_dirty": bool(git("status", "--porcelain", "--untracked-files=no")),
        "run_date": datetime.now(UTC).date().isoformat(),
        "versions": {p: metadata.version(p) for p in ("torch", "sentence-transformers")},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark stock vs fine-tuned embeddings")
    parser.add_argument(
        "--model",
        action="append",
        default=[],
        help="label=path of a fine-tuned model; repeat for several",
    )
    args = parser.parse_args()

    from sentence_transformers import SentenceTransformer

    split = json.loads(SPLIT_MANIFEST.read_text())
    meta = {q["id"]: q for q in split["questions"]}
    questions = {q["id"]: q for q in load_questions()}
    test_ids = [qid for qid in questions if meta[qid]["split"] == "test"]
    groups = [meta[qid]["group"] for qid in test_ids]
    chunks = corpus_chunks()
    print(f"Test questions: {len(test_ids)}  corpus chunks: {len(chunks)}")

    provenance = git_provenance()
    per_query: dict[str, dict[str, dict[str, float]]] = {}
    per_query["stock"] = evaluate(SentenceTransformer(STOCK), test_ids, questions, chunks)
    for spec in args.model:
        label, path = spec.split("=", 1)
        per_query[label] = evaluate(SentenceTransformer(path), test_ids, questions, chunks)
        print(f"  {label}: {mean_metrics(per_query[label], test_ids)}")

    histories = {}
    for spec in args.model:
        label, path = spec.split("=", 1)
        hist = Path(path) / "training_history.json"
        if hist.exists():
            histories[label] = json.loads(hist.read_text())

    result = {
        "provenance": {**provenance, "split_manifest": "datasets/dl_training_split.json"},
        "protocol": {
            "questions": "test split only",
            "corpus": f"{len(chunks)} chunks, SentenceSplitter(500, 50), plain text",
            "query_prefix": QUERY_INSTRUCTION,
            "recall_at_5": "fraction of source_docs among the documents of the top 5 chunks",
            "mrr": f"1 / rank of the first source chunk within the top {TOP_N}, else 0",
        },
        "test_questions": len(test_ids),
        "test_groups": len(set(groups)),
        "training": histories,
        "quality": {label: mean_metrics(pq, test_ids) for label, pq in per_query.items()},
        "comparisons": {
            f"{label}_minus_stock": {
                m: paired_summary(
                    [per_query["stock"][i][m] for i in test_ids],
                    [per_query[label][i][m] for i in test_ids],
                    groups=groups,
                )
                for m in ("mrr", "recall_at_5")
            }
            for label in per_query
            if label != "stock"
        },
        "per_query": per_query,
    }
    out_dir = PROJECT_ROOT / "results" / "data" / "article_09"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"embedders_{provenance['run_date']}.json"
    out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result["quality"], indent=1))
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
