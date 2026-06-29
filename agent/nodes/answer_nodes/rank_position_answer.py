"""指定公司排名位置查询回答节点。"""

from __future__ import annotations

from typing import Any


_DIRECTION_LABELS = {
    "desc": "从高到低",
    "asc": "从低到高",
}


def _build_position_text(result_summary: dict[str, Any]) -> str:
    """根据 analysis 层摘要生成分位说明。"""
    if not result_summary:
        return ""

    return (
        f"\n\n按名次位置看，{result_summary.get('company_name', '')}"
        f"处于前 {result_summary.get('percentile_bucket')}% 区间，"
        f"属于{result_summary.get('position_zone')}。"
    )


def generate_rank_position_answer_node(state: dict[str, Any]) -> dict:
    analysis = state.get("analysis_result") or {}
    if not analysis:
        return {
            "final_answer": "排名位置查询失败：未获得有效分析结果。",
            "sql_success": False,
            "business_success": False,
            "error_type": state.get("error_type") or "analysis_failed",
            "empty_fields": [],
        }

    company_name = analysis.get("company_name", "")
    metric_name = analysis.get("metric_name", "")
    report_year = analysis.get("report_year", "")
    rank_direction = analysis.get("rank_direction", "desc")
    direction_label = _DIRECTION_LABELS.get(rank_direction, rank_direction)

    if analysis.get("is_empty"):
        metric_type = analysis.get("metric_type", "base")
        if metric_type == "derived":
            reason = "可能原因是分子或分母指标缺失，或分母为 0。"
        else:
            reason = "可能原因是该公司该年度该指标为空，或无法参与当前排名计算。"
        return {
            "final_answer": f"未查询到{company_name} {report_year} 年{metric_name}的可排名数据。{reason}",
            "sql_success": True,
            "business_success": False,
            "error_type": state.get("error_type") or "empty_rank_position_result",
            "empty_fields": [],
        }

    rank_no = analysis.get("rank_no")
    total_count = analysis.get("total_count")
    answer = (
        f"{company_name} {report_year} 年{metric_name}为 {analysis.get('display_value')}，"
        f"{direction_label}排名第 {rank_no} / {total_count}。"
    )
    answer += _build_position_text(analysis.get("result_summary") or {})
    if analysis.get("formula_text"):
        answer += f"\n\n口径：{analysis['formula_text']}。"

    return {
        "final_answer": answer,
        "answer_facts": [analysis],
        "sql_success": True,
        "business_success": True,
        "error_type": None,
        "empty_fields": [],
    }


__all__ = ["generate_rank_position_answer_node"]
