"""PyTorch inference optimizations for embedding models - tasks 5.5, 5.6, 5.7.

Teaching note: WHY optimise the embedding model?
  In a high-traffic RAG pipeline, the embedding step runs on every query:
    - Semantic cache lookup (Article 6): query must be embedded to find similar cache entries
    - Retrieval: query embedded to search vector DB
  At 100 req/sec (Article 8 target), embedding latency directly caps throughput.
  Three standard optimisation techniques are benchmarked:

  1. torch.compile() - graph compilation
     PyTorch's JIT compiler fuses ops into optimised kernels. First call
     is slow (trace overhead ~1-3s), but subsequent calls are 20-50% faster.
     Best for models with stable input shapes (fixed sequence length).
     Caveat on MPS: torch.compile has partial MPS support; CPU backend is used
     for reliable benchmarking.

  2. Dynamic INT8 quantization
     Replaces 32-bit float weights with 8-bit integers in Linear layers.
     Cuts model size by ~4x and speeds up CPU inference by 30-70%.
     Quality impact: embeddings stay accurate (cosine similarity within 1%)
     because INT8 quantization error is below the noise floor for most tasks.
     Note: INT8 quantization is CPU-only in PyTorch (no GPU/MPS support yet).

  3. torch.profiler - bottleneck identification
     Records operator-level execution times. The profile reveals which ops
     dominate inference time (usually attention and layer norm), guiding
     targeted optimisation effort.
     Output: trace.json for chrome://tracing visualisation.

Usage:
    uv run python examples/article_09_dl/pytorch_optimizations.py
    # Outputs: results/data/pytorch_optimizations.json
    #          results/charts/article_09/03_speedup_comparison.png
    #          results/data/trace.json  (open in chrome://tracing)
"""

from __future__ import annotations

import json
import time
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import torch
from transformers import AutoModel, AutoTokenizer

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MODEL_NAME = "BAAI/bge-base-en-v1.5"
SAMPLE_QUERY = "What is FastAPI dependency injection?"
WARMUP_RUNS = 5
BENCH_RUNS = 50


def _load_model_and_tokenizer() -> tuple[torch.nn.Module, Any]:
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)  # type: ignore[no-untyped-call]
    model: torch.nn.Module = AutoModel.from_pretrained(MODEL_NAME)
    model.eval()
    return model, tokenizer


def _tokenize(query: str, tokenizer: Any) -> dict[str, torch.Tensor]:
    return tokenizer(
        query,
        return_tensors="pt",
        padding="max_length",
        truncation=True,
        max_length=128,
    )


