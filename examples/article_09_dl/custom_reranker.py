"""Custom cross-encoder reranker with attention hooks — task 5.8.

Teaching note: WHY a cross-encoder for reranking?
  In a two-stage retrieval pipeline:
    Stage 1 (recall): Bi-encoder retrieves top-K candidates fast.
      Bi-encoder: embed(query) + embed(doc) → cosine similarity
      Speed: O(1) per query after doc index is built
    Stage 2 (precision): Cross-encoder reranks top-K for accuracy.
      Cross-encoder: embed([CLS] query [SEP] doc [SEP]) → relevance score
      Accuracy: Sees full query-doc interactions; catches phrase matches,
                synonym pairs, and implicit dependencies that bi-encoders miss

  Why not cross-encoder for all retrieval?
    Cross-encoders can't pre-compute doc representations — every (query, doc)
    pair must be processed fresh. At 10K docs × 100 req/sec = 1M forward passes
    per second. Only feasible for small candidate sets (top 20-100 from Stage 1).

Attention hooks — interpretability:
  BERT's attention mechanism computes a weight matrix A ∈ [heads, seq, seq].
  A[h, 0, j] = how much [CLS] attends to token j in head h.
  Averaging across heads gives token-level attribution — which query/doc tokens
  drove the relevance score. This is approximate (attention ≠ importance),
  but gives useful debugging signals for training data curation.

Model: cross-encoder/ms-marco-MiniLM-L-6-v2
  - 6-layer MiniLM, 22M params, ~22MB
  - Pre-trained on MS MARCO passage ranking (500K Q-D pairs)
  - Fast: ~4ms per (query, doc) pair on CPU

Usage:
    # Full pipeline: train on tech docs, eval vs FlashRank
    uv run python examples/article_09_dl/custom_reranker.py --train --eval

    # Eval only (use pre-trained base without domain fine-tuning)
    uv run python examples/article_09_dl/custom_reranker.py --eval --no-train

    # Inspect attention for a single query
    uv run python examples/article_09_dl/custom_reranker.py --inspect
"""

from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path
from typing import Any

import numpy as np
import torch
from sentence_transformers import CrossEncoder
from sentence_transformers.cross_encoder import CrossEncoderTrainer, CrossEncoderTrainingArguments
from sentence_transformers.cross_encoder.losses import BinaryCrossEntropyLoss

from datasets import Dataset  # type: ignore[attr-defined]

RESULTS_DIR = Path("results/data")
CHARTS_DIR = Path("results/charts/article_09")
MODEL_DIR = Path("models/cross_encoder_finetuned")
BASE_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
DOCS_DIR = Path("datasets/tech_docs")
QUERIES_FILE = Path("datasets/synthetic_queries/article_01.json")

# Training hyperparameters — intentionally small for fast smoke-test teaching
TRAIN_EPOCHS = 1
BATCH_SIZE = 16
MAX_DOC_CHARS = 1500  # Truncate docs to fit within 512-token context window
NEGATIVES_PER_QUERY = 4
MAX_TRAIN_QUERIES = 200  # Cap training set for speed


# ---------------------------------------------------------------------------
# Data preparation
# ---------------------------------------------------------------------------


def _load_corpus() -> dict[str, str]:
    """Load tech docs corpus. Returns {relative_path: text[:MAX_DOC_CHARS]}."""
    corpus: dict[str, str] = {}
    for md in sorted(DOCS_DIR.rglob("*.md")):
        if md.name == "attribution.md":
            continue
        key = str(md.relative_to(DOCS_DIR))
        corpus[key] = md.read_text(encoding="utf-8")[:MAX_DOC_CHARS]
    return corpus


