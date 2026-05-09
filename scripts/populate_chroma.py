"""Populate a Chroma collection with embeddings from datasets/tech_docs/.

Used by `scripts/populate_chroma_in_cluster.sh` to seed the in-cluster Chroma
PVC for Article 8 throughput/HPA measurement, but the script is also reusable
locally against the docker-compose Chroma (just point CHROMA_URL).

Why this exists separately from `examples/article_01_state_aware_rag/demo_naive_rag.py`:
the demo script always runs an LLM query at the end which (a) costs Groq tokens,
(b) requires GROQ_API_KEY, and (c) muddles "did we populate" with "is the LLM
reachable". This script does the populate path only -- embed + write -- with no
LLM dependency. Verifying generation belongs in A08.deploy-api.

Idempotent: if the target collection already has rows, the script logs the
count and exits 0 without re-embedding. Use --rebuild to force.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from src.core.config import get_settings
from src.rag.naive_rag import NaiveRAGPipeline

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description="Populate a Chroma collection from tech_docs/")
    parser.add_argument(
        "--collection",
        type=str,
        default="naive_rag",
        help="Chroma collection name (default: naive_rag, matches api.py DEFAULT_COLLECTION)",
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "datasets" / "tech_docs" / "fastapi",
        help="Path to source documents (default: datasets/tech_docs/fastapi)",
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Re-embed even if the collection is already populated",
    )
    args = parser.parse_args()

    if not args.dataset.exists():
        logger.error("Dataset directory not found: %s", args.dataset)
        return 1

    settings = get_settings()
    logger.info("Chroma URL: %s", settings.chroma_url)
    logger.info("Collection: %s", args.collection)
    logger.info("Source: %s", args.dataset)

    pipeline = NaiveRAGPipeline(collection_name=args.collection, settings=settings)

    # Idempotency: skip embedding if the collection already has data. We use
    # get_or_create_collection (not get_collection) so a missing collection
    # is treated as "empty" rather than raising.
    collection = pipeline.chroma_client.get_or_create_collection(name=args.collection)
    existing = collection.count()
    if existing > 0 and not args.rebuild:
        logger.info(
            "Collection already populated with %d rows; skipping. Use --rebuild to force.", existing
        )
        return 0

    documents = pipeline.load_documents(args.dataset)
    logger.info("Loaded %d documents; embedding and writing to Chroma...", len(documents))
    pipeline.build_index(documents)

    final = collection.count()
    logger.info("Done. Collection %s now has %d rows.", args.collection, final)
    return 0


if __name__ == "__main__":
    sys.exit(main())
