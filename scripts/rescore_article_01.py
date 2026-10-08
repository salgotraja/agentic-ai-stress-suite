#!/usr/bin/env python3
"""Rescore stored Article 1 retrievals against the current question labels.

Reads the first-run per-query ``retrieved_docs`` from a benchmark artifact and
scores them with the same Recall@K and MRR functions the benchmark runner uses.
Questions no longer in the dataset are skipped. No retrieval or LLM call is
made, so the result is exact for the stored run.

Usage:
    uv run python scripts/rescore_article_01.py \
        results/data/article_01_benchmarks_corrected_2026-10-04.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from src.core.benchmarking import BenchmarkRunner  # noqa: E402

DATASET = PROJECT_ROOT / "datasets" / "synthetic_queries" / "article_01.json"


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 1
    artifact = json.loads(Path(sys.argv[1]).read_text())
    questions = {q["id"]: q for q in json.loads(DATASET.read_text())["queries"]}
    scorer = BenchmarkRunner.__new__(BenchmarkRunner)

    for result in artifact["results"]:
        rows = [row for row in result["per_query"] if row["id"] in questions]
        recall = mrr = 0.0
        hit_at_1 = 0
        for row in rows:
            expected = questions[row["id"]]["source_docs"]
            recall += scorer._calculate_recall_at_k(expected, row["retrieved_docs"])
            reciprocal_rank = scorer._calculate_mrr(expected, row["retrieved_docs"])
            mrr += reciprocal_rank
            hit_at_1 += reciprocal_rank == 1.0
        count = len(rows)
        print(
            f"{result['name']:20s} n={count} recall@5={recall / count:.3f} "
            f"mrr={mrr / count:.3f} hit@1={hit_at_1}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
