# Golden Test Set - Hand-Crafted Q&A Pairs

## Overview

This golden test set contains 50 hand-crafted question-answer pairs designed for rigorous RAG evaluation. Unlike synthetic queries, these pairs were manually created by reading the actual documentation and crafting precise answers that can be verified against source documents.

## Creation Methodology

### Selection Criteria

1. **Source Document Review**: Each question was crafted after reading the actual tech documentation
2. **Answer Verification**: Answers were extracted directly from source documents, not inferred
3. **Diversity**: Covered multiple frameworks (FastAPI, Pydantic, React, Spring) and query types
4. **Difficulty Balance**: Mixed simple factual questions with complex multi-hop reasoning

### Query Type Distribution

| Query Type | Count | Description |
|------------|-------|-------------|
| Simple Fact | 10 | Direct factual questions with single-document answers |
| Multi-hop | 10 | Questions requiring reasoning across concepts or documents |
| Temporal | 5 | Version-specific or historical questions |
| Comparison | 10 | Questions comparing concepts, frameworks, or approaches |
| Negation | 5 | Questions about what is NOT true or NOT possible |
| Procedural | 10 | "How-to" questions requiring step-by-step answers |

### Difficulty Distribution

- **Simple (difficulty 1-2)**: 10 pairs - Basic definitions and concepts
- **Moderate (difficulty 3-4)**: 25 pairs - Intermediate concepts requiring understanding
- **Complex (difficulty 5)**: 15 pairs - Advanced multi-hop reasoning or deep comparisons

## Structure

```json
{
  "id": "golden_XXX",
  "query": "The question text",
  "expected_answer": "The verified correct answer",
  "source_docs": ["path/to/doc.md"],
  "difficulty": 1-5,
  "query_type": "simple_fact|multi_hop|temporal|comparison|negation|procedural",
  "notes": "Internal notes about why this pair was included"
}
```

## Usage

### Evaluation

Use this golden set to:
1. **Validate RAG pipeline accuracy** - Compare generated answers to expected answers
2. **Calibrate LLM-as-judge** - Calculate correlation between automated and golden evaluations
3. **Benchmark technique improvements** - Measure impact of HyDE, reranking, etc.
4. **Regression testing** - Ensure changes don't degrade quality on known-good examples

### Validation

```bash
# Validate golden set structure and source document references
python scripts/validate_golden_set.py datasets/golden_set/qa_pairs.json
```

## Quality Assurance

### Verification Checklist

Each Q&A pair was verified for:
- [ ] Answer accuracy against source document
- [ ] Source document path exists in corpus
- [ ] No ambiguity in question phrasing
- [ ] Answer completeness (not truncated)
- [ ] Appropriate difficulty rating
- [ ] Correct query type classification

### Known Limitations

1. **Temporal Questions**: Some version-specific questions may become outdated as frameworks evolve
2. **Framework Coverage**: Weighted toward FastAPI and Spring (more complex docs)
3. **Subjectivity**: Some difficulty ratings involve judgment calls
4. **Answer Length**: Some complex answers are condensed for practicality

## Maintenance

### When to Update

Update the golden set when:
- Source documents are updated or replaced
- New frameworks are added to the corpus
- Evaluation reveals systematic gaps in coverage
- Answer accuracy is questioned (verify and correct)

### Version History

- **v1.0** (2026-02-15): Initial 50 hand-crafted pairs
  - 4 frameworks: FastAPI, Pydantic, React, Spring
  - 6 query types with balanced distribution
  - Difficulty range 1-5 with emphasis on moderate complexity

## Contributors

- Initial creation: Manual extraction from generated tech docs corpus
- Review: Verified against actual document content

## License

Same as parent project (MIT or Apache 2.0).
