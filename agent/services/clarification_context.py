"""澄清上下文保存与 QueryPlan 合并规则。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from agent.services.query_plan_merge_service import merge_query_plan


TIME_RANGE_FIELDS = {
    "time_mode": "mode",
    "report_year": "report_year",
    "recent_n_years": "recent_n_years",
    "start_year": "start_year",
    "end_year": "end_year",
    "report_years": "report_years",
}


def snapshot_query_plan(state: dict[str, Any]) -> dict[str, Any] | None:
    """从当前 state 获取触发澄清时的 QueryPlan 快照。"""
    query_plan = state.get("query_plan")
    if isinstance(query_plan, dict):
        return deepcopy(query_plan)

    intent_type = state.get("intent_type")
    if not intent_type:
        return None

    time_range = deepcopy(state.get("time_range") or {})
    for state_field, plan_field in TIME_RANGE_FIELDS.items():
        if state.get(state_field) is not None:
            time_range[plan_field] = deepcopy(state[state_field])

    return {
        "intent_type": intent_type,
        "company_mentions": list(state.get("company_mentions") or []),
        "metric_mentions": list(state.get("metric_mentions") or []),
        "report_period": state.get("report_period"),
        "time_range": time_range,
        "compare_spec": deepcopy(state.get("compare_spec")),
        "rank_direction": state.get("rank_direction"),
        "limit": state.get("limit"),
        "change_metric": state.get("change_metric"),
        "need_clarification": state.get("need_clarification", False),
        "clarification_reason": state.get("clarification_question"),
    }


def infer_clarification_type(state: dict[str, Any]) -> str | None:
    """在没有标准 payload 时，根据缺失字段和 QueryPlan 粗略推断澄清类型。"""
    if state.get("clarification_type"):
        return state.get("clarification_type")

    empty_fields = state.get("empty_fields") or []
    if "companies" in empty_fields or "compare_companies" in empty_fields:
        return "missing_company"
    if "metrics" in empty_fields:
        return "missing_metric"
    if "report_year" in empty_fields or "start_year" in empty_fields or "end_year" in empty_fields:
        return "missing_year"
    if "ranking_limit" in empty_fields:
        return "missing_ranking_limit"

    plan = state.get("query_plan") if isinstance(state.get("query_plan"), dict) else {}
    if not plan:
        return None
    if not plan.get("company_mentions") and plan.get("intent_type") not in {
        "ranking_query",
        "yoy_ranking_query",
        "trend_ranking_query",
    }:
        return "missing_company"
    if not plan.get("metric_mentions"):
        return "missing_metric"
    time_range = plan.get("time_range") or {}
    if time_range.get("mode") in {None, "unspecified"} or (
        time_range.get("mode") == "single_year" and time_range.get("report_year") is None
    ):
        return "missing_year"
    if plan.get("intent_type") in {"ranking_query", "yoy_ranking_query", "trend_ranking_query"} and plan.get("limit") is None:
        return "missing_ranking_limit"
    return None


def build_pending_clarification_state(state: dict[str, Any]) -> dict[str, Any]:
    """生成保存澄清上下文所需的 AgentState 增量字段。"""
    payload = state.get("clarification_payload") or {}
    pending_query_plan = snapshot_query_plan(state)
    slot_patch = state.get("slot_patch")
    pending_clarification_type = payload.get("clarification_type") or infer_clarification_type(state)
    pending_empty_fields = list(payload.get("empty_fields") or state.get("empty_fields") or [])
    merged_query_plan = None
    if pending_clarification_type != "unsupported_intent" and isinstance(slot_patch, dict) and slot_patch:
        merged_query_plan = merge_query_plan(pending_query_plan, slot_patch, pending_empty_fields)
    return {
        "pending_query_plan": pending_query_plan,
        "pending_clarification_type": pending_clarification_type,
        "pending_empty_fields": pending_empty_fields,
        "pending_candidates": list(payload.get("clarification_candidates") or state.get("clarification_candidates") or []),
        "slot_patch": deepcopy(slot_patch) if isinstance(slot_patch, dict) else None,
        "merged_query_plan": merged_query_plan,
    }


__all__ = [
    "build_pending_clarification_state",
    "infer_clarification_type",
    "snapshot_query_plan",
]
