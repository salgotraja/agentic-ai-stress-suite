"""PyTorch inference optimizations for the BGE embedder - tasks 5.5, 5.6, 5.7.

What this measures, all on CPU with a fixed thread count:

  1. torch.compile
     Eager vs two backends. ``aot_eager`` traces the graph through Dynamo and
     AOTAutograd but generates no new kernels, so it cannot fuse anything.
     ``inductor`` generates C++ kernels for CPU. Graph breaks are counted with
     torch._dynamo.explain rather than assumed.

  2. Dynamic INT8 quantization (torch.ao, qnnpack engine on Apple Silicon)
     Only nn.Linear weights become INT8; the embedding tables and LayerNorms
     stay FP32. The first version assumed a 4x smaller model
     (int8_size_mb = fp32_size_mb / 4). This version measures:
       - serialized size: bytes of torch.save(state_dict) on disk
       - runtime memory: in a fresh process per variant, resident memory after
         loading the model and encoding one query (garbage collected), and peak
         RSS. Dynamic quantization starts from the FP32 model, so the INT8
         peak includes the FP32 load.
       - retrieval quality: document-level Recall@5 and MRR over the full chunk
         corpus, FP32 vs INT8, paired per question
     The first version also mean-pooled token embeddings; BGE uses the [CLS]
     token (1_Pooling/config.json), so its 0.983 cosine compared embeddings the
     retriever never uses. Encoding here goes through SentenceTransformer, so
     pooling and normalisation match the retriever.

Usage:
    uv run python examples/article_09_dl/pytorch_optimizations.py
    # Output: results/data/article_09/pytorch_optimizations_<date>.json
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import platform
import resource
import subprocess
import sys
import tempfile
import time
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import torch

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

MODEL_NAME = "BAAI/bge-base-en-v1.5"
SAMPLE_QUERY = "What is FastAPI dependency injection?"
THREADS = 4
WARMUP_RUNS = 5
BENCH_RUNS = 50


def _load_st(device: str = "cpu") -> Any:
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(MODEL_NAME, device=device)


def _quantize(st_model: Any) -> Any:
    """Dynamic INT8 on every nn.Linear inside the transformer; returns a copy."""
    torch.backends.quantized.engine = "qnnpack"
    quantized = copy.deepcopy(st_model)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        # In place: sentence-transformers 5 does not accept a replacement
        # auto_model by assignment, which silently left the model FP32.
        torch.ao.quantization.quantize_dynamic(  # type: ignore[no-untyped-call]
            quantized[0].auto_model, {torch.nn.Linear}, dtype=torch.qint8, inplace=True
        )
    n_dynamic = sum(
        1
        for m in quantized[0].auto_model.modules()
        if type(m).__module__.startswith("torch.ao.nn.quantized.dynamic")
    )
    if n_dynamic == 0:
        raise RuntimeError("quantize_dynamic replaced no Linear layers")
    return quantized


def _inputs(st_model: Any) -> dict[str, torch.Tensor]:
    tok = st_model.tokenizer
    out: dict[str, torch.Tensor] = tok(
        SAMPLE_QUERY, return_tensors="pt", padding="max_length", truncation=True, max_length=128
    )
    return out


def _median_ms(fn: Any) -> float:
    for _ in range(WARMUP_RUNS):
        fn()
    times = []
    for _ in range(BENCH_RUNS):
        t0 = time.perf_counter()
        fn()
        times.append((time.perf_counter() - t0) * 1000)
    return float(np.median(times))


def benchmark_compile(st_model: Any) -> dict[str, Any]:
    """Eager vs torch.compile backends on the bare transformer forward pass."""
    bert = st_model[0].auto_model.eval()
    inputs = _inputs(st_model)

    def run(m: Any) -> Any:
        with torch.no_grad():
            return m(**inputs).last_hidden_state[:, 0]

    result: dict[str, Any] = {"device": "cpu", "threads": THREADS, "input": "1 x 128 tokens"}
    result["eager_ms"] = round(_median_ms(lambda: run(bert)), 2)

    explanation = torch._dynamo.explain(bert)(**inputs)
    result["dynamo_graph_count"] = explanation.graph_count
    result["dynamo_graph_break_count"] = explanation.graph_break_count
    result["dynamo_break_reasons"] = [str(r.reason) for r in explanation.break_reasons][:5]

    for backend in ("aot_eager", "inductor"):
        torch._dynamo.reset()
        entry: dict[str, Any] = {}
        try:
            compiled = torch.compile(bert, backend=backend)
            t0 = time.perf_counter()
            run(compiled)
            entry["first_call_ms"] = round((time.perf_counter() - t0) * 1000, 1)
            entry["steady_ms"] = round(_median_ms(lambda m=compiled: run(m)), 2)
            entry["speedup_vs_eager"] = round(result["eager_ms"] / entry["steady_ms"], 3)
        except Exception as exc:  # noqa: BLE001 - record why a backend failed
            lines = str(exc).splitlines()
            cause = next((ln for ln in lines if "error:" in ln), lines[0] if lines else "")
            entry["error"] = f"{type(exc).__name__}: {cause.replace(str(Path.home()), '~')}"
        result[backend] = entry
    torch._dynamo.reset()
    return result


def _state_dict_bytes(module: torch.nn.Module) -> int:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "model.pt"
        torch.save(module.state_dict(), path)
        return path.stat().st_size


def _rss_bytes() -> int:
    # ru_maxrss is bytes on macOS, kilobytes on Linux.
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(peak if sys.platform == "darwin" else peak * 1024)


def memory_probe(mode: str, path: str | None) -> None:
    """Run in a fresh process: print resident and peak memory around one forward pass.

    mode "checkpoint": load a whole pickled transformer module from ``path``
    (FP32 or already-quantized INT8), so only that model is ever resident.
    mode "quantize_at_startup": load FP32, quantize, drop the original.
    """
    import gc

    import psutil
    from transformers import AutoTokenizer

    torch.set_num_threads(THREADS)
    torch.backends.quantized.engine = "qnnpack"
    proc = psutil.Process()
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    before = proc.memory_info().rss
    if mode == "checkpoint":
        module = torch.load(str(path), weights_only=False)
    else:
        st = _load_st()
        module = _quantize(st)[0].auto_model
        del st
    inputs = tokenizer(SAMPLE_QUERY, return_tensors="pt")
    with torch.no_grad():
        module(**inputs)
    gc.collect()
    print(
        json.dumps(
            {"rss_before": before, "rss_after": proc.memory_info().rss, "rss_peak": _rss_bytes()}
        )
    )


def _probe(mode: str, path: Path | None = None) -> dict[str, float]:
    cmd = [sys.executable, __file__, "--memory-probe", mode]
    if path is not None:
        cmd += ["--path", str(path)]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True, cwd=PROJECT_ROOT)
    data = json.loads(out.stdout.strip().splitlines()[-1])
    return {
        "resident_growth_mb": round((data["rss_after"] - data["rss_before"]) / 1e6, 1),
        "peak_rss_mb": round(data["rss_peak"] / 1e6, 1),
    }


def _runtime_memory(fp32_bert: torch.nn.Module, int8_bert: torch.nn.Module) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        fp32_path, int8_path = Path(tmp) / "fp32.pt", Path(tmp) / "int8.pt"
        torch.save(fp32_bert, fp32_path)
        torch.save(int8_bert, int8_path)
        return {
            "fp32_checkpoint": _probe("checkpoint", fp32_path),
            "int8_checkpoint": _probe("checkpoint", int8_path),
            "int8_quantize_at_startup": _probe("quantize_at_startup"),
            "pickled_module_mb": {
                "fp32": round(fp32_path.stat().st_size / 1e6, 1),
                "int8": round(int8_path.stat().st_size / 1e6, 1),
            },
        }


def benchmark_quantization(st_model: Any) -> dict[str, Any]:
    from benchmarks.article_09_eval import paired_summary
    from benchmarks.benchmark_custom_embeddings import evaluate, mean_metrics
    from benchmarks.build_article_09_candidates import corpus_chunks
    from scripts.prepare_dl_training_data import load_questions

    quantized = _quantize(st_model)
    fp32_bert = st_model[0].auto_model
    int8_bert = quantized[0].auto_model
    linear_params = sum(
        m.weight.numel() for m in fp32_bert.modules() if isinstance(m, torch.nn.Linear)
    )
    all_params = sum(p.numel() for p in fp32_bert.parameters())

    result: dict[str, Any] = {
        "engine": torch.backends.quantized.engine,
        "quantized_modules": "torch.nn.Linear only",
        "linear_weight_share_of_params": round(linear_params / all_params, 4),
        "serialized_state_dict_mb": {
            "fp32": round(_state_dict_bytes(fp32_bert) / 1e6, 1),
            "int8": round(_state_dict_bytes(int8_bert) / 1e6, 1),
        },
        "runtime_memory": _runtime_memory(fp32_bert, int8_bert),
        "latency_ms_single_query": {
            "fp32": round(_median_ms(lambda: st_model.encode([SAMPLE_QUERY])), 2),
            "int8": round(_median_ms(lambda: quantized.encode([SAMPLE_QUERY])), 2),
        },
    }
    sizes = result["serialized_state_dict_mb"]
    result["serialized_size_ratio"] = round(sizes["fp32"] / sizes["int8"], 2)

    fp_emb = st_model.encode([SAMPLE_QUERY], normalize_embeddings=True)
    q_emb = quantized.encode([SAMPLE_QUERY], normalize_embeddings=True)
    result["cls_cosine_fp32_vs_int8_sample_query"] = round(float((fp_emb * q_emb).sum()), 6)

    split = {
        q["id"]: q
        for q in json.loads(Path("datasets/dl_training_split.json").read_text())["questions"]
    }
    questions = {q["id"]: q for q in load_questions()}
    ids = list(questions)
    test_ids = [i for i in ids if split[i]["split"] == "test"]
    chunks = corpus_chunks()
    fp_pq = evaluate(st_model, ids, questions, chunks)
    q_pq = evaluate(quantized, ids, questions, chunks)
    result["retrieval_quality"] = {
        "note": "stock model, never trained here, so all 192 questions are fair to use",
        "all_questions": {"fp32": mean_metrics(fp_pq, ids), "int8": mean_metrics(q_pq, ids)},
        "test_split": {"fp32": mean_metrics(fp_pq, test_ids), "int8": mean_metrics(q_pq, test_ids)},
        "int8_minus_fp32_all": {
            m: paired_summary(
                [fp_pq[i][m] for i in ids],
                [q_pq[i][m] for i in ids],
                groups=[split[i]["group"] for i in ids],
            )
            for m in ("mrr", "recall_at_5")
        },
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--memory-probe", choices=["checkpoint", "quantize_at_startup"])
    parser.add_argument("--path")
    args = parser.parse_args()
    if args.memory_probe:
        memory_probe(args.memory_probe, args.path)
        return

    from benchmarks.benchmark_custom_embeddings import git_provenance

    torch.set_num_threads(THREADS)
    provenance = git_provenance()
    load_start = [round(x, 2) for x in os.getloadavg()]
    cpu = subprocess.run(
        ["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True, check=False
    ).stdout.strip()

    print("[torch.compile]")
    compile_result = benchmark_compile(_load_st())
    print(json.dumps(compile_result, indent=1))
    print("[INT8 quantization]")
    quant_result = benchmark_quantization(_load_st())
    print(json.dumps({k: v for k, v in quant_result.items() if k != "retrieval_quality"}, indent=1))

    results = {
        "provenance": {
            **provenance,
            "hardware": f"{cpu}, macOS {platform.mac_ver()[0]}",
            "torch_threads": THREADS,
            "logical_cpus": os.cpu_count(),
            "load_average_1_5_15_at_start": load_start,
            "load_average_1_5_15_at_end": [round(x, 2) for x in os.getloadavg()],
            "model": MODEL_NAME,
        },
        "compile": compile_result,
        "quantization": quant_result,
    }
    out_dir = PROJECT_ROOT / "results" / "data" / "article_09"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"pytorch_optimizations_{provenance['run_date']}.json"
    out.write_text(json.dumps(results, indent=2) + "\n")
    print(f"Results saved: {out}")


if __name__ == "__main__":
    main()
