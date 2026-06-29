"""排名查询回答模块（V0.5.6）。

基于 analysis_result 生成 final_answer 和 answer_facts。
按 limit=1 / limit>1、desc / asc、base / derived 组合使用不同话术模板。
"""

from __future__ import annotations

from typing import Any

_PERIOD_LABELS = {
    "FY": "年度报告",
    "H1": "半年度报告",
    "Q1": "第一季度报告",
    "Q3": "前三季度报告",
}

_DIRECTION_LABELS = {
    "desc": "从高到低",
    "asc": "从低到高",
}


def _build_limit1_answer(
    metric_name: str,
    report_year: str | int,
    rank_direction: str,
    company_name: str,
    display_value: str,
) -> str:
    """limit=1 单行内联回答。"""
    direction_word = "最高" if rank_direction == "desc" else "最低"
    return f"{report_year} 年{metric_name}{direction_word}的是{company_name}，{metric_name}为{display_value}。"


def _build_limit_n_title(
    metric_name: str,
    report_year: str | int,
    rank_direction: str,
    count: int,
) -> str:
    """limit>1 列表标题。"""
    if rank_direction == "desc":
        return f"{report_year} 年{metric_name}排名前 {count} 的公司如下："
    else:
        return f"{report_year} 年{metric_name}最低的 {count} 家公司如下："


def _build_empty_message(
    metric_name: str,
    report_year: str | int,
    report_period: str,
    rank_direction: str,
    limit: int,
) -> str:
    """空结果详细说明。"""
    period_label = _PERIOD_LABELS.get(report_period, report_period)
    direction_label = _DIRECTION_LABELS.get(rank_direction, rank_direction)
    return (
        f"未查询到满足条件的数据。"
        f"查询条件：{report_year} 年，{period_label}，"
        f"指标为{metric_name}，排序方向为{direction_label}，返回数量为 {limit}。"
    )


def _build_summary_lines(metric_name: str, result_summary: dict[str, Any]) -> list[str]:
    """根据 analysis 层摘要生成补充说明。"""
    if not result_summary:
        return []

    summary = [
        "",
        f"其中，{result_summary.get('first_company_name', '')}"
        f"{result_summary.get('first_rank_label', '排名第一')}，"
        f"{metric_name}为{result_summary.get('first_display_value', '—')}；"
        f"前 {result_summary.get('topn_count')} 家公司的"
        f"{result_summary.get('average_label', '')}为{result_summary.get('average_display_value', '—')}。",
    ]

    if result_summary.get("gap_display_value"):
        compare_word = result_summary.get("gap_compare_word", "")
        gap_display = result_summary.get("gap_display_value")
        gap_ratio = result_summary.get("gap_ratio_display")
        second_company = result_summary.get("second_company_name")
        second_label = f"第二名{second_company}" if second_company else "第二名"
        if gap_ratio:
            summary.append(
                f"{result_summary.get('first_company_name', '第一名')}比"
                f"{second_label}{compare_word}{gap_display}，约{compare_word}{gap_ratio}。"
            )
        else:
            summary.append(
                f"{result_summary.get('first_company_name', '第一名')}比"
                f"{second_label}{compare_word}{gap_display}。"
            )

    return summary


def generate_ranking_answer_node(state: dict[str, Any]) -> dict:
    """排名查询回答生成。

    依赖 state.analysis_result（由 analyze_ranking_node 产出）。
    """
    analysis = state.get("analysis_result")
    if not analysis:
        return {
            "final_answer": "排名查询失败：未获取到有效分析结果。",
            "sql_success": False,
            "business_success": False,
            "error_type": state.get("error_type") or "analysis_failed",
            "empty_fields": [],
        }

    # ── 查询失败 ──
    if analysis.get("error"):
        return {
            "final_answer": f"排名查询执行失败：{analysis['error']}",
            "sql_success": False,
            "business_success": False,
            "error_type": "sql_execution_error",
            "empty_fields": [],
        }

    metric_name = analysis.get("metric_name", "")
    report_year = analysis.get("report_year", "")
    report_period = analysis.get("report_period", "FY")
    rank_direction = analysis.get("rank_direction", "desc")
    limit = analysis.get("limit", 10)
    metric_type = analysis.get("metric_type", "base")

    # ── 空结果 ──
    if analysis.get("is_empty"):
        return {
            "final_answer": _build_empty_message(
                metric_name, report_year, report_period, rank_direction, limit
            ),
            "sql_success": True,
            "business_success": False,
            "error_type": state.get("error_type") or "empty_ranking_result",
            "empty_fields": [],
        }

    rows = analysis.get("rows", [])
    if not rows:
        return {
            "final_answer": _build_empty_message(
                metric_name, report_year, report_period, rank_direction, limit
            ),
            "sql_success": True,
            "business_success": False,
            "error_type": state.get("error_type") or "empty_ranking_result",
            "empty_fields": [],
        }

    # ── 派生指标口径说明（在结果之后追加） ──
    formula_footer = ""
    if metric_type == "derived":
        sql_metadata = state.get("sql_metadata") or {}
        formula_display = sql_metadata.get("formula_display", "")
        if formula_display:
            formula_footer = f"\n\n口径：{metric_name} = {formula_display}。"

    # ── 统一结构：直接回答 → 排名列表 → 轻量摘要 → 口径说明 ──
    row_count = analysis.get("row_count", len(rows))
    count = min(limit, row_count)
    if limit == 1:
        first = rows[0]
        direction_word = "最高" if rank_direction == "desc" else "最低"
        title = (
            f"{report_year} 年{metric_name}{direction_word}的是"
            f"{first.get('company_name', '')}，{metric_name}为{first.get('display_value', '—')}。"
        )
    else:
        title = _build_limit_n_title(metric_name, report_year, rank_direction, count)

    lines = [title, ""]
    for item in rows:
        rank = item["rank"]
        name = item.get("company_name", "")
        display_value = item.get("display_value", "—")
        lines.append(f"{rank}. {name}：{display_value}")

    lines.extend(_build_summary_lines(metric_name, analysis.get("result_summary") or {}))

    return {
        "final_answer": "\n".join(lines) + formula_footer,
        "answer_facts": rows,
        "sql_success": True,
        "business_success": True,
        "error_type": None,
        "empty_fields": [],
    }


__all__ = ["generate_ranking_answer_node"]
