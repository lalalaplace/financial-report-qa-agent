"""指定公司排名位置查询分析节点。"""

from __future__ import annotations

from agent.services.sql_builders import _metric_column_alias
from agent.state import AgentState


def _format_metric_value(value: float, unit: str, precision: int = 2) -> str:
    if unit == "yuan":
        return f"{value / 100_000_000:,.2f} 亿元"
    if unit == "percent":
        return f"{value:.{precision}f}%"
    return f"{value:,.{precision}f}"


def _build_result_summary(company_name: str, rank_no: int, total_count: int) -> dict:
    """根据名次和总数生成粗粒度分位摘要。"""
    percentile = rank_no / total_count * 100
    bucket = max(10, int(((percentile + 9.9999) // 10) * 10))
    if percentile <= 25:
        zone = "前 25%"
    elif percentile >= 75:
        zone = "后 25%"
    else:
        zone = "中游"

    return {
        "company_name": company_name,
        "percentile_bucket": bucket,
        "position_zone": zone,
    }


def analyze_rank_position_node(state: AgentState) -> dict:
    query_result = state.get("query_result")
    companies = state.get("companies") or []
    metrics = state.get("metrics") or []
    metric = metrics[0] if metrics else {}
    company = companies[0] if companies else {}
    sql_metadata = state.get("sql_metadata") or {}
    rank_direction = state.get("rank_direction") or "desc"
    report_year = state.get("report_year")
    report_period = state.get("report_period") or "FY"

    base_result = {
        "analysis_type": "rank_position",
        "company_name": company.get("stock_abbr") or company.get("company_name", ""),
        "company_code": company.get("stock_code", ""),
        "metric_name": metric.get("metric_name", ""),
        "metric_type": metric.get("metric_type", "base"),
        "report_year": report_year,
        "report_period": report_period,
        "rank_direction": rank_direction,
    }

    if not query_result or not query_result.get("success"):
        return {
            "analysis_result": {
                **base_result,
                "is_empty": True,
                "empty_reason": "sql_execution_error",
                "error": (query_result or {}).get("error", "查询未执行"),
            },
            "business_success": False,
            "error_type": "sql_execution_error",
        }

    if query_result.get("row_count", 0) == 0:
        return {
            "analysis_result": {
                **base_result,
                "is_empty": True,
                "empty_reason": "target_company_not_in_ranked_result",
            },
            "business_success": False,
            "error_type": "empty_rank_position_result",
        }

    columns = query_result.get("columns", [])
    row = query_result.get("rows", [])[0]
    data = dict(zip(columns, row))

    metric_type = metric.get("metric_type", "base")
    column_alias = sql_metadata.get("column_alias") or (
        metric.get("metric_key") if metric_type == "derived" else _metric_column_alias(metric)
    )
    raw_value = data.get(column_alias)
    metric_value = None if raw_value is None else float(raw_value)
    unit = sql_metadata.get("unit") or metric.get("unit", "yuan")
    precision = int(sql_metadata.get("precision", metric.get("precision", 2)))
    if metric_value is not None and metric_type == "derived":
        metric_value = round(metric_value * float(sql_metadata.get("scale", metric.get("scale", 1))), precision)

    company_name = data.get("stock_abbr") or data.get("company_name") or base_result["company_name"]
    rank_no = int(data.get("rank_no"))
    total_count = int(data.get("total_count"))
    result = {
        **base_result,
        "company_name": company_name,
        "company_code": data.get("stock_code") or base_result["company_code"],
        "rank_no": rank_no,
        "total_count": total_count,
        "metric_value": metric_value,
        "display_value": "无有效数据" if metric_value is None else _format_metric_value(metric_value, unit, precision),
        "is_empty": False,
        "result_summary": _build_result_summary(company_name, rank_no, total_count),
    }

    if metric_type == "derived" and sql_metadata.get("formula_display"):
        result["formula_text"] = f"{metric.get('metric_name', '')} = {sql_metadata['formula_display']}"

    return {
        "analysis_result": result,
        "business_success": True,
        "error_type": None,
    }


__all__ = ["analyze_rank_position_node"]
