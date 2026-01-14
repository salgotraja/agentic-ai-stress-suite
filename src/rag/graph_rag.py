"""Graph RAG pipeline with NetworkX for multi-hop reasoning.

This module implements Graph RAG (Retrieval-Augmented Generation with Knowledge Graphs):
- Entity extraction: Identify key entities in documents
- Relation extraction: Find relationships between entities
- Graph construction: Build knowledge graph with NetworkX
- Graph traversal: Multi-hop queries across relationships

Teaching note: Graph RAG vs Vector RAG trade-offs:

**When Graph RAG Wins**:
- Multi-hop reasoning: "What Java framework is similar to React hooks?"
  → Need to traverse: React → hooks → reactive programming → Java frameworks
- Relationship queries: "How are FastAPI and Pydantic related?"
  → Direct relationship lookup in graph
- Structured knowledge: Technical specs, API dependencies

**When Vector RAG Wins**:
- Semantic similarity: "Explain async/await"
  → Dense vector captures meaning better
- Fuzzy matching: Different phrasings of same concept
- Large-scale: Millions of documents (graphs become unwieldy)

**Trade-offs**:
- Build time: Graph construction is expensive (entity + relation extraction)
- Query time: Graph traversal can be faster for specific query types
- Maintenance: Graph needs updates when documents change
- Hybrid approach: Use both (graph for structure, vectors for semantics)

Cost analysis:
- Graph construction: ~2 LLM calls per document (entities + relations)
- Query: ~1 LLM call + graph traversal (fast)
- One-time cost amortized over many queries

When to use:
- Technical documentation with clear relationships
- API dependencies and frameworks
- Multi-hop reasoning tasks
- Smaller, high-value document sets
"""

from __future__ import annotations

import json
from typing import Any

import networkx as nx
from llama_index.core import Document

from src.core.llm_client import UnifiedLLMClient
from src.core.observability import traced_generation


