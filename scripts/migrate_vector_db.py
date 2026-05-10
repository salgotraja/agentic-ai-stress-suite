#!/usr/bin/env python3
"""Migrate embeddings from Chroma to Qdrant.

Why migrate from Chroma to Qdrant at all?
- Chroma is excellent for local development: simple HTTP API, easy setup,
  no configuration required. But it hits scaling limits around 1M vectors.
- Qdrant offers payload filtering (pre-filter by metadata before ANN search),
  named vectors (multiple vector spaces per document), built-in snapshots for
  backups, and a gRPC API (~2x batch throughput vs REST due to binary protocol).
- Article 8 benchmark: Qdrant achieves p95 < 500ms at 100 req/sec with heavy
  metadata filtering; Chroma struggles with post-filter overhead at the same load.

Migration design choices:
- Stateless script (not a daemon): run once, verify, done.
- Batch upserts (default 100): avoids single large HTTP request that can time out
  and keeps memory bounded for multi-million vector corpora.
- Idempotent: re-running the script is safe. Qdrant upsert semantics handle
  duplicate point IDs by overwriting, so partial runs can be resumed.
- Dry-run flag: inspect Chroma counts without touching Qdrant state at all.

Usage:
    # Default migration (local dev stack)
    python scripts/migrate_vector_db.py

    # Custom collection names
    python scripts/migrate_vector_db.py \\
        --chroma-collection naive_rag \\
        --qdrant-collection naive_rag

    # Dry-run against production Chroma
    python scripts/migrate_vector_db.py \\
        --chroma-host prod-chroma.internal \\
        --dry-run

    # Smaller batch size for flaky networks
    python scripts/migrate_vector_db.py --batch-size 25
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import math
import sys

import chromadb
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def get_chroma_client(host: str, port: int) -> chromadb.HttpClient:
    """Connect to a running Chroma HTTP server.

    Args:
        host: Chroma server hostname or IP
        port: Chroma server port (default 8000 per docker-compose.yml)

    Returns:
        Chroma HTTP client connected to the specified server

    Teaching note: We use HttpClient (not PersistentClient) because Chroma
    is running as a Docker container with an HTTP API. PersistentClient would
    require direct filesystem access to the Chroma data directory, which is
    impractical when the DB lives inside a container volume.
    """
    return chromadb.HttpClient(host=host, port=port)


def get_chroma_documents(
    client: chromadb.HttpClient,
    collection_name: str,
) -> tuple[list[str], list[list[float]], list[dict]]:
    """Fetch all ids, embeddings, and metadata from a Chroma collection.

    Args:
        client: Connected Chroma HTTP client
        collection_name: Name of the collection to export

    Returns:
        Tuple of (ids, embeddings, metadatas) - parallel lists of equal length.
        ids: string document IDs assigned by Chroma
        embeddings: float vectors (dimension matches the embedding model)
        metadatas: per-document metadata dicts (source, chunk index, etc.)

    Teaching note: We fetch all documents in one call rather than paginating.
    For collections up to ~500k vectors this is safe (< 2 GB RAM for 768-dim
    float32 vectors). Beyond that, Chroma's get() API does not yet support
    server-side pagination with a stable cursor, so paging via offset/limit can
    miss documents if the collection changes mid-migration. Fetching all at once
    gives a consistent snapshot. For multi-million vector corpora, consider
    Chroma snapshots or a different export strategy.
    """
    collection = client.get_collection(name=collection_name)
    total = collection.count()

    if total == 0:
        logger.warning(f"Chroma collection '{collection_name}' is empty")
        return [], [], []

    logger.info(f"Fetching {total} documents from Chroma collection '{collection_name}'")

    result = collection.get(include=["embeddings", "metadatas"])

    ids: list[str] = result["ids"]
    embeddings: list[list[float]] = result["embeddings"]
    metadatas: list[dict] = result["metadatas"] or [{} for _ in ids]

    if len(ids) != total:
        logger.warning(
            f"Expected {total} documents from Chroma count(), got {len(ids)}. "
            "Collection may have been modified during fetch."
        )

    return ids, embeddings, metadatas


def get_qdrant_client(url: str) -> QdrantClient:
    """Connect to a running Qdrant instance.

    Args:
        url: Qdrant REST endpoint URL (e.g. "http://localhost:6333")

    Returns:
        QdrantClient connected to the specified URL

    Teaching note: We use the REST URL here (port 6333). The Qdrant Python
    client also supports gRPC (port 6334) for higher batch throughput, but REST
    is sufficient for a one-time migration and avoids the grpcio dependency.
    Switch to prefer_grpc=True for repeated high-volume operations.
    """
    return QdrantClient(url=url)


def create_qdrant_collection(
    client: QdrantClient,
    collection_name: str,
    vector_size: int,
) -> None:
    """Create a Qdrant collection, skipping if it already exists.

    Args:
        client: Connected Qdrant client
        collection_name: Name for the target collection
        vector_size: Dimensionality of the embedding vectors

    Teaching note: Idempotent migration design - why skip vs recreate?
    - Recreating on every run would delete partial progress from a previous
      interrupted migration. Idempotency lets us resume safely.
    - Upserting into an existing collection is safe because Qdrant's upsert
      uses point IDs as the key: same ID overwrites the old vector and payload.
    - If you need a clean slate (schema change, different distance metric),
      delete the collection manually first: qdrant_client.delete_collection(name).

    Distance.COSINE is correct for BGE-base-en-v1.5 embeddings. BGE models
    are trained with cosine similarity as the objective. Using Euclidean or
    dot-product distance would produce incorrect ranking.
    """
    existing_collections = [c.name for c in client.get_collections().collections]

    if collection_name in existing_collections:
        info = client.get_collection(collection_name)
        existing_size = info.config.params.vectors.size
        if existing_size != vector_size:
            raise ValueError(
                f"Qdrant collection '{collection_name}' already exists with "
                f"vector_size={existing_size}, but source has vector_size={vector_size}. "
                "Delete the collection manually and re-run."
            )
        logger.info(
            f"Qdrant collection '{collection_name}' already exists "
            f"(vector_size={vector_size}), reusing it"
        )
        return

    client.create_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
    )
    logger.info(
        f"Created Qdrant collection '{collection_name}' "
        f"(vector_size={vector_size}, distance=COSINE)"
    )


def _chroma_id_to_qdrant_id(str_id: str) -> int:
    """Convert a Chroma string ID to a Qdrant-compatible integer ID.

    Qdrant point IDs must be unsigned 64-bit integers or UUIDs.
    We take the first 16 hex chars of the MD5 digest (64 bits) so the
    full Qdrant ID space is used. Birthday-paradox collision probability
    at 500k docs is roughly n^2 / (2 * 2^64) ~= 6.8e-9, i.e. effectively
    zero. An earlier version of this helper sliced [:8] (32 bits) and
    would have hit ~29 expected collisions at 500k docs; do not regress.

    For deployments that prefer string identity, switch to UUID5:
        import uuid; uuid.uuid5(uuid.NAMESPACE_DNS, str_id)
    """
    return int(hashlib.md5(str_id.encode()).hexdigest()[:16], 16)


def migrate_batch(
    qdrant_client: QdrantClient,
    collection_name: str,
    ids: list[str],
    embeddings: list[list[float]],
    metadatas: list[dict],
) -> int:
    """Upsert one batch of points into Qdrant.

    Args:
        qdrant_client: Connected Qdrant client
        collection_name: Target collection name
        ids: Chroma string IDs for this batch
        embeddings: Float vectors for this batch (parallel to ids)
        metadatas: Metadata dicts for this batch (parallel to ids)

    Returns:
        Number of points successfully upserted (equals len(ids) on success)

    Teaching note: Why batch upserts instead of one large call?
    1. Network timeouts: A single HTTP request carrying 10k+ vectors can
       exceed server-side timeout limits (Qdrant default: 30s).
    2. Memory: Building one giant PointStruct list for 500k vectors uses
       several GB of RAM. Batches keep peak memory proportional to batch_size.
    3. Progress visibility: Batching allows progress logging so long migrations
       don't appear hung.
    4. Partial recovery: If the script crashes mid-migration, already-upserted
       batches are already committed. Re-running simply overwrites them
       (idempotent upsert), so you don't restart from zero.
    """
    points = [
        PointStruct(
            id=_chroma_id_to_qdrant_id(doc_id),
            vector=embedding,
            payload={**metadata, "_chroma_id": doc_id},
        )
        for doc_id, embedding, metadata in zip(ids, embeddings, metadatas)
    ]

    qdrant_client.upsert(collection_name=collection_name, points=points)
    return len(points)


def verify_migration(
    chroma_count: int,
    qdrant_client: QdrantClient,
    collection_name: str,
) -> bool:
    """Verify that Qdrant received the expected number of points.

    Args:
        chroma_count: Number of documents fetched from Chroma
        qdrant_client: Connected Qdrant client
        collection_name: Collection to inspect in Qdrant

    Returns:
        True if Qdrant point count matches chroma_count, False otherwise

    Teaching note: Why verify at all?
    Silent data corruption is the most dangerous failure mode in migrations:
    - A network hiccup during the last batch can silently drop points
    - Qdrant upsert returns 200 OK even if the operation is queued (eventually
      consistent for large batches)
    - Without verification you won't notice the 3% loss until users report
      degraded retrieval quality weeks later

    Count verification is cheap (O(1) server-side) and catches the most common
    failure: interrupted migration leaving Qdrant partially populated.

    Limitation: count equality is necessary but not sufficient. It won't catch
    a scenario where N documents were upserted twice and N others were missed
    (counts match but data is wrong). For high-stakes migrations, also spot-check
    random vector values or run a retrieval benchmark on both stores.
    """
    info = qdrant_client.get_collection(collection_name)
    qdrant_count = info.points_count

    if qdrant_count == chroma_count:
        logger.info(
            f"Verification passed: Qdrant has {qdrant_count} points (expected {chroma_count})"
        )
        return True

    logger.error(
        f"Verification FAILED: Qdrant has {qdrant_count} points, "
        f"expected {chroma_count}. Re-run the migration."
    )
    return False


def main() -> None:
    """Parse CLI arguments, run the migration, and print a summary."""
    parser = argparse.ArgumentParser(
        description="Migrate embeddings from Chroma to Qdrant (Article 8 scaling demo)"
    )
    parser.add_argument(
        "--source",
        default="chroma",
        choices=["chroma"],
        help="Source vector DB type (default: chroma)",
    )
    parser.add_argument(
        "--target",
        default="qdrant",
        choices=["qdrant"],
        help="Target vector DB type (default: qdrant)",
    )
    parser.add_argument(
        "--chroma-host",
        default="localhost",
        help="Chroma server host (default: localhost)",
    )
    parser.add_argument(
        "--chroma-port",
        type=int,
        default=8000,
        help="Chroma server port (default: 8000)",
    )
    parser.add_argument(
        "--chroma-collection",
        default="tech_docs",
        help="Chroma collection to migrate (default: tech_docs)",
    )
    parser.add_argument(
        "--qdrant-url",
        default="http://localhost:6333",
        help="Qdrant REST URL (default: http://localhost:6333)",
    )
    parser.add_argument(
        "--qdrant-collection",
        default="tech_docs",
        help="Qdrant target collection name (default: tech_docs)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Number of embeddings per batch upsert (default: 100)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print document counts from Chroma but do not write to Qdrant",
    )

    args = parser.parse_args()

    # Step 1: Connect to Chroma and fetch all documents
    logger.info(f"Connecting to Chroma at {args.chroma_host}:{args.chroma_port}")
    chroma_client = get_chroma_client(host=args.chroma_host, port=args.chroma_port)

    ids, embeddings, metadatas = get_chroma_documents(
        client=chroma_client,
        collection_name=args.chroma_collection,
    )
    chroma_count = len(ids)

    if chroma_count == 0:
        logger.error(
            f"No documents found in Chroma collection '{args.chroma_collection}'. "
            "Ensure the collection exists and is populated."
        )
        sys.exit(1)

    logger.info(f"Found {chroma_count} documents in Chroma")

    # Dry-run: report counts and exit without touching Qdrant
    # Teaching note: The dry-run flag is essential for production migrations.
    # It lets you validate that Chroma is reachable and holds the expected number
    # of vectors before committing any changes to the Qdrant cluster.
    if args.dry_run:
        vector_size = len(embeddings[0]) if embeddings else 0
        logger.info(
            f"[DRY RUN] Would migrate {chroma_count} documents "
            f"(vector_size={vector_size}) to Qdrant collection "
            f"'{args.qdrant_collection}' at {args.qdrant_url}"
        )
        logger.info(
            f"[DRY RUN] Batch size: {args.batch_size}, "
            f"batches needed: {math.ceil(chroma_count / args.batch_size)}"
        )
        logger.info("[DRY RUN] No data written. Remove --dry-run to proceed.")
        return

    # Step 2: Connect to Qdrant and create target collection
    logger.info(f"Connecting to Qdrant at {args.qdrant_url}")
    qdrant_client = get_qdrant_client(url=args.qdrant_url)

    vector_size = len(embeddings[0])
    create_qdrant_collection(
        client=qdrant_client,
        collection_name=args.qdrant_collection,
        vector_size=vector_size,
    )

    # Step 3: Migrate in batches
    total_migrated = 0
    num_batches = math.ceil(chroma_count / args.batch_size)

    logger.info(f"Migrating {chroma_count} documents in {num_batches} batches of {args.batch_size}")

    for batch_index in range(num_batches):
        start = batch_index * args.batch_size
        end = min(start + args.batch_size, chroma_count)

        batch_ids = ids[start:end]
        batch_embeddings = embeddings[start:end]
        batch_metadatas = metadatas[start:end]

        count = migrate_batch(
            qdrant_client=qdrant_client,
            collection_name=args.qdrant_collection,
            ids=batch_ids,
            embeddings=batch_embeddings,
            metadatas=batch_metadatas,
        )
        total_migrated += count

        logger.info(
            f"Batch {batch_index + 1}/{num_batches}: "
            f"upserted {count} points (total so far: {total_migrated})"
        )

    # Step 4: Verify migration completeness
    success = verify_migration(
        chroma_count=chroma_count,
        qdrant_client=qdrant_client,
        collection_name=args.qdrant_collection,
    )

    # Summary
    logger.info("")
    logger.info("Migration summary")
    logger.info("-" * 40)
    logger.info(f"  Source:      Chroma {args.chroma_host}:{args.chroma_port}")
    logger.info(f"  Target:      Qdrant {args.qdrant_url}")
    logger.info(f"  Collection:  {args.chroma_collection} -> {args.qdrant_collection}")
    logger.info(f"  Documents:   {chroma_count}")
    logger.info(f"  Vector size: {vector_size}")
    logger.info(f"  Batches:     {num_batches} x {args.batch_size}")
    logger.info(f"  Status:      {'SUCCESS' if success else 'FAILED'}")

    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
