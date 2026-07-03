"""公司同比对比回答模块。"""

from typing import Any

from agent.nodes.answer_nodes.common import _fmt_yuan_value, _section_numeral
from agent.services.compare_service import _get_compare_spec
from agent.utils.formatters import _format_abs_compare_value, _format_compare_value
from agent.utils.result_utils import _find_named_item, _select_extreme_item


def _fmt_base_value(value: float, unit: str) -> str:
    if unit == "yuan":
        yi = value / 100000000
        return f"{yi:.2f} 亿元" if abs(yi) >= 1 else f"{value:.0f} 元"
    if unit == "percent":
        return f"{value:.2f}%"
    return f"{value:.2f}"


def _compare_yoy_status(all_results: list[dict[str, Any]]) -> tuple[bool, str | None]:
    """根据同比对比分析状态生成业务状态。"""
    statuses = {item.get("status") for item in all_results}
    unavailable_statuses = {"compare_yoy_unavailable", "derived_compare_yoy_unavailable"}
    partial_statuses = {"partial_compare_yoy_unavailable", "partial_derived_compare_yoy_unavailable"}
    if statuses and statuses <= unavailable_statuses:
        return False, "compare_yoy_unavailable"
    if statuses.intersection(unavailable_statuses) or statuses.intersection(partial_statuses):
        return True, "partial_compare_yoy_unavailable"
    return True, None


def _append_yoy_detail_lines(
    parts: list[str],
    metric_result: dict[str, Any],
    *,
    include_metric_heading: bool,
    answer_facts: list[dict[str, Any]],
) -> None:
    """追加公司同比对比的支撑数据。"""
    if include_metric_heading:
        parts.append(f"{metric_result['metric_name']}：")

    is_derived = metric_result.get("metric_type") == "derived"
    unit = metric_result.get("unit", "yuan")
    precision = metric_result.get("precision", 2)
    current_year = metric_result.get("current_year")
    previous_year = metric_result.get("previous_year")

    for item in metric_result.get("items", []):
        company_name = item.get("company_name", "")
        status = item.get("status")
        if status == "ok":
            if is_derived:
                change = item.get("absolute_change")
                if change is None:
                    change_text = "变化无法计算"
                elif change > 0:
                    change_text = f"提高 {abs(change):.{precision}f} {item.get('change_unit', '百分点')}"
                elif change < 0:
                    change_text = f"下降 {abs(change):.{precision}f} {item.get('change_unit', '百分点')}"
                else:
                    change_text = "持平"
                parts.append(
                    f"- {company_name}：{previous_year} 年 "
                    f"{_fmt_base_value(item['previous_value'], unit)}，"
                    f"{current_year} 年 {_fmt_base_value(item['current_value'], unit)}，"
                    f"{change_text}"
                )
            else:
                yoy_rate = item.get("yoy_rate")
                if yoy_rate is None:
                    yoy_text = "同比无法计算"
                elif yoy_rate > 0:
                    yoy_text = f"同比增长 {yoy_rate * 100:.2f}%"
                elif yoy_rate < 0:
                    yoy_text = f"同比下降 {abs(yoy_rate) * 100:.2f}%"
                else:
                    yoy_text = "同比持平"
                parts.append(
                    f"- {company_name}：{previous_year} 年 "
                    f"{_fmt_base_value(item['previous_value'], unit)}，"
                    f"{current_year} 年 {_fmt_base_value(item['current_value'], unit)}，"
                    f"{yoy_text}"
                )
            answer_facts.append({
                "company_name": company_name,
                "metric_name": metric_result["metric_name"],
                "metric_type": metric_result.get("metric_type", "base"),
                "current_year": current_year,
                "previous_year": previous_year,
                "current_value": item.get("current_value"),
                "previous_value": item.get("previous_value"),
                "absolute_change": item.get("absolute_change"),
                "yoy_rate": item.get("yoy_rate"),
                "unit": unit,
                "status": status,
            })
        elif "current" in str(status):
            parts.append(f"- {company_name}：缺少或无法使用 {current_year} 年数据")
        elif "previous" in str(status):
            parts.append(f"- {company_name}：缺少或无法使用 {previous_year} 年数据")
        else:
            parts.append(f"- {company_name}：无法计算同比")

    if metric_result.get("status") == "ok" and metric_result.get("winner_company"):
        if is_derived:
            diff = metric_result.get("diff_change")
            if diff is not None:
                parts.append(
                    f"- 差值：{metric_result['winner_company']}高出 "
                    f"{diff:.{precision}f} {metric_result.get('diff_unit', '')}"
                )
        else:
            diff = metric_result.get("diff_yoy_rate")
            if diff is not None:
                parts.append(
                    f"- 差值：{metric_result['winner_company']}同比增速高出 "
                    f"{diff * 100:.2f} 个百分点"
                )


