"""Unit tests for metadata filtering module.

Focus areas:
- FilterCondition matching (EQ, NE, IN, CONTAINS)
- MetadataFilter composition (AND, OR, NOT)
- MetadataExtractor (path-based extraction)
- pre_filter and post_filter functions
- Edge cases (missing fields, empty metadata)
"""

from __future__ import annotations

from pathlib import Path

from llama_index.core.schema import NodeWithScore, TextNode

from src.rag.metadata_filter import (
    FilterCondition,
    FilterOperator,
    MetadataExtractor,
    MetadataFilter,
    post_filter,
    pre_filter,
)


class TestFilterCondition:
    """Test individual filter conditions."""

    def test_eq_match(self) -> None:
        """Test EQ operator matches exactly."""
        condition = FilterCondition("framework", FilterOperator.EQ, "fastapi")
        assert condition.matches({"framework": "fastapi"})
        assert not condition.matches({"framework": "react"})

    def test_eq_case_insensitive(self) -> None:
        """Test EQ is case-insensitive."""
        condition = FilterCondition("framework", FilterOperator.EQ, "FastAPI")
        assert condition.matches({"framework": "fastapi"})
        assert condition.matches({"framework": "FASTAPI"})

    def test_ne_match(self) -> None:
        """Test NE operator excludes."""
        condition = FilterCondition("framework", FilterOperator.NE, "react")
        assert condition.matches({"framework": "fastapi"})
        assert not condition.matches({"framework": "react"})

    def test_ne_missing_field(self) -> None:
        """Test NE matches when field is missing (field != value is true)."""
        condition = FilterCondition("framework", FilterOperator.NE, "react")
        assert condition.matches({})

    def test_in_match(self) -> None:
        """Test IN operator matches any value in list."""
        condition = FilterCondition("framework", FilterOperator.IN, ["fastapi", "pydantic"])
        assert condition.matches({"framework": "fastapi"})
        assert condition.matches({"framework": "pydantic"})
        assert not condition.matches({"framework": "react"})

    def test_in_single_value(self) -> None:
        """Test IN with single string value."""
        condition = FilterCondition("framework", FilterOperator.IN, "fastapi")
        assert condition.matches({"framework": "fastapi"})

    def test_contains_match(self) -> None:
        """Test CONTAINS operator for substring matching."""
        condition = FilterCondition("section", FilterOperator.CONTAINS, "auth")
        assert condition.matches({"section": "authentication"})
        assert condition.matches({"section": "OAuth2 Authorization"})
        assert not condition.matches({"section": "routing"})

    def test_missing_field_returns_false(self) -> None:
        """Test that missing field returns False for most operators."""
        condition = FilterCondition("framework", FilterOperator.EQ, "fastapi")
        assert not condition.matches({})

    def test_missing_field_ne_returns_true(self) -> None:
        """Test that NE with missing field returns True."""
        condition = FilterCondition("framework", FilterOperator.NE, "fastapi")
        assert condition.matches({})


