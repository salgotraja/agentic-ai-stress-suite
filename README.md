# Agentic AI Stress Test Suite

Production-grade proof-of-concept demonstrating empirical trade-offs in RAG-to-agent workflows. Targets senior engineers transitioning to applied AI with reproducible benchmarks and annotated production code.

## Quick Start

### Prerequisites

- Python 3.11+
- Docker & Docker Compose
- `uv` package manager (or Poetry)
- LLM API keys (Groq, DeepSeek, Claude, Gemini, OpenAI)

### Installation

```bash
# Clone the repository
git clone <repository-url>
cd agentic-ai-stress-suite

# Install dependencies with uv (preferred)
export PATH="$HOME/.local/bin:$PATH"
uv sync --all-extras

# Or with Poetry
poetry install --all-extras

# Copy environment template
cp .env.example .env
# Edit .env with your API keys

# Start local services (embeddings, Redis, Chroma, Phoenix)
cd infra
docker-compose up -d

# Install pre-commit hooks
uv run pre-commit install
```

### Verify Installation

```bash
# Check services
docker-compose ps

# Access Phoenix UI
open http://localhost:6006

# Run tests
uv run pytest tests/unit/ -v
```

## Architecture

### Hybrid Local/Cloud Infrastructure

**Local Services (Docker Compose):**
- **text-embeddings-inference**: BGE-base-en-v1.5 embeddings (Metal-accelerated on M4)
- **Redis**: Cache + state persistence (from Phase 1)
- **Chroma**: Vector database (local dev)
- **Phoenix**: Observability platform
- **Postgres**: Optional, for complex agent state (use `--profile optional`)

**Cloud Services:**
- **LLMs**: Groq → DeepSeek → Claude → Gemini → OpenAI (cost-optimized fallback chain)
- **Qdrant**: Cloud vector DB option (production, Article 2+)
- **Cohere**: Reranker API

### Project Structure

```
src/
├── core/          # Shared utilities (LLM client, config, observability)
├── rag/           # RAG implementations (Articles 1-3)
├── agents/        # Agent systems (Articles 4-5)
└── ops/           # Production concerns (Articles 6-8)

infra/             # Docker Compose setup
tests/             # Unit, integration, benchmarks
examples/          # Runnable demos per article
datasets/          # Tech docs corpus + synthetic queries
results/           # Charts, data, reports
notebooks/         # Jupyter analysis notebooks
```

## Development Workflow

### Generating Documentation

Generate technical documentation for RAG dataset:

```bash
# Generate specific topic range
uv run python scripts/generate_tech_docs.py --framework fastapi --start 1 --end 10
uv run python scripts/generate_tech_docs.py --framework pydantic --start 5 --end 15

# Regenerate only invalid documents
uv run python scripts/generate_tech_docs.py --framework fastapi --regenerate-invalid

# Generate all topics for a framework (1-50)
uv run python scripts/generate_tech_docs.py --framework react

# Generate all frameworks
uv run python scripts/generate_tech_docs.py --all

# Use specific model (default: Qwen 32B → Llama 70B → DeepSeek → Claude fallback)
uv run python scripts/generate_tech_docs.py --framework spring --start 20 --end 30 --model claude

# Dry run (preview without writing files)
uv run python scripts/generate_tech_docs.py --framework fastapi --start 1 --end 5 --dry-run
```

### Validating Documentation

```bash
# Validate all documentation
uv run python scripts/validate_tech_docs.py

# Validate specific framework
uv run python scripts/validate_tech_docs.py --framework fastapi

# Verbose output with warnings
uv run python scripts/validate_tech_docs.py --verbose

# Export validation results to JSON
uv run python scripts/validate_tech_docs.py --output results.json
```

### Generating Synthetic Queries

Generate diverse test queries for RAG evaluation:

```bash
# Generate 30 queries (2 batches of 15-20, default batch size is 20)
uv run python scripts/generate_queries.py --count 30

# Generate large batch with auto-batching (generates in batches of 20)
uv run python scripts/generate_queries.py --count 265 --append

# Append to existing queries file
uv run python scripts/generate_queries.py --count 50 --append

# Generate specific query types
uv run python scripts/generate_queries.py --count 20 --types simple,multi-hop,comparison

# Use specific model (default: Groq → DeepSeek → Claude fallback)
uv run python scripts/generate_queries.py --count 100 --model claude

# Use smaller batch size (10-15) if experiencing JSON parsing errors
uv run python scripts/generate_queries.py --count 200 --batch-size 10

# Custom output file
uv run python scripts/generate_queries.py --count 50 --output datasets/synthetic_queries/custom.json
```

