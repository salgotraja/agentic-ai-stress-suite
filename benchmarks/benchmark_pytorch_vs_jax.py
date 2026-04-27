"""PyTorch vs JAX head-to-head benchmark - task 5.10.

Teaching note: When to choose PyTorch vs JAX
  Both compile to XLA/hardware kernels and achieve near-identical throughput
  on the same hardware. The choice is about the programming model:

  Choose PyTorch when:
    - Rapid prototyping with mutable debugging (print inside forward)
    - Existing ecosystem (HuggingFace, torchvision, torchaudio)
    - Dynamic control flow in forward pass (variable-length inputs)
    - Team is familiar with OOP / nn.Module pattern

  Choose JAX when:
    - Composing transforms: jit(vmap(grad(f))) for meta-learning, RL
    - Large-scale distributed training on TPU pods (XLA native)
    - Functional programming style (Flax, Equinox ecosystems)
    - Research needing per-sample gradients (differentiable algorithms)
    - Reproducibility: explicit PRNG keys, no global state

  Performance on CPU:
    Both call into the same underlying BLAS/LAPACK libraries for matmul.
    Differences come from:
      1. Dispatch overhead (Python → C++)
      2. Memory allocation patterns
      3. JIT warmup cost (first call is slow for both torch.compile and jax.jit)
    On GPU/TPU, JAX's XLA ahead-of-time compilation often wins because
    it fuses more ops across the whole computation graph.

Benchmarks:
  1. Matrix multiplication (N×N square, FP32)
  2. Softmax over vector of length N
  3. Gradient computation (∂L/∂W for W ∈ R^{N×N})

Usage:
    uv run python benchmarks/benchmark_pytorch_vs_jax.py
    uv run python benchmarks/benchmark_pytorch_vs_jax.py --devices cpu
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import jax
import jax.numpy as jnp
import numpy as np
import torch

RESULTS_DIR = Path("results/data")
CHARTS_DIR = Path("results/charts/article_09")
N_RUNS = 100
WARMUP = 10


# ---------------------------------------------------------------------------
# PyTorch benchmarks
# ---------------------------------------------------------------------------


def pt_matmul(n: int) -> float:
    """Median matmul latency (ms) for N×N FP32 matrix on CPU."""
    a = torch.randn(n, n)
    b = torch.randn(n, n)

    # Warmup
    for _ in range(WARMUP):
        _ = torch.mm(a, b)

    times: list[float] = []
    for _ in range(N_RUNS):
        t0 = time.perf_counter()
        _ = torch.mm(a, b)
        times.append((time.perf_counter() - t0) * 1000)
    return float(np.median(times))


def pt_softmax(n: int) -> float:
    """Median softmax latency (ms) for vector of length N."""
    x = torch.randn(n)

    for _ in range(WARMUP):
        _ = torch.nn.functional.softmax(x, dim=0)

    times: list[float] = []
    for _ in range(N_RUNS * 2):
        t0 = time.perf_counter()
        _ = torch.nn.functional.softmax(x, dim=0)
        times.append((time.perf_counter() - t0) * 1000)
    return float(np.median(times))


def pt_grad(n: int) -> float:
    """Median gradient computation latency (ms) for dL/dW, W ∈ R^{N×N}.

    Teaching note: PyTorch's autograd works by recording operations on a
    computation graph (tape). .backward() walks this graph in reverse.
    The graph has O(depth) nodes and O(n²) gradient tensors for a single
    linear layer - this is the memory cost of backprop.
    """
    w = torch.randn(n, n, requires_grad=True)
    x = torch.randn(n)

    for _ in range(WARMUP):
        loss = torch.nn.functional.mse_loss(w @ x, torch.zeros(n))
        loss.backward()
        if w.grad is not None:
            w.grad.zero_()

    times: list[float] = []
    for _ in range(N_RUNS):
        loss = torch.nn.functional.mse_loss(w @ x, torch.zeros(n))
        t0 = time.perf_counter()
        loss.backward()
        times.append((time.perf_counter() - t0) * 1000)
        if w.grad is not None:
            w.grad.zero_()
    return float(np.median(times))


# ---------------------------------------------------------------------------
# JAX benchmarks
# ---------------------------------------------------------------------------


@jax.jit  # type: ignore[misc]
def _jax_matmul(a: jnp.ndarray, b: jnp.ndarray) -> jnp.ndarray:
    return jnp.dot(a, b)


@jax.jit  # type: ignore[misc]
def _jax_softmax(x: jnp.ndarray) -> jnp.ndarray:
    return jax.nn.softmax(x)


def _jax_loss(w: jnp.ndarray, x: jnp.ndarray) -> jnp.ndarray:
    pred = jnp.dot(w, x)
    return jnp.mean((pred - jnp.zeros_like(pred)) ** 2)


_jax_grad_fn = jax.jit(jax.grad(_jax_loss))


def jax_matmul(n: int) -> float:
    """Median matmul latency (ms) for N×N FP32 matrix, JAX jit."""
    key = jax.random.PRNGKey(0)
    a = jax.random.normal(key, (n, n))
    b = jax.random.normal(key, (n, n))

    # JIT warmup - first call compiles
    for _ in range(WARMUP):
        _jax_matmul(a, b).block_until_ready()

    times: list[float] = []
    for _ in range(N_RUNS):
        t0 = time.perf_counter()
        _jax_matmul(a, b).block_until_ready()
        times.append((time.perf_counter() - t0) * 1000)
    return float(np.median(times))


def jax_softmax(n: int) -> float:
    """Median softmax latency (ms) for vector of length N, JAX jit."""
    key = jax.random.PRNGKey(1)
    x = jax.random.normal(key, (n,))

    for _ in range(WARMUP):
        _jax_softmax(x).block_until_ready()

    times: list[float] = []
    for _ in range(N_RUNS * 2):
        t0 = time.perf_counter()
        _jax_softmax(x).block_until_ready()
        times.append((time.perf_counter() - t0) * 1000)
    return float(np.median(times))


def jax_grad(n: int) -> float:
    """Median gradient computation latency (ms) for dL/dW, W ∈ R^{N×N}.

    Teaching note: jax.grad returns a function that computes ∂L/∂W.
    Under the hood it uses reverse-mode AD via 'jaxprs' (JAX expression trees).
    The jit-compiled version fuses forward and backward into a single XLA graph,
    potentially allowing more optimisation than PyTorch's eager tape.
    """
    key = jax.random.PRNGKey(2)
    w = jax.random.normal(key, (n, n))
    x = jax.random.normal(key, (n,))

    for _ in range(WARMUP):
        _jax_grad_fn(w, x).block_until_ready()

    times: list[float] = []
    for _ in range(N_RUNS):
        t0 = time.perf_counter()
        _jax_grad_fn(w, x).block_until_ready()
        times.append((time.perf_counter() - t0) * 1000)
    return float(np.median(times))


# ---------------------------------------------------------------------------
# Chart
# ---------------------------------------------------------------------------


def plot_comparison(results: dict[str, dict[str, dict[str, float]]], output_path: Path) -> None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        ops = ["matmul", "softmax", "grad"]
        op_labels = ["Matrix Multiply\n(N×N)", "Softmax\n(length N)", "Gradient\n(dL/dW, N×N)"]
        colors = {"pytorch": "#e63946", "jax": "#457b9d"}

        # Use the largest size for the bar chart summary
        fig, axes = plt.subplots(1, 3, figsize=(13, 5))
        fig.suptitle("PyTorch vs JAX: Operation Latency (CPU, FP32)\nMedian of 100 runs")

        for ax, op, op_label in zip(axes, ops, op_labels):
            pt_sizes = sorted(int(k) for k in results["pytorch"][op])
            pt_vals = [results["pytorch"][op][str(s)] for s in pt_sizes]
            jax_vals = [results["jax"][op][str(s)] for s in pt_sizes]

            x = np.arange(len(pt_sizes))
            width = 0.35
            ax.bar(x - width / 2, pt_vals, width, label="PyTorch", color=colors["pytorch"])
            ax.bar(x + width / 2, jax_vals, width, label="JAX (jit)", color=colors["jax"])
            ax.set_xlabel("N (matrix/vector size)")
            ax.set_ylabel("Median latency (ms)")
            ax.set_title(op_label)
            ax.set_xticks(x)
            ax.set_xticklabels(pt_sizes)
            ax.legend(fontsize=8)
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
    parser = argparse.ArgumentParser(description="PyTorch vs JAX benchmark (task 5.10)")
    parser.add_argument(
        "--devices",
        default="cpu",
        help="Comma-separated list of devices to test (e.g. cpu,cuda). "
        "Only 'cpu' is supported without CUDA/TPU.",
    )
    parser.parse_args()

    print(f"PyTorch version: {torch.__version__}  device: cpu")
    print(f"JAX version: {jax.__version__}  backend: {jax.default_backend()}")
    print()

    sizes_matmul = [64, 256, 512, 1024]
    sizes_softmax = [128, 512, 2048, 8192]
    sizes_grad = [32, 64, 128, 256]

    pt_results: dict[str, dict[str, float]] = {"matmul": {}, "softmax": {}, "grad": {}}
    jax_results: dict[str, dict[str, float]] = {"matmul": {}, "softmax": {}, "grad": {}}

    # --- Matrix multiply ---
    print("[Matmul N×N]")
    for n in sizes_matmul:
        pt = pt_matmul(n)
        jx = jax_matmul(n)
        winner = "JAX" if jx < pt else "PyTorch"
        ratio = max(pt, jx) / max(min(pt, jx), 1e-6)
        print(f"  N={n:5d}: PyTorch={pt:.3f}ms  JAX={jx:.3f}ms  winner={winner} ({ratio:.2f}x)")
        pt_results["matmul"][str(n)] = round(pt, 4)
        jax_results["matmul"][str(n)] = round(jx, 4)

    # --- Softmax ---
    print("\n[Softmax, length N]")
    for n in sizes_softmax:
        pt = pt_softmax(n)
        jx = jax_softmax(n)
        winner = "JAX" if jx < pt else "PyTorch"
        ratio = max(pt, jx) / max(min(pt, jx), 1e-6)
        print(f"  N={n:5d}: PyTorch={pt:.4f}ms  JAX={jx:.4f}ms  winner={winner} ({ratio:.2f}x)")
        pt_results["softmax"][str(n)] = round(pt, 5)
        jax_results["softmax"][str(n)] = round(jx, 5)

    # --- Gradient ---
    print("\n[Gradient dL/dW, W ∈ R^{N×N}]")
    for n in sizes_grad:
        pt = pt_grad(n)
        jx = jax_grad(n)
        winner = "JAX" if jx < pt else "PyTorch"
        ratio = max(pt, jx) / max(min(pt, jx), 1e-6)
        print(f"  N={n:5d}: PyTorch={pt:.4f}ms  JAX={jx:.4f}ms  winner={winner} ({ratio:.2f}x)")
        pt_results["grad"][str(n)] = round(pt, 5)
        jax_results["grad"][str(n)] = round(jx, 5)

    # --- Print summary table ---
    print("\n[Summary - CPU, FP32, median of 100 runs]")
    print(f"{'Operation':<25} {'PyTorch':>12} {'JAX (jit)':>12} {'Winner':>10}")
    print("-" * 63)
    for op, label, sizes in [
        ("matmul", "matmul 1024×1024", [1024]),
        ("softmax", "softmax n=8192", [8192]),
        ("grad", "grad 256×256", [256]),
    ]:
        for n in sizes:
            pt = pt_results[op][str(n)]
            jx = jax_results[op][str(n)]
            winner = "JAX" if jx < pt else "PyTorch"
            print(f"  {label:<23} {pt:>10.3f}ms {jx:>10.3f}ms {winner:>10}")

    # Save JSON
    results = {
        "pytorch": pt_results,
        "jax": jax_results,
        "teaching_note": (
            "On CPU, PyTorch and JAX call the same BLAS/LAPACK libraries for matmul. "
            "Differences reflect dispatch overhead and JIT compile strategy. "
            "JAX jit tends to win on repeated calls (no Python dispatch overhead "
            "after compilation); PyTorch eager wins for one-shot ops or when "
            "torch.compile is not used. On TPU, JAX's XLA wins decisively."
        ),
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / "pytorch_vs_jax_benchmark.json"
    with open(out, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved: {out}")

    # Chart
    print("\n[Chart]")
    chart_data = {"pytorch": pt_results, "jax": jax_results}
    plot_comparison(chart_data, CHARTS_DIR / "05_pytorch_vs_jax.png")


if __name__ == "__main__":
    main()
