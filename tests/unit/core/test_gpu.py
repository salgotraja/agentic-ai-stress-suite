"""Unit tests for GPU detection and configuration."""

from __future__ import annotations

import subprocess
import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.core import gpu
from src.core.gpu import (
    GPUBackend,
    GPUInfo,
    _check_cuda_available,
    _check_metal_available,
    detect_gpu,
    get_gpu_info,
    get_pytorch_device,
    get_text_embeddings_inference_device,
)


@pytest.fixture(autouse=True)
def _reset_cache() -> Any:
    """Reset the module-level GPU cache between tests so order doesn't matter."""
    gpu._cached_gpu_info = None
    yield
    gpu._cached_gpu_info = None


def _completed_process(stdout: str, returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


# ---------- GPUInfo dataclass ----------


def test_gpu_info_to_dict_round_trip() -> None:
    info = GPUInfo(
        backend=GPUBackend.METAL,
        device_name="Apple M4 Pro",
        device_count=1,
        is_available=True,
    )
    assert info.to_dict() == {
        "backend": "metal",
        "device_name": "Apple M4 Pro",
        "device_count": 1,
        "is_available": True,
    }


def test_gpu_info_repr_is_human_readable() -> None:
    info = GPUInfo(backend=GPUBackend.CPU, device_name="x86_64 (8 cores)", device_count=8)
    assert "GPUInfo" in repr(info)
    assert "x86_64 (8 cores)" in repr(info)


# ---------- _check_cuda_available ----------


def test_check_cuda_available_via_torch() -> None:
    """torch.cuda path is preferred over the nvidia-smi fallback."""
    fake_torch = MagicMock()
    fake_torch.cuda.is_available.return_value = True
    fake_torch.cuda.device_count.return_value = 2
    fake_torch.cuda.get_device_name.return_value = "NVIDIA A100"

    with patch.dict(sys.modules, {"torch": fake_torch}):
        available, name, count = _check_cuda_available()

    assert available is True
    assert name == "NVIDIA A100"
    assert count == 2


def test_check_cuda_available_falls_back_to_nvidia_smi_when_torch_missing() -> None:
    """When torch import fails, nvidia-smi output is parsed."""
    with patch.dict(sys.modules, {"torch": None}):
        with patch(
            "src.core.gpu.subprocess.run",
            return_value=_completed_process("Tesla T4\nTesla T4\n"),
        ) as mock_run:
            available, name, count = _check_cuda_available()

    assert available is True
    assert name == "Tesla T4"
    assert count == 2
    mock_run.assert_called_once()


def test_check_cuda_unavailable_when_both_paths_fail() -> None:
    """No torch + no nvidia-smi binary -> not available, sentinel name."""
    with patch.dict(sys.modules, {"torch": None}):
        with patch("src.core.gpu.subprocess.run", side_effect=FileNotFoundError):
            available, name, count = _check_cuda_available()

    assert available is False
    assert name == "CUDA"
    assert count == 0


def test_check_cuda_handles_torch_runtime_error() -> None:
    """Driver/library errors must not crash detection - they fall through to nvidia-smi."""
    fake_torch = MagicMock()
    fake_torch.cuda.is_available.side_effect = RuntimeError("driver mismatch")

    with patch.dict(sys.modules, {"torch": fake_torch}):
        with patch("src.core.gpu.subprocess.run", side_effect=FileNotFoundError):
            available, _, _ = _check_cuda_available()

    assert available is False


# ---------- _check_metal_available ----------


def test_check_metal_unavailable_on_non_darwin() -> None:
    with patch("src.core.gpu.platform.system", return_value="Linux"):
        available, name, count = _check_metal_available()
    assert available is False
    assert name == "Metal"
    assert count == 0


def test_check_metal_unavailable_on_intel_mac() -> None:
    with patch("src.core.gpu.platform.system", return_value="Darwin"):
        with patch("src.core.gpu.platform.machine", return_value="x86_64"):
            available, _, _ = _check_metal_available()
    assert available is False


def test_check_metal_available_via_torch_mps() -> None:
    """Apple Silicon + torch MPS path returns chip name from sysctl."""
    fake_torch = MagicMock()
    fake_torch.backends.mps.is_available.return_value = True

    with patch("src.core.gpu.platform.system", return_value="Darwin"):
        with patch("src.core.gpu.platform.machine", return_value="arm64"):
            with patch.dict(sys.modules, {"torch": fake_torch}):
                with patch(
                    "src.core.gpu.subprocess.run",
                    return_value=_completed_process("Apple M4 Pro\n"),
                ):
                    available, name, count = _check_metal_available()

    assert available is True
    assert name == "Apple M4 Pro"
    assert count == 1


def test_check_metal_available_without_torch_via_sysctl() -> None:
    """Apple Silicon without torch still reports Metal when sysctl shows M-series."""
    with patch("src.core.gpu.platform.system", return_value="Darwin"):
        with patch("src.core.gpu.platform.machine", return_value="arm64"):
            with patch.dict(sys.modules, {"torch": None}):
                with patch(
                    "src.core.gpu.subprocess.run",
                    return_value=_completed_process("Apple M2\n"),
                ):
                    available, name, _ = _check_metal_available()

    assert available is True
    assert name == "Apple M2"


def test_check_metal_unavailable_on_darwin_arm_without_m_series_marker() -> None:
    """Defensive: Darwin/arm64 but sysctl reports a non-M chip -> not Metal."""
    with patch("src.core.gpu.platform.system", return_value="Darwin"):
        with patch("src.core.gpu.platform.machine", return_value="arm64"):
            with patch.dict(sys.modules, {"torch": None}):
                with patch(
                    "src.core.gpu.subprocess.run",
                    return_value=_completed_process("Some Other Chip\n"),
                ):
                    available, _, _ = _check_metal_available()

    assert available is False


# ---------- detect_gpu priority ----------


def test_detect_gpu_prefers_cuda() -> None:
    with patch("src.core.gpu._check_cuda_available", return_value=(True, "NVIDIA A100", 1)):
        with patch("src.core.gpu._check_metal_available", return_value=(True, "Apple M4", 1)):
            info = detect_gpu()
    assert info.backend == GPUBackend.CUDA
    assert info.device_name == "NVIDIA A100"


def test_detect_gpu_picks_metal_when_no_cuda() -> None:
    with patch("src.core.gpu._check_cuda_available", return_value=(False, "CUDA", 0)):
        with patch("src.core.gpu._check_metal_available", return_value=(True, "Apple M4", 1)):
            info = detect_gpu()
    assert info.backend == GPUBackend.METAL
    assert info.device_name == "Apple M4"


def test_detect_gpu_falls_back_to_cpu() -> None:
    with patch("src.core.gpu._check_cuda_available", return_value=(False, "CUDA", 0)):
        with patch("src.core.gpu._check_metal_available", return_value=(False, "Metal", 0)):
            info = detect_gpu()
    assert info.backend == GPUBackend.CPU
    assert info.is_available is True
    assert info.device_count >= 1


# ---------- caching ----------


def test_get_gpu_info_caches_first_call() -> None:
    """detect_gpu must run once, then results come from the module cache."""
    with patch("src.core.gpu.detect_gpu") as mock_detect:
        mock_detect.return_value = GPUInfo(GPUBackend.CPU, "x86_64 (4 cores)", 4)
        first = get_gpu_info()
        second = get_gpu_info()

    assert first is second
    mock_detect.assert_called_once()


def test_get_gpu_info_force_refresh_redetects() -> None:
    with patch("src.core.gpu.detect_gpu") as mock_detect:
        mock_detect.return_value = GPUInfo(GPUBackend.CPU, "x86_64 (4 cores)", 4)
        get_gpu_info()
        get_gpu_info(force_refresh=True)

    assert mock_detect.call_count == 2


# ---------- public device-string helpers ----------


@pytest.mark.parametrize(
    "backend, expected",
    [
        (GPUBackend.CUDA, "cuda"),
        (GPUBackend.METAL, "mps"),
        (GPUBackend.CPU, "cpu"),
    ],
)
def test_get_pytorch_device_maps_backend(backend: GPUBackend, expected: str) -> None:
    """PyTorch uses 'mps' for Metal, not 'metal' - verify the mapping is correct."""
    with patch(
        "src.core.gpu.detect_gpu",
        return_value=GPUInfo(backend, "fake", 1),
    ):
        assert get_pytorch_device() == expected


@pytest.mark.parametrize(
    "backend, expected",
    [
        (GPUBackend.CUDA, "cuda"),
        (GPUBackend.METAL, "metal"),
        (GPUBackend.CPU, "cpu"),
    ],
)
def test_get_text_embeddings_inference_device(backend: GPUBackend, expected: str) -> None:
    """text-embeddings-inference uses 'metal' (not 'mps') for Apple Silicon."""
    with patch(
        "src.core.gpu.detect_gpu",
        return_value=GPUInfo(backend, "fake", 1),
    ):
        assert get_text_embeddings_inference_device() == expected


def test_device_helpers_share_the_cache() -> None:
    """Both helpers must route through get_gpu_info() so detect_gpu runs once."""
    with patch("src.core.gpu.detect_gpu") as mock_detect:
        mock_detect.return_value = GPUInfo(GPUBackend.CPU, "x86_64 (4 cores)", 4)
        get_pytorch_device()
        get_text_embeddings_inference_device()
        get_pytorch_device()

    mock_detect.assert_called_once()
