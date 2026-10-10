"""Fine-tune BGE-base-en-v1.5 on tech docs corpus - task 5.3.

Teaching note: WHY fine-tune a pre-trained embedding model?
  BGE-base-en-v1.5 is trained on general web text and NLI-style pairs.
  It scores ~63 on MTEB, but "What is FastAPI's BackgroundTasks?" is not
  web text - the vocabulary, phrasing, and concept relationships are
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
  methodology - the numbers are secondary.

Loss: MultipleNegativesRankingLoss (InfoNCE variant)
  Given a batch of (anchor, positive, negative) triplets, the loss maximises:
    log softmax(sim(anchor_i, positive_i) / temperature) against all
    {positive_j, negative_j} in the batch as negatives for anchor_i.
  With batch_size=16 and 1 explicit negative per row, each anchor sees
  31 negatives (15 in-batch positives + 16 in-batch negatives) - efficient.

  sentence-transformers v3+ uses SentenceTransformerTrainer (HuggingFace Trainer
  under the hood). Dataset columns must match loss requirements:
  {"anchor": str, "positive": str, "negative": str}

Validation metric: Recall@5
  For each val query, retrieve top-5 from val positives by cosine similarity.
  Recall@5 = fraction of queries whose correct positive is in top-5.

Usage:
    # Full training on MPS (M4, ~5-10 min for 2 epochs)
    uv run python examples/article_09_dl/train_custom_embedder.py

    # Chunk-shaped pairs, one seed
    uv run python examples/article_09_dl/train_custom_embedder.py \\
        --train-file train_chunk.json --seed 13 --output-dir models/bge_chunk_seed13

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
from sentence_transformers import SentenceTransformer, losses
from sentence_transformers.trainer import SentenceTransformerTrainer
from sentence_transformers.training_args import SentenceTransformerTrainingArguments

from datasets import Dataset

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
    parser.add_argument("--train-file", default="train.json", help="File in --data-dir")
    parser.add_argument("--seed", type=int, default=42, help="Training seed")
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
    train_path = args.data_dir / args.train_file
    if not train_path.exists():
        raise FileNotFoundError(
            f"{train_path} not found. Run: uv run python scripts/prepare_dl_training_data.py"
        )
    with open(train_path) as f:
        raw_train = json.load(f)
    print(f"Train: {len(raw_train)} triples from {train_path}")
    train_dataset = Dataset.from_list(
        [
            {"anchor": p["query"], "positive": p["positive"], "negative": p["negative"]}
            for p in raw_train
        ]
    )
    torch.manual_seed(args.seed)

    # Load model
    model_name = "BAAI/bge-base-en-v1.5"
    print(f"Loading {model_name}...")
    model = SentenceTransformer(model_name, device=device)

    # Loss: MultipleNegativesRankingLoss
    # Teaching note: expects columns (anchor, positive, negative) in that order.
    # With explicit negatives, each row contributes 1 hard negative + (B-1)
    # in-batch positives as additional negatives for free.
    loss_fn = losses.MultipleNegativesRankingLoss(model)

    # Training arguments - use HuggingFace Trainer conventions
    args.output_dir.mkdir(parents=True, exist_ok=True)
    training_args = SentenceTransformerTrainingArguments(
        output_dir=str(args.output_dir),
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        max_steps=args.max_steps,
        save_strategy="no",  # We save manually after training
        logging_steps=10,
        report_to="none",  # Disable wandb/mlflow
        seed=args.seed,
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

    model.save(str(args.output_dir))
    history = {
        "model": model_name,
        "device": device,
        "seed": args.seed,
        "epochs": args.epochs,
        "batch_size": args.batch_size,
        "learning_rate": training_args.learning_rate,
        "train_file": args.train_file,
        "train_triples": len(raw_train),
        "training_seconds": round(elapsed, 1),
        "torch": torch.__version__,
    }
    history_path = args.output_dir / "training_history.json"
    with open(history_path, "w") as f:
        json.dump(history, f, indent=2)

    print(f"\nModel saved to:   {args.output_dir}")
    print(f"Training history: {history_path}")


if __name__ == "__main__":
    main()
