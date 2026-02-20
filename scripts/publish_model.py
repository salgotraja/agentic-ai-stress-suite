"""Save fine-tuned model with metadata card to models/ directory — task 5.12.

Teaching note: Model versioning for production deployment
  A fine-tuned model without metadata is a liability: you can't tell
  which data it was trained on, what its performance characteristics are,
  or when it was created. Model cards (following HuggingFace convention)
  solve this by documenting:
    1. Model architecture and base
    2. Training data and objective
    3. Evaluation results
    4. Intended use and limitations
    5. Reproducibility instructions

  For HuggingFace Hub publishing:
    from huggingface_hub import HfApi
    api = HfApi()
    api.upload_folder(folder_path=str(model_dir), repo_id="username/model-name")
  This requires a HuggingFace account and write token (HF_TOKEN env var).
  Omitted here to avoid authentication requirements in the teaching example.

Usage:
    # Save custom embedder with metadata
    uv run python scripts/publish_model.py --model custom_embedder

    # Save custom cross-encoder reranker
    uv run python scripts/publish_model.py --model cross_encoder

    # Save both
    uv run python scripts/publish_model.py --model all
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

MODELS_DIR = Path("models")
RESULTS_DIR = Path("results/data")


def _load_training_history(model_dir: Path) -> dict[str, object]:
    """Load training_history.json if it exists."""
    h = model_dir / "training_history.json"
    if h.exists():
        with open(h) as f:
            return json.load(f)
    return {}


def _load_benchmark_result(key: str) -> dict[str, object]:
    """Load benchmark results from results/data/ for the model card."""
    mapping = {
        "custom_embedder": RESULTS_DIR / "article_09_benchmarks.json",
        "cross_encoder": RESULTS_DIR / "custom_reranker_benchmark.json",
    }
    p = mapping.get(key)
    if p and p.exists():
        with open(p) as f:
            return json.load(f)
    return {}


def write_model_card(model_dir: Path, card_content: str) -> None:
    """Write README.md model card to the model directory."""
    readme = model_dir / "README.md"
    readme.write_text(card_content, encoding="utf-8")
    print(f"  Model card written: {readme}")


def publish_custom_embedder() -> None:
    """Document the fine-tuned BGE embedding model."""
    model_dir = MODELS_DIR / "bge_finetuned"
    if not model_dir.exists():
        print(f"  [skip] {model_dir} not found. Run train_custom_embedder.py first.")
        return

    history = _load_training_history(model_dir)
    benchmarks = _load_benchmark_result("custom_embedder")

    # Extract key metrics
    baseline_r5 = history.get("baseline_recall_at_5", "N/A")
    final_r5 = history.get("final_recall_at_5", "N/A")
    improvement = history.get("improvement", "N/A")
    train_pairs = history.get("train_pairs", "N/A")
    val_pairs = history.get("val_pairs", "N/A")
    device = history.get("device", "N/A")
    epochs = history.get("epochs", "N/A")
    training_secs = history.get("training_seconds", "N/A")

    # Full-corpus benchmark
    recall_at_5 = benchmarks.get("recall_at_5", {})
    stock_r5 = recall_at_5.get("stock", "N/A") if isinstance(recall_at_5, dict) else "N/A"
    ft_r5 = recall_at_5.get("finetuned", "N/A") if isinstance(recall_at_5, dict) else "N/A"
    teaching_note = benchmarks.get("teaching_note", "")

    card = f"""---
base_model: BAAI/bge-base-en-v1.5
tags:
  - sentence-transformers
  - feature-extraction
  - dense-retrieval
  - tech-docs
language:
  - en
datasets:
  - custom:tech_docs_triplets
metrics:
  - recall@5
---

# BGE-base-en-v1.5 Fine-tuned on Tech Docs Corpus

**Generated**: {datetime.now().strftime('%Y-%m-%d')}
**Project**: Agentic AI Stress Test Suite — Article 9 (Deep Learning)

## Model Description

