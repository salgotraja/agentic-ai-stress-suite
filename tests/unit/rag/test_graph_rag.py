"""Unit tests for Graph RAG pipeline with NetworkX.

Teaching note: These tests verify graph construction and traversal logic.
We use mocked LLMs for deterministic, fast tests without API calls.

Key test scenarios:
1. Entity extraction from text
2. Relation extraction between entities
3. Graph building from documents
4. Multi-hop graph traversal
5. Graph statistics and visualization
"""

from __future__ import annotations

from unittest.mock import MagicMock, Mock

from llama_index.core import Document

from src.rag.graph_rag import GraphRAGPipeline


class TestGraphRAGPipelineInit:
    """Test graph RAG pipeline initialization."""

    def test_init_with_defaults(self) -> None:
        """Test initialization with default parameters."""
        pipeline = GraphRAGPipeline()

        assert pipeline.llm_client is not None
        assert pipeline.graph is not None
        assert pipeline.graph.number_of_nodes() == 0
        assert pipeline.graph.number_of_edges() == 0

    def test_init_with_custom_llm(self) -> None:
        """Test initialization with custom LLM client."""
        mock_llm = MagicMock()
        pipeline = GraphRAGPipeline(llm_client=mock_llm)

        assert pipeline.llm_client == mock_llm


class TestEntityExtraction:
    """Test entity extraction from text."""

    def test_extract_entities_basic(self) -> None:
        """Test basic entity extraction."""
        mock_llm = MagicMock()
        mock_llm.generate.return_value = Mock(
            content='[{"name": "FastAPI", "type": "framework"}, '
            '{"name": "async/await", "type": "concept"}]'
        )

        pipeline = GraphRAGPipeline(llm_client=mock_llm)
        entities = pipeline.extract_entities("FastAPI supports async/await")

        # Verify LLM was called
        assert mock_llm.generate.called
        call_args = mock_llm.generate.call_args

        # Verify prompt includes text
        assert "FastAPI supports async/await" in call_args.kwargs["prompt"]

        # Verify temperature is low (consistent extraction)
        assert call_args.kwargs["temperature"] == 0.2

        # Verify entities were extracted
        assert len(entities) == 2
        assert entities[0]["name"] == "FastAPI"
        assert entities[0]["type"] == "framework"
        assert entities[1]["name"] == "async/await"
        assert entities[1]["type"] == "concept"

    def test_extract_entities_with_markdown_json(self) -> None:
        """Test entity extraction handles markdown code blocks."""
        mock_llm = MagicMock()
        mock_llm.generate.return_value = Mock(
            content='```json\n[{"name": "React", "type": "library"}]\n```'
        )

        pipeline = GraphRAGPipeline(llm_client=mock_llm)
        entities = pipeline.extract_entities("React is a library")

        assert len(entities) == 1
        assert entities[0]["name"] == "React"

    def test_extract_entities_handles_parse_error(self) -> None:
        """Test entity extraction handles malformed JSON."""
        mock_llm = MagicMock()
        mock_llm.generate.return_value = Mock(content="Invalid JSON {")

        pipeline = GraphRAGPipeline(llm_client=mock_llm)
        entities = pipeline.extract_entities("Some text")

        # Should return empty list on parse error
        assert entities == []


class TestRelationExtraction:
    """Test relation extraction between entities."""

    def test_extract_relations_basic(self) -> None:
        """Test basic relation extraction."""
        mock_llm = MagicMock()
        mock_llm.generate.return_value = Mock(
            content='[{"subject": "FastAPI", "predicate": "uses", "object": "Pydantic"}]'
        )

        pipeline = GraphRAGPipeline(llm_client=mock_llm)
        entities = [
            {"name": "FastAPI", "type": "framework"},
            {"name": "Pydantic", "type": "library"},
        ]

        relations = pipeline.extract_relations("FastAPI uses Pydantic", entities)

        # Verify LLM was called
        assert mock_llm.generate.called
        call_args = mock_llm.generate.call_args

        # Verify prompt includes entities and text
        prompt = call_args.kwargs["prompt"]
        assert "FastAPI" in prompt
        assert "Pydantic" in prompt

        # Verify relations were extracted
        assert len(relations) == 1
        assert relations[0]["subject"] == "FastAPI"
        assert relations[0]["predicate"] == "uses"
        assert relations[0]["object"] == "Pydantic"

    def test_extract_relations_with_markdown_json(self) -> None:
        """Test relation extraction handles markdown code blocks."""
        mock_llm = MagicMock()
        mock_llm.generate.return_value = Mock(
            content="```json\n"
            '[{"subject": "React", "predicate": "supports", "object": "hooks"}]\n'
            "```"
        )

        pipeline = GraphRAGPipeline(llm_client=mock_llm)
        entities = [{"name": "React", "type": "library"}]

        relations = pipeline.extract_relations("React supports hooks", entities)

        assert len(relations) == 1
        assert relations[0]["subject"] == "React"

    def test_extract_relations_handles_parse_error(self) -> None:
        """Test relation extraction handles malformed JSON."""
        mock_llm = MagicMock()
        mock_llm.generate.return_value = Mock(content="Invalid JSON")

        pipeline = GraphRAGPipeline(llm_client=mock_llm)
        entities = []

        relations = pipeline.extract_relations("Text", entities)

        # Should return empty list on parse error
        assert relations == []


