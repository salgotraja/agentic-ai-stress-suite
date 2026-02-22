# Agentic AI Stress Test Suite

[![CI](https://github.com/salgotraja/agentic-ai-stress-suite/actions/workflows/ci.yml/badge.svg)](https://github.com/salgotraja/agentic-ai-stress-suite/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Coverage](https://img.shields.io/badge/coverage-90%25-brightgreen)

Production-grade proof-of-concept demonstrating empirical trade-offs in
RAG-to-agent workflows. 9 articles, reproducible benchmarks, ~25,000 lines
of annotated production code.

**Target audience**: Senior engineers transitioning to applied AI.

## Key Results

| Technique | Metric | Improvement |
|-----------|--------|-------------|
| Hybrid search (BM25+RRF) | Recall@5 | 0.723 → 0.862 (+19%) |
| BGE fine-tuning | Recall@5 | 0.61 → 0.78 (+17%) |
| Semantic cache | LLM cost | $0.375 → $0.003 per session (99.2%) |
| Parallel tool execution | Latency | 297ms → 114ms (2.62×) |
| INT8 quantisation | Embed speed | 28ms → 11ms (2.51×, 4× smaller) |
| K8s autoscaling | Throughput | 74 rps peak, p95=372ms at 50 users |
| Guardrails | Safety | 100% PII coverage, 0% false positives |

## Quick Start

```bash
# Clone and install
git clone <repository-url>
cd agentic-ai-stress-suite
uv sync

# Copy env template and add your API keys
cp .env.example .env

# Start local services (Redis, Chroma, Phoenix observability)
docker-compose -f infra/docker-compose.yml up -d

# Verify
uv run pytest tests/unit/ -v
open http://localhost:6006  # Phoenix traces
```

**Prerequisites**: Python 3.11+, Docker, `uv`, API keys for at least one LLM
provider (Groq is cheapest for development).

[//]: # (## Articles and Code)

[//]: # ()
[//]: # (| # | Title | Key File | Blog Post |)

[//]: # (|---|-------|----------|-----------|)

[//]: # (| 1 | State-Aware RAG | `src/rag/advanced_rag.py` | [Article 1]&#40;docs/blog/article_01_state_aware_rag.md&#41; |)

[//]: # (| 2 | Advanced Retrieval | `src/rag/hybrid_search.py` | [Article 2]&#40;docs/blog/article_02_advanced_retrieval.md&#41; |)

[//]: # (| 3 | Evaluation Framework | `src/rag/evaluation/` | [Article 3]&#40;docs/blog/article_03_evaluation_framework.md&#41; |)

[//]: # (| 4 | Single-Agent | `src/agents/single_agent.py` | [Article 4]&#40;docs/blog/article_04_single_agent.md&#41; |)

[//]: # (| 5 | Multi-Agent | `src/agents/multi_agent.py` | [Article 5]&#40;docs/blog/article_05_multi_agent.md&#41; |)

[//]: # (| 6 | LLM Ops | `src/ops/caching.py`, `routing.py` | [Article 6]&#40;docs/blog/article_06_llm_ops.md&#41; |)

[//]: # (| 7 | Security | `src/ops/security.py` | [Article 7]&#40;docs/blog/article_07_security.md&#41; |)

[//]: # (| 8 | Scaling | `src/ops/deployment/k8s/` | [Article 8]&#40;docs/blog/article_08_scaling.md&#41; |)

[//]: # (| 9 | Deep Learning | `examples/article_09_dl/` | [Article 9]&#40;docs/blog/article_09_deep_learning.md&#41; |)

## Architecture

```
src/
├── core/           # LLM client (Groq→DeepSeek→Claude→Gemini→OpenAI fallback),
│                   # config, observability (@traced_*), benchmarking, cost tracking
├── rag/            # Naive RAG, HyDE, query decomp, graph RAG, hybrid search,
│                   # reranking, chunking, evaluation (RAGAS/DeepEval/LLM-judge)
├── agents/
│   ├── tools/      # Calculator, RAG, Search, DB, CodeExec, MCP, CustomEmbeddingRAG
│   ├── single_agent.py   # ReActAgent + PlanAndExecuteAgent + parallel tool dispatch
│   ├── multi_agent.py    # Sequential, critic loop, parallel fan-out, conflict resolution
│   └── state_persistence.py  # InMemory / SQLite / Redis backends
└── ops/
    ├── caching.py   # L1 exact (MD5/Redis) + L2 semantic (cosine>0.95)
    ├── routing.py   # LiteLLM fallback chain, complexity router, cost forecasting
    └── security.py  # Guardrails, Llama-Guard, PII scanner, audit logger

infra/              # Docker Compose (Redis, Chroma, Phoenix, Neo4j optional)
examples/           # Runnable demos per article
benchmarks/         # Reproducible benchmark runners
notebooks/          # Jupyter analysis notebooks with charts
datasets/           # 200 tech docs + 450 synthetic queries + 50 golden Q&A pairs
results/            # charts/, data/, reports/
tests/unit/         # 28+ files, mock-only, <1s per test
tests/integration/  # Testcontainers-based, real Redis/Postgres
```

## LLM Cost Strategy

Development uses Groq (Llama-3-8B: ~$0.05/1M tokens). Benchmarks escalate
to premium models only when quality comparison is the point. Local embeddings
(BGE-base-en-v1.5, Metal-accelerated) are free.

Fallback chain: `Groq-8B → Groq-70B → DeepSeek → Claude → Gemini → OpenAI`

Total spend across all 9 articles: **<$12**.

## Running Benchmarks

```bash
# Individual article benchmarks (mock mode, no API required)
uv run python benchmarks/run_article_04.py --mock
uv run python benchmarks/run_article_07.py

# Article 9: DL benchmarks (requires training data)
uv run python benchmarks/run_article_09.py --quick

# Generate all charts (executes Jupyter notebooks)
./scripts/generate_all_charts.sh
```

## Code Quality

```bash
uv run ruff check src/ tests/
uv run mypy src/
uv run pytest tests/unit/ --cov=src/ --cov-report=term-missing
```

## Docker Compose Services

```bash
docker-compose -f infra/docker-compose.yml up -d   # start
docker-compose -f infra/docker-compose.yml ps      # status
docker-compose -f infra/docker-compose.yml down    # stop
```

Services: Redis (cache/state), Chroma (vector DB), Phoenix (observability at
`localhost:6006`). Neo4j optional for graph RAG demos.

## Key Documents

- `docs/specifications.md` — full technical specifications
- `docs/requirements.md` — functional and non-functional requirements
- `docs/tasks.md` — 110 implementation tasks (all phases complete)
- `docs/blog/` — 9 article drafts with code references and benchmarks
- `handover.md` — full implementation history and architectural decisions

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for how to add new RAG techniques, agent
tools, or benchmarks.

## License

MIT — see [LICENSE](LICENSE).