def build_training_pairs(
    corpus: dict[str, str],
    rng: random.Random,
) -> list[dict[str, Any]]:
    """Build (query, document, label) pairs for binary cross-entropy training.

    Teaching note: Cross-encoder training data format:
      - Positive pair (label=1.0): query + its source document
      - Negative pair (label=0.0): query + random unrelated document
      Hard negatives (BM25 top-K that are wrong) work better but require BM25 retrieval.
      For teaching purposes, random negatives are sufficient to show the training path.

    1 positive + NEGATIVES_PER_QUERY negatives per query gives a
    (1+N):1 ratio — typical for reranker training.
    """
    with open(QUERIES_FILE) as f:
        queries_data = json.load(f)

    all_doc_keys = list(corpus.keys())
    pairs: list[dict[str, Any]] = []

    # Shuffle and cap queries for speed
    all_queries = queries_data["queries"]
    rng.shuffle(all_queries)
    all_queries = all_queries[:MAX_TRAIN_QUERIES]

    for item in all_queries:
        query = item["query"]
        source_docs = item.get("source_docs", [])
        if not source_docs:
            continue
        src_key = source_docs[0]
        if src_key not in corpus:
            # Try normalising path (some entries use bare filename)
            matches = [k for k in all_doc_keys if k.endswith(src_key)]
            if not matches:
                continue
            src_key = matches[0]

        # Positive pair
        pairs.append({"sentence1": query, "sentence2": corpus[src_key], "label": 1.0})

        # Random negative pairs — avoid sampling the actual source doc
        negatives = [k for k in all_doc_keys if k != src_key]
        for neg_key in rng.sample(negatives, min(NEGATIVES_PER_QUERY, len(negatives))):
            pairs.append({"sentence1": query, "sentence2": corpus[neg_key], "label": 0.0})

    return pairs


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------


def train_reranker(pairs: list[dict[str, Any]]) -> Any:
    """Fine-tune the cross-encoder on domain Q-D pairs.

    Teaching note: CrossEncoderTrainer (sentence-transformers v5) wraps
    HuggingFace Trainer. The loss is BinaryCrossEntropyLoss which applies
    sigmoid to the single-logit output and computes BCE against {0, 1} labels.
    This produces a calibrated probability score ∈ (0, 1) at inference.
    """
    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    model: Any = CrossEncoder(BASE_MODEL, num_labels=1)  # type: ignore[operator]
    loss_fn = BinaryCrossEntropyLoss(model)

    # 80/20 train/val split
    split = int(len(pairs) * 0.8)
    train_dataset = Dataset.from_list(pairs[:split])
    val_dataset = Dataset.from_list(pairs[split:])

    training_args = CrossEncoderTrainingArguments(
        output_dir=str(MODEL_DIR),
        num_train_epochs=TRAIN_EPOCHS,
        per_device_train_batch_size=BATCH_SIZE,
        save_strategy="no",
        logging_steps=20,
        report_to="none",
    )

    trainer = CrossEncoderTrainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=val_dataset,
        loss=loss_fn,
    )

    print(f"  Training on {len(pairs[:split])} pairs, validating on {len(pairs[split:])} pairs...")
    t0 = time.time()
    trainer.train()
    elapsed = time.time() - t0
    print(f"  Training took {elapsed:.1f}s")

    model.save(str(MODEL_DIR))
    print(f"  Model saved to {MODEL_DIR}")
    return model


# ---------------------------------------------------------------------------
# Attention hooks — interpretability
# ---------------------------------------------------------------------------


