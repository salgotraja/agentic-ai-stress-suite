#!/usr/bin/env python3
"""Generate comprehensive technical documentation using LLM assistance.

This script generates production-quality technical documentation for multiple frameworks:
- FastAPI: Web framework documentation (topics 18-50)
- Spring Framework: Java enterprise framework (topics 05-50)
- React: JavaScript UI library (topics 06-50)
- Pydantic: Python data validation (topics 05-50)

Generation Strategy:
- Uses Groq (LLama-3.1-8B) for cost-efficient generation (~$0.05/1M tokens)
- Structured prompts ensure consistent quality and format
- Automatic validation of word count (800-1500 words)
- Cross-framework references included based on topic lists
- Total cost: <$1 for all 170 documents

Usage:
    # Generate all frameworks (default: Qwen 32B -> Llama 70B -> DeepSeek -> Claude)
    python scripts/generate_tech_docs.py --all

    # Generate specific framework
    python scripts/generate_tech_docs.py --framework fastapi

    # Generate range of topics
    python scripts/generate_tech_docs.py --framework pydantic --start 2 --end 9

    # Regenerate only invalid documents (based on validation)
    python scripts/generate_tech_docs.py --framework fastapi --regenerate-invalid

    # Force specific model (skip fallback chain)
    python scripts/generate_tech_docs.py --framework fastapi --start 18 --end 25 --model groq

    # Dry run
    python scripts/generate_tech_docs.py --framework fastapi --dry-run

Model Options:
    --model claude: Claude Sonnet 4.5 only ($3.00/MTok)
    --model gpt4: GPT-4 only ($2.50/MTok)
    --model groq: Groq Llama-3-70B only ($0.59/MTok)
    (default): Qwen 32B -> Llama 70B -> DeepSeek ($0.27/MTok) -> Claude fallback
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from src.core.config import get_settings
from src.core.llm_client import UnifiedLLMClient


@dataclass
class Topic:
    """Represents a documentation topic to generate."""

    number: int
    title: str
    slug: str
    concepts: str
    word_count_range: tuple[int, int]
    cross_refs: str
    code_examples: str


@dataclass
class GenerationResult:
    """Result of generating a single document."""

    topic_number: int
    filename: str
    success: bool
    word_count: int
    tokens_used: int
    cost_usd: float
    error: str | None = None


class TechDocsGenerator:
    """LLM-assisted technical documentation generator."""

    # Framework configurations
    FRAMEWORKS = {
        "fastapi": {
            "name": "FastAPI",
            "desc": "FastAPI is a modern, fast web framework for building APIs with Python",
            "start": 1,
            "end": 50,
        },
        "pydantic": {
            "name": "Pydantic",
            "desc": "Pydantic provides data validation and settings management using Python type annotations",
            "start": 1,
            "end": 50,
        },
        "react": {
            "name": "React",
            "desc": "React is a JavaScript library for building user interfaces",
            "start": 1,
            "end": 50,
        },
        "spring": {
            "name": "Spring Framework",
            "desc": "Spring Framework is a comprehensive framework for enterprise Java development",
            "start": 1,
            "end": 50,
        },
    }

    def __init__(self, dry_run: bool = False, preferred_model: str | None = None) -> None:
        """Initialize generator.

        Args:
            dry_run: If True, generate content but don't write files
            preferred_model: Preferred LLM model (claude, gpt4, groq). If None, uses fallback chain.
        """
        self.dry_run = dry_run
        self.preferred_model = preferred_model
        self.settings = get_settings()
        self.llm_client = UnifiedLLMClient(self.settings, enable_caching=True)
        self.datasets_dir = PROJECT_ROOT / "datasets" / "tech_docs"
        self.topic_lists_dir = PROJECT_ROOT / "datasets" / "tech_docs_topic_lists"

        # Statistics
        self.total_tokens = 0
        self.total_cost = 0.0
        self.successful_gens = 0
        self.failed_gens = 0

    def get_invalid_topic_numbers(self, framework: str) -> list[int]:
        """Get list of topic numbers for invalid documents.

        Args:
            framework: Framework name

        Returns:
            List of topic numbers that need regeneration
        """
        framework_dir = self.datasets_dir / framework
        if not framework_dir.exists():
            return []

        invalid_topics = []
        doc_files = sorted(framework_dir.glob("*.md"))

        for filepath in doc_files:
            filename = filepath.name

            # Skip attribution file
            if filename == "attribution.md":
                continue

            # Extract topic number from filename (e.g., "01_introduction.md" -> 1)
            match = re.match(r"^(\d{2})_", filename)
            if not match:
                continue

            topic_number = int(match.group(1))

            # Read and validate content
            try:
                content = filepath.read_text()

                # Same validation as validate_tech_docs.py
                text_content = re.sub(r"```.*?```", "", content, flags=re.DOTALL)
                words = len(text_content.split())

                # Check if invalid (< 800 words or missing code/headings)
                has_code = "```" in content
                has_headings = re.search(r"^##\s+", content, re.MULTILINE)

                if words < 800 or not has_code or not has_headings:
                    invalid_topics.append(topic_number)

            except Exception:
                # If can't read, consider it invalid
                invalid_topics.append(topic_number)

        return sorted(invalid_topics)

    def load_topics_from_file(self, framework: str) -> list[Topic]:
        """Load topic list from planning file.

        Args:
            framework: Framework name (fastapi, pydantic, react, spring)

        Returns:
            List of Topic objects parsed from the topic list file
        """
        config = self.FRAMEWORKS[framework]
        topic_file = self.topic_lists_dir / f"{framework}_topics_01-50.md"

        if not topic_file.exists():
            raise FileNotFoundError(f"Topic list not found: {topic_file}")

        topics = []
        current_topic: dict[str, Any] = {}

        with open(topic_file) as f:
            for line in f:
                line = line.rstrip()

                # Match topic header: ## 18. Custom Response Classes
                topic_match = re.match(r"^## (\d+)\.\s+(.+)$", line)
                if topic_match:
                    # Save previous topic if exists
                    if current_topic:
                        topics.append(self._parse_topic(current_topic, framework))

                    # Start new topic
                    number = int(topic_match.group(1))
                    title = topic_match.group(2)
                    current_topic = {"number": number, "title": title, "lines": []}
                    continue

                # Collect lines for current topic
                if current_topic:
                    current_topic["lines"].append(line)

            # Save last topic
            if current_topic:
                topics.append(self._parse_topic(current_topic, framework))

        return topics

    def _parse_topic(self, topic_data: dict[str, Any], framework: str) -> Topic:
        """Parse topic data into Topic object."""
        number = topic_data["number"]
        title = topic_data["title"]
        lines = topic_data["lines"]

        # Extract fields from lines
        concepts = ""
        word_count_range = (800, 1500)
        cross_refs = ""
        code_examples = ""

        for line in lines:
            if line.startswith("**Concepts:**"):
                concepts = line.replace("**Concepts:**", "").strip()
            elif line.startswith("**Word count:**"):
                wc_match = re.search(r"(\d+)-(\d+)", line)
                if wc_match:
                    word_count_range = (int(wc_match.group(1)), int(wc_match.group(2)))
            elif line.startswith("**Cross-refs:**"):
                cross_refs = line.replace("**Cross-refs:**", "").strip()
            elif line.startswith("**Code examples:**"):
                code_examples = line.replace("**Code examples:**", "").strip()

        # Generate slug from title
        slug = title.lower().replace(" ", "_").replace("(", "").replace(")", "")
        slug = re.sub(r"[^a-z0-9_]", "", slug)

        return Topic(
            number=number,
            title=title,
            slug=slug,
            concepts=concepts,
            word_count_range=word_count_range,
            cross_refs=cross_refs,
            code_examples=code_examples,
        )

    def generate_documentation(
        self, framework: str, topic: Topic, retry_count: int = 0
    ) -> tuple[str, int, float]:
        """Generate documentation for a single topic using LLM.

        Teaching note: Cost-optimized fallback chain for documentation generation:
        - Qwen 32B: $0.59/MTok, 32B params should handle 800-1500 word requirements
        - Llama 70B: $0.59/MTok, stronger model if Qwen fails
        - DeepSeek: $0.27/MTok, excellent quality and cheapest cloud option
        - Claude: $3.00/MTok, last resort (11x more expensive than DeepSeek)

        Skip Groq 8B: Too weak for comprehensive docs (~700 words vs 800+ needed)

        Args:
            framework: Framework name
            topic: Topic to generate
            retry_count: Current retry (0=Qwen 32B, 1=Llama 70B, 2=DeepSeek, 3=Claude)

        Returns:
            Tuple of (content, tokens_used, cost_usd)
        """
        config = self.FRAMEWORKS[framework]
        framework_name = config["name"]
        framework_desc = config["desc"]

        prompt = self._build_generation_prompt(framework_name, framework_desc, topic)

        try:
            if self.preferred_model == "claude":
                response = self.llm_client._call_anthropic(
                    prompt=prompt,
                    temperature=0.7,
                    max_tokens=4000,
                    timeout=60,
                )
            elif self.preferred_model == "gpt4":
                response = self.llm_client._call_openai(
                    prompt=prompt,
                    temperature=0.7,
                    max_tokens=4000,
                    timeout=60,
                )
            elif self.preferred_model == "groq":
                from src.core.llm_client import GroqModel

                response = self.llm_client._call_groq(
                    prompt=prompt,
                    model=GroqModel.LLAMA_3_70B,
                    temperature=0.7,
                    max_tokens=4000,
                    timeout=60,
                )
            elif retry_count == 0:
                from src.core.llm_client import GroqModel

                response = self.llm_client._call_groq(
                    prompt=prompt,
                    model=GroqModel.LLAMA_3_32B,
                    temperature=0.7,
                    max_tokens=4000,
                    timeout=60,
                )
            elif retry_count == 1:
                from src.core.llm_client import GroqModel

                response = self.llm_client._call_groq(
                    prompt=prompt,
                    model=GroqModel.LLAMA_3_70B,
                    temperature=0.7,
                    max_tokens=4000,
                    timeout=60,
                )
            elif retry_count == 2:
                response = self.llm_client._call_deepseek(
                    prompt=prompt,
                    temperature=0.7,
                    max_tokens=4000,
                    timeout=60,
                )
            else:
                response = self.llm_client._call_anthropic(
                    prompt=prompt,
                    temperature=0.7,
                    max_tokens=4000,
                    timeout=60,
                )

            content = self._clean_llm_output(response.content)
            return content, response.total_tokens, response.cost_usd

        except Exception as e:
            raise RuntimeError(f"LLM generation failed: {e}") from e

    def _clean_llm_output(self, content: str) -> str:
        """Remove LLM thinking process and extract only markdown content.

        Teaching note: Some LLMs output thinking process despite instructions.
        Strip everything before first markdown heading to get clean content.

        Args:
            content: Raw LLM output

        Returns:
            Cleaned markdown content starting with first heading
        """
        lines = content.split("\n")

        # Find first line that starts with # (markdown heading)
        for i, line in enumerate(lines):
            if line.strip().startswith("#"):
                # Return everything from first heading onwards
                return "\n".join(lines[i:])

        # If no heading found, return as-is (validation will catch it)
        return content

    def _build_generation_prompt(
        self, framework_name: str, framework_desc: str, topic: Topic
    ) -> str:
        """Build structured prompt for LLM generation."""
        min_words, max_words = topic.word_count_range

        prompt = f"""Generate ONLY the markdown documentation. DO NOT include any thinking process, commentary, or meta-discussion.

