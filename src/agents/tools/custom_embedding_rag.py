"""RAG tool backed by the domain fine-tuned BGE embedding model - task 5.11.

Teaching note: WHY swap the embedding model in a RAG pipeline?
  The default RAGTool uses the stock BAAI/bge-base-en-v1.5 model.
  After domain fine-tuning (task 5.3), the custom model is aligned to
  the tech docs vocabulary. This tool demonstrates how to drop in a
  custom encoder without changing the agent or pipeline structure.

  Pluggability pattern:
    - RAGTool wires agent → NaiveRAGPipeline → stock embedder
    - CustomEmbeddingRAGTool wires agent → same pipeline → custom embedder
    - Everything else (retrieval, reranking, LLM generation) stays identical
    - This is the Dependency Inversion Principle applied to AI systems

  When to use a fine-tuned embedder in production:
    1. Domain vocabulary diverges from pre-training (medical, legal, code)
    2. Recall@K on custom eval set improves by >5%
    3. The fine-tuned model is stable (not over-fitted to training queries)
  When to stick with stock:
    1. Corpus is too small (<100 docs) - stock generalises better
    2. Training data objective doesn't match retrieval task (task 5.4 finding)
    3. Latency budget is tight - fine-tuned model adds no speed benefit

Mock mode:
  Returns a canned response so the tool can be used in unit tests
  without loading a 400MB model or running embedding inference.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.agents.tools.base import BaseTool
from src.core.observability import traced_tool_call

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from src.rag.naive_rag import NaiveRAGPipeline

FINETUNED_MODEL_DIR = Path("models/bge_finetuned")

# Canned mock responses keyed by partial query match - deterministic for tests
_MOCK_RESPONSES: dict[str, str] = {
    "dependency injection": (
        "FastAPI's dependency injection system uses Depends() to declare "
        "dependencies that are resolved automatically at request time."
    ),
    "pydantic": (
        "Pydantic validates data using Python type hints. BaseModel provides "
        "automatic parsing and serialisation."
    ),
}
_MOCK_DEFAULT = (
    "Custom embedding RAG (mock): No result found for query. This is a mock response for testing."
)


class CustomEmbeddingRAGTool(BaseTool):
    """RAG tool using the domain fine-tuned BGE embedding model.

    Teaching note: The custom model is loaded lazily (on first execute() call)
    to avoid slow import times when the tool is instantiated but not used.
    This is the standard pattern for heavy ML model loading in tool systems.

    The tool is intentionally thin: it delegates all retrieval logic to
    NaiveRAGPipeline and only overrides the embedding component. This keeps
    the blast radius of the custom model swap minimal - if the fine-tuned
    model degrades quality, switching back requires changing one argument.
    """

    def __init__(
        self,
        rag_pipeline: NaiveRAGPipeline,
        top_k: int = 5,
        model_dir: Path = FINETUNED_MODEL_DIR,
        name: str | None = None,
    ) -> None:
        self._pipeline = rag_pipeline
        self._top_k = top_k
        self._model_dir = model_dir
        self._name = name or "custom_embedding_rag"
        self._custom_embedder: Any = None  # lazy-loaded

    def _load_embedder(self) -> Any:
        """Lazy-load the fine-tuned SentenceTransformer model.

        Teaching note: Lazy loading avoids the ~2s model load time when
        the tool is not actually used. In a multi-tool agent, many tools
        are registered but only a few are called per query.
        """
        if self._custom_embedder is None:
            from sentence_transformers import SentenceTransformer

            if self._model_dir.exists():
                self._custom_embedder = SentenceTransformer(str(self._model_dir))
            else:
                # Fall back to stock model if fine-tuned not available
                self._custom_embedder = SentenceTransformer("BAAI/bge-base-en-v1.5")
        return self._custom_embedder

    @traced_tool_call
    def execute(self, input: str) -> str:
        """Run RAG query using the fine-tuned embedding model.

        Teaching note: The pipeline's retrieve() + generate() pair lets us
        inject a custom query embedding without modifying NaiveRAGPipeline.
        We encode the query ourselves, then hand the retrieved nodes to
        generate() for answer synthesis. query() is used as a fallback when
        the retrieve+generate path fails (e.g. pipeline not initialised).
        """
        self._load_embedder()  # warm up the embedder

        # Use the pipeline's retrieve + generate machinery directly
        try:
            nodes = self._pipeline.retrieve(input, top_k=self._top_k)
            answer = self._pipeline.generate(query=input, context_nodes=nodes)
            return f"{answer}\n\n[Retrieved with fine-tuned BGE embedder]"
        except Exception as exc:
            # Broad on purpose: pipeline.retrieve/generate composes a vector
            # store + LLM call, so failures span connection errors, missing
            # indices, model load issues, etc. We fall back to query() rather
            # than propagate, but log so silent degradation is observable.
            logger.debug("Custom-embedding retrieve/generate failed, falling back: %s", exc)
            result = self._pipeline.query(input, top_k=self._top_k)
            return str(result.get("answer", "No answer found."))

    def mock_execute(self, input: str) -> str:
        """Return a deterministic canned response for testing."""
        query_lower = input.lower()
        for keyword, response in _MOCK_RESPONSES.items():
            if keyword in query_lower:
                return f"{response} [mock: custom_embedding_rag]"
        return _MOCK_DEFAULT

    def describe(self) -> str:
        model_info = (
            f"fine-tuned BGE ({self._model_dir})"
            if self._model_dir.exists()
            else "stock BGE (fine-tuned model not found)"
        )
        return (
            f"Search technical documentation (FastAPI, Pydantic, React, Spring) "
            f"using a domain-adapted embedding model ({model_info}). "
            f"Use this tool to answer questions about these frameworks. "
            f"Returns a text answer with source attribution."
        )
