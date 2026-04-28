"""Advanced RAG pipeline with state-of-the-art retrieval techniques.

This module implements advanced RAG techniques beyond naive retrieval:
- HyDE (Hypothetical Document Embeddings): Generate hypothetical answer, embed that
- Query Decomposition: Break complex queries into sub-queries
- Multi-query retrieval: Generate multiple query variations

Teaching note: Advanced RAG techniques address specific failure modes of naive RAG:

1. Vocabulary mismatch: Query uses different words than documents
   - Example: User asks "How do I make Spring async?" but docs say "asynchronous processing"
   - Solution: HyDE generates hypothetical answer in document vocabulary

2. Complex multi-hop queries: Single query requires multiple retrieval steps
   - Example: "Compare FastAPI and Spring async patterns"
   - Solution: Query decomposition breaks into sub-queries

3. Query ambiguity: Single query can be interpreted multiple ways
   - Example: "React hooks" (JavaScript or Java reactive programming?)
   - Solution: Multi-query generates variations to cover interpretations

Trade-offs:
- HyDE adds 1 extra LLM call (200-500ms latency + $0.0001-0.001 cost)
- Query decomposition adds N LLM calls for N sub-queries
- Benefit: 10-30% improvement in retrieval accuracy for complex queries
- Cost: Increased latency and API costs

When to use:
- HyDE: Technical documentation with specific terminology
- Query decomposition: Multi-part questions requiring multiple facts
- Multi-query: Ambiguous queries in broad domains
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from llama_index.core import Document, VectorStoreIndex
from llama_index.core.embeddings import BaseEmbedding
from llama_index.core.node_parser import SentenceSplitter

from src.core.llm_client import UnifiedLLMClient
from src.core.observability import traced_generation, traced_retrieval

logger = logging.getLogger(__name__)


class AdvancedRAGPipeline:
    """
    Advanced RAG pipeline with HyDE and query decomposition.

    This pipeline extends naive RAG with advanced retrieval techniques:
    - HyDE: Generate hypothetical document, embed that instead of query
    - Query decomposition: Break complex query into sub-queries (Phase 2, Task 2.2)

    Teaching note: This is a superset of NaiveRAGPipeline. It can operate
    in naive mode (use_hyde=False) or advanced mode (use_hyde=True).

    The pipeline follows this flow:
    1. Load documents (same as naive)
    2. Build vector index (same as naive)
    3. Query processing:
       - If use_hyde=False: embed query directly (naive)
       - If use_hyde=True: generate hypothetical answer, embed that (HyDE)
    4. Retrieve top-K documents
    5. Generate final answer using LLM

    Architecture:
        User Query
            |
            v
        [HyDE Layer] (optional)
            |
            v
        Embedding
            |
            v
        Vector Search
            |
            v
        Top-K Docs
            |
            v
        LLM Generation
            |
            v
        Final Answer

    Args:
        embedding_model: Embedding model name (default: BGE-base-en-v1.5)
        llm_client: LLM client for generation and HyDE/decomposition
        chunk_size: Document chunk size in tokens
        chunk_overlap: Overlap between chunks
        use_hyde: Enable HyDE (hypothetical document embeddings)
        use_decomposition: Enable query decomposition for complex queries
    """

    def __init__(
        self,
        embedding_model: str = "BAAI/bge-base-en-v1.5",
        llm_client: UnifiedLLMClient | None = None,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        use_hyde: bool = False,
        use_decomposition: bool = False,
    ) -> None:
        """Initialize advanced RAG pipeline."""
        self.embedding_model_name = embedding_model
        self.llm_client = llm_client or UnifiedLLMClient()
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.use_hyde = use_hyde
        self.use_decomposition = use_decomposition

        # Vector index (built during indexing)
        self.index: VectorStoreIndex | None = None

        # Node parser for chunking
        self.node_parser = SentenceSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

    def load_documents(self, docs_dir: str) -> list[Document]:
        """
        Load documents from a directory.

        Args:
            docs_dir: Path to directory containing markdown files

        Returns:
            List of Document objects

        Teaching note: Reuses naive RAG document loading.
        For Phase 2, we'll add PDF support with table extraction.
        """
        from pathlib import Path

        from llama_index.core import SimpleDirectoryReader

        docs_path = Path(docs_dir)
        if not docs_path.exists():
            raise ValueError(f"Documents directory not found: {docs_dir}")

        reader = SimpleDirectoryReader(
            input_dir=str(docs_path),
            required_exts=[".md"],
            recursive=True,
        )

        documents = reader.load_data()
        return documents

    def build_index(
        self,
        documents: list[Document],
        embed_model: BaseEmbedding,
    ) -> None:
        """
        Build vector index from documents.

        Args:
            documents: List of documents to index
            embed_model: Embedding model to use

        Teaching note: Same as naive RAG indexing.
        We build the index once, then use it for both naive and HyDE retrieval.
        HyDE only changes the query embedding, not document embeddings.
        """
        nodes = self.node_parser.get_nodes_from_documents(documents)

        self.index = VectorStoreIndex(
            nodes=nodes,
            embed_model=embed_model,
            show_progress=True,
        )

    @traced_generation
    def _generate_hypothetical_document(
        self,
        query: str,
        correlation_id: str | None = None,
    ) -> str:
        """
        Generate hypothetical document for HyDE.

        Teaching note: This is the core of HyDE. Instead of embedding the query,
        we ask the LLM to generate a hypothetical answer/document that would
        answer the query. Then we embed that hypothetical document.

        Why this works:
        - User queries are often short, informal: "how to make spring async?"
        - Documents are longer, formal: "Spring Framework supports asynchronous processing..."
        - Queries and documents live in different embedding spaces
        - Hypothetical documents bridge this gap

        Prompt engineering considerations:
        - We ask for a technical document snippet, not a conversational answer
        - We limit length (2-3 sentences) to avoid noise
        - We don't ask the LLM to be accurate - we just need document-like text

        Trade-off: This adds ~200-500ms latency and $0.0001-0.001 cost per query.

        Args:
            query: User query
            correlation_id: Optional trace correlation ID

        Returns:
            Hypothetical document text
        """
        prompt = f"""You are generating a hypothetical technical document snippet.

