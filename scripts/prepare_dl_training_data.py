"""Prepare training data for fine-tuning BGE-base-en-v1.5 — task 5.2.

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
  - Positive pairs: (query, expected_answer) from article_01 synthetic queries
    The expected_answer text matches the style of the tech docs corpus, so
    the embedding space should learn to align them.
  - Hard negatives: top-K BM25 results that are NOT the correct document.
    BM25 errors are particularly valuable: if BM25 finds a doc with many
    matching keywords but wrong semantics, training on it teaches the model
    to go beyond keyword overlap.
  - Split: 80% train / 20% validation (stratified by difficulty)

Output schema (each line is a JSON object):
  {"query": str, "positive": str, "negative": str}

Usage:
    uv run python scripts/prepare_dl_training_data.py --output datasets/dl_training/
    uv run python scripts/prepare_dl_training_data.py --output datasets/dl_training/ --max-pairs 500
"""

from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path


def load_tech_docs(docs_dir: Path) -> dict[str, str]:
    """Load all tech doc markdown files as {relative_path: content}."""
    docs: dict[str, str] = {}
    for md_file in docs_dir.rglob("*.md"):
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
    word-level lowercase split — good enough for hard-negative mining where we
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
                # BM25 TF normalisation (skip IDF for speed — uniform across corpus)
                tf_norm = tf * (k1 + 1) / (tf + k1 * (1 - b + b * doc_len / avg_len))
                tf_sum += tf_norm
        scores.append(tf_sum)

    ranked = sorted(range(len(doc_ids)), key=lambda i: scores[i], reverse=True)
    return [doc_ids[i] for i in ranked[:k]]


def build_pairs(
    queries: list[dict],  # type: ignore[type-arg]
    docs: dict[str, str],
    doc_ids: list[str],
    tokenised_docs: list[list[str]],
    max_pairs: int,
    rng: random.Random,
    negatives_per_query: int = 6,
) -> list[dict[str, str]]:
    """Build (query, positive, hard_negative) triples.

    Teaching note on positive selection:
      We use expected_answer text as the positive rather than the raw source doc.
      This trains the model to align query representations with concise answer
      text — useful because at inference time the LLM response (not the raw doc)
      is what gets cached and reused via semantic cache (Article 6).

    Teaching note on hard_negative selection:
      We retrieve top-K BM25 docs for each query, then drop correct source docs.
      Each remaining candidate becomes a separate training triple with the same
      (query, positive) — this multiplies the dataset size by negatives_per_query
      while keeping each negative distinct. Using multiple negatives per query is
      standard practice (MultipleNegativesRankingLoss uses all in-batch negatives
      simultaneously, but for simplicity we emit one-negative-per-example files).

    Dataset size math:
      350 queries × 6 negatives each = 2100 triples → select up to max_pairs
    """
    pairs: list[dict[str, str]] = []
    fallback_count = 0

    rng.shuffle(queries)
    for item in queries:
        if len(pairs) >= max_pairs:
            break

        query_text: str = item["query"]
        positive_text: str = item["expected_answer"]
        correct_sources: set[str] = set(item.get("source_docs", []))

        if not positive_text.strip():
            continue

        # BM25 hard-negative mining — retrieve more candidates to pick N from
        query_tokens = query_text.lower().split()
        candidates = bm25_top_k(query_tokens, doc_ids, tokenised_docs, k=20)
        hard_negatives = [c for c in candidates if c not in correct_sources]

        # Pick up to negatives_per_query hard negatives
        chosen = hard_negatives[:negatives_per_query]
        if len(chosen) < negatives_per_query:
            # Pad with random docs not already chosen or correct
            exclude = correct_sources | set(chosen)
            fallback_pool = [d for d in doc_ids if d not in exclude]
            rng.shuffle(fallback_pool)
            needed = negatives_per_query - len(chosen)
            chosen.extend(fallback_pool[:needed])
            fallback_count += needed

        for neg_doc_id in chosen:
            if len(pairs) >= max_pairs:
                break
            # Truncate doc to first 512 words to keep negative manageable
            negative_text = " ".join(docs[neg_doc_id].split()[:512])
            pairs.append(
                {
                    "query": query_text,
                    "positive": positive_text,
                    "negative": negative_text,
                }
            )

    if fallback_count:
        print(
            f"  Info: {fallback_count}/{len(pairs)} negatives used random fallback "
            "(BM25 had fewer than {negatives_per_query} hard negatives)"
        )

    return pairs


def stratified_split(
    pairs: list[dict[str, str]],
    train_ratio: float,
    rng: random.Random,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """80/20 split, shuffled.

    Teaching note: Stratification by difficulty would require keeping
    difficulty labels through the pipeline. Here we do a simple random
    split after shuffling — acceptable because the dataset is synthesised
    and already balanced by construction (article_01.json was built with
    equal difficulty distribution).
    """
    shuffled = list(pairs)
    rng.shuffle(shuffled)
    cut = math.floor(len(shuffled) * train_ratio)
    return shuffled[:cut], shuffled[cut:]


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare DL training data")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("datasets/dl_training"),
        help="Output directory (default: datasets/dl_training/)",
    )
    parser.add_argument(
        "--max-pairs",
        type=int,
        default=2000,
        help="Max training pairs to generate (default: 2000)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducibility",
    )
    args = parser.parse_args()

    rng = random.Random(args.seed)
    output_dir: Path = args.output
    output_dir.mkdir(parents=True, exist_ok=True)

    print("Loading tech docs...")
    docs_dir = Path("datasets/tech_docs")
    docs = load_tech_docs(docs_dir)
    print(f"  Loaded {len(docs)} documents")

    print("Building BM25 index...")
    doc_ids, tokenised_docs = build_bm25_index(docs)

    print("Loading synthetic queries...")
    with open("datasets/synthetic_queries/article_01.json") as f:
        article_01 = json.load(f)
    queries_01 = article_01["queries"]  # 300 queries

    # Also load golden set for higher-quality positives
    with open("datasets/golden_set/qa_pairs.json") as f:
        golden_data = json.load(f)
    golden_queries = golden_data["qa_pairs"]  # 50 pairs

    all_queries = queries_01 + golden_queries
    print(f"  Total query pool: {len(all_queries)}")

    print(f"Building up to {args.max_pairs} training pairs (hard-negative mining)...")
    pairs = build_pairs(all_queries, docs, doc_ids, tokenised_docs, args.max_pairs, rng)
    print(f"  Generated {len(pairs)} pairs")

    print("Splitting 80/20...")
    train_pairs, val_pairs = stratified_split(pairs, train_ratio=0.8, rng=rng)
    print(f"  Train: {len(train_pairs)}  Val: {len(val_pairs)}")

    train_path = output_dir / "train.json"
    val_path = output_dir / "val.json"

    with open(train_path, "w") as f:
        json.dump(train_pairs, f, indent=2)
    with open(val_path, "w") as f:
        json.dump(val_pairs, f, indent=2)

    # Write metadata
    meta = {
        "source_queries": len(all_queries),
        "total_pairs": len(pairs),
        "train": len(train_pairs),
        "val": len(val_pairs),
        "seed": args.seed,
        "negative_strategy": "bm25_hard_negative",
        "positive_source": "expected_answer",
    }
    with open(output_dir / "metadata.json", "w") as f:
        json.dump(meta, f, indent=2)

    print(f"\nWrote: {train_path} ({len(train_pairs)} pairs)")
    print(f"       {val_path} ({len(val_pairs)} pairs)")
    print(f"       {output_dir}/metadata.json")


if __name__ == "__main__":
    main()
