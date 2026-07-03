"""从 graph.py 拆出的业务实现。"""

from __future__ import annotations

from typing import Any

from agent.state import AgentState
from agent.tools.metric_tools import load_metric_dictionary
from db.readonly_executor import execute_readonly_sql


def _query_latest_fy_year(company: dict[str, Any], metric: dict[str, Any]) -> int | None:
    table = metric.get("table") or "balance_sheet"
    stock_code = company["stock_code"].replace("'", "''")
    sql = f"""
    SELECT report_year
    FROM {table}
    WHERE stock_code = '{stock_code}'
      AND report_period = 'FY'
    ORDER BY report_year DESC
    LIMIT 1
    """
    result = execute_readonly_sql(sql, limit=1)
    if not result["success"] or not result["rows"]:
        return None

    latest_year = result["rows"][0][0]
    if latest_year is None:
        return None
    return int(latest_year)

def _metric_for_latest_year_lookup(metric: dict[str, Any]) -> dict[str, Any]:
    """为最新年份探测选择可落地到表的基础指标。"""
    if metric.get("metric_type") != "derived":
        return metric

    formula = metric.get("formula") or {}
    numerator_key = formula.get("numerator")
    metric_dict = load_metric_dictionary()
    numerator = metric_dict.get(numerator_key) if numerator_key else None
    if numerator:
        return numerator
    return {"table": "balance_sheet"}

def _resolve_trend_year_range(state: AgentState) -> tuple[int | None, int | None]:
    """从状态解析趋势年份范围。"""
    report_years = state.get("report_years") or []
    if report_years:
        return min(report_years), max(report_years)

    time_mode = state.get("time_mode") or "recent_n"
    report_year = state.get("report_year")
    if time_mode == "explicit_range":
        return state.get("start_year"), state.get("end_year")

    recent_n = state.get("recent_n_years") or 5
    end_year = report_year
    start_year = end_year - recent_n + 1 if end_year else None
    return start_year, end_year

def _resolve_trend_years(state: AgentState) -> list[int]:
    """优先使用准入节点确认过的 report_years。"""
    report_years = state.get("report_years") or []
    if report_years:
        return sorted(int(year) for year in report_years)

    start_year, end_year = _resolve_trend_year_range(state)
    if start_year is None or end_year is None:
        return []
    return list(range(start_year, end_year + 1))

def _years_union_sql(report_years: list[int]) -> str:
    """生成确定年份集合，避免某公司缺年导致结果行消失。"""
    return "\n        UNION ALL\n        ".join(
        f"SELECT {year} AS report_year" for year in report_years
    )

__all__ = ['_query_latest_fy_year', '_metric_for_latest_year_lookup', '_resolve_trend_year_range', '_resolve_trend_years', '_years_union_sql']
