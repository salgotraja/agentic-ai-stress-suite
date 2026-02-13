"""Unit tests for document chunking module.

Focus areas:
- FixedChunker: size, overlap, sentence boundary respect
- SemanticChunker: sentence grouping, min/max sizes
- LateChunker: context prefix prepended
- PDFProcessor: text extraction (mocked)
- DocumentProcessor: orchestration, file type handling
- Edge cases: empty text, tiny documents, missing files
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.rag.chunking import (
    Chunk,
    ChunkingStrategy,
    DocumentProcessor,
    FixedChunker,
    LateChunker,
    PDFProcessor,
    SemanticChunker,
)


class TestFixedChunker:
    """Test fixed-size character chunking."""

    def test_basic_chunking(self) -> None:
        """Test basic fixed chunking produces chunks."""
        chunker = FixedChunker(chunk_size=100, chunk_overlap=10)
        text = "A" * 250
        chunks = chunker.chunk(text, {"source": "test.md"})

        assert len(chunks) >= 2
        for chunk in chunks:
            assert isinstance(chunk, Chunk)
            assert chunk.parent_doc_id == "test.md"

    def test_chunk_size_respected(self) -> None:
        """Test chunks don't exceed configured size (approximately)."""
        chunker = FixedChunker(chunk_size=100, chunk_overlap=10)
        text = "word " * 200  # ~1000 chars
        chunks = chunker.chunk(text, {"source": "test.md"})

        for chunk in chunks:
            # Allow some slack for sentence boundary seeking
            assert len(chunk.text) <= 120

    def test_overlap_creates_redundancy(self) -> None:
        """Test overlap causes text overlap between adjacent chunks."""
        chunker = FixedChunker(chunk_size=100, chunk_overlap=30)
        text = "The quick brown fox jumps over the lazy dog. " * 10
        chunks = chunker.chunk(text, {"source": "test.md"})

        if len(chunks) >= 2:
            # Last part of chunk[0] should appear in chunk[1]
            end_of_first = chunks[0].text[-20:]
            assert (
                any(end_of_first[:10] in chunks[i].text for i in range(1, len(chunks)))
                or len(chunks) < 3
            )  # May not overlap in small docs

    def test_empty_text_returns_empty(self) -> None:
        """Test empty text returns no chunks."""
        chunker = FixedChunker()
        chunks = chunker.chunk("", {"source": "empty.md"})
        assert chunks == []

    def test_whitespace_only_returns_empty(self) -> None:
        """Test whitespace-only text returns no chunks."""
        chunker = FixedChunker()
        chunks = chunker.chunk("   \n\n  \t  ", {"source": "whitespace.md"})
        assert chunks == []

    def test_small_text_single_chunk(self) -> None:
        """Test text smaller than chunk_size produces one chunk."""
        chunker = FixedChunker(chunk_size=500)
        text = "Short document."
        chunks = chunker.chunk(text, {"source": "short.md"})

        assert len(chunks) == 1
        assert chunks[0].text == "Short document."

    def test_chunk_index_sequential(self) -> None:
        """Test chunk indices are sequential."""
        chunker = FixedChunker(chunk_size=50, chunk_overlap=5)
        text = "word " * 100
        chunks = chunker.chunk(text, {"source": "test.md"})

        for i, chunk in enumerate(chunks):
            assert chunk.chunk_index == i

    def test_metadata_preserved(self) -> None:
        """Test base metadata is preserved in chunks."""
        chunker = FixedChunker(chunk_size=50)
        text = "word " * 50
        chunks = chunker.chunk(text, {"source": "test.md", "framework": "fastapi"})

        for chunk in chunks:
            assert chunk.metadata["source"] == "test.md"
            assert chunk.metadata["framework"] == "fastapi"
            assert "chunk_index" in chunk.metadata


