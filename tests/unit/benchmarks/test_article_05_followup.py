import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest

from benchmarks.run_article_05_followup import (
    DATASET,
    BudgetExceededError,
    Ledger,
    MeasuredClient,
    create_fixture,
    parse_verdict,
    query_ids,
)


def test_concurrent_reservations_cannot_overspend(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "calls.jsonl", cap=0.015)

    def reserve() -> bool:
        try:
            ledger.reserve(0.01)
            return True
        except BudgetExceededError:
            return False

    with ThreadPoolExecutor(max_workers=3) as executor:
        assert sum(executor.map(lambda _: reserve(), range(3))) == 1


def test_crash_reservations_survive_restart(tmp_path: Path) -> None:
    path = tmp_path / "calls.jsonl"
    Ledger(path, cap=1).reserve(0.8)
    restarted = Ledger(path, cap=1)
    assert restarted.liability == pytest.approx(0.8)
    with pytest.raises(BudgetExceededError):
        restarted.reserve(0.3)


def test_settled_request_is_not_counted_twice(tmp_path: Path) -> None:
    path = tmp_path / "calls.jsonl"
    ledger = Ledger(path, cap=1)
    token = ledger.reserve(0.8)
    ledger.settle(0.8, {"reservation_id": token, "budget_charge_usd": 0.1})
    assert Ledger(path, cap=1).liability == pytest.approx(0.1)


def test_empty_billed_response_is_accounted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    ledger = Ledger(tmp_path / "calls.jsonl")
    client = MeasuredClient(ledger, "inner_rag")
    client.http = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "id": "r",
                    "model": "claude-sonnet-5-5",
                    "content": [],
                    "stop_reason": "max_tokens",
                    "usage": {"input_tokens": 100, "output_tokens": 50},
                },
                request=request,
            )
        )
    )
    result = client.generate(prompt="test", max_tokens=100)
    assert result.content == ""
    assert ledger.events[0]["cost_usd"] == pytest.approx(0.0007)
    assert ledger.events[0]["role"] == "inner_rag"


def test_provider_error_consumes_reservation_and_is_retained(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    ledger = Ledger(tmp_path / "calls.jsonl")
    client = MeasuredClient(ledger, "outer")
    client.http = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                429, json={"error": {"type": "rate_limit_error"}}, request=request
            )
        )
    )
    with pytest.raises(httpx.HTTPStatusError):
        client.generate(prompt="test", max_tokens=100)
    assert not ledger.events[0]["usage_known"]
    assert ledger.liability == ledger.events[0]["reservation_usd"]


def test_cap_blocks_before_http_dispatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    client = MeasuredClient(Ledger(tmp_path / "calls.jsonl", cap=0), "outer")
    with pytest.raises(BudgetExceededError):
        client.generate(prompt="test")
    assert client.ledger.events == []


def test_fixture_oracles_and_filter_broadening(tmp_path: Path) -> None:
    spec = json.loads(DATASET.read_text())
    path = tmp_path / "fixture.db"
    create_fixture(path, spec["fixture_rows"])
    for case in spec["sql_cases"]:
        assert query_ids(path, case["oracle_sql"]) == case["expected_ids"]
    assert query_ids(path, "SELECT id FROM docs WHERE framework='pydantic'") != [3, 7]
    assert query_ids(path, "SELECT id FROM docs WHERE difficulty='beginner'") != [3, 7]
    assert query_ids(path, "SELECT id FROM docs WHERE framework='fastapi' OR framework='react'")


def test_judge_cannot_pass_by_omitting_criteria_or_fabricating() -> None:
    verdict = {
        "criteria": [{"met": True, "reason": "test"}],
        "evidence_supported": True,
        "fabrication": True,
    }
    assert not parse_verdict(json.dumps(verdict), 1)["supported_answer"]
    with pytest.raises(AssertionError):
        parse_verdict(json.dumps(verdict), 2)
    verdict["criteria"][0]["met"] = "true"
    with pytest.raises(AssertionError):
        parse_verdict(json.dumps(verdict), 1)
