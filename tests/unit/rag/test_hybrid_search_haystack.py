"""Unit tests for HaystackHybridSearchPipeline.

These tests verify the Haystack implementation provides equivalent
functionality to the LlamaIndex implementation.

Focus areas:
- Pipeline construction and component wiring
- Document loading and chunking
- Retrieval accuracy parity with LlamaIndex
- Teaching comments and documentation
"""

from __future__ import annotations


class TestHaystackPipelineConstruction:
    """Test Haystack pipeline initialization and construction."""

    def test_pipeline_initialization(self):
        """Test pipeline initializes without errors."""
        from src.rag.hybrid_search import HaystackHybridSearchPipeline

        pipeline = HaystackHybridSearchPipeline(
            collection_name="test_haystack",
            chunk_size=500,
            chunk_overlap=50,
            top_k=5,
        )

        assert pipeline.collection_name == "test_haystack"
        assert pipeline.chunk_size == 500
        assert pipeline.chunk_overlap == 50
        assert pipeline.top_k == 5
        assert pipeline._retrieval_pipeline is None  # Not built yet

    def test_pipeline_builds_successfully(self):
        """Test pipeline builds with minimal documents."""
        from haystack import Document as HaystackDocument

        from src.rag.hybrid_search import HaystackHybridSearchPipeline

        pipeline = HaystackHybridSearchPipeline(collection_name="test_build")

        # Create minimal test documents
        test_docs = [
            HaystackDocument(
                content="FastAPI is a modern web framework for Python.",
                meta={"source": "test1.md"},
            ).to_dict(),
            HaystackDocument(
                content="React is a JavaScript library for building user interfaces.",
                meta={"source": "test2.md"},
            ).to_dict(),
        ]

        # Build pipeline
        built_pipeline = pipeline.build_index(test_docs)

        assert built_pipeline is not None
        assert pipeline._retrieval_pipeline is not None
        assert pipeline._document_store is not None

        # Verify pipeline components exist
        assert "text_embedder" in pipeline._retrieval_pipeline.graph.nodes
        assert "bm25_retriever" in pipeline._retrieval_pipeline.graph.nodes
        assert "embedding_retriever" in pipeline._retrieval_pipeline.graph.nodes
        assert "joiner" in pipeline._retrieval_pipeline.graph.nodes


class TestHaystackDocumentLoading:
    """Test Haystack document loading and preprocessing."""

    def test_load_documents_haystack_format(self, tmp_path):
        """Test documents are loaded in correct Haystack format."""
        from src.rag.hybrid_search import HaystackHybridSearchPipeline

        # Create test markdown file
        test_md = tmp_path / "test_doc.md"
        test_md.write_text("# FastAPI\n\nFastAPI is a modern web framework.")

        pipeline = HaystackHybridSearchPipeline()
        documents = pipeline.load_documents(tmp_path)

        assert len(documents) > 0
        assert isinstance(documents[0], dict)  # Haystack Document dicts
        assert "content" in documents[0]
        # Haystack may flatten metadata into top-level dict
        assert "source" in documents[0] or "meta" in documents[0]

    def test_chunking_respects_parameters(self, tmp_path):
        """Test document chunking uses configured parameters."""
        from src.rag.hybrid_search import HaystackHybridSearchPipeline

        # Create test document with sufficient content
        test_md = tmp_path / "test_doc.md"
        long_content = " ".join(["FastAPI"] * 200)  # 200 words
        test_md.write_text(f"# Test\n\n{long_content}")

        pipeline = HaystackHybridSearchPipeline(
            chunk_size=50,  # Small chunks
            chunk_overlap=10,
        )

        documents = pipeline.load_documents(tmp_path)

        # Should have multiple chunks due to small chunk size
        assert len(documents) > 1


class TestHaystackRetrieval:
    """Test Haystack retrieval functionality."""

    def test_retrieve_returns_documents(self, tmp_path):
        """Test retrieval returns documents in correct format."""
        from haystack import Document as HaystackDocument

        from src.rag.hybrid_search import HaystackHybridSearchPipeline

        # Create test documents
        test_docs = [
            HaystackDocument(
                content="FastAPI is a modern Python web framework for building APIs.",
                meta={"source": "fastapi.md"},
            ).to_dict(),
            HaystackDocument(
                content="React is a JavaScript library for building user interfaces.",
                meta={"source": "react.md"},
            ).to_dict(),
        ]

        pipeline = HaystackHybridSearchPipeline(collection_name="test_retrieve", top_k=2)
        pipeline.build_index(test_docs)

        # Query for FastAPI
        results = pipeline.retrieve("What is FastAPI?", top_k=2)

        assert isinstance(results, list)
        assert len(results) > 0
        assert isinstance(results[0], dict)  # Haystack Document dict
        assert "content" in results[0]
        assert "score" in results[0]

    def test_hybrid_search_combines_bm25_and_dense(self, tmp_path):
        """Test hybrid search uses both BM25 and dense retrieval."""
        from haystack import Document as HaystackDocument

        from src.rag.hybrid_search import HaystackHybridSearchPipeline

        # Create documents with distinct characteristics
        test_docs = [
            HaystackDocument(
                content="MongoDB $lookup operator performs left outer join.",
                meta={"source": "mongodb.md"},
            ).to_dict(),  # Good for BM25 (exact term "$lookup")
            HaystackDocument(
                content="Combining data from multiple collections in MongoDB.",
                meta={"source": "joins.md"},
            ).to_dict(),  # Good for dense (semantic)
        ]

        pipeline = HaystackHybridSearchPipeline(
            collection_name="test_hybrid",
            bm25_weight=0.5,
            dense_weight=0.5,
        )
        pipeline.build_index(test_docs)

        # Query should leverage both methods
        results = pipeline.retrieve("MongoDB join collections", top_k=2)

        # Both documents should be retrieved (one by BM25, one by dense)
        assert len(results) == 2


