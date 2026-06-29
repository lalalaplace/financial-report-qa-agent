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
from agent.services.trend_service import _trend_conclusion_payload
from agent.utils.year_utils import _resolve_trend_years


def _summarize_trend_series(
    series: list[dict[str, Any]],
    *,
    precision: int,
) -> dict[str, Any]:
    valid_points = [
        item for item in series
        if item.get("status") == "ok" and item.get("value") is not None
    ]
    valid_values = [float(item["value"]) for item in valid_points]

    start_value = valid_values[0] if valid_values else None
    end_value = valid_values[-1] if len(valid_values) >= 2 else None
    if len(valid_values) == 0:
        status = "no_valid_points"
        trend_direction = "insufficient_points"
    elif len(valid_values) == 1:
        status = "insufficient_points"
        trend_direction = "insufficient_points"
    elif end_value > start_value:
        status = "ok"
        trend_direction = "up"
    elif end_value < start_value:
        status = "ok"
        trend_direction = "down"
    else:
        status = "ok"
        trend_direction = "flat"
    change_abs = (
        round(end_value - start_value, precision)
        if start_value is not None and end_value is not None
        else None
    )
    change_rate = (
        round(change_abs / abs(start_value), 4)
        if change_abs is not None and start_value != 0
        else None
    )

    return {
        "status": status,
        "valid_points": len(valid_values),
        "first_year": valid_points[0]["year"] if valid_points else None,
        "last_year": valid_points[-1]["year"] if valid_points else None,
        "first_value": start_value,
        "last_value": end_value,
        "absolute_change": change_abs,
        "change_rate": change_rate,
        "trend_direction": trend_direction,
    }

def _build_compare_trend_item(
    *,
    company_id: str,
    company_name: str,
    series: list[dict[str, Any]],
    precision: int,
) -> dict[str, Any]:
    summary = _summarize_trend_series(series, precision=precision)
    return {
        "company_id": company_id,
        "company_name": company_name,
        "series": series,
        "first_value": summary["first_value"],
        "last_value": summary["last_value"],
        "absolute_change": summary["absolute_change"],
        "change_rate": summary["change_rate"],
        "trend_direction": summary["trend_direction"],
        "status": "ok" if summary["status"] == "ok" else summary["status"],
    }

def _latest_year_winner_company(items: list[dict[str, Any]], years: list[int]) -> str | None:
    latest_year = years[-1] if years else None
    if latest_year is None:
        return None
    candidates: list[dict[str, Any]] = []
    for item in items:
        point = next(
            (
                p for p in item.get("series", [])
                if p.get("year") == latest_year and p.get("status") == "ok" and p.get("value") is not None
            ),
            None,
        )
        if point:
            candidates.append({"company_name": item["company_name"], "value": point["value"]})
    if not candidates:
        return None
    return max(candidates, key=lambda row: row["value"])["company_name"]

def _largest_absolute_change_company(items: list[dict[str, Any]]) -> str | None:
    candidates = [
        item for item in items
        if item.get("absolute_change") is not None
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: abs(item["absolute_change"]))["company_name"]

def _latest_year_loser_company(items: list[dict[str, Any]], years: list[int]) -> str | None:
    latest_year = years[-1] if years else None
    if latest_year is None:
        return None
    candidates: list[dict[str, Any]] = []
    for item in items:
        point = next(
            (
                p for p in item.get("series", [])
                if p.get("year") == latest_year and p.get("status") == "ok" and p.get("value") is not None
            ),
            None,
        )
        if point:
            candidates.append({"company_name": item["company_name"], "value": point["value"]})
    if not candidates:
        return None
    return min(candidates, key=lambda row: row["value"])["company_name"]

def _largest_increase_company(items: list[dict[str, Any]]) -> str | None:
    candidates = [
        item for item in items
        if item.get("absolute_change") is not None and item["absolute_change"] > 0
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: item["absolute_change"])["company_name"]

def _largest_decline_company(items: list[dict[str, Any]]) -> str | None:
    candidates = [
        item for item in items
        if item.get("absolute_change") is not None and item["absolute_change"] < 0
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda item: item["absolute_change"])["company_name"]

