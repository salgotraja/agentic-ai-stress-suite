# Running Benchmarks on Google Colab

This guide explains how to run benchmarks on Google Colab to avoid local rate limits.

## Why Use Colab?

- **Fresh API quota**: Different IP address from your local machine
- **Free resources**: T4 GPU, 12GB RAM
- **No Docker needed**: Uses embedded Chroma
- **Long runtimes**: Can run for hours without interrupting local work
- **Easy sharing**: Share notebooks with collaborators

## Quick Start

### 1. Upload to Colab

**Option A: Direct Upload**
1. Go to [Google Colab](https://colab.research.google.com)
2. File → Upload notebook
3. Select `notebooks/colab_benchmark_runner.ipynb`

**Option B: From GitHub**
1. Push the notebook to your GitHub repo
2. Go to Colab
3. File → Open notebook → GitHub tab
4. Enter your repo URL

### 2. Configure API Keys

**IMPORTANT**: Never hardcode API keys in the notebook!

1. Click the 🔑 (key) icon in the left sidebar
2. Add secrets:
   - **Required**: `GROQ_API_KEY` - Your Groq API key
   - **Optional**: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, etc. (for fallback)

3. Toggle "Notebook access" ON for each secret

### 3. Run the Benchmark

1. **Runtime → Run all** (or Ctrl+F9)
2. Wait 15-30 minutes (depending on query count and rate limits)
3. Monitor progress in cell outputs

### 4. Download Results

The notebook will automatically trigger a download of:
- `article_01_results.zip` - Contains benchmark JSON

Extract and copy to your local repo:
```bash
# On your local machine
unzip article_01_results.zip
cp article_01_benchmarks.json /path/to/repo/results/data/
```

### 5. Generate Visualizations Locally

```bash
cd /path/to/repo
uv run jupyter nbconvert --execute --to notebook --inplace notebooks/analysis_article_01.ipynb
```

## Handling Rate Limits

If you hit rate limits even on Colab:

### Reduce Benchmark Scope
```python
# In cell "Run Benchmark", change:
NUM_RUNS = 1  # Instead of 3
```

### Add Delays Between Queries
Modify `src/core/benchmarking.py` locally, then push to GitHub:

```python
# In BenchmarkRunner.run_single_query()
import time
time.sleep(2)  # Add 2-second delay between queries
```

### Use Multiple Colab Accounts
- Run different articles on different Google accounts
- Combine results later

## Tips & Tricks

### 1. Use GPU Runtime (Optional)
- Runtime → Change runtime type → GPU (T4)
- Speeds up embedding generation slightly
- Not critical for this project (embeddings are small)

### 2. Mount Google Drive (Optional)
Uncomment the Drive mount cell to:
- Auto-save results to Drive
- Survive Colab session disconnects

```python
from google.colab import drive
drive.mount('/content/drive')
```

### 3. Run Overnight
- Colab free tier: 12-hour max runtime
- Colab Pro: 24-hour max runtime
- Set NUM_RUNS=1 and split into multiple sessions if needed

### 4. Monitor Progress
Add this to benchmark loop for better progress tracking:

```python
from tqdm.notebook import tqdm
# Wrap query loop with tqdm
for query in tqdm(queries, desc="Running queries"):
    result = runner.run_single_query(query)
```

## Troubleshooting

### "GROQ_API_KEY not found"
- Ensure you added it to Colab Secrets (🔑 icon)
- Toggle "Notebook access" ON
- Restart runtime and re-run

### "Module not found"
- Re-run the dependency installation cell
- Check for any package conflicts

### "Rate limit exceeded"
**Solutions:**
1. Reduce NUM_RUNS to 1
2. Add time.sleep() between queries
3. Split dataset into smaller batches
4. Try different LLM provider (DeepSeek, Claude)

### "Out of memory"
- Restart runtime: Runtime → Restart runtime
- Reduce chunk_size in pipeline initialization
- Process documents in batches

### "Session disconnected"
If Colab disconnects during benchmark:
- Partial results are saved automatically
- Re-run from the "Run Benchmark" cell
- Results accumulate across sessions

## Cost Comparison

| Approach | API Costs | Compute Costs | Time |
|----------|-----------|---------------|------|
| **Local** | Groq (free/rate limited) | $0 (your machine) | Variable |
| **Colab Free** | Groq (free/rate limited) | $0 | 15-30 min |
| **Colab Pro** | Groq (free/rate limited) | $10/month | Faster, longer runtime |

**Recommendation**: Start with Colab Free. Upgrade to Pro only if you need:
- Longer runtimes (>12 hours)
- Better GPUs (A100)
- Priority access

## Advanced: Running Multiple Articles

To benchmark multiple articles in parallel:

1. **Create copies** of the Colab notebook:
   - `colab_article_01.ipynb`
   - `colab_article_02.ipynb`
   - etc.

2. **Modify dataset paths** in each:
   ```python
   DATASET_FILE = Path("datasets/synthetic_queries/article_02.json")
   ```

3. **Run on separate Colab sessions**
   - Open multiple Colab tabs
   - Each uses independent quota

4. **Merge results locally**:
   ```bash
   cp article_01_benchmarks.json results/data/
   cp article_02_benchmarks.json results/data/
   ```

## Integration with CI/CD (Future)

For automated benchmarking:

1. **GitHub Actions + Colab**:
   - Use [colab-cli](https://github.com/ris-ai/colab-cli)
   - Trigger from PRs or scheduled runs

2. **Weights & Biases**:
   - Log metrics to W&B from Colab
   - Track experiments across sessions

3. **DVC (Data Version Control)**:
   - Version benchmark results
   - Track data lineage

## Questions?

See:
- `docs/specifications.md` - Full technical specs
- `docs/tasks.md` - Implementation roadmap
- `benchmarks/run_article_01.py` - Local benchmark script

Or open an issue on GitHub.
