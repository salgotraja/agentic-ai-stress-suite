"""Benchmark stock vs fine-tuned BGE-base-en-v1.5 — task 5.4.

Teaching note: WHY compare stock vs fine-tuned on a full corpus?
  The val-set Recall@5 in training_history.json (task 5.3) only tests
  query→positive retrieval among 400 pairs — it never sees the 207-doc
  corpus. Full-corpus retrieval is harder: the model must distinguish the
  correct doc from 206 distractors, not just 399. This benchmark runs the
  real retrieval scenario to show the production-relevant improvement.

  Three dimensions compared:
  1. Recall@K (K=1,3,5): fraction of queries where correct doc in top-K
  2. Inference latency: encode-time per query (batch=1, repeated 100×)
  3. Embedding space: UMAP projection to visualise framework separation

Usage:
    # Full benchmark (loads real corpus, requires datasets/dl_training/)
    uv run python benchmarks/benchmark_custom_embeddings.py

    # Quick run (fewer queries, no UMAP)
    uv run python benchmarks/benchmark_custom_embeddings.py --quick

Output:
    results/data/article_09_benchmarks.json
    results/charts/article_09/01_recall_comparison.png
    results/charts/article_09/02_umap_embedding_space.png
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as functional
from sentence_transformers import SentenceTransformer

# ---------------------------------------------------------------------------
# Recall@K helpers
# ---------------------------------------------------------------------------


def build_corpus_index(
    model: SentenceTransformer,
    doc_texts: list[str],
    batch_size: int = 64,
) -> torch.Tensor:
    """Encode all corpus docs; return normalised embedding matrix."""
    embs = model.encode(
        doc_texts,
        batch_size=batch_size,
        show_progress_bar=False,
        convert_to_tensor=True,
    )
    return functional.normalize(embs, dim=-1)  # [N, D]


def recall_at_k_corpus(
    model: SentenceTransformer,
    queries: list[str],
    correct_indices: list[int],
    corpus_index: torch.Tensor,
    k: int = 5,
) -> float:
    """Recall@K against the full corpus.

    Teaching note: This is the production-relevant metric. Each query is
    encoded, compared against all corpus embeddings via cosine similarity,
    and Recall@K measures whether the correct doc appears in the top-K
    results. This simulates what the RAG retrieval pipeline does at inference.
    """
    q_embs = model.encode(
        queries,
        batch_size=64,
        show_progress_bar=False,
        convert_to_tensor=True,
    )
    q_norm = functional.normalize(q_embs, dim=-1)  # [Q, D]
    sim = torch.mm(q_norm, corpus_index.T)  # [Q, N]

    top_k = torch.topk(sim, k=k, dim=1).indices  # [Q, k]
    correct = torch.tensor(correct_indices, device=top_k.device).unsqueeze(1)  # [Q, 1]
    hits = (top_k == correct).any(dim=1)
    return float(hits.float().mean().item())


def measure_latency(
    model: SentenceTransformer,
    query: str,
    repeats: int = 100,
) -> float:
    """Median single-query encode latency in milliseconds."""
    # Warmup
    for _ in range(5):
        model.encode([query], show_progress_bar=False)

    times: list[float] = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        model.encode([query], show_progress_bar=False)
        times.append((time.perf_counter() - t0) * 1000)

    return float(np.median(times))


# ---------------------------------------------------------------------------
# UMAP visualisation
# ---------------------------------------------------------------------------


def plot_umap(
    stock_embs: np.ndarray,
    finetuned_embs: np.ndarray,
    labels: list[str],
    output_path: Path,
) -> None:
    """Project embeddings with UMAP and colour by framework.

    Teaching note: UMAP preserves local neighbourhood structure from the
    high-dimensional (768-D) embedding space. A well-trained embedding model
    should cluster documents by framework (FastAPI, Pydantic, React, Spring)
    and sub-topic. Comparing stock vs fine-tuned projections reveals whether
    fine-tuning increased within-framework cohesion or cross-framework
    separation — the key signal that domain adaptation is working.
    """
    try:
        import matplotlib
        import umap

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("  [skip] UMAP plot requires umap-learn and matplotlib")
        return

    reducer = umap.UMAP(n_components=2, random_state=42, n_neighbors=15, min_dist=0.1)

    # Fit on combined embeddings so both projections share the same axes
    combined = np.vstack([stock_embs, finetuned_embs])
    projected = reducer.fit_transform(combined)
    n = len(stock_embs)
    stock_2d = projected[:n]
    ft_2d = projected[n:]

    # Infer framework from label (doc path prefix)
    frameworks = ["fastapi", "pydantic", "react", "spring"]
    color_map = {
        "fastapi": "#e63946",
        "pydantic": "#2a9d8f",
        "react": "#457b9d",
        "spring": "#f4a261",
    }
    colors = []
    for lbl in labels:
        matched = next((fw for fw in frameworks if fw in lbl.lower()), "other")
        colors.append(color_map.get(matched, "#adb5bd"))

    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    fig.suptitle("Embedding Space: Stock vs Fine-tuned BGE-base-en-v1.5", fontsize=13)

    for ax, embs_2d, title in [(axes[0], stock_2d, "Stock"), (axes[1], ft_2d, "Fine-tuned")]:
        for fw in frameworks:
            idx = [i for i, lbl in enumerate(labels) if fw in lbl.lower()]
            if idx:
                ax.scatter(
                    embs_2d[idx, 0],
                    embs_2d[idx, 1],
                    c=color_map[fw],
                    label=fw,
                    s=15,
                    alpha=0.7,
                )
        ax.set_title(title)
        ax.legend(loc="upper right", fontsize=8)
        ax.set_xticks([])
        ax.set_yticks([])

    plt.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Saved: {output_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark stock vs fine-tuned embeddings")
    parser.add_argument(
        "--finetuned-dir",
        type=Path,
        default=Path("models/bge_finetuned"),
        help="Fine-tuned model directory",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("datasets/dl_training"),
        help="Training data directory (for val queries)",
    )
    parser.add_argument("--quick", action="store_true", help="Fewer queries, skip UMAP")
    args = parser.parse_args()

    if not args.finetuned_dir.exists():
        raise FileNotFoundError(
            f"{args.finetuned_dir} not found. Run train_custom_embedder.py first."
        )

    results_dir = Path("results/data")
    charts_dir = Path("results/charts/article_09")
    results_dir.mkdir(parents=True, exist_ok=True)
    charts_dir.mkdir(parents=True, exist_ok=True)

    # Load corpus docs
    print("Loading corpus...")
    docs_dir = Path("datasets/tech_docs")
    doc_paths: list[str] = []
    doc_texts: list[str] = []
    for md in sorted(docs_dir.rglob("*.md")):
        if md.name == "attribution.md":
            continue
        doc_paths.append(str(md.relative_to(docs_dir)))
        doc_texts.append(md.read_text(encoding="utf-8")[:2000])  # first 2000 chars
    print(f"  Corpus: {len(doc_texts)} documents")

    # Build path→corpus_index map for ground-truth matching
    path_to_idx: dict[str, int] = {p: i for i, p in enumerate(doc_paths)}

    # Load original queries with source_docs ground truth
    print("Loading queries with ground-truth source_docs...")
    with open("datasets/synthetic_queries/article_01.json") as f:
        article_01 = json.load(f)
    with open("datasets/golden_set/qa_pairs.json") as f:
        golden_data = json.load(f)

    # Build query → first source_doc mapping
    query_to_source: dict[str, str] = {}
    for item in article_01["queries"] + golden_data["qa_pairs"]:
        srcs = item.get("source_docs", [])
        if srcs:
            query_to_source[item["query"]] = srcs[0]

    # Build eval set: queries where source_doc is in corpus
    val_queries: list[str] = []
    correct_indices: list[int] = []
    skipped = 0
    seen: set[str] = set()
    for item in article_01["queries"] + golden_data["qa_pairs"]:
        q = item["query"]
        if q in seen:
            continue
        seen.add(q)
        srcs = item.get("source_docs", [])
        if not srcs:
            skipped += 1
            continue
        # Normalise path (remove leading framework dir if needed)
        src = srcs[0]
        if src in path_to_idx:
            val_queries.append(q)
            correct_indices.append(path_to_idx[src])
        else:
            skipped += 1

    if args.quick:
        n = min(50, len(val_queries))
        val_queries = val_queries[:n]
        correct_indices = correct_indices[:n]
        print(f"  Quick mode: using {n} queries")
    else:
        print(
            f"  Using {len(val_queries)} queries with ground-truth docs "
            f"({skipped} skipped: source_doc not in corpus)"
        )

    # Load models
    print("\nLoading stock model (BAAI/bge-base-en-v1.5)...")
    stock = SentenceTransformer("BAAI/bge-base-en-v1.5")
    print("Loading fine-tuned model...")
    finetuned = SentenceTransformer(str(args.finetuned_dir))

    # Build corpus indices (encode once each)
    print("\nBuilding corpus indices...")
    t0 = time.time()
    stock_corpus = build_corpus_index(stock, doc_texts)
    stock_index_ms = (time.time() - t0) * 1000
    print(f"  Stock index:     {stock_index_ms:.0f}ms")

    t0 = time.time()
    ft_corpus = build_corpus_index(finetuned, doc_texts)
    ft_index_ms = (time.time() - t0) * 1000
    print(f"  Fine-tuned index: {ft_index_ms:.0f}ms")

    # Recall@K
    print("\nRecall@K (full corpus)...")
    results: dict[str, object] = {}
    for k in [1, 3, 5]:
        r_stock = recall_at_k_corpus(stock, val_queries, correct_indices, stock_corpus, k=k)
        r_ft = recall_at_k_corpus(finetuned, val_queries, correct_indices, ft_corpus, k=k)
        delta = r_ft - r_stock
        print(f"  Recall@{k}: stock={r_stock:.4f}  fine-tuned={r_ft:.4f}  Δ={delta:+.4f}")
        results[f"recall_at_{k}"] = {
            "stock": round(r_stock, 4),
            "finetuned": round(r_ft, 4),
            "delta": round(delta, 4),
        }

    # Latency
    print("\nInference latency (single query, 100 repeats)...")
    probe_query = val_queries[0]
    stock_lat = measure_latency(stock, probe_query)
    ft_lat = measure_latency(finetuned, probe_query)
    print(f"  Stock:      {stock_lat:.2f}ms median")
    print(f"  Fine-tuned: {ft_lat:.2f}ms median")
    results["latency_ms"] = {
        "stock_median": round(stock_lat, 2),
        "finetuned_median": round(ft_lat, 2),
    }

    # Recall comparison chart
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        ks = [1, 3, 5]
        stock_vals = [results[f"recall_at_{k}"]["stock"] for k in ks]  # type: ignore[index]
        ft_vals = [results[f"recall_at_{k}"]["finetuned"] for k in ks]  # type: ignore[index]

        x = np.arange(len(ks))
        width = 0.35
        fig, ax = plt.subplots(figsize=(7, 5))
        ax.bar(x - width / 2, stock_vals, width, label="Stock BGE-base-en-v1.5", color="#457b9d")
        ax.bar(x + width / 2, ft_vals, width, label="Fine-tuned (domain)", color="#e63946")
        ax.set_xlabel("K")
        ax.set_ylabel("Recall@K")
        ax.set_title("Stock vs Fine-tuned: Recall@K on Full Corpus")
        ax.set_xticks(x)
        ax.set_xticklabels([f"K={k}" for k in ks])
        ax.set_ylim(0, 1)
        ax.legend()
        ax.grid(axis="y", alpha=0.4)
        out = charts_dir / "01_recall_comparison.png"
        plt.tight_layout()
        plt.savefig(out, dpi=150)
        plt.close()
        print(f"\n  Saved chart: {out}")
    except ImportError:
        print("  [skip] matplotlib not available for chart")

    # UMAP
    if not args.quick:
        print("\nGenerating UMAP embedding space visualisation...")
        stock_np = stock_corpus.cpu().numpy()
        ft_np = ft_corpus.cpu().numpy()
        plot_umap(
            stock_np,
            ft_np,
            doc_paths,
            charts_dir / "02_umap_embedding_space.png",
        )

    # Save JSON results
    out_json = results_dir / "article_09_benchmarks.json"
    with open(out_json, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved: {out_json}")


if __name__ == "__main__":
    main()
