"""语义化对比回答：解析 compare_spec operator 生成自然语言结论。"""

from typing import Any

from agent.state import AgentState
from agent.services.compare_service import _get_compare_spec
from agent.utils.formatters import _format_abs_compare_value, _format_compare_value
from agent.utils.result_utils import _find_named_item, _select_extreme_item


def _semantic_point_compare_answer(state: AgentState, results: list[dict[str, Any]]) -> str | None:
    compare_spec = _get_compare_spec(state)
    operator = compare_spec.get("operator", "general")
    if operator == "general":
        return None

    report_year = state.get("report_year", "未知年份")
    lines: list[str] = []
    for result in results:
        if result.get("status") in {"compare_unavailable", "derived_compare_unavailable"}:
            lines.append(f"{result['metric_name']}：所有公司均无有效数据，无法比较。")
            continue

        unit = result.get("diff_unit") or result.get("unit", "")
        precision = int(result.get("precision", 2))
        ok_items = [item for item in result.get("items", []) if item.get("status") == "ok"]
        if not ok_items:
            lines.append(f"{result['metric_name']}：无有效数据，无法比较。")
            continue

        high_item = _select_extreme_item(ok_items, "value", choose_max=True)
        low_item = _select_extreme_item(ok_items, "value", choose_max=False)
        diff = result.get("diff")
        metric_name = result["metric_name"]

        if operator == "higher" and high_item:
            lines.append(
                f"{report_year} 年{metric_name}更高的是{high_item['company_name']}，"
                f"为{_format_compare_value(high_item['value'], result.get('unit', ''), precision)}。"
            )
        elif operator == "lower" and low_item:
            lines.append(
                f"{report_year} 年{metric_name}更低的是{low_item['company_name']}，"
                f"为{_format_compare_value(low_item['value'], result.get('unit', ''), precision)}。"
            )
        elif operator == "difference" and high_item and low_item and diff is not None:
            lines.append(
                f"{report_year} 年{metric_name}相差{_format_compare_value(diff, unit, precision)}，"
                f"{high_item['company_name']}高于{low_item['company_name']}。"
            )
        elif operator in {"higher_than", "lower_than"}:
            subject = _find_named_item(ok_items, compare_spec.get("subject_company"))
            reference = _find_named_item(ok_items, compare_spec.get("reference_company"))
            if not subject or not reference:
                lines.append(f"{metric_name}：未能在结果中匹配到定向比较的两家公司。")
                continue
            value_diff = float(subject["value"]) - float(reference["value"])
            abs_diff_text = _format_abs_compare_value(value_diff, unit, precision)
            if operator == "higher_than":
                if value_diff > 0:
                    lines.append(f"{subject['company_name']}高于{reference['company_name']}，高出{abs_diff_text}。")
                elif value_diff < 0:
                    lines.append(f"{subject['company_name']}并不高于{reference['company_name']}，而是低{abs_diff_text}。")
                else:
                    lines.append(f"{subject['company_name']}并不高于{reference['company_name']}，两者持平。")
            else:
                if value_diff < 0:
                    lines.append(f"{subject['company_name']}低于{reference['company_name']}，低{abs_diff_text}。")
                elif value_diff > 0:
                    lines.append(f"{subject['company_name']}并不低于{reference['company_name']}，而是高{abs_diff_text}。")
                else:
                    lines.append(f"{subject['company_name']}并不低于{reference['company_name']}，两者持平。")

    return "\n".join(lines) if lines else None


