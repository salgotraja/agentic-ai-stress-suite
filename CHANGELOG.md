# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [1.0.0] - 2026-02-22

### Added

**Phase 1 - End-to-End Spike**
- `src/core/`: UnifiedLLMClient with Groq→DeepSeek→Claude→Gemini→OpenAI fallback,
  Pydantic BaseSettings config, `@traced_*` observability decorators, BenchmarkRunner
- `src/rag/naive_rag.py`: LlamaIndex + BGE-base-en-v1.5 + Chroma pipeline
- `src/agents/`: ReActAgent, PlanAndExecuteAgent, BaseTool contract, multi-agent spike
- `infra/docker-compose.yml`: Redis, Chroma, Phoenix, Neo4j (optional)
- 200 tech docs dataset (FastAPI, Pydantic, React, Spring)

**Phase 2 - RAG Depth (Articles 1–3)**
- `src/rag/advanced_rag.py`: HyDE + query decomposition; Recall@5 +9% over naive
- `src/rag/graph_rag.py`: NetworkX entity/relation graph, multi-hop traversal
- `src/rag/hybrid_search.py`: BM25+RRF + LlamaIndex/Haystack comparison;
  measured on a 30-query / 211-chunk technical-docs corpus, dense and hybrid
  tied at Recall@5 0.761 (BGE-base already covered the keyword/paraphrase
  split; BM25 added rank noise, dropping MRR 0.739 → 0.648). Adding
  FlashRank reranking recovered MRR (→ 0.769) but dropped Recall@5 to
  0.683. Hybrid+rerank is a recall/ranking trade-off on this corpus, not
  a pure win
- `src/rag/reranking.py`: FlashRank (local) + Cohere API reranker
- `src/rag/metadata_filter.py`: Pre/post-filtering with AND/OR/NOT logic
- `src/rag/chunking.py`: Semantic, fixed, and late chunking; PDF table extraction
- `src/rag/evaluation/`: RAGAS, DeepEval, LLM-as-Judge (r=0.83), A/B testing,
  drift detection (KS test + KL divergence)
- `datasets/golden_set/qa_pairs.json`: 50 hand-crafted Q&A pairs

**Phase 3 - Agent Breadth (Articles 4–5)**
- Tool suite: SearchTool (DuckDuckGo), DatabaseLookupTool (SQLite), CodeExecutionTool
  (AST sandbox), MCPFileReadTool, MCPAPICallTool
- `src/agents/single_agent.py`: 3-retry error recovery, `execute_tools_parallel()`
  with ThreadPoolExecutor for I/O-bound tools and ProcessPoolExecutor for
  CPU-bound tools (per-tool timeout preserves graceful degradation;
  parallel-vs-sequential delta not isolated in this run). Article 4
  benchmark: ReAct 94.1% / P&E 100% success on 17-query deterministic slice
- `src/agents/multi_agent.py`: 4 measured orchestration patterns on LangGraph -
  sequential (3047±558 ms / $0.000147), critic refinement loop
  (4280±1029 ms / $0.000253; loop fires ~56% of trials), parallel fan-out
  concat (849±74 ms / $0.000111), conflict resolution (voting + supervisor
  variants measured; round-robin implemented but not measured)
- `src/agents/state_persistence.py`: InMemory, SQLite, Redis backends
- CrewAI and AutoGen comparison implementations

**Phase 4 - Production Readiness (Articles 6–8)**
- `src/ops/caching.py`: L1 exact (MD5/Redis, 24h TTL) + L2 semantic (cosine>0.95);
  on a 100-query technical-docs workload, tiered cache cut a Groq-8B baseline
  $0.001272 → $0.000769 (39.6% cost reduction, 40% hit rate); complexity
  routing alone cut a GPT-4o-for-everything baseline $0.193474 → $0.002277
  (98.8% cost reduction) because 97% of queries in this benchmark were
  simple enough for Groq-8B
- `src/ops/routing.py`: LiteLLM fallback chain, complexity router, cost forecasting
  (linear regression, 95% CI)
- `src/core/cost_logger.py`: YAML pricing, budget alerts at 80%/100%
- `src/ops/security.py`: GuardrailsManager (regex + Llama-Guard), SpacyPIIScanner,
  RawChunkDetector, sanitize_output, AuditLogger (SHA-256 + SQLite WAL);
  104-prompt red-team, 0% false positives, p99=0.009ms
- `src/ops/deployment/k8s/`: 6 YAML manifests; in-cluster API + Redis +
  Chroma, fixed-replica scenarios (HPA disabled by design - single-node
  Docker Desktop K8s leaves no scheduling headroom)
- Locust load test on Docker Desktop single-node K8s: r=2 sustains 3.64 rps,
  r=5 sustains 3.93 rps (replica gain 1.078×, host CPU saturation cliff at
  85.4%)
- Chroma → Qdrant migration script (idempotent, batched, count-verified)

**Phase 5 - Deep Learning (Article 9)**
- BGE-base-en-v1.5 fine-tuning with MultipleNegativesRankingLoss;
  Recall@5: 0.729 → 0.622 (-11%, objective-mismatch finding documented
  in `results/data/article_09_benchmarks.json` - training used
  query→answer-summary pairs but inference matches query→doc-chunk)
- PyTorch optimisations: torch.compile on MPS (0.92×, no win on Apple Silicon),
  INT8 dynamic quantisation (4× smaller: 437.9MB → 109.5MB, but ~2.08× slower
  on M4: 23.49ms → 48.95ms per embedding - QNNPACK's optimized shapes appear
  x86-leaning; size win real, latency win is x86-only),
  torch.profiler Chrome trace
- Custom cross-encoder reranker (cross-encoder/ms-marco-MiniLM-L-6-v2 base):
  NDCG@5 0.7606 (FlashRank) → 0.874 (+15%), latency 340.75ms → 120.73ms
  (2.82× faster) on 39-query technical-docs set; attention hooks for [CLS]
  attention visualization
- JAX DPR-like retriever with jax.vmap/jit; JAX vs PyTorch benchmark
- `src/agents/tools/custom_embedding_rag.py`: DIP plug-in, mock mode for CI

**Phase 6 - Finalization**
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