def _mean_pool(token_embeddings: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
    """Mean pooling over non-padding tokens - standard for BGE models."""
    mask_expanded = attention_mask.unsqueeze(-1).float()
    return (token_embeddings * mask_expanded).sum(1) / mask_expanded.sum(1).clamp(min=1e-9)


def _encode(
    model: torch.nn.Module,
    inputs: dict[str, torch.Tensor],
) -> torch.Tensor:
    with torch.no_grad():
        out = model(**inputs)
    return _mean_pool(out.last_hidden_state, inputs["attention_mask"])


def measure_latency_ms(
    model: torch.nn.Module,
    inputs: dict[str, torch.Tensor],
    runs: int = BENCH_RUNS,
) -> float:
    """Median inference latency in milliseconds (CPU, no grad)."""
    for _ in range(WARMUP_RUNS):
        _encode(model, inputs)

    times: list[float] = []
    for _ in range(runs):
        t0 = time.perf_counter()
        _encode(model, inputs)
        times.append((time.perf_counter() - t0) * 1000)
    return float(np.median(times))


# ---------------------------------------------------------------------------
# Benchmark: eager vs torch.compile
# ---------------------------------------------------------------------------


def benchmark_compile(
    model: torch.nn.Module,
    inputs: dict[str, torch.Tensor],
) -> dict[str, float]:
    """Compare eager mode vs torch.compile on CPU.

    Teaching note: torch.compile is most effective on hardware with
    dedicated CUDA tensor cores. On CPU (and MPS which has partial support),
    gains are more modest - typically 10-25% for transformer inference.
    The lesson is the code path, not the exact speedup number.
    """
    print("  [eager] measuring...")
    eager_ms = measure_latency_ms(model, inputs)
    print(f"    Eager: {eager_ms:.2f}ms")

    print("  [compile] compiling (first call slow, subsequent fast)...")
    # aot_eager is a CPU-compatible backend that works without CUDA.
    # The full inductor backend (default) requires triton which is CUDA-only.
    compiled: torch.nn.Module = torch.compile(model, backend="aot_eager")  # type: ignore[assignment]
    # First call triggers compilation - not included in benchmark
    _encode(compiled, inputs)

    print("  [compile] measuring compiled model...")
    compiled_ms = measure_latency_ms(compiled, inputs)
    speedup = eager_ms / compiled_ms
    print(f"    Compiled: {compiled_ms:.2f}ms  speedup: {speedup:.2f}x")

    return {
        "eager_ms": round(eager_ms, 2),
        "compiled_ms": round(compiled_ms, 2),
        "speedup": round(speedup, 2),
    }


# ---------------------------------------------------------------------------
# Benchmark: float32 vs INT8 quantization
# ---------------------------------------------------------------------------


def benchmark_quantization(
    model: torch.nn.Module,
    inputs: dict[str, torch.Tensor],
) -> dict[str, float]:
    """Dynamic INT8 quantization of Linear layers.

    Teaching note: torch.quantization.quantize_dynamic replaces specified
    layer types (here: nn.Linear) with INT8 equivalents at runtime. No
    calibration dataset required - hence 'dynamic' (vs static quantization).
    The tradeoff:
      - Pro: 4x smaller weights (float32 → int8), faster GEMM on CPU
      - Con: slight accuracy loss (< 1% cosine similarity drift for BGE)
      - Limitation: CPU-only; GPU and MPS don't benefit from INT8 in PyTorch yet

    Engine note: PyTorch requires an explicit quantization backend on ARM
    (Apple Silicon, Raspberry Pi). QNNPACK targets ARM NEON intrinsics and
    is the correct choice here. FBGEMM targets x86 AVX2 and won't load on M4.
    Note: torch.ao.quantization is deprecated as of PyTorch 2.9 in favour of
    torchao, but the legacy API remains functional for teaching purposes.

    QNNPACK vs FBGEMM result: on Apple Silicon, QNNPACK INT8 is actually
    SLOWER than FP32 because Apple's CPU doesn't have x86-style VNNI
    instructions - size reduction is real (4x) but latency benefit requires x86.
    """
    fp32_ms = measure_latency_ms(model, inputs)
    fp32_size_mb = sum(p.numel() * 4 for p in model.parameters()) / 1e6

    # QNNPACK is the ARM-native quantization engine (vs FBGEMM for x86 AVX2).
    # Must be set before quantize_dynamic; the default is 'none' on non-x86.
    torch.backends.quantized.engine = "qnnpack"

    # Dynamic quantization of all Linear layers.
    # Suppress DeprecationWarning: torch.ao.quantization deprecated in PyTorch 2.9.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        quantized: torch.nn.Module = torch.quantization.quantize_dynamic(  # type: ignore[attr-defined]
            model,
            {torch.nn.Linear},
            dtype=torch.qint8,
        )

    # Quantized Linear layers store weights as packed INT8 tensors that don't
    # show up as standard parameters - approximate size as fp32_size / 4.
    int8_size_mb = fp32_size_mb / 4.0

    int8_ms = measure_latency_ms(quantized, inputs)
    speedup = fp32_ms / int8_ms

    # Cosine similarity between FP32 and INT8 embeddings (quality check)
    fp32_emb = _encode(model, inputs)
    int8_emb = _encode(quantized, inputs)
    cos_sim = float(torch.nn.functional.cosine_similarity(fp32_emb, int8_emb, dim=-1).mean().item())

    print(f"    FP32: {fp32_ms:.2f}ms  {fp32_size_mb:.0f}MB")
    print(f"    INT8: {int8_ms:.2f}ms  {int8_size_mb:.0f}MB  speedup: {speedup:.2f}x")
    print(f"    Cosine similarity (FP32 vs INT8): {cos_sim:.6f}")

    return {
        "fp32_ms": round(fp32_ms, 2),
        "int8_ms": round(int8_ms, 2),
        "speedup": round(speedup, 2),
        "fp32_size_mb": round(fp32_size_mb, 1),
        "int8_size_mb": round(int8_size_mb, 1),
        "size_reduction": round(fp32_size_mb / max(int8_size_mb, 1), 2),
        "cosine_similarity": round(cos_sim, 6),
    }


