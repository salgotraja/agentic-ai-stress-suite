# Article 1: State-Aware RAG - Naive RAG Demonstration

This directory contains demonstration scripts for the Naive RAG Pipeline, the baseline implementation for Article 1.

## Prerequisites

1. **Chroma server running**:
   ```bash
   docker run -d -p 8000:8000 chromadb/chroma
   ```

2. **Phoenix server running** (optional, for tracing):
   ```bash
   python scripts/start_phoenix.py &
   ```

3. **LLM API key configured** (at least one):
   - Groq: `GROQ_API_KEY` in `.env.local`
   - Or any other supported provider (DeepSeek, Claude, Gemini, OpenAI)

## Quick Start

1. **Verify dataset**:
   ```bash
   python setup_demo_data.py
   ```

2. **Run a query**:
   ```bash
   python demo_naive_rag.py --query "What is FastAPI?"
   ```

3. **View traces** (if Phoenix running):
   Open http://localhost:6006

## Usage Examples

### Basic query
```bash
python demo_naive_rag.py --query "How do I use async in FastAPI?"
```

### Adjust number of retrieved chunks
```bash
python demo_naive_rag.py --query "What are FastAPI dependencies?" --top-k 3
```

### Rebuild index
```bash
python demo_naive_rag.py --query "..." --rebuild-index
```

### Use custom collection name
```bash
python demo_naive_rag.py --query "..." --collection my_custom_collection
```

## Expected Output

The demo script will:
1. Initialize Phoenix tracing
2. Initialize the RAG pipeline
3. Load documents (or use existing index)
4. Build vector index (first run only)
5. Run your query
6. Display:
   - Generated answer
   - Retrieved context chunks with relevance scores
   - Link to Phoenix trace

## What This Demonstrates

This baseline implementation shows:
- Document loading from markdown files
- Chunking with SentenceSplitter (500 tokens, 50 overlap)
- Embedding with BGE-base-en-v1.5 (local, Metal-accelerated)
- Vector storage in Chroma
- Top-K semantic retrieval
- Response generation with Groq Llama-3-8B (cloud, cheap)
- Full observability via Phoenix traces

## Limitations (Addressed in Advanced RAG)

- No query rewriting (HyDE)
- No query decomposition for multi-hop questions
- No hybrid search (dense-only, no BM25)
- No reranking of retrieved chunks
- Fixed chunking strategy (no semantic boundaries)

These limitations are intentional to establish a baseline for comparison.

## Troubleshooting

### Chroma connection error
```
ERROR: chromadb.errors.ChromaError: Unable to connect to Chroma server
```
**Solution**: Start Chroma server:
```bash
docker run -d -p 8000:8000 chromadb/chroma
```

### No LLM API key
```
ERROR: All LLM providers failed. Configure at least one API key.
```
**Solution**: Add API key to `.env.local`:
```bash
echo "GROQ_API_KEY=your_key_here" >> .env.local
```

### Dataset not found
```
ERROR: Dataset directory not found: datasets/tech_docs/fastapi/
```
**Solution**: Ensure FastAPI docs are in `datasets/tech_docs/fastapi/`

### Phoenix not running
The demo works without Phoenix, but traces won't be captured.
Start Phoenix for observability:
```bash
python scripts/start_phoenix.py &
```

## Next Steps

After running this baseline:
1. View trace in Phoenix to understand latency breakdown
2. Note the relevance scores of retrieved chunks
3. Try different queries to see when naive RAG fails
4. Proceed to advanced RAG techniques (Article 1 continued)
