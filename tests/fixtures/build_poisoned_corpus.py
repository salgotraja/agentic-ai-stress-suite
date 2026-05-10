"""Build the in-process poisoned-corpus index for Article 7's chaos benchmark.

Why a builder script and not a checked-in pre-embedded fixture:
    Embedding vectors are pinned to the model. If the project switches
    BGE versions, a binary fixture would silently retrieve nonsense
    rather than fail loudly. Building at test time also keeps the
    repo lean and forces the build to fail when the embedding stack
    breaks.

Why an in-process numpy index instead of Chroma server:
    The chaos benchmark needs to run in CI without external services
    (the rest of the A7 benchmark already runs offline). A 13-document
    corpus (5 adversarial + 8 benign) is small enough that cosine
    similarity over a numpy array is fast and dependency-free.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from collections.abc import Callable


_FIXTURE_DIR = Path(__file__).parent / "poisoned_corpus"
_ADVERSARIAL_DIR = _FIXTURE_DIR / "adversarial"
_BENIGN_DIR = _FIXTURE_DIR / "benign"
_PROBES_PATH = _FIXTURE_DIR / "probes.json"

# A small chunk size keeps the marker phrase (which fits in one chunk)
# concentrated in a single retrievable unit. With 800-char chunks the
# 5 adversarial docs each produce 1-2 chunks; benign docs produce more.
_CHUNK_SIZE_CHARS = 800
_CHUNK_OVERLAP_CHARS = 100


@dataclass(frozen=True)
class Chunk:
    """One indexable unit of the corpus."""

    doc_id: str
    source: str
    text: str
    is_adversarial: bool


@dataclass(frozen=True)
class Probe:
    """One probe query and its expected adversarial signature."""

    id: str
    query: str
    adversarial_doc: str
    marker: str


@dataclass(frozen=True)
class PoisonedCorpus:
    """Built corpus + retrieval handle + probe set.

    `retrieve(query, top_k)` returns the top-k Chunks by cosine similarity.
    `probes` is the list of 5 probe queries with expected markers.
    `condition` is "clean" (benign only) or "poisoned" (benign + adversarial).
    """

    chunks: list[Chunk]
    embeddings: np.ndarray
    probes: list[Probe]
    condition: str
    embed_fn: Callable[[str], list[float]]

    def retrieve(self, query: str, top_k: int = 3) -> list[Chunk]:
        q_vec = np.asarray(self.embed_fn(query), dtype=np.float32)
        q_norm = q_vec / (np.linalg.norm(q_vec) + 1e-12)
        doc_norms = np.linalg.norm(self.embeddings, axis=1, keepdims=True) + 1e-12
        doc_unit = self.embeddings / doc_norms
        scores = doc_unit @ q_norm
        order = np.argsort(-scores)[:top_k]
        return [self.chunks[i] for i in order]


def _split_into_chunks(text: str) -> list[str]:
    """Naive char-window chunker; keeps the builder dependency-free.

    Article-1's pipeline uses LlamaIndex's SimpleNodeParser, but pulling that
    in here would force the heavier import path on the chaos benchmark when
    its only need is "embed N short markdown files". The marker phrases all
    fit comfortably inside one window, which is the only correctness
    requirement.
    """
    text = text.strip()
    if len(text) <= _CHUNK_SIZE_CHARS:
        return [text]
    chunks: list[str] = []
    step = _CHUNK_SIZE_CHARS - _CHUNK_OVERLAP_CHARS
    for start in range(0, len(text), step):
        end = start + _CHUNK_SIZE_CHARS
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
    return chunks


def _load_chunks(directory: Path, is_adversarial: bool) -> list[Chunk]:
    out: list[Chunk] = []
    for md_path in sorted(directory.glob("*.md")):
        body = md_path.read_text(encoding="utf-8")
        for chunk_text in _split_into_chunks(body):
            out.append(
                Chunk(
                    doc_id=md_path.name,
                    source=str(md_path.relative_to(_FIXTURE_DIR)),
                    text=chunk_text,
                    is_adversarial=is_adversarial,
                )
            )
    return out


def _load_probes() -> list[Probe]:
    raw = json.loads(_PROBES_PATH.read_text(encoding="utf-8"))
    return [
        Probe(
            id=p["id"],
            query=p["query"],
            adversarial_doc=p["adversarial_doc"],
            marker=p["marker"],
        )
        for p in raw["probes"]
    ]


def _build_embed_fn() -> Callable[[str], list[float]]:
    """Same embedding stack as run_article_06.py:103-121.

    HuggingFaceEmbedding caches the model under .cache/embeddings/ so
    subsequent runs skip the download. Switching to a different BGE
    revision invalidates the cache automatically because the cache path
    incorporates the model name.
    """
    from llama_index.embeddings.huggingface import HuggingFaceEmbedding

    project_root = Path(__file__).parent.parent.parent
    embed_model = HuggingFaceEmbedding(
        model_name="BAAI/bge-base-en-v1.5",
        cache_folder=str(project_root / ".cache" / "embeddings"),
    )

    def embed(text: str) -> list[float]:
        return embed_model.get_text_embedding(text)

    return embed


def _embed_chunks(chunks: list[Chunk], embed_fn: Callable[[str], list[float]]) -> np.ndarray:
    if not chunks:
        return np.zeros((0, 0), dtype=np.float32)
    vectors = [embed_fn(c.text) for c in chunks]
    return np.asarray(vectors, dtype=np.float32)


def build_corpus(condition: str) -> PoisonedCorpus:
    """Build either the clean or poisoned corpus.

    "clean" indexes only the benign tech_docs samples; the adversarial files
    on disk are ignored. This is the baseline condition.

    "poisoned" indexes both directories. Every probe query is targeted to
    pull its matching adversarial doc into top-k; whether the rails catch it
    is what the benchmark measures.
    """
    if condition not in ("clean", "poisoned"):
        raise ValueError(f"condition must be 'clean' or 'poisoned'; got {condition!r}")

    benign_chunks = _load_chunks(_BENIGN_DIR, is_adversarial=False)
    if condition == "poisoned":
        adversarial_chunks = _load_chunks(_ADVERSARIAL_DIR, is_adversarial=True)
        chunks = benign_chunks + adversarial_chunks
    else:
        chunks = benign_chunks

    embed_fn = _build_embed_fn()
    embeddings = _embed_chunks(chunks, embed_fn)
    probes = _load_probes()
    return PoisonedCorpus(
        chunks=chunks,
        embeddings=embeddings,
        probes=probes,
        condition=condition,
        embed_fn=embed_fn,
    )


def marker_in_text(marker: str, text: str) -> bool:
    """Case-insensitive whitespace-tolerant substring match.

    LLM outputs frequently re-flow whitespace (collapse newlines, alter
    indentation), so an exact-string match misses legitimate quotations.
    This helper normalises both sides to a single-space form before
    comparison.
    """
    norm = re.compile(r"\s+")
    return norm.sub(" ", marker).strip().lower() in norm.sub(" ", text).strip().lower()


__all__ = [
    "Chunk",
    "PoisonedCorpus",
    "Probe",
    "build_corpus",
    "marker_in_text",
]


if __name__ == "__main__":
    # Smoke build: verify both conditions construct without errors.
    for cond in ("clean", "poisoned"):
        corpus = build_corpus(cond)
        print(f"[{cond}] chunks={len(corpus.chunks)}  emb_shape={corpus.embeddings.shape}")
        for probe in corpus.probes[:1]:
            top = corpus.retrieve(probe.query, top_k=3)
            print(f"  probe '{probe.id}' top-1 doc={top[0].doc_id} adv={top[0].is_adversarial}")
