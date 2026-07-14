"""基于 QuerySpec 的执行能力路由。"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

from agent.nodes.global_structured_query_detector import has_out_of_scope_signal


CapabilityMode = Literal["deterministic", "flexible_sql", "composite", "clarification", "unsupported"]


class CapabilityDecision(TypedDict, total=False):
    execution_mode: CapabilityMode
    reason: str


TEMPLATE_SUPPORTED_OPERATIONS = {
    "single_metric_query",
    "multi_metric_query",
    "point_query",
    "trend_query",
    "yoy_query",
    "derived_metric_query",
    "company_compare_query",
    "company_compare_trend_query",
    "company_compare_yoy_query",
    "ranking_query",
    "yoy_ranking_query",
    "trend_ranking_query",
    "rank_position_query",
}

TEMPLATE_FILTER_LIMIT = 1


def _query_spec(state: dict[str, Any]) -> dict[str, Any]:
    spec = state.get("query_spec")
    return spec if isinstance(spec, dict) else {}


def _has_set_operations(spec: dict[str, Any]) -> bool:
    return bool(spec.get("set_operations"))


def _has_cross_metric_conditions(spec: dict[str, Any]) -> bool:
    metric_names: set[str] = set()
    for item in spec.get("filters") or []:
        if isinstance(item, dict) and isinstance(item.get("metric"), str):
            metric_names.add(item["metric"])
    for item in spec.get("sort") or []:
        if isinstance(item, dict) and isinstance(item.get("metric"), str):
            metric_names.add(item["metric"])
    return len(metric_names) > 1


def route_query_capability(state: dict[str, Any]) -> CapabilityDecision:
    """在 SQL 生成前显式决定执行能力，不依赖模板报错。"""
    if has_out_of_scope_signal(state):
        return {
            "execution_mode": "unsupported",
            "reason": "问题需要结构化数据库之外的能力。",
        }

    spec = _query_spec(state)
    if not spec:
        return {
            "execution_mode": "unsupported",
            "reason": "正式执行链要求 QuerySpec。",
        }

    if spec.get("clarification_question"):
        return {
            "execution_mode": "clarification",
            "reason": str(spec.get("clarification_question")),
        }

    if spec.get("unsupported_reason"):
        return {
            "execution_mode": "unsupported",
            "reason": str(spec["unsupported_reason"]),
        }

    if spec.get("execution_mode") == "flexible_sql" and spec.get("operation") not in TEMPLATE_SUPPORTED_OPERATIONS:
        return {
            "execution_mode": "flexible_sql",
            "reason": "QuerySpec 已声明为受控 Flexible SQL。",
        }

    if _has_set_operations(spec):
        return {
            "execution_mode": "flexible_sql",
            "reason": "QuerySpec 包含集合运算。",
        }

    if len(spec.get("filters") or []) > TEMPLATE_FILTER_LIMIT:
        return {
            "execution_mode": "flexible_sql",
            "reason": "QuerySpec 包含超过模板能力的多条件筛选。",
        }

    if _has_cross_metric_conditions(spec):
        return {
            "execution_mode": "flexible_sql",
            "reason": "QuerySpec 包含跨指标筛选或排序条件。",
        }

    operation = spec.get("operation")
    if operation in TEMPLATE_SUPPORTED_OPERATIONS:
        return {
            "execution_mode": "deterministic",
            "reason": "QuerySpec operation 命中确定性模板能力。",
        }

    return {
        "execution_mode": "unsupported",
        "reason": f"QuerySpec operation 未注册：{operation or 'unknown'}。",
    }


__all__ = [
    "CapabilityDecision",
    "TEMPLATE_FILTER_LIMIT",
    "TEMPLATE_SUPPORTED_OPERATIONS",
    "route_query_capability",
]
