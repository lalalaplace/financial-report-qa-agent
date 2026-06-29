"""上下文路由与 QueryPlan 补丁合并节点。"""

from __future__ import annotations

from typing import Any

from agent.schemas.clarification import build_clarification_payload
from agent.schemas.query_plan import validate_plan
from agent.services.clarification_followup import (
    build_clarification_context_from_state,
    detect_and_extract_contextual_patch,
    detect_and_extract_slot_patch,
    has_pending_query_plan,
)
from agent.services.query_plan_merge_service import (
    clear_execution_state_after_merge,
    merge_query_plan,
)


def _state_from_plan(plan: dict[str, Any]) -> dict[str, Any]:
    time_range = plan["time_range"]
    return {
        "query_plan": plan,
        "intent_type": plan["intent_type"],
        "company_mentions": plan["company_mentions"],
        "metric_mentions": plan["metric_mentions"],
        "time_range": time_range,
        "report_period": None if plan["report_period"] == "unspecified" else plan["report_period"],
        "time_mode": time_range["mode"],
        "report_year": time_range.get("report_year"),
        "recent_n_years": time_range.get("recent_n_years"),
        "start_year": time_range.get("start_year"),
        "end_year": time_range.get("end_year"),
        "report_years": time_range.get("report_years") or [],
        "compare_spec": plan.get("compare_spec"),
        "rank_direction": plan.get("rank_direction"),
        "limit": plan.get("limit"),
        "change_metric": plan.get("change_metric"),
        "need_clarification": plan.get("need_clarification", False),
        "clarification_question": plan.get("clarification_reason"),
    }


def _clear_pending_state() -> dict[str, Any]:
    return {
        "pending_query_plan": None,
        "pending_clarification_type": None,
        "pending_empty_fields": [],
        "pending_candidates": [],
        "slot_patch": None,
        "merged_query_plan": None,
    }


def _unsupported_context_result(question: str) -> dict[str, Any]:
    payload = build_clarification_payload(
        clarification_type="unsupported_intent",
        error_type="unsupported_query",
        empty_fields=["intent_type"],
        clarification_question="请补充一个完整的财务查询问题，例如公司、指标和年份。",
        detail={"route_type": "ambiguous", "user_question": question},
    )
    return {
        "route_type": "ambiguous",
        "need_clarification": True,
        "clarification_type": "unsupported_intent",
        "clarification_question": payload["clarification_question"],
        "clarification_payload": payload,
        "error_type": "unsupported_query",
        "empty_fields": ["intent_type"],
    }


def _looks_irrelevant(question: str) -> bool:
    compact = "".join((question or "").split())
    if not compact:
        return True
    financial_markers = {
        "收入",
        "营收",
        "利润",
        "资产",
        "负债",
        "现金流",
        "净利率",
        "同比",
        "增长",
        "排名",
        "年报",
    }
    year_like = any(str(year) in compact for year in range(1990, 2031))
    if year_like or any(marker in compact for marker in financial_markers):
        return False
    return len(compact) <= 8


def context_router_node(state: dict[str, Any]) -> dict[str, Any]:
    """在 planner 前判断当前输入应走新问题、澄清补答、上下文追问还是兜底澄清。"""
    question = state.get("user_question", "")

    if has_pending_query_plan(state):
        clarification_context = build_clarification_context_from_state(state)
        followup_result = detect_and_extract_slot_patch(
            user_input=question,
            pending_query_plan=state["pending_query_plan"],
            clarification_context=clarification_context,
        )
        if followup_result.is_clarification_answer:
            return {
                "route_type": "clarification_answer",
                "slot_patch": followup_result.slot_patch,
            }
        return {"route_type": "new_query", **_clear_pending_state()}

    last_plan = state.get("last_successful_query_plan")
    contextual_result = detect_and_extract_contextual_patch(question, last_plan)
    if contextual_result.is_clarification_answer:
        return {
            "route_type": "contextual_followup",
            "slot_patch": contextual_result.slot_patch,
        }

    if _looks_irrelevant(question):
        return _unsupported_context_result(question)

    return {"route_type": "new_query"}