def _semantic_trend_compare_answer(state: AgentState, results: list[dict[str, Any]]) -> str | None:
    compare_spec = _get_compare_spec(state)
    operator = compare_spec.get("operator", "general")
    if operator == "general":
        return None

    lines: list[str] = []
    for result in results:
        metric_name = result["metric_name"]
        unit = result.get("unit", "")
        precision = int(result.get("precision", 2))
        years = result.get("years") or []
        start_year = years[0] if years else ""
        end_year = years[-1] if years else ""
        ok_items = [item for item in result.get("items", []) if item.get("status") == "ok"]
        if not ok_items:
            lines.append(f"{metric_name}：无有效趋势数据，无法比较。")
            continue

        if operator == "higher":
            item = _select_extreme_item(ok_items, "last_value", choose_max=True)
            if item:
                lines.append(f"{end_year} 年{metric_name}更高的是{item['company_name']}。")
        elif operator == "lower":
            item = _select_extreme_item(ok_items, "last_value", choose_max=False)
            if item:
                lines.append(f"{end_year} 年{metric_name}更低的是{item['company_name']}。")
        elif operator == "larger_decline":
            item = _select_extreme_item(
                [item for item in ok_items if item.get("absolute_change") is not None and item["absolute_change"] < 0],
                "absolute_change",
                choose_max=False,
            )
            if item:
                change_unit = item.get("change_unit") or unit
                lines.append(
                    f"{start_year} 到 {end_year} 年{metric_name}下降更多的是{item['company_name']}，"
                    f"下降{_format_abs_compare_value(item['absolute_change'], change_unit, precision)}。"
                )
        elif operator == "faster_growth":
            item = _select_extreme_item(ok_items, "change_rate", choose_max=True)
            if item and item.get("change_rate") is not None:
                lines.append(f"{start_year} 到 {end_year} 年{metric_name}增长更快的是{item['company_name']}。")
            else:
                item = _select_extreme_item(ok_items, "absolute_change", choose_max=True)
                if item:
                    lines.append(f"{start_year} 到 {end_year} 年{metric_name}增长更多的是{item['company_name']}。")
        elif operator == "larger_change":
            increase_items = [item for item in ok_items if item.get("absolute_change") is not None and item["absolute_change"] > 0]
            item = _select_extreme_item(increase_items, "absolute_change", choose_max=True)
            if not item:
                item = _select_extreme_item(ok_items, "absolute_change", choose_max=True, abs_value=True)
            if item:
                change_unit = item.get("change_unit") or unit
                lines.append(
                    f"{start_year} 到 {end_year} 年{metric_name}变化幅度更大的是{item['company_name']}，"
                    f"变化{_format_abs_compare_value(item['absolute_change'], change_unit, precision)}。"
                )
        elif operator in {"difference", "higher_than", "lower_than"}:
            subject = _find_named_item(ok_items, compare_spec.get("subject_company"))
            reference = _find_named_item(ok_items, compare_spec.get("reference_company"))
            if operator == "difference":
                high_item = _select_extreme_item(ok_items, "last_value", choose_max=True)
                low_item = _select_extreme_item(ok_items, "last_value", choose_max=False)
                if high_item and low_item:
                    diff = float(high_item["last_value"]) - float(low_item["last_value"])
                    lines.append(
                        f"{end_year} 年{metric_name}相差{_format_compare_value(diff, unit, precision)}，"
                        f"{high_item['company_name']}高于{low_item['company_name']}。"
                    )
            elif subject and reference:
                value_diff = float(subject["last_value"]) - float(reference["last_value"])
                diff_text = _format_abs_compare_value(value_diff, unit, precision)
                if operator == "higher_than":
                    if value_diff > 0:
                        lines.append(f"{end_year} 年{subject['company_name']}高于{reference['company_name']}，高出{diff_text}。")
                    elif value_diff < 0:
                        lines.append(f"{end_year} 年{subject['company_name']}并不高于{reference['company_name']}，而是低{diff_text}。")
                    else:
                        lines.append(f"{end_year} 年{subject['company_name']}并不高于{reference['company_name']}，两者持平。")
                else:
                    if value_diff < 0:
                        lines.append(f"{end_year} 年{subject['company_name']}低于{reference['company_name']}，低{diff_text}。")
                    elif value_diff > 0:
                        lines.append(f"{end_year} 年{subject['company_name']}并不低于{reference['company_name']}，而是高{diff_text}。")
                    else:
                        lines.append(f"{end_year} 年{subject['company_name']}并不低于{reference['company_name']}，两者持平。")

    return "\n".join(lines) if lines else None