class TestMetadataFilter:
    """Test composable metadata filters."""

    def test_single_condition_and(self) -> None:
        """Test filter with single AND condition."""
        f = MetadataFilter(
            [FilterCondition("framework", FilterOperator.EQ, "fastapi")],
            logic="and",
        )
        assert f.matches({"framework": "fastapi"})
        assert not f.matches({"framework": "react"})

    def test_multiple_conditions_and(self) -> None:
        """Test filter with multiple AND conditions."""
        f = MetadataFilter(
            [
                FilterCondition("framework", FilterOperator.EQ, "fastapi"),
                FilterCondition("doc_type", FilterOperator.EQ, "reference"),
            ],
            logic="and",
        )
        assert f.matches({"framework": "fastapi", "doc_type": "reference"})
        assert not f.matches({"framework": "fastapi", "doc_type": "tutorial"})
        assert not f.matches({"framework": "react", "doc_type": "reference"})

    def test_multiple_conditions_or(self) -> None:
        """Test filter with OR conditions."""
        f = MetadataFilter(
            [
                FilterCondition("framework", FilterOperator.EQ, "fastapi"),
                FilterCondition("framework", FilterOperator.EQ, "pydantic"),
            ],
            logic="or",
        )
        assert f.matches({"framework": "fastapi"})
        assert f.matches({"framework": "pydantic"})
        assert not f.matches({"framework": "react"})

    def test_empty_conditions(self) -> None:
        """Test filter with no conditions matches everything."""
        f = MetadataFilter(conditions=[])
        assert f.matches({"framework": "anything"})
        assert f.matches({})

    def test_and_composition(self) -> None:
        """Test MetadataFilter.and_() composition."""
        f1 = MetadataFilter([FilterCondition("framework", FilterOperator.EQ, "fastapi")])
        f2 = MetadataFilter([FilterCondition("doc_type", FilterOperator.EQ, "reference")])

        combined = MetadataFilter.and_(f1, f2)

        assert combined.matches({"framework": "fastapi", "doc_type": "reference"})
        assert not combined.matches({"framework": "fastapi", "doc_type": "tutorial"})

    def test_or_composition(self) -> None:
        """Test MetadataFilter.or_() composition."""
        f1 = MetadataFilter([FilterCondition("framework", FilterOperator.EQ, "fastapi")])
        f2 = MetadataFilter([FilterCondition("framework", FilterOperator.EQ, "react")])

        combined = MetadataFilter.or_(f1, f2)

        assert combined.matches({"framework": "fastapi"})
        assert combined.matches({"framework": "react"})
        assert not combined.matches({"framework": "spring"})

    def test_not_composition(self) -> None:
        """Test MetadataFilter.not_() negation."""
        f = MetadataFilter([FilterCondition("framework", FilterOperator.EQ, "react")])
        negated = MetadataFilter.not_(f)

        assert negated.matches({"framework": "fastapi"})
        assert not negated.matches({"framework": "react"})

    def test_complex_nested_filter(self) -> None:
        """Test complex nested filter: (fastapi OR pydantic) AND NOT tutorial."""
        frameworks = MetadataFilter.or_(
            MetadataFilter([FilterCondition("framework", FilterOperator.EQ, "fastapi")]),
            MetadataFilter([FilterCondition("framework", FilterOperator.EQ, "pydantic")]),
        )
        not_tutorial = MetadataFilter.not_(
            MetadataFilter([FilterCondition("doc_type", FilterOperator.EQ, "tutorial")])
        )
        combined = MetadataFilter.and_(frameworks, not_tutorial)

        assert combined.matches({"framework": "fastapi", "doc_type": "reference"})
        assert combined.matches({"framework": "pydantic", "doc_type": "guide"})
        assert not combined.matches({"framework": "fastapi", "doc_type": "tutorial"})
        assert not combined.matches({"framework": "react", "doc_type": "reference"})


class TestMetadataExtractor:
    """Test metadata extraction from file paths and content."""

    def test_extract_framework_from_path(self) -> None:
        """Test framework extraction from file path."""
        extractor = MetadataExtractor()
        metadata = extractor.extract(
            Path("datasets/tech_docs/fastapi/01_introduction.md"),
            "# Introduction\nFastAPI is a web framework.",
        )

        assert metadata["framework"] == "fastapi"

    def test_extract_section_from_heading(self) -> None:
        """Test section extraction from first heading."""
        extractor = MetadataExtractor()
        metadata = extractor.extract(
            Path("datasets/tech_docs/react/01_hooks.md"),
            "# React Hooks\n\nHooks let you use state in function components.",
        )

        assert metadata["section"] == "React Hooks"

    def test_extract_doc_type_from_filename(self) -> None:
        """Test doc_type classification from filename."""
        extractor = MetadataExtractor()

        intro_meta = extractor.extract(
            Path("datasets/tech_docs/fastapi/01_introduction.md"),
            "# Introduction\nBasic content.",
        )
        assert intro_meta["doc_type"] == "reference"

        testing_meta = extractor.extract(
            Path("datasets/tech_docs/fastapi/09_testing.md"),
            "# Testing\nHow to test.",
        )
        assert testing_meta["doc_type"] == "guide"

    def test_extract_source_path(self) -> None:
        """Test source path is always included."""
        extractor = MetadataExtractor()
        metadata = extractor.extract(
            Path("docs/unknown.md"),
            "# Unknown\nSome content.",
        )

        assert metadata["source"] == "docs/unknown.md"
        assert metadata["doc_type"] == "reference"  # Default

    def test_extract_pydantic_framework(self) -> None:
        """Test Pydantic framework detection."""
        extractor = MetadataExtractor()
        metadata = extractor.extract(
            Path("datasets/tech_docs/pydantic/01_models.md"),
            "# Pydantic Models\nValidation.",
        )

        assert metadata["framework"] == "pydantic"


