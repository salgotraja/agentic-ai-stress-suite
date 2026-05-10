# Agentic AI Stress Test Suite

[![CI](https://github.com/salgotraja/agentic-ai-stress-suite/actions/workflows/ci.yml/badge.svg)](https://github.com/salgotraja/agentic-ai-stress-suite/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Coverage](https://img.shields.io/badge/coverage-75%25-green)

Production-grade proof-of-concept demonstrating empirical trade-offs in
RAG-to-agent workflows. ~25,000 lines of annotated production code with
reproducible benchmarks across retrieval, agents, LLM ops, security,
scaling, and custom embeddings.

**Target audience**: Senior engineers transitioning to applied AI.

## What This Is

A reproducible empirical study of where production RAG-to-agent stacks
actually break. ~25,000 lines of annotated production code, one harness,
one corpus, one set of frameworks, organized as 9 self-contained
experiments (state-aware RAG, advanced retrieval, evaluation,
single-agent, multi-agent, LLM ops, security, scaling, custom embeddings).
Each experiment isolates a specific design decision (HyDE vs
decomposition, dense vs hybrid, ReAct vs Plan-and-Execute, INT8 vs FP32,
kill-the-provider vs poison-the-corpus) and measures the trade-off in
cost, latency, accuracy, and resilience.

## How to Read These Results

Every row in the tables below comes from a runner under `benchmarks/`,
writes JSON to `results/data/`, and renders a chart via Jupyter. The
"Key Results" table reports happy-path measurements; "Stress Test
Results" reports the same code under chaos injection (`--chaos` flag).
Numbers are mean over 3 runs unless noted. We publish the numbers that
lost too: BGE fine-tune regressed -11%, hybrid recall tied dense, INT8
on Apple Silicon was a wash.

## Key Results

| Technique | Metric | Improvement |
|-----------|--------|-------------|
| Hybrid (BM25+dense+RRF) vs dense baseline (30q / 211 chunks) | Recall@5 / MRR | dense 0.761 / 0.739 → hybrid 0.761 / 0.648 (no recall lift; MRR drops on rank noise) |
| + FlashRank reranking on top-20 candidates | Recall@5 / MRR | 0.683 / 0.769 (cross-encoder recovers ranking quality but mispredicts on edge cases; trade-off, not pure win) |
| BGE fine-tuning (regression) | Recall@5 | 0.729 → 0.622 (-11%) |
| Semantic cache (alone) | LLM cost on 100-query workload (vs uncached Groq-8B) | $0.001272 → $0.000769 (39.6%) |
| Complexity routing (alone) | LLM cost on 100-query workload (vs all-GPT-4o reprice) | $0.1935 → $0.00228 (98.8%) |
| INT8 quantisation (BGE) | Model size | 438MB → 110MB (4× smaller); slower on M4 (QNNPACK has no ARM speedup) |
| torch.compile (BGE on MPS) | Embed latency | 23.97 ms → 26.12 ms (0.92×, no win on Apple Silicon) |
| Custom cross-encoder reranker | NDCG@5 / latency | 0.761 → 0.874 (+15%) and 341 ms → 121 ms (2.82× faster) vs FlashRank |
| K8s replica scaling (LLM-bound) | Throughput at sustained 50 users | r=2 → r=5 (2.5× pods) = 3.64 → 3.93 rps (+8%); cloud-LLM RTT is the gating factor |
| K8s saturation cliff | Spike to 200 users at r=2 | 85.4% `RemoteDisconnected`; both pods SIGKILLed by liveness; cluster self-heals |
| Guardrails (regex + Llama-Prompt-Guard-2-86m on Groq) | Overall block rate on 99-prompt red team | 68/99 blocked, 0% false positives on 5 benign queries; per-call p50 latency ~124 ms |

## Stress Test Results (fault injection)

Running the same code under failure shows what graceful degradation actually
costs. Every number below is reproducible via the `--chaos` flag on the
relevant runner; raw JSON lives at `results/data/article_0[67]_stress.json`.

| Article | Scenario | Happy path | Under chaos | Key finding |
|---------|----------|-----------|-------------|-------------|
| 6 | `degraded_groq` (Groq killed after 3 calls; DeepSeek p50/p99 = 4s/16s injected) | 788 ms / $0.00035 / 30 Groq calls | 20,955 ms / $0.00775 / 3 Groq + 27 DeepSeek | Fallback fires at exactly the kill threshold; **0 query loss, 26x latency, 22x cost**. Resilience is not free. |
| 7 | `corpus_poisoning` (5 probe queries vs poisoned BGE index, top-k=3) | n/a (clean corpus does not surface adversarial chunks) | regex-only rails: **4/5 (80%) bypassed**; regex + raw-chunk detector: **0/5 (0%) bypassed** | Same fixture, same prompts, same LLM. Only the rail config differs. Verbatim-chunk detector catches 5/5 adversarial blocks regex misses. |

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

[//]: # ()
[//]: # (## Articles and Code)

[//]: # ()
[//]: # (Each article is implemented in production-grade code with teaching comments,)

[//]: # (benchmarks, and runnable demos. Long-form blog posts are published separately.)

[//]: # ()
[//]: # (| # | Title | Key Code |)

[//]: # (|---|-------|----------|)

[//]: # (| 1 | State-Aware RAG &#40;HyDE, query decomposition, graph RAG&#41; | `src/rag/advanced_rag.py`, `graph_rag.py` |)

[//]: # (| 2 | Advanced Retrieval &#40;BM25+RRF, reranking, metadata filtering, chunking&#41; | `src/rag/hybrid_search.py`, `reranking.py`, `metadata_filter.py`, `chunking.py` |)

[//]: # (| 3 | Evaluation Framework &#40;RAGAS, DeepEval, LLM-judge, drift, A/B&#41; | `src/rag/evaluation/` |)

[//]: # (| 4 | Single-Agent &#40;ReAct, Plan-and-Execute, parallel tool dispatch&#41; | `src/agents/single_agent.py`, `src/agents/tools/` |)

[//]: # (| 5 | Multi-Agent &#40;sequential, critic loop, parallel fan-out, conflict resolution&#41; | `src/agents/multi_agent.py` |)

[//]: # (| 6 | LLM Ops &#40;tiered cache, fallback router, cost tracking&#41; | `src/ops/caching.py`, `src/ops/routing.py`, `src/core/cost_logger.py` |)

[//]: # (| 7 | Security &#40;guardrails, Llama-Guard, PII scanner, red-team&#41; | `src/ops/security.py` |)

[//]: # (| 8 | Scaling &#40;parallel dispatch, K8s manifests, Locust load test&#41; | `src/ops/deployment/k8s/`, `src/ops/deployment/load_test.py` |)

[//]: # (| 9 | Deep Learning &#40;BGE fine-tune, torch.compile, INT8, JAX vs PyTorch&#41; | `examples/article_09_dl/`, `benchmarks/run_article_09.py` |)

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

Total spend to reproduce every benchmark in this repo: **<$12**.

## Running Benchmarks

Every runner honours `SMOKE_TEST=1` and exits after imports / setup, so CI
can validate the entry point without spending budget. All runners write to
`results/data/article_NN_benchmarks.json` (or `_stress.json` under `--chaos`).

```bash
# Article 1: State-aware RAG (naive, HyDE, query decomposition, graph RAG)
uv run python benchmarks/run_article_01.py --runs 3
#   --skip-naive | --skip-advanced | --top-k N | --docs-dir PATH

# Article 2: Advanced retrieval (hybrid search, reranking, metadata filtering)
uv run python benchmarks/run_article_02.py --runs 3
#   --cohere (requires COHERE_API_KEY) | --dry-run

# Article 3: Evaluation (RAGAS + LLM-as-judge)
uv run python benchmarks/run_article_03.py --runs 3 --queries 30 \
    --judge-model gpt-4o-mini
#   --judge-model is recommended: Groq Llama-3-8B emits malformed rubric
#   JSON >70% of the time. --ragas-llm openai/gpt-4o-mini overrides RAGAS too.
#   --skip-ragas | --skip-judge

# Article 4: Single-agent (ReAct vs Plan-and-Execute)
uv run python benchmarks/run_article_04.py --runs 3
#   --mock-tools (no API calls) | --max-queries N | --categories all
#   default categories: rag_calculation database_analysis code_execution

# Article 5: Multi-agent (sequential, critic, parallel, conflict)
uv run python benchmarks/run_article_05.py --runs 3
#   --tasks q001 q006 | --patterns sequential parallel | --max-refinements 2

# Article 6: LLM Ops (semantic cache + complexity router)
uv run python benchmarks/run_article_06.py --runs 3
uv run python benchmarks/run_article_06.py --chaos              # 10 prompts x 3 runs
uv run python benchmarks/run_article_06.py --chaos --quick      # 5-prompt smoke

# Article 7: Security (regex + optional Llama-Prompt-Guard-2)
uv run python benchmarks/run_article_07.py --runs 3
uv run python benchmarks/run_article_07.py --runs 3 --prompt-guard --per-run-pause-s 60
uv run python benchmarks/run_article_07.py --chaos --chaos-runs 3
#   --per-run-pause-s 60 lets Groq's free-tier rate-limit window reset
#   between runs for clean steady-state latency.
#   --no-llm runs the rails against a stub answerer (no Groq budget burned).

# Article 8: Scaling (K8s + Locust)
uv run python benchmarks/run_article_08.py --mode simulated     # legacy math model
uv run python benchmarks/run_article_08.py --mode measured \
    --csv-dir results/data/article_08_locust_<scenario>_<date>/

# Article 9: Deep learning (BGE fine-tune, torch.compile, INT8, JAX)
uv run python benchmarks/run_article_09.py
uv run python benchmarks/run_article_09.py --quick              # smaller eval set
uv run python benchmarks/run_article_09.py --force              # ignore caches

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
