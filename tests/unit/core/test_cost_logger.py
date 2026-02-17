from __future__ import annotations

import pytest

from src.core.cost_logger import CostLogger


def test_calculate_cost_for_known_model() -> None:
    """Cost calculation uses per-model pricing from config."""
    logger = CostLogger()
    cost = logger.calculate_cost(
        model="groq/llama-3.1-8b-instant",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
    )
    # $0.05/1M input + $0.08/1M output = $0.13
    assert cost == pytest.approx(0.13, rel=1e-3)


def test_calculate_cost_for_unknown_model_uses_default() -> None:
    """Unknown model falls back to default pricing."""
    logger = CostLogger()
    cost = logger.calculate_cost("unknown/model-xyz", 1_000_000, 1_000_000)
    assert cost > 0  # Uses default, not zero


def test_log_call_accumulates_daily_total() -> None:
    """Daily cost accumulates across multiple log_call calls."""
    logger = CostLogger()
    logger.log_call("groq/llama-3.1-8b-instant", 100_000, 50_000)
    logger.log_call("groq/llama-3.1-8b-instant", 100_000, 50_000)
    summary = logger.daily_summary()
    assert summary["total_cost_usd"] > 0
    assert summary["total_input_tokens"] == 200_000
    assert summary["total_output_tokens"] == 100_000


def test_budget_alert_at_80_percent() -> None:
    """Budget alert triggers at 80% of monthly budget."""
    logger = CostLogger(monthly_budget_usd=10.0)
    # Simulate $8.50 spend (85%)
    logger._accumulated_cost = 8.50
    alert = logger.check_budget()
    assert alert["level"] == "WARNING"
    assert "80%" in alert["message"]


def test_budget_error_at_100_percent() -> None:
    """Budget error triggers at 100% of monthly budget."""
    logger = CostLogger(monthly_budget_usd=10.0)
    logger._accumulated_cost = 10.50
    alert = logger.check_budget()
    assert alert["level"] == "ERROR"


def test_forecast_linear_regression_from_7_day_data() -> None:
    """Linear regression forecasts 30-day cost from 7-day history."""
    from src.core.cost_logger import CostForecast

    # Simulate 7 days of increasing cost: $1/day
    daily_costs = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]
    forecast = CostForecast(daily_costs)
    prediction_30d = forecast.predict_30_days()
    # Day 30 should be ~$30 (linear extrapolation): sum of days 8-37 at ~$1/day slope
    assert prediction_30d > 0


def test_forecast_confidence_interval_is_wider_for_volatile_data() -> None:
    """High variance in daily costs -> wider confidence interval."""
    from src.core.cost_logger import CostForecast

    stable = CostForecast([1.0, 1.1, 0.9, 1.0, 1.1, 0.9, 1.0])
    volatile = CostForecast([0.5, 5.0, 0.1, 8.0, 0.3, 6.0, 1.0])
    stable_ci = stable.confidence_interval_30d()
    volatile_ci = volatile.confidence_interval_30d()
    stable_width = stable_ci[1] - stable_ci[0]
    volatile_width = volatile_ci[1] - volatile_ci[0]
    assert volatile_width > stable_width