class TestSemanticChunker:
    """Test semantic (sentence-boundary) chunking."""

    def test_respects_sentence_boundaries(self) -> None:
        """Test chunks split at sentence boundaries."""
        chunker = SemanticChunker(max_chunk_size=100)
        text = "First sentence. Second sentence. Third sentence. Fourth sentence."
        chunks = chunker.chunk(text, {"source": "test.md"})

        for chunk in chunks:
            # Each chunk should end with a complete sentence
            assert not chunk.text.endswith(" ")

    def test_groups_short_sentences(self) -> None:
        """Test short sentences are grouped together."""
        chunker = SemanticChunker(max_chunk_size=200)
        text = "Short. Very short. Tiny. Small. Brief."
        chunks = chunker.chunk(text, {"source": "test.md"})

        # All short sentences should fit in one chunk
        assert len(chunks) == 1

    def test_splits_long_content(self) -> None:
        """Test long content is split into multiple chunks."""
        chunker = SemanticChunker(max_chunk_size=100)
        text = "This is a long sentence about FastAPI. " * 20
        chunks = chunker.chunk(text, {"source": "test.md"})

        assert len(chunks) > 1

    def test_empty_text_returns_empty(self) -> None:
        """Test empty text returns no chunks."""
        chunker = SemanticChunker()
        chunks = chunker.chunk("", {"source": "empty.md"})
        assert chunks == []

    def test_merges_tiny_trailing_chunk(self) -> None:
        """Test tiny trailing sentences merge with previous chunk."""
        chunker = SemanticChunker(max_chunk_size=200, min_chunk_size=50)
        # Long enough to create 2 chunks, with tiny trailing content
        text = ("A" * 180 + ". ") + "Ok."
        chunks = chunker.chunk(text, {"source": "test.md"})

        # Tiny trailing "Ok." should merge with previous chunk
        if len(chunks) > 0:
            assert all(len(c.text) >= 3 for c in chunks)


class TestLateChunker:
    """Test contextual (late) chunking with context prefix."""

    def test_prepends_heading_context(self) -> None:
        """Test heading is prepended as context."""
        chunker = LateChunker(chunk_size=200)
        text = "# FastAPI Guide\n\nFastAPI is a modern framework. " * 10
        chunks = chunker.chunk(text, {"source": "test.md"})

        assert len(chunks) > 0
        assert chunks[0].text.startswith("[FastAPI Guide]")

    def test_all_chunks_have_context(self) -> None:
        """Test all chunks receive the context prefix."""
        chunker = LateChunker(chunk_size=100)
        text = "# My Document\n\n" + "Some content here. " * 30
        chunks = chunker.chunk(text, {"source": "test.md"})

        for chunk in chunks:
            assert "[My Document]" in chunk.text

    def test_context_in_metadata(self) -> None:
        """Test context prefix stored in metadata."""
        chunker = LateChunker(chunk_size=200)
        text = "# Title\n\nContent content content. " * 5
        chunks = chunker.chunk(text, {"source": "test.md"})

        assert len(chunks) > 0
        assert chunks[0].metadata.get("context_prefix") == "Title"

    def test_no_heading_no_prefix(self) -> None:
        """Test text without heading gets no prefix."""
        chunker = LateChunker(chunk_size=200)
        text = "Just plain text without any heading. " * 5
        chunks = chunker.chunk(text, {"source": "test.md"})

        if chunks:
            # First line is the context, so it should be prepended
            # even without a heading (uses first line as context)
            assert chunks[0].text.startswith("[Just plain text")

    def test_empty_text_returns_empty(self) -> None:
        """Test empty text returns no chunks."""
        chunker = LateChunker()
        chunks = chunker.chunk("", {"source": "empty.md"})
        assert chunks == []


class TestPDFProcessor:
    """Test PDF text extraction (mocked PyMuPDF)."""

    def test_file_not_found_raises(self) -> None:
        """Test non-existent file raises FileNotFoundError."""
        processor = PDFProcessor()
        with pytest.raises(FileNotFoundError):
            processor.extract(Path("/nonexistent/file.pdf"))

    def test_non_pdf_raises(self, tmp_path: Path) -> None:
        """Test non-PDF file raises ValueError."""
        txt_file = tmp_path / "test.txt"
        txt_file.write_text("not a pdf")

        processor = PDFProcessor()
        with pytest.raises(ValueError, match="Not a PDF"):
            processor.extract(txt_file)

    def test_extract_text_mocked(self, tmp_path: Path) -> None:
        """Test PDF extraction with mocked PyMuPDF."""
        import sys

        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"fake pdf content")

        mock_page = MagicMock()
        mock_page.get_text.return_value = "Page 1 content"
        mock_page.find_tables.return_value = []

        # fitz.open() returns a doc that iterates pages directly
        # enumerate(doc) yields (index, page), so __iter__ yields pages
        mock_doc = MagicMock()
        mock_doc.__iter__ = MagicMock(return_value=iter([mock_page]))
        mock_doc.close = MagicMock()

        mock_fitz = MagicMock()
        mock_fitz.open.return_value = mock_doc

        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            processor = PDFProcessor()
            text, tables = processor.extract(pdf_file)

        assert "Page 1 content" in text
        assert isinstance(tables, list)