def extract_attention_attributions(
    model: Any,
    query: str,
    document: str,
) -> dict[str, Any]:
    """Extract [CLS]-to-token attention weights from the last BERT layer.

    Teaching note: Attention hooks work by registering a callback that fires
    during the forward pass and captures the attention weight tensor before it
    is used to compute the weighted sum of values. The hook receives:
      module: the attention layer object
      input: tuple of tensors passed to the layer
      output: tuple of (context_layer, attention_weights_if_output_attentions=True)

    We force output_attentions=True in the model forward call, then the hook
    receives attention weights with shape [batch, heads, seq_len, seq_len].
    Row 0 (the [CLS] token) is the relevance-driving row for reranking.
    """
    captured: dict[str, torch.Tensor] = {}

    def _hook(module: torch.nn.Module, inp: Any, out: Any) -> None:
        # out is (context_layer, attention_weights) when output_attentions=True
        if isinstance(out, tuple) and len(out) > 1 and out[1] is not None:
            captured["weights"] = out[1].detach().cpu()

    # Register hook on the LAST encoder layer's self-attention
    bert_model = model.model.bert  # BertForSequenceClassification → .bert → BertModel
    last_layer = bert_model.encoder.layer[-1]
    handle = last_layer.attention.self.register_forward_hook(_hook)

    # Tokenise and run forward pass with output_attentions=True.
    # Move inputs to the model's device (MPS after training, CPU for base model).
    tokenizer = model.tokenizer
    encoding = tokenizer(
        query,
        document,
        return_tensors="pt",
        padding=True,
        truncation=True,
        max_length=512,
    )
    device = next(model.model.parameters()).device
    encoding = {k: v.to(device) for k, v in encoding.items()}
    with torch.no_grad():
        model.model(**encoding, output_attentions=True)

    handle.remove()

    if "weights" not in captured:
        return {"error": "attention not captured"}

    # weights: [1, heads, seq, seq] → [heads, seq]
    attention = captured["weights"][0]  # [heads, seq_len, seq_len]
    # Average across heads; take row 0 ([CLS]) as the relevance attribution
    cls_attention = attention.mean(dim=0)[0].numpy()  # [seq_len]

    tokens = tokenizer.convert_ids_to_tokens(encoding["input_ids"][0].cpu())

    # Build top-10 attributed tokens (skip [CLS], [SEP], [PAD])
    skip = {"[CLS]", "[SEP]", "[PAD]"}
    attributed = [
        (tokens[i], float(cls_attention[i])) for i in range(len(tokens)) if tokens[i] not in skip
    ]
    attributed.sort(key=lambda x: x[1], reverse=True)

    return {
        "query": query,
        "score": float(model.predict([[query, document]])[0]),
        "top_attributed_tokens": attributed[:10],
    }


# ---------------------------------------------------------------------------
# Benchmark vs FlashRank
# ---------------------------------------------------------------------------


def _ndcg_at_k(ranked_docs: list[str], relevant_doc: str, k: int) -> float:
    """Normalised Discounted Cumulative Gain at K.

    Teaching note: NDCG penalises correct answers appearing lower in the
    ranking. A hit at position 1 contributes 1/log2(2)=1.0; at position 3
    contributes 1/log2(4)=0.5. NDCG@K normalises by the ideal ranking (hit
    at position 1 always), so the score is always ∈ [0, 1].
    """
    for i, doc_path in enumerate(ranked_docs[:k]):
        if doc_path == relevant_doc:
            # DCG / IDCG; IDCG = 1 (ideal: relevant doc at position 0)
            return 1.0 / np.log2(i + 2)  # i+2 because log2(1)=0 undefined
    return 0.0


