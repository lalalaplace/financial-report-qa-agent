"""公司趋势对比回答模块。"""

from typing import Any

from agent.nodes.answer_nodes.common import _section_numeral
from agent.services.compare_service import _get_compare_spec
from agent.utils.formatters import _format_abs_compare_value, _format_compare_value
from agent.utils.result_utils import _find_named_item, _select_extreme_item


def _fmt_trend_value(value: float, unit: str, precision: int = 2) -> str:
    if unit == "yuan":
        return f"{value / 100000000:.2f} 亿元"
    if unit == "percent":
        return f"{value:.{precision}f}%"
    return f"{value:.{precision}f}"


def _fmt_change(value: float, unit: str, precision: int) -> str:
    if unit == "yuan":
        return f"{abs(value) / 100000000:.2f} 亿元"
    if unit == "百分点":
        return f"{abs(value):.{precision}f} 个百分点"
    if unit == "percent":
        return f"{abs(value):.{precision}f}%"
    return f"{abs(value):.{precision}f}"


def _company_change_sentence(company_item: dict[str, Any], unit: str, precision: int) -> str:
    change_abs = company_item.get("absolute_change")
    if change_abs is None:
        return "有效年份不足，无法计算首末变化"
    first_value = company_item.get("first_value")
    last_value = company_item.get("last_value")
    if first_value is None or last_value is None:
        return "有效年份不足，无法计算首末变化"

    change_unit = company_item.get("change_unit") or unit
    if unit == "percent":
        if change_abs > 0:
            return f"整体提高 {_fmt_change(change_abs, change_unit, precision)}"
        if change_abs < 0:
            return f"整体下降 {_fmt_change(change_abs, change_unit, precision)}"
        return "整体持平"

    start = _fmt_trend_value(float(first_value), unit, precision)
    end = _fmt_trend_value(float(last_value), unit, precision)
    if change_abs > 0:
        return f"整体从 {start} 增至 {end}，增加 {_fmt_change(change_abs, change_unit, precision)}"
    if change_abs < 0:
        return f"整体从 {start} 降至 {end}，减少 {_fmt_change(change_abs, change_unit, precision)}"
    return f"整体从 {start} 到 {end}，保持持平"


def _company_period_change_line(
    company_item: dict[str, Any],
    start_year: int | str | None,
    end_year: int | str | None,
    unit: str,
    precision: int,
) -> str:
    """生成公司首末变化行。"""
    change_abs = company_item.get("absolute_change")
    if change_abs is None:
        return f"- {start_year} 到 {end_year} 年：有效年份不足，无法计算首末变化"

    change_unit = company_item.get("change_unit") or unit
    if unit == "percent":
        if change_abs > 0:
            return f"- {start_year} 到 {end_year} 年提高 {_fmt_change(change_abs, change_unit, precision)}"
        if change_abs < 0:
            return f"- {start_year} 到 {end_year} 年下降 {_fmt_change(change_abs, change_unit, precision)}"
        return f"- {start_year} 到 {end_year} 年持平"

    if change_abs > 0:
        return f"- {start_year} 到 {end_year} 年增加 {_fmt_change(change_abs, change_unit, precision)}"
    if change_abs < 0:
        return f"- {start_year} 到 {end_year} 年减少 {_fmt_change(change_abs, change_unit, precision)}"
    return f"- {start_year} 到 {end_year} 年持平"


def _metric_conclusion(metric_result: dict[str, Any], unit: str) -> str | None:
    latest_winner = metric_result.get("latest_year_winner_company")
    largest_change = metric_result.get("largest_absolute_change_company")
    years = metric_result.get("years") or []
    latest_year = years[-1] if years else None

    clauses: list[str] = []
    if latest_winner and latest_year:
        clauses.append(f"{latest_year} 年{latest_winner}{metric_result['metric_name']}更高")
    if largest_change:
        verb = "提高幅度" if unit == "percent" else "增加幅度"
        clauses.append(f"从首尾变化看，{largest_change}{verb}更大")
    if not clauses:
        return None
    return "结论：" + "；".join(clauses) + "。"


def _compare_trend_status(all_results: list[dict[str, Any]]) -> tuple[bool, str | None]:
    """根据趋势对比分析状态生成业务状态。"""
    statuses = {item.get("status") for item in all_results}
    unavailable_statuses = {"compare_trend_unavailable", "derived_compare_trend_unavailable"}
    partial_statuses = {
        "partial_compare_trend_unavailable",
        "partial_derived_compare_trend_unavailable",
    }
    if statuses and statuses <= unavailable_statuses:
        error_type = (
            "derived_compare_trend_unavailable"
            if "derived_compare_trend_unavailable" in statuses
            else "compare_trend_unavailable"
        )
        return False, error_type
    if statuses.intersection(unavailable_statuses) or statuses.intersection(partial_statuses):
        error_type = (
            "partial_derived_compare_trend_unavailable"
            if statuses.intersection({"derived_compare_trend_unavailable", "partial_derived_compare_trend_unavailable"})
            else "partial_compare_trend_unavailable"
        )
        return True, error_type
    return True, None


