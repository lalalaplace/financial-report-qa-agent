"""从 graph.py 拆出的业务实现。"""

from __future__ import annotations

from typing import Any

from agent.services.compare_service import _get_compare_spec


def _format_compare_value(value: float | int | None, unit: str, precision: int = 2) -> str:
    if value is None:
        return "无有效数据"
    value_f = float(value)
    if unit == "yuan":
        return f"{value_f / 100000000:.2f} 亿元"
    if unit == "percent":
        return f"{value_f:.{precision}f}%"
    if unit == "百分点":
        return f"{value_f:.{precision}f} 个百分点"
    return f"{value_f:.{precision}f}"

def _format_abs_compare_value(value: float | int | None, unit: str, precision: int = 2) -> str:
    if value is None:
        return "无有效数据"
    return _format_compare_value(abs(float(value)), unit, precision)

def _build_compare_conclusion(
    state: dict[str, Any],
    *,
    target: str,
    winner_company: str | None,
    loser_company: str | None,
    diff: float | int | None,
    diff_unit: str | None,
) -> dict[str, Any]:
    compare_spec = _get_compare_spec(state)
    return {
        "operator": compare_spec.get("operator", "general"),
        "target": compare_spec.get("target") or target,
        "winner_company": winner_company,
        "loser_company": loser_company,
        "diff": diff,
        "diff_unit": diff_unit,
    }

__all__ = ['_format_compare_value', '_format_abs_compare_value', '_build_compare_conclusion']
