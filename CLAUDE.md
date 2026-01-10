# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is the **Agentic AI Stress Test Suite**, a production-grade proof-of-concept demonstrating empirical trade-offs in RAG-to-agent workflows. The project targets senior engineers transitioning to applied AI and will produce 8-9 blog articles with reproducible benchmarks.

**Current Status**: Planning phase complete, implementation not yet started (Phase 1 pending)

**Key Documents**:
- `docs/specifications.md` - Complete technical specifications
- `docs/requirements.md` - Functional (FR) and non-functional (NFR) requirements
- `docs/tasks.md` - 190 trackable tasks across 6 implementation phases
- `docs/discussions.md` - Project rationale and goals

## Core Principles

**CRITICAL - Read Before Every Task**:

1. **Do what has been asked; nothing more, nothing less**
2. **Keep it simple** - prefer simple solutions over complex ones
3. **Minimal changes only** - don't over-engineer or add unnecessary complexity
4. **Ask before major changes** - confirm scope and approach for significant modifications
5. **Everything is 'in development'** until explicitly marked production-ready
6. **No emojis** in logs, code, comments, or documentation
7. **Type hints required** for all parameters and return types
8. **Meaningful names** for variables and functions
9. **No magic numbers or strings** - use named constants
10. **Consistent naming conventions** - follow PEP 8 and project patterns
11. **Minimal comments** - code should be self-documenting; add comments only when necessary for teaching or complex logic

### Investigation Before Answering

**ALWAYS read relevant files before proposing solutions**:
- Never speculate about code you have not opened
- If user references a specific file, you MUST read it before answering
- Be rigorous and persistent in searching code for key facts
- Thoroughly review style, conventions, and abstractions before implementing
- Give grounded, hallucination-free answers based on actual code inspection

### Implementation Philosophy

**Avoid Over-Engineering**:
- Only make changes that are directly requested or clearly necessary
- A bug fix doesn't need surrounding code cleaned up
- A simple feature doesn't need extra configurability
- Don't add error handling for scenarios that can't happen
- Trust internal code and framework guarantees
- Only validate at system boundaries (user input, external APIs)
- Don't create helpers/utilities for one-time operations
- Don't design for hypothetical future requirements
- Reuse existing abstractions; follow DRY principle
- The right complexity = minimum needed for current task

**Clean Up After Yourself**:
- Remove any temporary files, scripts, or helpers created during iteration
- Execute operations sequentially with brief pauses for stability

### Parallel Tool Usage

When calling multiple tools:
- **Use parallel calls** for independent operations (e.g., reading 3 unrelated files)
- **Use sequential calls** when operations have dependencies
- **Never use placeholders** or guess missing parameters
- Maximize parallelism for speed and efficiency

## Pre-Submission Checklist

Before submitting any solution, ensure:

1. **Code Quality Pass**: All automated hooks must pass
2. **Strict Tool Checks**:
   - `mypy` - ZERO type errors
   - `ruff check` - ZERO linting errors
   - `ruff format` or `black` - Code properly formatted
3. **Green Tests**: All unit and integration tests must pass
4. **Minimalism**:
   - No code emojis
   - Minimalistic logging
   - Least documentation necessary
5. **No Clutter**: Update existing documents only; do not create new ones unless absolutely necessary

**Verification Commands**:
```bash
# Run all quality checks
mypy src/
ruff check src/ tests/
ruff format src/ tests/  # or: black src/ tests/
pytest tests/ -v
```

## Architecture Philosophy

### Core Principles
1. **Teaching-First Code**: All production code must include teaching comments explaining WHY, not WHAT
2. **Empirical Over Hype**: Measure everything, prove claims with benchmarks
3. **Hybrid Infrastructure**: Local embeddings (text-embeddings-inference with BGE-base-en-v1.5, Metal-accelerated on M4) and cloud LLMs (Groq, DeepSeek, Claude, Gemini, OpenAI) with cost-optimized fallback chains
4. **Framework Diversity**: Use multiple frameworks (LlamaIndex, Haystack, LangChain, LangGraph) to demonstrate trade-offs
5. **Pluggable Design**: All backends (state, cache, vector DB, LLM) must be swappable via interfaces

