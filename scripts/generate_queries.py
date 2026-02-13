#!/usr/bin/env python3
"""Generate synthetic queries for RAG testing.

This script generates diverse synthetic queries based on existing documentation
to test RAG pipeline capabilities.

Query Types:
- Simple: Direct factual questions (What is X?)
- Multi-hop: Require combining information from multiple docs
- Comparison: Compare concepts across frameworks
- Temporal: When/why questions (When should I use X?)
- Negation: What NOT to do, limitations
- Procedural: How-to questions

Usage:
    # Generate 30 queries (2 batches of 15-20, default batch size is 20)
    python scripts/generate_queries.py --count 30

    # Generate large batch with auto-batching (generates in batches of 20)
    python scripts/generate_queries.py --count 265 --append

    # Generate specific query types
    python scripts/generate_queries.py --count 20 --types simple,multi-hop

    # Append to existing file
    python scripts/generate_queries.py --count 10 --append

    # Use specific model (default: Groq → DeepSeek → Claude fallback)
    python scripts/generate_queries.py --count 50 --model claude

    # Use smaller batch size (10-15) if experiencing JSON parsing errors
    python scripts/generate_queries.py --count 200 --batch-size 10
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from src.core.config import get_settings
from src.core.llm_client import UnifiedLLMClient


@dataclass
class Query:
    """Represents a synthetic query for RAG testing."""

    id: str
    query: str
    expected_answer: str
    source_docs: list[str]
    difficulty: str
    category: str
    notes: str


class QueriesGenerator:
    """Generate synthetic queries for RAG testing."""

    FRAMEWORKS = ["fastapi", "pydantic", "react", "spring"]

    QUERY_CATEGORIES = [
        "simple",  # Direct factual questions
        "multi-hop",  # Require multiple docs
        "comparison",  # Compare concepts
        "temporal",  # When/why questions
        "negation",  # What NOT to do
        "procedural",  # How-to questions
    ]

    DIFFICULTY_LEVELS = ["simple", "moderate", "complex"]

    def __init__(self, preferred_model: str | None = None) -> None:
        """Initialize generator.

        Args:
            preferred_model: Preferred LLM model (claude, gpt4, groq). If None, uses fallback chain.
        """
        self.settings = get_settings()
        self.llm_client = UnifiedLLMClient(self.settings, enable_caching=True)
        self.datasets_dir = PROJECT_ROOT / "datasets" / "tech_docs"
        self.queries_dir = PROJECT_ROOT / "datasets" / "synthetic_queries"
        self.preferred_model = preferred_model

    def load_documentation_summary(self) -> dict[str, list[str]]:
        """Load summary of available documentation.

        Returns:
            Dict mapping framework to list of topic titles
        """
        doc_summary = {}

        for framework in self.FRAMEWORKS:
            framework_dir = self.datasets_dir / framework
            if not framework_dir.exists():
                continue

            topics = []
            for doc_file in sorted(framework_dir.glob("*.md")):
                if doc_file.name == "attribution.md":
                    continue

                # Extract title from first line of file
                try:
                    content = doc_file.read_text()
                    lines = content.split("\n")
                    for line in lines:
                        if line.startswith("# "):
                            title = line[2:].strip()
                            topics.append({"file": doc_file.name, "title": title})
                            break
                except Exception:
                    continue

            doc_summary[framework] = topics

        return doc_summary

    def generate_queries_batch(
        self,
        count: int,
        categories: list[str] | None = None,
        existing_queries: list[Query] | None = None,
    ) -> list[Query]:
        """Generate a batch of queries using LLM.

        Args:
            count: Number of queries to generate
            categories: Specific categories to focus on (None = all)
            existing_queries: Existing queries to avoid duplicates

        Returns:
            List of Query objects
        """
        if categories is None:
            categories = self.QUERY_CATEGORIES

        # Load documentation summary
        doc_summary = self.load_documentation_summary()

        # Build context about available docs
        docs_context = self._build_docs_context(doc_summary)

        # Build prompt
        prompt = self._build_generation_prompt(count, categories, docs_context, existing_queries)

        print(f"Generating {count} queries using LLM...")
        print(f"Categories: {', '.join(categories)}")
        if self.preferred_model:
            print(f"Model: {self.preferred_model}")
        else:
            print(f"Model: Groq → DeepSeek → Claude (fallback chain)")

        try:
            if self.preferred_model == "claude":
                response = self.llm_client._call_anthropic(
                    prompt=prompt,
                    max_tokens=4000,
                    temperature=0.8,
                    timeout=120,
                )
            elif self.preferred_model == "gpt4":
                response = self.llm_client._call_openai(
                    prompt=prompt,
                    max_tokens=4000,
                    temperature=0.8,
                    timeout=120,
                )
            elif self.preferred_model == "groq":
                from src.core.llm_client import GroqModel
                response = self.llm_client._call_groq(
                    prompt=prompt,
                    model=GroqModel.LLAMA_3_70B,
                    max_tokens=4000,
                    temperature=0.8,
                    timeout=120,
                )
            else:
                # Use default fallback chain
                response = self.llm_client.generate(
                    prompt=prompt,
                    max_tokens=4000,
                    temperature=0.8,
                    timeout=120,
                )

            # Parse JSON response
            queries = self._parse_llm_response(response.content, doc_summary)

            print(f"✅ Generated {len(queries)} queries")
            print(f"   Tokens used: {response.total_tokens:,}")
            print(f"   Cost: ${response.cost_usd:.4f}")

            return queries

        except Exception as e:
            print(f"❌ Error generating queries: {e}")
            import traceback
            traceback.print_exc()
            return []

    def _build_docs_context(self, doc_summary: dict[str, list[str]]) -> str:
        """Build context string describing available documentation."""
        context_parts = []

        for framework, topics in doc_summary.items():
            context_parts.append(f"\n**{framework.upper()}** ({len(topics)} docs):")
            for topic in topics[:10]:  # Show first 10 topics
                context_parts.append(f"  - {topic['file']}: {topic['title']}")
            if len(topics) > 10:
                context_parts.append(f"  ... and {len(topics) - 10} more topics")

        return "\n".join(context_parts)

    def _build_generation_prompt(
        self,
        count: int,
        categories: list[str],
        docs_context: str,
        existing_queries: list[Query] | None,
    ) -> str:
        """Build prompt for query generation."""

        existing_context = ""
        if existing_queries:
            existing_context = f"\n**Avoid duplicating these existing queries**:\n"
            for q in existing_queries[-10:]:  # Show last 10 to avoid
                existing_context += f"- {q.query}\n"

        prompt = f"""You are an expert at creating test queries for RAG (Retrieval-Augmented Generation) systems.

