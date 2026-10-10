"""Prepare training data for fine-tuning BGE-base-en-v1.5 - task 5.2.

Teaching note: WHY contrastive training pairs?
  Embedding models are trained with contrastive loss: given a query, the model
  must learn to score the correct answer document higher than any negative.
  Quality of negatives matters enormously:
  - Random negatives: easy, model learns slowly (obvious differences)
  - Hard negatives: retrieved by BM25/dense but wrong answer (forces model to
    distinguish semantically similar but factually different documents)
  Hard negatives from retrieval errors (docs BM25 found but shouldn't have)
  are the strongest signal for domain fine-tuning.

Data strategy:
  - Questions: datasets/synthetic_queries/article_01.json (142) plus
    datasets/golden_set/qa_pairs.json (50), 192 in total.
  - Split first, then build pairs. Questions are grouped (same normalised
    text, question-embedding cosine >= 0.90, or identical source_docs set)
    and whole groups go to train or test. The first version expanded each
    question into several triples and split the triples, so every validation
    question also appeared in training.
  - The split is written to datasets/dl_training_split.json, which is
    committed. Only train questions produce training pairs; test questions
    are scored by benchmarks/benchmark_custom_embeddings.py and
    benchmarks/benchmark_article_09_rerankers.py.
  - Answer triples (train.json): (query, expected_answer, BM25 document that
    is not any listed source). This is the original objective.
  - Chunk triples (train_chunk.json, needs --candidates): (query, highest
    ranked retrieved chunk from a listed source, retrieved chunk from a
    document that is not a listed source). This matches what the retriever
    embeds at inference.

Output schema (JSON list): {"query": str, "positive": str, "negative": str}

Usage:
    uv run python scripts/prepare_dl_training_data.py
    uv run python scripts/prepare_dl_training_data.py \
        --candidates results/data/article_09/candidates_2026-10-10.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.article_09_eval import group_questions, split_groups  # noqa: E402

QUERY_FILES = {
    "article_01": Path("datasets/synthetic_queries/article_01.json"),
    "golden_set": Path("datasets/golden_set/qa_pairs.json"),
}
SPLIT_MANIFEST = Path("datasets/dl_training_split.json")
GROUP_MODEL = "BAAI/bge-base-en-v1.5"
GROUP_THRESHOLD = 0.90
TEST_FRACTION = 0.4
NEGATIVES_PER_QUERY = 6


def load_tech_docs(docs_dir: Path) -> dict[str, str]:
    """Load all tech doc markdown files as {relative_path: content}."""
    docs: dict[str, str] = {}
    for md_file in sorted(docs_dir.rglob("*.md")):
        if md_file.name == "attribution.md":
            continue
        # Use path relative to docs_dir as key so it matches source_docs field
        rel = md_file.relative_to(docs_dir)
        docs[str(rel)] = md_file.read_text(encoding="utf-8")
    return docs


def build_bm25_index(docs: dict[str, str]) -> tuple[list[str], list[list[str]]]:
    """Build a simple BM25-style inverted index.

    Teaching note: We implement a lightweight BM25 here rather than importing
    rank_bm25 to avoid adding a dependency to this script. The tokenisation is
    word-level lowercase split - good enough for hard-negative mining where we
    just need approximate keyword overlap, not production-quality ranking.
    """
    doc_ids = list(docs.keys())
    tokenised = [docs[d].lower().split() for d in doc_ids]
    return doc_ids, tokenised


def bm25_top_k(
    query_tokens: list[str],
    doc_ids: list[str],
    tokenised_docs: list[list[str]],
    k: int = 5,
) -> list[str]:
    """Return top-k doc IDs by BM25 TF-IDF approximation (no IDF for speed)."""

    query_set = set(query_tokens)
    scores: list[float] = []
    avg_len = sum(len(d) for d in tokenised_docs) / max(len(tokenised_docs), 1)
    k1, b = 1.5, 0.75

    for tokens in tokenised_docs:
        tf_sum = 0.0
        counter: dict[str, int] = {}
        for t in tokens:
            counter[t] = counter.get(t, 0) + 1
        doc_len = len(tokens)
        for term in query_set:
            tf = counter.get(term, 0)
            if tf > 0:
                # BM25 TF normalisation (skip IDF for speed - uniform across corpus)
                tf_norm = tf * (k1 + 1) / (tf + k1 * (1 - b + b * doc_len / avg_len))
                tf_sum += tf_norm
        scores.append(tf_sum)

    ranked = sorted(range(len(doc_ids)), key=lambda i: scores[i], reverse=True)
    return [doc_ids[i] for i in ranked[:k]]


def load_questions() -> list[dict[str, Any]]:
    """All questions with their origin file; ids are unique across both files."""
    article_01 = json.loads(QUERY_FILES["article_01"].read_text())["queries"]
    golden = json.loads(QUERY_FILES["golden_set"].read_text())["qa_pairs"]
    rows = [{**q, "origin": "article_01"} for q in article_01]
    rows += [{**q, "origin": "golden_set"} for q in golden]
    return rows


def build_split_manifest(questions: list[dict[str, Any]], seed: int) -> dict[str, Any]:
    """Group questions, assign whole groups to train or test, describe the rule."""
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(GROUP_MODEL, device="cpu")
    texts = [q["query"] for q in questions]
    emb = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    similarity = emb @ emb.T
    sources = [frozenset(q.get("source_docs", [])) for q in questions]
    groups = group_questions(texts, sources, similarity, GROUP_THRESHOLD)
    splits = split_groups(groups, TEST_FRACTION, seed)

    train_docs = {d for q, s in zip(questions, splits) if s == "train" for d in q["source_docs"]}
    return {
        "rule": (
            "Questions share a group when their normalised text is equal, when the cosine "
            f"similarity of their {GROUP_MODEL} question embeddings (no instruction prefix) "
            f"is >= {GROUP_THRESHOLD}, or when their source_docs sets are identical. Groups are "
            f"shuffled with the seed and assigned to test until {TEST_FRACTION:.0%} of "
            "questions are in test. No dev split: nothing is selected on held-out data."
        ),
        "seed": seed,
        "group_threshold": GROUP_THRESHOLD,
        "test_fraction": TEST_FRACTION,
        "inputs": {
            name: hashlib.sha256(path.read_bytes()).hexdigest()
            for name, path in QUERY_FILES.items()
        },
        "counts": {
            "questions": len(questions),
            "groups": len(set(groups)),
            "train": splits.count("train"),
            "test": splits.count("test"),
            "test_groups": len({g for g, s in zip(groups, splits) if s == "test"}),
            "test_with_a_source_doc_also_labelled_in_train": sum(
                1
                for q, s in zip(questions, splits)
                if s == "test" and set(q["source_docs"]) & train_docs
            ),
        },
        "questions": [
            {"id": q["id"], "origin": q["origin"], "group": g, "split": s}
            for q, g, s in zip(questions, groups, splits)
        ],
    }


def build_answer_triples(
    train_questions: list[dict[str, Any]],
    docs: dict[str, str],
    doc_ids: list[str],
    tokenised_docs: list[list[str]],
) -> list[dict[str, str]]:
    """(query, expected_answer, BM25 negative) for train questions only.

    Negatives skip every listed source document, not only the first one.
    """
    triples: list[dict[str, str]] = []
    for item in train_questions:
        sources = set(item.get("source_docs", []))
        candidates = bm25_top_k(item["query"].lower().split(), doc_ids, tokenised_docs, k=20)
        negatives = [c for c in candidates if c not in sources][:NEGATIVES_PER_QUERY]
        for neg in negatives:
            triples.append(
                {
                    "query": item["query"],
                    "positive": item["expected_answer"],
                    "negative": " ".join(docs[neg].split()[:512]),
                }
            )
    return triples


def build_chunk_triples(
    train_questions: list[dict[str, Any]], candidates_path: Path
) -> tuple[list[dict[str, str]], int]:
    """(query, source chunk, non-source chunk) from frozen retriever candidates."""
    from benchmarks.build_article_09_candidates import load_candidates

    frozen = load_candidates(candidates_path)
    triples: list[dict[str, str]] = []
    skipped = 0
    for item in train_questions:
        sources = set(item["source_docs"])
        ranked = frozen[item["id"]]
        positives = [c for c in ranked if c["doc"] in sources]
        negatives = [c for c in ranked if c["doc"] not in sources][:NEGATIVES_PER_QUERY]
        if not positives:
            skipped += 1
            continue
        for neg in negatives:
            triples.append(
                {"query": item["query"], "positive": positives[0]["text"], "negative": neg["text"]}
            )
    return triples, skipped


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare Article 9 split and training pairs")
    parser.add_argument("--output", type=Path, default=Path("datasets/dl_training"))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--candidates",
        type=Path,
        default=None,
        help="Frozen retriever candidates; also writes train_chunk.json",
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    questions = load_questions()
    print(f"Questions: {len(questions)}")

    if SPLIT_MANIFEST.exists():
        manifest = json.loads(SPLIT_MANIFEST.read_text())
        print(f"Using existing split manifest {SPLIT_MANIFEST}")
    else:
        manifest = build_split_manifest(questions, args.seed)
        SPLIT_MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")
        print(f"Wrote split manifest {SPLIT_MANIFEST}")
    split_of = {q["id"]: q["split"] for q in manifest["questions"]}
    train_questions = [q for q in questions if split_of[q["id"]] == "train"]
    print(f"  {manifest['counts']}")

    docs = load_tech_docs(Path("datasets/tech_docs"))
    doc_ids, tokenised = build_bm25_index(docs)
    answer_triples = build_answer_triples(train_questions, docs, doc_ids, tokenised)
    (args.output / "train.json").write_text(json.dumps(answer_triples, indent=2))
    print(f"Answer triples: {len(answer_triples)} from {len(train_questions)} train questions")

    meta: dict[str, Any] = {
        "split_manifest": str(SPLIT_MANIFEST),
        "train_questions": len(train_questions),
        "answer_triples": len(answer_triples),
        "negatives_per_query": NEGATIVES_PER_QUERY,
    }
    if args.candidates is not None:
        chunk_triples, skipped = build_chunk_triples(train_questions, args.candidates)
        (args.output / "train_chunk.json").write_text(json.dumps(chunk_triples, indent=2))
        meta.update({"chunk_triples": len(chunk_triples), "chunk_questions_skipped": skipped})
        print(f"Chunk triples: {len(chunk_triples)} ({skipped} questions had no source chunk)")
    (args.output / "metadata.json").write_text(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