def _merge_plan_patch(
    base_plan: dict[str, Any] | None,
    slot_patch: dict[str, Any] | None,
    empty_fields: list[str] | None,
) -> dict[str, Any]:
    merged_plan = merge_query_plan(base_plan, slot_patch, empty_fields)
    if merged_plan is None:
        raise ValueError("缺少可合并的 QueryPlan。")
    normalized_plan = validate_plan(merged_plan)
    result = clear_execution_state_after_merge({})
    result.update(_state_from_plan(normalized_plan))
    result["merged_query_plan"] = normalized_plan
    result["need_clarification"] = normalized_plan.get("need_clarification", False)
    return result


def clarification_patch_node(state: dict[str, Any]) -> dict[str, Any]:
    """把澄清补答 slot_patch 合并回 pending_query_plan。"""
    clarification_context = build_clarification_context_from_state(state)
    try:
        result = _merge_plan_patch(
            state.get("pending_query_plan"),
            state.get("slot_patch"),
            clarification_context.get("empty_fields") or clarification_context.get("pending_empty_fields") or [],
        )
    except Exception as exc:
        payload = build_clarification_payload(
            clarification_type="unsupported_intent",
            error_type="invalid_query",
            empty_fields=["intent_type"],
            clarification_question="无法把补充信息合并到上一轮查询，请重新输入完整问题。",
            detail={"error": str(exc), "route_type": "clarification_answer"},
        )
        return {
            "need_clarification": True,
            "clarification_type": "unsupported_intent",
            "clarification_question": payload["clarification_question"],
            "clarification_payload": payload,
            "error_type": "invalid_query",
            "empty_fields": ["intent_type"],
        }

    merged_query_plan = result.get("merged_query_plan")
    result.update(_clear_pending_state())
    result["slot_patch"] = state.get("slot_patch")
    result["merged_query_plan"] = merged_query_plan
    result["route_type"] = "clarification_answer"
    return result


def followup_patch_node(state: dict[str, Any]) -> dict[str, Any]:
    """把上下文追问 slot_patch 合并回 last_successful_query_plan。"""
    allowed_fields = [
        "companies",
        "metrics",
        "report_year",
        "start_year",
        "end_year",
        "ranking_limit",
        "ranking_direction",
        "report_period",
    ]
    try:
        result = _merge_plan_patch(
            state.get("last_successful_query_plan"),
            state.get("slot_patch"),
            allowed_fields,
        )
    except Exception as exc:
        payload = build_clarification_payload(
            clarification_type="unsupported_intent",
            error_type="invalid_query",
            empty_fields=["intent_type"],
            clarification_question="无法理解这次追问，请补充公司、指标和年份后重新提问。",
            detail={"error": str(exc), "route_type": "contextual_followup"},
        )
        return {
            "need_clarification": True,
            "clarification_type": "unsupported_intent",
            "clarification_question": payload["clarification_question"],
            "clarification_payload": payload,
            "error_type": "invalid_query",
            "empty_fields": ["intent_type"],
        }

    result["slot_patch"] = state.get("slot_patch")
    result["route_type"] = "contextual_followup"
    return result


def remember_successful_query_plan_node(state: dict[str, Any]) -> dict[str, Any]:
    """成功回答后保存可供下一轮上下文追问使用的 QueryPlan。"""
    if state.get("business_success") is not True:
        return {}
    if state.get("need_clarification") is True:
        return {}
    if state.get("error_type"):
        return {}
    query_plan = state.get("query_plan")
    if not isinstance(query_plan, dict):
        return {}
    return {"last_successful_query_plan": query_plan}


__all__ = [
    "clarification_patch_node",
    "context_router_node",
    "followup_patch_node",
    "remember_successful_query_plan_node",
]
