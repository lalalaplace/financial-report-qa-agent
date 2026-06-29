"""排名分析节点（V0.5.2）。

将 query_result 转换为结构化的 ranking analysis_result。
统一 rows 结构，limit=1 不特殊处理。
"""

from __future__ import annotations

from typing import Any

from agent.state import AgentState
from agent.services.sql_builders import _metric_column_alias


def _format_metric_value(value: float, unit: str) -> str:
    """根据指标单位格式化展示值。"""
    if unit == "yuan":
        value_yi = value / 100_000_000
        return f"{value_yi:,.2f} 亿元"
    elif unit == "percent":
        return f"{value:.2f}%"
    else:
        return f"{value:,.2f}"


def _format_gap_value(value: float, unit: str) -> str:
    """格式化第一名和第二名的差距。"""
    if unit == "percent":
        return f"{value:.2f} 个百分点"
    return _format_metric_value(value, unit)


def _safe_ratio(numerator: float, denominator: float) -> float | None:
    """计算相对比例，分母为 0 时返回空值。"""
    if denominator == 0:
        return None
    return numerator / abs(denominator)


def _build_empty_result(metric: dict, report_year, rank_direction, limit) -> dict:
    return {
        "analysis_type": "ranking",
        "metric_name": metric.get("metric_name", ""),
        "metric_type": metric.get("metric_type", "base"),
        "report_year": report_year,
        "rank_direction": rank_direction,
        "limit": limit,
        "row_count": 0,
        "is_empty": True,
        "rows": [],
    }


def _build_result_summary(
    metric_name: str,
    unit: str,
    rows: list[dict[str, Any]],
    rank_direction: str,
) -> dict[str, Any]:
    """基于已返回的 TopN 行生成排名摘要。"""
    values = [row.get("metric_value") for row in rows if row.get("metric_value") is not None]
    if not rows or not values:
        return {}

    first = rows[0]
    first_value = first.get("metric_value")
    summary: dict[str, Any] = {
        "first_company_name": first.get("company_name", ""),
        "first_display_value": first.get("display_value", "—"),
        "first_rank_label": "排名第一" if rank_direction == "desc" else "排名第一（数值最低）",
        "average_label": f"平均{metric_name}",
        "average_display_value": _format_metric_value(sum(values) / len(values), unit),
        "topn_count": len(rows),
    }

    if len(rows) >= 2 and first_value is not None and rows[1].get("metric_value") is not None:
        second_value = rows[1]["metric_value"]
        if rank_direction == "asc":
            gap = second_value - first_value
            compare_word = "低"
        else:
            gap = first_value - second_value
            compare_word = "高"

        summary.update(
            {
                "second_company_name": rows[1].get("company_name", ""),
                "gap_compare_word": compare_word,
                "gap_display_value": _format_gap_value(gap, unit),
                "gap_ratio_display": None,
            }
        )
        if unit != "percent":
            gap_ratio = _safe_ratio(gap, second_value)
            if gap_ratio is not None:
                summary["gap_ratio_display"] = f"{gap_ratio * 100:.2f}%"

    return summary


def analyze_ranking_node(state: AgentState) -> dict:
    """排名分析：将 SQL 查询结果转换为带排名的结构化分析结果。"""
    query_result = state.get("query_result")
    metrics = state.get("metrics") or []
    rank_direction = state.get("rank_direction") or "desc"
    limit = state.get("limit") or 10
    report_year = state.get("report_year")
    report_period = state.get("report_period") or "FY"

    metric = metrics[0] if metrics else {}
    metric_name = metric.get("metric_name", "")
    metric_type = metric.get("metric_type", "base")

    # ── 查询失败 ──
    if not query_result or not query_result.get("success"):
        return {
            "analysis_result": {
                "analysis_type": "ranking",
                "metric_name": metric_name,
                "metric_type": metric_type,
                "report_year": report_year,
                "rank_direction": rank_direction,
                "limit": limit,
                "row_count": 0,
                "is_empty": True,
                "rows": [],
                "error": (query_result or {}).get("error", "查询未执行"),
            },
            "business_success": False,
            "error_type": "sql_execution_error",
        }

    # ── 空结果 ──
    if query_result.get("row_count", 0) == 0:
        return {
            "analysis_result": _build_empty_result(metric, report_year, rank_direction, limit),
            "business_success": False,
            "error_type": "empty_ranking_result",
        }

    rows = query_result["rows"]
    columns = query_result["columns"]

    metric_key = metric.get("metric_key", "")
    unit = metric.get("unit", "yuan")

    sql_metadata = state.get("sql_metadata") or {}
    column_alias = sql_metadata.get("column_alias") or _metric_column_alias(metric)

    # 派生指标：SQL 存原始比率，analysis 层统一乘 scale
    derived_scale = sql_metadata.get("scale", 1) if metric_type == "derived" else 1
    derived_precision = sql_metadata.get("precision", 2) if metric_type == "derived" else 2

    # ── 构建 rows ──
    result_rows: list[dict[str, Any]] = []
    for idx, row in enumerate(rows):
        data = dict(zip(columns, row))
        raw_value = data.get(column_alias)

        if raw_value is None:
            display_value = "—"
            metric_value = None
        else:
            raw_float = float(raw_value)
            if metric_type == "derived":
                metric_value = round(raw_float * derived_scale, derived_precision)
            else:
                metric_value = raw_float
            display_value = _format_metric_value(metric_value, unit)

        result_rows.append({
            "rank": idx + 1,
            "stock_code": data.get("stock_code", ""),
            "company_name": data.get("company_name", ""),
            "metric_value": metric_value,
            "display_value": display_value,
        })

    return {
        "analysis_result": {
            "analysis_type": "ranking",
            "metric_name": metric_name,
            "metric_key": metric_key,
            "metric_type": metric_type,
            "report_year": report_year,
            "report_period": report_period,
            "rank_direction": rank_direction,
            "limit": limit,
            "row_count": len(result_rows),
            "is_empty": False,
            "rows": result_rows,
            "result_summary": _build_result_summary(metric_name, unit, result_rows, rank_direction),
        },
        "business_success": True,
        "error_type": None,
    }


__all__ = ["analyze_ranking_node"]