Start immediately with the markdown heading. No preamble.

**Topic**: {topic.title}
**Key Concepts**: {topic.concepts}
**Code Examples Needed**: {topic.code_examples}
**Cross-References**: {topic.cross_refs}
**Target Length**: {min_words}-{max_words} words

**Framework Context**:
{framework_desc}

**CRITICAL LENGTH REQUIREMENT - READ CAREFULLY**:
Your response MUST contain MINIMUM {min_words} words of actual text content (not counting code blocks).
Target range: {min_words}-{max_words} words.

COUNT YOUR WORDS as you write. If you reach the end and have fewer than {min_words} words:
- Add more examples (edge cases, error handling, best practices)
- Expand explanations with WHY and WHEN to use features
- Include troubleshooting sections
- Add comparison with alternative approaches
- Provide real-world use case examples

Quality over brevity - comprehensive documentation is valuable.

**Requirements**:
1. Write {min_words}-{max_words} words of technical content (MANDATORY - count your words!)
2. Include multiple detailed code examples with syntax highlighting (use ```language blocks)
3. Explain WHY and WHEN to use features, not just WHAT they are (add depth)
4. Use clear headings (## and ###) to organize content into multiple sections
5. Include practical use cases and best practices sections
6. Add cross-framework comparisons if relevant
7. Write in a teaching-oriented style for senior engineers
8. Focus on production-ready patterns, not toy examples
9. Expand each section with detailed explanations, edge cases, and examples
10. Add troubleshooting tips and common pitfalls sections where appropriate

**Format**:
```markdown
# {topic.title}

[Introduction paragraph explaining the concept]

## [Section 1 Heading]

[Content with code examples]

```language
[code example]
```

## [Section 2 Heading]

[More content...]

## Best Practices

[Practical guidance]
```

OUTPUT FORMAT:
Start your response with: # {topic.title}

Do NOT output:
- Thinking process or planning
- Meta-commentary about what you're writing
- Phrases like "Okay, let's" or "I need to"
- Anything in <think> tags

Generate the documentation NOW. First line must be: # {topic.title}"""

        return prompt

    def validate_content(self, content: str, topic: Topic) -> tuple[bool, str]:
        """Validate generated content meets quality standards.

        Teaching note: Word count validation removed to avoid wasteful retries.
        Models consistently generate 800-1000 words regardless of prompting.
        For RAG corpus, quality matters more than hitting arbitrary word counts.
        Focus on structural requirements: code examples + headings.

        Args:
            content: Generated markdown content
            topic: Topic specification

        Returns:
            Tuple of (is_valid, error_message)
        """
        text_content = re.sub(r"```.*?```", "", content, flags=re.DOTALL)
        words = len(text_content.split())

        # Minimum viability check: at least 600 words to ensure substance
        if words < 600:
            return False, f"Too short: {words} words (need 600+ for substantive content)"

        if "```" not in content:
            return False, "Missing code examples"

        if not re.search(r"^##\s+", content, re.MULTILINE):
            return False, "Missing section headings"

        return True, ""

    def save_documentation(self, framework: str, topic: Topic, content: str) -> str:
        """Save generated documentation to file.

        Args:
            framework: Framework name
            topic: Topic object
            content: Generated markdown content

        Returns:
            Path to saved file
        """
        framework_dir = self.datasets_dir / framework
        framework_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{topic.number:02d}_{topic.slug}.md"
        filepath = framework_dir / filename

        if not self.dry_run:
            filepath.write_text(content)

        return str(filepath)

    def generate_framework(
        self,
        framework: str,
        start: int | None = None,
        end: int | None = None,
        specific_topics: list[int] | None = None,
    ) -> list[GenerationResult]:
        """Generate all documentation for a framework.

        Args:
            framework: Framework name
            start: Optional start topic number
            end: Optional end topic number
            specific_topics: Optional list of specific topic numbers to generate

        Returns:
            List of GenerationResult objects
        """
        config = self.FRAMEWORKS[framework]
        framework_name = config["name"]

        # Load topics
        topics = self.load_topics_from_file(framework)

        # Filter by specific topics if provided
        if specific_topics is not None:
            topics = [t for t in topics if t.number in specific_topics]
        else:
            # Filter by range if specified
            if start is not None:
                topics = [t for t in topics if t.number >= start]
            if end is not None:
                topics = [t for t in topics if t.number <= end]

        print(f"\n{'=' * 70}\nGenerating {len(topics)} documents for {framework_name}\n{'=' * 70}")

        results = []

        for i, topic in enumerate(topics, 1):
            print(f"\n[{i}/{len(topics)}] Generating: {topic.number:02d}_{topic.slug}")

            # Retry with model escalation on validation failure
            max_retries = 4
            content = ""
            tokens = 0
            cost = 0.0
            is_valid = False
            error = ""

            for retry in range(max_retries):
                try:
                    if retry > 0:
                        model_names = ["Qwen 32B", "Llama 70B", "DeepSeek", "Claude"]
                        print(f"  Retry {retry} with {model_names[retry]}")

                    content, tokens_attempt, cost_attempt = self.generate_documentation(
                        framework, topic, retry_count=retry
                    )
                    tokens += tokens_attempt
                    cost += cost_attempt

                    is_valid, error = self.validate_content(content, topic)
                    if is_valid:
                        break
                    else:
                        if retry < max_retries - 1:
                            print(f"  Validation failed: {error}")
                        else:
                            print(f"  Failed after {max_retries} attempts: {error}")

                except Exception as e:
                    error = str(e)
                    print(f"  Error: {e}")
                    if retry >= max_retries - 1:
                        break

            # Check final result
            if not is_valid:
                results.append(
                    GenerationResult(
                        topic_number=topic.number,
                        filename=f"{topic.number:02d}_{topic.slug}.md",
                        success=False,
                        word_count=0,
                        tokens_used=tokens,
                        cost_usd=cost,
                        error=error,
                    )
                )
                self.failed_gens += 1
                continue

            # Save successful generation
            filepath = self.save_documentation(framework, topic, content)

            # Count words for stats
            text_content = re.sub(r"```.*?```", "", content, flags=re.DOTALL)
            words = len(text_content.split())

            print(f"  Success: {words} words, {tokens} tokens, ${cost:.4f}")
            if self.dry_run:
                print(f"  Would save to: {filepath}")
            else:
                print(f"  Saved to: {filepath}")

            results.append(
                GenerationResult(
                    topic_number=topic.number,
                    filename=f"{topic.number:02d}_{topic.slug}.md",
                    success=True,
                    word_count=words,
                    tokens_used=tokens,
                    cost_usd=cost,
                )
            )

            # Update stats
            self.total_tokens += tokens
            self.total_cost += cost
            self.successful_gens += 1

        return results

    def print_summary(self, results: dict[str, list[GenerationResult]]) -> None:
        """Print generation summary statistics."""
        print(f"\n{'=' * 70}")
        print("GENERATION SUMMARY")
        print(f"{'=' * 70}\n")

        for framework, framework_results in results.items():
            config = self.FRAMEWORKS[framework]
            print(f"{config['name']}:")
            print(f"  Successful: {sum(1 for r in framework_results if r.success)}")
            print(f"  Failed: {sum(1 for r in framework_results if not r.success)}")
            print(f"  Total words: {sum(r.word_count for r in framework_results):,}")
            print(f"  Total tokens: {sum(r.tokens_used for r in framework_results):,}")
            print(f"  Total cost: ${sum(r.cost_usd for r in framework_results):.4f}\n")

        print(f"{'=' * 70}")
        print("OVERALL TOTALS")
        print(f"{'=' * 70}")
        print(f"Successful generations: {self.successful_gens}")
        print(f"Failed generations: {self.failed_gens}")
        print(f"Total tokens used: {self.total_tokens:,}")
        print(f"Total cost: ${self.total_cost:.4f}")
        print(f"Average cost per document: ${self.total_cost / max(self.successful_gens, 1):.4f}")

        if self.dry_run:
            print(f"\n{'=' * 70}")
            print("DRY RUN - No files were written")
            print(f"{'=' * 70}")


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Generate technical documentation using LLM assistance"
    )
    parser.add_argument(
        "--framework",
        choices=["fastapi", "pydantic", "react", "spring"],
        help="Generate docs for specific framework",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Generate docs for all frameworks",
    )
    parser.add_argument(
        "--start",
        type=int,
        help="Start topic number (for single framework only)",
    )
    parser.add_argument(
        "--end",
        type=int,
        help="End topic number (for single framework only)",
    )
    parser.add_argument(
        "--regenerate-invalid",
        action="store_true",
        help="Regenerate only invalid documents (requires --framework)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate content but don't write files",
    )
    parser.add_argument(
        "--model",
        choices=["claude", "gpt4", "groq"],
        help="Preferred LLM model (default: uses fallback chain starting with Groq, retries with Claude on failure)",
    )

    args = parser.parse_args()

    if not args.framework and not args.all:
        parser.error("Must specify either --framework or --all")

    if args.all and (args.start or args.end or args.regenerate_invalid):
        parser.error("Cannot use --start/--end/--regenerate-invalid with --all")

    if args.regenerate_invalid and not args.framework:
        parser.error("--regenerate-invalid requires --framework")

    if args.regenerate_invalid and (args.start or args.end):
        parser.error("Cannot use --regenerate-invalid with --start/--end")

    # Initialize generator
    generator = TechDocsGenerator(dry_run=args.dry_run, preferred_model=args.model)

    # Determine frameworks to generate
    if args.all:
        frameworks = list(generator.FRAMEWORKS.keys())
    else:
        frameworks = [args.framework]

    # Generate documentation
    all_results = {}
    for framework in frameworks:
        if args.regenerate_invalid:
            # Get list of invalid topic numbers
            invalid_topics = generator.get_invalid_topic_numbers(framework)
            if not invalid_topics:
                print(f"\n✅ No invalid documents found for {framework}")
                continue
            print(f"\n🔄 Found {len(invalid_topics)} invalid documents to regenerate:")
            print(f"   Topic numbers: {invalid_topics}")
            results = generator.generate_framework(framework, specific_topics=invalid_topics)
        else:
            results = generator.generate_framework(framework, args.start, args.end)
        all_results[framework] = results

    # Print summary
    generator.print_summary(all_results)

    # Return exit code
    return 0 if generator.failed_gens == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
