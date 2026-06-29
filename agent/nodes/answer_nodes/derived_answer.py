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


def generate_derived_yoy_answer_node(state: AgentState) -> dict:
    """派生指标同比回答：格式化 derived_yoy_result 为自然语言输出。

    规则：
    - percent 指标：变化用"百分点"，默认不输出"同比增长率"
      - 例：资产负债率为 45.23%，2023 年为 42.10%，较上年上升 3.13 个百分点
    - ratio 指标：输出绝对变化 + 相对变化率
      - 例：经营现金流净利比为 1.15，2023 年为 0.98，较上年上升 0.17，同比增长率为 17.35%
    """
    intent_type = state.get("intent_type") or DEFAULT_QUERY_TYPE
    if intent_type != "yoy_query":
        return {}

    metrics = state.get("metrics") or []
    metric_types = {m.get("metric_type", "base") for m in metrics}
    if metric_types != {"derived"}:
        return {}

    derived_yoy_result = state.get("derived_yoy_result") or {}
    items = derived_yoy_result.get("items") or []
    company_name = derived_yoy_result.get("company_name", "")
    report_year = derived_yoy_result.get("report_year", "")
    prev_year = derived_yoy_result.get("previous_year", "")

    if not items:
        return {
            "final_answer": "数据库中没有查询到对应派生指标同比数据。",
            "answer_facts": [],
            "sql_success": True,
            "business_success": False,
            "error_type": "derived_yoy_unavailable",
            "empty_fields": [],
        }

    answer_facts: list[dict[str, Any]] = []
    metric_lines: list[str] = []
    ok_count = 0
    failed_count = 0

    for item in items:
        metric_name = item["metric_name"]
        status = item["status"]
        unit = item.get("unit", "ratio")
        precision = item.get("precision", 2)
        formula_text = item.get("formula_text", "")

        if unit == "percent":
            unit_suffix = "%"
        elif unit == "ratio":
            unit_suffix = ""
        else:
            unit_suffix = f" {unit}"

        if status == "ok":
            ok_count += 1
            cur_val = item["current_value"]
            prev_val = item["previous_value"]
            change_abs = item["change_abs"]

            fmt_cur = f"{cur_val:.{precision}f}{unit_suffix}"
            fmt_prev = f"{prev_val:.{precision}f}{unit_suffix}"

            if change_abs > 0:
                direction_word = "上升"
            elif change_abs < 0:
                direction_word = "下降"
            else:
                direction_word = ""

            if unit == "percent":
                abs_change = abs(change_abs)
                change_str = f"{abs_change:.{precision}f} 个百分点"
                line = (
                    f"{metric_name}为 {fmt_cur}，{prev_year} 年为 {fmt_prev}"
                    f"，较上年{direction_word} {change_str}。"
                )
            else:
                abs_change = abs(change_abs)
                change_str = f"{abs_change:.{precision}f}"
                yoy_rate = item.get("yoy_rate")
                if change_abs != 0 and yoy_rate is not None:
                    rate_pct = round(abs(yoy_rate) * 100, 2)
                    line = (
                        f"{metric_name}为 {fmt_cur}，{prev_year} 年为 {fmt_prev}"
                        f"，较上年{direction_word} {change_str}，同比增长率为 {rate_pct:.2f}%。"
                    )
                elif change_abs != 0:
                    line = (
                        f"{metric_name}为 {fmt_cur}，{prev_year} 年为 {fmt_prev}"
                        f"，较上年{direction_word} {change_str}。"
                    )
                else:
                    line = (
                        f"{metric_name}为 {fmt_cur}，{prev_year} 年为 {fmt_prev}"
                        f"，同比持平。"
                    )

            metric_lines.append(line)
            answer_facts.append({
                "metric_name": metric_name,
                "metric_key": item["metric_key"],
                "status": "ok",
                "current_value": cur_val,
                "previous_value": prev_val,
                "change_abs": change_abs,
                "yoy_rate": item.get("yoy_rate"),
            })

        else:
            failed_count += 1
            status_messages = {
                "sql_error": "SQL 执行失败，无法计算。",
                "empty_result": "缺少基础财务数据，无法计算。",
                "missing_current_year": f"缺少 {report_year} 年数据，无法计算同比。",
                "missing_previous_year": f"缺少 {prev_year} 年数据，无法计算同比。",
                "empty_numerator_current": f"{report_year} 年分子（{item.get('numerator_metric', '')}）为空，无法计算。",
                "empty_numerator_previous": f"{prev_year} 年分子（{item.get('numerator_metric', '')}）为空，无法计算。",
                "empty_denominator_current": f"{report_year} 年分母（{item.get('denominator_metric', '')}）为空，无法计算。",
                "empty_denominator_previous": f"{prev_year} 年分母（{item.get('denominator_metric', '')}）为空，无法计算。",
                "zero_denominator_current": f"{report_year} 年分母（{item.get('denominator_metric', '')}）为 0，无法计算。",
                "zero_denominator_previous": f"{prev_year} 年分母（{item.get('denominator_metric', '')}）为 0，无法计算。",
            }
            reason = status_messages.get(status, status)
            metric_lines.append(f"{metric_name}：{reason}")
            answer_facts.append({
                "metric_name": metric_name,
                "metric_key": item["metric_key"],
                "status": status,
            })

    # 业务状态
    if ok_count == 0:
        business_success = False
        error_type = "derived_yoy_unavailable"
    elif failed_count > 0:
        business_success = True
        error_type = "partial_derived_yoy_unavailable"
    else:
        business_success = True
        error_type = None

    # 计算口径说明
    computation_notes = []
    for item in items:
        if item["status"] == "ok":
            num_name = item.get("numerator_metric", "")
            den_name = item.get("denominator_metric", "")
            suffix = " × 100%" if item.get("unit") == "percent" else ""
            formula_text_short = item.get("formula_text", "")
            note = f"- {item['metric_name']} = {num_name} / {den_name}{suffix}"
            if formula_text_short:
                note += f"（{formula_text_short}）"
            computation_notes.append(note)

    answer = (
        f"根据数据库查询结果，{company_name} {report_year} 年年报中：\n\n"
        + "\n".join(metric_lines)
    )
    if computation_notes:
        answer += "\n\n计算口径：\n" + "\n".join(computation_notes)

    return {
        "final_answer": answer,
        "answer_facts": answer_facts,
        "sql_success": True,
        "business_success": business_success,
        "error_type": error_type,
        "empty_fields": [],
    }

