"""趋势回答模块。"""

from __future__ import annotations

from typing import Any

from agent.constants import DEFAULT_QUERY_TYPE
from agent.state import AgentState
from agent.services.sql_builders import _metric_column_alias


direction_label = {
    "up": "整体呈上升趋势",
    "down": "整体呈下降趋势",
    "flat": "整体保持持平",
    "mixed": "各指标趋势方向不一致",
    "insufficient": "数据不足以判断趋势方向",
    "fluctuating": "整体呈波动趋势",
    "fluctuating_up": "整体波动上升",
    "fluctuating_down": "整体波动下降",
    "fluctuating_flat": "整体波动持平",
}


def _generate_trend_answer(state: dict[str, Any]) -> dict:
    """普通趋势回答（base 指标）。"""
    result = state.get("query_result")
    if not result:
        return {
            "final_answer": "查询失败：未生成查询结果。",
            "sql_success": False,
            "business_success": False,
            "error_type": "sql_execution_error",
            "empty_fields": [],
        }

    if not result["success"]:
        return {
            "final_answer": f"查询失败：{result['error']}",
            "sql_success": False,
            "business_success": False,
            "error_type": state.get("error_type") or "sql_execution_error",
            "empty_fields": [],
        }

    analysis = state.get("analysis_result") or {}
    metric_analyses = analysis.get("metrics") or {}
    rows = result["rows"]
    columns = result["columns"]
    metrics = state.get("metrics") or []

    if rows and not metric_analyses:
        return {
            "final_answer": "数据库中没有查询到对应趋势数据。",
            "answer_facts": [],
            "sql_success": True,
            "business_success": False,
            "error_type": "empty_result",
            "empty_fields": [],
        }

    if rows:
        company_name = dict(zip(columns, rows[0])).get("company_name", "")
    else:
        companies = state.get("companies") or []
        company_name = companies[0].get("company_name", "") if companies else ""
    answer_facts: list[dict[str, Any]] = []

    conclusion_parts: list[str] = []
    for _key, item in metric_analyses.items():
        d = item.get("direction", "insufficient")
        conclusion_parts.append(
            f"{item.get('metric_name', '')}{direction_label.get(d, d)}"
        )
    conclusion_text = "，".join(conclusion_parts) if conclusion_parts else "数据不足以判断趋势"

    metric_blocks: list[str] = []
    for metric in metrics:
        metric_key = metric["metric_key"]
        item = metric_analyses.get(metric_key, {})
        is_derived = item.get("is_derived", False)
        unit = metric.get("unit", "yuan")

        year_data_lines: list[str] = []
        if is_derived:
            year_values = item.get("year_values", {})
            for year_str in sorted(year_values.keys(), key=int):
                val = year_values[year_str]
                row_year = int(year_str)
                if val is None:
                    year_data_lines.append(f"  - {row_year} 年：无数据")
                    continue
                if unit == "percent":
                    formatted = f"{val:.{metric.get('precision', 2)}f}%"
                else:
                    formatted = f"{val:.{metric.get('precision', 2)}f}"
                year_data_lines.append(f"  - {row_year} 年：{formatted}")
                answer_facts.append({
                    "report_year": row_year,
                    "metric_name": metric["metric_name"],
                    "metric_key": metric_key,
                    "status": "ok",
                    "value": val,
                    "unit": unit,
                })
        else:
            column_alias = _metric_column_alias(metric)
            for row in rows:
                data = dict(zip(columns, row))
                row_year = data.get("report_year", "未知年份")
                value = data.get(column_alias)
                if value is None:
                    year_data_lines.append(f"  - {row_year} 年：无数据")
                    continue
                value_yi = float(value) / 100000000
                year_data_lines.append(f"  - {row_year} 年：{value_yi:.2f} 亿元")
                answer_facts.append({
                    "report_year": row_year,
                    "metric_name": metric["metric_name"],
                    "field": column_alias,
                    "source_field": f"{metric['table']}.{metric['field']}",
                    "status": "ok",
                    "value": value,
                })

        change_lines: list[str] = []
        if item.get("absolute_change") is not None:
            abs_change = item["absolute_change"]
            direction_word = "增加" if abs_change > 0 else "减少"
            if is_derived:
                if unit == "percent":
                    change_lines.append(
                        f"  - {item['first_year']} 年到 {item['last_year']} 年"
                        f"{direction_word} {abs(abs_change):.{metric.get('precision', 2)}f} 个百分点"
                    )
                else:
                    change_lines.append(
                        f"  - {item['first_year']} 年到 {item['last_year']} 年"
                        f"{direction_word} {abs(abs_change):.{metric.get('precision', 2)}f}"
                    )
            else:
                change_yi = abs_change / 100000000
                change_lines.append(
                    f"  - {item['first_year']} 年到 {item['last_year']} 年"
                    f"{direction_word} {abs(change_yi):.2f} 亿元"
                )
        if item.get("change_rate_pct") is not None:
            change_lines.append(
                f"  - 累计变化率：{item['change_rate_pct']:+.2f}%"
            )
        null_years = item.get("null_years") or []
        if null_years:
            change_lines.append(
                f"  - 空值年份：{', '.join(str(y) for y in null_years)}"
            )

        block = f"{metric['metric_name']}：\n"
        block += "年度数据：\n" + "\n".join(year_data_lines)
        if change_lines:
            block += "\n首末变化：\n" + "\n".join(change_lines)
        metric_blocks.append(block)

    answer = (
        f"根据数据库查询结果，{company_name} 年报中"
        f"{conclusion_text}。\n\n"
        + "\n".join(metric_blocks)
    )
    return {
        "final_answer": answer,
        "answer_facts": answer_facts,
        "sql_success": True,
        "business_success": True,
        "error_type": None,
        "empty_fields": [],
    }


