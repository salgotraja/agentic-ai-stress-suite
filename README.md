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
# Article 1 benchmarks
uv run python benchmarks/run_article_01.py --dataset datasets/synthetic_queries/article_01.json

# Generate charts
jupyter nbconvert --execute notebooks/analysis_article_01.ipynb
```

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
