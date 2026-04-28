"""GPU detection and configuration.

This module detects available GPU hardware and provides configuration
for optimal compute backend selection.

Priority order: CUDA (NVIDIA) > Metal (Apple Silicon) > CPU

Teaching note: GPU selection is critical for:
- Local embedding generation (text-embeddings-inference)
- Fine-tuning embeddings (Article 9)
- PyTorch/JAX model training and inference

Why this priority order:
1. CUDA: Industry standard, best PyTorch/JAX support, highest throughput
2. Metal: Apple Silicon GPU, good for M-series chips, PyTorch MPS backend
3. CPU: Universal fallback, slower but always available

Metal (Apple Silicon) specifics:
- Available on M1/M2/M3/M4 Macs
- Accessed via PyTorch MPS (Metal Performance Shaders) backend
- text-embeddings-inference supports Metal acceleration
- Significantly faster than CPU, ~60-70% of CUDA performance
"""

from __future__ import annotations

import logging
import platform
import subprocess
from enum import Enum

logger = logging.getLogger(__name__)


class GPUBackend(str, Enum):
    """Available GPU backends."""

    CUDA = "cuda"
    METAL = "metal"
    CPU = "cpu"


class GPUInfo:
    """GPU information and capabilities."""

    def __init__(
        self,
        backend: GPUBackend,
        device_name: str,
        device_count: int = 1,
        is_available: bool = True,
    ) -> None:
        """
        Initialize GPU information.

        Args:
            backend: GPU backend type
            device_name: Human-readable device name
            device_count: Number of available devices
            is_available: Whether the backend is available
        """
        self.backend = backend
        self.device_name = device_name
        self.device_count = device_count
        self.is_available = is_available

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"GPUInfo(backend={self.backend}, device_name='{self.device_name}', "
            f"device_count={self.device_count}, is_available={self.is_available})"
        )

    def to_dict(self) -> dict[str, str | int | bool]:
        """Convert to dictionary for logging/config."""
        return {
            "backend": self.backend.value,
            "device_name": self.device_name,
            "device_count": self.device_count,
            "is_available": self.is_available,
        }


def _check_cuda_available() -> tuple[bool, str, int]:
    """
    Check if CUDA (NVIDIA GPU) is available.

    Returns:
        Tuple of (is_available, device_name, device_count)
    """
    try:
        import torch

        if torch.cuda.is_available():
            device_count = torch.cuda.device_count()
            device_name = torch.cuda.get_device_name(0) if device_count > 0 else "CUDA"
            return True, device_name, device_count
    except ImportError:
        pass
    except Exception as exc:
        # Broad on purpose: torch.cuda probing can raise driver-specific
        # errors (RuntimeError on missing libs, OSError on permission). The
        # nvidia-smi fallback below covers the same signal, so we log at
        # debug and keep going rather than fail hardware detection.
        logger.debug("torch.cuda probe failed: %s", exc)

    # Fallback: check nvidia-smi
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            gpus = result.stdout.strip().split("\n")
            return True, gpus[0], len(gpus)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    except Exception as exc:
        # Broad on purpose: subprocess.run can surface OSError variants
        # depending on platform/libc. Hardware detection must never crash
        # the application - log and degrade to "no CUDA".
        logger.debug("nvidia-smi probe failed: %s", exc)

    return False, "CUDA", 0