def generate_derived_answer_node(state: AgentState) -> dict:
    """派生指标回答：格式化 derived_result 为自然语言输出。"""
    intent_type = state.get("intent_type") or DEFAULT_QUERY_TYPE
    if intent_type != "derived_metric_query":
        return {}

    derived_result = state.get("derived_result") or {}
    items = derived_result.get("items") or []
    company_name = derived_result.get("company_name", "")
    report_year = derived_result.get("report_year", "")

    if not items:
        return {
            "final_answer": "数据库中没有查询到对应财务数据，无法计算派生指标。",
            "answer_facts": [],
            "sql_success": True,
            "business_success": False,
            "error_type": "derived_unavailable",
            "empty_fields": [],
        }

    answer_facts: list[dict[str, Any]] = []
    metric_lines: list[str] = []
    ok_count = 0
    failed_count = 0

    for item in items:
        status = item["status"]
        metric_name = item["metric_name"]
        formula_text = item.get("formula_text", "")
        unit = item.get("unit", "ratio")
        precision = item.get("precision", 2)

        answer_facts.append({
            "metric_name": metric_name,
            "metric_key": item["metric_key"],
            "status": status,
            "value": item.get("value"),
            "unit": unit,
            "numerator_value": item.get("numerator_value"),
            "denominator_value": item.get("denominator_value"),
        })

        if status == "ok":
            ok_count += 1
            value = item["value"]
            if unit == "percent":
                formatted_value = f"{value:.{precision}f}%"
            else:
                formatted_value = f"{value:.{precision}f}"
            numerator_name = item.get("numerator_metric", "")
            denominator_name = item.get("denominator_metric", "")
            suffix = " × 100%" if unit == "percent" else ""
            metric_lines.append(
                f"{metric_name}：{formatted_value}"
                f"（计算口径：{numerator_name} / {denominator_name}{suffix}）"
            )

        elif status == "missing_record":
            failed_count += 1
            metric_lines.append(f"{metric_name}：缺少基础财务数据，无法计算。")
        elif status == "empty_numerator":
            failed_count += 1
            numerator_name = item.get("numerator_metric", "")
            metric_lines.append(f"{metric_name}：{numerator_name} 字段为空，无法计算。")
        elif status == "empty_denominator":
            failed_count += 1
            denominator_name = item.get("denominator_metric", "")
            metric_lines.append(f"{metric_name}：{denominator_name} 字段为空，无法计算。")
        elif status == "zero_denominator":
            failed_count += 1
            denominator_name = item.get("denominator_metric", "")
            metric_lines.append(f"{metric_name}：{denominator_name} 为 0，无法计算。")
        else:
            failed_count += 1
            metric_lines.append(f"{metric_name}：无法计算。")

    if ok_count == 0:
        business_success = False
        error_type = "derived_unavailable"
    elif failed_count > 0:
        business_success = True
        error_type = "partial_derived_unavailable"
    else:
        business_success = True
        error_type = None

    answer = (
        f"根据数据库查询结果，{company_name} {report_year} 年年报中：\n\n"
        + "\n".join(metric_lines)
    )

    return {
        "final_answer": answer,
        "answer_facts": answer_facts,
        "sql_success": True,
        "business_success": business_success,
        "error_type": error_type,
        "empty_fields": [],
    }

__all__ = ['generate_derived_yoy_answer_node', 'generate_derived_answer_node']
