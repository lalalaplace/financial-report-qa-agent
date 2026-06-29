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


def analyze_compare_node(state: AgentState) -> dict:
    """base 指标多公司对比分析。

    输出 compare_result，逐指标给出 winner/max/min/diff。
    """
    intent_type = state.get("intent_type") or DEFAULT_QUERY_TYPE
    if intent_type != "company_compare_query":
        return {}

    compare_results = state.get("compare_query_results") or []
    companies = state.get("companies") or []
    metrics = [m for m in (state.get("metrics") or []) if m.get("metric_type") != "derived"]
    report_year = state.get("report_year")
    report_period = state.get("report_period") or DEFAULT_REPORT_PERIOD

    if not compare_results or not companies or not metrics:
        return {"compare_result": []}

    # 公司 lookup
    company_lookup: dict[str, str] = {}
    for c in companies:
        code = c.get("stock_code", "")
        company_lookup[code] = c.get("company_name") or c.get("stock_abbr", code)

    # 为每个 base 指标建立 company→value 映射
    metric_data: dict[str, dict[str, Any]] = {}
    for m in metrics:
        mk = m["metric_key"]
        metric_data[mk] = {
            "metric_key": mk,
            "metric_name": m["metric_name"],
            "metric_type": "base",
            "unit": m.get("unit", "yuan"),
            "year": report_year,
            "period": report_period,
            "column": f"{m['table']}__{m['field']}",
            "values": {},
        }

    for cr in compare_results:
        if not cr.get("success"):
            continue
        cr_columns = cr.get("columns", [])
        for row in cr.get("rows", []):
            data = dict(zip(cr_columns, row))
            code = data.get("stock_code", "")
            if code not in company_lookup:
                continue
            for mk, md in metric_data.items():
                col = md["column"]
                if col in data:
                    md["values"][code] = data[col]

    # 构建 compare_result
    compare_result: list[dict[str, Any]] = []

    for mk, md in metric_data.items():
        items: list[dict[str, Any]] = []
        ok_count = 0
        missing_count = 0

        for code, name in company_lookup.items():
            if code in md["values"] and md["values"][code] is not None:
                items.append({
                    "company_id": code,
                    "company_name": name,
                    "value": float(md["values"][code]),
                    "status": "ok",
                })
                ok_count += 1
            elif code in md["values"]:
                items.append({
                    "company_id": code,
                    "company_name": name,
                    "value": None,
                    "status": "empty_value",
                })
                missing_count += 1
            else:
                items.append({
                    "company_id": code,
                    "company_name": name,
                    "value": None,
                    "status": "missing_record",
                })
                missing_count += 1

        ok_items = [it for it in items if it["status"] == "ok"]

        if ok_count == 0:
            metric_status = "compare_unavailable"
        elif missing_count > 0:
            metric_status = "partial_compare_unavailable"
        else:
            metric_status = "ok"

        winner_company = None
        loser_company = None
        max_value = None
        min_value = None
        diff = None

        if ok_items:
            max_item = max(ok_items, key=lambda x: x["value"])
            min_item = min(ok_items, key=lambda x: x["value"])
            winner_company = max_item["company_name"]
            loser_company = min_item["company_name"]
            max_value = max_item["value"]
            min_value = min_item["value"]
            if len(ok_items) >= 2:
                diff = round(max_value - min_value, 2)

        compare_result.append({
            "metric_key": mk,
            "metric_name": md["metric_name"],
            "metric_type": "base",
            "unit": md["unit"],
            "year": md["year"],
            "period": md["period"],
            "items": items,
            "winner_company": winner_company,
            "higher": winner_company,
            "lower": loser_company,
            "max_value": max_value,
            "min_value": min_value,
            "diff": diff,
            "diff_unit": md["unit"],
            "status": metric_status,
            "compare_spec": _get_compare_spec(state),
            "conclusion": _build_compare_conclusion(
                state,
                target="metric_value",
                winner_company=winner_company,
                loser_company=loser_company,
                diff=diff,
                diff_unit=md["unit"],
            ),
        })

    return {"compare_result": compare_result}