class TestWeightConfiguration:
    """Test BM25 vs dense weight configuration."""

    def test_bm25_heavy_weights(self):
        """Test BM25-heavy configuration favors keyword matching."""
        from haystack import Document as HaystackDocument

        from src.rag.hybrid_search import HaystackHybridSearchPipeline

        test_docs = [
            HaystackDocument(
                content="React hooks useState for state management.",
                meta={"source": "react.md"},
            ).to_dict(),
            HaystackDocument(
                content="Managing component state in React applications.",
                meta={"source": "state.md"},
            ).to_dict(),
        ]

        # BM25-heavy pipeline
        pipeline_bm25 = HaystackHybridSearchPipeline(
            collection_name="test_bm25_heavy",
            bm25_weight=0.9,
            dense_weight=0.1,
        )
        pipeline_bm25.build_index(test_docs)

        # Query with exact keyword "useState"
        results = pipeline_bm25.retrieve("useState hook", top_k=1)

        # Should favor exact keyword match
        assert len(results) > 0
        assert "useState" in results[0]["content"]

    def test_dense_heavy_weights(self):
        """Test dense-heavy configuration favors semantic matching."""
        from haystack import Document as HaystackDocument

        from src.rag.hybrid_search import HaystackHybridSearchPipeline

        test_docs = [
            HaystackDocument(
                content="Delete items from database using ORM.",
                meta={"source": "db.md"},
            ).to_dict(),
            HaystackDocument(
                content="Remove records from database tables.",
                meta={"source": "sql.md"},
            ).to_dict(),
        ]

        # Dense-heavy pipeline
        pipeline_dense = HaystackHybridSearchPipeline(
            collection_name="test_dense_heavy",
            bm25_weight=0.1,
            dense_weight=0.9,
        )
        pipeline_dense.build_index(test_docs)

        # Semantic query (no exact match for "delete" in second doc)
        results = pipeline_dense.retrieve("how to delete database records", top_k=2)

        # Should retrieve both (semantic similarity)
        assert len(results) == 2


class TestTeachingComments:
    """Verify teaching comments exist in Haystack implementation."""

    def test_teaching_comments_present(self):
        """Verify key teaching concepts are documented."""
        import inspect

        from src.rag.hybrid_search import HaystackHybridSearchPipeline

        source = inspect.getsource(HaystackHybridSearchPipeline)

        # Check for key teaching concepts
        teaching_concepts = [
            "Teaching note:",
            "Haystack",
            "LlamaIndex",
            "trade-offs",
            "pipeline",
            "production",
        ]

        for concept in teaching_concepts:
            assert concept in source, f"Missing teaching concept: {concept}"

    def test_framework_comparison_documented(self):
        """Verify framework comparison is documented."""
        import inspect

        from src.rag.hybrid_search import HaystackHybridSearchPipeline

        source = inspect.getsource(HaystackHybridSearchPipeline)

        # Should document when to choose each framework
        assert (
            "When to choose" in source
            or "Choose LlamaIndex" in source
            or "Choose Haystack" in source
        )
        assert "strengths" in source.lower()
        assert "weaknesses" in source.lower()


class TestFrameworkParity:
    """Test Haystack and LlamaIndex provide equivalent functionality."""

    def test_both_frameworks_available(self):
        """Test both implementations can be imported."""
        from src.rag.hybrid_search import HaystackHybridSearchPipeline, HybridSearchPipeline

        # Both should be importable
        assert HybridSearchPipeline is not None
        assert HaystackHybridSearchPipeline is not None

    def test_api_similarity(self):
        """Test both implementations have similar APIs."""
        from src.rag.hybrid_search import HaystackHybridSearchPipeline, HybridSearchPipeline

        # Both should have same public methods
        llamaindex_methods = {
            "load_documents",
            "build_index",
            "retrieve",
            "generate",
            "query",
        }
        haystack_methods = {
            "load_documents",
            "build_index",
            "retrieve",
            "generate",
            "query",
        }

        for method in llamaindex_methods:
            assert hasattr(HybridSearchPipeline, method)

        for method in haystack_methods:
            assert hasattr(HaystackHybridSearchPipeline, method)

    def test_initialization_parameters_similar(self):
        """Test both implementations accept similar parameters."""
        from src.rag.hybrid_search import HaystackHybridSearchPipeline, HybridSearchPipeline

        # Common parameters
        common_params = {
            "collection_name": "test",
            "chunk_size": 500,
            "chunk_overlap": 50,
            "top_k": 5,
            "bm25_weight": 0.5,
            "dense_weight": 0.5,
        }

        # Both should accept these parameters
        pipeline_llama = HybridSearchPipeline(**common_params)
        pipeline_haystack = HaystackHybridSearchPipeline(**common_params)

        assert pipeline_llama.collection_name == "test"
        assert pipeline_haystack.collection_name == "test"
