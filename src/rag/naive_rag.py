"""Naive RAG Pipeline using LlamaIndex.

This module implements a basic Retrieval-Augmented Generation (RAG) pipeline
demonstrating the core RAG pattern: embed → store → retrieve → generate.

Teaching note: This is the baseline implementation for Article 1. Advanced techniques
(HyDE, query decomposition, graph RAG) build on this foundation. Understanding
this simple pipeline's strengths and weaknesses is critical before optimization.

RAG Pipeline Stages:
1. Document Loading: Read markdown files from disk
2. Chunking: Split into 500-token chunks with 50-token overlap
3. Embedding: Generate vectors using BGE-base-en-v1.5 (local, Metal-accelerated)
4. Storage: Persist embeddings in Chroma vector database
5. Retrieval: Top-K semantic search (K=5 default)
6. Generation: Synthesize answer using Groq Llama-3-8B

Why these choices:
- BGE-base-en-v1.5: Better MTEB scores (~63) than all-MiniLM-L6-v2 (~56)
- Chroma: Simple local vector store, good for development
- Groq Llama-3-8B: Cheap cloud LLM ($0.05/1M tokens), fast iteration
- 500 tokens/chunk: Balances context vs retrieval precision for tech docs
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from llama_index.core import SimpleDirectoryReader, StorageContext, VectorStoreIndex
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.schema import Document, NodeWithScore
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.vector_stores.chroma import ChromaVectorStore

from src.core.config import Settings
from src.core.llm_client import UnifiedLLMClient
from src.core.observability import traced_generation, traced_retrieval


class NaiveRAGPipeline:
    """
    Naive RAG implementation using LlamaIndex.

    This pipeline demonstrates the basic RAG pattern without advanced optimizations.
    It's intentionally simple to serve as a baseline for comparison with advanced
    techniques in subsequent articles.

    Limitations (addressed in advanced_rag.py):
    - No query rewriting or expansion
    - No hybrid search (dense-only, no BM25)
    - No reranking of retrieved chunks
    - No parent document retrieval (returns only chunks)
    - Fixed chunking strategy (no semantic boundaries)

    Teaching note: These limitations are not bugs - they're deliberate choices
    to establish a baseline. Measuring the impact of each advanced technique
    requires a simple, well-understood starting point.
    """

    def __init__(
        self,
        collection_name: str = "naive_rag",
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        top_k: int = 5,
        settings: Settings | None = None,
    ) -> None:
        """
        Initialize the Naive RAG pipeline.

        Args:
            collection_name: Chroma collection name for vector storage
            chunk_size: Token count per chunk (default: 500)
            chunk_overlap: Overlapping tokens between chunks (default: 50)
            top_k: Number of chunks to retrieve (default: 5)
            settings: Configuration settings (uses get_settings() if None)

        Teaching note: Chunk size is a critical hyperparameter:
        - Too small: Fragments lose context, retrieval becomes noisy
        - Too large: Irrelevant context dilutes relevant info, hits token limits
        - 500 tokens ≈ 375 words ≈ 1-2 paragraphs for tech docs
        - Overlap prevents information loss at chunk boundaries
        """
        from src.core.config import get_settings

        self.settings = settings or get_settings()
        self.collection_name = collection_name
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.top_k = top_k

        # Initialize LLM client for generation
        self.llm_client = UnifiedLLMClient(settings=self.settings)

        # Initialize embedding model (BGE-base-en-v1.5 via HuggingFace)
        # Teaching note: We use HuggingFace locally instead of text-embeddings-inference
        # for simplicity in this spike. Production should use text-embeddings-inference
        # server for GPU acceleration (see .env.local EMBEDDINGS_URL).
        self.embed_model = HuggingFaceEmbedding(
            model_name="BAAI/bge-base-en-v1.5",
            cache_folder=str(self.settings.get_project_root() / ".cache" / "embeddings"),
        )

        # Initialize Chroma vector store
        try:
            import chromadb
        except ImportError:
            raise ImportError(
                "chromadb not installed. Run: uv add chromadb or pip install chromadb"
            )

        # Teaching note: Chroma client setup
        # - HTTP client connects to Chroma server (configured via CHROMA_URL)
        # - Persistent client would use local disk storage
        # - Cloud deployment would use Chroma cloud or migrate to Qdrant/Weaviate
        self.chroma_client = chromadb.HttpClient(
            host=self._parse_chroma_host(),
            port=self._parse_chroma_port(),
        )

        # Initialize node parser for chunking
        # Teaching note: SentenceSplitter respects sentence boundaries when possible
        # while targeting the specified chunk_size. This is better than naive splitting
        # on character count, but not as sophisticated as semantic chunking.
        self.node_parser = SentenceSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

        # Vector store index (lazy initialized on first load/query)
        self._index: VectorStoreIndex | None = None

    def _parse_chroma_host(self) -> str:
        """Extract host from Chroma URL."""
        url = self.settings.chroma_url
        # Remove http:// or https://
        if "://" in url:
            url = url.split("://")[1]
        # Split host:port
        if ":" in url:
            return url.split(":")[0]
        return url

    def _parse_chroma_port(self) -> int:
        """Extract port from Chroma URL."""
        url = self.settings.chroma_url
        # Remove http:// or https://
        if "://" in url:
            url = url.split("://")[1]
        # Split host:port
        if ":" in url:
            return int(url.split(":")[1])
        return 8000  # Default Chroma port

    def load_documents(self, directory: str | Path) -> list[Document]:
        """
        Load documents from a directory (supports markdown, txt, pdf).

        Args:
            directory: Path to directory containing documents

        Returns:
            List of LlamaIndex Document objects

        Teaching note: LlamaIndex's SimpleDirectoryReader handles multiple formats
        automatically. In production, you'd want more control over parsing
        (e.g., custom markdown parsing to preserve code blocks, tables).
        """
        directory = Path(directory)
        if not directory.exists():
            raise ValueError(f"Directory not found: {directory}")

        reader = SimpleDirectoryReader(
            input_dir=str(directory),
            recursive=True,
            filename_as_id=True,  # Use filename as document ID
        )

        documents = reader.load_data()

        # Add metadata for traceability
        for doc in documents:
            doc.metadata["source"] = doc.id_
            doc.metadata["collection"] = self.collection_name

        return documents

    def build_index(self, documents: list[Document]) -> VectorStoreIndex:
        """
        Build vector index from documents.

        Args:
            documents: List of documents to index

        Returns:
            VectorStoreIndex ready for querying

        Teaching note: This method combines chunking, embedding, and storage:
        1. SentenceSplitter chunks documents into nodes
        2. HuggingFaceEmbedding generates BGE embeddings for each chunk
        3. ChromaVectorStore persists embeddings to Chroma server

        In production, you'd want to:
        - Batch embeddings for efficiency
        - Add progress tracking for large corpora
        - Handle embedding errors gracefully
        - Cache embeddings to avoid recomputation
        """
        # Get or create Chroma collection
        chroma_collection = self.chroma_client.get_or_create_collection(name=self.collection_name)

        # Create vector store
        vector_store = ChromaVectorStore(chroma_collection=chroma_collection)

        # Create storage context
        storage_context = StorageContext.from_defaults(vector_store=vector_store)

        # Create service context with our embedding model
        # Teaching note: ServiceContext is deprecated in newer LlamaIndex versions
        # but still used in 0.10.x. Newer versions use Settings.embed_model directly.
        from llama_index.core import Settings as LlamaIndexSettings

        LlamaIndexSettings.embed_model = self.embed_model
        LlamaIndexSettings.node_parser = self.node_parser

        # Build index
        # Teaching note: VectorStoreIndex.from_documents() performs:
        # 1. Parse documents into nodes (chunks)
        # 2. Generate embeddings for each node
        # 3. Store embeddings in vector store
        self._index = VectorStoreIndex.from_documents(
            documents,
            storage_context=storage_context,
            show_progress=True,
        )

        return self._index

    @traced_retrieval
    def retrieve(self, query: str, top_k: int | None = None) -> list[NodeWithScore]:
        """
        Retrieve relevant chunks for a query.

        Args:
            query: User query string
            top_k: Number of chunks to retrieve (uses self.top_k if None)

        Returns:
            List of nodes with relevance scores

        Teaching note: Retrieval is the core of RAG. This naive implementation:
        - Embeds the query using the same model as documents (BGE-base-en-v1.5)
        - Performs cosine similarity search in Chroma
        - Returns top-K most similar chunks

        Limitations:
        - Query and documents must have similar vocabulary (no query expansion)
        - Pure semantic search (no keyword fallback for rare terms)
        - No reranking to improve precision
        - No parent document retrieval (context limited to chunk)

        The @traced_retrieval decorator captures:
        - Query text
        - Number of results
        - Retrieval latency
        - Result relevance scores
        """
        if self._index is None:
            raise ValueError("Index not built. Call build_index() first.")

        k = top_k or self.top_k

        # Get retriever from index
        retriever = self._index.as_retriever(similarity_top_k=k)

        # Retrieve nodes
        nodes = retriever.retrieve(query)

        return nodes

    @traced_generation
    def generate(self, query: str, context_nodes: list[NodeWithScore]) -> str:
        """
        Generate answer from query and retrieved context.

        Args:
            query: User query string
            context_nodes: Retrieved chunks with scores

        Returns:
            Generated answer string

        Teaching note: This method constructs a prompt with:
        - System instruction (answer based on context)
        - Retrieved context chunks
        - User query

        The prompt follows the "context + question" pattern common in RAG.
        Advanced techniques (Article 2) explore:
        - Chain-of-thought prompting
        - Self-consistency (multiple generations, voting)
        - Citation generation (link answers to source chunks)

        The @traced_generation decorator captures:
        - Full prompt sent to LLM
        - Generated response
        - Token counts (prompt + completion)
        - Generation latency
        - Cost in USD
        """
        # Format context from nodes
        context_parts = []
        for i, node in enumerate(context_nodes, 1):
            source = node.node.metadata.get("source", "Unknown")
            score = node.score or 0.0
            # Get text content from node
            text = node.node.get_content()
            context_parts.append(f"[{i}] (relevance: {score:.3f}, source: {source})\n{text}")

        context = "\n\n".join(context_parts)

        # Construct prompt
        # Teaching note: This prompt template is intentionally simple.
        # Advanced prompting techniques (few-shot examples, chain-of-thought)
        # can significantly improve answer quality but add complexity.
        prompt = f"""You are a helpful assistant answering questions about technical documentation.

