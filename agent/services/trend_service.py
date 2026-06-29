"""从 graph.py 拆出的业务实现。"""

from __future__ import annotations

from typing import Any

from agent.services.compare_service import _get_compare_spec
from agent.utils.formatters import _build_compare_conclusion


def _trend_conclusion_payload(
    state: dict[str, Any],
    result: dict[str, Any],
    *,
    diff_unit: str,
) -> dict[str, Any]:
    operator = _get_compare_spec(state).get("operator", "general")
    if operator == "larger_decline":
        target = "absolute_change"
        winner = result.get("largest_decline")
        loser = None
    elif operator in {"larger_change", "faster_growth"}:
        target = "absolute_change"
        winner = result.get("larger_metric_change") or result.get("largest_absolute_change_company")
        loser = None
    else:
        target = "latest_value"
        winner = result.get("latest_year_winner_company") or result.get("latest_higher")
        loser = result.get("latest_lower")
    return _build_compare_conclusion(
        state,
        target=target,
        winner_company=winner,
        loser_company=loser,
        diff=None,
        diff_unit=diff_unit,
    )

def _summarize_trend_series(
    series: list[dict[str, Any]],
    *,
    precision: int,
) -> dict[str, Any]:
    valid_points = [
        item for item in series
        if item.get("status") == "ok" and item.get("value") is not None
    ]
    valid_values = [float(item["value"]) for item in valid_points]

    start_value = valid_values[0] if valid_values else None
    end_value = valid_values[-1] if len(valid_values) >= 2 else None
    if len(valid_values) == 0:
        status = "no_valid_points"
        trend_direction = "insufficient_points"
    elif len(valid_values) == 1:
        status = "insufficient_points"
        trend_direction = "insufficient_points"
    elif end_value > start_value:
        status = "ok"
        trend_direction = "up"
    elif end_value < start_value:
        status = "ok"
        trend_direction = "down"
    else:
        status = "ok"
        trend_direction = "flat"
    change_abs = (
        round(end_value - start_value, precision)
        if start_value is not None and end_value is not None
        else None
    )
    change_rate = (
        round(change_abs / abs(start_value), 4)
        if change_abs is not None and start_value != 0
        else None
    )

    return {
        "status": status,
        "valid_points": len(valid_values),
        "first_year": valid_points[0]["year"] if valid_points else None,
        "last_year": valid_points[-1]["year"] if valid_points else None,
        "first_value": start_value,
        "last_value": end_value,
        "absolute_change": change_abs,
        "change_rate": change_rate,
        "trend_direction": trend_direction,
    }

def _infer_trend_direction(values: list[float]) -> str:
    """推断趋势方向：基于有效值的逐期变化。"""
    if len(values) < 2:
        return "insufficient_points"
    diffs = [values[i] - values[i - 1] for i in range(1, len(values))]
    if all(d >= 0 for d in diffs):
        return "up"
    if all(d <= 0 for d in diffs):
        return "down"
    start, end = values[0], values[-1]
    if end > start:
        return "fluctuating_up"
    if end < start:
        return "fluctuating_down"
    return "fluctuating_flat"

__all__ = ['_trend_conclusion_payload', '_summarize_trend_series', '_infer_trend_direction']
