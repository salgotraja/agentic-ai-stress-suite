"""DL environment check for Article 9 - task 5.1.

Teaching note: WHY check hardware before fine-tuning?
  Fine-tuning an embedding model with 22M parameters (BGE-base-en-v1.5)
  on 2000 pairs takes ~5 min on M4 MPS vs ~30 min on CPU. The device
  selection below mirrors the auto-detection in src/core/config.py so
  training and inference use the same logic throughout the project.

  JAX note: jax-metal (Apple Silicon GPU) requires a separate install
  and is pinned to specific jaxlib versions. To keep dependency resolution
  stable we use CPU-only JAX here; GPU JAX benchmarks would require a
  separate environment (e.g. Google Colab with A100). The PyTorch benchmarks
  run on MPS and are the primary hardware-accelerated path on M4.

Run:
    uv run python examples/article_09_dl/check_environment.py
"""

from __future__ import annotations

import importlib.metadata


def _version(package: str) -> str:
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return "not installed"


def check_torch() -> None:
    import torch

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    print(f"  PyTorch:        {torch.__version__}")
    print(f"  MPS available:  {torch.backends.mps.is_available()}")
    print(f"  CUDA available: {torch.cuda.is_available()}")
    print(f"  Active device:  {device}")

    # Quick smoke test on active device
    t = torch.ones(3, 3, device=device)
    assert t.sum().item() == 9.0, "Tensor op failed"
    print(f"  Smoke test:     PASS (3x3 ones on {device})")


def check_jax() -> None:
    import jax
    import jax.numpy as jnp

    print(f"  JAX:            {jax.__version__}")
    print(f"  JAX devices:    {jax.devices()}")

    # Quick smoke test
    x = jnp.ones((3, 3))
    assert float(x.sum()) == 9.0, "JAX op failed"
    print("  Smoke test:     PASS (3x3 ones on CPU)")


def check_transformers() -> None:
    import transformers

    print(f"  Transformers:   {transformers.__version__}")
    print(f"  SentTrans:      {_version('sentence-transformers')}")


def check_umap() -> None:
    print(f"  umap-learn:     {_version('umap-learn')}")


def main() -> None:
    print("=== DL Environment Check ===\n")

    print("[PyTorch]")
    check_torch()

    print("\n[JAX]")
    check_jax()

    print("\n[Transformers]")
    check_transformers()

    print("\n[Visualization]")
    check_umap()

    print("\nAll checks passed.")


if __name__ == "__main__":
    main()
