"""Hybrid Search Pipeline combining BM25 and dense embeddings.

This module implements hybrid retrieval that combines:
- BM25: Keyword-based search (good for exact term matching, rare words)
- Dense embeddings: Semantic search (good for conceptual similarity)

Teaching note: Why hybrid search matters
-----------------------------------------
Dense-only search (Article 1) fails when:
1. Query contains rare technical terms not in training data
   Example: "MongoDB $lookup" → Dense may miss exact operator names
2. Acronyms and abbreviations differ from full forms
   Example: "JWT" query vs "JSON Web Token" in documents
3. Exact API names, error codes, version numbers
   Example: "React 18.2" → BM25 catches exact version, dense is fuzzy

BM25-only search fails when:
1. Query is semantically similar but lexically different
   Example: "How to make async calls?" vs documents saying "asynchronous requests"
2. Synonyms and paraphrasing
   Example: "delete" query vs "remove" in documents
3. Cross-lingual or translated content

Hybrid search (BM25 + dense) combines strengths:
- BM25 catches exact matches, rare terms
- Dense catches semantic similarities, paraphrases
- Reciprocal Rank Fusion (RRF) merges results robustly

Trade-offs:
- 2x retrieval cost (BM25 + dense)
- ~50-100ms extra latency
- But: +10-15% Recall improvement on technical docs

When to use hybrid vs dense-only:
- Technical docs with jargon: Hybrid wins
- Natural language FAQs: Dense often sufficient
- Code search: Hybrid essential (variable names, function signatures)
- Multilingual: Dense with multilingual embeddings
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, cast

from llama_index.core import SimpleDirectoryReader, StorageContext, VectorStoreIndex
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.schema import BaseNode, Document, NodeWithScore, TextNode
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.vector_stores.chroma import ChromaVectorStore
from rank_bm25 import BM25Okapi

from src.core.config import Settings
from src.core.llm_client import UnifiedLLMClient
from src.core.observability import traced_generation, traced_retrieval
from src.rag.reranking import FlashRankReranker, create_reranker

# Reciprocal Rank Fusion damping constant. The 60 originates from Cormack et
# al.'s 2009 paper introducing RRF; subsequent benchmarks (TREC, BEIR) found
# the merge to be insensitive to k in [10, 100]. Hoisted out of the inner
# loop so the value is searchable, swappable, and not mistaken for a magic
# number when reading _reciprocal_rank_fusion().
_RRF_K = 60


class HybridSearchPipeline:
    """
    Hybrid search combining BM25 (keyword) and dense (semantic) retrieval.

    This pipeline demonstrates the power of combining lexical and semantic search:
    - BM25: Classic IR algorithm, excels at exact term matching
    - Dense: Neural embeddings, excels at conceptual similarity
    - RRF: Reciprocal Rank Fusion for robust result merging

    Teaching note: Implementation strategy
    -------------------------------------
    We maintain TWO separate indices:
    1. BM25 index: rank_bm25 library, in-memory token lists
    2. Dense index: Chroma vector store, same as NaiveRAG

    At query time:
    1. BM25 retrieval: Tokenize query, score all docs
    2. Dense retrieval: Embed query, vector similarity search
    3. RRF merge: Combine rankings using reciprocal rank formula
    4. Return top-K from merged results

    Alternative approaches:
    - ElasticSearch: Combined BM25 + dense in one index (more complex)
    - Weaviate/Qdrant: Native hybrid search (production recommendation)
    - Haystack: High-level API for hybrid retrieval (Article 2.10)
    """

    def __init__(
        self,
        collection_name: str = "hybrid_search",
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        top_k: int = 5,
        bm25_weight: float = 0.5,
        dense_weight: float = 0.5,
        k1: float = 1.5,
        b: float = 0.75,
        settings: Settings | None = None,
    ) -> None:
        """
        Initialize Hybrid Search pipeline.

        Args:
            collection_name: Chroma collection name
            chunk_size: Tokens per chunk
            chunk_overlap: Overlapping tokens
            top_k: Number of final results to return
            bm25_weight: Weight for BM25 scores (0.0-1.0)
            dense_weight: Weight for dense scores (0.0-1.0)
            k1: BM25 term frequency saturation parameter
            b: BM25 document length normalization parameter
            settings: Configuration settings

        Teaching note: Weight tuning
        ----------------------------
        bm25_weight and dense_weight control fusion:
        - (0.5, 0.5): Equal weight, good default
        - (0.7, 0.3): Favor BM25 for technical docs with jargon
        - (0.3, 0.7): Favor dense for natural language queries
        - (1.0, 0.0): BM25 only (baseline comparison)
        - (0.0, 1.0): Dense only (equivalent to NaiveRAG)

        These weights apply during RRF, NOT to raw scores.
        RRF uses rank position, making it robust to score magnitude differences.

        BM25 hyperparameters (k1, b):
        - k1: Controls term frequency saturation (typical: 1.2-2.0)
          Higher k1 → More weight to repeated terms
        - b: Controls doc length normalization (typical: 0.75)
          b=1: Full normalization (shorter docs favored)
          b=0: No normalization (raw term freq)
        """
        from src.core.config import get_settings

        self.settings = settings or get_settings()
        self.collection_name = collection_name
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.top_k = top_k
        self.bm25_weight = bm25_weight
        self.dense_weight = dense_weight
        self.k1 = k1
        self.b = b

        # Initialize LLM client
        self.llm_client = UnifiedLLMClient(settings=self.settings)

        # Initialize embedding model (same as NaiveRAG)
        self.embed_model = HuggingFaceEmbedding(
            model_name="BAAI/bge-base-en-v1.5",
            cache_folder=str(self.settings.get_project_root() / ".cache" / "embeddings"),
        )

        # Delay Chroma client creation until index build to avoid hard
        # dependency on a running Chroma service at object construction time.
        self.chroma_client: Any | None = None

        # Initialize node parser
        self.node_parser = SentenceSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

        # Storage for indices
        self._dense_index: VectorStoreIndex | None = None
        self._bm25: BM25Okapi | None = None
        self._chunks: list[BaseNode] = []  # Store chunks for BM25 retrieval

        # Initialize reranker if enabled
        self._reranker: FlashRankReranker | None = None
        if self.settings.use_reranking:
            reranker = create_reranker(
                backend=self.settings.reranking_backend,
                settings=self.settings,
            )
            # Store as base type for the pipeline's internal use
            self._reranker = reranker  # type: ignore[assignment]

    def _parse_chroma_host(self) -> str:
        """Extract host from Chroma URL."""
        url = self.settings.chroma_url
        if "://" in url:
            url = url.split("://")[1]
        if ":" in url:
            return url.split(":")[0]
        return url

    def _parse_chroma_port(self) -> int:
        """Extract port from Chroma URL."""
        url = self.settings.chroma_url
        if "://" in url:
            url = url.split("://")[1]
        if ":" in url:
            return int(url.split(":")[1])
        return 8000

    def _get_or_create_chroma_client(self) -> Any:
        """Lazily initialize Chroma client when dense index is actually built."""
        if self.chroma_client is None:
            import chromadb

            self.chroma_client = chromadb.HttpClient(
                host=self._parse_chroma_host(),
                port=self._parse_chroma_port(),
            )
        return self.chroma_client

    def load_documents(self, directory: str | Path) -> list[Document]:
        """
        Load documents from directory.

        Args:
            directory: Path to directory containing documents

        Returns:
            List of LlamaIndex Document objects
        """
        directory = Path(directory)
        if not directory.exists():
            raise ValueError(f"Directory not found: {directory}")

        reader = SimpleDirectoryReader(
            input_dir=str(directory),
            recursive=True,
            filename_as_id=True,
        )

        documents = reader.load_data()

        for doc in documents:
            doc.metadata["source"] = doc.id_
            doc.metadata["collection"] = self.collection_name

        return documents

    def build_index(self, documents: list[Document]) -> tuple[VectorStoreIndex, BM25Okapi]:
        """
        Build both BM25 and dense indices.

        Args:
            documents: List of documents to index

        Returns:
            Tuple of (dense_index, bm25_index)

        Teaching note: Dual indexing
        -----------------------------
        We build TWO indices from the same chunked documents:

        1. Dense index (Chroma):
           - Chunks → embeddings → vector store
           - Same process as NaiveRAG

        2. BM25 index (rank_bm25):
           - Chunks → tokenized text → inverted index
           - BM25Okapi calculates IDF statistics during initialization

        Both indices operate on the SAME chunks, ensuring:
        - Results can be merged (same chunk IDs)
        - Fair comparison between methods
        - Consistent chunking strategy

        In production:
        - Parallelize embedding generation (batch processing)
        - Use persistent BM25 index (pickle or database)
        - Consider ElasticSearch for unified indexing
        """
        # Build dense index (identical to NaiveRAG)
        chroma_client = self._get_or_create_chroma_client()
        chroma_collection = chroma_client.get_or_create_collection(name=self.collection_name)
        vector_store = ChromaVectorStore(chroma_collection=chroma_collection)
        storage_context = StorageContext.from_defaults(vector_store=vector_store)

        from llama_index.core import Settings as LlamaIndexSettings

        LlamaIndexSettings.embed_model = self.embed_model
        LlamaIndexSettings.node_parser = self.node_parser

        self._dense_index = VectorStoreIndex.from_documents(
            documents,
            storage_context=storage_context,
            show_progress=True,
        )

        # Extract chunks for BM25 indexing
        # Teaching note: We need to access the chunks created by VectorStoreIndex.
        # LlamaIndex stores these in the vector store, but we need them for BM25.
        # We re-parse documents to get identical chunks.
        self._chunks = []
        for doc in documents:
            nodes = self.node_parser.get_nodes_from_documents([doc])
            self._chunks.extend(nodes)

        # Build BM25 index
        # Teaching note: BM25 requires tokenized text
        # We use simple whitespace + lowercase tokenization here
        # Production should use:
        # - Stemming (Porter stemmer)
        # - Stopword removal (language-specific)
        # - Subword tokenization for code (CamelCase splitting)
        tokenized_chunks = [self._tokenize(chunk.get_content()) for chunk in self._chunks]

        self._bm25 = BM25Okapi(tokenized_chunks, k1=self.k1, b=self.b)

        return self._dense_index, self._bm25

    def _tokenize(self, text: str) -> list[str]:
        """
        Tokenize text for BM25.

        Args:
            text: Input text

        Returns:
            List of tokens

        Teaching note: Tokenization strategy
        ------------------------------------
        This is a simple whitespace + lowercase tokenizer.
        For better performance, consider:

        1. Stemming/Lemmatization:
           - "running" → "run", "better" → "good"
           - Helps match word variations
           - NLTK Porter stemmer or spaCy lemmatizer

        2. Stop word removal:
           - Remove "the", "is", "at", etc.
           - Reduces index size, improves precision
           - But: Keep for phrases ("to be or not to be")

        3. Code-aware tokenization:
           - CamelCase: "getUserName" → ["get", "user", "name"]
           - Snake_case: "get_user_name" → ["get", "user", "name"]
           - Important for code search

        4. Subword tokenization:
           - Byte-Pair Encoding (BPE)
           - Handles rare words, typos
           - Trade-off: More complex, larger index

        For technical docs, simple tokenization often works well
        because terms are standardized (API names, keywords).
        """
        return text.lower().split()

    @traced_retrieval
    def retrieve_bm25(self, query: str, top_k: int | None = None) -> list[tuple[BaseNode, float]]:
        """
        Retrieve using BM25 keyword search.

        Args:
            query: User query
            top_k: Number of results

        Returns:
            List of (node, score) tuples

        Teaching note: BM25 scoring
        ---------------------------
        BM25 (Best Matching 25) is a probabilistic ranking function:

        score(Q, D) = Σ IDF(qi) * (f(qi, D) * (k1 + 1)) /
                      (f(qi, D) + k1 * (1 - b + b * |D| / avgdl))

        Where:
        - IDF(qi): Inverse document frequency of term qi
        - f(qi, D): Term frequency of qi in document D
        - |D|: Length of document D
        - avgdl: Average document length
        - k1, b: Tuning parameters

        Key properties:
        - Rare terms score higher (IDF)
        - Repeated terms saturate (k1 controls saturation)
        - Longer docs penalized (b controls normalization)

        BM25 excels at:
        - Exact term matching
        - Rare technical terms
        - Acronyms and abbreviations
        - Code identifiers (function names, error codes)

        BM25 fails at:
        - Synonyms and paraphrasing
        - Semantic similarity without lexical overlap
        - Multilingual queries
        """
        if self._bm25 is None or not self._chunks:
            raise ValueError("BM25 index not built. Call build_index() first.")

        k = top_k or self.top_k

        # Tokenize query
        query_tokens = self._tokenize(query)

        # Get BM25 scores for all documents
        scores = self._bm25.get_scores(query_tokens)

        # Get top-K indices
        top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:k]

        # Return nodes with scores
        results = [(self._chunks[i], float(scores[i])) for i in top_indices]

        return results

    @traced_retrieval
    def retrieve_dense(self, query: str, top_k: int | None = None) -> list[NodeWithScore]:
        """
        Retrieve using dense embedding search.

        Args:
            query: User query
            top_k: Number of results

        Returns:
            List of NodeWithScore objects

        Teaching note: Dense retrieval
        -------------------------------
        Dense retrieval uses neural embeddings to capture semantic similarity:

        1. Query embedding: Transform query to vector (768-dim for BGE-base)
        2. Similarity search: Cosine similarity in vector space
        3. Top-K selection: Return most similar documents

        Advantages:
        - Captures semantic meaning
        - Handles paraphrasing
        - Works across languages (with multilingual models)
        - No need for exact lexical match

        Disadvantages:
        - Misses rare terms not in training data
        - Can be too fuzzy (returns semantically similar but wrong docs)
        - Requires large models for good quality
        - Higher compute cost than BM25

        Typical use cases:
        - Natural language queries
        - FAQ matching
        - Semantic deduplication
        - Cross-lingual search
        """
        if self._dense_index is None:
            raise ValueError("Dense index not built. Call build_index() first.")

        k = top_k or self.top_k

        retriever = self._dense_index.as_retriever(similarity_top_k=k)
        nodes = retriever.retrieve(query)

        return nodes

    def _reciprocal_rank_fusion(
        self,
        bm25_results: list[tuple[BaseNode, float]],
        dense_results: list[NodeWithScore],
        top_k: int,
    ) -> list[NodeWithScore]:
        """
        Merge BM25 and dense results using Reciprocal Rank Fusion.

        Args:
            bm25_results: BM25 retrieval results
            dense_results: Dense retrieval results
            top_k: Number of final results

        Returns:
            Merged and reranked results

        Teaching note: Reciprocal Rank Fusion (RRF)
        --------------------------------------------
        RRF is a simple but effective rank aggregation method.

        Formula:
        RRF_score(d) = Σ weight_i / (k + rank_i(d))

        Where:
        - d: Document
        - rank_i(d): Rank of document d in retrieval method i
        - weight_i: Weight for retrieval method i
        - k: Constant (typically 60) to prevent division by zero

        Example:
        Document appears at:
        - BM25 rank 2 → score = 0.5 / (60 + 2) = 0.00806
        - Dense rank 5 → score = 0.5 / (60 + 5) = 0.00769
        - Total RRF = 0.01575

        Why RRF works:
        1. Rank-based (not score-based):
           - Robust to score magnitude differences
           - BM25 scores ~[0, 100], dense scores ~[0, 1]
           - RRF normalizes automatically

        2. Position-sensitive:
           - Top results weighted more heavily
           - Reciprocal decay (1/2, 1/3, 1/4, ...)

        3. Simple and parameter-free:
           - Only weights need tuning
           - k=60 works well in practice

        Alternatives:
        - CombSUM: Sum raw scores (requires score normalization)
        - CombMNZ: Sum scores × number of methods (favors consensus)
        - Learned fusion: Train ranker on top of retrievers (more complex)

        For most cases, RRF is the sweet spot: simple, robust, effective.
        """
        k = _RRF_K

        # Build rank maps
        bm25_ranks: dict[str, int] = {}
        for rank, (node, _score) in enumerate(bm25_results, start=1):
            node_id = node.node_id if hasattr(node, "node_id") else node.id_
            bm25_ranks[node_id] = rank

        dense_ranks: dict[str, int] = {}
        for rank, node_with_score in enumerate(dense_results, start=1):
            node_id = node_with_score.node.node_id
            dense_ranks[node_id] = rank

        # Calculate RRF scores
        rrf_scores: dict[str, float] = {}
        all_node_ids = set(bm25_ranks.keys()) | set(dense_ranks.keys())

        for node_id in all_node_ids:
            score = 0.0

            if node_id in bm25_ranks:
                score += self.bm25_weight / (k + bm25_ranks[node_id])

            if node_id in dense_ranks:
                score += self.dense_weight / (k + dense_ranks[node_id])

            rrf_scores[node_id] = score

        # Sort by RRF score
        sorted_node_ids = sorted(rrf_scores.keys(), key=lambda nid: rrf_scores[nid], reverse=True)

        # Build final result list
        # Create a map from node_id to node for easy lookup
        node_map: dict[str, TextNode | Any] = {}

        for node, _score in bm25_results:
            node_id = node.node_id if hasattr(node, "node_id") else node.id_
            node_map[node_id] = node

        for node_with_score in dense_results:
            node_id = node_with_score.node.node_id
            node_map[node_id] = node_with_score.node

        # Build merged results
        merged_results = []
        for node_id in sorted_node_ids[:top_k]:
            node = node_map[node_id]
            # Create NodeWithScore with RRF score
            node_with_score = NodeWithScore(node=node, score=rrf_scores[node_id])
            merged_results.append(node_with_score)

        return merged_results

    async def _gather_retrievals(
        self, query: str, retrieval_k: int
    ) -> tuple[list[tuple[BaseNode, float]], list[NodeWithScore]]:
        """Run BM25 and dense retrieval concurrently.

        asyncio.to_thread offloads each sync method to the default executor so
        their wait-time overlaps. BM25 is CPU-bound and contends for the GIL;
        dense retrieval is dominated by HTTP wait (Chroma + embeddings) which
        releases it. Net effect: dense I/O completes while BM25 computes,
        instead of strict sequencing.
        """
        return await asyncio.gather(
            asyncio.to_thread(self.retrieve_bm25, query, retrieval_k),
            asyncio.to_thread(self.retrieve_dense, query, retrieval_k),
        )

    @traced_retrieval
    def retrieve(self, query: str, top_k: int | None = None) -> list[NodeWithScore]:
        """
        Retrieve using hybrid search (BM25 + dense + RRF).

        Args:
            query: User query
            top_k: Number of results

        Returns:
            Merged and reranked results

        Teaching note: Hybrid retrieval flow
        ------------------------------------
        1. Parallel retrieval:
           - BM25: Keyword search (fast, in-memory)
           - Dense: Vector search (requires embedding)

        2. Result merging:
           - RRF combines rankings
           - Weights control influence of each method

        3. Performance characteristics:
           - Latency: max(BM25_time, Dense_time) + RRF_time
           - BM25: ~10-50ms (CPU, in-memory)
           - Dense: ~50-200ms (embedding + vector search)
           - RRF: ~1-5ms (simple dict operations)
           - Total: ~60-250ms (dominated by dense retrieval)

        4. When hybrid helps:
           - Technical docs: +10-15% Recall
           - Natural language: +5-10% Recall
           - Code search: +20-30% Recall

        5. Cost-benefit:
           - 2x compute (BM25 + dense)
           - ~50-100ms extra latency
           - But: Significant quality improvement

        For production:
        - Cache BM25 index (reuse across queries)
        - Batch embed queries when possible
        - Consider GPU acceleration for embeddings
        - Use approximate nearest neighbor (ANN) for large-scale dense search
        """
        k = top_k or self.top_k

        # Determine retrieval count based on reranking
        # Teaching note: Two-stage retrieval pattern
        # If reranking enabled: Retrieve top-20, rerank to top-K
        # If reranking disabled: Retrieve top-K directly
        if self._reranker is not None:
            retrieval_k = self.settings.reranking_top_k  # Default: 20
        else:
            retrieval_k = k

        # Retrieve from both indices in parallel via asyncio.gather + to_thread.
        # Dense retrieval is largely I/O (Chroma HTTP + embedding HTTP), which
        # releases the GIL; BM25 is CPU-bound and holds it. Overlap is partial
        # (dense I/O wait masks BM25 compute), so the realistic win is ~25-40%
        # latency reduction, not 2x. Synchronous callers are preserved by
        # bridging through asyncio.run(); no async caller exists today.
        bm25_results, dense_results = asyncio.run(self._gather_retrievals(query, retrieval_k * 2))

        # Merge using RRF
        merged_results = self._reciprocal_rank_fusion(
            bm25_results, dense_results, top_k=retrieval_k
        )

        # Apply reranking if enabled
        reranked: list[NodeWithScore] = merged_results
        if self._reranker is not None:
            reranked_raw, reranking_latency = self._reranker.rerank(
                query=query,
                documents=merged_results,
                top_k=k,
            )
            reranked = cast(list[NodeWithScore], reranked_raw)
            # Store latency for observability
            # Teaching note: Reranking latency is tracked separately
            # to measure cost-benefit of cross-encoder reranking
            if hasattr(self, "_last_reranking_latency_ms"):
                self._last_reranking_latency_ms = reranking_latency

        return reranked

    @traced_generation
    def generate(self, query: str, context_nodes: list[NodeWithScore]) -> str:
        """
        Generate answer from query and retrieved context.

        Args:
            query: User query
            context_nodes: Retrieved chunks

        Returns:
            Generated answer
        """
        # Format context
        context_parts = []
        for i, node in enumerate(context_nodes, 1):
            source = node.node.metadata.get("source", "Unknown")
            score = node.score or 0.0
            text = node.node.get_content()
            context_parts.append(f"[{i}] (relevance: {score:.3f}, source: {source})\n{text}")

        context = "\n\n".join(context_parts)

        # Construct prompt
        prompt = f"""You are a helpful assistant answering questions about technical documentation.

