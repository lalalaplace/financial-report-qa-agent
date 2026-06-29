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

from agent.services.sql_builders import _metric_column_alias


def analyze_yoy_node(state: AgentState) -> dict:
    """同比分析：从查询结果中提取当年/上年值，计算同比变化。

    非 yoy_query 时透传空返回。
    """
    intent_type = state.get("intent_type") or DEFAULT_QUERY_TYPE
    if intent_type != "yoy_query":
        return {}

    query_result = state.get("query_result")
    if not query_result or not query_result["success"] or query_result["row_count"] == 0:
        return {"yoy_result": None}

    rows = query_result["rows"]
    columns = query_result["columns"]
    metrics = state.get("metrics") or []
    report_year = state.get("report_year")
    prev_year = report_year - 1 if report_year is not None else None

    companies = state.get("companies") or []
    company_name = companies[0]["company_name"] if companies else ""

    items: list[dict[str, Any]] = []
    for metric in metrics:
        column_alias = _metric_column_alias(metric)

        current_year_exists = False
        previous_year_exists = False
        current_value = None
        previous_value = None

        for row in rows:
            data = dict(zip(columns, row))
            row_year = data.get("report_year")
            value = data.get(column_alias)
            if row_year == report_year:
                current_year_exists = True
                if value is not None:
                    current_value = float(value)
            elif row_year == prev_year:
                previous_year_exists = True
                if value is not None:
                    previous_value = float(value)

        item: dict[str, Any] = {
            "metric_name": metric["metric_name"],
            "table": metric["table"],
            "field": metric["field"],
            "current_value": current_value,
            "previous_value": previous_value,
            "change_abs": None,
            "yoy_rate": None,
            "status": "ok",
        }

        if not current_year_exists:
            item["status"] = "missing_current_year"
        elif current_value is None:
            item["status"] = "empty_current_value"
        elif not previous_year_exists:
            item["status"] = "missing_previous_year"
        elif previous_value is None:
            item["status"] = "empty_previous_value"
        elif previous_value == 0:
            item["status"] = "zero_previous_value"
            item["change_abs"] = current_value
        else:
            item["change_abs"] = round(current_value - previous_value, 2)
            item["yoy_rate"] = round(item["change_abs"] / abs(previous_value), 4)

        items.append(item)

    return {
        "yoy_result": {
            "company_name": company_name,
            "report_year": report_year,
            "previous_year": prev_year,
            "items": items,
        }
    }

