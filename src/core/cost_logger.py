"""LLM cost tracking with per-model pricing, budget alerts, and 30-day forecasting.

Teaching note: Cost tracking is non-negotiable in production LLM systems.
A single misdirected request loop can burn through a monthly budget in hours.
This module addresses two concerns:

1. CostLogger: Per-call cost accumulation with budget guardrails.
   - Prices loaded from config/model_pricing.yaml (easy to update without code changes)
   - In-memory accumulation (zero I/O per call, no latency impact)
   - Budget alerts at 80% (WARNING) and 100% (ERROR) thresholds

2. CostForecast: 30-day linear regression forecast from recent daily totals.
   - Linear (not exponential) because LLM usage at stable load is roughly linear
   - Confidence interval width signals forecast reliability: wide CI = volatile spend
   - Use as input to automated budget scaling or alert emails
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml
from scipy import stats as scipy_stats

logger = logging.getLogger(__name__)

_PRICING_CONFIG = Path(__file__).parent.parent.parent / "config" / "model_pricing.yaml"

# Default pricing when model not in config (conservative overestimate).
# GPT-4o pricing used as worst-case: unknown model is probably expensive.
_DEFAULT_INPUT_PRICE = 5.00  # $/1M tokens
_DEFAULT_OUTPUT_PRICE = 15.00  # $/1M tokens

_BUDGET_WARNING_THRESHOLD = 0.80  # Warn at 80% spent
_BUDGET_ERROR_THRESHOLD = 1.00  # Error at 100% spent


@dataclass
class CallRecord:
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float


class CostLogger:
    """Tracks LLM token usage and cost across calls.

    Teaching note: Cost tracking is non-negotiable in production.
    A bug that doubles token usage can turn $100/day into $200/day overnight.
    This class accumulates costs in memory (fast, no I/O per call) and
    exposes budget alerts that the router can check periodically.

    For persistent tracking across restarts, wire log_call() output to SQLite
    (see Article 6 benchmarks script).
    """

    def __init__(
        self,
        pricing_config: Path = _PRICING_CONFIG,
        monthly_budget_usd: float = 100.0,
    ) -> None:
        self._pricing = self._load_pricing(pricing_config)
        self._monthly_budget = monthly_budget_usd
        self._records: list[CallRecord] = []
        self._accumulated_cost: float = 0.0

    def _load_pricing(self, config_path: Path) -> dict[str, dict[str, float]]:
        if config_path.exists():
            with open(config_path) as f:
                data = yaml.safe_load(f)
                return dict(data.get("models", {}))
        logger.warning("Pricing config not found at %s, using defaults", config_path)
        return {}

    def calculate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Calculate USD cost for a single LLM call."""
        prices = self._pricing.get(
            model,
            {"input": _DEFAULT_INPUT_PRICE, "output": _DEFAULT_OUTPUT_PRICE},
        )
        input_cost = (input_tokens / 1_000_000) * prices["input"]
        output_cost = (output_tokens / 1_000_000) * prices["output"]
        return input_cost + output_cost

    def log_call(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Record a call and return its cost in USD."""
        cost = self.calculate_cost(model, input_tokens, output_tokens)
        self._records.append(CallRecord(model, input_tokens, output_tokens, cost))
        self._accumulated_cost += cost
        return cost

    def daily_summary(self) -> dict[str, float | int]:
        """Aggregate metrics for all logged calls."""
        return {
            "total_cost_usd": round(self._accumulated_cost, 6),
            "total_input_tokens": sum(r.input_tokens for r in self._records),
            "total_output_tokens": sum(r.output_tokens for r in self._records),
            "call_count": len(self._records),
        }

    def check_budget(self) -> dict[str, str]:
        """Check current spend against monthly budget."""
        pct = self._accumulated_cost / self._monthly_budget
        if pct >= _BUDGET_ERROR_THRESHOLD:
            msg = f"Budget EXCEEDED: ${self._accumulated_cost:.2f} / ${self._monthly_budget:.2f}"
            logger.error(msg)
            return {"level": "ERROR", "message": msg}
        if pct >= _BUDGET_WARNING_THRESHOLD:
            msg = (
                f"Budget at 80%+: ${self._accumulated_cost:.2f} / ${self._monthly_budget:.2f}"
                " (100% = stop)"
            )
            logger.warning(msg)
            return {"level": "WARNING", "message": msg}
        return {
            "level": "OK",
            "message": f"${self._accumulated_cost:.2f} / ${self._monthly_budget:.2f}",
        }


class CostForecast:
    """Linear regression forecast for LLM costs.

    Teaching note: Why linear (not exponential)?
    - Simple to explain and audit; budget owners understand straight-line projections
    - Good enough for stable workloads (not growth modeling)
    - Exponential: Use only when user base is doubling week-over-week
    - Linear with confidence interval catches surprise spikes via CI width

    The confidence interval width is the key signal:
    - Narrow CI: Spend is predictable, safe to plan around the point estimate
    - Wide CI: Spend is volatile, add a safety buffer or investigate the cause

    Usage: Compute daily_costs from CostLogger.daily_summary() over a rolling 7-day
    window, then call predict_30_days() to estimate next month's spend.
    """

    def __init__(self, daily_costs: list[float]) -> None:
        if len(daily_costs) < 2:
            raise ValueError("Need at least 2 days of data for forecasting")
        costs = np.array(daily_costs)
        days = np.arange(len(daily_costs))
        result = scipy_stats.linregress(days, costs)
        self._slope = float(result.slope)
        self._intercept = float(result.intercept)
        self._std_err = float(result.stderr)
        self._n = len(daily_costs)

    def predict_30_days(self) -> float:
        """Predict total cost for next 30 days."""
        future_days = np.arange(self._n, self._n + 30)
        predictions = self._slope * future_days + self._intercept
        return float(predictions.sum())

    def confidence_interval_30d(self, alpha: float = 0.05) -> tuple[float, float]:
        """95% confidence interval on 30-day forecast.

        Uses regression standard error scaled by number of forecast periods.
        Wider std_err = less certain trend = wider CI.
        """
        margin = 1.96 * self._std_err * 30
        center = self.predict_30_days()
        return (max(0.0, center - margin), center + margin)