### Repository Structure (Planned)

```
src/
├── core/          # Shared utilities - IMPLEMENT FIRST
│   ├── config.py          # Hierarchical config (.env < env vars < CLI)
│   ├── llm_client.py      # Unified LLM wrapper (Groq, DeepSeek, Claude, Gemini, OpenAI)
│   ├── observability.py   # Tracing decorators (@traced_retrieval, etc.)
│   ├── benchmarking.py    # Consistent test harness
│   ├── cost_logger.py     # Token/cost tracking
│   └── plotting.py        # Matplotlib/Plotly helpers
├── rag/           # RAG implementations (Articles 1-3)
├── agents/        # Agent systems (Articles 4-5)
└── ops/           # Production concerns (Articles 6-8)

examples/article_N/  # Each article has runnable demos
datasets/            # Tech docs corpus + synthetic queries
tests/               # unit/, integration/, benchmarks/
results/             # charts/, data/, reports/
```

## Development Workflow

### Phase-Based Implementation

**DO NOT skip phases.** Each phase builds on the previous:

1. **Phase 1 (Weeks 1-2)**: End-to-End Spike
   - Prove RAG → Agent → Multi-agent integration
   - Implement core infrastructure (`src/core/`)
   - Set up Docker Compose dev stack

2. **Phase 2 (Weeks 3-5)**: RAG Depth (Articles 1-3)
   - Advanced RAG techniques (HyDE, query decomp, graph RAG)
   - Evaluation framework (RAGAS, DeepEval)

3. **Phase 3 (Weeks 6-8)**: Agent Breadth (Articles 4-5)
   - Single-agent (ReAct, Plan-and-Execute)
   - Multi-agent orchestration (LangGraph primary)

4. **Phase 4 (Weeks 9-10)**: Production Readiness (Articles 6-8)
   - Caching, routing, security, K8s deployment

5. **Phase 5 (Weeks 11-12)**: Deep Learning (Article 9)
   - Custom embeddings, PyTorch/JAX optimizations

6. **Phase 6 (Week 13)**: Finalization
   - CI/CD, documentation, v1.0 release

**Track progress** by checking off tasks in `docs/tasks.md` (`- [ ]` → `- [x]`)

### Dependency Management

**Use `uv` (preferred) or `poetry`**

```bash
# Setup with uv
uv init
uv add <package>
uv sync

# Setup with poetry (fallback)
poetry init
poetry add <package>
poetry install
```

**Key Dependencies** (from specifications):
- Python 3.11+
- LLM Frameworks: LlamaIndex 0.10.x, LangChain 0.1.x, Haystack 2.x, LangGraph 0.1.x
- Embeddings: text-embeddings-inference (local, BGE-base-en-v1.5 model, Metal-accelerated on M4)
- LLMs: Groq (dev, cheap), DeepSeek, Claude, Gemini, OpenAI (final fallback for reliability)
- Vector DBs: Chroma (dev) → Qdrant cloud (Article 2+) or Weaviate (Article 8 alternative)
- Cache/State: Redis (from Phase 1), SQLite (local persistence option)
- Graph: NetworkX (primary), Neo4j (optional, Docker Compose architecture demo)
- Database: Postgres (optional, future requirement for complex agent state/structured data)
- Observability: Arize Phoenix (local), LangFuse (production, Article 6+)
- DL: PyTorch 2.2+, JAX 0.4+ (Article 9 only)

## Critical Implementation Patterns

### 1. LLM Client (src/core/llm_client.py)

**Must implement**:
- Unified interface for Groq, DeepSeek, Claude, Gemini, OpenAI
- Graceful degradation: `Groq-8b → Groq-32b → Groq-70b → DeepSeek → Claude → Gemini → OpenAI (GPT-4)` fallback chain
- Exponential backoff: 3 retries at 1s, 2s, 4s intervals
- Token counting and cost calculation per request
- Timeout handling (30s default)
- Support for text-embeddings-inference (local, BGE-base-en-v1.5)

