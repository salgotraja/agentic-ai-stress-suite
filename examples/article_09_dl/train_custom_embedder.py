"""Fine-tune BGE-base-en-v1.5 on tech docs corpus — task 5.3.

Teaching note: WHY fine-tune a pre-trained embedding model?
  BGE-base-en-v1.5 is trained on general web text and NLI-style pairs.
  It scores ~63 on MTEB, but "What is FastAPI's BackgroundTasks?" is not
  web text — the vocabulary, phrasing, and concept relationships are
  domain-specific. Fine-tuning bridges the gap:
  - Aligns query phrasing with doc phrasing in the embedding space
  - Groups related framework concepts (DI, DI testing, FastAPI testing)
  - Target: 5-15% Recall@5 improvement over the base model

  Expected improvement is modest (not 50%+) because BGE-base-en-v1.5 is
  already a strong general-purpose model and our corpus is small (200 docs).
  Fine-tuning shows the largest gains when:
  1. Domain vocabulary diverges strongly from pre-training data
  2. Training data is large (10k+ pairs)
  For teaching purposes, the key lesson is the code path and evaluation
  methodology — the numbers are secondary.

Loss: MultipleNegativesRankingLoss (InfoNCE variant)
  Given a batch of (anchor, positive, negative) triplets, the loss maximises:
    log softmax(sim(anchor_i, positive_i) / temperature) against all
    {positive_j, negative_j} in the batch as negatives for anchor_i.
  With batch_size=16 and 1 explicit negative per row, each anchor sees
  31 negatives (15 in-batch positives + 16 in-batch negatives) — efficient.

  sentence-transformers v3+ uses SentenceTransformerTrainer (HuggingFace Trainer
  under the hood). Dataset columns must match loss requirements:
  {"anchor": str, "positive": str, "negative": str}

Validation metric: Recall@5
  For each val query, retrieve top-5 from val positives by cosine similarity.
  Recall@5 = fraction of queries whose correct positive is in top-5.

Usage:
    # Full training on MPS (M4, ~5-10 min for 2 epochs)
    uv run python examples/article_09_dl/train_custom_embedder.py

    # Fast smoke-test (CPU, 1 epoch, small subset)
    uv run python examples/article_09_dl/train_custom_embedder.py \\
        --device cpu --epochs 1 --max-steps 20

    # Check results
    cat models/bge_finetuned/training_history.json
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import torch
import torch.nn.functional as functional
from sentence_transformers import SentenceTransformer, losses
from sentence_transformers.trainer import SentenceTransformerTrainer
from sentence_transformers.training_args import SentenceTransformerTrainingArguments

from datasets import Dataset

# ---------------------------------------------------------------------------
# Recall@K evaluation
# ---------------------------------------------------------------------------


def recall_at_k(model: SentenceTransformer, val_pairs: list[dict[str, str]], k: int = 5) -> float:
    """Compute Recall@K on val set using anchor→positive retrieval.

    Teaching note: We embed all val positives as the "corpus" and each val
    anchor as the "query". Recall@K = fraction of queries whose correct positive
    is in the top-K by cosine similarity. This is fast (400 pairs ≈ 800
    embeddings) and correlates well with full-corpus Recall@K (task 5.4).
    """
    anchors = [p["anchor"] for p in val_pairs]
    positives = [p["positive"] for p in val_pairs]

    a_emb = model.encode(anchors, batch_size=64, show_progress_bar=False, convert_to_tensor=True)
    p_emb = model.encode(positives, batch_size=64, show_progress_bar=False, convert_to_tensor=True)

    a_norm = functional.normalize(a_emb, dim=-1)
    p_norm = functional.normalize(p_emb, dim=-1)
    sim = torch.mm(a_norm, p_norm.T)  # [Q, P]

    top_k = torch.topk(sim, k=k, dim=1).indices  # [Q, k]
    correct = torch.arange(len(anchors), device=top_k.device).unsqueeze(1)  # [Q, 1]
    hits = (top_k == correct).any(dim=1)
    return float(hits.float().mean().item())


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Fine-tune BGE-base-en-v1.5 embedder")
    parser.add_argument(
        "--device",
        default="auto",
        choices=["auto", "mps", "cpu", "cuda"],
        help="Device: auto selects MPS > CUDA > CPU (default: auto)",
    )
    parser.add_argument("--epochs", type=int, default=2, help="Training epochs (default: 2)")
    parser.add_argument(
        "--batch-size", type=int, default=16, help="Training batch size (default: 16)"
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=-1,
        help="Max total training steps (-1 = no limit, default: -1)",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("datasets/dl_training"),
        help="Training data directory",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("models/bge_finetuned"),
        help="Model output directory",
    )
    args = parser.parse_args()

    # Device selection: MPS (Apple Silicon) > CUDA > CPU
    if args.device == "auto":
        if torch.backends.mps.is_available():
            device = "mps"
        elif torch.cuda.is_available():
            device = "cuda"
        else:
            device = "cpu"
    else:
        device = args.device
    print(f"Device: {device}")

    # Load data
    train_path = args.data_dir / "train.json"
    val_path = args.data_dir / "val.json"
    if not train_path.exists():
        raise FileNotFoundError(
            f"{train_path} not found. Run: uv run python scripts/prepare_dl_training_data.py"
        )

    with open(train_path) as f:
        raw_train = json.load(f)
    with open(val_path) as f:
        raw_val = json.load(f)
    print(f"Train: {len(raw_train)} pairs  Val: {len(raw_val)} pairs")

    # Convert to sentence-transformers v3 column format:
    # {anchor, positive, negative} — column names must match the loss expectation
    def remap(pairs: list[dict[str, str]]) -> list[dict[str, str]]:
        return [
            {"anchor": p["query"], "positive": p["positive"], "negative": p["negative"]}
            for p in pairs
        ]

    train_dataset = Dataset.from_list(remap(raw_train))
    val_pairs_remapped = remap(raw_val)

    # Load model
    model_name = "BAAI/bge-base-en-v1.5"
    print(f"Loading {model_name}...")
    model = SentenceTransformer(model_name, device=device)

    # Baseline Recall@5 before fine-tuning
    print("Computing baseline Recall@5...")
    baseline_r5 = recall_at_k(model, val_pairs_remapped, k=5)
    print(f"  Baseline Recall@5: {baseline_r5:.4f}")

    # Loss: MultipleNegativesRankingLoss
    # Teaching note: expects columns (anchor, positive, negative) in that order.
    # With explicit negatives, each row contributes 1 hard negative + (B-1)
    # in-batch positives as additional negatives for free.
    loss_fn = losses.MultipleNegativesRankingLoss(model)

    # Training arguments — use HuggingFace Trainer conventions
    args.output_dir.mkdir(parents=True, exist_ok=True)
    training_args = SentenceTransformerTrainingArguments(
        output_dir=str(args.output_dir),
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        max_steps=args.max_steps,
        save_strategy="no",  # We save manually after training
        logging_steps=10,
        report_to="none",  # Disable wandb/mlflow
    )

    # Trainer
    trainer = SentenceTransformerTrainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        loss=loss_fn,
    )

    print(f"\nTraining {args.epochs} epoch(s) with batch_size={args.batch_size}...")
    t0 = time.time()
    trainer.train()
    elapsed = time.time() - t0
    print(f"Training took {elapsed:.1f}s")

    # Post-training Recall@5
    model.eval()
    final_r5 = recall_at_k(model, val_pairs_remapped, k=5)
    improvement = final_r5 - baseline_r5
    print(f"\nBaseline Recall@5: {baseline_r5:.4f}")
    print(f"Final Recall@5:    {final_r5:.4f}  (Δ={improvement:+.4f})")

    # Save model and training history
    model.save(str(args.output_dir))
    history = {
        "model": model_name,
        "device": device,
        "epochs": args.epochs,
        "batch_size": args.batch_size,
        "train_pairs": len(raw_train),
        "val_pairs": len(raw_val),
        "training_seconds": round(elapsed, 1),
        "baseline_recall_at_5": round(baseline_r5, 4),
        "final_recall_at_5": round(final_r5, 4),
        "improvement": round(improvement, 4),
    }
    history_path = args.output_dir / "training_history.json"
    with open(history_path, "w") as f:
        json.dump(history, f, indent=2)

    print(f"\nModel saved to:   {args.output_dir}")
    print(f"Training history: {history_path}")


if __name__ == "__main__":
    main()