Query: {query}

Write 2-3 sentences of technical documentation that would answer this query.
Use formal technical language and specific terminology.
Do not say "this document explains" - just write the content directly.

Hypothetical document:"""

        response = self.llm_client.generate(
            prompt=prompt,
            temperature=0.7,  # Some creativity for vocabulary variation
            max_tokens=150,  # Short snippet
        )

        hypothetical_doc = response.content.strip()

        # Teaching note: Log for debugging
        # In production, you'd use structured logging
        # print(f"[HyDE] Query: {query}")
        # print(f"[HyDE] Hypothetical doc: {hypothetical_doc}")

        return hypothetical_doc

    @traced_generation
    def _decompose_query(
        self,
        query: str,
        correlation_id: str | None = None,
    ) -> list[str]:
        """
        Decompose complex query into sub-queries.

        Teaching note: Query decomposition helps with multi-hop queries:
        - "Compare FastAPI and Spring async" →
          ["What is FastAPI async?", "What is Spring async?"]
        - "How does React hooks work in TypeScript?" →
          ["What are React hooks?", "How to use TypeScript with React?"]

        Why this works:
        - Complex queries often need multiple facts
        - Single retrieval may miss relevant docs
        - Sub-queries target specific aspects
        - Parallel retrieval is faster than sequential

        Prompt engineering:
        - Ask for 2-4 sub-queries (not too many)
        - Each should be self-contained
        - Should cover different aspects of original query

        Trade-off: Adds 1 LLM call + N parallel retrievals
        - Cost: ~$0.0001 for decomposition + N retrievals
        - Latency: ~300ms LLM + parallel retrieval (faster than sequential)
        - Benefit: 15-40% better recall for complex queries

        Args:
            query: Complex user query
            correlation_id: Optional trace correlation ID

        Returns:
            List of 2-4 sub-queries
        """
        prompt = f"""Break down this complex query into 2-4 simpler sub-queries.

Query: {query}

Rules:
- Each sub-query should be self-contained and answerable independently
- Cover different aspects of the original query
- Keep sub-queries concise (1 sentence each)
- Return as numbered list