**Teaching comment required**:
```python
# Cloud-first LLM strategy (hardware constraints on M4):
# Local: text-embeddings-inference (BGE-base-en-v1.5, Metal-accelerated)
# Cloud LLMs: Groq → DeepSeek → Claude → Gemini → OpenAI (final fallback)
#
# Groq fallback chain by model size:
# - Llama-3-8B: Development iteration ($0.05/1M tokens, fast)
# - Llama-3-32B: Medium complexity queries
# - Llama-3-70B: High complexity tasks
# Then escalate: DeepSeek → Claude → Gemini → OpenAI (GPT-4) for max reliability
#
# Why not Ollama locally:
# - M4 memory constraints for running 7B+ models locally
# - Groq offers better cost/performance ratio for development
# - text-embeddings-inference handles embeddings locally (free, Metal-accelerated)
#
# Embedding model choice:
# - BGE-base-en-v1.5: Better performance than all-MiniLM-L6-v2
# - MTEB benchmark: BGE scores ~63 vs all-MiniLM ~56
# - Same memory footprint, better semantic understanding
```

### 2. Tracing Decorators (src/core/observability.py)

```python
@traced_retrieval  # For vector search operations
@traced_generation # For LLM calls
@traced_tool_call  # For agent tool execution
```

Must auto-capture: latency, token counts, inputs, outputs, errors, correlation IDs

### 3. Agent Tools (src/agents/tools/base.py)

**All tools must extend `BaseTool` with**:
```python
def execute(input: str) -> str:      # Real implementation
def mock_execute(input: str) -> str: # For testing
def describe() -> str:               # Tool description
```

**Why**: Enables dependency injection for testing (swap real ↔ mock)

### 4. State Persistence (src/agents/state_persistence.py)

**Pluggable backends via `StateBackend` interface**:
- `InMemoryBackend` (Phase 1, dev/testing)
- `SQLiteBackend` (Phase 1, local persistence option)
- `RedisBackend` (Phase 1 onwards, primary for cache and distributed state)

### 5. Benchmarking (src/core/benchmarking.py)

**Every technique must**:
- Run 3 times, report mean ± std dev
- Output JSON to `results/data/article_N_benchmarks.json`
- Generate charts via Jupyter notebook in `notebooks/analysis_article_N.ipynb`
- Export charts as PNG to `results/charts/article_N/`

## Testing Strategy

### Unit Tests
- Mock all LLM calls with predefined responses
- Use pytest with coverage
- Fast: <1s per test
- Location: `tests/unit/`

### Integration Tests
- Use VCR/vcrpy for cassette-based LLM replay
- Record real interactions once, replay in CI
- Slower: 10-30s per test
- Location: `tests/integration/`

### Benchmarks
- Not traditional tests (no assertions)
- Validation of metrics, performance regression detection
- Location: `tests/benchmarks/`

**Run tests**:
```bash
# Unit tests
pytest tests/unit/ -v

# Integration tests
pytest tests/integration/ -v

# Specific test
pytest tests/unit/core/test_config.py::test_hierarchical_loading -v

# With coverage
pytest tests/unit/ --cov=src/ --cov-report=term-missing
```

## Teaching Comments Requirements

**Every non-trivial implementation must include teaching comments**:

✅ **Good example**:
```python
# HyDE: Helps when query-document vocabulary mismatch is high
# Example: "How do I make Spring async?" vs doc text "Asynchronous processing"
# Generates hypothetical answer, embeds that (semantically closer to docs)
# Trade-off: Extra LLM call adds 200-500ms latency + cost
```

❌ **Bad example**:
```python
# Call reranker on results
```

**Focus on**:
- WHY this approach was chosen
- When it helps vs hurts
- Trade-offs (cost, latency, accuracy)
- Alternative approaches considered

## Docker & Deployment

### Local Development Stack

```bash
# Start all services
docker-compose up -d

# Services:
#   - text-embeddings-inference (BGE-base-en-v1.5, Metal-accelerated)
#   - redis (cache/state, from Phase 1)
#   - chroma (vector DB, local dev)
#   - phoenix (observability)
#   - postgres (optional, future requirement for complex agent state)
# Neo4j: Optional, documented separately for graph RAG architecture demo
docker-compose ps

# Shutdown
docker-compose down
```

