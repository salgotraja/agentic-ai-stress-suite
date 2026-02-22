"""DPR-like dense retriever implemented in JAX — task 5.9.

Teaching note: JAX vs PyTorch design philosophy
  PyTorch: imperative, eager execution, mutable state
    - Define operations as class methods (nn.Module)
    - State stored inside modules (model.weight, model.bias)
    - Natural for researchers who think step-by-step
    - Autograd: .backward() fills .grad attributes

  JAX: functional, explicit state, transformations
    - Functions, not classes: f(params, x) → y
    - State is explicit: params dict passed as argument
    - Transformations stack: jit(vmap(grad(f)))
    - Autograd: jax.grad returns a function, not a value

  Why this matters for retrieval:
    JAX's functional design makes batch operations cleaner.
    jax.vmap(encode)(batch_queries) vectorises over the batch
    axis without explicit batch dimensions in the forward function.
    jax.jit compiles the function to XLA for hardware-optimised kernels.

DPR (Dense Passage Retrieval):
  Two encoders — query encoder Q(q) and passage encoder P(d) —
  trained so that dot(Q(q), P(d_pos)) >> dot(Q(q), P(d_neg)).
  Here we use a single shared encoder for both (symmetric DPR)
  to keep the teaching example concise.
  Architecture: embedding lookup → mean pooling → linear projection → L2 norm

jax.distributed.initialize():
  In production, call once at program start before any JAX ops.
  On a multi-host TPU pod:
    jax.distributed.initialize(coordinator_address='<coordinator-host>:1234',
                                num_processes=8, process_id=rank)
  On a single machine: no-op (safe to call, just prints info).
  Here we demonstrate the API without multi-host infrastructure.

Usage:
    uv run python examples/article_09_dl/jax_retriever.py
    uv run python examples/article_09_dl/jax_retriever.py --device cpu
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import jax
import jax.numpy as jnp
import numpy as np

# ---------------------------------------------------------------------------
# Distributed init (demonstration)
# ---------------------------------------------------------------------------


def init_distributed() -> None:
    """Demonstrate jax.distributed.initialize() for multi-host setups.

    Teaching note: On a single machine this is a no-op — JAX already detects
    all local devices. The call pattern is shown so readers know where to add
    it when scaling to TPU pods or multi-GPU clusters.
    """
    # On a single machine, distributed init is automatic.
    # For multi-host: jax.distributed.initialize(coordinator_address=...,
    #                     num_processes=N, process_id=rank)
    print(f"  JAX devices: {jax.devices()}")
    print(f"  Default backend: {jax.default_backend()}")
    print("  (Single-machine: distributed init is automatic)")


# ---------------------------------------------------------------------------
# Model parameters (pure dicts — JAX style)
# ---------------------------------------------------------------------------


def init_params(vocab_size: int, embed_dim: int, proj_dim: int, key: Any) -> dict[str, Any]:
    """Initialise model parameters as a plain dict.

    Teaching note: In JAX, model state is explicit data — a dict of arrays.
    There are no "modules" with hidden state. This makes:
      - Serialisation trivial (just save the dict)
      - Functional transforms natural (pass params as first argument)
      - Multi-device sharding explicit (shard the dict)
    Frameworks like Flax and Equinox add thin wrappers around this pattern.
    """
    k1, k2 = jax.random.split(key, 2)
    return {
        # Word embedding table: vocab_size × embed_dim
        # Initialised with small random values (Xavier-like)
        "embed": jax.random.normal(k1, (vocab_size, embed_dim)) * 0.02,
        # Projection: embed_dim → proj_dim
        # Projects pooled embedding into retrieval space
        "proj_w": jax.random.normal(k2, (embed_dim, proj_dim)) * 0.02,
        "proj_b": jnp.zeros(proj_dim),
    }


# ---------------------------------------------------------------------------
# Forward pass (pure function)
# ---------------------------------------------------------------------------


def encode(params: dict[str, Any], token_ids: jnp.ndarray) -> jnp.ndarray:
    """Encode a single sequence to a unit-norm dense vector.

    Teaching note: This is a pure function — same inputs always produce same
    outputs, no side effects. This is required for jax.jit (which caches the
    compiled version) and jax.grad (which differentiates through it).

    The steps mirror BGE/DPR encoding:
      1. Token embeddings: [seq_len] → [seq_len, embed_dim]
      2. Mean pooling: [seq_len, embed_dim] → [embed_dim]
      3. Linear projection: [embed_dim] → [proj_dim]
      4. L2 normalisation: cosine similarity = dot product of unit vectors
    """
    # Step 1: embedding lookup (equivalent to nn.Embedding in PyTorch)
    x = params["embed"][token_ids]  # [seq_len, embed_dim]

    # Step 2: mean pooling (simplified — real BGE uses attention mask)
    x = jnp.mean(x, axis=0)  # [embed_dim]

    # Step 3: linear projection
    x = jnp.dot(x, params["proj_w"]) + params["proj_b"]  # [proj_dim]

    # Step 4: L2 normalisation → cosine similarity = dot product
    x = x / (jnp.linalg.norm(x) + 1e-9)
    return x  # [proj_dim]


# Batched version via vmap — no explicit batch dimension in encode()
# jax.vmap maps encode over the first axis of token_ids [B, seq_len] → [B, proj_dim]
# Teaching note: vmap eliminates the manual batch loop and lets XLA vectorise
# the operation across hardware. The function doesn't change — only the call site.
encode_batch = jax.vmap(encode, in_axes=(None, 0))

# JIT-compiled version — compiled on first call, cached for all subsequent calls.
# Teaching note: @jax.jit (or jax.jit(f)) traces f with abstract values,
# compiles to XLA HLO, and caches by input shape/dtype. Subsequent calls
# skip Python overhead (~10-100x faster for small models on TPU).
encode_batch_jit = jax.jit(encode_batch)


# ---------------------------------------------------------------------------
# InfoNCE loss (JAX autograd demo)
# ---------------------------------------------------------------------------


def infonce_loss(
    params: dict[str, Any],
    query_ids: jnp.ndarray,
    pos_ids: jnp.ndarray,
    neg_ids: jnp.ndarray,
) -> jnp.ndarray:
    """InfoNCE contrastive loss for dual-encoder training.

    Teaching note: jax.grad requires the loss to be a scalar-valued
    pure function of params. The gradient of this function w.r.t. params
    is computed symbolically by JAX's autograd — no .backward() call needed.

    InfoNCE: maximise similarity(q, pos) while minimising similarity(q, neg_i)
      loss = -log(exp(sim(q, pos)) / (exp(sim(q, pos)) + Σ exp(sim(q, neg_i))))
    This is equivalent to cross-entropy over a (1+N) class problem.
    """
    q = encode(params, query_ids)  # [proj_dim]
    p = encode(params, pos_ids)  # [proj_dim]
    n = encode(params, neg_ids)  # [proj_dim] (single negative for simplicity)

    logits = jnp.stack([jnp.dot(q, p), jnp.dot(q, n)])  # [2]
    # Cross-entropy loss: label 0 is the positive
    loss = -jnp.log(jax.nn.softmax(logits)[0] + 1e-9)
    return loss


# Gradient function: same signature as infonce_loss but returns dL/d(params)
# Teaching note: jax.grad(f)(x) is mathematically identical to ∂f/∂x.
# Unlike PyTorch's .backward(), it returns a new dict with the same structure
# as params — making gradient clipping and weight updates explicit.
loss_and_grad = jax.jit(jax.value_and_grad(infonce_loss))


# ---------------------------------------------------------------------------
# Benchmark helpers
# ---------------------------------------------------------------------------


def _make_random_inputs(
    batch_size: int,
    seq_len: int,
    vocab_size: int,
    key: Any,
) -> jnp.ndarray:
    return jax.random.randint(key, (batch_size, seq_len), 0, vocab_size)


def benchmark_encode(
    params: dict[str, Any],
    batch_sizes: list[int],
    seq_len: int,
    vocab_size: int,
    n_runs: int = 50,
) -> dict[int, float]:
    """Measure median encode latency (ms) per batch size after JIT warmup."""
    results: dict[int, float] = {}
    key = jax.random.PRNGKey(0)

    for bs in batch_sizes:
        token_ids = _make_random_inputs(bs, seq_len, vocab_size, key)

        # Warmup — first call triggers JIT compilation (slow)
        for _ in range(3):
            _ = encode_batch_jit(params, token_ids).block_until_ready()

        times: list[float] = []
        for _ in range(n_runs):
            t0 = time.perf_counter()
            _ = encode_batch_jit(params, token_ids).block_until_ready()
            times.append((time.perf_counter() - t0) * 1000)

        results[bs] = round(float(np.median(times)), 3)
        print(f"    batch={bs:4d}: {results[bs]:.3f}ms median")

    return results


def benchmark_matmul(sizes: list[int], n_runs: int = 100) -> dict[int, dict[str, float]]:
    """Benchmark square matrix multiplication N×N for different N.

    Teaching note: XLA fuses transpose + matmul into a single kernel.
    The matmul kernel is the most compute-bound operation in transformer
    inference (it corresponds to aten::addmm in the PyTorch profiler output
    from task 5.6). JAX's XLA backend produces identical operations, allowing
    direct apples-to-apples comparison.
    """
    results: dict[int, dict[str, float]] = {}
    key = jax.random.PRNGKey(1)

    @jax.jit
    def _matmul(a: jnp.ndarray, b: jnp.ndarray) -> jnp.ndarray:
        return jnp.dot(a, b)

    for n in sizes:
        a = jax.random.normal(key, (n, n))
        b = jax.random.normal(key, (n, n))

        # Warmup
        for _ in range(3):
            _matmul(a, b).block_until_ready()

        times: list[float] = []
        for _ in range(n_runs):
            t0 = time.perf_counter()
            _matmul(a, b).block_until_ready()
            times.append((time.perf_counter() - t0) * 1000)

        median_ms = round(float(np.median(times)), 3)
        results[n] = {"median_ms": median_ms}
        print(f"    matmul {n}×{n}: {median_ms:.3f}ms")

    return results


def benchmark_softmax(sizes: list[int], n_runs: int = 200) -> dict[int, float]:
    """Benchmark softmax over a vector of length N."""
    results: dict[int, float] = {}
    key = jax.random.PRNGKey(2)

    @jax.jit
    def _softmax(x: jnp.ndarray) -> jnp.ndarray:
        return jax.nn.softmax(x)

    for n in sizes:
        x = jax.random.normal(key, (n,))

        # Warmup
        for _ in range(3):
            _softmax(x).block_until_ready()

        times: list[float] = []
        for _ in range(n_runs):
            t0 = time.perf_counter()
            _softmax(x).block_until_ready()
            times.append((time.perf_counter() - t0) * 1000)

        results[n] = round(float(np.median(times)), 4)
        print(f"    softmax n={n}: {results[n]:.4f}ms")

    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

VOCAB_SIZE = 30_000
EMBED_DIM = 256
PROJ_DIM = 128
SEQ_LEN = 32


def main() -> None:
    parser = argparse.ArgumentParser(description="JAX DPR-like retriever benchmark (task 5.9)")
    parser.add_argument("--device", default="cpu", help="Device (cpu; gpu/tpu if available)")
    parser.add_argument(
        "--runs", type=int, default=50, help="Benchmark runs per config (default: 50)"
    )
    args = parser.parse_args()

    print(f"JAX version: {jax.__version__}")
    print(f"Backend: {jax.default_backend()}")
    print()

    print("[Distributed init]")
    init_distributed()
    print()

    print("[Model init]")
    key = jax.random.PRNGKey(42)
    params = init_params(VOCAB_SIZE, EMBED_DIM, PROJ_DIM, key)
    n_params = sum(p.size for p in jax.tree.leaves(params))
    print(f"  Parameters: {n_params:,} ({n_params * 4 / 1e6:.1f}MB float32)")
    print()

    print("[Encode benchmark — batched via vmap + jit]")
    batch_results = benchmark_encode(
        params,
        batch_sizes=[1, 8, 32, 128],
        seq_len=SEQ_LEN,
        vocab_size=VOCAB_SIZE,
        n_runs=args.runs,
    )
    print()

    print("[Gradient computation demo — jax.value_and_grad]")
    key, k1, k2, k3 = jax.random.split(key, 4)
    q_ids = jax.random.randint(k1, (SEQ_LEN,), 0, VOCAB_SIZE)
    p_ids = jax.random.randint(k2, (SEQ_LEN,), 0, VOCAB_SIZE)
    n_ids = jax.random.randint(k3, (SEQ_LEN,), 0, VOCAB_SIZE)

    t0 = time.perf_counter()
    loss_val, grads = loss_and_grad(params, q_ids, p_ids, n_ids)
    grad_ms = (time.perf_counter() - t0) * 1000
    print(f"  InfoNCE loss: {float(loss_val):.4f}")
    print(f"  Grad shapes: {{{', '.join(f'{k}: {v.shape}' for k, v in grads.items())}}}")
    print(f"  Grad norm (embed): {float(jnp.linalg.norm(grads['embed'])):.6f}")
    print(f"  Forward+backward: {grad_ms:.2f}ms (includes JIT compilation)")
    print()

    print("[Matrix multiply benchmark — N×N]")
    matmul_results = benchmark_matmul(
        sizes=[64, 256, 512, 1024],
        n_runs=args.runs,
    )
    print()

    print("[Softmax benchmark]")
    softmax_results = benchmark_softmax(
        sizes=[128, 512, 2048, 8192],
        n_runs=args.runs * 2,
    )
    print()

    # Save results
    out = Path("results/data/jax_retriever_benchmark.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    results = {
        "backend": jax.default_backend(),
        "jax_version": jax.__version__,
        "model": {
            "vocab_size": VOCAB_SIZE,
            "embed_dim": EMBED_DIM,
            "proj_dim": PROJ_DIM,
            "seq_len": SEQ_LEN,
            "n_params": n_params,
        },
        "encode_latency_ms": {str(k): v for k, v in batch_results.items()},
        "matmul_latency_ms": {str(k): v for k, v in matmul_results.items()},
        "softmax_latency_ms": {str(k): v for k, v in softmax_results.items()},
    }
    with open(out, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Results saved: {out}")


if __name__ == "__main__":
    main()