def analyze_derived_compare_node(state: AgentState) -> dict:
    """派生指标多公司对比分析。

    输出 derived_compare_result，逐 item 保留 numerator/denominator 原始值。
    percent 指标 diff_unit = \"百分点\"，非 percent 沿用原单位。
    """
    intent_type = state.get("intent_type") or DEFAULT_QUERY_TYPE
    if intent_type != "company_compare_query":
        return {}

    derived_results = state.get("derived_compare_query_results") or {}
    companies = state.get("companies") or []
    metrics = [m for m in (state.get("metrics") or []) if m.get("metric_type") == "derived"]
    report_year = state.get("report_year")
    report_period = state.get("report_period") or DEFAULT_REPORT_PERIOD

    if not derived_results or not companies or not metrics:
        return {"derived_compare_result": []}

    company_lookup: dict[str, str] = {}
    for c in companies:
        code = c.get("stock_code", "")
        company_lookup[code] = c.get("company_name") or c.get("stock_abbr", code)

    derived_compare_result: list[dict[str, Any]] = []

    for m in metrics:
        mk = m["metric_key"]
        unit = m.get("unit", "ratio")
        scale = m.get("scale", 1)
        precision = m.get("precision", 2)

        entry = derived_results.get(mk)
        items: list[dict[str, Any]] = []
        ok_count = 0
        missing_count = 0

        # 先为所有公司构建初始状态
        for code, name in company_lookup.items():
            items.append({
                "company_id": code,
                "company_name": name,
                "numerator": None,
                "denominator": None,
                "value": None,
                "status": "missing_record",
            })

        # 从 SQL 结果填充
        if entry and entry.get("sql_success") and entry.get("row_count", 0) > 0:
            for row in entry.get("rows", []):
                data = dict(zip(entry.get("columns", []), row))
                code = data.get("stock_code", "")
                if code not in company_lookup:
                    continue
                # 找到对应 item
                item = next((it for it in items if it["company_id"] == code), None)
                if not item:
                    continue

                num_val = data.get("numerator_value")
                den_val = data.get("denominator_value")
                item["numerator"] = float(num_val) if num_val is not None else None
                item["denominator"] = float(den_val) if den_val is not None else None

                if num_val is None:
                    item["status"] = "empty_numerator"
                    missing_count += 1
                elif den_val is None:
                    item["status"] = "empty_denominator"
                    missing_count += 1
                elif float(den_val) == 0:
                    item["status"] = "zero_denominator"
                    missing_count += 1
                else:
                    item["value"] = round(float(num_val) / float(den_val) * scale, precision)
                    item["status"] = "ok"
                    ok_count += 1

        # 汇总
        ok_items = [it for it in items if it["status"] == "ok"]

        if ok_count == 0:
            metric_status = "derived_compare_unavailable"
        elif missing_count > 0:
            metric_status = "partial_derived_compare_unavailable"
        else:
            metric_status = "ok"

        winner_company = None
        loser_company = None
        max_value = None
        min_value = None
        diff = None

        if ok_items:
            max_item = max(ok_items, key=lambda x: x["value"])
            min_item = min(ok_items, key=lambda x: x["value"])
            winner_company = max_item["company_name"]
            loser_company = min_item["company_name"]
            max_value = max_item["value"]
            min_value = min_item["value"]
            if len(ok_items) >= 2:
                diff = round(max_value - min_value, precision)

        diff_unit = "百分点" if unit == "percent" else unit

        derived_compare_result.append({
            "metric_key": mk,
            "metric_name": m["metric_name"],
            "metric_type": "derived",
            "unit": unit,
            "scale": scale,
            "year": report_year,
            "period": report_period,
            "items": items,
            "winner_company": winner_company,
            "higher": winner_company,
            "lower": loser_company,
            "max_value": max_value,
            "min_value": min_value,
            "diff": diff,
            "diff_unit": diff_unit,
            "status": metric_status,
            "compare_spec": _get_compare_spec(state),
            "conclusion": _build_compare_conclusion(
                state,
                target="metric_value",
                winner_company=winner_company,
                loser_company=loser_company,
                diff=diff,
                diff_unit=diff_unit,
            ),
        })

    return {"derived_compare_result": derived_compare_result}

__all__ = ['analyze_compare_node', 'analyze_derived_compare_node']
