"""区间增长排名查询分析节点。"""

from __future__ import annotations

from typing import Any

from agent.nodes.analyze_nodes.ranking_analysis import _format_metric_value
from agent.state import AgentState


def _format_growth_rate(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value * 100:.2f}%"


def _build_result_summary(rows: list[dict[str, Any]], rank_direction: str) -> dict[str, Any]:
    """基于已返回的 TopN 行生成区间增长排名摘要。"""
    rates = [row.get("growth_rate") for row in rows if row.get("growth_rate") is not None]
    if not rows or not rates:
        return {}

    first = rows[0]
    summary: dict[str, Any] = {
        "first_company_name": first.get("company_name", ""),
        "first_rate_display": _format_growth_rate(first.get("growth_rate")),
        "first_rank_label": "区间增长率最高" if rank_direction == "desc" else "区间下降最大或增长率最低",
        "average_label": "平均区间增长率" if rank_direction == "desc" else "平均区间变化率",
        "average_rate_display": _format_growth_rate(sum(rates) / len(rates)),
        "topn_count": len(rows),
        "positive_count": sum(1 for value in rates if value > 0),
        "negative_count": sum(1 for value in rates if value < 0),
    }

    if len(rows) >= 2 and first.get("growth_rate") is not None and rows[1].get("growth_rate") is not None:
        summary.update(
            {
                "second_company_name": rows[1].get("company_name", ""),
                "gap_compare_word": "高" if rank_direction == "desc" else "低",
                "gap_percentage_points": f"{abs(first['growth_rate'] - rows[1]['growth_rate']) * 100:.2f}",
            }
        )

    return summary


def _build_empty_result(metric: dict, state: AgentState) -> dict:
    return {
        "analysis_type": "trend_ranking",
        "metric_name": metric.get("metric_name", ""),
        "metric_type": metric.get("metric_type", "base"),
        "start_year": state.get("start_year"),
        "end_year": state.get("end_year"),
        "report_period": state.get("report_period") or "FY",
        "rank_direction": state.get("rank_direction") or "desc",
        "limit": state.get("limit") or 10,
        "change_metric": "growth_rate",
        "row_count": 0,
        "is_empty": True,
        "rows": [],
    }


def analyze_trend_ranking_node(state: AgentState) -> dict:
    query_result = state.get("query_result")
    metrics = state.get("metrics") or []
    metric = metrics[0] if metrics else {}

    if not query_result or not query_result.get("success"):
        result = _build_empty_result(metric, state)
        result["error"] = (query_result or {}).get("error", "查询未执行")
        return {
            "analysis_result": result,
            "business_success": False,
            "error_type": "sql_execution_error",
        }

    if query_result.get("row_count", 0) == 0:
        return {
            "analysis_result": _build_empty_result(metric, state),
            "business_success": False,
            "error_type": "empty_trend_ranking_result",
        }

    columns = query_result["columns"]
    rows = query_result["rows"]
    unit = metric.get("unit", "yuan")

    result_rows: list[dict[str, Any]] = []
    for idx, row in enumerate(rows):
        data = dict(zip(columns, row))
        start_value = data.get("start_value")
        end_value = data.get("end_value")
        growth_rate = data.get("growth_rate")

        start_float = float(start_value) if start_value is not None else None
        end_float = float(end_value) if end_value is not None else None
        growth_float = float(growth_rate) if growth_rate is not None else None

        result_rows.append(
            {
                "rank": idx + 1,
                "stock_code": data.get("stock_code", ""),
                "company_name": data.get("company_name", ""),
                "start_value": start_float,
                "end_value": end_float,
                "growth_rate": growth_float,
                "display_growth_rate": _format_growth_rate(growth_float),
                "display_start_value": (
                    _format_metric_value(start_float, unit) if start_float is not None else "—"
                ),
                "display_end_value": (
                    _format_metric_value(end_float, unit) if end_float is not None else "—"
                ),
            }
        )

    return {
        "analysis_result": {
            "analysis_type": "trend_ranking",
            "metric_name": metric.get("metric_name", ""),
            "metric_key": metric.get("metric_key", ""),
            "metric_type": metric.get("metric_type", "base"),
            "start_year": state.get("start_year"),
            "end_year": state.get("end_year"),
            "report_period": state.get("report_period") or "FY",
            "rank_direction": state.get("rank_direction") or "desc",
            "limit": state.get("limit") or 10,
            "change_metric": "growth_rate",
            "row_count": len(result_rows),
            "is_empty": False,
            "rows": result_rows,
            "result_summary": _build_result_summary(result_rows, state.get("rank_direction") or "desc"),
        },
        "business_success": True,
        "error_type": None,
    }


__all__ = ["analyze_trend_ranking_node"]