Use the following context to answer the question. If the context doesn't contain
enough information, say so clearly.

CONTEXT:
{context}

QUESTION:
{query}

ANSWER:"""

        # Generate response using Groq
        # Teaching note: We use the UnifiedLLMClient which handles:
        # - Fallback chain (Groq-8B → Groq-70B → DeepSeek → Claude → Gemini → GPT-4)
        # - Retry logic (exponential backoff)
        # - Token counting and cost tracking
        # - Timeout handling
        response = self.llm_client.generate(
            prompt=prompt,
            temperature=self.settings.default_llm_temperature,
            max_tokens=self.settings.default_llm_max_tokens,
            timeout=self.settings.llm_request_timeout,
        )

        return response.content

    def query(self, query_str: str, top_k: int | None = None) -> dict[str, Any]:
        """
        End-to-end RAG query: retrieve + generate.

        Args:
            query_str: User query string
            top_k: Number of chunks to retrieve (uses self.top_k if None)

        Returns:
            Dictionary with:
                - answer: Generated response
                - context_nodes: Retrieved chunks
                - metadata: Query metadata (latency, costs, etc.)

        Teaching note: This is the main entry point for RAG queries.
        It combines retrieve() and generate() into a single call.

        In production, you'd want to add:
        - Query validation (empty, too long, malicious)
        - Rate limiting per user
        - Result caching (semantic cache in Article 6)
        - Streaming responses for better UX
        - Error handling with fallbacks
        """
        # Retrieve relevant chunks
        context_nodes = self.retrieve(query_str, top_k=top_k)

        # Generate answer
        answer = self.generate(query_str, context_nodes)

        return {
            "answer": answer,
            "context_nodes": context_nodes,
            "metadata": {
                "query": query_str,
                "num_retrieved": len(context_nodes),
                "top_k": top_k or self.top_k,
                "collection": self.collection_name,
            },
        }