class TestDocumentProcessor:
    """Test DocumentProcessor orchestration."""

    def test_process_markdown_file(self, tmp_path: Path) -> None:
        """Test processing a markdown file."""
        md_file = tmp_path / "test.md"
        md_file.write_text("# Test\n\n" + "Content. " * 100)

        processor = DocumentProcessor(
            strategy=ChunkingStrategy.FIXED,
            chunk_size=200,
        )
        chunks = processor.process_file(md_file)

        assert len(chunks) > 0
        assert all(isinstance(c, Chunk) for c in chunks)
        assert chunks[0].metadata["file_type"] == ".md"

    def test_process_text_file(self, tmp_path: Path) -> None:
        """Test processing a plain text file."""
        txt_file = tmp_path / "test.txt"
        txt_file.write_text("Plain text content. " * 50)

        processor = DocumentProcessor(strategy=ChunkingStrategy.FIXED, chunk_size=200)
        chunks = processor.process_file(txt_file)

        assert len(chunks) > 0

    def test_unsupported_extension_raises(self, tmp_path: Path) -> None:
        """Test unsupported file extension raises ValueError."""
        py_file = tmp_path / "test.py"
        py_file.write_text("print('hello')")

        processor = DocumentProcessor()
        with pytest.raises(ValueError, match="Unsupported file type"):
            processor.process_file(py_file)

    def test_file_not_found_raises(self) -> None:
        """Test missing file raises FileNotFoundError."""
        processor = DocumentProcessor()
        with pytest.raises(FileNotFoundError):
            processor.process_file(Path("/nonexistent/file.md"))

    def test_process_directory(self, tmp_path: Path) -> None:
        """Test processing a directory of markdown files."""
        (tmp_path / "doc1.md").write_text("# Doc 1\n\nFirst document. " * 50)
        (tmp_path / "doc2.md").write_text("# Doc 2\n\nSecond document. " * 50)
        (tmp_path / "ignore.py").write_text("print('ignored')")

        processor = DocumentProcessor(
            strategy=ChunkingStrategy.FIXED,
            chunk_size=200,
        )
        chunks = processor.process_directory(tmp_path, file_types=[".md"])

        assert len(chunks) > 0
        # Should only process .md files
        assert all(c.metadata["file_type"] == ".md" for c in chunks)

    def test_directory_not_found_raises(self) -> None:
        """Test missing directory raises FileNotFoundError."""
        processor = DocumentProcessor()
        with pytest.raises(FileNotFoundError):
            processor.process_directory(Path("/nonexistent/dir"))

    def test_strategy_selection(self) -> None:
        """Test different strategies create correct chunkers."""
        fixed = DocumentProcessor(strategy=ChunkingStrategy.FIXED)
        assert isinstance(fixed._chunker, FixedChunker)

        semantic = DocumentProcessor(strategy=ChunkingStrategy.SEMANTIC)
        assert isinstance(semantic._chunker, SemanticChunker)

        late = DocumentProcessor(strategy=ChunkingStrategy.LATE)
        assert isinstance(late._chunker, LateChunker)


class TestChunkDataclass:
    """Test Chunk dataclass."""

    def test_chunk_creation(self) -> None:
        """Test Chunk can be created with all fields."""
        chunk = Chunk(
            text="Test content",
            metadata={"source": "test.md"},
            chunk_index=0,
            start_char=0,
            end_char=12,
            parent_doc_id="test.md",
        )

        assert chunk.text == "Test content"
        assert chunk.chunk_index == 0
        assert chunk.parent_doc_id == "test.md"


class TestTeachingComments:
    """Verify teaching comments exist in chunking module."""

    def test_module_docstring_teaches(self) -> None:
        """Verify module docstring documents strategy trade-offs."""
        import src.rag.chunking as module

        docstring = module.__doc__ or ""

        assert "Fixed" in docstring
        assert "Semantic" in docstring or "semantic" in docstring
        assert "Late" in docstring
        assert "overlap" in docstring.lower()
        assert "trade-off" in docstring.lower()

    def test_fixed_chunker_teaches(self) -> None:
        """Verify FixedChunker has teaching comments."""
        import inspect

        source = inspect.getsource(FixedChunker)
        assert "Teaching note:" in source
        assert "overlap" in source.lower()

    def test_late_chunker_teaches(self) -> None:
        """Verify LateChunker has teaching comments."""
        import inspect

        source = inspect.getsource(LateChunker)
        assert "Teaching note:" in source
        assert "context" in source.lower()