Generate {count} diverse, high-quality test queries for a technical documentation RAG system.

**Available Documentation**:
{docs_context}

**Query Categories to Generate** (mix them):
{', '.join(f'`{cat}`' for cat in categories)}

**Category Definitions**:
- **simple**: Direct factual questions (e.g., "What is FastAPI?", "How do you declare path parameters?")
- **multi-hop**: Requires combining info from multiple docs (e.g., "How does FastAPI dependency injection compare to Spring?")
- **comparison**: Compare concepts across frameworks (e.g., "Compare React hooks to Spring bean lifecycle")
- **temporal**: When/why questions (e.g., "When should I use async def vs def?")
- **negation**: What NOT to do (e.g., "What are common pitfalls with Pydantic validation?")
- **procedural**: How-to questions (e.g., "How do I implement authentication in FastAPI?")

**Difficulty Levels** (distribute evenly):
- **simple**: Can be answered from 1-2 paragraphs in a single doc
- **moderate**: Requires understanding multiple sections or concepts
- **complex**: Requires synthesizing information across multiple docs

{existing_context}

**CRITICAL REQUIREMENTS**:
1. Generate EXACTLY {count} queries
2. Make queries realistic - what a developer would actually ask
3. Ensure queries are answerable from the available docs
4. Vary difficulty levels (simple, moderate, complex)
5. Mix query categories evenly
6. Include specific technical terms from the docs
7. For multi-hop queries, specify which docs contain the answer
8. Write concise expected answers (2-3 sentences)