def generate_derived_trend_answer_node(state: AgentState) -> dict:
    """派生指标趋势回答：格式化 derived_trend_result 为自然语言输出。"""
    intent_type = state.get("intent_type") or DEFAULT_QUERY_TYPE
    if intent_type != "trend_query":
        return {}

    metrics = state.get("metrics") or []
    metric_types = {m.get("metric_type", "base") for m in metrics}
    if "derived" not in metric_types:
        return {}

    derived_trend_result = state.get("derived_trend_result") or {}
    items = derived_trend_result.get("items") or []
    company_name = derived_trend_result.get("company_name", "")
    start_year = derived_trend_result.get("start_year")
    end_year = derived_trend_result.get("end_year")

    if not items:
        return {
            "final_answer": "数据库中缺少计算派生指标趋势所需的财务数据，无法生成趋势结论。",
            "answer_facts": [],
            "sql_success": True,
            "business_success": False,
            "error_type": "derived_trend_unavailable",
            "empty_fields": [],
        }

    # 方向标签（短格式，用于嵌入句中）
    direction_short = {
        "up": "上升",
        "down": "下降",
        "flat": "持平",
        "fluctuating_up": "波动上升",
        "fluctuating_down": "波动下降",
        "fluctuating_flat": "波动持平",
    }

    year_range_str = f"{start_year}–{end_year}" if start_year and end_year else ""

    def _extract_formula(text: str) -> str:
        for sep in ("，", "。", "；"):
            if sep in text:
                return text.split(sep)[0]
        return text

    all_ok = True
    any_ok = False
    answer_facts: list[dict[str, Any]] = []
    metric_blocks: list[str] = []
    missing_year_notes: list[str] = []

    for item in items:
        metric_name = item["metric_name"]
        unit = item.get("unit", "ratio")
        formula_text = _extract_formula(item.get("formula_text", ""))
        summary = item["summary"]
        summary_status = summary["status"]
        series = item.get("series", [])

        if summary_status == "ok":
            any_ok = True
            trend_dir = summary["trend_direction"]
            trend_label = direction_short.get(trend_dir, "")
            start_val = summary["start_value"]
            end_val = summary["end_value"]
            change_abs = summary["change_abs"]
            valid_points = summary["valid_points"]

            # 变化方向
            if change_abs is not None:
                change_dir = "上升" if change_abs >= 0 else "下降"
                abs_change = abs(change_abs)
                if unit == "percent":
                    change_str = f"{abs_change:.{2}f} 个百分点"
                else:
                    change_str = f"{abs_change:.{2}f}"

            # 年度结果列表
            year_parts: list[str] = []
            for s in series:
                yr = s["report_year"]
                if s["status"] == "ok" and s["value"] is not None:
                    if unit == "percent":
                        year_parts.append(f"{yr} 年 {s['value']:.2f}%")
                    else:
                        year_parts.append(f"{yr} 年 {s['value']:.2f}")
                elif s["status"] == "missing_record":
                    year_parts.append(f"{yr} 年无数据")
                else:
                    # empty_numerator/denominator/zero → 附加到缺失说明
                    status_reason = {
                        "empty_numerator": "分子为空",
                        "empty_denominator": "分母为空",
                        "zero_denominator": "分母为 0",
                    }
                    reason = status_reason.get(s["status"], "无法计算")
                    missing_year_notes.append(f"{yr} 年因{reason}，无法计算{metric_name}")
                    year_parts.append(f"{yr} 年无数据")

            year_list = "，".join(year_parts)

            # 首末有效年份
            valid_series = [s for s in series if s["status"] == "ok" and s["value"] is not None]

            block = (
                f"{metric_name}整体呈{trend_label}趋势，从 {valid_series[0]['report_year']} 年的 "
                f"{start_val:.2f}{'%' if unit == 'percent' else ''} 变化至 {valid_series[-1]['report_year']} 年的 "
                f"{end_val:.2f}{'%' if unit == 'percent' else ''}，"
                f"累计{change_dir} {change_str}。"
                f"\n各年结果为：{year_list}。"
            )
            if formula_text:
                block += f"\n计算口径为：{formula_text}。"
            metric_blocks.append(block)

            for s in series:
                if s["status"] == "ok" and s["value"] is not None:
                    answer_facts.append({
                        "report_year": s["report_year"],
                        "metric_name": metric_name,
                        "metric_key": item["metric_key"],
                        "status": "ok",
                        "value": s["value"],
                        "unit": unit,
                    })

        elif summary_status == "insufficient_points":
            # 只有 1 个有效点
            all_ok = False
            valid_series = [s for s in series if s["status"] == "ok" and s["value"] is not None]
            if valid_series:
                v = valid_series[0]
                val_str = f"{v['value']:.2f}{'%' if unit == 'percent' else ''}"
                block = (
                    f"当前结构化数据中只有 1 个年份（{v['report_year']} 年 {val_str}）"
                    f"可计算{metric_name}，无法判断趋势。"
                )
            else:
                block = f"当前结构化数据中缺少足够的有效年份来计算{metric_name}趋势。"
            metric_blocks.append(block)
        else:
            # no_valid_points
            all_ok = False
            block = (
                f"当前结构化数据中缺少计算{company_name} "
                f"{year_range_str} 年{metric_name}所需的有效字段，无法生成趋势结论。"
            )
            metric_blocks.append(block)

    if not any_ok:
        business_success = False
        error_type = "derived_trend_unavailable"
    elif not all_ok:
        business_success = True
        error_type = "partial_derived_trend_unavailable"
    else:
        business_success = True
        error_type = None

    # 组装回答
    if len(items) == 1:
        # 单指标
        answer = f"{company_name} {year_range_str} 年{metric_blocks[0]}"
        if missing_year_notes:
            answer += "\n\n其中" + "；".join(missing_year_notes) + "。"
    else:
        # 多指标
        parts = [f"{company_name} {year_range_str} 年的派生财务指标趋势如下："]
        for i, block in enumerate(metric_blocks):
            parts.append(f"{i + 1}. {block}")
        answer = "\n\n".join(parts)
        if missing_year_notes:
            answer += "\n\n其中" + "；".join(missing_year_notes) + "。"

    return {
        "final_answer": answer,
        "answer_facts": answer_facts,
        "sql_success": True,
        "business_success": business_success,
        "error_type": error_type,
        "empty_fields": [],
    }

__all__ = ['generate_derived_trend_answer_node']