### Kubernetes (Phase 4, Article 8)

**Production-lite manifests** in `src/ops/deployment/k8s/`:
- Deployment (2-3 replicas, HPA at 70% CPU)
- Service, Ingress (NGINX), ConfigMap, Secrets
- NOT included: Full monitoring (Prometheus/Grafana), service mesh

## Cost Management

**Budget**: $50-100 per article for cloud LLM benchmarks

**Strategy**:
- **Development**: Use Groq (cloud, cheap ~$0.05/1M tokens) for iteration
- **Embeddings**: Use text-embeddings-inference (local, free, Metal-accelerated)
- **Quality benchmarks**: Use Claude, Gemini for high-quality comparisons
- **Fallback**: OpenAI (GPT-4) as final fallback for maximum reliability
- **Caching**: Implement semantic cache in Article 6 to reduce costs >40%
- **Routing**: LiteLLM router with cost-optimized fallback chain:
  - Groq-8b → Groq-32b → Groq-70b → DeepSeek → Claude → Gemini → OpenAI

## Article-Specific Guidance

### Article 1: State-Aware RAG
- Frameworks: LlamaIndex (primary), Haystack (comparison)
- Techniques: HyDE, query decomposition, graph RAG (NetworkX)
- Dataset: 50-100 pages from Spring, React, FastAPI, Pydantic docs

### Article 2: Advanced Retrieval
- Hybrid search: BM25 + dense (Reciprocal Rank Fusion)
- Reranking: FlashRank (primary), Cohere API (comparison)
- Metadata filtering: pre-filter vs post-filter strategies

### Article 3: Evaluation
- RAGAS + DeepEval metrics
- Golden set: 20-50 hand-crafted Q&A pairs
- LLM-as-judge: GPT-4 for scaled evaluation (100+ queries)
- Drift detection: KS test on embedding distributions

### Article 4: Single-Agent
- LangGraph for ReAct and Plan-and-Execute
- Tools: Search (DuckDuckGo), Calculator, DB lookup, Code exec, RAG, MCP
- Error recovery: 3 retries, fallback chain, partial results

### Article 5: Multi-Agent
- LangGraph (primary deep dive)
- CrewAI + AutoGen (surface comparison)
- Patterns: Sequential pipeline, parallel fan-out, conflict resolution

### Article 6: LLM Ops
- Tiered caching: L1 exact → L2 semantic (cosine > 0.95) → L3 miss
- LiteLLM routing with fallback
- Cost forecasting: Linear regression from 7-day patterns
- Observability migration: Phoenix → LangFuse

### Article 7: Security
- NVIDIA NeMo Guardrails + Llama-Guard
- Red-team: 100+ prompts (L1 naive, L2 moderate, L3 advanced)
- PII detection: Regex + spaCy NER
- Target: Block >90% of L2+ attacks

### Article 8: Scaling
- Parallel tool execution (ThreadPoolExecutor for I/O, ProcessPoolExecutor for CPU)
- Vector DB migration: Chroma → Weaviate/Qdrant
- K8s with Locust load testing
- Target: 100 req/sec with p95 < 500ms

### Article 9: Deep Learning
- Fine-tune BGE-base-en-v1.5 on tech docs (1000-2000 pairs, further improve from base model)
- PyTorch: torch.compile(), quantization, profiling
- JAX: DPR-like retriever with jax.vmap, jax.jit
- Profile on CPU + GPU, provide both results

## Common Pitfalls to Avoid

1. **Don't implement without reading specs**: Always check `docs/specifications.md` and `docs/requirements.md` first
2. **Don't skip teaching comments**: Production code without teaching = failure of core philosophy
3. **Don't cherry-pick phases**: Phase N depends on Phase N-1 infrastructure
4. **Use Groq for dev iteration (cheap)**: Groq for development, Claude/Gemini for quality benchmarks
5. **Don't mock in benchmarks**: Benchmarks must use real LLMs (with VCR replay in CI)
6. **Don't skip verification steps**: Each task in `docs/tasks.md` has verification commands - run them
7. **Don't create toy examples**: Code must be production-applicable, not tutorials

