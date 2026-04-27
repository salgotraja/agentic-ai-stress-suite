# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [1.0.0] - 2026-02-22

### Added

**Phase 1 — End-to-End Spike**
- `src/core/`: UnifiedLLMClient with Groq→DeepSeek→Claude→Gemini→OpenAI fallback,
  Pydantic BaseSettings config, `@traced_*` observability decorators, BenchmarkRunner
- `src/rag/naive_rag.py`: LlamaIndex + BGE-base-en-v1.5 + Chroma pipeline
- `src/agents/`: ReActAgent, PlanAndExecuteAgent, BaseTool contract, multi-agent spike
- `infra/docker-compose.yml`: Redis, Chroma, Phoenix, Neo4j (optional)
- 200 tech docs dataset (FastAPI, Pydantic, React, Spring)

**Phase 2 — RAG Depth (Articles 1–3)**
- `src/rag/advanced_rag.py`: HyDE + query decomposition; Recall@5 +9% over naive
- `src/rag/graph_rag.py`: NetworkX entity/relation graph, multi-hop traversal
- `src/rag/hybrid_search.py`: BM25+RRF + LlamaIndex/Haystack comparison;
  hybrid alone +8% Recall@5 (0.723 → 0.781); full pipeline (hybrid +
  FlashRank + metadata pre-filter + late chunking) +19% Recall@5
  (0.723 → 0.862)
- `src/rag/reranking.py`: FlashRank (local) + Cohere API reranker
- `src/rag/metadata_filter.py`: Pre/post-filtering with AND/OR/NOT logic
- `src/rag/chunking.py`: Semantic, fixed, and late chunking; PDF table extraction
- `src/rag/evaluation/`: RAGAS, DeepEval, LLM-as-Judge (r=0.83), A/B testing,
  drift detection (KS test + KL divergence)
- `datasets/golden_set/qa_pairs.json`: 50 hand-crafted Q&A pairs

**Phase 3 — Agent Breadth (Articles 4–5)**
- Tool suite: SearchTool (DuckDuckGo), DatabaseLookupTool (SQLite), CodeExecutionTool
  (AST sandbox), MCPFileReadTool, MCPAPICallTool
- `src/agents/single_agent.py`: 3-retry error recovery, `execute_tools_parallel()`
  with ThreadPoolExecutor/ProcessPoolExecutor (2.62× speedup)
- `src/agents/multi_agent.py`: 9 orchestration patterns including critic feedback
  loop (4.2/5 quality vs 3.6/5 sequential), parallel fan-out (2.7×), conflict
  resolution (voting/supervisor/round-robin)
- `src/agents/state_persistence.py`: InMemory, SQLite, Redis backends
- CrewAI and AutoGen comparison implementations

**Phase 4 — Production Readiness (Articles 6–8)**
- `src/ops/caching.py`: L1 exact (MD5/Redis, 24h TTL) + L2 semantic (cosine>0.95);
  semantic cache alone: 39% hit rate, $0.375 → $0.229 (39% cost reduction)
  on a 100-query workload; complexity routing alone: $0.375 → $0.003
  (99.2% cost reduction) because 97% of queries route to Groq-8B
- `src/ops/routing.py`: LiteLLM fallback chain, complexity router, cost forecasting
  (linear regression, 95% CI)
- `src/core/cost_logger.py`: YAML pricing, budget alerts at 80%/100%
- `src/ops/security.py`: GuardrailsManager (regex + Llama-Guard), SpacyPIIScanner,
  RawChunkDetector, sanitize_output, AuditLogger (SHA-256 + SQLite WAL);
  104-prompt red-team, 0% false positives, p99=0.009ms
- `src/ops/deployment/k8s/`: 6 YAML manifests; HPA 2–8 replicas at 70% CPU
- Locust load test: 74 rps peak, p95=372ms at 50 users
- Chroma → Qdrant migration script (idempotent, batched, count-verified)

**Phase 5 — Deep Learning (Article 9)**
- BGE-base-en-v1.5 fine-tuning with MultipleNegativesRankingLoss;
  Recall@5: 0.729 → 0.622 (-11%, objective-mismatch finding documented
  in `results/data/article_09_benchmarks.json` — training used
  query→answer-summary pairs but inference matches query→doc-chunk)
- PyTorch optimisations: torch.compile on MPS (0.99×, no win on Apple Silicon),
  INT8 dynamic quantisation (4× smaller, but ~1.8× slower on M4 — QNNPACK lacks
  ARM SIMD acceleration; size win real, latency win is x86-only),
  torch.profiler Chrome trace
- Custom cross-encoder reranker (cross-encoder/ms-marco-MiniLM-L-6-v2 base):
  NDCG@5 0.761 (FlashRank) → 0.874 (+15%), latency 339ms → 112ms (3× faster)
  on 39-query technical-docs set; attention hooks for [CLS] interpretability
- JAX DPR-like retriever with jax.vmap/jit; JAX vs PyTorch benchmark
- Custom cross-encoder with attention hooks (interpretability)
- `src/agents/tools/custom_embedding_rag.py`: DIP plug-in, mock mode for CI

**Phase 6 — Finalization**
- GitHub Actions: CI (lint/typecheck/unit/smoke), nightly, release workflows
- Blog posts: 8 articles in `docs/blog/` (Article 9 deep-learning writeup
  pending; code, benchmarks, and notebook shipped)
- CONTRIBUTING.md, CHANGELOG.md
- `scripts/generate_all_charts.sh`, `results/reports/v1.0_summary.md`
- Git tag v1.0.0

### Technical Notes

- Total production code: ~25,000 lines across 60+ source files
- Test coverage: 28+ unit test files, 20+ integration test files
- Total LLM cost across all 9 articles: <$12 (Groq for development)
- All benchmarks reproducible via mock mode in CI

[1.0.0]: https://github.com/salgotraja/agentic-ai-stress-suite/releases/tag/v1.0.0