def _generate_compare_yoy_answer(state: dict[str, Any]) -> dict:
    compare_yoy_result = state.get("compare_yoy_result") or []
    derived_yoy_result = state.get("derived_compare_yoy_result") or []
    all_results = compare_yoy_result + derived_yoy_result

    if not all_results:
        return {
            "final_answer": "公司同比对比查询失败：分析结果为空。",
            "sql_success": False,
            "business_success": False,
            "error_type": "sql_execution_error",
            "empty_fields": [],
        }

    # 语义化回答
    from agent.nodes.answer_nodes.compare_semantic_answer import _semantic_yoy_compare_answer
    semantic_answer = _semantic_yoy_compare_answer(state, all_results)
    if semantic_answer:
        business_success, error_type = _compare_yoy_status(all_results)
        warnings = state.get("warnings") or []
        if warnings:
            semantic_answer = "\n".join(warnings) + "\n\n" + semantic_answer
        answer_facts: list[dict[str, Any]] = []
        parts = [semantic_answer, "", "同比数据："]
        include_metric_heading = len(all_results) > 1
        for metric_result in all_results:
            _append_yoy_detail_lines(
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
    report_year = state.get("report_year", "未知年份")
    prev_year = report_year - 1 if isinstance(report_year, int) else None
    parts.append(f"{report_year} 年公司同比对比结果如下：")

    section_index = 0
    for metric_result in all_results:
        section_index += 1
        is_derived = metric_result.get("metric_type") == "derived"
        unit = metric_result.get("unit", "yuan")
        precision = metric_result.get("precision", 2)
        metric_status = metric_result.get("status", "ok")
        all_ok = metric_status == "ok"

        parts.append(f"\n{_section_numeral(section_index)}、{metric_result['metric_name']}")

        ok_items: list[dict[str, Any]] = []
        missing_prev: list[str] = []
        missing_curr: list[str] = []

        for item in metric_result.get("items", []):
            status = item["status"]
            if status == "ok":
                ok_items.append(item)
            elif "missing_previous" in status or "empty_previous" in status:
                missing_prev.append(item["company_name"])
            elif "missing_current" in status or "empty_current" in status:
                missing_curr.append(item["company_name"])

            if is_derived:
                if status == "ok":
                    change = item["absolute_change"]
                    if change is not None:
                        if change > 0:
                            direction = "提高"
                        elif change < 0:
                            direction = "下降"
                        else:
                            direction = "持平"
                        change_unit = item.get("change_unit", "百分点")
                        parts.append(
                            f"- {item['company_name']}：{prev_year} 年 "
                            f"{_fmt_base_value(item['previous_value'] or 0, unit)}，"
                            f"{report_year} 年 "
                            f"{_fmt_base_value(item['current_value'] or 0, unit)}，"
                            f"变化 {direction} {abs(change):.{precision}f} {change_unit}"
                        )
                    answer_facts.append({
                        "company_name": item["company_name"],
                        "metric_name": metric_result["metric_name"],
                        "metric_type": "derived",
                        "report_year": report_year,
                        "previous_year": prev_year,
                        "current_value": item["current_value"],
                        "previous_value": item["previous_value"],
                        "absolute_change": item["absolute_change"],
                        "unit": unit,
                        "status": status,
                    })
                elif status in ("missing_current_record",):
                    parts.append(f"- {item['company_name']}：缺少 {report_year} 年数据，无法计算")
                elif status in ("missing_previous_record",):
                    parts.append(f"- {item['company_name']}：缺少 {prev_year} 年数据，无法计算同比变化")
                elif "current" in status and "denominator" in status and "zero" in status:
                    parts.append(f"- {item['company_name']}：{report_year} 年分母为零，无法计算")
                elif "previous" in status and "denominator" in status and "zero" in status:
                    parts.append(f"- {item['company_name']}：{prev_year} 年分母为零，无法计算同比变化")
                elif "empty" in status:
                    which = "当年" if "current" in status else "上年"
                    field = "分子" if "numerator" in status else "分母"
                    parts.append(f"- {item['company_name']}：{which}{field}为空")
            else:
                if status == "ok":
                    yoy_pct = f"{item['yoy_rate'] * 100:+.2f}%" if item['yoy_rate'] is not None else "N/A"
                    direction = "增长" if item['yoy_rate'] and item['yoy_rate'] > 0 else (
                        "下降" if item['yoy_rate'] and item['yoy_rate'] < 0 else "持平"
                    )
                    parts.append(
                        f"- {item['company_name']}：{prev_year} 年 "
                        f"{_fmt_base_value(item['previous_value'], unit)}，"
                        f"{report_year} 年 "
                        f"{_fmt_base_value(item['current_value'], unit)}，"
                        f"同比 {direction} {yoy_pct}"
                    )
                    if item.get("warning") == "negative_previous_value":
                        parts.append("  [注意] 上年值为负，同比率解读需谨慎")
                    answer_facts.append({
                        "company_name": item["company_name"],
                        "metric_name": metric_result["metric_name"],
                        "metric_type": "base",
                        "report_year": report_year,
                        "previous_year": prev_year,
                        "current_value": item["current_value"],
                        "previous_value": item["previous_value"],
                        "absolute_change": item["absolute_change"],
                        "yoy_rate": item["yoy_rate"],
                        "status": status,
                    })
                elif status == "missing_current":
                    parts.append(f"- {item['company_name']}：缺少 {report_year} 年数据，无法计算")
                elif status == "empty_current":
                    parts.append(f"- {item['company_name']}：{report_year} 年数据为空")
                elif status == "missing_previous":
                    parts.append(f"- {item['company_name']}：缺少 {prev_year} 年数据，无法计算同比变化")
                elif status == "empty_previous":
                    parts.append(f"- {item['company_name']}：{prev_year} 年数据为空")
                elif status == "zero_previous":
                    parts.append(
                        f"- {item['company_name']}：{prev_year} 年基数为零，"
                        f"{report_year} 年 {_fmt_base_value(item['current_value'], unit)}，无法计算同比率"
                    )

        if all_ok and ok_items and len(ok_items) >= 2:
            if is_derived:
                winner = metric_result.get("winner_company")
                diff = metric_result.get("diff_change")
                diff_unit = metric_result.get("diff_unit", "")
                if winner and diff is not None:
                    parts.append(
                        f"结论：{winner} 同比提升幅度最大，"
                        f"高出 {diff:.{precision}f} {diff_unit}。"
                    )
            else:
                winner = metric_result.get("winner_company")
                diff = metric_result.get("diff_yoy_rate")
                if winner and diff is not None:
                    parts.append(
                        f"结论：{winner} 同比增速更高，"
                        f"高出 {diff * 100:.2f} 个百分点。"
                    )
        elif not all_ok and ok_items:
            available_names = [it["company_name"] for it in ok_items]
            missing_all = missing_prev + missing_curr
            if missing_all:
                parts.append(
                    f"注：{'、'.join(missing_all)} 缺少必要年份数据，"
                    f"无法完成完整同比对比。已查询到 {'、'.join(available_names)} 的完整数据。"
                )

    business_success, error_type = _compare_yoy_status(all_results)

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