def analyze_compare_trend_node(state: AgentState) -> dict:
    """base 指标公司趋势对比分析。"""
    if state.get("intent_type") != "company_compare_trend_query":
        return {}

    query_results = state.get("compare_trend_query_results") or []
    companies = state.get("companies") or []
    metrics = [m for m in (state.get("metrics") or []) if m.get("metric_type") != "derived"]
    expected_years = _resolve_trend_years(state)

    if not query_results or not companies or not metrics or len(expected_years) < 2:
        return {"compare_trend_result": []}

    company_lookup = {
        c.get("stock_code", ""): c.get("company_name") or c.get("stock_abbr", "")
        for c in companies
    }
    metric_rows: dict[str, dict[str, dict[int, Any]]] = {
        m["metric_key"]: {code: {} for code in company_lookup}
        for m in metrics
    }

    for result in query_results:
        if not result.get("success"):
            continue
        columns = result.get("columns", [])
        for row in result.get("rows", []):
            data = dict(zip(columns, row))
            code = data.get("stock_code")
            year = data.get("report_year")
            if code not in company_lookup or year is None:
                continue
            for metric in metrics:
                column = f"{metric['table']}__{metric['field']}"
                if column in data:
                    metric_rows[metric["metric_key"]][code][int(year)] = data.get(column)

    compare_trend_result: list[dict[str, Any]] = []
    for metric in metrics:
        metric_key = metric["metric_key"]
        company_items: list[dict[str, Any]] = []
        ok_company_count = 0
        has_any_invalid_point = False

        for code, name in company_lookup.items():
            year_values = metric_rows[metric_key][code]
            series: list[dict[str, Any]] = []
            for year in expected_years:
                raw_value = year_values.get(year)
                if raw_value is None:
                    series.append({
                        "report_year": year,
                        "value": None,
                        "status": "missing_record",
                    })
                else:
                    series.append({
                        "report_year": year,
                        "value": float(raw_value),
                        "status": "ok",
                    })

            normalized_series = [
                {"year": point["report_year"], "value": point["value"], "status": point["status"]}
                for point in series
            ]
            item = _build_compare_trend_item(
                company_id=code,
                company_name=name,
                series=normalized_series,
                precision=2,
            )
            if item["status"] == "ok":
                ok_company_count += 1
            if any(point.get("status") != "ok" for point in item.get("series", [])):
                has_any_invalid_point = True
            company_items.append(item)

        if ok_company_count == 0:
            status = "compare_trend_unavailable"
        elif ok_company_count < len(company_items) or has_any_invalid_point:
            status = "partial_compare_trend_unavailable"
        else:
            status = "ok"

        trend_result = {
            "metric_key": metric_key,
            "metric_name": metric["metric_name"],
            "metric_type": "base",
            "unit": metric.get("unit", "yuan"),
            "years": expected_years,
            "items": [
                {**item, "change_unit": metric.get("unit", "yuan")}
                for item in company_items
            ],
            "latest_year_winner_company": _latest_year_winner_company(company_items, expected_years),
            "latest_higher": _latest_year_winner_company(company_items, expected_years),
            "latest_lower": _latest_year_loser_company(company_items, expected_years),
            "largest_increase": _largest_increase_company(company_items),
            "largest_decline": _largest_decline_company(company_items),
            "largest_absolute_change_company": _largest_absolute_change_company(company_items),
            "larger_metric_change": _largest_absolute_change_company(company_items),
            "status": status,
        }
        trend_result["compare_spec"] = _get_compare_spec(state)
        trend_result["conclusion"] = _trend_conclusion_payload(
            state,
            trend_result,
            diff_unit=metric.get("unit", "yuan"),
        )
        compare_trend_result.append(trend_result)

    return {"compare_trend_result": compare_trend_result}

