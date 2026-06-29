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
from agent.services.trend_service import _infer_trend_direction


def analyze_trend_node(state: AgentState) -> dict:
    """趋势分析：把多年份 SQL 结果转为结构化趋势事实。

    非 trend_query / yoy_query 时透传空返回。
    """
    intent_type = state.get("intent_type") or DEFAULT_QUERY_TYPE
    # V0.3.5：yoy_query+derived 不应进入此节点（防御性检测）
    if intent_type == "yoy_query":
        metrics = state.get("metrics") or []
        metric_types = {m.get("metric_type", "base") for m in metrics}
        if metric_types == {"derived"}:
            return {
                "business_success": False,
                "error_type": "route_error",
                "final_answer": "系统路由异常：yoy_query 不应进入趋势分析节点，请联系管理员。",
            }
    if intent_type not in ("trend_query", "yoy_query"):
        return {}

    # 派生趋势使用独立结果（derived_trend_query_results），不依赖 query_result
    derived_trend_query_results = state.get("derived_trend_query_results")

    if derived_trend_query_results:
        rows: list[list] = []
        columns: list[str] = []
    else:
        query_result = state.get("query_result")
        if not query_result or not query_result["success"] or query_result["row_count"] == 0:
            return {"analysis_result": None}
        rows = query_result["rows"]
        columns = query_result["columns"]

    metrics = state.get("metrics") or []

    metric_series: dict[str, dict[str, Any]] = {}
    is_derived_trend = any(m.get("metric_type") == "derived" for m in metrics)
    metric_dict = load_metric_dictionary() if is_derived_trend and not derived_trend_query_results else {}

    for metric in metrics:
        if is_derived_trend:
            scale = metric.get("scale") or 1
            precision = metric.get("precision", 2)

            if derived_trend_query_results:
                # 新路径：从 dict 按 metric_key 取结果
                entry = derived_trend_query_results.get(metric["metric_key"])
                if entry and entry.get("sql_success") and entry.get("row_count", 0) > 0:
                    metric_rows = entry["rows"]
                    metric_columns = entry.get("columns", [])
                    num_col = "numerator_value"
                    den_col = "denominator_value"
                else:
                    metric_series[metric["metric_key"]] = {
                        "metric_name": metric["metric_name"],
                        "unit": metric.get("unit", "yuan"),
                        "is_derived": True,
                        "year_values": {},
                        "direction": "insufficient",
                    }
                    continue
            else:
                # 旧路径（回退）：从合并 query_result 读取
                metric_rows = rows
                metric_columns = columns
                formula = metric.get("formula") or {}

                def _col_from_key(dep_key: str) -> str:
                    info = metric_dict.get(dep_key)
                    return f"{info['table']}__{info['field']}" if info else ""

                num_col = _col_from_key(formula.get("numerator", ""))
                den_col = _col_from_key(formula.get("denominator", ""))

            year_values: dict[int, float | None] = {}
            for row in metric_rows:
                data = dict(zip(metric_columns, row))
                report_year = data.get("report_year")
                if report_year is None:
                    continue
                num_val = data.get(num_col)
                den_val = data.get(den_col)
                if num_val is not None and den_val is not None and float(den_val) != 0:
                    year_values[int(report_year)] = round(
                        float(num_val) / float(den_val) * scale, precision
                    )
                else:
                    year_values[int(report_year)] = None
        else:
            column_alias = _metric_column_alias(metric)
            year_values: dict[int, float | None] = {}
            for row in rows:
                data = dict(zip(columns, row))
                report_year = data.get("report_year")
                value = data.get(column_alias)
                if report_year is not None:
                    year_values[int(report_year)] = float(value) if value is not None else None

        sorted_years = sorted(year_values.keys())
        if len(sorted_years) < 2:
            direction = "insufficient"
        else:
            first_year = sorted_years[0]
            last_year = sorted_years[-1]
            first_val = year_values[first_year]
            last_val = year_values[last_year]

            if first_val is None or last_val is None:
                direction = "insufficient"
            elif abs(last_val - first_val) < 1e-9:
                direction = "flat"
            elif last_val > first_val:
                direction = "up"
            else:
                direction = "down"

            null_years = sorted(
                year for year, val in year_values.items() if val is None
            )

            absolute_change = None
            change_rate_pct = None
            if first_val is not None and last_val is not None:
                absolute_change = last_val - first_val
                if first_val != 0:
                    change_rate_pct = round(absolute_change / first_val * 100, 2)

            metric_series[metric["metric_key"]] = {
                "metric_name": metric["metric_name"],
                "unit": metric.get("unit", "yuan"),
                "is_derived": is_derived_trend,
                "year_values": {str(y): v for y, v in year_values.items()},
                "first_year": first_year,
                "first_value": first_val,
                "last_year": last_year,
                "last_value": last_val,
                "absolute_change": absolute_change,
                "change_rate_pct": change_rate_pct,
                "null_years": null_years,
                "direction": direction,
            }

    # 汇总方向：全升 → up，全降 → down，混合 → mixed
    directions = {m["direction"] for m in metric_series.values()}
    if "insufficient" in directions:
        overall_direction = "insufficient"
    elif directions == {"up"}:
        overall_direction = "up"
    elif directions == {"down"}:
        overall_direction = "down"
    elif directions == {"flat"}:
        overall_direction = "flat"
    else:
        overall_direction = "mixed"

    return {
        "analysis_result": {
            "direction": overall_direction,
            "metrics": metric_series,
        }
    }