**Output Format** (JSON array):
```json
[
  {{
    "id": "q001",
    "query": "What is FastAPI and what are its key features?",
    "expected_answer": "FastAPI is a modern, fast web framework for building APIs with Python 3.7+ based on standard Python type hints. Key features include high performance, fast development, automatic documentation, and standards-based design.",
    "source_docs": ["fastapi/01_introduction.md"],
    "difficulty": "simple",
    "category": "simple",
    "notes": "Basic definition query from introduction"
  }},
  {{
    "id": "q002",
    "query": "How does dependency injection work in FastAPI compared to Spring Framework?",
    "expected_answer": "Both FastAPI and Spring use dependency injection to provide shared resources. FastAPI uses function parameters with type hints and Depends(), while Spring uses @Autowired annotations. FastAPI's approach is more explicit and type-safe.",
    "source_docs": ["fastapi/05_dependencies.md", "spring/02_dependency_injection.md"],
    "difficulty": "moderate",
    "category": "comparison",
    "notes": "Multi-hop query comparing two frameworks"
  }}
]
```

Generate the {count} queries now. Output ONLY valid JSON, no additional commentary."""

        return prompt

    def _parse_llm_response(
        self, response_text: str, doc_summary: dict[str, list[str]]
    ) -> list[Query]:
        """Parse LLM response into Query objects.

        Args:
            response_text: LLM response containing JSON
            doc_summary: Available documentation for validation

        Returns:
            List of Query objects
        """
        # Extract JSON from response (may have markdown code blocks)
        json_text = response_text.strip()
        if json_text.startswith("```json"):
            json_text = json_text[7:]  # Remove ```json
        if json_text.startswith("```"):
            json_text = json_text[3:]  # Remove ```
        if json_text.endswith("```"):
            json_text = json_text[:-3]  # Remove trailing ```
        json_text = json_text.strip()

        # Parse JSON
        try:
            # Try to fix common JSON issues
            json_text = json_text.replace('\\"', '"')  # Fix escaped quotes
            json_text = json_text.replace('\\n', ' ')  # Replace literal \n
            queries_data = json.loads(json_text)
        except json.JSONDecodeError as e:
            print(f"⚠️  Failed to parse JSON: {e}")
            print(f"Response text (first 1000 chars):")
            print(response_text[:1000])
            print("\nTrying alternative parsing...")

            # Strategy 1: Try to find and extract the JSON array
            import re
            queries_data = []

            # Look for array pattern [...]
            array_match = re.search(r'\[\s*\{.*\}\s*\]', response_text, re.DOTALL)
            if array_match:
                try:
                    array_text = array_match.group(0)
                    queries_data = json.loads(array_text)
                    print(f"✅ Extracted array with {len(queries_data)} items")
                except Exception:
                    pass

            if not queries_data:
                print("⚠️  Array extraction failed, trying object-by-object parsing...")

                # Strategy 2: Extract individual query objects (with limit to prevent infinite loop)
                start = 0
                max_iterations = 1000  # Safety limit
                iteration = 0

                while start < len(response_text) and iteration < max_iterations:
                    iteration += 1
                    start_idx = response_text.find('{', start)
                    if start_idx == -1:
                        break

                    # Find matching closing brace
                    depth = 0
                    end_idx = start_idx
                    max_chars = 5000  # Max chars per object

                    for i in range(start_idx, min(start_idx + max_chars, len(response_text))):
                        char = response_text[i]
                        if char == '{':
                            depth += 1
                        elif char == '}':
                            depth -= 1
                            if depth == 0:
                                end_idx = i + 1
                                break

                    if depth == 0 and end_idx > start_idx:
                        obj_text = response_text[start_idx:end_idx]
                        try:
                            obj = json.loads(obj_text)
                            if 'query' in obj:  # Validate it's a query object
                                queries_data.append(obj)
                                print(f"  Extracted query {len(queries_data)}")
                        except Exception:
                            pass
                        start = end_idx
                    else:
                        # Skip this character and continue
                        start = start_idx + 1

                if iteration >= max_iterations:
                    print(f"⚠️  Hit iteration limit during parsing")

            if not queries_data:
                print("❌ Could not parse any queries from response")
                return []

            print(f"✅ Fallback parsing extracted {len(queries_data)} queries")

        # Convert to Query objects
        queries = []
        for i, q_data in enumerate(queries_data, 1):
            try:
                query = Query(
                    id=q_data.get("id", f"q{i:03d}"),
                    query=q_data["query"],
                    expected_answer=q_data["expected_answer"],
                    source_docs=q_data.get("source_docs", []),
                    difficulty=q_data.get("difficulty", "moderate"),
                    category=q_data.get("category", "simple"),
                    notes=q_data.get("notes", ""),
                )
                queries.append(query)
            except KeyError as e:
                print(f"⚠️  Skipping query {i} - missing field: {e}")
                continue

        return queries

    def load_existing_queries(self, filepath: Path) -> list[Query]:
        """Load existing queries from JSON file.

        Args:
            filepath: Path to queries JSON file

        Returns:
            List of Query objects
        """
        if not filepath.exists():
            return []

        try:
            data = json.loads(filepath.read_text())
            queries = []

            for q_data in data.get("queries", []):
                query = Query(
                    id=q_data["id"],
                    query=q_data["query"],
                    expected_answer=q_data["expected_answer"],
                    source_docs=q_data.get("source_docs", []),
                    difficulty=q_data.get("difficulty", "moderate"),
                    category=q_data.get("category", "simple"),
                    notes=q_data.get("notes", ""),
                )
                queries.append(query)

            return queries
        except Exception as e:
            print(f"⚠️  Failed to load existing queries: {e}")
            return []

    def save_queries(
        self,
        queries: list[Query],
        filepath: Path,
        append: bool = False,
    ) -> None:
        """Save queries to JSON file.

        Args:
            queries: List of Query objects to save
            filepath: Output file path
            append: If True, append to existing queries
        """
        # Load existing queries if appending
        existing_queries = []
        if append and filepath.exists():
            existing_queries = self.load_existing_queries(filepath)

        # Combine queries
        all_queries = existing_queries + queries

        # Re-number IDs sequentially
        for i, q in enumerate(all_queries, 1):
            q.id = f"q{i:03d}"

        # Count by difficulty and category
        difficulty_dist = {}
        category_dist = {}
        for q in all_queries:
            difficulty_dist[q.difficulty] = difficulty_dist.get(q.difficulty, 0) + 1
            category_dist[q.category] = category_dist.get(q.category, 0) + 1

        # Build output structure
        output = {
            "metadata": {
                "version": "1.0",
                "created_date": datetime.now().strftime("%Y-%m-%d"),
                "description": "Synthetic test queries for Article 1: RAG baseline evaluation",
                "total_queries": len(all_queries),
                "difficulty_distribution": difficulty_dist,
                "category_distribution": category_dist,
            },
            "queries": [asdict(q) for q in all_queries],
            "evaluation_notes": {
                "purpose": "These queries test the RAG pipeline's ability to retrieve and answer technical documentation questions across multiple frameworks.",
                "success_criteria": {
                    "answer_correctness": "Generated answers should cover key points in expected_answer",
                    "context_precision": "Retrieved chunks should include the source_docs listed",
                    "answer_relevance": "Answers should directly address the query without hallucination",
                },
            },
        }

        # Ensure directory exists
        filepath.parent.mkdir(parents=True, exist_ok=True)

        # Write JSON
        filepath.write_text(json.dumps(output, indent=2))
        print(f"\n💾 Saved {len(all_queries)} queries to: {filepath}")

        # Print statistics
        print(f"\n📊 Query Statistics:")
        print(f"   Total queries: {len(all_queries)}")
        print(f"   Difficulty distribution:")
        for diff, count in sorted(difficulty_dist.items()):
            print(f"     - {diff}: {count}")
        print(f"   Category distribution:")
        for cat, count in sorted(category_dist.items()):
            print(f"     - {cat}: {count}")


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Generate synthetic queries for RAG testing"
    )
    parser.add_argument(
        "--count",
        type=int,
        default=30,
        help="Number of queries to generate (default: 30)",
    )
    parser.add_argument(
        "--types",
        type=str,
        help="Comma-separated query types (default: all)",
    )
    parser.add_argument(
        "--append",
        action="store_true",
        help="Append to existing queries file",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "datasets" / "synthetic_queries" / "article_01.json",
        help="Output file path",
    )
    parser.add_argument(
        "--model",
        choices=["claude", "gpt4", "groq"],
        help="Preferred LLM model (default: uses fallback chain Groq → DeepSeek → Claude)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=20,
        help="Batch size for generating queries (default: 20). Large counts are split into batches. Use smaller sizes (10-15) if experiencing JSON parsing errors.",
    )

    args = parser.parse_args()

    # Parse query types
    categories = None
    if args.types:
        categories = [t.strip() for t in args.types.split(",")]
        valid_categories = QueriesGenerator.QUERY_CATEGORIES
        invalid = [c for c in categories if c not in valid_categories]
        if invalid:
            print(f"❌ Invalid query types: {invalid}")
            print(f"   Valid types: {', '.join(valid_categories)}")
            return 1

    # Initialize generator
    generator = QueriesGenerator(preferred_model=args.model)

    # Load existing queries if appending
    existing_queries = None
    if args.append:
        existing_queries = generator.load_existing_queries(args.output)
        print(f"📖 Loaded {len(existing_queries)} existing queries")

    # Generate queries in batches
    all_new_queries = []
    remaining = args.count
    batch_num = 1
    total_batches = (args.count + args.batch_size - 1) // args.batch_size

    while remaining > 0:
        batch_count = min(remaining, args.batch_size)
        print(f"\n{'='*70}")
        print(f"Batch {batch_num}/{total_batches}: Generating {batch_count} queries")
        print(f"{'='*70}")

        # Pass existing queries + already generated queries to avoid duplicates
        context_queries = (existing_queries or []) + all_new_queries

        # Try batch generation with retry on failure
        batch_queries = None
        retry_count = 0
        max_retries = 2

        while batch_queries is None and retry_count <= max_retries:
            if retry_count > 0:
                # Reduce batch size on retry
                batch_count = max(5, batch_count // 2)
                print(f"\n⚠️  Retry {retry_count}: Reducing batch size to {batch_count}")

            batch_queries = generator.generate_queries_batch(
                count=batch_count,
                categories=categories,
                existing_queries=context_queries if context_queries else None,
            )

            if not batch_queries:
                retry_count += 1
                batch_queries = None  # Explicitly set to None for retry
            else:
                break

        if not batch_queries:
            print(f"⚠️  Batch {batch_num} failed after {max_retries} retries, stopping")
            break

        all_new_queries.extend(batch_queries)
        remaining -= len(batch_queries)
        batch_num += 1

        print(f"   Progress: {len(all_new_queries)}/{args.count} queries generated")

    if not all_new_queries:
        print("❌ No queries generated")
        return 1

    print(f"\n{'='*70}")
    print(f"✅ Generated {len(all_new_queries)} total queries across {batch_num - 1} batches")
    print(f"{'='*70}")

    # Save queries
    generator.save_queries(all_new_queries, args.output, append=args.append)

    return 0


if __name__ == "__main__":
    sys.exit(main())