def benchmark_vs_flashrank(
    cross_encoder: Any,
    corpus: dict[str, str],
) -> dict[str, Any]:
    """Compare custom cross-encoder vs FlashRank on tech docs retrieval.

    Teaching note: Evaluation protocol:
      1. For each test query, we start from a top-20 shortlist (simulating
         bi-encoder retrieval). In production this comes from vector search;
         here we construct it from the ground-truth doc + 19 random distractors.
      2. Both rerankers see the same shortlist and reorder it.
      3. We measure:
         - NDCG@5: whether the ground-truth doc appears in the top-5
         - Latency (ms per query): time to rerank 20 candidates
    """
    from flashrank import RerankRequest

    try:
        from flashrank import Ranker as FlashRanker
    except ImportError:
        print("  [skip] flashrank not installed — install with: uv add flashrank")
        return {}

    flash_ranker = FlashRanker(model_name="ms-marco-MiniLM-L-12-v2", cache_dir="/tmp/flashrank")

    with open(QUERIES_FILE) as f:
        queries_data = json.load(f)

    all_doc_keys = list(corpus.keys())
    rng = random.Random(42)

    ce_ndcg: list[float] = []
    fr_ndcg: list[float] = []
    ce_latency: list[float] = []
    fr_latency: list[float] = []

    test_queries = [q for q in queries_data["queries"] if q.get("source_docs")][:50]

    for item in test_queries:
        query = item["query"]
        src_key = item["source_docs"][0]
        if src_key not in corpus:
            matches = [k for k in all_doc_keys if k.endswith(src_key)]
            if not matches:
                continue
            src_key = matches[0]

        # Build shortlist: ground-truth doc + 19 random distractors
        distractors = rng.sample([k for k in all_doc_keys if k != src_key], 19)
        shortlist_keys = [src_key] + distractors
        rng.shuffle(shortlist_keys)
        shortlist_docs = [corpus[k] for k in shortlist_keys]

        # --- FlashRank ---
        fr_passages = [
            {"id": i, "text": doc, "meta": {"path": key}}
            for i, (doc, key) in enumerate(zip(shortlist_docs, shortlist_keys))
        ]
        t0 = time.perf_counter()
        fr_request = RerankRequest(query=query, passages=fr_passages)
        fr_ranked = flash_ranker.rerank(fr_request)
        fr_latency.append((time.perf_counter() - t0) * 1000)
        fr_paths = [str(p["meta"]["path"]) for p in fr_ranked]
        fr_ndcg.append(_ndcg_at_k(fr_paths, src_key, k=5))

        # --- Custom cross-encoder ---
        pairs_for_ranking = [[query, doc] for doc in shortlist_docs]
        t0 = time.perf_counter()
        scores = cross_encoder.predict(pairs_for_ranking)
        ce_latency.append((time.perf_counter() - t0) * 1000)
        sorted_indices = np.argsort(scores)[::-1].tolist()
        ce_paths = [shortlist_keys[i] for i in sorted_indices]
        ce_ndcg.append(_ndcg_at_k(ce_paths, src_key, k=5))

    results = {
        "cross_encoder": {
            "model": BASE_MODEL,
            "ndcg_at_5": round(float(np.mean(ce_ndcg)), 4),
            "latency_ms_median": round(float(np.median(ce_latency)), 2),
            "n_queries": len(ce_ndcg),
        },
        "flashrank": {
            "model": "ms-marco-MiniLM-L-12-v2",
            "ndcg_at_5": round(float(np.mean(fr_ndcg)), 4),
            "latency_ms_median": round(float(np.median(fr_latency)), 2),
            "n_queries": len(fr_ndcg),
        },
    }

    print(
        f"  Custom CE:  NDCG@5={results['cross_encoder']['ndcg_at_5']:.4f}  "
        f"latency={results['cross_encoder']['latency_ms_median']:.1f}ms"
    )
    print(
        f"  FlashRank:  NDCG@5={results['flashrank']['ndcg_at_5']:.4f}  "
        f"latency={results['flashrank']['latency_ms_median']:.1f}ms"
    )

    return results


# ---------------------------------------------------------------------------
# Chart
# ---------------------------------------------------------------------------