def analyze_derived_trend_node(state: AgentState) -> dict:
    """派生指标趋势分析：基于 derived_trend_query_results 计算逐年比率值并推断趋势。

    同时输出 derived_trend_result（新详细格式）和 analysis_result（向后兼容）。
    """
    intent_type = state.get("intent_type") or DEFAULT_QUERY_TYPE
    if intent_type != "trend_query":
        return {}

    metrics = state.get("metrics") or []
    if not metrics:
        return {}

    # 只处理派生指标
    metric_types = {m.get("metric_type", "base") for m in metrics}
    if "derived" not in metric_types:
        return {}

    dt_results = state.get("derived_trend_query_results") or {}
    companies = state.get("companies") or []
    company_name = companies[0].get("company_name", "") if companies else ""

    # 计算预期年份范围
    time_mode = state.get("time_mode") or "recent_n"
    report_year = state.get("report_year")
    recent_n = state.get("recent_n_years") or 5
    if time_mode == "explicit_range":
        start_year = state.get("start_year")
        end_year = state.get("end_year")
    else:
        end_year = report_year
        start_year = end_year - recent_n + 1 if end_year else None

    expected_years = list(range(start_year, end_year + 1)) if start_year and end_year else []
    metric_dict = load_metric_dictionary()

    items: list[dict[str, Any]] = []
    analysis_metrics: dict[str, dict[str, Any]] = {}
    all_directions: set[str] = set()

    for metric in metrics:
        metric_key = metric["metric_key"]
        metric_name = metric["metric_name"]
        unit = metric.get("unit", "ratio")
        scale = metric.get("scale") or 1
        precision = metric.get("precision", 2)

        info = metric_dict.get(metric_key, {})
        formula_text = info.get("description", "")

        # 获取查询结果
        entry = dt_results.get(metric_key)

        # 解析已有年份数据
        row_data: dict[int, dict[str, Any]] = {}
        if entry and entry.get("sql_success") and entry.get("row_count", 0) > 0:
            for row in entry["rows"]:
                data = dict(zip(entry.get("columns", []), row))
                yr = data.get("report_year")
                if yr is None:
                    continue
                yr = int(yr)
                row_data[yr] = {
                    "numerator_value": data.get("numerator_value"),
                    "denominator_value": data.get("denominator_value"),
                }

        # 构建系列（含预期年份中缺失的）
        series: list[dict[str, Any]] = []
        valid_values: list[float] = []
        year_values: dict[str, float | None] = {}

        for yr in expected_years:
            if yr not in row_data:
                series.append({
                    "report_year": yr,
                    "numerator_value": None,
                    "denominator_value": None,
                    "value": None,
                    "status": "missing_record",
                })
                year_values[str(yr)] = None
                continue

            rd = row_data[yr]
            num_val = rd["numerator_value"]
            den_val = rd["denominator_value"]

            if num_val is None:
                status = "empty_numerator"
                value = None
            elif den_val is None:
                status = "empty_denominator"
                value = None
            elif float(den_val) == 0:
                status = "zero_denominator"
                value = None
            else:
                status = "ok"
                value = round(float(num_val) / float(den_val) * scale, precision)
                valid_values.append(value)

            series.append({
                "report_year": yr,
                "numerator_value": float(num_val) if num_val is not None else None,
                "denominator_value": float(den_val) if den_val is not None else None,
                "value": value,
                "status": status,
            })
            year_values[str(yr)] = value

        # 构建 summary
        valid_points = len(valid_values)
        if valid_points < 1:
            summary_status = "no_valid_points"
            trend_dir = "insufficient_points"
        elif valid_points == 1:
            summary_status = "insufficient_points"
            trend_dir = "insufficient_points"
        else:
            summary_status = "ok"
            trend_dir = _infer_trend_direction(valid_values)

        # 首末变化
        start_val = valid_values[0] if valid_values else None
        end_val = valid_values[-1] if valid_points >= 2 else None
        change_abs = round(end_val - start_val, precision) if start_val is not None and end_val is not None else None
        change_rate = round(change_abs / abs(start_val), 4) if change_abs is not None and start_val != 0 else None

        # percent 指标不展示 change_rate（避免财务口径混乱）
        if unit == "percent":
            change_rate_display = None
        else:
            change_rate_display = change_rate

        items.append({
            "metric_key": metric_key,
            "metric_name": metric_name,
            "unit": unit,
            "formula_text": formula_text,
            "series": series,
            "summary": {
                "status": summary_status,
                "valid_points": valid_points,
                "start_year": expected_years[0] if expected_years else None,
                "end_year": expected_years[-1] if expected_years else None,
                "start_value": start_val,
                "end_value": end_val,
                "change_abs": change_abs,
                "change_rate": change_rate_display,
                "trend_direction": trend_dir,
            },
        })

        # 构建向后兼容的 analysis_result 方向映射
        if trend_dir in ("up", "down"):
            compat_dir = trend_dir
        elif trend_dir == "insufficient_points":
            compat_dir = "insufficient"
        elif trend_dir in ("fluctuating_up", "fluctuating_down"):
            compat_dir = "fluctuating"
        else:
            compat_dir = "flat"
        all_directions.add(compat_dir)

        null_years = sorted(yr for yr in expected_years if year_values.get(str(yr)) is None)

        analysis_metrics[metric_key] = {
            "metric_name": metric_name,
            "unit": unit,
            "is_derived": True,
            "year_values": year_values,
            "first_year": expected_years[0] if expected_years else None,
            "first_value": start_val,
            "last_year": expected_years[-1] if expected_years else None,
            "last_value": end_val,
            "absolute_change": change_abs,
            "change_rate_pct": change_rate_display,
            "null_years": null_years,
            "direction": compat_dir,
        }

    # 总体方向
    if "insufficient" in all_directions:
        overall_direction = "insufficient"
    elif all_directions == {"up"}:
        overall_direction = "up"
    elif all_directions == {"down"}:
        overall_direction = "down"
    elif all_directions == {"flat"} or all_directions == {"fluctuating"}:
        overall_direction = "flat"
    else:
        overall_direction = "mixed"

    return {
        "derived_trend_result": {
            "company_name": company_name,
            "start_year": start_year,
            "end_year": end_year,
            "items": items,
        },
        "analysis_result": {
            "direction": overall_direction,
            "metrics": analysis_metrics,
        },
    }

__all__ = ['analyze_trend_node', 'analyze_derived_trend_node']