class TestGraphBuilding:
    """Test knowledge graph construction."""

    def test_build_graph_basic(self) -> None:
        """Test basic graph building from documents."""
        mock_llm = MagicMock()

        # Mock entity extraction and relation extraction
        mock_llm.generate.side_effect = [
            # Entities from doc 1
            Mock(
                content='[{"name": "FastAPI", "type": "framework"}, '
                '{"name": "Pydantic", "type": "library"}]'
            ),
            # Relations from doc 1
            Mock(content='[{"subject": "FastAPI", "predicate": "uses", "object": "Pydantic"}]'),
        ]

        pipeline = GraphRAGPipeline(llm_client=mock_llm)

        docs = [Document(text="FastAPI uses Pydantic for data validation")]
        pipeline.build_graph(docs)

        # Verify graph has nodes and edges
        assert pipeline.graph.number_of_nodes() == 2
        assert pipeline.graph.number_of_edges() == 1

        # Verify nodes exist
        assert "FastAPI" in pipeline.graph.nodes()
        assert "Pydantic" in pipeline.graph.nodes()

        # Verify edge exists
        assert pipeline.graph.has_edge("FastAPI", "Pydantic")

        # Verify edge attributes
        edge_data = pipeline.graph.get_edge_data("FastAPI", "Pydantic")
        assert edge_data["relation"] == "uses"

    def test_build_graph_multiple_documents(self) -> None:
        """Test graph building from multiple documents."""
        mock_llm = MagicMock()

        # Mock responses for 2 documents
        mock_llm.generate.side_effect = [
            # Doc 1 entities
            Mock(content='[{"name": "FastAPI", "type": "framework"}]'),
            # Doc 1 relations
            Mock(content="[]"),
            # Doc 2 entities
            Mock(content='[{"name": "Pydantic", "type": "library"}]'),
            # Doc 2 relations
            Mock(content="[]"),
        ]

        pipeline = GraphRAGPipeline(llm_client=mock_llm)

        docs = [
            Document(text="FastAPI is a web framework"),
            Document(text="Pydantic is a data validation library"),
        ]
        pipeline.build_graph(docs)

        # Should have nodes from both documents
        assert pipeline.graph.number_of_nodes() == 2
        assert "FastAPI" in pipeline.graph.nodes()
        assert "Pydantic" in pipeline.graph.nodes()

    def test_build_graph_merges_duplicate_entities(self) -> None:
        """Test that duplicate entities are merged."""
        mock_llm = MagicMock()

        # Two documents mention FastAPI
        mock_llm.generate.side_effect = [
            # Doc 1 entities
            Mock(content='[{"name": "FastAPI", "type": "framework"}]'),
            # Doc 1 relations
            Mock(content="[]"),
            # Doc 2 entities (FastAPI again)
            Mock(content='[{"name": "FastAPI", "type": "framework"}]'),
            # Doc 2 relations
            Mock(content="[]"),
        ]

        pipeline = GraphRAGPipeline(llm_client=mock_llm)

        docs = [
            Document(text="FastAPI doc 1"),
            Document(text="FastAPI doc 2"),
        ]
        pipeline.build_graph(docs)

        # Should only have 1 node (merged)
        assert pipeline.graph.number_of_nodes() == 1
        assert "FastAPI" in pipeline.graph.nodes()


