# Contributing

## Adding a New RAG Technique

1. Create `src/rag/your_technique.py` following the pattern in `advanced_rag.py`
2. Implement the retrieval method with `@traced_retrieval` decorator
3. Add unit tests in `tests/unit/rag/test_your_technique.py` (mock all LLM calls)
4. Add a benchmark in `benchmarks/` that reports Recall@K against the golden set
5. Include teaching comments explaining why the technique works and its trade-offs

## Adding a New Agent Tool

1. Extend `BaseTool` in `src/agents/tools/your_tool.py`
2. Implement `execute()`, `mock_execute()`, and `describe()`
3. `mock_execute()` must return a deterministic response - tests use this
4. Add unit tests with `mock=True` in `tests/unit/agents/tools/`
5. Register the tool in `src/agents/single_agent.py`

## Running Tests

```bash
# Unit tests (fast, no Docker, no API keys)
uv run pytest tests/unit/ -v

# Integration tests (requires Docker for testcontainers)
uv run pytest tests/integration/ -v

# Specific test
uv run pytest tests/unit/core/test_config.py -v
```

## Code Style

- Type hints required on all public functions
- Teaching comments required on non-trivial implementations (WHY, not WHAT)
- No emojis in code, comments, or log messages
- `ruff`, `black`, `isort`, `mypy` must all pass before committing
- Pre-commit hooks enforce these automatically

## Commit Format

Conventional commits:
- `feat(rag): add ColBERT-style late interaction reranker`
- `fix(agents): handle timeout in parallel tool dispatch`
- `docs(blog): polish Article 3 evaluation section`

## PR Process

1. Fork the repository
2. Create a branch: `feat/your-feature-name`
3. Run the full quality check: `uv run pytest tests/unit/ && uv run mypy src/`
4. Open a PR with a description of the technique and its trade-offs
