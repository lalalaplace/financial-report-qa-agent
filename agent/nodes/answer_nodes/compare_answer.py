"""公司单年对比回答模块。"""

from typing import Any

from agent.services.compare_service import _get_compare_spec
from agent.utils.formatters import _format_abs_compare_value, _format_compare_value
from agent.utils.result_utils import _find_named_item, _select_extreme_item


def _fmt_value(value: float, unit: str) -> str:
    if unit == "yuan":
        return f"{value / 100000000:.2f} 亿元"
    if unit == "percent":
        return f"{value:.2f}%"
    return f"{value:.2f}"


def _fmt_diff(diff: float, diff_unit: str) -> str:
    if diff_unit == "yuan":
        return f"{diff / 100000000:.2f} 亿元"
    if diff_unit in ("percent", "百分点"):
        return f"{diff:.2f} 个百分点"
    return f"{diff:.2f}"


def _metric_block(cr: dict, report_year: int, index: int | None = None) -> str:
    ok_items = [it for it in cr["items"] if it["status"] == "ok"]
    missing_items = [it for it in cr["items"] if it["status"] != "ok"]

    if cr["status"] in {"compare_unavailable", "derived_compare_unavailable"}:
        return f"{cr['metric_name']}：所有公司均无有效数据，无法比较。"

    value_parts: list[str] = []
    for it in cr["items"]:
        if it["status"] == "ok":
            value_parts.append(f"{it['company_name']}为 {_fmt_value(it['value'], cr['unit'])}")
        elif it["status"] == "missing_record":
            value_parts.append(f"{it['company_name']}无数据")
        elif it["status"] == "empty_value":
            value_parts.append(f"{it['company_name']}数据为空")
        elif it["status"] == "empty_numerator":
            value_parts.append(f"{it['company_name']}分子为空")
        elif it["status"] == "empty_denominator":
            value_parts.append(f"{it['company_name']}分母为空")
        elif it["status"] == "zero_denominator":
            value_parts.append(f"{it['company_name']}分母为0")
        else:
            value_parts.append(f"{it['company_name']}无法计算")

    body = f"{report_year} 年，{'，'.join(value_parts)}。"

    if cr["status"] == "ok" and cr["winner_company"] and cr["diff"] is not None:
        body += f"{cr['winner_company']}更高，高出 {_fmt_diff(cr['diff'], cr.get('diff_unit', cr['unit']))}。"
    elif cr["status"] in {"partial_compare_unavailable", "partial_derived_compare_unavailable"} and ok_items:
        missing_names = "、".join(it["company_name"] for it in missing_items)
        body += f"注意：{missing_names} 数据缺失，以上对比不完整。"
        if cr["winner_company"] and cr["diff"] is not None:
            body += f"在已有数据中，{cr['winner_company']}更高，高出 {_fmt_diff(cr['diff'], cr.get('diff_unit', cr['unit']))}。"

    return body


def _generate_compare_answer(state: dict[str, Any]) -> dict:
    compare_result = state.get("compare_result") or []
    derived_result = state.get("derived_compare_result") or []
    all_results = compare_result + derived_result

    if not all_results:
        return {
            "final_answer": "对比查询失败：分析结果为空。",
            "sql_success": False,
            "business_success": False,
            "error_type": "sql_execution_error",
            "empty_fields": [],
        }

    report_year = state.get("report_year", "未知年份")

    # 语义化回答
    from agent.nodes.answer_nodes.compare_semantic_answer import _semantic_point_compare_answer
    semantic_answer = _semantic_point_compare_answer(state, all_results)
    if semantic_answer:
        statuses = {cr.get("status") for cr in all_results}
        unavailable_statuses = {"compare_unavailable", "derived_compare_unavailable"}
        partial_statuses = {"partial_compare_unavailable", "partial_derived_compare_unavailable"}
        if statuses and statuses <= unavailable_statuses:
            biz_success = False
            err_type = (
                "derived_compare_unavailable"
                if "derived_compare_unavailable" in statuses
                else "compare_unavailable"
            )
        elif statuses.intersection(unavailable_statuses) or statuses.intersection(partial_statuses):
            biz_success = True
            err_type = (
                "partial_derived_compare_unavailable"
                if statuses.intersection({"derived_compare_unavailable", "partial_derived_compare_unavailable"})
                else "partial_compare_unavailable"
            )
        else:
            biz_success = True
            err_type = None
        return {
            "final_answer": semantic_answer,
            "answer_facts": [],
            "sql_success": True,
            "business_success": biz_success,
            "error_type": err_type,
            "empty_fields": [],
        }

    if len(all_results) == 1:
        answer = _metric_block(all_results[0], report_year)
    else:
        parts = [f"{report_year} 年对比结果如下："]
        for i, cr in enumerate(all_results, start=1):
            parts.append(f"{i}. {cr['metric_name']}：")
            for it in cr["items"]:
                if it["status"] == "ok":
                    parts.append(f"   - {it['company_name']}：{_fmt_value(it['value'], cr['unit'])}")
                elif it["status"] in ("missing_record",):
                    parts.append(f"   - {it['company_name']}：无数据")
                elif it["status"] == "empty_value":
                    parts.append(f"   - {it['company_name']}：数据为空")
                elif it["status"] == "empty_numerator":
                    parts.append(f"   - {it['company_name']}：分子为空")
                elif it["status"] == "empty_denominator":
                    parts.append(f"   - {it['company_name']}：分母为空")
                elif it["status"] == "zero_denominator":
                    parts.append(f"   - {it['company_name']}：分母为0")
            if cr["status"] == "ok" and cr["winner_company"] and cr["diff"] is not None:
                parts.append(f"   结论：{cr['winner_company']}更高，高出 {_fmt_diff(cr['diff'], cr.get('diff_unit', cr['unit']))}。")
            elif cr["status"] in {"partial_compare_unavailable", "partial_derived_compare_unavailable"}:
                missing = [it for it in cr["items"] if it["status"] != "ok"]
                parts.append(f"   注意：{'、'.join(it['company_name'] for it in missing)} 数据缺失，对比不完整。")
            elif cr["status"] in {"compare_unavailable", "derived_compare_unavailable"}:
                parts.append("   结论：所有公司均无有效数据，无法比较。")
        answer = "\n".join(parts)

    statuses = {cr["status"] for cr in all_results}
    unavailable_statuses = {"compare_unavailable", "derived_compare_unavailable"}
    partial_statuses = {"partial_compare_unavailable", "partial_derived_compare_unavailable"}
    if statuses and statuses <= unavailable_statuses:
        biz_success = False
        err_type = (
            "derived_compare_unavailable"
            if "derived_compare_unavailable" in statuses
            else "compare_unavailable"
        )
    elif statuses.intersection(unavailable_statuses) or statuses.intersection(partial_statuses):
        biz_success = True
        err_type = (
            "partial_derived_compare_unavailable"
            if statuses.intersection({"derived_compare_unavailable", "partial_derived_compare_unavailable"})
            else "partial_compare_unavailable"
        )
    else:
        biz_success = True
        err_type = None

    return {
        "final_answer": answer,
        "answer_facts": [],
        "sql_success": True,
        "business_success": biz_success,
        "error_type": err_type,
        "empty_fields": [],
    }
