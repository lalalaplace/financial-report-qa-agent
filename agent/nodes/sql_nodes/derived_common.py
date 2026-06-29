"""派生指标 SQL 公共函数。"""

from __future__ import annotations

from typing import Any

from agent.constants import TABLE_ALIASES


def resolve_derived_formula(
    derived_metric: dict[str, Any],
    metric_dict: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """解析派生指标公式，返回 (num_info, den_info) 或 None。"""
    formula = derived_metric.get("formula") or {}
    numerator_key = formula.get("numerator")
    denominator_key = formula.get("denominator")
    num_info = metric_dict.get(numerator_key) if numerator_key else None
    den_info = metric_dict.get(denominator_key) if denominator_key else None
    if not num_info or not den_info:
        return None
    return num_info, den_info


def resolve_derived_tables(
    num_info: dict[str, Any],
    den_info: dict[str, Any],
) -> tuple[str, str, str, str] | None:
    """解析表别名，返回 (num_table, den_table, num_alias, den_alias) 或 None。"""
    num_table = num_info["table"]
    den_table = den_info["table"]
    unknown = sorted(set([num_table, den_table]) - set(TABLE_ALIASES))
    if unknown:
        return None
    return num_table, den_table, TABLE_ALIASES[num_table], TABLE_ALIASES[den_table]


def stock_codes_str(companies: list[dict[str, Any]]) -> str:
    codes = [c["stock_code"].replace("'", "''") for c in companies]
    return ", ".join(f"'{code}'" for code in codes)