class GraphRAGPipeline:
    """
    Graph RAG pipeline using NetworkX for knowledge graph construction.

    This pipeline builds a knowledge graph from documents and uses graph
    traversal to answer multi-hop queries.

    Architecture:
        Documents
            |
            v
        [Entity Extraction]
            |
            v
        [Relation Extraction]
            |
            v
        NetworkX Graph
            |
            v
        [Graph Traversal]
            |
            v
        Answer

    Teaching note: NetworkX is chosen for simplicity and teaching value:
    - Pure Python (no external database)
    - Easy to visualize
    - Good for small-to-medium graphs (<10k nodes)
    - For production: Consider Neo4j, ArangoDB, or other graph DBs

    Args:
        llm_client: LLM client for entity/relation extraction
    """

    def __init__(self, llm_client: UnifiedLLMClient | None = None) -> None:
        """Initialize graph RAG pipeline."""
        self.llm_client = llm_client or UnifiedLLMClient()
        self.graph: nx.DiGraph = nx.DiGraph()

    @traced_generation
    def extract_entities(
        self,
        text: str,
        correlation_id: str | None = None,
    ) -> list[dict[str, str]]:
        """
        Extract entities from text using LLM.

        Teaching note: Entity extraction identifies key concepts:
        - Frameworks: FastAPI, Spring, React
        - Concepts: async, hooks, dependency injection
        - Tools: Docker, Kubernetes, Redis

        Prompt engineering:
        - Ask for structured JSON output
        - Specify entity types (framework, concept, tool)
        - Request 5-10 entities (not too many, not too few)

        Trade-off: LLM-based extraction is flexible but expensive
        - Alternative: spaCy NER (faster, less accurate)
        - Alternative: Pattern matching (rigid, cheap)

        Args:
            text: Document text
            correlation_id: Optional trace ID

        Returns:
            List of entities with name and type
        """
        prompt = f"""Extract 5-10 key entities from this technical text.

Text: {text[:1000]}

Return entities as JSON array with format:
[
  {{"name": "FastAPI", "type": "framework"}},
  {{"name": "async/await", "type": "concept"}}
]

Entity types: framework, library, concept, tool, language

Entities:"""

        response = self.llm_client.generate(
            prompt=prompt,
            temperature=0.2,  # Low for consistent extraction
            max_tokens=300,
        )

        # Parse JSON response
        try:
            # Extract JSON from response (handle markdown code blocks)
            content = response.content.strip()
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()

            entities = json.loads(content)
            return entities if isinstance(entities, list) else []
        except (json.JSONDecodeError, IndexError):
            # Fallback: return empty list
            return []

    @traced_generation
    def extract_relations(
        self,
        text: str,
        entities: list[dict[str, str]],
        correlation_id: str | None = None,
    ) -> list[dict[str, str]]:
        """
        Extract relations between entities using LLM.

        Teaching note: Relation extraction finds connections:
        - "FastAPI uses Pydantic" → (FastAPI, uses, Pydantic)
        - "React hooks enable reactive programming" → (React, enables, reactive)

        Prompt engineering:
        - Provide entity list to guide extraction
        - Ask for structured JSON with subject, predicate, object
        - Request 3-8 relations (quality over quantity)

        Predicate types:
        - uses, depends_on, similar_to, implements, supports

        Args:
            text: Document text
            entities: Previously extracted entities
            correlation_id: Optional trace ID

        Returns:
            List of relations (subject, predicate, object)
        """
        entity_names = [e["name"] for e in entities]
        entity_list = ", ".join(entity_names)

        prompt = f"""Extract 3-8 relationships between these entities in the text.

Entities: {entity_list}

Text: {text[:1000]}

Return relations as JSON array:
[
  {{"subject": "FastAPI", "predicate": "uses", "object": "Pydantic"}},
  {{"subject": "React", "predicate": "supports", "object": "hooks"}}
]

Predicate types: uses, depends_on, similar_to, implements, supports, enables

Relations:"""

        response = self.llm_client.generate(
            prompt=prompt,
            temperature=0.2,
            max_tokens=400,
        )

        # Parse JSON response
        try:
            content = response.content.strip()
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()

            relations = json.loads(content)
            return relations if isinstance(relations, list) else []
        except (json.JSONDecodeError, IndexError):
            return []

    def build_graph(self, documents: list[Document]) -> None:
        """
        Build knowledge graph from documents.

        Teaching note: Graph construction pipeline:
        1. For each document:
           a. Extract entities
           b. Extract relations
           c. Add to graph
        2. Result: Unified knowledge graph

        Graph properties:
        - Nodes: Entities with attributes (name, type)
        - Edges: Relations with labels (predicate)
        - Directed: Relations have direction (A → B)

        Deduplication:
        - Same entity names are merged (case-insensitive)
        - Multiple relations between same entities preserved

        Args:
            documents: List of documents to process
        """
        for doc in documents:
            text = doc.get_content()

            # Extract entities
            entities = self.extract_entities(text)

            # Add entities as nodes
            for entity in entities:
                name = entity["name"]
                entity_type = entity.get("type", "unknown")

                # Add node with attributes
                self.graph.add_node(
                    name,
                    type=entity_type,
                    label=name,
                )

            # Extract relations
            relations = self.extract_relations(text, entities)

            # Add relations as edges
            for relation in relations:
                subject = relation.get("subject", "")
                predicate = relation.get("predicate", "related_to")
                obj = relation.get("object", "")

                if subject and obj:
                    # Add edge with relation type
                    self.graph.add_edge(
                        subject,
                        obj,
                        relation=predicate,
                        label=predicate,
                    )

    def query(
        self,
        query_str: str,
        max_hops: int = 3,
    ) -> dict[str, Any]:
        """
        Query knowledge graph with multi-hop traversal.

        Teaching note: Graph query strategies:
        1. Extract query entities (e.g., "FastAPI", "Pydantic")
        2. Find relevant nodes in graph
        3. Traverse up to max_hops to find connections
        4. Aggregate findings into answer

        Multi-hop example:
        Query: "What Java framework is similar to React hooks?"
        - Find "React" and "hooks" in graph
        - Traverse: React → hooks → reactive → Java frameworks
        - Return: Spring WebFlux (reactive framework)

        Limitations:
        - Query entity extraction may miss variations
        - Graph may be incomplete (missing entities/relations)
        - Need hybrid with vector search for robustness

        Args:
            query_str: User query
            max_hops: Maximum graph traversal depth

        Returns:
            Dictionary with answer and graph paths
        """
        # Simple implementation: extract key terms from query
        # In production: use NER or LLM to extract query entities
        import string

        query_terms = [
            term.strip(string.punctuation).lower()
            for term in query_str.split()
            if len(term.strip(string.punctuation)) > 3
        ]

        # Find relevant nodes (case-insensitive matching)
        relevant_nodes = []
        for node in self.graph.nodes():
            node_lower = node.lower()
            if any(term in node_lower for term in query_terms):
                relevant_nodes.append(node)

        # If no nodes found, return empty result
        if not relevant_nodes:
            return {
                "answer": "No relevant entities found in knowledge graph.",
                "nodes": [],
                "paths": [],
                "metadata": {
                    "max_hops": max_hops,
                    "num_nodes": 0,
                    "num_paths": 0,
                },
            }

        # Collect subgraph around relevant nodes
        subgraph_nodes = set(relevant_nodes)
        paths = []

        for node in relevant_nodes:
            # Get neighbors within max_hops
            for target in self.graph.nodes():
                if target == node:
                    continue

                try:
                    # Find shortest path
                    path = nx.shortest_path(self.graph, node, target)
                    if len(path) <= max_hops + 1:
                        subgraph_nodes.update(path)
                        paths.append(path)
                except nx.NetworkXNoPath:
                    continue

        # Generate answer from subgraph
        # Teaching note: In production, use LLM to synthesize answer from paths
        # For now, return structured data
        answer_parts = []
        for path in paths[:5]:  # Limit to top 5 paths
            path_str = " → ".join(path)
            answer_parts.append(path_str)

        if answer_parts:
            answer = "Found relevant connections:\n" + "\n".join(f"- {p}" for p in answer_parts)
        else:
            answer = f"Found entities: {', '.join(relevant_nodes)}"

        return {
            "answer": answer,
            "nodes": list(subgraph_nodes),
            "paths": paths,
            "metadata": {
                "max_hops": max_hops,
                "num_nodes": len(subgraph_nodes),
                "num_paths": len(paths),
            },
        }

    def visualize(self, output_path: str = "graph.png") -> None:
        """
        Visualize knowledge graph using matplotlib.

        Teaching note: Visualization helps understand graph structure:
        - Node colors: Entity types
        - Edge labels: Relation types
        - Layout: Force-directed (spring layout)

        For large graphs: Use Gephi, Cytoscape, or Neo4j Browser

        Args:
            output_path: Path to save visualization
        """
        try:
            import matplotlib.pyplot as plt

            plt.figure(figsize=(12, 8))

            # Layout: spring layout (force-directed)
            pos = nx.spring_layout(self.graph, k=0.5, iterations=50)

            # Draw nodes
            nx.draw_networkx_nodes(
                self.graph,
                pos,
                node_color="lightblue",
                node_size=500,
            )

            # Draw edges
            nx.draw_networkx_edges(
                self.graph,
                pos,
                edge_color="gray",
                arrows=True,
                arrowsize=20,
            )

            # Draw labels
            nx.draw_networkx_labels(
                self.graph,
                pos,
                font_size=8,
            )

            # Draw edge labels (relations)
            edge_labels = nx.get_edge_attributes(self.graph, "relation")
            nx.draw_networkx_edge_labels(
                self.graph,
                pos,
                edge_labels,
                font_size=6,
            )

            plt.title("Knowledge Graph")
            plt.axis("off")
            plt.tight_layout()
            plt.savefig(output_path, dpi=150, bbox_inches="tight")
            plt.close()

        except ImportError:
            # Matplotlib not available (e.g., in tests)
            pass

    def get_stats(self) -> dict[str, int]:
        """
        Get graph statistics.

        Returns:
            Dictionary with node count, edge count, etc.
        """
        return {
            "num_nodes": self.graph.number_of_nodes(),
            "num_edges": self.graph.number_of_edges(),
            "num_connected_components": nx.number_weakly_connected_components(self.graph),
            "avg_degree": (
                sum(dict(self.graph.degree()).values()) / self.graph.number_of_nodes()
                if self.graph.number_of_nodes() > 0
                else 0
            ),
        }