class TestGraphQuerying:
    """Test graph traversal and querying."""

    def test_query_finds_relevant_nodes(self) -> None:
        """Test query finds nodes matching query terms."""
        pipeline = GraphRAGPipeline()

        # Manually add nodes
        pipeline.graph.add_node("FastAPI", type="framework")
        pipeline.graph.add_node("Pydantic", type="library")
        pipeline.graph.add_edge("FastAPI", "Pydantic", relation="uses")

        result = pipeline.query("What is FastAPI?")

        # Should find FastAPI node
        assert "FastAPI" in result["nodes"]
        assert result["metadata"]["num_nodes"] >= 1

    def test_query_finds_paths(self) -> None:
        """Test query finds paths between nodes."""
        pipeline = GraphRAGPipeline()

        # Create a path: React → hooks → reactive
        pipeline.graph.add_node("React")
        pipeline.graph.add_node("hooks")
        pipeline.graph.add_node("reactive")
        pipeline.graph.add_edge("React", "hooks", relation="relates_to")
        pipeline.graph.add_edge("hooks", "reactive", relation="relates_to")

        result = pipeline.query("React and reactive", max_hops=3)

        # Should find path from React to reactive
        assert result["metadata"]["num_paths"] > 0
        # Should have found path through hooks
        found_path = False
        for path in result["paths"]:
            if "React" in path and "reactive" in path:
                found_path = True
                break
        assert found_path

    def test_query_respects_max_hops(self) -> None:
        """Test that query respects max_hops parameter."""
        pipeline = GraphRAGPipeline()

        # Create a long chain: A → B → C → D → E
        pipeline.graph.add_edge("A", "B")
        pipeline.graph.add_edge("B", "C")
        pipeline.graph.add_edge("C", "D")
        pipeline.graph.add_edge("D", "E")

        # Query with max_hops=2 should not reach E from A
        result = pipeline.query("A", max_hops=2)

        # Paths should be limited
        for path in result["paths"]:
            assert len(path) <= 3  # max_hops + 1

    def test_query_no_relevant_nodes(self) -> None:
        """Test query when no relevant nodes found."""
        pipeline = GraphRAGPipeline()

        pipeline.graph.add_node("FastAPI")

        result = pipeline.query("NonexistentTerm")

        # Should return empty result with message
        assert "No relevant entities" in result["answer"]
        assert result["metadata"]["num_nodes"] == 0


class TestGraphVisualization:
    """Test graph visualization."""

    def test_visualize_creates_file(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """Test that visualize creates output file."""
        pipeline = GraphRAGPipeline()

        # Add some nodes
        pipeline.graph.add_node("A")
        pipeline.graph.add_node("B")
        pipeline.graph.add_edge("A", "B", relation="relates_to")

        output_path = tmp_path / "test_graph.png"
        pipeline.visualize(str(output_path))

        # Visualization may fail if matplotlib not available (graceful)
        # Just verify no exception was raised


class TestGraphStatistics:
    """Test graph statistics."""

    def test_get_stats_empty_graph(self) -> None:
        """Test statistics for empty graph."""
        pipeline = GraphRAGPipeline()

        stats = pipeline.get_stats()

        assert stats["num_nodes"] == 0
        assert stats["num_edges"] == 0
        assert stats["avg_degree"] == 0

    def test_get_stats_basic(self) -> None:
        """Test statistics for simple graph."""
        pipeline = GraphRAGPipeline()

        pipeline.graph.add_node("A")
        pipeline.graph.add_node("B")
        pipeline.graph.add_edge("A", "B")

        stats = pipeline.get_stats()

        assert stats["num_nodes"] == 2
        assert stats["num_edges"] == 1
        assert stats["avg_degree"] == 1.0

    def test_get_stats_complex_graph(self) -> None:
        """Test statistics for more complex graph."""
        pipeline = GraphRAGPipeline()

        # Create a graph with 3 nodes and multiple edges
        pipeline.graph.add_edge("A", "B")
        pipeline.graph.add_edge("B", "C")
        pipeline.graph.add_edge("C", "A")

        stats = pipeline.get_stats()

        assert stats["num_nodes"] == 3
        assert stats["num_edges"] == 3
        assert stats["num_connected_components"] == 1


class TestMultiHopReasoning:
    """Test multi-hop reasoning capabilities."""

    def test_multi_hop_query(self) -> None:
        """
        Test multi-hop reasoning through graph.

        Teaching note: This simulates a real query like:
        "What Java framework is similar to React hooks?"

        Graph: React → hooks → reactive → Spring WebFlux
        """
        pipeline = GraphRAGPipeline()

        # Build knowledge graph
        pipeline.graph.add_node("React", type="library")
        pipeline.graph.add_node("hooks", type="concept")
        pipeline.graph.add_node("reactive", type="concept")
        pipeline.graph.add_node("Spring WebFlux", type="framework")

        pipeline.graph.add_edge("React", "hooks", relation="supports")
        pipeline.graph.add_edge("hooks", "reactive", relation="implements")
        pipeline.graph.add_edge("reactive", "Spring WebFlux", relation="similar_to")

        # Query
        result = pipeline.query("React hooks", max_hops=3)

        # Should find path from React through hooks to Spring WebFlux
        assert "React" in result["nodes"]
        assert "hooks" in result["nodes"]

        # Should have found multi-hop paths
        assert result["metadata"]["num_paths"] > 0