## When Starting Work

1. **Check current phase**: Look at progress in `docs/tasks.md`
2. **Read requirements**: Find relevant FR/NFR in `docs/requirements.md`
3. **Understand architecture**: Review `docs/specifications.md` for the module you're implementing
4. **Implement with teaching**: Write production code + teaching comments
5. **Verify**: Run verification commands from task description
6. **Update progress**: Check off task in `docs/tasks.md` (`- [ ]` → `- [x]`)

## Success Criteria

**Minimum Viable Product** (Phase 1 complete):
- Articles 1-3 RAG implementations working
- Core infrastructure functional
- Docker Compose stack operational

**Full Success** (All phases):
- All 9 articles with working code + benchmarks
- CI/CD pipeline (linting, tests, smoke benchmarks)
- Results directory with all charts and data
- 50+ GitHub stars within 3 months of v1.0

## Quick Reference

**Start development**:
```bash
# Phase 1, Task 1.1: Project Setup
uv init
# Follow tasks in docs/tasks.md sequentially
```

**Run examples** (once implemented):
```bash
cd examples/article_01_state_aware_rag/
python demo.py --query "What is FastAPI?"
```

**Run benchmarks**:
```bash
python benchmarks/run_article_01.py --dataset datasets/synthetic_queries/article_01.json
```

**Generate charts**:
```bash
jupyter nbconvert --execute notebooks/analysis_article_01.ipynb
```

**Full stack**:
```bash
docker-compose up -d
# Open Phoenix: http://localhost:6006
# Open Neo4j: http://localhost:7474
```

## Documentation Hierarchy

1. **CLAUDE.md** (this file) - Quick orientation for Claude Code
2. **docs/specifications.md** - Complete technical specifications (150+ pages)
3. **docs/requirements.md** - FR/NFR with traceability
4. **docs/tasks.md** - 190 trackable implementation tasks
5. **docs/discussions.md** - Project rationale and goals
6. **examples/article_N/README.md** - Article-specific instructions (once implemented)

## Claude Code Specific Guidelines

### Default LLM Selection

When an LLM is needed for implementation (e.g., in `src/core/llm_client.py` or agent tools), **default to Claude Sonnet 4.5** unless user requests otherwise.

**Model string**: `claude-sonnet-4-5-20250929`

### Frontend Aesthetics (For Visualization/Dashboard Work)

While this is primarily a backend/AI project, when creating visualizations, dashboards, or Jupyter notebooks:

**Avoid "AI Slop" Aesthetic**:
- No generic fonts (Inter, Roboto, Arial)
- No clichéd color schemes (purple gradients on white)
- No cookie-cutter design patterns

**Instead**:
- **Typography**: Choose distinctive fonts for charts and dashboards
- **Color & Theme**: Use CSS variables, commit to cohesive aesthetic (draw from IDE themes)
- **Motion**: CSS animations for Jupyter output, staggered reveals for impact
- **Backgrounds**: Layer CSS gradients, geometric patterns for depth

**For this project specifically**:
- Matplotlib/Seaborn charts should use distinctive color schemes
- Jupyter notebooks should have custom CSS for professional presentation
- Dashboard visualizations (if created) should reflect technical/engineering aesthetic
- Avoid default matplotlib colors; use curated palettes

### General-Purpose Solutions

Write high-quality, general-purpose solutions:
- **No helper scripts or workarounds** - use standard tools
- **Solve generally, not for specific test cases** - no hard-coded values
- **Implement correct algorithms** - tests verify correctness, don't define solution
- **Robust and maintainable** - follow best practices and design principles

If a task is unreasonable or tests are incorrect, inform the user rather than working around issues.

---

## Final Reminders

**Before Every Implementation**:
1. Read the Pre-Submission Checklist
2. Review Core Principles
3. Check relevant files in docs/
4. Verify you're in the correct phase
5. Run verification commands

**Remember**: This project is about teaching senior engineers through empirical evidence and production-quality code. Every line of code is an opportunity to educate. Make it count.