Domain-adapted version of [BAAI/bge-base-en-v1.5](https://huggingface.co/BAAI/bge-base-en-v1.5)
fine-tuned on query-document triplets from a technical documentation corpus
(FastAPI, Pydantic, React, Spring Boot).

## Training Details

| Parameter | Value |
|-----------|-------|
| Base model | BAAI/bge-base-en-v1.5 |
| Loss | MultipleNegativesRankingLoss (InfoNCE variant) |
| Train pairs | {train_pairs} |
| Val pairs | {val_pairs} |
| Epochs | {epochs} |
| Device | {device} |
| Training time | {training_secs}s |

Hard negatives were mined via BM25 (6 negatives per query).

## Evaluation Results

### Val-set Recall@5 (query → expected_answer retrieval)

| Model | Recall@5 |
|-------|----------|
| Stock BGE-base-en-v1.5 | {baseline_r5} |
| Fine-tuned (this model) | {final_r5} |
| Improvement | {improvement:+.4f} |

### Full-corpus Recall@5 (207-doc corpus, 177 test queries)

| Model | Recall@5 |
|-------|----------|
| Stock | {stock_r5} |
| Fine-tuned | {ft_r5} |

## Teaching Note

{teaching_note}

## Usage

```python
from sentence_transformers import SentenceTransformer

model = SentenceTransformer("models/bge_finetuned")
embeddings = model.encode(["What is FastAPI dependency injection?"])
```

## Reproduce Training

```bash
uv run python scripts/prepare_dl_training_data.py
uv run python examples/article_09_dl/train_custom_embedder.py
uv run python benchmarks/benchmark_custom_embeddings.py
```

## Limitations

- Trained on small corpus (207 documents, ~{train_pairs} triplets)
- Optimised for query→document retrieval, not query→answer alignment
- May over-fit to FastAPI/Pydantic patterns (60% of corpus)
"""

    write_model_card(model_dir, card)

    # Save metadata JSON alongside the card
    metadata = {
        "model_type": "sentence_transformer_finetuned",
        "base_model": "BAAI/bge-base-en-v1.5",
        "task": "dense_retrieval",
        "domain": "tech_docs",
        "training_history": history,
        "benchmarks": {
            "val_recall_at_5": {
                "baseline": baseline_r5,
                "finetuned": final_r5,
                "improvement": improvement,
            },
            "full_corpus_recall_at_5": {
                "stock": stock_r5,
                "finetuned": ft_r5,
            },
        },
        "published_at": datetime.now().isoformat(),
    }
    meta_path = model_dir / "model_metadata.json"
    with open(meta_path, "w") as f:
        json.dump(metadata, f, indent=2)
    print(f"  Metadata written: {meta_path}")
    print(f"  Model directory: {model_dir}/")


def publish_cross_encoder() -> None:
    """Document the fine-tuned cross-encoder reranker."""
    model_dir = MODELS_DIR / "cross_encoder_finetuned"
    if not model_dir.exists():
        print(f"  [skip] {model_dir} not found. Run custom_reranker.py first.")
        return

    benchmarks = _load_benchmark_result("cross_encoder")
    ce_metrics = benchmarks.get("cross_encoder", {})
    fr_metrics = benchmarks.get("flashrank", {})

    ce_ndcg = ce_metrics.get("ndcg_at_5", "N/A") if isinstance(ce_metrics, dict) else "N/A"
    ce_lat = ce_metrics.get("latency_ms_median", "N/A") if isinstance(ce_metrics, dict) else "N/A"
    fr_ndcg = fr_metrics.get("ndcg_at_5", "N/A") if isinstance(fr_metrics, dict) else "N/A"
    fr_lat = fr_metrics.get("latency_ms_median", "N/A") if isinstance(fr_metrics, dict) else "N/A"

    card = f"""---
base_model: cross-encoder/ms-marco-MiniLM-L-6-v2
tags:
  - cross-encoder
  - reranking
  - tech-docs
language:
  - en
metrics:
  - ndcg@5
---

# MS-MARCO MiniLM-L-6-v2 Cross-Encoder Fine-tuned on Tech Docs

**Generated**: {datetime.now().strftime('%Y-%m-%d')}
**Project**: Agentic AI Stress Test Suite — Article 9 (Deep Learning)

## Model Description

Domain-adapted cross-encoder reranker based on
[cross-encoder/ms-marco-MiniLM-L-6-v2](https://huggingface.co/cross-encoder/ms-marco-MiniLM-L-6-v2),
fine-tuned on query-document relevance pairs from the tech docs corpus.

## Training Details

| Parameter | Value |
|-----------|-------|
| Base model | cross-encoder/ms-marco-MiniLM-L-6-v2 |
| Loss | BinaryCrossEntropyLoss |
| Architecture | 6-layer MiniLM (~22M params) |
| Training data | 765 pairs (153 positive, 612 negative) |
| Epochs | 1 |

## Evaluation (NDCG@5, 50 queries, top-20 shortlist)

| Reranker | NDCG@5 | Median latency |
|----------|--------|----------------|
| This model | {ce_ndcg} | {ce_lat}ms |
| FlashRank (baseline) | {fr_ndcg} | {fr_lat}ms |

## Interpretability

This model supports attention weight extraction via PyTorch forward hooks.
See `examples/article_09_dl/custom_reranker.py --inspect` for a demo.

## Usage

```python
from sentence_transformers import CrossEncoder

model = CrossEncoder("models/cross_encoder_finetuned", num_labels=1)
scores = model.predict([["What is FastAPI?", "FastAPI is a modern web framework..."]])
```

## Reproduce Training

```bash
uv run python examples/article_09_dl/custom_reranker.py --train --eval
```
"""

    write_model_card(model_dir, card)

    metadata = {
        "model_type": "cross_encoder_finetuned",
        "base_model": "cross-encoder/ms-marco-MiniLM-L-6-v2",
        "task": "reranking",
        "domain": "tech_docs",
        "benchmarks": {
            "ndcg_at_5": ce_ndcg,
            "latency_ms_median": ce_lat,
            "vs_flashrank_ndcg": fr_ndcg,
        },
        "published_at": datetime.now().isoformat(),
    }
    meta_path = model_dir / "model_metadata.json"
    with open(meta_path, "w") as f:
        json.dump(metadata, f, indent=2)
    print(f"  Metadata written: {meta_path}")
    print(f"  Model directory: {model_dir}/")


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish fine-tuned models with metadata cards")
    parser.add_argument(
        "--model",
        choices=["custom_embedder", "cross_encoder", "all"],
        default="all",
        help="Which model to publish (default: all)",
    )
    args = parser.parse_args()

    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    if args.model in ("custom_embedder", "all"):
        print("[Custom embedder (BGE fine-tuned)]")
        publish_custom_embedder()
        print()

    if args.model in ("cross_encoder", "all"):
        print("[Cross-encoder reranker]")
        publish_cross_encoder()
        print()

    print("Done. Model cards written to models/*/README.md")
    print("To upload to HuggingFace Hub:")
    print("  pip install huggingface_hub")
    print("  huggingface-cli login")
    print("  huggingface-cli upload <username>/<repo-name> models/bge_finetuned/")


if __name__ == "__main__":
    main()