### Utility Scripts

```bash
# Start Phoenix observability server (http://localhost:6006)
uv run python scripts/start_phoenix.py

# Test M4 GPU embeddings (Metal backend)
uv run python scripts/test_m4_embeddings.py
```

### Running Examples

```bash
# Article 1: State-Aware RAG
cd examples/article_01_state_aware_rag/
uv run python demo.py --query "What is FastAPI?"

# Article 4: Single-Agent
cd examples/article_04_single_agent/
uv run python demo.py --agent react --query "Calculate 2^8"
```

### Running Benchmarks

```bash
# Run Article 1 benchmarks (Naive RAG baseline)
uv run python benchmarks/run_article_01.py

# Custom dataset or output
uv run python benchmarks/run_article_01.py --dataset datasets/synthetic_queries/custom.json --output results/data/custom.json

# More runs for better statistics
uv run python benchmarks/run_article_01.py --runs 5

# Different retrieval parameters
uv run python benchmarks/run_article_01.py --top-k 10

# Generate charts from benchmark results (executes notebook and updates in-place)
uv run jupyter nbconvert --execute --to notebook --inplace notebooks/analysis_article_01.ipynb

# Alternative: Open notebook interactively
uv run jupyter notebook notebooks/analysis_article_01.ipynb
```

### Running Benchmarks on Google Colab

If you hit rate limits locally, use Google Colab for benchmarks:

```bash
# 1. Upload notebook to Colab
#    - Go to https://colab.research.google.com
#    - File → Upload notebook
#    - Select: notebooks/colab_benchmark_runner.ipynb

# 2. Set API keys in Colab Secrets (🔑 icon)
#    - Add GROQ_API_KEY (required)
#    - Add OPENAI_API_KEY, ANTHROPIC_API_KEY (optional fallback)

# 3. Run all cells in Colab
#    - Runtime → Run all (Ctrl+F9)
#    - Wait 15-30 minutes
#    - Download results automatically

# 4. Merge results back to local repo
uv run python scripts/merge_colab_results.py ~/Downloads/article_01_benchmarks.json

# 5. Generate visualizations locally
uv run jupyter nbconvert --execute --to notebook --inplace notebooks/analysis_article_01.ipynb
```

**Benefits of Colab:**
- Fresh API quota (different IP)
- Free T4 GPU for embeddings
- No Docker dependencies
- Longer runtimes without local interruption

See `notebooks/COLAB_SETUP.md` for detailed instructions.

### Code Quality Checks

```bash
# Linting
uv run ruff check src/ tests/

# Type checking
uv run mypy src/

# Formatting
uv run black src/ tests/
uv run isort src/ tests/

# Tests with coverage
uv run pytest tests/unit/ --cov=src --cov-report=term-missing
```

## Implementation Progress

**Current Status**: Phase 1 - End-to-End Spike

See [docs/tasks.md](docs/tasks.md) for detailed task tracking across 6 implementation phases.

## Key Documents

- **CLAUDE.md**: Development guidelines for Claude Code
- **docs/specifications.md**: Complete technical specifications
- **docs/requirements.md**: Functional and non-functional requirements
- **docs/tasks.md**: 190 trackable tasks across 6 phases
- **docs/discussions.md**: Project rationale and goals

## Contributing

This is a personal learning project demonstrating applied AI patterns. Not currently accepting external contributions, but feel free to fork and adapt for your own use.

## License

MIT License - see [LICENSE](LICENSE) file for details.

## Blog Series

This codebase supports an 8-9 article blog series:

1. **State-Aware RAG**: Moving Beyond Top-K Retrieval
2. **Advanced Retrieval**: Hybrid Search, Reranking, Metadata Mastery
3. **Evaluation-Driven RAG**: Metrics, Tracing, Continuous Improvement
4. **From RAG to Agents**: Building Reliable Single-Agent Workflows
5. **Multi-Agent Systems**: Orchestration Patterns and Collaboration
6. **LLM Ops in Production**: Caching, Routing, Observability, Cost Control
7. **Security and Governance**: Prompt Injection, Data Leakage, Compliance
8. **Scaling Agentic Systems**: Performance, Fault Tolerance, Deployment
9. **Deep Learning Integrations**: Custom Architectures and PyTorch/JAX Internals

## Contact

Author: Jagdish Salgotra (@salgotraja)

**Target Audience**: Senior engineers and architects transitioning to applied AI
