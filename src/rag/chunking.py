"""Document chunking strategies for RAG pipelines.

This module provides multiple chunking strategies and a PDF processor:
- FixedChunker: Split by character count with overlap
- SemanticChunker: Group sentences by embedding similarity
- LateChunker: Prepend document summary for contextual retrieval
- PDFProcessor: Extract text and tables from PDF files

Teaching note: Why chunking strategy matters
---------------------------------------------
Chunking is the most underrated step in RAG. The choice of strategy directly
impacts retrieval quality, and there's no universal best answer.

Strategy comparison:
1. Fixed (character-based):
   - Split at N characters with overlap
   - Predictable sizes, simple to implement
   - Risk: Splits mid-sentence, loses context
   - Best for: Consistent, structured documents (API docs, code)

2. Semantic (sentence grouping):
   - Embed sentences, group by cosine similarity
   - Chunks map to natural topic boundaries
   - Risk: Unpredictable sizes (some chunks huge, others tiny)
   - Best for: Long-form prose, research papers, blog posts

3. Late (contextual chunking):
   - Fixed chunking + prepend document summary to each chunk
   - Chunks carry document-level context into embedding
   - Risk: Longer chunks consume more token budget
   - Best for: Technical docs where chunks need parent document context
   - Named after "Late Interaction" concept from ColBERT

Chunk size trade-offs:
- Small chunks (100-200 chars): Higher precision, lower recall, more noise
- Medium chunks (300-500 chars): Good balance (our default: 500)
- Large chunks (500-1000 chars): Higher recall, lower precision, more token usage
- Rule of thumb: Chunk size ~= answer length for your use case

Overlap trade-offs:
- No overlap (0): Clean splits, may lose boundary context
- Small overlap (10-20%): Captures boundary context, minimal redundancy
- Large overlap (30-50%): Maximizes context preservation, storage bloat
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class ChunkingStrategy(str, Enum):
    """Available chunking strategies."""

    FIXED = "fixed"
    SEMANTIC = "semantic"
    LATE = "late"


@dataclass
class Chunk:
    """A single document chunk with metadata.

    Attributes:
        text: Chunk text content
        metadata: Inherited + chunk-specific metadata
        chunk_index: Position within parent document
        start_char: Start character offset in original document
        end_char: End character offset in original document
        parent_doc_id: Identifier of the source document
    """

    text: str
    metadata: dict[str, Any]
    chunk_index: int
    start_char: int
    end_char: int
    parent_doc_id: str


class FixedChunker:
    """Fixed-size character chunking with configurable overlap.

    Teaching note: Fixed chunking mechanics
    ----------------------------------------
    The simplest strategy: slide a window of N characters with overlap.

    Example (chunk_size=100, overlap=20):
    Document: [0..............100..............200..............300]
    Chunk 1:  [0..............100]
    Chunk 2:            [80..............180]
    Chunk 3:                      [160..............260]

    Overlap ensures sentences at boundaries aren't lost.
    Without overlap: "FastAPI supports" | "async endpoints" -> split
    With overlap: Both chunks contain "FastAPI supports async endpoints"
    """

    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 50) -> None:
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def chunk(self, text: str, metadata: dict[str, Any]) -> list[Chunk]:
        """Split text into fixed-size chunks.

        Args:
            text: Document text
            metadata: Base metadata for all chunks

        Returns:
            List of Chunk objects
        """
        if not text.strip():
            return []

        chunks = []
        doc_id = metadata.get("source", "unknown")
        start = 0
        chunk_index = 0

        while start < len(text):
            end = min(start + self.chunk_size, len(text))

            # Try to break at sentence boundary within last 20% of chunk
            if end < len(text):
                boundary_zone_start = max(start, end - self.chunk_size // 5)
                best_break = end

                for sep in [". ", ".\n", "\n\n", "\n", " "]:
                    pos = text.rfind(sep, boundary_zone_start, end)
                    if pos != -1:
                        best_break = pos + len(sep)
                        break

                end = best_break

            chunk_text = text[start:end].strip()
            if chunk_text:
                chunk_metadata = {**metadata, "chunk_index": chunk_index}
                chunks.append(
                    Chunk(
                        text=chunk_text,
                        metadata=chunk_metadata,
                        chunk_index=chunk_index,
                        start_char=start,
                        end_char=end,
                        parent_doc_id=doc_id,
                    )
                )
                chunk_index += 1

            # If this chunk reached the end, stop
            if end >= len(text):
                break

            # Advance with overlap
            step = max(end - start - self.chunk_overlap, 1)
            start += step

        return chunks


class SemanticChunker:
    """Sentence-level chunking grouped by semantic similarity.

    Teaching note: Semantic chunking approach
    ------------------------------------------
    Instead of fixed windows, semantic chunking:
    1. Split document into sentences
    2. Embed each sentence
    3. Compute pairwise cosine similarity between adjacent sentences
    4. Split where similarity drops below threshold (topic change)

    Advantages:
    - Chunks align with topic boundaries
    - No mid-sentence splits
    - Better retrieval for topic-focused queries

    Disadvantages:
    - Requires embedding model at index time (slower)
    - Unpredictable chunk sizes
    - Similarity threshold needs tuning per domain

    Simplified implementation:
    We use a simpler version that groups consecutive sentences up to a size limit,
    breaking at sentence boundaries. This avoids the embedding dependency while
    still respecting sentence boundaries (unlike fixed chunking).

    Full semantic chunking with embeddings is better but requires:
    - Sentence-level embedding (slow for large corpora)
    - Threshold tuning (0.5-0.8 typical)
    - Sliding window similarity computation
    """

    SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[.!?])\s+")

    def __init__(
        self,
        max_chunk_size: int = 500,
        min_chunk_size: int = 100,
    ) -> None:
        self.max_chunk_size = max_chunk_size
        self.min_chunk_size = min_chunk_size

    def chunk(self, text: str, metadata: dict[str, Any]) -> list[Chunk]:
        """Split text into semantic chunks (sentence-boundary aware).

        Args:
            text: Document text
            metadata: Base metadata for all chunks

        Returns:
            List of Chunk objects
        """
        if not text.strip():
            return []

        sentences = self.SENTENCE_SPLIT_PATTERN.split(text)
        sentences = [s.strip() for s in sentences if s.strip()]

        if not sentences:
            return []

        chunks = []
        doc_id = metadata.get("source", "unknown")
        current_sentences: list[str] = []
        current_length = 0
        chunk_index = 0
        start_char = 0

        for sentence in sentences:
            sentence_len = len(sentence)

            # If adding this sentence exceeds max, flush current chunk
            if current_length + sentence_len > self.max_chunk_size and current_sentences:
                chunk_text = " ".join(current_sentences)
                end_char = start_char + len(chunk_text)
                chunk_metadata = {**metadata, "chunk_index": chunk_index}

                chunks.append(
                    Chunk(
                        text=chunk_text,
                        metadata=chunk_metadata,
                        chunk_index=chunk_index,
                        start_char=start_char,
                        end_char=end_char,
                        parent_doc_id=doc_id,
                    )
                )
                chunk_index += 1
                start_char = end_char + 1
                current_sentences = []
                current_length = 0

            current_sentences.append(sentence)
            current_length += sentence_len + 1  # +1 for space

        # Flush remaining sentences
        if current_sentences:
            chunk_text = " ".join(current_sentences)
            # Merge tiny trailing chunk with previous if possible
            if len(chunk_text) < self.min_chunk_size and chunks:
                last_chunk = chunks[-1]
                merged_text = last_chunk.text + " " + chunk_text
                chunks[-1] = Chunk(
                    text=merged_text,
                    metadata=last_chunk.metadata,
                    chunk_index=last_chunk.chunk_index,
                    start_char=last_chunk.start_char,
                    end_char=last_chunk.start_char + len(merged_text),
                    parent_doc_id=doc_id,
                )
            else:
                end_char = start_char + len(chunk_text)
                chunk_metadata = {**metadata, "chunk_index": chunk_index}
                chunks.append(
                    Chunk(
                        text=chunk_text,
                        metadata=chunk_metadata,
                        chunk_index=chunk_index,
                        start_char=start_char,
                        end_char=end_char,
                        parent_doc_id=doc_id,
                    )
                )

        return chunks


class LateChunker:
    """Contextual chunking that prepends document summary to each chunk.

    Teaching note: Late chunking / contextual retrieval
    ----------------------------------------------------
    Problem: When chunks are retrieved independently, they lose document context.
    Example: A chunk says "It also supports..." but doesn't say what "it" refers to.

    Solution: Prepend a brief summary (first paragraph or heading) to each chunk.
    This gives every chunk enough context to stand alone.

    Before: "It also supports async/await patterns for concurrent processing."
    After:  "[FastAPI - Web Framework for APIs] It also supports async/await
             patterns for concurrent processing."

    Trade-offs:
    - Larger chunks: More tokens per chunk (embedding and retrieval cost)
    - Better context: Chunks are self-contained, reducing hallucination
    - Inspired by Anthropic's "Contextual Retrieval" paper (2024)
    - Simple version: Use first heading/paragraph as context prefix
    - Advanced version: Generate summary per document via LLM (expensive)

    We implement the simple version (heading extraction) because:
    - No extra LLM cost at index time
    - Works well for structured technical docs with clear headings
    - Can be upgraded to LLM-generated summaries later
    """

    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 50) -> None:
        self._fixed_chunker = FixedChunker(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

    def _extract_context(self, text: str) -> str:
        """Extract document context from heading or first paragraph.

        Args:
            text: Full document text

        Returns:
            Context string to prepend to chunks
        """
        lines = text.strip().split("\n")
        context_parts = []

        for line in lines[:5]:  # Check first 5 lines
            stripped = line.strip()
            if stripped.startswith("#"):
                heading = stripped.lstrip("#").strip()
                context_parts.append(heading)
            elif stripped and not context_parts:
                # First non-empty, non-heading line
                context_parts.append(stripped[:200])
                break
            elif stripped and context_parts:
                break

        return " - ".join(context_parts) if context_parts else ""

    def chunk(self, text: str, metadata: dict[str, Any]) -> list[Chunk]:
        """Split text with context prefix on each chunk.

        Args:
            text: Document text
            metadata: Base metadata for all chunks

        Returns:
            List of Chunk objects with context prefix
        """
        context = self._extract_context(text)
        base_chunks = self._fixed_chunker.chunk(text, metadata)

        if not context:
            return base_chunks

        prefix = f"[{context}] "
        contextualized = []
        for chunk in base_chunks:
            contextualized.append(
                Chunk(
                    text=prefix + chunk.text,
                    metadata={**chunk.metadata, "context_prefix": context},
                    chunk_index=chunk.chunk_index,
                    start_char=chunk.start_char,
                    end_char=chunk.end_char,
                    parent_doc_id=chunk.parent_doc_id,
                )
            )

        return contextualized


class PDFProcessor:
    """Extract text and tables from PDF files using PyMuPDF.

    Teaching note: PDF extraction challenges
    -----------------------------------------
    PDF is a visual format, not a semantic one. Extracting structured text
    from PDFs involves dealing with:

    1. Multi-column layouts: Text flows in columns, not top-to-bottom
    2. Headers/footers: Repeated on every page, not actual content
    3. Tables: Cell boundaries lost in raw text extraction
    4. Images: Embedded images may contain text (OCR needed)
    5. Ligatures and encoding: Special characters, Unicode issues

    PyMuPDF (fitz) vs alternatives:
    - PyMuPDF: Fast, lightweight, good text extraction (~1MB)
    - pdfplumber: Better table extraction, slower
    - Unstructured: Best quality, heaviest dependency (~500MB+)
    - PyPDF2/pypdf: Basic, no table support

    We use PyMuPDF because:
    - Lightweight (no heavy ML dependencies)
    - Good text quality for technical documents
    - Built-in table detection
    - Fast processing (C-based backend)
    """

    def extract(self, filepath: Path) -> tuple[str, list[dict[str, Any]]]:
        """Extract text and tables from a PDF file.

        Args:
            filepath: Path to PDF file

        Returns:
            Tuple of (full_text, list_of_tables)
            Each table is a dict with "page", "rows" keys

        Raises:
            FileNotFoundError: If PDF file doesn't exist
            ValueError: If file is not a valid PDF
        """
        if not filepath.exists():
            raise FileNotFoundError(f"PDF not found: {filepath}")

        if filepath.suffix.lower() != ".pdf":
            raise ValueError(f"Not a PDF file: {filepath}")

        import fitz  # PyMuPDF

        doc = fitz.open(str(filepath))
        text_parts = []
        tables = []

        for page_num, page in enumerate(doc):
            # Extract text
            page_text = page.get_text("text")
            if page_text.strip():
                text_parts.append(page_text)

            # Extract tables (if available)
            try:
                page_tables = page.find_tables()
                for table in page_tables:
                    table_data = table.extract()
                    if table_data:
                        tables.append(
                            {
                                "page": page_num + 1,
                                "rows": table_data,
                            }
                        )
            except Exception:
                pass  # Table extraction not available in all PyMuPDF versions

        doc.close()

        full_text = "\n\n".join(text_parts)
        return full_text, tables


class DocumentProcessor:
    """High-level document processor combining chunking and PDF support.

    Teaching note: DocumentProcessor as orchestrator
    --------------------------------------------------
    This class orchestrates:
    1. File type detection (markdown, PDF, text)
    2. Content extraction (raw read or PDF parsing)
    3. Chunking with selected strategy
    4. Metadata attachment

    Design: Strategy pattern for chunking, composition for PDF processing.
    The processor doesn't know about retrieval or indexing -- it just
    produces chunks that any downstream pipeline can consume.
    """

    SUPPORTED_EXTENSIONS = {".md", ".txt", ".pdf"}

    def __init__(
        self,
        strategy: ChunkingStrategy = ChunkingStrategy.FIXED,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
    ) -> None:
        self.strategy = strategy
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

        self._chunker = self._create_chunker()
        self._pdf_processor = PDFProcessor()

    def _create_chunker(self) -> FixedChunker | SemanticChunker | LateChunker:
        """Create chunker instance based on strategy."""
        if self.strategy == ChunkingStrategy.FIXED:
            return FixedChunker(
                chunk_size=self.chunk_size,
                chunk_overlap=self.chunk_overlap,
            )
        elif self.strategy == ChunkingStrategy.SEMANTIC:
            return SemanticChunker(
                max_chunk_size=self.chunk_size,
            )
        elif self.strategy == ChunkingStrategy.LATE:
            return LateChunker(
                chunk_size=self.chunk_size,
                chunk_overlap=self.chunk_overlap,
            )
        else:
            raise ValueError(f"Unknown chunking strategy: {self.strategy}")

    def process_file(self, filepath: Path) -> list[Chunk]:
        """Process a single file into chunks.

        Args:
            filepath: Path to document file

        Returns:
            List of Chunk objects
        """
        if not filepath.exists():
            raise FileNotFoundError(f"File not found: {filepath}")

        if filepath.suffix.lower() not in self.SUPPORTED_EXTENSIONS:
            raise ValueError(
                f"Unsupported file type: {filepath.suffix}. Supported: {self.SUPPORTED_EXTENSIONS}"
            )

        metadata: dict[str, Any] = {
            "source": str(filepath),
            "file_type": filepath.suffix.lower(),
        }

        if filepath.suffix.lower() == ".pdf":
            text, tables = self._pdf_processor.extract(filepath)
            if tables:
                metadata["has_tables"] = True
                metadata["table_count"] = len(tables)
        else:
            text = filepath.read_text(encoding="utf-8")

        return self._chunker.chunk(text, metadata)

    def process_directory(
        self,
        directory: Path,
        file_types: list[str] | None = None,
    ) -> list[Chunk]:
        """Process all supported files in a directory.

        Args:
            directory: Directory to process
            file_types: Optional list of extensions to include (e.g., [".md", ".pdf"])

        Returns:
            List of all Chunk objects from all files
        """
        if not directory.exists():
            raise FileNotFoundError(f"Directory not found: {directory}")

        extensions = set(file_types) if file_types else self.SUPPORTED_EXTENSIONS

        all_chunks = []
        for filepath in sorted(directory.rglob("*")):
            if filepath.suffix.lower() in extensions and filepath.is_file():
                chunks = self.process_file(filepath)
                all_chunks.extend(chunks)

        return all_chunks
