# Article 1: State-Aware RAG Examples

Demonstrates baseline and advanced RAG implementations for Article 1, establishing performance benchmarks for comparison.

## Overview

This directory contains:
- **Naive RAG** (`demo_naive_rag.py`) - Baseline vector search implementation
- **Graph RAG** (`demo_graph_rag.py`) - Knowledge graph traversal with NetworkX
- **Benchmark reproduction** - Steps to regenerate Article 1 results

## Prerequisites

### 1. Install Dependencies

```bash
# From project root
uv sync --all-extras
```

### 2. Start Infrastructure

```bash
# Start all services (Chroma, Redis, Phoenix)
docker-compose -f infra/docker-compose.yml up -d

# Verify services running
docker-compose -f infra/docker-compose.yml ps

# Check Phoenix UI
open http://localhost:6006
```

### 3. Configure API Keys

```bash
# Copy environment template
cp .env.example .env.local

# Edit .env.local with your API keys
# At minimum, add GROQ_API_KEY for cheap cloud LLM
```

Required keys (at least one):
- `GROQ_API_KEY` - Recommended for development (~$0.05/1M tokens)
- `OPENAI_API_KEY` - Fallback for reliability
- `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, `DEEPSEEK_API_KEY` - Optional

### 4. Verify Dataset

```bash
# From project root
cd examples/article_01_state_aware_rag

# Check FastAPI documentation exists
python setup_demo_data.py
```

Expected output:
```
✓ Found 50 FastAPI documentation files
✓ Dataset ready for demos
```

## Quick Start

### Naive RAG Demo

```bash
# Basic query
python demo_naive_rag.py --query "What is FastAPI?"

# Adjust retrieval parameters
python demo_naive_rag.py --query "How do I use async in FastAPI?" --top-k 3

# Rebuild index (e.g., after updating documents)
python demo_naive_rag.py --query "..." --rebuild-index

# Use custom collection name
python demo_naive_rag.py --query "..." --collection my_experiments
```

**Expected output**:
```
================================================================================
Naive RAG Pipeline Demonstration
================================================================================

[1/5] Initializing observability...
      Phoenix URL: http://localhost:6006

[2/5] Initializing RAG pipeline...
      Collection: naive_rag_demo
      Chunk size: 500 tokens, 50-token overlap
      Top-K: 5

[3/5] Loading documents...
      Found 50 documents in datasets/tech_docs/fastapi

[4/5] Building index...
      Created 487 chunks
      Building embeddings (BGE-base-en-v1.5)...
      Index built successfully (12.3s)

[5/5] Running query...

================================================================================
Query: What is FastAPI?
================================================================================

Answer:
FastAPI is a modern, high-performance Python web framework for building APIs.
It uses Python type hints for automatic validation, serialization, and
documentation generation via OpenAPI and JSON Schema...

Retrieved Context (5 chunks):
  1. fastapi/01_fastapi_introduction.md (score: 0.847)
     "FastAPI is a modern, fast (high-performance), web framework for building
     APIs with Python 3.7+ based on standard Python type hints..."

  2. fastapi/02_path_parameters.md (score: 0.712)
     "FastAPI provides powerful path parameter handling with automatic
     validation..."
  ...

Phoenix Trace: http://localhost:6006/traces/abc123
================================================================================
```

### Graph RAG Demo

```bash
# Basic query with graph traversal
python demo_graph_rag.py --query "How are FastAPI and Pydantic related?"

# Multi-hop reasoning (deeper graph traversal)
python demo_graph_rag.py --query "What Java framework is similar to React hooks?" --max-hops 3

# Visualize knowledge graph
python demo_graph_rag.py --query "..." --visualize
# Saves graph.png in current directory

# Rebuild knowledge graph (e.g., after adding documents)
python demo_graph_rag.py --query "..." --rebuild-graph
```

**Expected output**:
```
================================================================================
Graph RAG Pipeline Demonstration (NetworkX)
================================================================================

[1/5] Initializing observability...

[2/5] Initializing Graph RAG pipeline...
      Max hops: 3

[3/5] Loading knowledge graph...
      Loading cached graph from .cache/graph_rag_cache.pkl
      Graph: 342 entities, 618 relationships

[4/5] Running query...
      Query: How are FastAPI and Pydantic related?
      Extracted entities: ["FastAPI", "Pydantic"]
      Graph traversal: 2 hops
      Found 12 relevant paths

[5/5] Generating answer...

================================================================================
Answer:
FastAPI is built on top of Pydantic for data validation. Pydantic models are
used to define request/response schemas, and FastAPI automatically validates
incoming data against these models...

Retrieved Context (graph paths):
  Path 1: FastAPI → uses → Pydantic → provides → Data Validation
  Path 2: FastAPI → depends_on → Pydantic Models → enables → Type Safety
  ...

