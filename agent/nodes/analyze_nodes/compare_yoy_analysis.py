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

from agent.services.compare_service import _get_compare_spec
from agent.utils.formatters import _build_compare_conclusion


def analyze_compare_yoy_node(state: AgentState) -> dict:
    """base 指标多公司同比对比分析。

    对每个公司 × 指标计算同比：absolute_change、yoy_rate。
    状态码：ok / missing_current / missing_previous / empty_current / empty_previous / zero_previous
    """
    intent_type = state.get("intent_type") or DEFAULT_QUERY_TYPE
    if intent_type != "company_compare_yoy_query":
        return {}

    query_results = state.get("compare_yoy_query_results") or []
    companies = state.get("companies") or []
    metrics = [m for m in (state.get("metrics") or []) if m.get("metric_type") != "derived"]
    report_year = state.get("report_year")
    prev_year = report_year - 1 if report_year is not None else None
    report_period = state.get("report_period") or DEFAULT_REPORT_PERIOD

    if not query_results or not companies or not metrics or report_year is None:
        return {"compare_yoy_result": []}

    company_lookup: dict[str, str] = {}
    for c in companies:
        code = c.get("stock_code", "")
        company_lookup[code] = c.get("company_name") or c.get("stock_abbr", code)

    metric_data: dict[str, dict[str, Any]] = {}
    for m in metrics:
        mk = m["metric_key"]
        metric_data[mk] = {
            "metric_key": mk,
            "metric_name": m["metric_name"],
            "unit": m.get("unit", "yuan"),
            "column": f"{m['table']}__{m['field']}",
            "values": {code: {} for code in company_lookup},
        }

    for cr in query_results:
        if not cr.get("success"):
            continue
        cr_columns = cr.get("columns", [])
        for row in cr.get("rows", []):
            data = dict(zip(cr_columns, row))
            code = data.get("stock_code", "")
            year = data.get("report_year")
            if code not in company_lookup or year is None:
                continue
            for mk, md in metric_data.items():
                col = md["column"]
                if col in data:
                    md["values"][code][int(year)] = data[col]

    compare_yoy_result: list[dict[str, Any]] = []
    for mk, md in metric_data.items():
        company_items: list[dict[str, Any]] = []
        ok_count = 0

        for code, name in company_lookup.items():
            year_values = md["values"][code]
            current_val = year_values.get(report_year)
            prev_val = year_values.get(prev_year)

            current_exists = report_year in year_values
            prev_exists = prev_year in year_values

            item: dict[str, Any] = {
                "company_id": code,
                "company_name": name,
                "current_value": float(current_val) if current_val is not None else None,
                "previous_value": float(prev_val) if prev_val is not None else None,
                "absolute_change": None,
                "yoy_rate": None,
                "status": "ok",
                "warning": None,
            }

            if not current_exists:
                item["status"] = "missing_current"
            elif current_val is None:
                item["status"] = "empty_current"
            elif not prev_exists:
                item["status"] = "missing_previous"
            elif prev_val is None:
                item["status"] = "empty_previous"
            elif float(prev_val) == 0:
                item["status"] = "zero_previous"
                item["absolute_change"] = round(float(current_val), 2)
            else:
                current_f = float(current_val)
                prev_f = float(prev_val)
                item["absolute_change"] = round(current_f - prev_f, 2)
                item["yoy_rate"] = round(item["absolute_change"] / abs(prev_f), 4)
                if prev_f < 0:
                    item["warning"] = "negative_previous_value"
                ok_count += 1

            company_items.append(item)

        # 汇总
        ok_items = [it for it in company_items if it["status"] == "ok"]

        if ok_count == 0:
            metric_status = "compare_yoy_unavailable"
        elif ok_count < len(company_items):
            metric_status = "partial_compare_yoy_unavailable"
        else:
            metric_status = "ok"

        winner_company = None
        loser_company = None
        larger_metric_change = None
        max_yoy_rate = None
        min_yoy_rate = None
        diff_yoy_rate = None

        # 仅全部 ok 时计算 winner，避免部分缺失误导
        if metric_status == "ok" and ok_items and len(ok_items) >= 2:
            best = max(ok_items, key=lambda x: x["yoy_rate"]
                       if x["yoy_rate"] is not None else float("-inf"))
            worst = min(ok_items, key=lambda x: x["yoy_rate"]
                        if x["yoy_rate"] is not None else float("inf"))
            largest_change = max(ok_items, key=lambda x: abs(x["absolute_change"])
                                 if x["absolute_change"] is not None else float("-inf"))
            winner_company = best["company_name"]
            loser_company = worst["company_name"]
            larger_metric_change = largest_change["company_name"]
            max_yoy_rate = best["yoy_rate"]
            min_yoy_rate = worst["yoy_rate"]
            if max_yoy_rate is not None and min_yoy_rate is not None:
                diff_yoy_rate = round(max_yoy_rate - min_yoy_rate, 4)

        compare_yoy_result.append({
            "metric_key": mk,
            "metric_name": md["metric_name"],
            "metric_type": "base",
            "unit": md["unit"],
            "current_year": report_year,
            "previous_year": prev_year,
            "period": report_period,
            "items": company_items,
            "winner_company": winner_company,
            "higher_yoy": winner_company,
            "lower_yoy": loser_company,
            "larger_metric_change": larger_metric_change,
            "max_yoy_rate": max_yoy_rate,
            "min_yoy_rate": min_yoy_rate,
            "diff_yoy_rate": diff_yoy_rate,
            "diff_unit": "百分点",
            "status": metric_status,
            "compare_spec": _get_compare_spec(state),
            "conclusion": _build_compare_conclusion(
                state,
                target="yoy_rate",
                winner_company=winner_company,
                loser_company=loser_company,
                diff=diff_yoy_rate,
                diff_unit="百分点",
            ),
        })

    return {"compare_yoy_result": compare_yoy_result}

