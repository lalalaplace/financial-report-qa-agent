"""全公司范围结构化查询与外部能力检测。"""

from __future__ import annotations

from typing import Any


STRUCTURED_QUERY_KEYWORDS = (
    "哪些公司", "哪些企业", "哪家公司", "上市公司", "前", "top", "Top", "TOP",
    "最高", "最低", "超过", "低于", "高于", "大于", "小于", "同比", "增长",
    "下降", "上升", "同时", "并且", "其中", "范围内", "排序", "为正", "为负",
)

OUT_OF_SCOPE_KEYWORDS = (
    "未来", "预测", "股价", "股票价格", "新闻", "管理层访谈", "管理层解释",
    "政策", "投资建议", "PDF", "pdf", "原文", "尚未入库", "未入库",
)

AMBIGUOUS_EVALUATION_KEYWORDS = (
    "表现最好", "财务最好", "最好的企业", "最好的公司",
)


def _has_company_scope(state: dict[str, Any]) -> bool:
    return bool(state.get("company_mentions") or state.get("companies"))


def _has_metric_signal(state: dict[str, Any]) -> bool:
    return bool(state.get("metric_mentions") or state.get("metrics"))


def _has_time_signal(state: dict[str, Any]) -> bool:
    if isinstance(state.get("report_year"), int):
        return True
    time_range = state.get("time_range")
    if not isinstance(time_range, dict):
        return False
    if isinstance(time_range.get("report_year"), int):
        return True
    report_years = time_range.get("report_years")
    return isinstance(report_years, list) and bool(report_years)


def has_out_of_scope_signal(state: dict[str, Any]) -> bool:
    """判断问题是否明确依赖结构化财报数据库之外的能力。"""
    question = str(state.get("user_question") or "")
    return any(keyword in question for keyword in OUT_OF_SCOPE_KEYWORDS)


def is_ambiguous_global_evaluation(state: dict[str, Any]) -> bool:
    question = str(state.get("user_question") or "")
    return any(keyword in question for keyword in AMBIGUOUS_EVALUATION_KEYWORDS)


def is_global_structured_query(state: dict[str, Any]) -> bool:
    """识别无需指定公司的全公司筛选或排序问题。"""
    if _has_company_scope(state) or not _has_metric_signal(state) or not _has_time_signal(state):
        return False
    if has_out_of_scope_signal(state) or is_ambiguous_global_evaluation(state):
        return False
    question = str(state.get("user_question") or "")
    return any(keyword in question for keyword in STRUCTURED_QUERY_KEYWORDS)


def mark_global_structured_query(state: dict[str, Any]) -> dict[str, Any]:
    if not is_global_structured_query(state):
        return {}
    return {
        "company_source": "all_companies",
        "is_global_structured_query": True,
        "empty_fields": [
            field for field in (state.get("empty_fields") or [])
            if field not in {"company", "companies"}
        ],
    }


__all__ = [
    "has_out_of_scope_signal", "is_ambiguous_global_evaluation",
    "is_global_structured_query", "mark_global_structured_query",
]
