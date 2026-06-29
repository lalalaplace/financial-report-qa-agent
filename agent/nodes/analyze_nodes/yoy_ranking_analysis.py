"""同比排名查询分析节点。"""

from __future__ import annotations

from typing import Any

from agent.nodes.analyze_nodes.ranking_analysis import _format_metric_value
from agent.state import AgentState


def _format_yoy_rate(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value * 100:.2f}%"


def _build_result_summary(rows: list[dict[str, Any]], rank_direction: str) -> dict[str, Any]:
    """基于已返回的 TopN 行生成同比排名摘要。"""
    rates = [row.get("yoy_rate") for row in rows if row.get("yoy_rate") is not None]
    if not rows or not rates:
        return {}

    first = rows[0]
    summary: dict[str, Any] = {
        "first_company_name": first.get("company_name", ""),
        "first_rate_display": _format_yoy_rate(first.get("yoy_rate")),
        "first_rank_label": "同比增速最高" if rank_direction == "desc" else "同比下降最大或增速最低",
        "average_label": "平均同比增速" if rank_direction == "desc" else "平均同比变化率",
        "average_rate_display": _format_yoy_rate(sum(rates) / len(rates)),
        "topn_count": len(rows),
        "positive_count": sum(1 for value in rates if value > 0),
        "negative_count": sum(1 for value in rates if value < 0),
    }

    if len(rows) >= 2 and first.get("yoy_rate") is not None and rows[1].get("yoy_rate") is not None:
        summary.update(
            {
                "second_company_name": rows[1].get("company_name", ""),
                "gap_compare_word": "高" if rank_direction == "desc" else "低",
                "gap_percentage_points": f"{abs(first['yoy_rate'] - rows[1]['yoy_rate']) * 100:.2f}",
            }
        )

    return summary


def _build_empty_result(metric: dict, state: AgentState) -> dict:
    return {
        "analysis_type": "yoy_ranking",
        "metric_name": metric.get("metric_name", ""),
        "metric_type": metric.get("metric_type", "base"),
        "report_year": state.get("report_year"),
        "previous_year": (state.get("report_year") - 1) if state.get("report_year") else None,
        "report_period": state.get("report_period") or "FY",
        "rank_direction": state.get("rank_direction") or "desc",
        "limit": state.get("limit") or 10,
        "change_metric": "yoy_rate",
        "row_count": 0,
        "is_empty": True,
        "rows": [],
    }


def analyze_yoy_ranking_node(state: AgentState) -> dict:
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
            "error_type": "empty_yoy_ranking_result",
        }

    columns = query_result["columns"]
    rows = query_result["rows"]
    unit = metric.get("unit", "yuan")

    result_rows: list[dict[str, Any]] = []
    for idx, row in enumerate(rows):
        data = dict(zip(columns, row))
        current_value = data.get("current_value")
        previous_value = data.get("previous_value")
        yoy_rate = data.get("yoy_rate")

        current_float = float(current_value) if current_value is not None else None
        previous_float = float(previous_value) if previous_value is not None else None
        yoy_float = float(yoy_rate) if yoy_rate is not None else None

        result_rows.append(
            {
                "rank": idx + 1,
                "stock_code": data.get("stock_code", ""),
                "company_name": data.get("company_name", ""),
                "current_value": current_float,
                "previous_value": previous_float,
                "yoy_rate": yoy_float,
                "display_yoy_rate": _format_yoy_rate(yoy_float),
                "display_current_value": (
                    _format_metric_value(current_float, unit) if current_float is not None else "—"
                ),
                "display_previous_value": (
                    _format_metric_value(previous_float, unit) if previous_float is not None else "—"
                ),
            }
        )

    report_year = state.get("report_year")
    return {
        "analysis_result": {
            "analysis_type": "yoy_ranking",
            "metric_name": metric.get("metric_name", ""),
            "metric_key": metric.get("metric_key", ""),
            "metric_type": metric.get("metric_type", "base"),
            "report_year": report_year,
            "previous_year": report_year - 1 if report_year else None,
            "report_period": state.get("report_period") or "FY",
            "rank_direction": state.get("rank_direction") or "desc",
            "limit": state.get("limit") or 10,
            "change_metric": "yoy_rate",
            "row_count": len(result_rows),
            "is_empty": False,
            "rows": result_rows,
            "result_summary": _build_result_summary(result_rows, state.get("rank_direction") or "desc"),
        },
        "business_success": True,
        "error_type": None,
    }


__all__ = ["analyze_yoy_ranking_node"]
