"""从 graph.py 拆出的业务实现。"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.constants import DEFAULT_REPORT_PERIOD, DEFAULT_QUERY_TYPE, TABLE_ALIASES, COMPARE_INTENTS
from agent.schemas.query_plan import normalize_compare_spec
from agent.state import AgentState
from agent.tools.company_tools import resolve_company
from agent.tools.metric_tools import load_metric_dictionary, map_metrics
from agent.tools.sql_tools import execute_financial_sql, review_sql
from db.readonly_executor import execute_readonly_sql


def analyze_derived_metric_node(state: AgentState) -> dict:
    """派生指标计算：从查询结果中提取 numerator/denominator 并计算。"""
    intent_type = state.get("intent_type") or DEFAULT_QUERY_TYPE
    if intent_type != "derived_metric_query":
        return {}

    metrics = state.get("metrics") or []
    derivative_query_results = state.get("derived_query_results")
    uses_derived_sqls = derivative_query_results is not None

    if uses_derived_sqls:
        # 多派生指标：逐条配对各 SQL 结果
        paired = list(zip(metrics, derivative_query_results))
    else:
        # 单派生指标：使用 query_result
        query_result = state.get("query_result")
        paired = [(metrics[0], query_result)] if metrics and query_result else []

    metric_dict = load_metric_dictionary()
    companies = state.get("companies") or []
    company_name = companies[0]["company_name"] if companies else ""
    report_year = state.get("report_year")

    items: list[dict[str, Any]] = []
    for derived_metric, query_result in paired:
        metric_name = derived_metric["metric_name"]
        formula = derived_metric.get("formula") or {}
        scale = derived_metric.get("scale") or 1
        precision = derived_metric.get("precision") or 2
        unit = derived_metric.get("unit") or "ratio"

        # 从当前 query_result 取值
        if not query_result or not query_result.get("success"):
            items.append({
                "metric_name": metric_name,
                "metric_key": derived_metric["metric_key"],
                "status": "missing_record",
                "value": None,
                "unit": unit,
                "formula_text": derived_metric.get("description", ""),
            })
            continue

        rows = query_result.get("rows") or []
        columns = query_result.get("columns") or []
        if not rows:
            items.append({
                "metric_name": metric_name,
                "metric_key": derived_metric["metric_key"],
                "status": "missing_record",
                "value": None,
                "unit": unit,
                "formula_text": derived_metric.get("description", ""),
            })
            continue

        data = dict(zip(columns, rows[0]))

        # 解析 numerator / denominator 对应列
        def _find_value(metric_key: str) -> float | None:
            info = metric_dict.get(metric_key)
            if not info:
                return None
            col = f"{info['table']}__{info['field']}"
            val = data.get(col)
            return float(val) if val is not None else None

        numerator_key = formula.get("numerator")
        denominator_key = formula.get("denominator")
        numerator_value = _find_value(numerator_key) if numerator_key else None
        denominator_value = _find_value(denominator_key) if denominator_key else None

        item: dict[str, Any] = {
            "metric_name": metric_name,
            "metric_key": derived_metric["metric_key"],
            "numerator_metric": metric_dict.get(numerator_key, {}).get("metric_name", ""),
            "denominator_metric": metric_dict.get(denominator_key, {}).get("metric_name", ""),
            "numerator_value": numerator_value,
            "denominator_value": denominator_value,
            "unit": unit,
            "scale": scale,
            "precision": precision,
            "formula_text": derived_metric.get("description", ""),
            "value": None,
            "status": "ok",
        }

        if numerator_value is None:
            item["status"] = "empty_numerator"
        elif denominator_value is None:
            item["status"] = "empty_denominator"
        elif denominator_value == 0:
            item["status"] = "zero_denominator"
        else:
            item["value"] = round(numerator_value / denominator_value * scale, precision)

        items.append(item)

    return {
        "derived_result": {
            "company_name": company_name,
            "report_year": report_year,
            "items": items,
        }
    }

__all__ = ['analyze_derived_metric_node']