def analyze_derived_compare_trend_node(state: AgentState) -> dict:
    """derived 指标公司趋势对比分析。"""
    if state.get("intent_type") != "company_compare_trend_query":
        return {}

    query_results = state.get("derived_compare_trend_query_results") or {}
    companies = state.get("companies") or []
    metrics = [m for m in (state.get("metrics") or []) if m.get("metric_type") == "derived"]
    expected_years = _resolve_trend_years(state)

    if not query_results or not companies or not metrics or len(expected_years) < 2:
        return {"derived_compare_trend_result": []}

    company_lookup = {
        c.get("stock_code", ""): c.get("company_name") or c.get("stock_abbr", "")
        for c in companies
    }
    derived_compare_trend_result: list[dict[str, Any]] = []
    for metric in metrics:
        metric_key = metric["metric_key"]
        unit = metric.get("unit", "ratio")
        scale = metric.get("scale") or 1
        precision = metric.get("precision", 2)
        entry = query_results.get(metric_key)
        has_any_invalid_point = False

        rows_by_company_year: dict[str, dict[int, dict[str, Any]]] = {
            code: {} for code in company_lookup
        }
        if entry and entry.get("sql_success"):
            columns = entry.get("columns", [])
            for row in entry.get("rows", []):
                data = dict(zip(columns, row))
                code = data.get("stock_code")
                year = data.get("report_year")
                if code in company_lookup and year is not None:
                    rows_by_company_year[code][int(year)] = data

        company_items: list[dict[str, Any]] = []
        ok_company_count = 0
        for code, name in company_lookup.items():
            series: list[dict[str, Any]] = []
            for year in expected_years:
                data = rows_by_company_year[code].get(year)
                if not data:
                    series.append({
                        "report_year": year,
                        "numerator": None,
                        "denominator": None,
                        "value": None,
                        "status": "missing_record",
                    })
                    continue

                numerator = data.get("numerator_value")
                denominator = data.get("denominator_value")
                if numerator is None:
                    status = "empty_numerator"
                    value = None
                elif denominator is None:
                    status = "empty_denominator"
                    value = None
                elif float(denominator) == 0:
                    status = "zero_denominator"
                    value = None
                else:
                    status = "ok"
                    value = round(float(numerator) / float(denominator) * scale, precision)

                series.append({
                    "report_year": year,
                    "numerator": float(numerator) if numerator is not None else None,
                    "denominator": float(denominator) if denominator is not None else None,
                    "value": value,
                    "status": status,
                })

            normalized_series = [
                {
                    "year": point["report_year"],
                    "value": point["value"],
                    "status": point["status"],
                    "numerator": point.get("numerator"),
                    "denominator": point.get("denominator"),
                }
                for point in series
            ]
            item = _build_compare_trend_item(
                company_id=code,
                company_name=name,
                series=normalized_series,
                precision=precision,
            )
            if unit == "percent":
                item["change_rate"] = None
                item["change_unit"] = "百分点"
            else:
                item["change_unit"] = unit
            if item["status"] == "ok":
                ok_company_count += 1
            if any(point.get("status") != "ok" for point in item.get("series", [])):
                has_any_invalid_point = True
            company_items.append(item)

        if ok_company_count == 0:
            status = "derived_compare_trend_unavailable"
        elif ok_company_count < len(company_items) or has_any_invalid_point:
            status = "partial_derived_compare_trend_unavailable"
        else:
            status = "ok"

        derived_trend_result = {
            "metric_key": metric_key,
            "metric_name": metric["metric_name"],
            "metric_type": "derived",
            "unit": unit,
            "scale": scale,
            "precision": precision,
            "years": expected_years,
            "items": company_items,
            "latest_year_winner_company": _latest_year_winner_company(company_items, expected_years),
            "latest_higher": _latest_year_winner_company(company_items, expected_years),
            "latest_lower": _latest_year_loser_company(company_items, expected_years),
            "largest_increase": _largest_increase_company(company_items),
            "largest_decline": _largest_decline_company(company_items),
            "largest_absolute_change_company": _largest_absolute_change_company(company_items),
            "larger_metric_change": _largest_absolute_change_company(company_items),
            "status": status,
        }
        derived_trend_result["compare_spec"] = _get_compare_spec(state)
        derived_trend_result["conclusion"] = _trend_conclusion_payload(
            state,
            derived_trend_result,
            diff_unit="百分点" if unit == "percent" else unit,
        )
        derived_compare_trend_result.append(derived_trend_result)

    return {"derived_compare_trend_result": derived_compare_trend_result}

__all__ = ['_summarize_trend_series', '_build_compare_trend_item', '_latest_year_winner_company', '_largest_absolute_change_company', '_latest_year_loser_company', '_largest_increase_company', '_largest_decline_company', 'analyze_compare_trend_node', 'analyze_derived_compare_trend_node']