Phoenix Trace: http://localhost:6006/traces/def456
================================================================================
```

## Benchmark Reproduction

Regenerate Article 1 benchmark results:

### Local Execution

```bash
# From project root
cd /path/to/repo

# Ensure services running
docker-compose -f infra/docker-compose.yml up -d

# Run benchmark (3 runs, 50 queries)
uv run python benchmarks/run_article_01.py

# Results saved to: results/data/article_01_benchmarks.json
```

### Google Colab Execution (Recommended)

Use Colab to avoid local rate limits:

```bash
# 1. Upload notebook to Colab
#    https://colab.research.google.com
#    File → Upload: notebooks/colab_benchmark_runner.ipynb

# 2. Set API keys in Colab Secrets (🔑 icon)
#    Add: GROQ_API_KEY

# 3. Run all cells (Runtime → Run all)
#    Wait 15-30 minutes, results auto-download

# 4. Merge results locally
uv run python scripts/merge_colab_results.py ~/Downloads/article_01_benchmarks.json
```

See `notebooks/COLAB_SETUP.md` for detailed instructions.

### Generate Visualizations

```bash
# Generate charts from benchmark results
uv run jupyter nbconvert --execute --to notebook --inplace notebooks/analysis_article_01.ipynb

# Charts saved to: results/charts/article_01/
# - 01_retrieval_quality.png
# - 02_latency_distribution.png
# - 03_accuracy_vs_cost.png
```

## What This Demonstrates

### Naive RAG Pipeline

**Core RAG pattern**: embed → store → retrieve → generate

**Implementation details**:
- **Document loading**: SimpleDirectoryReader for markdown files
- **Chunking**: SentenceSplitter (500 tokens, 50-token overlap)
- **Embeddings**: BGE-base-en-v1.5 via HuggingFace (local, Metal-accelerated on M4)
- **Vector DB**: Chroma (HTTP client to Docker container)
- **Retrieval**: Top-K semantic search (cosine similarity)
- **Generation**: Groq Llama-3-8B (cloud LLM, ~$0.05/1M tokens)
- **Observability**: Arize Phoenix traces

**Teaching note**: This baseline deliberately omits advanced techniques to establish a performance floor for comparison.

### Graph RAG Pipeline

**Pattern**: Entity extraction → Graph construction → Traversal → Generation

**Implementation details**:
- **Entity extraction**: LLM-based NER from documents
- **Relationship extraction**: LLM identifies connections between entities
- **Graph storage**: NetworkX (in-memory for development)
- **Graph traversal**: Multi-hop path finding (configurable depth)
- **Query processing**: Extract entities from query, find connecting paths
- **Caching**: Pickle serialization for fast reloads

**Teaching note**: Graph RAG excels at multi-hop reasoning but requires structured knowledge. Use for:
- Framework comparisons ("What Java framework is like React?")
- API dependency chains ("What endpoints use authentication?")
- Smaller, high-value document sets

Use Vector RAG for:
- Large-scale document retrieval
- Semantic similarity queries
- Fuzzy matching needs

## Limitations (Intentional)

These are **not bugs** - they're deliberate simplifications to establish a baseline:

### Naive RAG Limitations
- ❌ No query rewriting (HyDE)
- ❌ No query decomposition for multi-hop questions
- ❌ No hybrid search (dense-only, no BM25)
- ❌ No reranking of retrieved chunks
- ❌ Fixed chunking strategy (no semantic boundaries)
- ❌ No parent document retrieval

### Graph RAG Limitations
- ❌ In-memory graph (not persistent database)
- ❌ Simple entity extraction (no custom NER models)
- ❌ No hybrid vector + graph retrieval
- ❌ Manual entity disambiguation

**These limitations are addressed in Articles 2-3** with advanced techniques and empirical comparisons.

## Troubleshooting

### Docker Services Not Running

```
ERROR: chromadb.errors.ChromaError: Unable to connect to Chroma server
```

**Solution**:
```bash
# Start all services
docker-compose -f infra/docker-compose.yml up -d

# Check status
docker-compose -f infra/docker-compose.yml ps

# View logs if issues
docker-compose -f infra/docker-compose.yml logs chroma
```

### No LLM API Key

```
ERROR: All LLM providers failed. Configure at least one API key.
```

**Solution**:
```bash
# Add to .env.local (gitignored)
echo "GROQ_API_KEY=gsk_your_key_here" >> .env.local

# Verify
cat .env.local | grep GROQ_API_KEY
```

### Dataset Not Found

```
ERROR: Dataset directory not found: datasets/tech_docs/fastapi/
```

**Solution**:
```bash
# Generate FastAPI documentation
uv run python scripts/generate_tech_docs.py --framework fastapi

