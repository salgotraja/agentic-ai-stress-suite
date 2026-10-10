"""Count train/evaluation question overlap in the first Article 9 run.

Reconstructs, from git history and the original (gitignored) training files,
how many evaluated questions had also been trained on:

  1. BGE validation rows vs training rows in the original
     datasets/dl_training/{train,val}.json (row-level split after expanding
     each question into several triples).
  2. The reranker evaluation: the first 50 article_01 rows with a source
     document, against the 200 questions the seed-42 shuffle put into
     training. Replayed from the code and data at --ref.
  3. The full-corpus BGE evaluation, which scored every distinct question in
     article_01 and the golden set, against the training questions in (1).

Usage:
    uv run python scripts/audit_article_09_leakage.py \\
        --old-data <path to the original datasets/dl_training> --ref d283fb6
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.article_09_eval import normalize_question  # noqa: E402


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=PROJECT_ROOT, capture_output=True, text=True, check=True
    ).stdout


def _json_at(ref: str, path: str) -> Any:
    return json.loads(_git("show", f"{ref}:{path}"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--old-data", type=Path, required=True)
    parser.add_argument("--ref", default="d283fb6", help="Commit of the first Article 9 run")
    args = parser.parse_args()

    train_rows = json.loads((args.old_data / "train.json").read_text())
    val_rows = json.loads((args.old_data / "val.json").read_text())
    train_q = {normalize_question(r["query"]) for r in train_rows}
    val_q = {normalize_question(r["query"]) for r in val_rows}

    article_01 = _json_at(args.ref, "datasets/synthetic_queries/article_01.json")["queries"]
    golden = _json_at(args.ref, "datasets/golden_set/qa_pairs.json")["qa_pairs"]
    corpus = {
        line.removeprefix("datasets/tech_docs/")
        for line in _git("ls-tree", "-r", "--name-only", args.ref, "datasets/tech_docs").split()
        if line.endswith(".md") and not line.endswith("attribution.md")
    }

    # Reranker: replay build_training_pairs and benchmark_vs_flashrank at --ref.
    shuffled = list(article_01)
    random.Random(42).shuffle(shuffled)
    rr_train = {normalize_question(q["query"]) for q in shuffled[:200]}
    evaluated = []
    for item in [q for q in article_01 if q.get("source_docs")][:50]:
        src = item["source_docs"][0]
        if src in corpus or any(k.endswith(src) for k in corpus):
            evaluated.append(normalize_question(item["query"]))

    # Full-corpus BGE evaluation: distinct questions whose first source exists.
    seen: set[str] = set()
    full_eval: list[str] = []
    for item in article_01 + golden:
        norm = normalize_question(item["query"])
        if norm in seen:
            continue
        seen.add(norm)
        if item.get("source_docs") and item["source_docs"][0] in corpus:
            full_eval.append(norm)

    result = {
        "provenance": {
            "git_commit": _git("rev-parse", "HEAD").strip(),
            "replayed_ref": _git("rev-parse", args.ref).strip(),
            "run_date": datetime.now(UTC).date().isoformat(),
            "old_files_sha256": {
                name: hashlib.sha256((args.old_data / name).read_bytes()).hexdigest()
                for name in ("train.json", "val.json", "metadata.json")
            },
            "normalisation": "lowercase, punctuation removed, whitespace collapsed",
        },
        "bge_validation": {
            "train_rows": len(train_rows),
            "val_rows": len(val_rows),
            "distinct_train_questions": len(train_q),
            "distinct_val_questions": len(val_q),
            "val_questions_also_in_train": len(val_q & train_q),
        },
        "reranker_evaluation": {
            "article_01_rows_at_ref": len(article_01),
            "distinct_article_01_questions_at_ref": len(
                {normalize_question(q["query"]) for q in article_01}
            ),
            "evaluated_rows": len(evaluated),
            "evaluated_rows_whose_question_was_trained_on": sum(
                1 for q in evaluated if q in rr_train
            ),
        },
        "bge_full_corpus_evaluation": {
            "evaluated_questions": len(full_eval),
            "also_in_bge_training": sum(1 for q in full_eval if q in train_q),
        },
    }
    out = PROJECT_ROOT / "results" / "data" / "article_09" / "leakage_audit.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
