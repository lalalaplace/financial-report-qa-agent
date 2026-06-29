"""区间增长排名查询回答节点。"""

from __future__ import annotations

from typing import Any


_PERIOD_LABELS = {
    "FY": "年度报告",
    "H1": "半年度报告",
    "Q1": "第一季度报告",
    "Q3": "前三季度报告",
}


def _build_empty_message(
    metric_name: str,
    start_year: int | str,
    end_year: int | str,
    report_period: str,
    limit: int,
) -> str:
    period_label = _PERIOD_LABELS.get(report_period, report_period)
    return (
        f"未查询到满足条件的数据。查询条件：{start_year} 到 {end_year} 年，{period_label}，"
        f"指标为{metric_name}，按区间增长率排序，返回数量为 {limit}。"
    )


def _build_summary_lines(result_summary: dict[str, Any]) -> list[str]:
    """根据 analysis 层摘要生成区间增长排名补充说明。"""
    if not result_summary:
        return []

    summary = [
        "",
        f"其中，{result_summary.get('first_company_name', '')}{result_summary.get('first_rank_label', '')}，"
        f"为 {result_summary.get('first_rate_display', '—')}。",
        f"前 {result_summary.get('topn_count')} 家公司的{result_summary.get('average_label', '')}为 "
        f"{result_summary.get('average_rate_display', '—')}。",
    ]

    if result_summary.get("gap_percentage_points"):
        second_company = result_summary.get("second_company_name")
        second_label = f"第二名{second_company}" if second_company else "第二名"
        summary.append(
            f"{result_summary.get('first_company_name', '第一名')}比"
            f"{second_label}{result_summary.get('gap_compare_word', '')} "
            f"{result_summary.get('gap_percentage_points')} 个百分点。"
        )

    summary.append(
        f"前 {result_summary.get('topn_count')} 家公司中，"
        f"正增长 {result_summary.get('positive_count')} 家，"
        f"负增长 {result_summary.get('negative_count')} 家。"
    )
    return summary


def generate_trend_ranking_answer_node(state: dict[str, Any]) -> dict:
    analysis = state.get("analysis_result")
    if not analysis:
        return {
            "final_answer": "区间增长排名查询失败：未获取到有效分析结果。",
            "sql_success": False,
            "business_success": False,
            "error_type": state.get("error_type") or "analysis_failed",
            "empty_fields": [],
        }

    if analysis.get("error"):
        return {
            "final_answer": f"区间增长排名查询执行失败：{analysis['error']}",
            "sql_success": False,
            "business_success": False,
            "error_type": "sql_execution_error",
            "empty_fields": [],
        }

    metric_name = analysis.get("metric_name", "")
    start_year = analysis.get("start_year", "")
    end_year = analysis.get("end_year", "")
    report_period = analysis.get("report_period", "FY")
    rank_direction = analysis.get("rank_direction", "desc")
    limit = analysis.get("limit", 10)
    rows = analysis.get("rows", [])

    if analysis.get("is_empty") or not rows:
        return {
            "final_answer": _build_empty_message(metric_name, start_year, end_year, report_period, limit),
            "sql_success": True,
            "business_success": False,
            "error_type": state.get("error_type") or "empty_trend_ranking_result",
            "empty_fields": [],
        }

    row_count = analysis.get("row_count", len(rows))
    count = min(limit, row_count)
    if rank_direction == "desc":
        title = f"{start_year} 到 {end_year} 年{metric_name}增长率排名前 {count} 的公司如下："
        rate_label = "增长率"
    else:
        title = f"{start_year} 到 {end_year} 年{metric_name}下降幅度最大或增长率最低的前 {count} 家公司如下："
        rate_label = "区间变化率"

    lines = [title, ""]
    for item in rows:
        lines.append(
            f"{item['rank']}. {item.get('company_name', '')}："
            f"{rate_label} {item.get('display_growth_rate', '—')}，"
            f"{start_year} 年为 {item.get('display_start_value', '—')}，"
            f"{end_year} 年为 {item.get('display_end_value', '—')}"
        )

    lines.extend(_build_summary_lines(analysis.get("result_summary") or {}))

    return {
        "final_answer": "\n".join(lines),
        "answer_facts": rows,
        "sql_success": True,
        "business_success": True,
        "error_type": None,
        "empty_fields": [],
    }


__all__ = ["generate_trend_ranking_answer_node"]
