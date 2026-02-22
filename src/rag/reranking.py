"""Reranking backends for improving retrieval precision.

This module provides a pluggable reranking abstraction with two implementations:
- FlashRankReranker: Local cross-encoder, free, no API dependency
- CohereReranker: Cloud API, better accuracy, costs $1/1K queries

Teaching note: Local vs cloud reranking trade-offs
---------------------------------------------------
Reranking is a second-stage refinement after initial retrieval (BM25, dense, hybrid).
It uses cross-encoders that process [query, document] pairs jointly, producing
more accurate relevance scores than bi-encoders used in retrieval.

Why two backends:
1. FlashRank (local):
   - Free, no API key needed
   - Data stays on-premise (privacy compliance)
   - ~100-200ms latency on CPU
   - Good accuracy for most use cases (MiniLM-based models)
   - No rate limits, works offline
   - Choose when: Cost-sensitive, data privacy required, offline environments

2. Cohere Rerank API (cloud):
   - $1 per 1,000 queries (rerank-english-v3.0)
   - ~50-150ms latency (network + inference)
   - State-of-the-art accuracy on benchmarks
   - Handles 100+ languages natively
   - Choose when: Need best accuracy, multilingual, latency budget allows network call

Cost comparison at scale:
- 10K queries/day with FlashRank: $0 (CPU cost only)
- 10K queries/day with Cohere: ~$10/day = $300/month
- Break-even: If Cohere's +3-5% accuracy improvement drives measurable business value

Production recommendation:
- Start with FlashRank for development and cost-sensitive deployments
- A/B test Cohere on production traffic to measure accuracy lift
- Switch to Cohere only if accuracy improvement justifies cost
"""

from __future__ import annotations

import time
from typing import Any, Protocol, cast

from llama_index.core.schema import NodeWithScore

from src.core.config import Settings


class RerankerBackend(Protocol):
    """Protocol defining the reranker interface.

    Teaching note: Protocol vs ABC for backend abstraction
    -------------------------------------------------------
    Using Protocol (structural subtyping) instead of ABC because:
    - No inheritance required: Existing classes work if they match the signature
    - Better for testing: Minimal mocks satisfy the protocol
    - Matches Python duck-typing philosophy
    - Same pattern used in BenchmarkRunner's RAGPipeline protocol
    """

    def rerank(
        self,
        query: str,
        documents: list[NodeWithScore] | list[dict[str, Any]],
        top_k: int = 5,
    ) -> tuple[list[NodeWithScore] | list[dict[str, Any]], float]:
        """Rerank documents by query relevance.

        Args:
            query: User query
            documents: Retrieved documents (LlamaIndex or Haystack format)
            top_k: Number of top results to return

        Returns:
            Tuple of (reranked_documents, latency_ms)
        """
        ...


class FlashRankReranker:
    """Local cross-encoder reranking using FlashRank.

    Teaching note: FlashRank internals
    -----------------------------------
    FlashRank wraps ONNX-optimized cross-encoder models:
    - Model: ms-marco-MiniLM-L-12-v2 (22M params, trained on MS MARCO)
    - Inference: ONNX Runtime (CPU optimized, no GPU needed)
    - First call: Downloads model to ~/.cache/flashrank/ (~100MB)
    - Subsequent calls: Loads from cache instantly

    Cross-encoder vs bi-encoder:
    - Bi-encoder (retrieval): embed(query) cosine embed(doc) -- fast, approximate
    - Cross-encoder (reranking): score([query; doc]) -- slow, accurate
    - Cross-encoders see both query and doc together, enabling attention across them
    - Reranking improves precision but can't replace retrieval (too slow)
    """

    def __init__(
        self,
        model: str = "ms-marco-MiniLM-L-12-v2",
        settings: Settings | None = None,
    ) -> None:
        from src.core.config import get_settings

        self.settings = settings or get_settings()
        self.model = model
        self._ranker: Any = None

    def _get_ranker(self) -> Any:
        """Lazy-initialize FlashRank ranker."""
        if self._ranker is None:
            from flashrank import Ranker

            self._ranker = Ranker(model_name=self.model)
        return self._ranker

    def rerank(
        self,
        query: str,
        documents: list[NodeWithScore] | list[dict[str, Any]],
        top_k: int = 5,
    ) -> tuple[list[NodeWithScore] | list[dict[str, Any]], float]:
        """Rerank documents using local FlashRank cross-encoder.

        Args:
            query: User query
            documents: Retrieved documents (LlamaIndex NodeWithScore or Haystack dicts)
            top_k: Number of top results to return after reranking

        Returns:
            Tuple of (reranked_documents, reranking_latency_ms)
        """
        if not documents:
            return documents, 0.0

        start = time.perf_counter()

        ranker = self._get_ranker()

        is_llamaindex = isinstance(documents[0], NodeWithScore)

        # Convert to FlashRank passage format
        passages = []
        for i, doc in enumerate(documents):
            if is_llamaindex:
                text = cast("NodeWithScore", doc).node.get_content()
            else:
                text = cast("dict[str, Any]", doc).get("content", "")
            passages.append({"id": str(i), "text": text})

        from flashrank import RerankRequest

        rerank_request = RerankRequest(query=query, passages=passages)
        reranked = ranker.rerank(rerank_request)[:top_k]

        # Map back to original document format
        reranked_docs: list[Any] = []
        for passage in reranked:
            idx = int(passage["id"])
            original_doc = documents[idx]

            if is_llamaindex:
                assert isinstance(original_doc, NodeWithScore)
                reranked_docs.append(
                    NodeWithScore(
                        node=original_doc.node,
                        score=passage["score"],
                    )
                )
            else:
                assert isinstance(original_doc, dict)
                updated_doc = original_doc.copy()
                updated_doc["score"] = passage["score"]
                reranked_docs.append(updated_doc)

        end = time.perf_counter()
        latency_ms = (end - start) * 1000

        return reranked_docs, latency_ms


