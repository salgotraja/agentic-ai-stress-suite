# Agentic AI Stress Test Suite

[![CI](https://github.com/salgotraja/agentic-ai-stress-suite/actions/workflows/ci.yml/badge.svg)](https://github.com/salgotraja/agentic-ai-stress-suite/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Coverage](https://img.shields.io/badge/coverage-77%25-green)

Production-grade proof-of-concept demonstrating empirical trade-offs in
RAG-to-agent workflows. 9 articles, reproducible benchmarks, ~25,000 lines
of annotated production code.

**Target audience**: Senior engineers transitioning to applied AI.

## Key Results

| Technique | Metric | Improvement |
|-----------|--------|-------------|
| Full retrieval pipeline (hybrid + rerank + filter + chunking) | Recall@5 | 0.723 → 0.862 (+19%) |
| Hybrid search alone (BM25+RRF) | Recall@5 | 0.723 → 0.781 (+8%) |
| BGE fine-tuning (regression) | Recall@5 | 0.729 → 0.622 (-11%) |
| Semantic cache (alone) | LLM cost on 100-query workload (vs uncached Groq-8B) | $0.001272 → $0.000769 (39.6%) |
| Complexity routing (alone) | LLM cost on 100-query workload (vs all-GPT-4o reprice) | $0.1935 → $0.00228 (98.8%) |
| Parallel tool execution | Latency | 297ms → 114ms (2.62×) |
| INT8 quantisation (BGE) | Model size | 438MB → 110MB (4× smaller); slower on M4 (QNNPACK has no ARM speedup) |
| torch.compile (BGE on MPS) | Embed latency | 28.3ms → 28.7ms (0.99×, no win on Apple Silicon) |
| Custom cross-encoder reranker | NDCG@5 / latency | 0.761 → 0.874 (+15%) and 339ms → 112ms (3× faster) vs FlashRank |
| K8s autoscaling | Throughput | 74 rps peak, p95=372ms at 50 users |
| Guardrails (PII-extraction category) | Block rate | 100% on PII-extraction prompts (regex+spaCy NER), 0% false positives. Overall block rate across all five attack categories was 19/99 |

## Quick Start

```bash
# Clone and install
git clone <repository-url>
cd agentic-ai-stress-suite
uv sync

# Copy env template and add your API keys (.env.local is gitignored;
# .env holds team defaults committed to the repo)
cp .env.example .env.local

# Start local services (Redis, Chroma, Phoenix observability)
docker-compose -f infra/docker-compose.yml up -d

# Verify
uv run pytest tests/unit/ -v
open http://localhost:6006  # Phoenix traces
```

**Prerequisites**: Python 3.11+, Docker, `uv`, API keys for at least one LLM
provider (Groq is cheapest for development).

## Articles and Code

Each article is implemented in production-grade code with teaching comments,
benchmarks, and runnable demos. Long-form blog posts are published separately.

| # | Title | Key Code |
|---|-------|----------|
| 1 | State-Aware RAG (HyDE, query decomposition, graph RAG) | `src/rag/advanced_rag.py`, `graph_rag.py` |
| 2 | Advanced Retrieval (BM25+RRF, reranking, metadata filtering, chunking) | `src/rag/hybrid_search.py`, `reranking.py`, `metadata_filter.py`, `chunking.py` |
| 3 | Evaluation Framework (RAGAS, DeepEval, LLM-judge, drift, A/B) | `src/rag/evaluation/` |
| 4 | Single-Agent (ReAct, Plan-and-Execute, parallel tool dispatch) | `src/agents/single_agent.py`, `src/agents/tools/` |
| 5 | Multi-Agent (sequential, critic loop, parallel fan-out, conflict resolution) | `src/agents/multi_agent.py` |
| 6 | LLM Ops (tiered cache, fallback router, cost tracking) | `src/ops/caching.py`, `src/ops/routing.py`, `src/core/cost_logger.py` |
| 7 | Security (guardrails, Llama-Guard, PII scanner, red-team) | `src/ops/security.py` |
| 8 | Scaling (parallel dispatch, K8s manifests, Locust load test) | `src/ops/deployment/k8s/`, `src/ops/deployment/load_test.py` |
| 9 | Deep Learning (BGE fine-tune, torch.compile, INT8, JAX vs PyTorch) | `examples/article_09_dl/`, `benchmarks/run_article_09.py` |

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

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for how to add new RAG techniques, agent
tools, or benchmarks.

## License

MIT - see [LICENSE](LICENSE).