def analyze_derived_compare_yoy_node(state: AgentState) -> dict:
    """派生指标多公司同比对比分析。

    先计算每年派生值，再计算同比变化。
    percent 单位的 absolute_change 为百分点。
    状态码：ok / missing_current_record / missing_previous_record /
            empty_current_numerator / empty_current_denominator /
            empty_previous_numerator / empty_previous_denominator /
            zero_current_denominator / zero_previous_denominator
    """
    intent_type = state.get("intent_type") or DEFAULT_QUERY_TYPE
    if intent_type != "company_compare_yoy_query":
        return {}

    query_results = state.get("derived_compare_yoy_query_results") or {}
    companies = state.get("companies") or []
    metrics = [m for m in (state.get("metrics") or []) if m.get("metric_type") == "derived"]
    report_year = state.get("report_year")
    prev_year = report_year - 1 if report_year is not None else None
    report_period = state.get("report_period") or DEFAULT_REPORT_PERIOD

    if not query_results or not companies or not metrics or report_year is None:
        return {"derived_compare_yoy_result": []}

    company_lookup: dict[str, str] = {}
    for c in companies:
        code = c.get("stock_code", "")
        company_lookup[code] = c.get("company_name") or c.get("stock_abbr", code)

    derived_compare_yoy_result: list[dict[str, Any]] = []
    for metric in metrics:
        mk = metric["metric_key"]
        unit = metric.get("unit", "ratio")
        scale = metric.get("scale", 1)
        precision = metric.get("precision", 2)
        change_unit = "百分点" if unit == "percent" else unit

        entry = query_results.get(mk)
        company_items: list[dict[str, Any]] = []
        ok_count = 0

        rows_by_company_year: dict[str, dict[int, dict[str, Any]]] = {
            code: {} for code in company_lookup
        }
        if entry and entry.get("sql_success") and entry.get("row_count", 0) > 0:
            columns = entry.get("columns", [])
            for row in entry.get("rows", []):
                data = dict(zip(columns, row))
                code = data.get("stock_code")
                year = data.get("report_year")
                if code in company_lookup and year is not None:
                    rows_by_company_year[code][int(year)] = data

        for code, name in company_lookup.items():
            curr_data = rows_by_company_year[code].get(report_year, {})
            prev_data = rows_by_company_year[code].get(prev_year, {})

            item: dict[str, Any] = {
                "company_id": code,
                "company_name": name,
                "previous_numerator": None,
                "previous_denominator": None,
                "previous_value": None,
                "current_numerator": None,
                "current_denominator": None,
                "current_value": None,
                "absolute_change": None,
                "change_unit": change_unit,
                "status": "ok",
            }

            curr_num = curr_data.get("numerator_value")
            curr_den = curr_data.get("denominator_value")
            prev_num = prev_data.get("numerator_value")
            prev_den = prev_data.get("denominator_value")

            if not curr_data:
                item["status"] = "missing_current_record"
            elif curr_num is None:
                item["status"] = "empty_current_numerator"
            elif curr_den is None:
                item["status"] = "empty_current_denominator"
            elif float(curr_den) == 0:
                item["status"] = "zero_current_denominator"
                item["current_numerator"] = float(curr_num)
                item["current_denominator"] = float(curr_den)
            elif not prev_data:
                item["status"] = "missing_previous_record"
            elif prev_num is None:
                item["status"] = "empty_previous_numerator"
            elif prev_den is None:
                item["status"] = "empty_previous_denominator"
            elif float(prev_den) == 0:
                item["status"] = "zero_previous_denominator"
                item["current_numerator"] = float(curr_num)
                item["current_denominator"] = float(curr_den)
                item["current_value"] = round(float(curr_num) / float(curr_den) * scale, precision)
                item["previous_numerator"] = float(prev_num)
                item["previous_denominator"] = float(prev_den)
            else:
                item["current_numerator"] = float(curr_num)
                item["current_denominator"] = float(curr_den)
                item["previous_numerator"] = float(prev_num)
                item["previous_denominator"] = float(prev_den)
                item["current_value"] = round(float(curr_num) / float(curr_den) * scale, precision)
                item["previous_value"] = round(float(prev_num) / float(prev_den) * scale, precision)
                item["absolute_change"] = round(
                    item["current_value"] - item["previous_value"], precision
                )
                ok_count += 1

            company_items.append(item)

        # 汇总
        ok_items = [it for it in company_items if it["status"] == "ok"]

        if ok_count == 0:
            metric_status = "derived_compare_yoy_unavailable"
        elif ok_count < len(company_items):
            metric_status = "partial_derived_compare_yoy_unavailable"
        else:
            metric_status = "ok"

        winner_company = None
        loser_company = None
        larger_metric_change = None
        max_change = None
        min_change = None
        diff_change = None

        # 仅全部 ok 时计算 winner，避免部分缺失误导
        if metric_status == "ok" and ok_items and len(ok_items) >= 2:
            best = max(ok_items, key=lambda x: x["absolute_change"]
                       if x["absolute_change"] is not None else float("-inf"))
            worst = min(ok_items, key=lambda x: x["absolute_change"]
                        if x["absolute_change"] is not None else float("inf"))
            largest_change = max(ok_items, key=lambda x: abs(x["absolute_change"])
                                 if x["absolute_change"] is not None else float("-inf"))
            winner_company = best["company_name"]
            loser_company = worst["company_name"]
            larger_metric_change = largest_change["company_name"]
            max_change = best["absolute_change"]
            min_change = worst["absolute_change"]
            if max_change is not None and min_change is not None:
                diff_change = round(max_change - min_change, precision)

        derived_compare_yoy_result.append({
            "metric_key": mk,
            "metric_name": metric["metric_name"],
            "metric_type": "derived",
            "unit": unit,
            "scale": scale,
            "precision": precision,
            "current_year": report_year,
            "previous_year": prev_year,
            "period": report_period,
            "items": company_items,
            "winner_company": winner_company,
            "higher_yoy": winner_company,
            "lower_yoy": loser_company,
            "larger_metric_change": larger_metric_change,
            "max_change": max_change,
            "min_change": min_change,
            "diff_change": diff_change,
            "diff_unit": change_unit,
            "status": metric_status,
            "compare_spec": _get_compare_spec(state),
            "conclusion": _build_compare_conclusion(
                state,
                target="derived_change",
                winner_company=winner_company,
                loser_company=loser_company,
                diff=diff_change,
                diff_unit=change_unit,
            ),
        })

    return {"derived_compare_yoy_result": derived_compare_yoy_result}

__all__ = ['analyze_compare_yoy_node', 'analyze_derived_compare_yoy_node']
