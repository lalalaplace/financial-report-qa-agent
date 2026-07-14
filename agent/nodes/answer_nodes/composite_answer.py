"""复合查询回答生成节点。"""

from __future__ import annotations

from typing import Any

from agent.nodes.answer_router import route_answer_generation
from agent.nodes.llm_answer_synthesis_node import llm_answer_synthesis_node


def _format_amount(value: Any) -> str:
    """格式化金额类数值。"""
    if value is None:
        return "无数据"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{number / 100_000_000:,.2f} 亿元"


def _format_rate(value: Any) -> str:
    """格式化同比率。"""
    if value is None:
        return "无法计算"
    try:
        return f"{float(value) * 100:.2f}%"
    except (TypeError, ValueError):
        return str(value)


def _task_items(task_results: dict[str, dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    return [(task_id, result) for task_id, result in task_results.items() if isinstance(result, dict)]


def _find_analysis(task_results: dict[str, dict[str, Any]], analysis_type: str) -> dict[str, Any] | None:
    for _, result in _task_items(task_results):
        analysis = result.get("analysis_result")
        if isinstance(analysis, dict) and analysis.get("analysis_type") == analysis_type:
            return analysis
    return None


def _ranking_rows(task_results: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    ranking = _find_analysis(task_results, "ranking")
    if not ranking:
        return []
    rows = ranking.get("rows")
    return rows if isinstance(rows, list) else []


def _company_set_yoy_rows(task_results: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    yoy = _find_analysis(task_results, "company_set_yoy")
    if not yoy:
        return []
    rows = yoy.get("rows")
    return rows if isinstance(rows, list) else []


def _secondary_yoy_ranking_rows(task_results: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    ranking = _find_analysis(task_results, "yoy_ranking_from_artifact")
    if not ranking:
        return []
    rows = ranking.get("rows")
    return rows if isinstance(rows, list) else []


def _metric_text(row: dict[str, Any]) -> str:
    metric_name = row.get("metric_name") or row.get("metric_key") or "指标"
    current_value = _format_amount(row.get("current_value"))
    yoy_rate = _format_rate(row.get("yoy_rate"))
    status = row.get("status")
    if status and status != "ok":
        return f"{metric_name}：{current_value}，同比{yoy_rate}（{status}）"
    return f"{metric_name}：{current_value}，同比{yoy_rate}"


def _build_ranking_section(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return []
    lines = ["排名结果："]
    for index, row in enumerate(rows, start=1):
        rank = row.get("rank") or index
        company_name = row.get("company_name") or row.get("stock_code") or "未知公司"
        value = row.get("display_value") or _format_amount(row.get("metric_value"))
        lines.append(f"{rank}. {company_name}：{value}")
    return lines


def _build_yoy_section(
    ranking_rows: list[dict[str, Any]],
    yoy_rows: list[dict[str, Any]],
) -> list[str]:
    if not yoy_rows:
        return []

    rows_by_company: dict[str, list[dict[str, Any]]] = {}
    for row in yoy_rows:
        stock_code = str(row.get("stock_code") or "")
        rows_by_company.setdefault(stock_code, []).append(row)

    ordered_companies = [
        {
            "stock_code": str(row.get("stock_code") or ""),
            "company_name": row.get("company_name") or row.get("stock_code") or "未知公司",
        }
        for row in ranking_rows
        if row.get("stock_code")
    ]
    if not ordered_companies:
        seen_codes: set[str] = set()
        ordered_companies = []
        for row in yoy_rows:
            stock_code = str(row.get("stock_code") or "")
            if stock_code in seen_codes:
                continue
            seen_codes.add(stock_code)
            ordered_companies.append(
                {
                    "stock_code": stock_code,
                    "company_name": row.get("company_name") or stock_code or "未知公司",
                }
            )

    lines = ["这些公司的同比情况："]
    for index, company in enumerate(ordered_companies, start=1):
        metric_rows = rows_by_company.get(company["stock_code"], [])
        metric_parts = [_metric_text(row) for row in metric_rows]
        metric_text = "；".join(metric_parts) if metric_parts else "无同比数据"
        lines.append(f"{index}. {company['company_name']}：{metric_text}")
    return lines


def _build_secondary_section(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return []
    lines = ["二次排序结果："]
    for row in rows:
        rank = row.get("rank")
        company_name = row.get("company_name") or row.get("stock_code") or "未知公司"
        metric_name = row.get("metric_name") or row.get("metric_key") or "指标"
        lines.append(f"{rank}. {company_name}：{metric_name}同比{_format_rate(row.get('yoy_rate'))}")
    return lines


def generate_composite_answer_node(state: dict[str, Any]) -> dict[str, Any]:
    """把复合查询 task_results 汇总为最终中文回答。"""
    if state.get("need_clarification"):
        return {}

    task_results = state.get("task_results")
    if not isinstance(task_results, dict) or not task_results:
        return {
            "final_answer": "复合查询失败：未获得可汇总的任务结果。",
            "final_answer": "复合查询失败：" + "；".join(detail_parts) + "。",
            "business_success": False,
            "error_type": state.get("composite_error_type") or "missing_task_results",
        }

    if state.get("composite_success") is not True:
        failed_task_id = None
        failed_stage = None
        error_type = state.get("composite_error_type") or "composite_task_failed"
        error_message = None
        template_gap_reason = None
        sql_generation_mode = None
        analysis = state.get("composite_analysis_result")
        if isinstance(analysis, dict):
            failed_task_id = analysis.get("failed_task_id")
            failed_stage = analysis.get("failed_stage")
            error_type = analysis.get("error_type") or error_type
            error_message = analysis.get("error_message")
            template_gap_reason = analysis.get("template_gap_reason")
            sql_generation_mode = analysis.get("sql_generation_mode")
        detail_parts = [
            f"失败任务：{failed_task_id or 'unknown'}",
            f"失败阶段：{failed_stage or 'unknown'}",
            f"错误类型：{error_type}",
        ]
        if error_message:
            detail_parts.append(f"错误信息：{error_message}")
        if template_gap_reason:
            detail_parts.append(f"模板缺口：{template_gap_reason}")
        if sql_generation_mode:
            detail_parts.append(f"SQL生成模式：{sql_generation_mode}")
        return {
            "final_answer": f"复合查询失败：任务 {failed_task_id or 'unknown'} 未成功完成。",
            "business_success": False,
            "final_answer": "复合查询失败：" + "；".join(detail_parts) + "。",
            "error_type": state.get("composite_error_type") or "composite_task_failed",
            "error_type": error_type,
        }

    if route_answer_generation(state) == "llm_answer":
        return llm_answer_synthesis_node(state)

    ranking_rows = _ranking_rows(task_results)
    yoy_rows = _company_set_yoy_rows(task_results)
    secondary_rows = _secondary_yoy_ranking_rows(task_results)

    sections: list[str] = []
    sections.extend(_build_ranking_section(ranking_rows))
    if sections and yoy_rows:
        sections.append("")
    sections.extend(_build_yoy_section(ranking_rows, yoy_rows))
    if sections and secondary_rows:
        sections.append("")
    sections.extend(_build_secondary_section(secondary_rows))

    if not sections:
        sections = ["复合查询已完成，但当前结果类型暂不支持自动汇总展示。"]

    return {
        "final_answer": "\n".join(sections),
        "business_success": True,
        "error_type": None,
        "analysis_result": state.get("composite_analysis_result"),
    }


__all__ = ["generate_composite_answer_node"]