Sub-queries:"""

        response = self.llm_client.generate(
            prompt=prompt,
            temperature=0.3,  # Low creativity for consistent decomposition
            max_tokens=200,
        )

        # Parse sub-queries from response
        sub_queries = []
        for line in response.content.strip().split("\n"):
            line = line.strip()
            # Remove numbering (1., 2., -, etc.)
            if line and (line[0].isdigit() or line.startswith("-")):
                # Strip numbering
                query_text = line.lstrip("0123456789.-) ").strip()
                if query_text:
                    sub_queries.append(query_text)

        # Fallback: if parsing failed, use original query
        if not sub_queries:
            sub_queries = [query]

        # Teaching note: Log for debugging
        # print(f"[Decomposition] Original: {query}")
        # print(f"[Decomposition] Sub-queries: {sub_queries}")

        return sub_queries

    def _retrieve_single(
        self,
        query: str,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """
        Retrieve documents for a single query (internal helper).

        Teaching note: This is the core retrieval logic, extracted for reuse
        in both single-query and multi-query (decomposition) scenarios.

        Args:
            query: Query string (may be transformed by HyDE)
            top_k: Number of documents to retrieve

        Returns:
            List of retrieved document nodes with scores
        """
        if self.index is None:
            raise ValueError("Index not built. Call build_index() first.")

        # Retrieve using query engine
        query_engine = self.index.as_query_engine(
            similarity_top_k=top_k,
            response_mode="no_text",
        )

        response = query_engine.query(query)

        # Extract nodes and scores
        retrieved_nodes = []
        if hasattr(response, "source_nodes"):
            for node in response.source_nodes:
                retrieved_nodes.append(
                    {
                        "text": node.node.get_content(),
                        "score": node.score if hasattr(node, "score") else 0.0,
                        "metadata": node.node.metadata,
                    }
                )

        return retrieved_nodes

    @traced_retrieval
    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        correlation_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Retrieve relevant documents for a query with optional decomposition.

        Teaching note: Multi-strategy retrieval:
        1. HyDE: Transform query → hypothetical document (vocabulary bridging)
        2. Decomposition: Split query → sub-queries → parallel retrieval
        3. Both can be enabled simultaneously

        Parallel retrieval with ThreadPoolExecutor:
        - Why threads: I/O-bound (network calls to embedding service)
        - CPU-bound would use ProcessPoolExecutor
        - ThreadPoolExecutor faster startup, less overhead
        - max_workers=4: Balance parallelism vs resource usage

        Result aggregation:
        - Combine results from all sub-queries
        - Deduplicate by document text
        - Sort by score (higher is better)
        - Return top_k overall

        Args:
            query: User query
            top_k: Number of documents to retrieve
            correlation_id: Optional trace correlation ID

        Returns:
            List of retrieved document nodes with scores
        """
        if self.index is None:
            raise ValueError("Index not built. Call build_index() first.")

        # Query decomposition: Split into sub-queries, retrieve in parallel
        if self.use_decomposition:
            sub_queries = self._decompose_query(
                query=query,
                correlation_id=correlation_id,
            )

            # Teaching note: Parallel retrieval using ThreadPoolExecutor
            # Each sub-query is retrieved independently and simultaneously
            all_results: list[dict[str, Any]] = []

            with ThreadPoolExecutor(max_workers=4) as executor:
                # Submit all sub-query retrievals
                future_to_query = {}
                for sub_query in sub_queries:
                    # Apply HyDE to each sub-query if enabled
                    processed_query = sub_query
                    if self.use_hyde:
                        processed_query = self._generate_hypothetical_document(
                            query=sub_query,
                            correlation_id=correlation_id,
                        )

                    # Submit retrieval task
                    future = executor.submit(
                        self._retrieve_single,
                        processed_query,
                        top_k,
                    )
                    future_to_query[future] = sub_query

                # Collect results as they complete
                for future in as_completed(future_to_query):
                    sub_query = future_to_query[future]
                    try:
                        results = future.result()
                        all_results.extend(results)
                    except Exception as exc:
                        # Broad on purpose: future.result() re-raises whatever
                        # the worker threw - vector store timeouts, embedding
                        # errors, malformed sub-queries from HyDE. We continue
                        # so partial results from sibling sub-queries survive.
                        logger.warning(
                            "Sub-query retrieval failed (%r): %s",
                            sub_query,
                            exc,
                        )

            # Deduplicate and sort by score
            seen_texts = set()
            unique_results = []
            for result in all_results:
                text = result["text"]
                if text not in seen_texts:
                    seen_texts.add(text)
                    unique_results.append(result)

            # Sort by score (descending)
            unique_results.sort(key=lambda x: x["score"], reverse=True)

            # Return top_k
            return unique_results[:top_k]

        # Standard retrieval (with optional HyDE)
        processed_query = query
        if self.use_hyde:
            processed_query = self._generate_hypothetical_document(
                query=query,
                correlation_id=correlation_id,
            )

        return self._retrieve_single(processed_query, top_k)

    @traced_generation
    def generate(
        self,
        query: str,
        context_nodes: list[dict[str, Any]],
        correlation_id: str | None = None,
    ) -> str:
        """
        Generate answer from retrieved context.

        Teaching note: Same as naive RAG generation.
        HyDE only affects retrieval, not generation.

        Args:
            query: Original user query (not hypothetical document)
            context_nodes: Retrieved document nodes
            correlation_id: Optional trace correlation ID

        Returns:
            Generated answer
        """
        # Format context
        context_texts = [node["text"] for node in context_nodes]
        context_str = "\n\n".join(
            [f"Document {i + 1}:\n{text}" for i, text in enumerate(context_texts)]
        )

        # Build prompt
        prompt = f"""Answer the following query using the provided context.

Query: {query}

Context:
{context_str}

Answer the query concisely and accurately.
If the context doesn't contain enough information, say so.

Answer:"""

        response = self.llm_client.generate(
            prompt=prompt,
            temperature=0.0,  # Deterministic for factual answers
            max_tokens=500,
        )

        return response.content.strip()

    def query(
        self,
        query_str: str,
        top_k: int = 5,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        """
        End-to-end query execution.

        Teaching note: Same interface as NaiveRAGPipeline for easy comparison.

        Args:
            query_str: User query
            top_k: Number of documents to retrieve
            correlation_id: Optional trace correlation ID

        Returns:
            Dictionary with answer and metadata
        """
        # Retrieve
        context_nodes = self.retrieve(
            query=query_str,
            top_k=top_k,
            correlation_id=correlation_id,
        )

        # Generate
        answer = self.generate(
            query=query_str,  # Use original query, not hypothetical doc
            context_nodes=context_nodes,
            correlation_id=correlation_id,
        )

        return {
            "answer": answer,
            "context_nodes": context_nodes,
            "metadata": {
                "top_k": top_k,
                "use_hyde": self.use_hyde,
                "use_decomposition": self.use_decomposition,
                "num_retrieved": len(context_nodes),
            },
        }
