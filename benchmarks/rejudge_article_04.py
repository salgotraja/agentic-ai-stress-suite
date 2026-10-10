#!/usr/bin/env python3
"""Re-score a saved Article 4 artifact with the current judge.

Generation and judging are separate: an artifact keeps every trial's answer
and tool events, so a judge fix can be applied to both models' saved trials
without re-running any agent. Writes a new artifact; the input is unchanged.

Usage:
    uv run python benchmarks/rejudge_article_04.py IN.json OUT.json
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.run_article_04 import (  # noqa: E402
    JUDGE_MODEL,
    JUDGE_PROVIDER,
    JUDGE_REVISION,
    AgentBenchmarkResult,
    _AccumulatingLLMClient,
    compute_summary,
    judge_trial,
)

DATASET = PROJECT_ROOT / "datasets" / "synthetic_queries" / "article_04.json"


def rejudge(artifact: dict[str, Any], queries: dict[str, dict[str, Any]], judge: Any) -> None:
    """Replace every trial's judge verdict and recompute the summaries in place."""
    names = {f.name for f in fields(AgentBenchmarkResult)}
    for agent_type, rows in artifact["detailed_results"].items():
        results = [AgentBenchmarkResult(**{k: v for k, v in r.items() if k in names}) for r in rows]
        for result in results:
            result.judge = judge_trial(judge, queries[result.query_id], result)
        artifact["detailed_results"][agent_type] = [asdict(r) for r in results]
        artifact["summaries"][agent_type] = asdict(compute_summary(results, agent_type))


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 1
    source, target = Path(sys.argv[1]), Path(sys.argv[2])
    artifact = json.loads(source.read_text())
    queries = {q["id"]: q for q in json.loads(DATASET.read_text())["queries"]}
    judge = _AccumulatingLLMClient()
    rejudge(artifact, queries, judge)
    provenance = artifact.setdefault("provenance", {})
    provenance["judge_model"] = f"{JUDGE_PROVIDER.value}/{JUDGE_MODEL}"
    provenance["judge_revision"] = JUDGE_REVISION
    provenance["judge_cost_usd"] = judge.cost_usd
    provenance["rejudged_from"] = source.name
    target.write_text(json.dumps(artifact, indent=2) + "\n")
    for agent_type, summary in artifact["summaries"].items():
        print(
            f"{agent_type}: evidence-consistent {summary['evidence_consistent']}/"
            f"{summary['judged']} judged, parse failures {summary['judge_parse_failures']}"
        )
    print(f"Judge: {judge.calls} calls, ${judge.cost_usd:.4f}. Wrote {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
