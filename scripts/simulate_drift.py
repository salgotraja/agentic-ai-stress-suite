#!/usr/bin/env python3
"""
Simulate embedding drift by injecting out-of-distribution queries.

Usage:
    python scripts/simulate_drift.py --ood-queries 100
"""

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np

from src.rag.evaluation.drift_detection import DriftDetector


def generate_baseline_embeddings(n: int, embedding_dim: int = 384, seed: int = 42) -> np.ndarray:
    """
    Generate baseline embeddings from normal distribution.

    Simulates typical query embeddings with specific characteristics:
    - Mean around 0 (normalized embeddings)
    - Std around 0.3 (realistic for BGE embeddings)
    """
    rng = np.random.RandomState(seed)
    embeddings = rng.normal(loc=0.0, scale=0.3, size=(n, embedding_dim))
    # Normalize to unit length (typical for cosine similarity)
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    embeddings = embeddings / (norms + 1e-8)
    return embeddings


def generate_drifted_embeddings(
    n: int,
    embedding_dim: int = 384,
    drift_type: str = "shift",
    drift_magnitude: float = 0.5,
    seed: int = 43,
) -> np.ndarray:
    """
    Generate out-of-distribution embeddings.

    Args:
        n: Number of embeddings
        embedding_dim: Embedding dimensionality
        drift_type: Type of drift ("shift", "scale", "rotation")
        drift_magnitude: Magnitude of drift
        seed: Random seed

    Returns:
        Drifted embeddings
    """
    rng = np.random.RandomState(seed)

    if drift_type == "shift":
        # Mean shift: embeddings from different distribution center
        # Simulates topic shift (e.g., users now asking about different products)
        embeddings = rng.normal(loc=drift_magnitude, scale=0.3, size=(n, embedding_dim))

    elif drift_type == "scale":
        # Variance change: embeddings with different spread
        # Simulates increased query diversity
        embeddings = rng.normal(loc=0.0, scale=0.3 * (1 + drift_magnitude), size=(n, embedding_dim))

    elif drift_type == "rotation":
        # Rotated distribution: different subspace
        # Simulates semantic shift to related but distinct topics
        embeddings = rng.normal(loc=0.0, scale=0.3, size=(n, embedding_dim))
        # Apply random rotation matrix
        rotation_matrix = generate_rotation_matrix(embedding_dim, drift_magnitude, rng)
        embeddings = embeddings @ rotation_matrix.T

    else:
        raise ValueError(f"Unknown drift type: {drift_type}")

    # Normalize
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    embeddings = embeddings / (norms + 1e-8)

    return embeddings


def generate_rotation_matrix(dim: int, magnitude: float, rng: np.random.RandomState) -> np.ndarray:
    """Generate random rotation matrix."""
    # QR decomposition of random matrix gives orthogonal matrix (rotation)
    random_matrix = rng.randn(dim, dim)
    q, r = np.linalg.qr(random_matrix)
    # Scale rotation by magnitude
    identity = np.eye(dim)
    return identity * (1 - magnitude) + q * magnitude


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulate embedding drift")
    parser.add_argument(
        "--ood-queries", type=int, default=100, help="Number of out-of-distribution queries"
    )
    parser.add_argument(
        "--baseline-queries", type=int, default=1000, help="Number of baseline queries"
    )
    parser.add_argument(
        "--drift-type",
        choices=["shift", "scale", "rotation"],
        default="shift",
        help="Type of drift",
    )
    parser.add_argument(
        "--drift-magnitude", type=float, default=0.5, help="Magnitude of drift (0.0-1.0)"
    )
    parser.add_argument("--embedding-dim", type=int, default=384, help="Embedding dimensionality")
    parser.add_argument(
        "--output", default="results/drift_simulation_report.json", help="Output report path"
    )

    args = parser.parse_args()

    print("Simulating embedding drift")
    print(f"Baseline queries: {args.baseline_queries}")
    print(f"Out-of-distribution queries: {args.ood_queries}")
    print(f"Drift type: {args.drift_type}")
    print(f"Drift magnitude: {args.drift_magnitude}")

    # Initialize detector
    detector = DriftDetector(
        embedding_dim=args.embedding_dim,
        window_size=500,
        baseline_size=args.baseline_queries,
        kl_threshold=0.15,
        ks_threshold=0.05,
    )

    # Phase 1: Establish baseline
    print("\nPhase 1: Establishing baseline...")
    baseline_embeddings = generate_baseline_embeddings(args.baseline_queries, args.embedding_dim)

    for embedding in baseline_embeddings:
        detector.add_embedding(embedding)

    print(f"Baseline established with {len(detector.baseline_embeddings)} embeddings")

    # Phase 2: Normal operation (should not trigger drift)
    print("\nPhase 2: Normal operation (no drift)...")
    normal_embeddings = generate_baseline_embeddings(500, args.embedding_dim, seed=100)

    normal_alerts = 0
    for embedding in normal_embeddings:
        alert = detector.add_embedding(embedding)
        if alert:
            normal_alerts += 1

    print(f"Normal phase: {normal_alerts} drift alerts (should be near 0)")

    # Phase 3: Inject drift
    print(f"\nPhase 3: Injecting {args.drift_type} drift...")
    drifted_embeddings = generate_drifted_embeddings(
        args.ood_queries, args.embedding_dim, args.drift_type, args.drift_magnitude
    )

    drift_alerts = []
    for idx, embedding in enumerate(drifted_embeddings):
        alert = detector.add_embedding(embedding, metadata={"query_type": "drifted", "index": idx})
        if alert:
            drift_alerts.append(alert)
            if len(drift_alerts) == 1:  # First alert
                print(f"  First drift detected at sample {idx + 1}")
                print(f"  KL divergence: {alert['metrics']['kl_divergence']:.4f}")
                print(f"  KS test p-value: {alert['metrics']['ks_test_pvalue']:.6f}")

    print(f"Drift phase: {len(drift_alerts)} drift alerts")

    # Get summary
    summary = detector.get_drift_summary()

    # Create report
    report: dict[str, Any] = {
        "simulation_params": {
            "baseline_queries": args.baseline_queries,
            "ood_queries": args.ood_queries,
            "drift_type": args.drift_type,
            "drift_magnitude": args.drift_magnitude,
            "embedding_dim": args.embedding_dim,
        },
        "results": {
            "normal_phase_alerts": normal_alerts,
            "drift_phase_alerts": len(drift_alerts),
            "detection_rate": len(drift_alerts) / args.ood_queries if args.ood_queries > 0 else 0,
        },
        "detector_summary": summary,
        "first_alert": drift_alerts[0] if drift_alerts else None,
    }

    # Save report
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"\nReport saved to: {args.output}")

    # Print summary
    print("\n" + "=" * 60)
    print("Drift Detection Summary")
    print("=" * 60)
    print(f"Detection Rate: {report['results']['detection_rate']:.1%}")
    print(f"Mean KL Divergence: {summary['kl_divergence']['mean']:.4f}")
    print(f"Max KL Divergence: {summary['kl_divergence']['max']:.4f}")
    print(f"Total Alerts: {summary['total_alerts']}")
    print("=" * 60)


if __name__ == "__main__":
    main()