Use the following context to answer the question. If the context doesn't contain
enough information, say so clearly.

CONTEXT:
{context}

QUESTION:
{query}

ANSWER:"""

        # Generate response
        response = self.llm_client.generate(
            prompt=prompt,
            temperature=self.settings.default_llm_temperature,
            max_tokens=self.settings.default_llm_max_tokens,
            timeout=self.settings.llm_request_timeout,
        )

        return response.content

    def query(self, query_str: str, top_k: int | None = None) -> dict[str, Any]:
        """
        End-to-end hybrid RAG query.

        Args:
            query_str: User query
            top_k: Number of results

        Returns:
            Dictionary with answer, context, and metadata
        """
        context_nodes = self.retrieve(query_str, top_k=top_k)
        answer = self.generate(query_str, context_nodes)

        return {
            "answer": answer,
            "context_nodes": context_nodes,
            "metadata": {
                "query": query_str,
                "num_retrieved": len(context_nodes),
                "top_k": top_k or self.top_k,
                "collection": self.collection_name,
                "retrieval_method": "hybrid (BM25 + dense + RRF)",
                "bm25_weight": self.bm25_weight,
                "dense_weight": self.dense_weight,
            },
        }


class HaystackHybridSearchPipeline:
    """
    Haystack-based hybrid search for framework comparison.

    Teaching note: Haystack vs LlamaIndex trade-offs
    -------------------------------------------------
    Haystack is a production-focused framework with different design philosophy:

    Haystack strengths:
    - Pipeline DSL: Explicit pipeline construction with visual debugging
    - Type safety: Strong typing for pipeline components
    - Production focus: Built-in caching, batching, error handling
    - Modularity: Mix-and-match components (retrievers, rankers, generators)
    - Native hybrid: BM25Retriever + EmbeddingRetriever built-in

    Haystack weaknesses:
    - Steeper learning curve: More boilerplate, explicit pipeline setup
    - Heavier dependencies: Larger installation footprint
    - Less flexible: Pipelines are more rigid than LlamaIndex

    LlamaIndex strengths:
    - Simplicity: Less boilerplate, faster prototyping
    - Flexibility: Easy to customize and extend
    - Better docs: More examples, clearer tutorials
    - Agent-first: Better integration with ReAct, multi-agent patterns

    LlamaIndex weaknesses:
    - Less production-ready: Caching and error handling manual
    - Type safety: Weaker typing in some areas
    - Pipeline complexity: Harder to visualize and debug

    When to choose:
    - Haystack: Production services, team collaboration, complex pipelines
    - LlamaIndex: Prototyping, research, agent-heavy workflows

    Code complexity comparison (this implementation):
    - Haystack: ~150 LOC (more explicit pipeline setup)
    - LlamaIndex: ~120 LOC (more concise but less visible)

    Performance:
    - Both use same underlying libraries (sentence-transformers, rank_bm25)
    - Haystack has slight overhead from pipeline abstraction (~5-10ms)
    - LlamaIndex has slight overhead from index abstraction (~5-10ms)
    - In practice: Negligible difference (<2% latency)
    """

    def __init__(
        self,
        collection_name: str = "haystack_hybrid",
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        top_k: int = 5,
        bm25_weight: float = 0.5,
        dense_weight: float = 0.5,
        settings: Settings | None = None,
    ) -> None:
        """
        Initialize Haystack Hybrid Search pipeline.

        Args:
            collection_name: Chroma collection name
            chunk_size: Tokens per chunk
            chunk_overlap: Overlapping tokens
            top_k: Number of final results to return
            bm25_weight: Weight for BM25 scores (0.0-1.0)
            dense_weight: Weight for dense scores (0.0-1.0)
            settings: Configuration settings

        Teaching note: Haystack pipeline components
        -------------------------------------------
        Haystack uses explicit components:
        1. DocumentStore: Chroma, Elasticsearch, etc.
        2. BM25Retriever: Keyword-based retrieval
        3. EmbeddingRetriever: Dense retrieval
        4. JoinDocuments: Merge results with strategy (reciprocal_rank_fusion)
        5. PromptBuilder + Generator: Answer generation

        This is more verbose than LlamaIndex but clearer for production teams.
        """
        from src.core.config import get_settings

        self.settings = settings or get_settings()
        self.collection_name = collection_name
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.top_k = top_k
        self.bm25_weight = bm25_weight
        self.dense_weight = dense_weight

        self.llm_client = UnifiedLLMClient(settings=self.settings)

        # Haystack components will be initialized in build_index()
        from haystack.components.embedders import SentenceTransformersDocumentEmbedder
        from haystack.utils.device import ComponentDevice

        self._document_embedder = SentenceTransformersDocumentEmbedder(
            model="BAAI/bge-base-en-v1.5",
            device=ComponentDevice.from_str("cpu"),
        )
        self._document_embedder.warm_up()

        # Pipeline storage (type annotation using Any due to deferred import)
        self._retrieval_pipeline: Any = None
        self._document_store: Any = None

    def load_documents(self, directory: str | Path) -> list[dict[str, Any]]:
        """
        Load documents from directory in Haystack format.

        Args:
            directory: Path to directory containing documents

        Returns:
            List of Haystack Document dicts
        """
        from haystack import Document as HaystackDocument
        from haystack.components.converters import MarkdownToDocument
        from haystack.components.preprocessors import DocumentSplitter

        directory = Path(directory)
        if not directory.exists():
            raise ValueError(f"Directory not found: {directory}")

        # Haystack approach: Use converters and preprocessors
        converter = MarkdownToDocument()
        splitter = DocumentSplitter(
            split_by="word",
            split_length=self.chunk_size,
            split_overlap=self.chunk_overlap,
        )

        all_documents: list[HaystackDocument] = []

        # Load all markdown files
        for md_file in directory.rglob("*.md"):
            if md_file.name == "attribution.md":
                continue

            # Convert markdown to Haystack Document
            result = converter.run(sources=[md_file])
            documents = result["documents"]

            # Add metadata
            for doc in documents:
                doc.meta["source"] = str(md_file.relative_to(directory))
                doc.meta["collection"] = self.collection_name

            all_documents.extend(documents)

        # Split documents into chunks
        split_result = splitter.run(documents=all_documents)
        chunked_documents = split_result["documents"]

        return [doc.to_dict() for doc in chunked_documents]

    def build_index(self, documents: list[dict[str, Any]]) -> Any:
        """
        Build Haystack hybrid retrieval pipeline.

        Args:
            documents: List of Haystack Document dicts

        Returns:
            Configured Haystack Pipeline

        Teaching note: Haystack indexing approach
        ------------------------------------------
        Haystack separates indexing and retrieval:

        Indexing:
        1. DocumentStore initialization (Chroma)
        2. Embedding generation (SentenceTransformersDocumentEmbedder)
        3. Write to DocumentStore (handles both text and embeddings)

        Retrieval:
        1. Create BM25Retriever (points to DocumentStore)
        2. Create EmbeddingRetriever (points to DocumentStore)
        3. Create JoinDocuments for RRF merging
        4. Build Pipeline connecting components

        This separation makes it easy to:
        - Update embeddings without rebuilding index
        - Switch retrievers without code changes
        - Visualize pipeline with draw()
        """
        from haystack import Document as HaystackDocument
        from haystack import Pipeline
        from haystack.components.embedders import SentenceTransformersTextEmbedder
        from haystack.components.joiners import DocumentJoiner
        from haystack.components.retrievers import InMemoryBM25Retriever, InMemoryEmbeddingRetriever
        from haystack.document_stores.in_memory import InMemoryDocumentStore
        from haystack.utils.device import ComponentDevice

        # Initialize document store
        # Teaching note: Using InMemoryDocumentStore for simplicity
        # Production would use ChromaDocumentStore or ElasticsearchDocumentStore
        self._document_store = InMemoryDocumentStore(bm25_algorithm="BM25Okapi")

        # Convert dicts back to Haystack Documents
        haystack_docs = [HaystackDocument.from_dict(doc) for doc in documents]

        # Embed documents
        embedded_result = self._document_embedder.run(documents=haystack_docs)
        embedded_docs = embedded_result["documents"]

        # Write to document store
        self._document_store.write_documents(embedded_docs)

        # Build retrieval pipeline
        # Teaching note: Haystack uses explicit pipeline construction
        # This is more verbose but clearer for debugging
        self._retrieval_pipeline = Pipeline()

        # Add text embedder for query
        self._retrieval_pipeline.add_component(
            "text_embedder",
            SentenceTransformersTextEmbedder(
                model="BAAI/bge-base-en-v1.5",
                device=ComponentDevice.from_str("cpu"),
            ),
        )

        # Add BM25 retriever
        self._retrieval_pipeline.add_component(
            "bm25_retriever",
            InMemoryBM25Retriever(document_store=self._document_store, top_k=self.top_k * 2),
        )

        # Add embedding retriever
        self._retrieval_pipeline.add_component(
            "embedding_retriever",
            InMemoryEmbeddingRetriever(document_store=self._document_store, top_k=self.top_k * 2),
        )

        # Add document joiner for RRF
        # Teaching note: Haystack has built-in RRF support
        # weights parameter controls BM25 vs dense influence
        self._retrieval_pipeline.add_component(
            "joiner",
            DocumentJoiner(
                join_mode="reciprocal_rank_fusion",
                weights=[self.bm25_weight, self.dense_weight],
                top_k=self.top_k,
            ),
        )

        # Connect pipeline components
        # Teaching note: Explicit connections make data flow visible
        # This helps with debugging and understanding pipeline behavior
        self._retrieval_pipeline.connect(
            "text_embedder.embedding", "embedding_retriever.query_embedding"
        )
        self._retrieval_pipeline.connect("bm25_retriever.documents", "joiner.documents")
        self._retrieval_pipeline.connect("embedding_retriever.documents", "joiner.documents")

        return self._retrieval_pipeline

    @traced_retrieval
    def retrieve(self, query: str, top_k: int | None = None) -> list[dict[str, Any]]:
        """
        Retrieve using Haystack hybrid search.

        Args:
            query: User query
            top_k: Number of results (overrides pipeline default)

        Returns:
            List of Document dicts with scores

        Teaching note: Haystack retrieval execution
        -------------------------------------------
        Haystack uses run() method with inputs dict:
        - text_embedder expects "text"
        - bm25_retriever expects "query"
        - Pipeline automatically routes inputs to components

        This is different from LlamaIndex's retrieve() method
        which takes query directly.

        Haystack advantage:
        - Clear input/output contracts
        - Easy to trace data flow
        - Type-safe with IDE support

        Haystack disadvantage:
        - More verbose
        - Requires understanding pipeline structure
        """
        if self._retrieval_pipeline is None:
            raise ValueError("Pipeline not built. Call build_index() first.")

        k = top_k or self.top_k

        # Update joiner top_k if needed
        if k != self.top_k:
            self._retrieval_pipeline.get_component("joiner").top_k = k

        # Run pipeline
        # Teaching note: Haystack requires explicit input mapping
        result = self._retrieval_pipeline.run(
            {
                "text_embedder": {"text": query},
                "bm25_retriever": {"query": query},
            }
        )

        # Extract documents from joiner output
        documents = result["joiner"]["documents"]

        return [doc.to_dict() for doc in documents]

    @traced_generation
    def generate(self, query: str, context_docs: list[dict[str, Any]]) -> str:
        """
        Generate answer from query and retrieved context.

        Args:
            query: User query
            context_docs: Retrieved document dicts

        Returns:
            Generated answer
        """
        from haystack import Document as HaystackDocument

        # Convert dicts to Haystack Documents
        docs = [HaystackDocument.from_dict(doc) for doc in context_docs]

        # Format context
        context_parts = []
        for i, doc in enumerate(docs, 1):
            source = doc.meta.get("source", "Unknown")
            score = doc.score or 0.0
            text = doc.content
            context_parts.append(f"[{i}] (relevance: {score:.3f}, source: {source})\n{text}")

        context = "\n\n".join(context_parts)

        # Construct prompt
        prompt = f"""You are a helpful assistant answering questions about technical documentation.