def _semantic_yoy_compare_answer(state: AgentState, results: list[dict[str, Any]]) -> str | None:
    compare_spec = _get_compare_spec(state)
    operator = compare_spec.get("operator", "general")
    if operator == "general":
        return None

    lines: list[str] = []
    for result in results:
        metric_name = result["metric_name"]
        is_derived = result.get("metric_type") == "derived"
        compare_field = "absolute_change" if is_derived else "yoy_rate"
        diff_unit = result.get("diff_unit") or "百分点"
        precision = int(result.get("precision", 2))
        year = result.get("current_year")
        ok_items = [item for item in result.get("items", []) if item.get("status") == "ok"]
        if not ok_items:
            lines.append(f"{metric_name}：无有效同比数据，无法比较。")
            continue

        def _yoy_diff_text(raw_diff: float) -> str:
            if is_derived:
                return _format_abs_compare_value(raw_diff, diff_unit, precision)
            return _format_abs_compare_value(raw_diff * 100, "百分点", 2)

        if operator in {"higher", "faster_growth"}:
            item = _select_extreme_item(ok_items, compare_field, choose_max=True)
            if item:
                verb = "同比变化更高" if is_derived else "同比增速更高"
                lines.append(f"{year} 年{metric_name}{verb}的是{item['company_name']}。")
        elif operator == "lower":
            item = _select_extreme_item(ok_items, compare_field, choose_max=False)
            if item:
                lines.append(f"{year} 年{metric_name}同比更低的是{item['company_name']}。")
        elif operator == "larger_change":
            item = _select_extreme_item(ok_items, "absolute_change", choose_max=True, abs_value=True)
            if item:
                lines.append(f"{year} 年{metric_name}同比变化幅度更大的是{item['company_name']}。")
        elif operator == "larger_decline":
            item = _select_extreme_item(
                [item for item in ok_items if item.get("absolute_change") is not None and item["absolute_change"] < 0],
                "absolute_change",
                choose_max=False,
            )
            if item:
                lines.append(f"{year} 年{metric_name}同比下降更多的是{item['company_name']}。")
        elif operator == "difference":
            high_item = _select_extreme_item(ok_items, compare_field, choose_max=True)
            low_item = _select_extreme_item(ok_items, compare_field, choose_max=False)
            if high_item and low_item:
                raw_diff = float(high_item[compare_field]) - float(low_item[compare_field])
                lines.append(
                    f"{year} 年{metric_name}同比差值为{_yoy_diff_text(raw_diff)}，"
                    f"{high_item['company_name']}高于{low_item['company_name']}。"
                )
        elif operator in {"higher_than", "lower_than"}:
            subject = _find_named_item(ok_items, compare_spec.get("subject_company"))
            reference = _find_named_item(ok_items, compare_spec.get("reference_company"))
            if not subject or not reference:
                lines.append(f"{metric_name}：未能在结果中匹配到定向比较的两家公司。")
                continue
            raw_diff = float(subject[compare_field]) - float(reference[compare_field])
            diff_text = _yoy_diff_text(raw_diff)
            if operator == "higher_than":
                if raw_diff > 0:
                    lines.append(f"{subject['company_name']}高于{reference['company_name']}，高出{diff_text}。")
                elif raw_diff < 0:
                    lines.append(f"{subject['company_name']}并不高于{reference['company_name']}，而是低{diff_text}。")
                else:
                    lines.append(f"{subject['company_name']}并不高于{reference['company_name']}，两者持平。")
            else:
                if raw_diff < 0:
                    lines.append(f"{subject['company_name']}低于{reference['company_name']}，低{diff_text}。")
                elif raw_diff > 0:
                    lines.append(f"{subject['company_name']}并不低于{reference['company_name']}，而是高{diff_text}。")
                else:
                    lines.append(f"{subject['company_name']}并不低于{reference['company_name']}，两者持平。")

    return "\n".join(lines) if lines else None


__all__ = ['_semantic_point_compare_answer', '_semantic_trend_compare_answer', '_semantic_yoy_compare_answer']