def _append_yearly_detail_lines(
    parts: list[str],
    metric_result: dict[str, Any],
    *,
    include_metric_heading: bool,
    answer_facts: list[dict[str, Any]],
) -> None:
    """追加公司趋势对比的逐年数据明细。"""
    unit = metric_result.get("unit", "")
    precision = metric_result.get("precision", 2)
    years = metric_result.get("years") or []
    start_year = years[0] if years else None
    end_year = years[-1] if years else None

    if include_metric_heading:
        parts.append(f"{metric_result['metric_name']}：")

    for company_item in metric_result.get("items", []):
        parts.append(f"- {company_item['company_name']}：")
        for point in company_item.get("series", []):
            value = point.get("value")
            if point.get("status") == "ok" and value is not None:
                parts.append(f"  - {point['year']} 年：{_fmt_trend_value(float(value), unit, precision)}")
                answer_facts.append({
                    "company_name": company_item["company_name"],
                    "metric_name": metric_result["metric_name"],
                    "report_year": point["year"],
                    "value": value,
                    "unit": unit,
                    "status": "ok",
                })
            else:
                parts.append(f"  - {point['year']} 年：无数据")
        parts.append(
            "  "
            + _company_period_change_line(
                company_item,
                start_year,
                end_year,
                unit,
                precision,
            )
        )


def _generate_compare_trend_answer(state: dict[str, Any]) -> dict:
    base_result = state.get("compare_trend_result") or []
    derived_result = state.get("derived_compare_trend_result") or []
    all_results = base_result + derived_result

    if not all_results:
        return {
            "final_answer": "公司趋势对比查询失败：分析结果为空。",
            "sql_success": False,
            "business_success": False,
            "error_type": "sql_execution_error",
            "empty_fields": [],
        }

    # 语义化回答
    from agent.nodes.answer_nodes.compare_semantic_answer import _semantic_trend_compare_answer
    semantic_answer = _semantic_trend_compare_answer(state, all_results)
    if semantic_answer:
        business_success, error_type = _compare_trend_status(all_results)
        warnings = state.get("warnings") or []
        if warnings:
            semantic_answer = "\n".join(warnings) + "\n\n" + semantic_answer
        answer_facts: list[dict[str, Any]] = []
        parts = [semantic_answer, "", "年度数据："]
        include_metric_heading = len(all_results) > 1
        for metric_result in all_results:
            _append_yearly_detail_lines(
                parts,
                metric_result,
                include_metric_heading=include_metric_heading,
                answer_facts=answer_facts,
            )
        return {
            "final_answer": "\n".join(parts),
            "answer_facts": answer_facts,
            "sql_success": True,
            "business_success": business_success,
            "error_type": error_type,
            "empty_fields": [],
        }

    parts: list[str] = []
    answer_facts: list[dict[str, Any]] = []
    years = all_results[0].get("years") or []
    start_year = years[0] if years else None
    end_year = years[-1] if years else None
    parts.append(f"{start_year} 到 {end_year} 年公司趋势对比结果如下：")

    for index, metric_result in enumerate(all_results, start=1):
        unit = metric_result.get("unit", "")
        precision = metric_result.get("precision", 2)
        parts.append(f"\n{_section_numeral(index)}、{metric_result['metric_name']}")
        for company_item in metric_result.get("items", []):
            parts.append(f"{company_item['company_name']}：")
            for point in company_item.get("series", []):
                value = point.get("value")
                if point.get("status") == "ok" and value is not None:
                    parts.append(f"- {point['year']} 年：{_fmt_trend_value(float(value), unit, precision)}")
                    answer_facts.append({
                        "company_name": company_item["company_name"],
                        "metric_name": metric_result["metric_name"],
                        "report_year": point["year"],
                        "value": value,
                        "unit": unit,
                        "status": "ok",
                    })
                else:
                    parts.append(f"- {point['year']} 年：无数据")
            parts.append(_company_change_sentence(company_item, unit, precision) + "。")

        conclusion = _metric_conclusion(metric_result, unit)
        if conclusion:
            parts.append(conclusion)

    business_success, error_type = _compare_trend_status(all_results)

    warnings = state.get("warnings") or []
    answer = "\n".join(parts)
    if warnings:
        answer = "\n".join(warnings) + "\n\n" + answer

    return {
        "final_answer": answer,
        "answer_facts": answer_facts,
        "sql_success": True,
        "business_success": business_success,
        "error_type": error_type,
        "empty_fields": [],
    }
