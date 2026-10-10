"""Custom cross-encoder reranker with attention hooks - task 5.8.

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
    Cross-encoders can't pre-compute doc representations - every (query, doc)
    pair must be processed fresh. At 10K docs × 100 req/sec = 1M forward passes
    per second. Only feasible for small candidate sets (top 20-100 from Stage 1).

Attention hooks - interpretability:
  BERT's attention mechanism computes a weight matrix A ∈ [heads, seq, seq].
  A[h, 0, j] = how much [CLS] attends to token j in head h.
  Averaging across heads gives token-level attribution - which query/doc tokens
  drove the relevance score. This is approximate (attention ≠ importance),
  but gives useful debugging signals for training data curation.

Model: cross-encoder/ms-marco-MiniLM-L-6-v2
  - 6-layer MiniLM, 22.7M params
  - Pre-trained on MS MARCO passage ranking

Training data (repaired):
  Only questions assigned to "train" in datasets/dl_training_split.json are
  used. Each contributes up to 2 positives (retrieved chunks from any listed
  source document) and 4 negatives (the highest-ranked retrieved chunks whose
  document is not a listed source), taken from the frozen hybrid-retriever
  candidates. The first version used only source_docs[0] as the positive and
  sampled random whole-document negatives, so a second listed source could be
  trained as a negative, and its evaluation reused training questions.
  Evaluation lives in benchmarks/benchmark_article_09_rerankers.py.

Usage:
    uv run python examples/article_09_dl/custom_reranker.py --train --seeds 13 21 42
    uv run python examples/article_09_dl/custom_reranker.py --inspect
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import torch
from sentence_transformers import CrossEncoder
from sentence_transformers.cross_encoder import CrossEncoderTrainer, CrossEncoderTrainingArguments
from sentence_transformers.cross_encoder.losses import BinaryCrossEntropyLoss

from datasets import Dataset  # type: ignore[attr-defined]

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

MODEL_DIR = Path("models/cross_encoder_finetuned")
BASE_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
SPLIT_MANIFEST = Path("datasets/dl_training_split.json")
CANDIDATES = Path("results/data/article_09/candidates_2026-10-10.json")

TRAIN_EPOCHS = 1
BATCH_SIZE = 16
MAX_POSITIVES = 2
NEGATIVES_PER_QUERY = 4


# ---------------------------------------------------------------------------
# Data preparation
# ---------------------------------------------------------------------------


def build_training_pairs(
    manifest_path: Path = SPLIT_MANIFEST, candidates_path: Path = CANDIDATES
) -> list[dict[str, Any]]:
    """(query, chunk, label) pairs for train-split questions only."""
    from benchmarks.article_09_eval import build_reranker_pairs
    from benchmarks.build_article_09_candidates import load_candidates
    from scripts.prepare_dl_training_data import load_questions

    split_of = {q["id"]: q["split"] for q in json.loads(manifest_path.read_text())["questions"]}
    candidates = load_candidates(candidates_path)
    pairs: list[dict[str, Any]] = []
    for item in load_questions():
        if split_of[item["id"]] != "train":
            continue
        pairs += build_reranker_pairs(
            item["query"],
            item["source_docs"],
            candidates[item["id"]],
            MAX_POSITIVES,
            NEGATIVES_PER_QUERY,
        )
    return pairs


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------


def train_reranker(pairs: list[dict[str, Any]], seed: int, device: str) -> dict[str, Any]:
    """Fine-tune the cross-encoder on train-split pairs; save under MODEL_DIR/seed<N>.

    BinaryCrossEntropyLoss applies a sigmoid to the single logit and scores it
    against {0, 1} labels. No pairs are held back here: held-out questions
    are a separate split, not a slice of these rows.
    """
    out_dir = MODEL_DIR / f"seed{seed}"
    out_dir.mkdir(parents=True, exist_ok=True)
    torch.manual_seed(seed)
    random.seed(seed)
    np.random.seed(seed)

    model: Any = CrossEncoder(BASE_MODEL, num_labels=1, device=device)
    training_args = CrossEncoderTrainingArguments(
        output_dir=str(out_dir),
        num_train_epochs=TRAIN_EPOCHS,
        per_device_train_batch_size=BATCH_SIZE,
        save_strategy="no",
        logging_steps=20,
        report_to="none",
        seed=seed,
    )
    trainer = CrossEncoderTrainer(
        model=model,
        args=training_args,
        train_dataset=Dataset.from_list(pairs),
        loss=BinaryCrossEntropyLoss(model),
    )
    t0 = time.time()
    trainer.train()
    elapsed = time.time() - t0
    model.save(str(out_dir))
    history = {
        "base_model": BASE_MODEL,
        "seed": seed,
        "device": device,
        "epochs": TRAIN_EPOCHS,
        "batch_size": BATCH_SIZE,
        "pairs": len(pairs),
        "positives": sum(1 for p in pairs if p["label"] == 1.0),
        "negatives": sum(1 for p in pairs if p["label"] == 0.0),
        "training_seconds": round(elapsed, 1),
        "torch": torch.__version__,
    }
    (out_dir / "training_history.json").write_text(json.dumps(history, indent=2))
    print(f"  seed {seed}: {elapsed:.1f}s on {device}, saved to {out_dir}")
    return history


# ---------------------------------------------------------------------------
# Attention hooks - interpretability
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
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Custom cross-encoder reranker (task 5.8)")
    parser.add_argument("--train", action="store_true", help="Fine-tune on train-split pairs")
    parser.add_argument("--seeds", type=int, nargs="+", default=[13, 21, 42])
    parser.add_argument("--device", default="mps" if torch.backends.mps.is_available() else "cpu")
    parser.add_argument("--inspect", action="store_true", help="Show attention attributions")
    args = parser.parse_args()

    if args.train:
        pairs = build_training_pairs()
        print(
            f"Training pairs: {len(pairs)} "
            f"({sum(1 for p in pairs if p['label'] == 1.0)} positive, "
            f"{sum(1 for p in pairs if p['label'] == 0.0)} negative)"
        )
        for seed in args.seeds:
            train_reranker(pairs, seed, args.device)

    if args.inspect:
        seed_dir = MODEL_DIR / f"seed{args.seeds[0]}"
        model: Any = CrossEncoder(str(seed_dir) if seed_dir.exists() else BASE_MODEL, num_labels=1)
        test_query = "What is FastAPI dependency injection?"
        doc = Path("datasets/tech_docs/fastapi/05_dependencies__dependency_injection.md")
        attribution = extract_attention_attributions(model, test_query, doc.read_text()[:1500])
        print(f"  Query: '{test_query}'  Relevance score: {attribution.get('score', 'n/a')}")
        for token, weight in attribution.get("top_attributed_tokens", []):
            print(f"    {token:<20} {weight:.4f}")


if __name__ == "__main__":
    main()