def plot_benchmark(results: dict[str, Any], output_path: Path) -> None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        models = ["Custom\nCross-Encoder", "FlashRank\n(baseline)"]
        ndcg_vals = [
            results["cross_encoder"]["ndcg_at_5"],
            results["flashrank"]["ndcg_at_5"],
        ]
        latency_vals = [
            results["cross_encoder"]["latency_ms_median"],
            results["flashrank"]["latency_ms_median"],
        ]

        fig, axes = plt.subplots(1, 2, figsize=(10, 5))
        fig.suptitle("Custom Cross-Encoder vs FlashRank\n(top-20 reranking, tech docs corpus)")

        axes[0].bar(models, ndcg_vals, color=["#e63946", "#457b9d"], width=0.5)
        axes[0].set_ylabel("NDCG@5 — higher is better")
        axes[0].set_ylim(0, 1)
        for i, v in enumerate(ndcg_vals):
            axes[0].text(i, v + 0.02, f"{v:.3f}", ha="center", fontsize=10)
        axes[0].grid(axis="y", alpha=0.4)

        axes[1].bar(models, latency_vals, color=["#e63946", "#457b9d"], width=0.5)
        axes[1].set_ylabel("Median latency (ms) — lower is better")
        for i, v in enumerate(latency_vals):
            axes[1].text(i, v + 1, f"{v:.1f}ms", ha="center", fontsize=10)
        axes[1].grid(axis="y", alpha=0.4)

        plt.tight_layout()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(output_path, dpi=150, bbox_inches="tight")
        plt.close()
        print(f"  Saved chart: {output_path}")
    except ImportError:
        print("  [skip] matplotlib not available")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Custom cross-encoder reranker (task 5.8)")
    parser.add_argument("--train", action="store_true", help="Fine-tune on tech docs pairs")
    parser.add_argument("--eval", action="store_true", help="Benchmark vs FlashRank")
    parser.add_argument("--inspect", action="store_true", help="Show attention attributions")
    args = parser.parse_args()

    if not (args.train or args.eval or args.inspect):
        # Default: run everything
        args.train = True
        args.eval = True
        args.inspect = True

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    corpus = _load_corpus()
    print(f"Corpus: {len(corpus)} documents")

    if args.train:
        print("\n[Training]")
        rng = random.Random(42)
        pairs = build_training_pairs(corpus, rng)
        print(
            f"  Built {len(pairs)} training pairs "
            f"({sum(1 for p in pairs if p['label'] == 1.0)} positive, "
            f"{sum(1 for p in pairs if p['label'] == 0.0)} negative)"
        )
        model = train_reranker(pairs)
    else:
        # Load base model (no domain fine-tuning)
        if MODEL_DIR.exists():
            print(f"\nLoading fine-tuned model from {MODEL_DIR}...")
            model: Any = CrossEncoder(str(MODEL_DIR), num_labels=1)  # type: ignore[operator,no-redef]
        else:
            print(f"\nLoading base model {BASE_MODEL}...")
            model = CrossEncoder(BASE_MODEL, num_labels=1)  # type: ignore[operator]

    if args.inspect:
        print("\n[Attention attributions]")
        test_query = "What is FastAPI dependency injection?"
        doc_keys = list(corpus.keys())
        # Pick the FastAPI intro doc as a positive example
        pos_key = next((k for k in doc_keys if "fastapi" in k.lower()), doc_keys[0])
        print(f"  Query: '{test_query}'")
        print(f"  Document: {pos_key}")
        attribution = extract_attention_attributions(model, test_query, corpus[pos_key])
        print(f"  Relevance score: {attribution.get('score', 'n/a'):.4f}")
        print("  Top 10 attended tokens:")
        for token, weight in attribution.get("top_attributed_tokens", []):
            bar = "#" * int(weight * 40)
            print(f"    {token:<20} {bar} ({weight:.4f})")

    if args.eval:
        print("\n[Benchmarking vs FlashRank]")
        results = benchmark_vs_flashrank(model, corpus)
        if results:
            # Save results
            out = RESULTS_DIR / "custom_reranker_benchmark.json"
            with open(out, "w") as f:
                json.dump(results, f, indent=2)
            print(f"\n  Results saved: {out}")

            # Chart
            plot_benchmark(results, CHARTS_DIR / "04_reranker_comparison.png")


if __name__ == "__main__":
    main()