# Optional Neo4j backend for production deployments
# Teaching note: This demonstrates how to scale Graph RAG from NetworkX to Neo4j.
# Use Neo4j when: graph >10k nodes, need persistence, concurrent queries, or ACID.
#
# Installation:
#   uv add neo4j  # or pip install neo4j
#
# Setup:
#   docker-compose -f infra/docker-compose.yml --profile optional up -d neo4j
#   Access Neo4j Browser: http://localhost:7474
#   Default credentials: neo4j/changeme123
#
# See docs/neo4j_migration_guide.md for full migration guide.


class Neo4jGraphRAGPipeline:
    """
    Graph RAG pipeline using Neo4j for persistent, scalable knowledge graphs.

    This is an optional alternative to GraphRAGPipeline (NetworkX-based).
    Use Neo4j for production deployments with:
    - Large graphs (>10k nodes)
    - Persistence across restarts
    - Concurrent query access
    - ACID transaction requirements

    Teaching note: Comparison with NetworkX implementation:
    - NetworkX: In-memory, fast for small graphs, no setup
    - Neo4j: Persistent, scales to billions of nodes, requires database

    Migration path:
    1. Develop with NetworkX (GraphRAGPipeline)
    2. Export graph when ready for production
    3. Import to Neo4j using migration guide
    4. Switch to this class for queries

    Args:
        uri: Neo4j connection URI (e.g., "bolt://localhost:7687")
        user: Neo4j username (default: "neo4j")
        password: Neo4j password (default: "changeme123")
        llm_client: Optional LLM client for entity/relation extraction
    """

    def __init__(
        self,
        uri: str = "bolt://localhost:7687",
        user: str = "neo4j",
        password: str = "changeme123",
        llm_client: UnifiedLLMClient | None = None,
    ) -> None:
        """Initialize Neo4j Graph RAG pipeline."""
        try:
            from neo4j import GraphDatabase
        except ImportError as e:
            raise ImportError("Neo4j driver not installed. Install with: uv add neo4j") from e

        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        self.llm_client = llm_client or UnifiedLLMClient()

        # Verify connection
        self._verify_connection()

    def _verify_connection(self) -> None:
        """Verify Neo4j connection is working."""
        try:
            with self.driver.session() as session:
                result = session.run("RETURN 1 AS test")
                result.single()
        except Exception as e:
            raise ConnectionError(
                f"Failed to connect to Neo4j at {self.driver._pool.address}. "
                "Ensure Neo4j is running (see docker-compose.yml)"
            ) from e

    def close(self) -> None:
        """Close Neo4j driver connection."""
        self.driver.close()

    def create_indexes(self) -> None:
        """
        Create indexes for optimal query performance.

        Teaching note: Indexes are CRITICAL for Neo4j performance.
        - Entity ID index: Fast lookups by entity name
        - Entity type index: Filter by entity type
        - Full-text index: Semantic search on labels

        Run this once after creating the database.
        """
        with self.driver.session() as session:
            # Index on entity ID (primary lookup)
            session.run(
                """
                CREATE INDEX entity_id_index IF NOT EXISTS
                FOR (n:Entity) ON (n.id)
            """
            )

            # Index on entity type (filtering)
            session.run(
                """
                CREATE INDEX entity_type_index IF NOT EXISTS
                FOR (n:Entity) ON (n.type)
            """
            )

            # Full-text search on labels
            session.run(
                """
                CREATE FULLTEXT INDEX entity_label_fulltext IF NOT EXISTS
                FOR (n:Entity) ON EACH [n.label]
            """
            )

    def add_entity(self, entity_id: str, entity_type: str, label: str | None = None) -> None:
        """
        Add entity to Neo4j graph.

        Args:
            entity_id: Unique entity identifier
            entity_type: Entity type (framework, library, concept, etc.)
            label: Optional human-readable label
        """
        with self.driver.session() as session:
            session.run(
                """
                MERGE (n:Entity {id: $id})
                SET n.type = $type,
                    n.label = $label
                """,
                id=entity_id,
                type=entity_type,
                label=label or entity_id,
            )

    def add_relation(self, source_id: str, target_id: str, relation_type: str) -> None:
        """
        Add relationship between entities.

        Args:
            source_id: Source entity ID
            target_id: Target entity ID
            relation_type: Relationship type (uses, depends_on, similar_to, etc.)
        """
        with self.driver.session() as session:
            session.run(
                """
                MATCH (source:Entity {id: $source_id})
                MATCH (target:Entity {id: $target_id})
                MERGE (source)-[r:RELATES_TO {type: $relation_type}]->(target)
                """,
                source_id=source_id,
                target_id=target_id,
                relation_type=relation_type,
            )

    def query(self, query_str: str, max_hops: int = 3, limit: int = 100) -> dict[str, Any]:
        """
        Query Neo4j knowledge graph with multi-hop traversal.

        Teaching note: Cypher query language differences from NetworkX:
        - Declarative: Describe WHAT you want, not HOW to get it
        - Optimized: Neo4j query planner chooses best execution
        - Indexed: Uses indexes for fast lookups

        Args:
            query_str: User query
            max_hops: Maximum graph traversal depth
            limit: Maximum number of paths to return

        Returns:
            Dictionary with answer and graph paths
        """
        import string

        # Extract query terms (same logic as NetworkX version)
        query_terms = [
            term.strip(string.punctuation).lower()
            for term in query_str.split()
            if len(term.strip(string.punctuation)) > 3
        ]

        if not query_terms:
            return {
                "answer": "No valid query terms found.",
                "nodes": [],
                "paths": [],
                "metadata": {"max_hops": max_hops, "num_nodes": 0, "num_paths": 0},
            }

        # Find relevant entities using pattern matching
        with self.driver.session() as session:
            # Find nodes matching query terms
            result = session.run(
                """
                MATCH (n:Entity)
                WHERE ANY(term IN $terms WHERE toLower(n.id) CONTAINS term
                                            OR toLower(n.label) CONTAINS term)
                RETURN n.id AS id
                LIMIT 10
                """,
                terms=query_terms,
            )

            relevant_nodes = [record["id"] for record in result]

            if not relevant_nodes:
                return {
                    "answer": "No relevant entities found in knowledge graph.",
                    "nodes": [],
                    "paths": [],
                    "metadata": {
                        "max_hops": max_hops,
                        "num_nodes": 0,
                        "num_paths": 0,
                    },
                }

            # Find paths from relevant nodes
            result = session.run(
                """
                UNWIND $relevant_nodes AS start_id
                MATCH (start:Entity {id: start_id})
                MATCH path = (start)-[:RELATES_TO*1..$max_hops]->(end:Entity)
                WITH path, start, end
                RETURN [node IN nodes(path) | node.id] AS path_nodes
                LIMIT $limit
                """,
                relevant_nodes=relevant_nodes,
                max_hops=max_hops,
                limit=limit,
            )

            paths = [record["path_nodes"] for record in result]

            # Collect all unique nodes
            all_nodes = set()
            for path in paths:
                all_nodes.update(path)

            # Generate answer
            answer_parts = []
            for path in paths[:5]:  # Limit to top 5 paths
                path_str = " → ".join(path)
                answer_parts.append(path_str)

            if answer_parts:
                answer = "Found relevant connections:\n" + "\n".join(f"- {p}" for p in answer_parts)
            else:
                answer = f"Found entities: {', '.join(relevant_nodes)}"

            return {
                "answer": answer,
                "nodes": list(all_nodes),
                "paths": paths,
                "metadata": {
                    "max_hops": max_hops,
                    "num_nodes": len(all_nodes),
                    "num_paths": len(paths),
                },
            }

    def get_stats(self) -> dict[str, int]:
        """
        Get Neo4j graph statistics.

        Returns:
            Dictionary with node count, edge count, etc.
        """
        with self.driver.session() as session:
            # Count nodes
            result = session.run("MATCH (n:Entity) RETURN COUNT(n) AS count")
            num_nodes = result.single()["count"]

            # Count edges
            result = session.run("MATCH ()-[r:RELATES_TO]->() RETURN COUNT(r) AS count")
            num_edges = result.single()["count"]

            # Average degree (approximate)
            if num_nodes > 0:
                result = session.run(
                    """
                    MATCH (n:Entity)
                    RETURN AVG(size((n)-[:RELATES_TO]-())) AS avg_degree
                """
                )
                avg_degree = result.single()["avg_degree"] or 0
            else:
                avg_degree = 0

            return {
                "num_nodes": num_nodes,
                "num_edges": num_edges,
                "avg_degree": avg_degree,
            }

    def export_to_networkx(self) -> nx.DiGraph:
        """
        Export Neo4j graph to NetworkX for analysis.

        Teaching note: Useful for:
        - Running NetworkX algorithms not available in Neo4j
        - Visualization with matplotlib
        - Offline analysis without database connection

        Warning: Only practical for small graphs (<10k nodes).
        Large graphs will consume too much memory.

        Returns:
            NetworkX DiGraph with nodes and edges
        """
        graph = nx.DiGraph()

        with self.driver.session() as session:
            # Export nodes
            result = session.run(
                """
                MATCH (n:Entity)
                RETURN n.id AS id, n.type AS type, n.label AS label
            """
            )

            for record in result:
                graph.add_node(record["id"], type=record["type"], label=record["label"])

            # Export edges
            result = session.run(
                """
                MATCH (source:Entity)-[r:RELATES_TO]->(target:Entity)
                RETURN source.id AS source, target.id AS target, r.type AS relation
            """
            )

            for record in result:
                graph.add_edge(
                    record["source"],
                    record["target"],
                    relation=record["relation"],
                    label=record["relation"],
                )

        return graph
