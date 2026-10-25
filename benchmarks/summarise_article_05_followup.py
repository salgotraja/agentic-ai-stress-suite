"""Recompute follow-up summaries from retained trials and request usage."""

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any


def distribution(values: list[float]) -> dict[str, float]:
    if not values:
        return {}
    return {
        "mean": statistics.mean(values),
        "std": statistics.pstdev(values),
        "median": statistics.median(values),
        "min": min(values),
        "max": max(values),
    }


def summarise(rows: list[dict[str, Any]], calls: list[dict[str, Any]]) -> dict[str, Any]:
    ids = {r["trial_id"] for r in rows}
    events = [c for c in calls if c["trial_id"] in ids]
    verdicts = [r["judge"] for r in rows]
    for verdict in verdicts:
        if verdict.get("status") == "unscored":
            continue
        for name in ["final_correct", "constraint_drift", "valid_repair", "unnecessary_retry"]:
            if verdict.get(name) is not None and type(verdict[name]) is not bool:
                raise ValueError(f"Non-boolean judge field: {name}")
    generator = [c for c in events if c["role"] != "judge"]
    cost = sum(c.get("cost_usd") or 0 for c in generator)
    supported = sum(v.get("supported_answer") is True for v in verdicts)
    cutoffs = {c["trial_id"] for c in generator if c.get("stop_reason") == "max_tokens"}
    sql = [r for r in rows if r["track"] == "sql"]
    sql_counts = [len(r.get("result", {}).get("tool_events", [])) for r in sql]
    input_tokens = output_tokens = 0
    for event in generator:
        usage = event.get("usage", {})
        input_tokens += usage.get("input_tokens", usage.get("prompt_tokens", 0))
        input_tokens += usage.get("cache_creation_input_tokens", 0) + usage.get(
            "cache_read_input_tokens", 0
        )
        output_tokens += usage.get("output_tokens", usage.get("completion_tokens", 0))
    return {
        "trials": len(rows),
        "runner_completion": sum(
            bool(r.get("result", {}).get("output", r.get("result", {}).get("answer")))
            and not r.get("error_type")
            for r in rows
        ),
        "judge_unscored": sum(v.get("status") == "unscored" for v in verdicts),
        "raw_judge_acceptance_pass": sum(v.get("acceptance_pass") is True for v in verdicts),
        "raw_judge_supported_answer": supported,
        "raw_judge_evidence_supported": sum(v.get("evidence_supported") is True for v in verdicts),
        "raw_judge_final_correct": sum(v.get("final_correct") is True for v in verdicts),
        "raw_judge_constraint_drift": sum(v.get("constraint_drift") is True for v in verdicts),
        "generator_cost_usd": cost,
        "judge_cost_usd": sum(c.get("cost_usd") or 0 for c in events if c["role"] == "judge"),
        "cost_per_raw_judge_supported_answer_usd": cost / supported if supported else None,
        "latency_ms": distribution([r["latency_ms"] for r in rows]),
        "llm_calls": distribution([r["llm_calls"] for r in rows]),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "inner_rag_calls": sum(c["role"] == "inner_rag" for c in events),
        "inner_rag_cost_usd": sum(
            c.get("cost_usd") or 0 for c in events if c["role"] == "inner_rag"
        ),
        "max_tokens_calls": sum(c.get("stop_reason") == "max_tokens" for c in generator),
        "trials_with_max_tokens": len(cutoffs),
        "unknown_usage_calls": sum(not c["usage_known"] for c in events),
        "sql_calls": distribution(sql_counts),
        "sql_trials_with_additional_calls": sum(n > 1 for n in sql_counts),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--ledger", type=Path, required=True)
    args = parser.parse_args()
    rows = [json.loads(line) for line in (args.directory / "trials.jsonl").read_text().splitlines()]
    calls = [json.loads(line) for line in args.ledger.read_text().splitlines()]
    assert len({r["trial_id"] for r in rows}) == len(rows)
    groups = {}
    for row in rows:
        key = (
            row["pattern"]
            if row["track"] == "multi"
            else "sql/" + row["agent"] + "/" + row["result"]["oracle"]["kind"]
        )
        groups.setdefault(key, []).append(row)
    report = {
        "summary": summarise(rows, calls),
        "groups": {key: summarise(value, calls) for key, value in groups.items()},
        "group_sizes": dict(Counter(r["track"] for r in rows)),
        "note": "Raw judge verdicts; consult assistant audit before interpreting SQL correctness or semantic predicate preservation.",
    }
    (args.directory / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