class CohereReranker:
    """Cloud-based reranking using Cohere Rerank API.

    Teaching note: Cohere Rerank API details
    -----------------------------------------
    Cohere's rerank endpoint is purpose-built for search result reranking:
    - Model: rerank-english-v3.0 (latest, best accuracy)
    - Pricing: $1 per 1,000 search queries (regardless of doc count per query)
    - Max documents per request: 1,000
    - Max document length: 510 tokens (truncated automatically)
    - Latency: ~50-150ms (network + server inference)

    API flow:
    1. Send query + list of documents
    2. Cohere scores each document against the query
    3. Returns documents sorted by relevance with scores [0, 1]

    Advantages over FlashRank:
    - Larger model with better accuracy (especially on complex queries)
    - Handles 100+ languages (FlashRank is English-focused)
    - No local model download or memory usage
    - Consistent latency (managed infrastructure)

    Disadvantages:
    - Costs money ($1/1K queries adds up at scale)
    - Requires network (fails if API is down or blocked)
    - Data sent to third party (not suitable for all compliance scenarios)
    - Rate limits: 10,000 requests/minute (generous but exists)
    """

    def __init__(
        self,
        model: str = "rerank-english-v3.0",
        settings: Settings | None = None,
    ) -> None:
        from src.core.config import get_settings

        self.settings = settings or get_settings()
        self.model = model
        self._client: Any = None

    def _get_client(self) -> Any:
        """Lazy-initialize Cohere client."""
        if self._client is None:
            import cohere

            api_key = self.settings.cohere_api_key
            if not api_key:
                raise ValueError(
                    "Cohere API key not configured. "
                    "Set COHERE_API_KEY in .env.local or use FlashRank backend instead."
                )
            self._client = cohere.Client(api_key=api_key)
        return self._client

    def rerank(
        self,
        query: str,
        documents: list[NodeWithScore] | list[dict[str, Any]],
        top_k: int = 5,
    ) -> tuple[list[NodeWithScore] | list[dict[str, Any]], float]:
        """Rerank documents using Cohere Rerank API.

        Args:
            query: User query
            documents: Retrieved documents (LlamaIndex NodeWithScore or Haystack dicts)
            top_k: Number of top results to return after reranking

        Returns:
            Tuple of (reranked_documents, reranking_latency_ms)

        Teaching note: Cohere rerank response format
        ---------------------------------------------
        Cohere returns a list of RerankResult objects:
        - index: Original document index
        - relevance_score: Float [0, 1] where 1 is most relevant
        - Results are pre-sorted by relevance (highest first)

        We map these back to the original document format,
        replacing the retrieval score with Cohere's relevance score.
        """
        if not documents:
            return documents, 0.0

        start = time.perf_counter()

        client = self._get_client()

        is_llamaindex = isinstance(documents[0], NodeWithScore)

        # Extract text from documents
        doc_texts = []
        for doc in documents:
            if is_llamaindex:
                node_with_score = cast("NodeWithScore", doc)
                doc_texts.append(node_with_score.node.get_content())
            else:
                doc_texts.append(cast("dict[str, Any]", doc).get("content", ""))

        # Call Cohere Rerank API
        response = client.rerank(
            query=query,
            documents=doc_texts,
            model=self.model,
            top_n=top_k,
        )

        # Map back to original document format
        reranked_docs: list[Any] = []
        for result in response.results:
            idx = result.index
            original_doc = documents[idx]

            if is_llamaindex:
                assert isinstance(original_doc, NodeWithScore)
                reranked_docs.append(
                    NodeWithScore(
                        node=original_doc.node,
                        score=result.relevance_score,
                    )
                )
            else:
                assert isinstance(original_doc, dict)
                updated_doc = original_doc.copy()
                updated_doc["score"] = result.relevance_score
                reranked_docs.append(updated_doc)

        end = time.perf_counter()
        latency_ms = (end - start) * 1000

        return reranked_docs, latency_ms


def create_reranker(
    backend: str = "flashrank",
    settings: Settings | None = None,
) -> FlashRankReranker | CohereReranker:
    """Factory function for creating reranker backends.

    Teaching note: Factory pattern for backend selection
    ----------------------------------------------------
    This factory allows configuration-driven backend selection:
    - Config: reranking_backend = "flashrank" or "cohere"
    - CLI: --reranking-backend cohere
    - Environment: RERANKING_BACKEND=cohere

    Default is FlashRank (free, no API key needed) to minimize setup friction.
    Users opt into Cohere when they need better accuracy and have an API key.

    Args:
        backend: Backend name ("flashrank" or "cohere")
        settings: Configuration settings

    Returns:
        Configured reranker instance
    """
    from src.core.config import get_settings

    settings = settings or get_settings()

    if backend == "cohere":
        return CohereReranker(settings=settings)
    elif backend == "flashrank":
        return FlashRankReranker(
            model=settings.reranking_model,
            settings=settings,
        )
    else:
        raise ValueError(
            f"Unknown reranking backend: '{backend}'. "
            f"Supported: 'flashrank' (local, free), 'cohere' (cloud, $1/1K queries)"
        )


# Backward-compatible alias for existing code that imports Reranker from hybrid_search
Reranker = FlashRankReranker