def analyze_derived_yoy_node(state: AgentState) -> dict:
    """派生指标同比分析：基于 derived_yoy_query_results 分离当年/上年数据，计算派生值及同比变化。

    状态枚举（优先级从高到低）：
    - sql_error: SQL执行失败
    - empty_result: SQL成功但无数据
    - missing_current_year: 缺当年行
    - missing_previous_year: 缺上年行
    - empty_numerator_current / empty_numerator_previous: 分子为NULL
    - empty_denominator_current / empty_denominator_previous: 分母为NULL
    - zero_denominator_current / zero_denominator_previous: 分母为0
    - ok: 正常计算成功
    """
    intent_type = state.get("intent_type") or DEFAULT_QUERY_TYPE
    if intent_type != "yoy_query":
        return {}

    metrics = state.get("metrics") or []
    metric_types = {m.get("metric_type", "base") for m in metrics}
    if metric_types != {"derived"}:
        return {}

    dy_results = state.get("derived_yoy_query_results") or {}
    metric_dict = load_metric_dictionary()
    companies = state.get("companies") or []
    company_name = companies[0].get("company_name", "") if companies else ""
    report_year = state.get("report_year")
    prev_year = report_year - 1 if report_year is not None else None

    items: list[dict[str, Any]] = []

    for derived_metric in metrics:
        metric_key = derived_metric["metric_key"]
        metric_name = derived_metric["metric_name"]
        unit = derived_metric.get("unit", "ratio")
        scale = derived_metric.get("scale") or 1
        precision = derived_metric.get("precision", 2)
        formula = derived_metric.get("formula") or {}
        numerator_key = formula.get("numerator")
        denominator_key = formula.get("denominator")

        num_metric_name = metric_dict.get(numerator_key, {}).get("metric_name", "")
        den_metric_name = metric_dict.get(denominator_key, {}).get("metric_name", "")
        formula_text = derived_metric.get("description", "")

        entry = dy_results.get(metric_key)

        # 1. 基础校验
        if not entry or not entry.get("sql_success"):
            items.append({
                "metric_key": metric_key,
                "metric_name": metric_name,
                "unit": unit,
                "formula_text": formula_text,
                "numerator_metric": num_metric_name,
                "denominator_metric": den_metric_name,
                "current_value": None,
                "previous_value": None,
                "change_abs": None,
                "yoy_rate": None,
                "status": "sql_error",
            })
            continue

        if entry.get("row_count", 0) == 0:
            items.append({
                "metric_key": metric_key,
                "metric_name": metric_name,
                "unit": unit,
                "formula_text": formula_text,
                "numerator_metric": num_metric_name,
                "denominator_metric": den_metric_name,
                "current_value": None,
                "previous_value": None,
                "change_abs": None,
                "yoy_rate": None,
                "status": "empty_result",
            })
            continue

        rows = entry["rows"]
        columns = entry["columns"]

        # 2. 分离当年/上年行
        current_row = None
        previous_row = None
        for row in rows:
            data = dict(zip(columns, row))
            yr = data.get("report_year")
            if yr == report_year:
                current_row = data
            elif yr == prev_year:
                previous_row = data

        # 3. 安全提取数值
        def _safe_float(data: dict | None, col: str) -> float | None:
            if data is None:
                return None
            val = data.get(col)
            return float(val) if val is not None else None

        cur_num = _safe_float(current_row, "numerator_value")
        cur_den = _safe_float(current_row, "denominator_value")
        prev_num = _safe_float(previous_row, "numerator_value")
        prev_den = _safe_float(previous_row, "denominator_value")

        item: dict[str, Any] = {
            "metric_key": metric_key,
            "metric_name": metric_name,
            "unit": unit,
            "precision": precision,
            "formula_text": formula_text,
            "numerator_metric": num_metric_name,
            "denominator_metric": den_metric_name,
            "current_numerator": cur_num,
            "current_denominator": cur_den,
            "previous_numerator": prev_num,
            "previous_denominator": prev_den,
            "current_value": None,
            "previous_value": None,
            "change_abs": None,
            "yoy_rate": None,
            "status": "ok",
        }

        # 4. 状态判定
        if current_row is None:
            item["status"] = "missing_current_year"
        elif previous_row is None:
            item["status"] = "missing_previous_year"
        elif cur_num is None:
            item["status"] = "empty_numerator_current"
        elif prev_num is None:
            item["status"] = "empty_numerator_previous"
        elif cur_den is None:
            item["status"] = "empty_denominator_current"
        elif prev_den is None:
            item["status"] = "empty_denominator_previous"
        elif cur_den == 0:
            item["status"] = "zero_denominator_current"
        elif prev_den == 0:
            item["status"] = "zero_denominator_previous"
        else:
            # 5. 分别计算当年和上年的派生指标值
            current_derived = round(cur_num / cur_den * scale, precision)
            previous_derived = round(prev_num / prev_den * scale, precision)
            item["current_value"] = current_derived
            item["previous_value"] = previous_derived

            change_abs = round(current_derived - previous_derived, precision)
            item["change_abs"] = change_abs

            if previous_derived != 0:
                item["yoy_rate"] = round(change_abs / abs(previous_derived), 4)
            else:
                item["yoy_rate"] = None

        items.append(item)

    return {
        "derived_yoy_result": {
            "company_name": company_name,
            "report_year": report_year,
            "previous_year": prev_year,
            "items": items,
        },
    }

__all__ = ['analyze_yoy_node', 'analyze_derived_yoy_node']
