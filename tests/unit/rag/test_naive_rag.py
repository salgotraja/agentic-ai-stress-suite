"""Unit tests for Naive RAG Pipeline."""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from src.core.config import Settings
from src.core.llm_client import LLMProvider, LLMResponse
from src.rag.naive_rag import NaiveRAGPipeline


@pytest.fixture
def mock_settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Create mock settings for testing."""
    monkeypatch.setenv("GROQ_API_KEY", "test_groq_key")
    monkeypatch.setenv("CHROMA_URL", "http://localhost:8000")
    return Settings()


@pytest.fixture
def mock_chroma_client() -> Mock:
    """Create mock Chroma client."""
    client = Mock()
    collection = Mock()
    client.get_or_create_collection.return_value = collection
    return client


@pytest.fixture
def mock_embed_model() -> Mock:
    """Create mock embedding model."""
    model = Mock()
    model.get_text_embedding.return_value = [0.1] * 768  # Mock 768-dim embedding
    return model


class TestNaiveRAGPipelineInit:
    """Test NaiveRAGPipeline initialization."""

    @patch("chromadb.HttpClient")
    @patch("src.rag.naive_rag.HuggingFaceEmbedding")
    def test_init_with_defaults(
        self,
        mock_hf_embed: Mock,
        mock_chroma: Mock,
        mock_settings: Settings,
    ) -> None:
        """Test initialization with default parameters."""
        pipeline = NaiveRAGPipeline(settings=mock_settings)

        assert pipeline.collection_name == "naive_rag"
        assert pipeline.chunk_size == 500
        assert pipeline.chunk_overlap == 50
        assert pipeline.top_k == 5
        assert pipeline.settings == mock_settings

    @patch("chromadb.HttpClient")
    @patch("src.rag.naive_rag.HuggingFaceEmbedding")
    def test_init_with_custom_parameters(
        self,
        mock_hf_embed: Mock,
        mock_chroma: Mock,
        mock_settings: Settings,
    ) -> None:
        """Test initialization with custom parameters."""
        pipeline = NaiveRAGPipeline(
            collection_name="custom_collection",
            chunk_size=1000,
            chunk_overlap=100,
            top_k=10,
            settings=mock_settings,
        )

        assert pipeline.collection_name == "custom_collection"
        assert pipeline.chunk_size == 1000
        assert pipeline.chunk_overlap == 100
        assert pipeline.top_k == 10

    @patch("chromadb.HttpClient")
    @patch("src.rag.naive_rag.HuggingFaceEmbedding")
    def test_parse_chroma_url(
        self,
        mock_hf_embed: Mock,
        mock_chroma: Mock,
        mock_settings: Settings,
    ) -> None:
        """Test Chroma URL parsing."""
        pipeline = NaiveRAGPipeline(settings=mock_settings)

        host = pipeline._parse_chroma_host()
        port = pipeline._parse_chroma_port()

        assert host == "localhost"
        assert port == 8000


class TestDocumentLoading:
    """Test document loading functionality."""

    @patch("chromadb.HttpClient")
    @patch("src.rag.naive_rag.HuggingFaceEmbedding")
    @patch("src.rag.naive_rag.SimpleDirectoryReader")
    def test_load_documents_success(
        self,
        mock_reader_class: Mock,
        mock_hf_embed: Mock,
        mock_chroma: Mock,
        mock_settings: Settings,
        tmp_path: Path,
    ) -> None:
        """Test successful document loading."""
        # Create temporary directory with a file
        test_dir = tmp_path / "docs"
        test_dir.mkdir()
        (test_dir / "test.md").write_text("# Test Document\n\nThis is a test.")

        # Mock reader
        mock_document = Mock()
        mock_document.id_ = "test.md"
        mock_document.metadata = {}
        mock_reader = Mock()
        mock_reader.load_data.return_value = [mock_document]
        mock_reader_class.return_value = mock_reader

        pipeline = NaiveRAGPipeline(settings=mock_settings)
        documents = pipeline.load_documents(test_dir)

        assert len(documents) == 1
        assert documents[0].metadata["source"] == "test.md"
        assert documents[0].metadata["collection"] == "naive_rag"

    @patch("chromadb.HttpClient")
    @patch("src.rag.naive_rag.HuggingFaceEmbedding")
    def test_load_documents_directory_not_found(
        self,
        mock_hf_embed: Mock,
        mock_chroma: Mock,
        mock_settings: Settings,
    ) -> None:
        """Test document loading with non-existent directory."""
        pipeline = NaiveRAGPipeline(settings=mock_settings)

        with pytest.raises(ValueError, match="Directory not found"):
            pipeline.load_documents("/nonexistent/directory")


class TestIndexBuilding:
    """Test vector index building."""

    @patch("chromadb.HttpClient")
    @patch("src.rag.naive_rag.HuggingFaceEmbedding")
    @patch("src.rag.naive_rag.VectorStoreIndex.from_documents")
    @patch("src.rag.naive_rag.ChromaVectorStore")
    def test_build_index(
        self,
        mock_vector_store_class: Mock,
        mock_index_class: Mock,
        mock_hf_embed: Mock,
        mock_chroma: Mock,
        mock_settings: Settings,
        mock_chroma_client: Mock,
    ) -> None:
        """Test index building."""
        # Setup mocks
        mock_document = Mock()
        mock_document.id_ = "test.md"
        mock_document.text = "Test content"
        mock_document.metadata = {}

        mock_index = Mock()
        mock_index_class.return_value = mock_index

        # Patch chroma client in pipeline
        pipeline = NaiveRAGPipeline(settings=mock_settings)
        pipeline.chroma_client = mock_chroma_client

        # Mock LlamaIndex Settings to avoid BaseEmbedding validation
        with patch("llama_index.core.Settings"):
            # Build index
            index = pipeline.build_index([mock_document])

            assert index is not None
            assert pipeline._index == index
            mock_chroma_client.get_or_create_collection.assert_called_once()


class TestRetrieval:
    """Test retrieval functionality."""

    @patch("chromadb.HttpClient")
    @patch("src.rag.naive_rag.HuggingFaceEmbedding")
    def test_retrieve_without_index(
        self,
        mock_hf_embed: Mock,
        mock_chroma: Mock,
        mock_settings: Settings,
    ) -> None:
        """Test that retrieve fails when index not built."""
        pipeline = NaiveRAGPipeline(settings=mock_settings)

        with pytest.raises(ValueError, match="Index not built"):
            pipeline.retrieve("test query")

    @patch("chromadb.HttpClient")
    @patch("src.rag.naive_rag.HuggingFaceEmbedding")
    def test_retrieve_with_index(
        self,
        mock_hf_embed: Mock,
        mock_chroma: Mock,
        mock_settings: Settings,
    ) -> None:
        """Test successful retrieval."""
        pipeline = NaiveRAGPipeline(settings=mock_settings)

        # Mock index and retriever
        mock_node = Mock()
        mock_node.score = 0.95
        mock_node.node.get_content.return_value = "Test content"
        mock_node.node.metadata = {"source": "test.md"}

        mock_retriever = Mock()
        mock_retriever.retrieve.return_value = [mock_node]

        mock_index = Mock()
        mock_index.as_retriever.return_value = mock_retriever

        pipeline._index = mock_index

        # Retrieve
        nodes = pipeline.retrieve("test query", top_k=3)

        assert len(nodes) == 1
        assert nodes[0].score == 0.95
        mock_index.as_retriever.assert_called_once_with(similarity_top_k=3)


class TestGeneration:
    """Test response generation."""

    @patch("chromadb.HttpClient")
    @patch("src.rag.naive_rag.HuggingFaceEmbedding")
    def test_generate(
        self,
        mock_hf_embed: Mock,
        mock_chroma: Mock,
        mock_settings: Settings,
    ) -> None:
        """Test answer generation."""
        pipeline = NaiveRAGPipeline(settings=mock_settings)

        # Mock context nodes
        mock_node = Mock()
        mock_node.score = 0.95
        mock_node.node.get_content.return_value = "FastAPI is a modern web framework."
        mock_node.node.metadata = {"source": "fastapi.md"}

        # Mock LLM response
        mock_response = LLMResponse(
            content="FastAPI is a fast web framework for Python.",
            provider=LLMProvider.GROQ,
            model="llama-3-8b",
            prompt_tokens=100,
            completion_tokens=20,
            total_tokens=120,
            cost_usd=0.0001,
            latency_seconds=0.5,
        )

        with patch.object(pipeline.llm_client, "generate", return_value=mock_response):
            answer = pipeline.generate("What is FastAPI?", [mock_node])

        assert answer == "FastAPI is a fast web framework for Python."

    @patch("chromadb.HttpClient")
    @patch("src.rag.naive_rag.HuggingFaceEmbedding")
    def test_generate_formats_context(
        self,
        mock_hf_embed: Mock,
        mock_chroma: Mock,
        mock_settings: Settings,
    ) -> None:
        """Test that generation formats context correctly."""
        pipeline = NaiveRAGPipeline(settings=mock_settings)

        # Mock multiple context nodes
        mock_node1 = Mock()
        mock_node1.score = 0.95
        mock_node1.node.get_content.return_value = "Content 1"
        mock_node1.node.metadata = {"source": "doc1.md"}

        mock_node2 = Mock()
        mock_node2.score = 0.85
        mock_node2.node.get_content.return_value = "Content 2"
        mock_node2.node.metadata = {"source": "doc2.md"}

        mock_response = LLMResponse(
            content="Test answer",
            provider=LLMProvider.GROQ,
            model="llama-3-8b",
            prompt_tokens=100,
            completion_tokens=20,
            total_tokens=120,
            cost_usd=0.0001,
            latency_seconds=0.5,
        )

        captured_prompt = None

        def capture_prompt(prompt: str, **kwargs: dict[str, any]) -> LLMResponse:
            nonlocal captured_prompt
            captured_prompt = prompt
            return mock_response

        with patch.object(pipeline.llm_client, "generate", side_effect=capture_prompt):
            pipeline.generate("test query", [mock_node1, mock_node2])

        # Verify prompt contains both contexts
        assert captured_prompt is not None
        assert "[1]" in captured_prompt
        assert "[2]" in captured_prompt
        assert "Content 1" in captured_prompt
        assert "Content 2" in captured_prompt
        assert "0.950" in captured_prompt  # Score of first node
        assert "0.850" in captured_prompt  # Score of second node


class TestEndToEndQuery:
    """Test end-to-end query functionality."""

    @patch("chromadb.HttpClient")
    @patch("src.rag.naive_rag.HuggingFaceEmbedding")
    def test_query_end_to_end(
        self,
        mock_hf_embed: Mock,
        mock_chroma: Mock,
        mock_settings: Settings,
    ) -> None:
        """Test full query pipeline."""
        pipeline = NaiveRAGPipeline(settings=mock_settings, top_k=3)

        # Mock retrieval
        mock_node = Mock()
        mock_node.score = 0.95
        mock_node.node.get_content.return_value = "Test content"
        mock_node.node.metadata = {"source": "test.md"}

        # Mock index
        mock_retriever = Mock()
        mock_retriever.retrieve.return_value = [mock_node]
        mock_index = Mock()
        mock_index.as_retriever.return_value = mock_retriever
        pipeline._index = mock_index

        # Mock generation
        mock_response = LLMResponse(
            content="This is the answer.",
            provider=LLMProvider.GROQ,
            model="llama-3-8b",
            prompt_tokens=100,
            completion_tokens=20,
            total_tokens=120,
            cost_usd=0.0001,
            latency_seconds=0.5,
        )

        with patch.object(pipeline.llm_client, "generate", return_value=mock_response):
            result = pipeline.query("test query")

        assert result["answer"] == "This is the answer."
        assert len(result["context_nodes"]) == 1
        assert result["metadata"]["query"] == "test query"
        assert result["metadata"]["num_retrieved"] == 1
        assert result["metadata"]["top_k"] == 3
        assert result["metadata"]["collection"] == "naive_rag"