def _check_metal_available() -> tuple[bool, str, int]:
    """
    Check if Metal (Apple Silicon GPU) is available.

    Teaching note: Metal is Apple's GPU framework for M-series chips.
    PyTorch MPS (Metal Performance Shaders) provides acceleration.

    Returns:
        Tuple of (is_available, device_name, device_count)
    """
    # Check if running on macOS ARM (Apple Silicon)
    if platform.system() != "Darwin":
        return False, "Metal", 0

    if platform.machine() not in ("arm64", "aarch64"):
        return False, "Metal", 0

    # Check if PyTorch MPS is available
    try:
        import torch

        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            # Get chip info
            try:
                result = subprocess.run(
                    ["sysctl", "-n", "machdep.cpu.brand_string"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                chip_name = result.stdout.strip() if result.returncode == 0 else "Apple Silicon"
            except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
                logger.debug("sysctl chip probe failed: %s", exc)
                chip_name = "Apple Silicon"

            return True, chip_name, 1
    except ImportError:
        pass
    except Exception as exc:
        # Broad on purpose: torch.backends.mps probing has changed shape
        # across PyTorch versions and can raise AttributeError or RuntimeError
        # on older builds. Fall through to the no-PyTorch sysctl path.
        logger.debug("torch MPS probe failed: %s", exc)

    # Even without PyTorch, Metal is available on Apple Silicon
    # Just mark as available but note PyTorch MPS not installed
    try:
        result = subprocess.run(
            ["sysctl", "-n", "machdep.cpu.brand_string"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        chip_name = result.stdout.strip() if result.returncode == 0 else "Apple Silicon"
        # Check for M-series chip
        if any(m in chip_name.upper() for m in ["M1", "M2", "M3", "M4"]):
            return True, chip_name, 1
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        logger.debug("sysctl Apple-Silicon detection failed: %s", exc)

    return False, "Metal", 0


def detect_gpu() -> GPUInfo:
    """
    Detect available GPU backend with priority: CUDA > Metal > CPU.

    Teaching note: This function is called at application startup to
    configure the compute backend. The detected GPU affects:
    - text-embeddings-inference acceleration
    - PyTorch device selection (Article 9)
    - JAX platform selection (Article 9)

    Returns:
        GPUInfo with detected backend information

    Example:
        >>> gpu = detect_gpu()
        >>> print(f"Using {gpu.backend}: {gpu.device_name}")
        Using metal: Apple M4 Pro
    """
    # Priority 1: Check CUDA (NVIDIA)
    cuda_available, cuda_name, cuda_count = _check_cuda_available()
    if cuda_available:
        return GPUInfo(
            backend=GPUBackend.CUDA,
            device_name=cuda_name,
            device_count=cuda_count,
            is_available=True,
        )

    # Priority 2: Check Metal (Apple Silicon)
    metal_available, metal_name, metal_count = _check_metal_available()
    if metal_available:
        return GPUInfo(
            backend=GPUBackend.METAL,
            device_name=metal_name,
            device_count=metal_count,
            is_available=True,
        )

    # Priority 3: Fallback to CPU
    cpu_name = platform.processor() or platform.machine() or "CPU"
    import multiprocessing

    cpu_count = multiprocessing.cpu_count()

    return GPUInfo(
        backend=GPUBackend.CPU,
        device_name=f"{cpu_name} ({cpu_count} cores)",
        device_count=cpu_count,
        is_available=True,
    )


def get_pytorch_device() -> str:
    """
    Get PyTorch device string based on detected GPU.

    Returns:
        Device string: "cuda", "mps" (Metal), or "cpu"

    Example:
        >>> device = get_pytorch_device()
        >>> model = model.to(device)
    """
    gpu_info = detect_gpu()

    if gpu_info.backend == GPUBackend.CUDA:
        return "cuda"
    elif gpu_info.backend == GPUBackend.METAL:
        # PyTorch uses "mps" for Metal Performance Shaders
        return "mps"
    else:
        return "cpu"


def get_text_embeddings_inference_device() -> str:
    """
    Get device string for text-embeddings-inference.

    Teaching note: text-embeddings-inference uses different device strings:
    - CUDA: "--device cuda"
    - Metal: "--device metal" (Apple Silicon acceleration)
    - CPU: "--device cpu"

    Returns:
        Device string for text-embeddings-inference CLI

    Example:
        >>> device = get_text_embeddings_inference_device()
        >>> # Use in Docker: text-embeddings-inference --device metal
    """
    gpu_info = detect_gpu()
    return gpu_info.backend.value  # Returns "cuda", "metal", or "cpu"


# Cached GPU info to avoid repeated detection
_cached_gpu_info: GPUInfo | None = None


def get_gpu_info(force_refresh: bool = False) -> GPUInfo:
    """
    Get cached GPU information (singleton pattern).

    Args:
        force_refresh: If True, re-detect GPU instead of using cache

    Returns:
        GPUInfo with detected backend

    Example:
        >>> gpu = get_gpu_info()
        >>> if gpu.backend == GPUBackend.METAL:
        ...     print("Running on Apple Silicon")
    """
    global _cached_gpu_info

    if _cached_gpu_info is None or force_refresh:
        _cached_gpu_info = detect_gpu()

    return _cached_gpu_info