# Verify
ls datasets/tech_docs/fastapi/ | wc -l
# Should show 50 files
```

### Rate Limit Exceeded (429 Error)

```
ERROR: groq.RateLimitError: Rate limit exceeded
```

**Solutions**:

1. **Use Colab** (recommended - fresh IP):
   ```bash
   # See notebooks/COLAB_SETUP.md
   ```

2. **Add delays** between queries:
   ```python
   # Edit src/core/benchmarking.py
   import time
   time.sleep(2)  # Add in run_single_query()
   ```

3. **Reduce benchmark scope**:
   ```bash
   # Run fewer iterations
   uv run python benchmarks/run_article_01.py --runs 1
   ```

4. **Use different LLM provider**:
   ```bash
   # Add DeepSeek key (higher free tier)
   echo "DEEPSEEK_API_KEY=your_key" >> .env.local
   ```

### Phoenix Not Running

Phoenix is optional but recommended for observability.

**Symptom**: Demo works but no traces visible at http://localhost:6006

**Solution**:
```bash
# Phoenix should start automatically with docker-compose
docker-compose -f infra/docker-compose.yml up -d phoenix

# Verify
open http://localhost:6006
```

### Embeddings Slow (No GPU)

**Symptom**: Building index takes >5 minutes

**Explanation**: BGE-base-en-v1.5 runs on CPU without GPU acceleration.

**Solutions**:

1. **Use M-series Mac** - Metal acceleration (automatic)
2. **Use CUDA GPU** - Set `CUDA_VISIBLE_DEVICES=0`
3. **Use smaller model** - Edit `src/rag/naive_rag.py`:
   ```python
   model_name="sentence-transformers/all-MiniLM-L6-v2"  # Faster, lower quality
   ```

### Graph Visualization Missing

**Symptom**: `--visualize` flag doesn't create graph.png

**Solution**:
```bash
# Install graphviz system dependency
brew install graphviz  # macOS
sudo apt install graphviz  # Ubuntu

# Install Python package
uv add pygraphviz

# Or use matplotlib-only visualization (no external deps)
# Already implemented as fallback
```

### Out of Memory (Large Dataset)

**Symptom**: Process killed during indexing

**Solution**:
```bash
# Process documents in batches
# Edit demo script to use subset:
dataset_dir = project_root / "datasets" / "tech_docs" / "fastapi"
# Add limit in SimpleDirectoryReader
reader = SimpleDirectoryReader(dataset_dir, file_limit=10)
```

## Performance Expectations

Based on M4 Pro (16GB RAM) benchmarks:

| Operation | Time | Notes |
|-----------|------|-------|
| **Index build** (50 docs) | 10-15s | First run only, cached after |
| **Single query** | 1-2s | Retrieval + generation |
| **Benchmark** (50 queries, 3 runs) | 15-25 min | With rate limiting |
| **Graph build** (50 docs) | 30-45s | Entity extraction via LLM |

Cloud benchmarks (Colab T4 GPU):
- Index build: 5-8s (GPU acceleration)
- Benchmark: 12-18 min (better network)

## Next Steps

After running these demos:

1. **View Phoenix traces** to understand:
   - Retrieval latency breakdown
   - Embedding time vs LLM time
   - Token usage per query

2. **Compare techniques**:
   - Try same query on both Naive RAG and Graph RAG
   - Note when graph traversal helps (multi-hop) vs hurts (simple queries)

3. **Experiment with parameters**:
   - Vary `--top-k` (3, 5, 10)
   - Try different chunk sizes (edit `naive_rag.py`)
   - Adjust graph depth (`--max-hops`)

4. **Run benchmarks** to quantify:
   - Recall@K (retrieval quality)
   - MRR (ranking quality)
   - Latency (user experience)
   - Cost (token usage)

5. **Proceed to Article 2** for advanced retrieval:
   - Hybrid search (BM25 + dense)
   - Reranking (FlashRank, Cohere)
   - Metadata filtering

## Related Files

- `../../src/rag/naive_rag.py` - Naive RAG implementation
- `../../src/rag/graph_rag.py` - Graph RAG implementation
- `../../src/core/llm_client.py` - Unified LLM interface
- `../../src/core/benchmarking.py` - Benchmark harness
- `../../benchmarks/run_article_01.py` - Full benchmark script
- `../../notebooks/analysis_article_01.ipynb` - Visualization notebook
- `../../docs/specifications.md` - Technical specifications
- `../../docs/tasks.md` - Implementation roadmap

## Questions?

- See `CLAUDE.md` for project principles and guidelines
- Check `docs/specifications.md` for full technical details
- Review `notebooks/COLAB_SETUP.md` for remote execution
- Open GitHub issue for bugs or feature requests
