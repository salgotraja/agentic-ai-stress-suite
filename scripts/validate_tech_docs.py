#!/usr/bin/env python3
"""Validate technical documentation quality.

This script validates all generated technical documentation files to ensure they meet
quality standards defined in the project specifications.

Validation Checks:
1. Word count: 800-1500 words (excluding code blocks)
2. File naming: {number:02d}_{slug}.md format
3. Markdown structure: Proper headings (# and ##)
4. Code examples: At least one code block with syntax highlighting
5. Content quality: No placeholder text, proper formatting
6. Cross-references: Basic validation of mentioned frameworks

Usage:
    # Validate all docs
    python scripts/validate_tech_docs.py

    # Validate specific framework
    python scripts/validate_tech_docs.py --framework fastapi

    # Verbose output
    python scripts/validate_tech_docs.py --verbose

    # Export results to JSON
    python scripts/validate_tech_docs.py --output results.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class ValidationResult:
    """Result of validating a single document."""

    framework: str
    filename: str
    filepath: str
    valid: bool
    word_count: int
    issues: list[str]
    warnings: list[str]


class TechDocsValidator:
    """Validator for technical documentation."""

    FRAMEWORKS = ["fastapi", "pydantic", "react", "spring"]

    # Word count constraints
    MIN_WORDS = 800
    MAX_WORDS = 1500
    WORD_COUNT_BUFFER = 200  # Allow buffer for complex topics

    # Expected file naming pattern: 01_introduction.md
    FILE_PATTERN = re.compile(r"^(\d{2})_([a-z0-9_]+)\.md$")

    def __init__(self, verbose: bool = False) -> None:
        """Initialize validator.

        Args:
            verbose: Enable verbose output
        """
        self.verbose = verbose
        self.project_root = Path(__file__).parent.parent.resolve()
        self.datasets_dir = self.project_root / "datasets" / "tech_docs"

        # Statistics
        self.total_docs = 0
        self.valid_docs = 0
        self.invalid_docs = 0

    def validate_file_naming(self, filename: str) -> tuple[bool, list[str]]:
        """Validate file naming convention.

        Args:
            filename: File name to validate

        Returns:
            Tuple of (is_valid, issues)
        """
        issues = []

        if filename == "attribution.md":
            return True, []  # Skip attribution file

        match = self.FILE_PATTERN.match(filename)
        if not match:
            issues.append(
                f"Invalid file naming: {filename} (expected format: 01_topic_name.md)"
            )
            return False, issues

        number_str, slug = match.groups()
        number = int(number_str)

        if number < 1 or number > 99:
            issues.append(f"Invalid topic number: {number} (must be 01-99)")

        if not re.match(r"^[a-z0-9_]+$", slug):
            issues.append(f"Invalid slug: {slug} (must be lowercase alphanumeric with underscores)")

        return len(issues) == 0, issues

    def validate_content(
        self, content: str, filename: str
    ) -> tuple[bool, int, list[str], list[str]]:
        """Validate document content.

        Args:
            content: Document content
            filename: File name for context

        Returns:
            Tuple of (is_valid, word_count, issues, warnings)
        """
        issues = []
        warnings = []

        # Extract text content (excluding code blocks for word count)
        text_content = re.sub(r"```.*?```", "", content, flags=re.DOTALL)
        words = text_content.split()
        word_count = len(words)

        # 1. Validate word count
        if word_count < self.MIN_WORDS:
            issues.append(
                f"Too short: {word_count} words (minimum: {self.MIN_WORDS})"
            )
        elif word_count > self.MAX_WORDS + self.WORD_COUNT_BUFFER:
            warnings.append(
                f"Lengthy: {word_count} words (target: {self.MIN_WORDS}-{self.MAX_WORDS})"
            )

        # 2. Validate markdown structure
        if not content.strip():
            issues.append("Empty file")
            return False, word_count, issues, warnings

        # Check for main heading (# Title)
        if not re.search(r"^#\s+.+$", content, re.MULTILINE):
            issues.append("Missing main heading (# Title)")

        # Check for section headings (## Section)
        section_headings = re.findall(r"^##\s+.+$", content, re.MULTILINE)
        if not section_headings:
            issues.append("Missing section headings (## Section)")
        elif self.verbose and len(section_headings) < 3:
            warnings.append(
                f"Few section headings: {len(section_headings)} (recommended: 3+)"
            )

        # 3. Validate code examples
        code_blocks = re.findall(r"```(\w+)?\n", content)
        if not code_blocks:
            issues.append("Missing code examples")
        elif len(code_blocks) < 2 and self.verbose:
            warnings.append(
                f"Few code examples: {len(code_blocks)} (recommended: 2+)"
            )

        # Check for syntax highlighting in code blocks
        code_blocks_no_lang = re.findall(r"```\n", content)
        if code_blocks_no_lang and self.verbose:
            warnings.append(
                f"{len(code_blocks_no_lang)} code block(s) missing syntax highlighting"
            )

        # 4. Check for placeholder/template text
        placeholders = [
            "[TODO]",
            "[PLACEHOLDER]",
            "Lorem ipsum",
            "[insert",
            "[add content",
        ]
        for placeholder in placeholders:
            if placeholder.lower() in content.lower():
                issues.append(f"Contains placeholder text: {placeholder}")

        # 5. Validate content quality
        if len(content) < 500:  # Minimum character count
            issues.append("Content too short (< 500 characters)")

        # Check for broken markdown links
        broken_links = re.findall(r"\[([^\]]+)\]\(\)", content)
        if broken_links:
            issues.append(f"Broken markdown links: {len(broken_links)}")

        # 6. Check for cross-framework references (basic validation)
        other_frameworks = {
            "fastapi": ["spring", "react", "pydantic"],
            "pydantic": ["fastapi", "spring", "react"],
            "react": ["fastapi", "spring", "pydantic"],
            "spring": ["fastapi", "react", "pydantic"],
        }

        # Detect framework from context (could be improved)
        framework_detected = None
        for fw in self.FRAMEWORKS:
            if fw.lower() in filename.lower():
                framework_detected = fw
                break

        if framework_detected and self.verbose:
            # Look for cross-framework mentions
            mentions = []
            for other_fw in other_frameworks.get(framework_detected, []):
                fw_name = other_fw.capitalize()
                if re.search(rf"\b{fw_name}\b", content, re.IGNORECASE):
                    mentions.append(other_fw)

            if mentions:
                warnings.append(f"Cross-references found: {', '.join(mentions)}")

        is_valid = len(issues) == 0
        return is_valid, word_count, issues, warnings

    def validate_document(self, filepath: Path, framework: str) -> ValidationResult:
        """Validate a single documentation file.

        Args:
            filepath: Path to documentation file
            framework: Framework name

        Returns:
            ValidationResult object
        """
        filename = filepath.name
        issues = []
        warnings = []

        # Skip attribution file
        if filename == "attribution.md":
            return ValidationResult(
                framework=framework,
                filename=filename,
                filepath=str(filepath),
                valid=True,
                word_count=0,
                issues=[],
                warnings=["Skipped: attribution file"],
            )

        # Validate file naming
        naming_valid, naming_issues = self.validate_file_naming(filename)
        issues.extend(naming_issues)

        # Read content
        try:
            content = filepath.read_text()
        except Exception as e:
            issues.append(f"Failed to read file: {e}")
            return ValidationResult(
                framework=framework,
                filename=filename,
                filepath=str(filepath),
                valid=False,
                word_count=0,
                issues=issues,
                warnings=warnings,
            )

        # Validate content
        content_valid, word_count, content_issues, content_warnings = (
            self.validate_content(content, filename)
        )
        issues.extend(content_issues)
        warnings.extend(content_warnings)

        is_valid = naming_valid and content_valid

        return ValidationResult(
            framework=framework,
            filename=filename,
            filepath=str(filepath),
            valid=is_valid,
            word_count=word_count,
            issues=issues,
            warnings=warnings,
        )

    def validate_framework(self, framework: str) -> list[ValidationResult]:
        """Validate all documentation for a framework.

        Args:
            framework: Framework name

        Returns:
            List of ValidationResult objects
        """
        framework_dir = self.datasets_dir / framework

        if not framework_dir.exists():
            print(f"⚠️  Framework directory not found: {framework_dir}")
            return []

        print(f"\n{'='*70}")
        print(f"Validating {framework.upper()} documentation")
        print(f"{'='*70}\n")

        results = []
        doc_files = sorted(framework_dir.glob("*.md"))

        for filepath in doc_files:
            result = self.validate_document(filepath, framework)
            results.append(result)

            self.total_docs += 1
            if result.valid:
                self.valid_docs += 1
                if self.verbose or result.warnings:
                    print(f"✅ {result.filename}")
                    if result.word_count > 0:
                        print(f"   {result.word_count} words")
                    if result.warnings:
                        for warning in result.warnings:
                            print(f"   ⚠️  {warning}")
            else:
                self.invalid_docs += 1
                print(f"❌ {result.filename}")
                for issue in result.issues:
                    print(f"   🔴 {issue}")
                if result.warnings:
                    for warning in result.warnings:
                        print(f"   ⚠️  {warning}")

        return results

    def validate_all(self, frameworks: list[str] | None = None) -> dict[str, list[ValidationResult]]:
        """Validate documentation for all or specified frameworks.

        Args:
            frameworks: List of framework names (None = all)

        Returns:
            Dict mapping framework to list of ValidationResult
        """
        if frameworks is None:
            frameworks = self.FRAMEWORKS

        all_results = {}
        for framework in frameworks:
            results = self.validate_framework(framework)
            all_results[framework] = results

        return all_results

    def print_summary(self, all_results: dict[str, list[ValidationResult]]) -> None:
        """Print validation summary.

        Args:
            all_results: Validation results by framework
        """
        print(f"\n{'='*70}")
        print("VALIDATION SUMMARY")
        print(f"{'='*70}\n")

        for framework, results in all_results.items():
            valid = sum(1 for r in results if r.valid)
            invalid = sum(1 for r in results if not r.valid)
            total_words = sum(r.word_count for r in results if r.word_count > 0)
            avg_words = total_words / max(len(results), 1)

            print(f"{framework.upper()}:")
            print(f"  Total docs: {len(results)}")
            print(f"  Valid: {valid} ✅")
            print(f"  Invalid: {invalid} ❌")
            if total_words > 0:
                print(f"  Total words: {total_words:,}")
                print(f"  Average words: {avg_words:.0f}\n")
            else:
                print()

        print(f"{'='*70}")
        print(f"OVERALL TOTALS")
        print(f"{'='*70}")
        print(f"Total documents: {self.total_docs}")
        print(f"Valid documents: {self.valid_docs} ✅")
        print(f"Invalid documents: {self.invalid_docs} ❌")

        if self.invalid_docs == 0:
            print(f"\n🎉 All {self.total_docs} documents passed validation!")
        else:
            print(
                f"\n⚠️  {self.invalid_docs} document(s) need attention"
            )

    def export_results(
        self, all_results: dict[str, list[ValidationResult]], output_file: Path
    ) -> None:
        """Export validation results to JSON.

        Args:
            all_results: Validation results by framework
            output_file: Output JSON file path
        """
        export_data = {
            "summary": {
                "total_docs": self.total_docs,
                "valid_docs": self.valid_docs,
                "invalid_docs": self.invalid_docs,
            },
            "frameworks": {},
        }

        for framework, results in all_results.items():
            export_data["frameworks"][framework] = [
                asdict(result) for result in results
            ]

        output_file.write_text(json.dumps(export_data, indent=2))
        print(f"\n📊 Results exported to: {output_file}")


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Validate technical documentation quality"
    )
    parser.add_argument(
        "--framework",
        choices=["fastapi", "pydantic", "react", "spring"],
        help="Validate specific framework only",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed validation output",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        help="Export validation results to JSON file",
    )

    args = parser.parse_args()

    # Initialize validator
    validator = TechDocsValidator(verbose=args.verbose)

    # Validate documents
    if args.framework:
        all_results = validator.validate_all([args.framework])
    else:
        all_results = validator.validate_all()

    # Print summary
    validator.print_summary(all_results)

    # Export results if requested
    if args.output:
        validator.export_results(all_results, args.output)

    # Return exit code
    return 0 if validator.invalid_docs == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