# ---------------------------------------------------------------------------
# Profiling
# ---------------------------------------------------------------------------


def profile_inference(
    model: torch.nn.Module,
    inputs: dict[str, torch.Tensor],
    output_path: Path,
    n_steps: int = 10,
) -> None:
    """Record operator-level profile; export Chrome trace for visualisation.

    Teaching note: The Chrome trace format (chrome://tracing) shows a
    timeline of every PyTorch operator. For transformer inference the typical
    hotspot is the attention SDPA (scaled dot-product attention) and the
    two Linear projections in each FFN block. Identifying these guides whether
    to pursue:
      - Fused kernels (torch.compile / FlashAttention)
      - Operator pruning (reducing layers)
      - Quantization (replacing GEMM precision)
    """
    with torch.profiler.profile(
        activities=[torch.profiler.ProfilerActivity.CPU],
        record_shapes=True,
        with_flops=True,
    ) as prof:
        for _ in range(n_steps):
            with torch.profiler.record_function("encode"):
                _encode(model, inputs)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    prof.export_chrome_trace(str(output_path))

    # Print top-10 ops by CPU time
    print("  Top operators by CPU time:")
    top_ops = prof.key_averages().table(sort_by="cpu_time_total", row_limit=10)
    for line in top_ops.split("\n")[:14]:
        if line.strip():
            print(f"    {line}")
    print(f"  Chrome trace saved: {output_path}")
    print("  View at: chrome://tracing → Load → select trace.json")


# ---------------------------------------------------------------------------
# Chart
# ---------------------------------------------------------------------------


def plot_speedup(
    compile_results: dict[str, float],
    quant_results: dict[str, float],
    output_path: Path,
) -> None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        labels = ["Eager\n(baseline)", "torch.compile", "INT8\nquantized"]
        eager_ms = compile_results["eager_ms"]
        values: list[float] = [
            eager_ms,
            compile_results["compiled_ms"],
            quant_results["int8_ms"],
        ]
        colors = ["#adb5bd", "#457b9d", "#e63946"]

        fig, ax = plt.subplots(figsize=(7, 5))
        bars = ax.bar(labels, values, color=colors, width=0.5)
        ax.set_ylabel("Median latency (ms) - lower is better")
        ax.set_title("PyTorch Inference Optimizations\n(BGE-base-en-v1.5, CPU, 128-token input)")
        ax.set_ylim(0, max(values) * 1.3)

        for bar, val in zip(bars, values):
            speedup = eager_ms / val
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + max(values) * 0.02,
                f"{val:.1f}ms\n({speedup:.2f}x)",
                ha="center",
                va="bottom",
                fontsize=9,
            )

        ax.grid(axis="y", alpha=0.4)
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
    print(f"Model: {MODEL_NAME}")
    print("Device: CPU (torch.compile and INT8 quant are CPU-only)\n")

    model, tokenizer = _load_model_and_tokenizer()
    inputs = _tokenize(SAMPLE_QUERY, tokenizer)

    results: dict[str, dict[str, float]] = {}

    print("[torch.compile]")
    results["compile"] = benchmark_compile(model, inputs)

    # Reload fresh model for quantization (compiled model can't be re-quantized)
    model2, _ = _load_model_and_tokenizer()
    inputs2 = _tokenize(SAMPLE_QUERY, tokenizer)

    print("\n[INT8 quantization]")
    results["quantization"] = benchmark_quantization(model2, inputs2)

    print("\n[torch.profiler]")
    model3, _ = _load_model_and_tokenizer()
    inputs3 = _tokenize(SAMPLE_QUERY, tokenizer)
    trace_path = Path("results/data/trace.json")
    profile_inference(model3, inputs3, trace_path)

    # Chart
    plot_speedup(
        results["compile"],
        results["quantization"],
        Path("results/charts/article_09/03_speedup_comparison.png"),
    )

    # Save results
    out = Path("results/data/pytorch_optimizations.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved: {out}")


if __name__ == "__main__":
    main()