class TestPreFilter:
    """Test pre-filtering (before retrieval)."""

    def test_pre_filter_basic(self) -> None:
        """Test pre_filter reduces node list."""
        nodes = [
            TextNode(text="FastAPI content", metadata={"framework": "fastapi"}),
            TextNode(text="React content", metadata={"framework": "react"}),
            TextNode(text="More FastAPI", metadata={"framework": "fastapi"}),
        ]

        filter_ = MetadataFilter([FilterCondition("framework", FilterOperator.EQ, "fastapi")])

        filtered = pre_filter(nodes, filter_)

        assert len(filtered) == 2
        assert all(n.metadata["framework"] == "fastapi" for n in filtered)

    def test_pre_filter_empty_result(self) -> None:
        """Test pre_filter when nothing matches."""
        nodes = [
            TextNode(text="React content", metadata={"framework": "react"}),
        ]

        filter_ = MetadataFilter([FilterCondition("framework", FilterOperator.EQ, "fastapi")])

        filtered = pre_filter(nodes, filter_)

        assert len(filtered) == 0

    def test_pre_filter_all_match(self) -> None:
        """Test pre_filter when everything matches."""
        nodes = [
            TextNode(text="FastAPI 1", metadata={"framework": "fastapi"}),
            TextNode(text="FastAPI 2", metadata={"framework": "fastapi"}),
        ]

        filter_ = MetadataFilter([FilterCondition("framework", FilterOperator.EQ, "fastapi")])

        filtered = pre_filter(nodes, filter_)

        assert len(filtered) == 2


class TestPostFilter:
    """Test post-filtering (after retrieval)."""

    def test_post_filter_basic(self) -> None:
        """Test post_filter narrows ranked results."""
        results = [
            NodeWithScore(
                node=TextNode(text="FastAPI auth", metadata={"framework": "fastapi"}),
                score=0.95,
            ),
            NodeWithScore(
                node=TextNode(text="React auth", metadata={"framework": "react"}),
                score=0.90,
            ),
            NodeWithScore(
                node=TextNode(text="FastAPI routes", metadata={"framework": "fastapi"}),
                score=0.85,
            ),
        ]

        filter_ = MetadataFilter([FilterCondition("framework", FilterOperator.EQ, "fastapi")])

        filtered = post_filter(results, filter_)

        assert len(filtered) == 2
        assert filtered[0].score == 0.95  # Ranking preserved
        assert filtered[1].score == 0.85

    def test_post_filter_preserves_order(self) -> None:
        """Test post_filter preserves original ranking order."""
        results = [
            NodeWithScore(
                node=TextNode(text="High score", metadata={"framework": "fastapi"}),
                score=0.99,
            ),
            NodeWithScore(
                node=TextNode(text="Filtered out", metadata={"framework": "react"}),
                score=0.95,
            ),
            NodeWithScore(
                node=TextNode(text="Low score", metadata={"framework": "fastapi"}),
                score=0.50,
            ),
        ]

        filter_ = MetadataFilter([FilterCondition("framework", FilterOperator.EQ, "fastapi")])

        filtered = post_filter(results, filter_)

        assert len(filtered) == 2
        assert filtered[0].score > filtered[1].score  # Order maintained


class TestTeachingComments:
    """Verify teaching comments exist in metadata filter implementation."""

    def test_module_docstring_teaches(self) -> None:
        """Verify module docstring documents pre vs post filter trade-offs."""
        import src.rag.metadata_filter as module

        docstring = module.__doc__ or ""

        assert "Pre-filter" in docstring or "pre-filter" in docstring
        assert "Post-filter" in docstring or "post-filter" in docstring
        assert "AND" in docstring
        assert "OR" in docstring
        assert "NOT" in docstring
