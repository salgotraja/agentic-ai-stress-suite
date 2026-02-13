# PDF Test Documents

Place open-license PDF files here for testing the PDF chunking pipeline.

Recommended sources (all open-license):
- PEP documents: https://peps.python.org/ (public domain)
- Python documentation: https://docs.python.org/ (PSF license)
- FastAPI documentation exports (MIT license)

To add a PDF:
1. Download the PDF to this directory
2. Add corresponding queries to `datasets/synthetic_queries/article_02.json`
3. Run: `uv run python -m src.rag.chunking` to verify extraction
