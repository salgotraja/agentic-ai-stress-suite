"""Freeze the hybrid retriever's top-20 candidates for every Article 9 question.

The first reranker benchmark ranked the gold document plus 19 random
distractors, an oracle shortlist. This script records what the series'
retriever actually hands a reranker: HybridSearchPipeline (BM25 + BGE dense,
reciprocal rank fusion, SentenceSplitter 500/50) with reranking disabled and
top_k=20, the reranking_top_k default.

Every reranker and every training run then reads this one file, so all
models score identical candidates. The file stores each distinct candidate
chunk's text once, keyed by document and character offsets, with a SHA-256.

Retrieval depends on the checkout path: LlamaIndex embeds each chunk's
metadata, including its absolute file path, with the chunk text (see the
Article 1 post). Rebuilding from another directory can change the candidates;
this file is the record of the ones used.

Usage:
    uv run python benchmarks/build_article_09_candidates.py
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DOCS_DIR = PROJECT_ROOT / "datasets" / "tech_docs"
TOP_K = 20
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50
COLLECTION = "a09_hybrid_candidates"


def _chunk_corpus() -> list[Any]:
    from llama_index.core import SimpleDirectoryReader
    from llama_index.core.node_parser import SentenceSplitter

    docs = SimpleDirectoryReader(
        input_dir=str(DOCS_DIR), recursive=True, filename_as_id=True
    ).load_data()
    # Same metadata as HybridSearchPipeline.load_documents: SentenceSplitter
    # subtracts metadata length from the chunk budget, so boundaries depend on it.
    for doc in docs:
        doc.metadata["source"] = doc.id_
        doc.metadata["collection"] = COLLECTION
    splitter = SentenceSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
    return list(splitter.get_nodes_from_documents(docs))


def chunk_key(node: Any) -> str:
    """Stable chunk id: relative path, page label for PDFs, character offsets."""
    rel = str(Path(node.metadata["file_path"]).resolve().relative_to(DOCS_DIR.resolve()))
    page = node.metadata.get("page_label")
    page_part = f"@p{page}" if page is not None else ""
    return f"{rel}{page_part}#{node.start_char_idx}-{node.end_char_idx}"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def corpus_chunks() -> dict[str, dict[str, str]]:
    """Every corpus chunk keyed by chunk_key, with its document and text."""
    out: dict[str, dict[str, str]] = {}
    for node in _chunk_corpus():
        key = chunk_key(node)
        out[key] = {"key": key, "doc": key.split("#")[0].split("@")[0], "text": node.get_content()}
    return out


def load_candidates(path: Path) -> dict[str, list[dict[str, Any]]]:
    """Frozen candidates per question id, with chunk text attached and hash-checked."""
    data = json.loads(Path(path).read_text())
    texts: dict[str, str] = data["chunks"]
    out: dict[str, list[dict[str, Any]]] = {}
    for qid, ranked in data["candidates"].items():
        restored = []
        for c in ranked:
            text = texts[c["key"]]
            if _sha(text) != c["sha256"]:
                raise ValueError(f"chunk text does not match its hash for {c['key']}")
            restored.append({**c, "text": text})
        out[qid] = restored
    return out


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=PROJECT_ROOT, capture_output=True, text=True, check=False
    ).stdout.strip()


def main() -> None:
    from scripts.prepare_dl_training_data import load_questions
    from src.core.config import get_settings
    from src.rag.hybrid_search import HybridSearchPipeline

    settings = get_settings()
    settings.use_reranking = False
    pipeline = HybridSearchPipeline(collection_name=COLLECTION, settings=settings)
    documents = pipeline.load_documents(DOCS_DIR)
    pipeline.build_index(documents)

    candidates: dict[str, list[dict[str, Any]]] = {}
    chunk_texts: dict[str, str] = {}
    for item in load_questions():
        nodes = pipeline.retrieve(item["query"], top_k=TOP_K)
        candidates[item["id"]] = [
            {
                "rank": rank,
                "key": chunk_key(n.node),
                "doc": chunk_key(n.node).split("#")[0].split("@")[0],
                "rrf_score": round(float(n.score or 0.0), 6),
                "sha256": _sha(n.node.get_content()),
            }
            for rank, n in enumerate(nodes, start=1)
        ]
        for n in nodes:
            chunk_texts[chunk_key(n.node)] = n.node.get_content()

    run_date = datetime.now(UTC).date().isoformat()
    out_dir = PROJECT_ROOT / "results" / "data" / "article_09"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"candidates_{run_date}.json"
    payload = {
        "provenance": {
            "git_commit": _git("rev-parse", "HEAD"),
            "git_dirty": bool(_git("status", "--porcelain", "--untracked-files=no")),
            "run_date": run_date,
            "retriever": "src.rag.hybrid_search.HybridSearchPipeline, use_reranking=False",
            "embedding_model": "BAAI/bge-base-en-v1.5",
            "chunking": f"SentenceSplitter({CHUNK_SIZE}, {CHUNK_OVERLAP})",
            "top_k": TOP_K,
            "checkout_path": "<bench-worktree>",
            "note": "Dense retrieval embeds the absolute file path; candidates are checkout-specific",
        },
        "candidates": candidates,
        "chunks": dict(sorted(chunk_texts.items())),
    }
    out.write_text(json.dumps(payload, indent=1) + "\n")
    print(f"Wrote {out} ({len(candidates)} questions)")


if __name__ == "__main__":
    main()
