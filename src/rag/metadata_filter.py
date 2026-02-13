"""Metadata filtering for RAG retrieval results.

This module provides composable metadata filters (AND/OR/NOT) for narrowing
retrieval results by document attributes like framework, doc_type, and section.

Teaching note: Pre-filter vs post-filter strategies
----------------------------------------------------
There are two strategies for applying metadata filters in RAG:

1. Pre-filter (filter BEFORE retrieval):
   - Removes documents from the search pool before BM25/dense search
   - Reduces search space -> faster retrieval, fewer candidates
   - Risk: May eliminate documents that are relevant but tagged differently
   - Best for: Large corpora where you KNOW the target metadata
   - Example: "Show me only FastAPI docs" when querying about FastAPI

2. Post-filter (filter AFTER retrieval):
   - Runs full retrieval first, then filters results
   - Preserves ranking quality from hybrid search + reranking
   - Risk: May return fewer than top-K results if many are filtered out
   - Best for: Exploratory queries, cross-category relevance possible
   - Example: "Best practices" query that might span multiple frameworks

Trade-offs in practice:
- Pre-filter: Faster (smaller search space), but may miss relevant cross-category docs
- Post-filter: Slower (full retrieval), but preserves ranking and catches edge cases
- Recommendation: Default to post-filter for safety; use pre-filter when metadata is certain

Composability (AND/OR/NOT):
- AND: All conditions must match (strict filtering)
- OR: Any condition can match (broad filtering)
- NOT: Invert a filter (exclusion)
- Nest freely: and_(or_(A, B), not_(C)) for complex queries
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from llama_index.core.schema import NodeWithScore, TextNode


class FilterOperator(str, Enum):
    """Operators for metadata filter conditions.

    Teaching note: Operator design
    -------------------------------
    Keep operators simple and SQL-like for familiarity:
    - EQ: Exact match (most common)
    - NE: Exclusion
    - IN: Match any value in a list
    - CONTAINS: Substring match (useful for partial framework names)
    """

    EQ = "eq"
    NE = "ne"
    IN = "in"
    CONTAINS = "contains"


@dataclass
class FilterCondition:
    """A single metadata filter condition.

    Attributes:
        field: Metadata field name (e.g., "framework", "doc_type")
        operator: Comparison operator
        value: Expected value or list of values (for IN operator)
    """

    field: str
    operator: FilterOperator
    value: str | list[str]

    def matches(self, metadata: dict[str, Any]) -> bool:
        """Check if metadata matches this condition.

        Args:
            metadata: Document metadata dictionary

        Returns:
            True if the metadata satisfies this condition
        """
        actual = metadata.get(self.field)
        if actual is None:
            return self.operator == FilterOperator.NE

        actual_str = str(actual).lower()

        if self.operator == FilterOperator.EQ:
            return actual_str == str(self.value).lower()
        elif self.operator == FilterOperator.NE:
            return actual_str != str(self.value).lower()
        elif self.operator == FilterOperator.IN:
            if not isinstance(self.value, list):
                return actual_str == str(self.value).lower()
            return actual_str in [str(v).lower() for v in self.value]
        elif self.operator == FilterOperator.CONTAINS:
            return str(self.value).lower() in actual_str
        return False


class MetadataFilter:
    """Composable metadata filter supporting AND/OR/NOT logic.

    Teaching note: Filter composition pattern
    ------------------------------------------
    Filters compose via static methods:
    - MetadataFilter.and_(f1, f2): Both must match
    - MetadataFilter.or_(f1, f2): Either must match
    - MetadataFilter.not_(f1): Invert result

    Example:
        # Find FastAPI or Pydantic reference docs
        filter = MetadataFilter.or_(
            MetadataFilter([FilterCondition("framework", FilterOperator.EQ, "fastapi")]),
            MetadataFilter([FilterCondition("framework", FilterOperator.EQ, "pydantic")]),
        )

        # Find non-tutorial FastAPI docs
        filter = MetadataFilter.and_(
            MetadataFilter([FilterCondition("framework", FilterOperator.EQ, "fastapi")]),
            MetadataFilter.not_(
                MetadataFilter([FilterCondition("doc_type", FilterOperator.EQ, "tutorial")])
            ),
        )
    """

    def __init__(
        self,
        conditions: list[FilterCondition],
        logic: Literal["and", "or"] = "and",
    ) -> None:
        self.conditions = conditions
        self.logic = logic
        self._negated = False
        self._sub_filters: list[MetadataFilter] = []
        self._sub_logic: Literal["and", "or"] = "and"

    def matches(self, metadata: dict[str, Any]) -> bool:
        """Check if metadata matches this filter.

        Args:
            metadata: Document metadata dictionary

        Returns:
            True if the metadata satisfies the filter
        """
        # Handle sub-filters (from and_/or_ composition)
        if self._sub_filters:
            if self._sub_logic == "and":
                result = all(f.matches(metadata) for f in self._sub_filters)
            else:
                result = any(f.matches(metadata) for f in self._sub_filters)
            return not result if self._negated else result

        # Handle direct conditions
        if not self.conditions:
            result = True
        elif self.logic == "and":
            result = all(c.matches(metadata) for c in self.conditions)
        else:
            result = any(c.matches(metadata) for c in self.conditions)

        return not result if self._negated else result

    @staticmethod
    def and_(*filters: MetadataFilter) -> MetadataFilter:
        """Combine filters with AND logic."""
        combined = MetadataFilter(conditions=[], logic="and")
        combined._sub_filters = list(filters)
        combined._sub_logic = "and"
        return combined

    @staticmethod
    def or_(*filters: MetadataFilter) -> MetadataFilter:
        """Combine filters with OR logic."""
        combined = MetadataFilter(conditions=[], logic="or")
        combined._sub_filters = list(filters)
        combined._sub_logic = "or"
        return combined

    @staticmethod
    def not_(filter_: MetadataFilter) -> MetadataFilter:
        """Negate a filter."""
        negated = MetadataFilter(
            conditions=filter_.conditions,
            logic=filter_.logic,
        )
        negated._negated = not filter_._negated
        negated._sub_filters = filter_._sub_filters
        negated._sub_logic = filter_._sub_logic
        return negated


class MetadataExtractor:
    """Extract metadata from document file paths and content.

    Teaching note: Metadata extraction strategy
    --------------------------------------------
    In this project, document metadata comes from two sources:

    1. File path convention:
       datasets/tech_docs/{framework}/{filename}.md
       -> framework = "fastapi", source = "fastapi/01_introduction.md"

    2. Content headers:
       First H1/H2 heading -> section name
       Content keywords -> doc_type classification

    This avoids requiring a separate metadata database while still enabling
    rich filtering. The trade-off is that metadata quality depends on
    consistent file naming and heading conventions.
    """

    FRAMEWORK_KEYWORDS = {
        "fastapi": "fastapi",
        "pydantic": "pydantic",
        "react": "react",
        "spring": "spring",
    }

    DOC_TYPE_KEYWORDS = {
        "introduction": "reference",
        "getting started": "tutorial",
        "tutorial": "tutorial",
        "guide": "guide",
        "reference": "reference",
        "api": "reference",
        "best practices": "guide",
        "advanced": "guide",
        "testing": "guide",
        "deployment": "guide",
        "security": "guide",
    }

    def extract(self, doc_path: Path, content: str) -> dict[str, Any]:
        """Extract metadata from document path and content.

        Args:
            doc_path: Path to the document file
            content: Document text content

        Returns:
            Metadata dictionary with: source, framework, doc_type, section
        """
        parts = doc_path.parts
        metadata: dict[str, Any] = {
            "source": str(doc_path),
        }

        # Extract framework from path
        for part in parts:
            part_lower = part.lower()
            if part_lower in self.FRAMEWORK_KEYWORDS:
                metadata["framework"] = self.FRAMEWORK_KEYWORDS[part_lower]
                break

        # Extract section from first heading
        for line in content.split("\n"):
            stripped = line.strip()
            if stripped.startswith("#"):
                heading = stripped.lstrip("#").strip()
                metadata["section"] = heading
                break

        # Classify doc_type from filename and content
        filename_lower = doc_path.stem.lower().replace("_", " ")
        content_lower = content[:500].lower()

        for keyword, doc_type in self.DOC_TYPE_KEYWORDS.items():
            if keyword in filename_lower or keyword in content_lower:
                metadata["doc_type"] = doc_type
                break

        if "doc_type" not in metadata:
            metadata["doc_type"] = "reference"

        return metadata


def pre_filter(
    nodes: list[TextNode],
    filter_: MetadataFilter,
) -> list[TextNode]:
    """Filter nodes BEFORE retrieval (reduces search space).

    Teaching note: Pre-filtering trade-offs
    ----------------------------------------
    Pre-filtering modifies the candidate pool:
    - Faster retrieval: Fewer documents to search through
    - Risk: May eliminate relevant documents tagged with unexpected metadata
    - Use when: Metadata is reliable and query intent is clear

    Example scenario:
    Query: "How does FastAPI handle authentication?"
    Pre-filter: framework="fastapi"
    Result: Only FastAPI docs searched -> faster, but misses Spring comparison docs

    Args:
        nodes: All indexed nodes
        filter_: Metadata filter to apply

    Returns:
        Filtered subset of nodes
    """
    return [node for node in nodes if filter_.matches(node.metadata)]


def post_filter(
    results: list[NodeWithScore],
    filter_: MetadataFilter,
) -> list[NodeWithScore]:
    """Filter results AFTER retrieval (preserves ranking).

    Teaching note: Post-filtering trade-offs
    -----------------------------------------
    Post-filtering narrows already-ranked results:
    - Preserves ranking quality from hybrid search + reranking
    - Risk: May return fewer than top-K results
    - Use when: Ranking quality matters more than speed

    Example scenario:
    Query: "What are dependency injection patterns?"
    Retrieve: top-20 from all frameworks
    Post-filter: framework="spring"
    Result: Only Spring docs from ranked results -> quality ranking preserved

    Args:
        results: Retrieved and ranked results
        filter_: Metadata filter to apply

    Returns:
        Filtered results preserving original ranking order
    """
    return [r for r in results if filter_.matches(r.node.metadata)]
