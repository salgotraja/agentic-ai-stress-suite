"""Generate a 30-day LLM cost forecast CSV from recent daily cost history.

Usage:
    python scripts/forecast_costs.py --output results/cost_forecast.csv
    python scripts/forecast_costs.py --output results/cost_forecast.csv --horizon 60

Teaching note: This script bridges CostForecast (which returns a 30-day total)
with the operational need for a per-day forecast table. Budget owners want to
see daily predictions (day 1: $0.55, day 2: $0.57 ...) not just a lump sum.
The per-day breakdown is a straight-line projection from the linear regression
trend — same math as CostForecast, exposed at finer granularity.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import numpy as np
from scipy import stats as scipy_stats

# Representative 7-day cost history in USD.
# In production: populate from CostLogger records persisted to SQLite,
# e.g. SELECT date, SUM(cost_usd) FROM call_log GROUP BY date ORDER BY date DESC LIMIT 7
_SAMPLE_DAILY_COSTS: list[float] = [0.42, 0.51, 0.48, 0.63, 0.55, 0.70, 0.68]


def forecast_to_csv(
    daily_costs: list[float],
    output_path: Path,
    horizon: int = 30,
) -> None:
    """Fit a linear trend to daily_costs and write per-day forecasts to CSV.

    Columns:
        day_offset    : 1-indexed day into the forecast horizon
        predicted_usd : point estimate from linear regression
        lower_ci_95   : lower bound of 95% confidence interval
        upper_ci_95   : upper bound of 95% confidence interval

    Why per-day margin = 1.96 * stderr (not cumulative)?
    Each day is an independent prediction from the regression line.
    Cumulative CI would require propagating uncertainty across days;
    per-day CI keeps it simple and is the common industry convention
    for operational dashboards.
    """
    costs = np.array(daily_costs, dtype=float)
    days = np.arange(len(daily_costs))
    result = scipy_stats.linregress(days, costs)
    slope = float(result.slope)
    intercept = float(result.intercept)
    stderr = float(result.stderr)

    future_days = np.arange(len(daily_costs), len(daily_costs) + horizon)
    predicted = slope * future_days + intercept
    per_day_margin = 1.96 * stderr  # same stderr applies to each daily prediction

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["day_offset", "predicted_usd", "lower_ci_95", "upper_ci_95"])
        for i, pred in enumerate(predicted):
            writer.writerow(
                [
                    i + 1,
                    round(max(0.0, float(pred)), 4),
                    round(max(0.0, float(pred) - per_day_margin), 4),
                    round(float(pred) + per_day_margin, 4),
                ]
            )

    total = float(predicted.sum())
    total_margin = 1.96 * stderr * horizon
    print(f"Forecast written to {output_path}")
    print(f"  30-day predicted total : ${total:.2f}")
    lower = max(0.0, total - total_margin)
    print(f"  95% CI                 : [${lower:.2f}, ${total + total_margin:.2f}]")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate LLM cost forecast CSV")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("results/cost_forecast.csv"),
        help="Output CSV path (default: results/cost_forecast.csv)",
    )
    parser.add_argument(
        "--horizon",
        type=int,
        default=30,
        help="Days to forecast (default: 30)",
    )
    args = parser.parse_args()
    forecast_to_csv(_SAMPLE_DAILY_COSTS, args.output, args.horizon)


if __name__ == "__main__":
    main()