Use the following context to answer the question. If the context doesn't contain
enough information, say so clearly.

CONTEXT:
{context}

QUESTION:
{query}

ANSWER:"""

        # Generate response using UnifiedLLMClient
        response = self.llm_client.generate(
            prompt=prompt,
            temperature=self.settings.default_llm_temperature,
            max_tokens=self.settings.default_llm_max_tokens,
            timeout=self.settings.llm_request_timeout,
        )

        return response.content

    def query(self, query_str: str, top_k: int | None = None) -> dict[str, Any]:
        """
        End-to-end Haystack hybrid RAG query.

        Args:
            query_str: User query
            top_k: Number of results

        Returns:
            Dictionary with answer, context, and metadata
        """
        context_docs = self.retrieve(query_str, top_k=top_k)
        answer = self.generate(query_str, context_docs)

        return {
            "answer": answer,
            "context_docs": context_docs,
            "metadata": {
                "query": query_str,
                "num_retrieved": len(context_docs),
                "top_k": top_k or self.top_k,
                "collection": self.collection_name,
                "retrieval_method": "haystack hybrid (BM25 + dense + RRF)",
                "framework": "Haystack",
                "bm25_weight": self.bm25_weight,
                "dense_weight": self.dense_weight,
            },
        }


# Backward-compatible alias: Reranker was originally defined inline here.
# Now lives in src.rag.reranking. Import it here so existing code still works.
from src.rag.reranking import FlashRankReranker as Reranker  # noqa: E402, F811

__all__ = [
    "HybridSearchPipeline",
    "HaystackHybridSearchPipeline",
    "Reranker",
]
