"""LLM 上下文路由、补丁抽取与确定性 QueryPlan 合并节点。"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any
import re

from agent.schemas.clarification import build_clarification_payload
from agent.schemas.query_plan import validate_plan
from agent.services.clarification_followup import build_clarification_context_from_state
from agent.services.llm_json_service import invoke_json_prompt
from agent.services.query_plan_merge_service import (
    clear_execution_state_after_merge,
    merge_query_plan,
    validate_slot_patch,
)


PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompts"
VALID_ROUTE_TYPES = {
    "new_query",
    "clarification_answer",
    "contextual_followup",
    "ambiguous",
    "irrelevant",
}
VALID_TARGET_CONTEXTS = {
    "none",
    "pending_query_plan",
    "last_successful_query_plan",
}
VALID_PATCH_STATUSES = {"ok", "need_clarification", "unsupported", "invalid"}
VALID_FOLLOWUP_ACTIONS = {"plan_and_run", "need_clarification", "unsupported", "invalid"}
QUERY_PLAN_KEYS = {
    "intent_type",
    "company_mentions",
    "metric_mentions",
    "report_period",
    "time_range",
    "compare_spec",
    "rank_direction",
    "limit",
    "change_metric",
    "need_clarification",
    "clarification_reason",
}
FORBIDDEN_PATCH_KEYS = {
    "sql",
    "sql_template",
    "table",
    "table_name",
    "column",
    "column_name",
    "where_clause",
    "companies",
    "metrics",
}
FOLLOWUP_ALLOWED_FIELDS = [
    "companies",
    "metrics",
    "report_year",
    "start_year",
    "end_year",
    "ranking_limit",
    "ranking_direction",
    "report_period",
]


def _compact_text(text: str) -> str:
    return "".join((text or "").strip().split())


def _company_name_from_candidate(candidate: dict[str, Any]) -> str:
    return (
        candidate.get("display_name")
        or candidate.get("stock_abbr")
        or candidate.get("normalized_name")
        or candidate.get("company_name")
        or candidate.get("code")
        or candidate.get("stock_code")
        or ""
    )


def _candidate_company_patch(state: dict[str, Any]) -> dict[str, Any] | None:
    """公司候选澄清支持候选编号和明确公司名补答。"""
    empty_fields = set(state.get("pending_empty_fields") or [])
    if "companies" not in empty_fields and "compare_companies" not in empty_fields:
        return None

    candidates = state.get("pending_candidates") or state.get("clarification_candidates") or []
    if not candidates:
        return None

    question = _compact_text(state.get("user_question", ""))
    selected: dict[str, Any] | None = None
    if re.fullmatch(r"\d+", question):
        index = int(question) - 1
        if 0 <= index < len(candidates):
            selected = candidates[index]
    else:
        for candidate in candidates:
            names = {
                str(candidate.get("display_name") or ""),
                str(candidate.get("normalized_name") or ""),
                str(candidate.get("stock_abbr") or ""),
                str(candidate.get("company_name") or ""),
                str(candidate.get("code") or ""),
                str(candidate.get("stock_code") or ""),
            }
            if any(name and (question == _compact_text(name) or question in _compact_text(name)) for name in names):
                selected = candidate
                break

    if not selected:
        return None

    company_name = _company_name_from_candidate(selected)
    if not company_name:
        return None
    return {
        "patch_status": "ok",
        "slot_patch": {"company_mentions": [company_name]},
        "route_type": "clarification_answer",
    }


def _load_prompt(name: str) -> str:
    return (PROMPT_DIR / name).read_text(encoding="utf-8")


def _json_block(title: str, payload: Any) -> str:
    return f"{title}：\n```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```"


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


def _unsupported_context_result(question: str, message: str, route_type: str = "ambiguous") -> dict[str, Any]:
    payload = build_clarification_payload(
        clarification_type="unsupported_intent",
        error_type="unsupported_query",
        empty_fields=["intent_type"],
        clarification_question="请补充一个完整的财务查询问题，例如公司、指标和年份。",
        detail={"route_type": route_type, "user_question": question, "error": message},
    )
    return {
        "route_type": route_type,
        "target_context": "none",
        "need_clarification": True,
        "clarification_type": "unsupported_intent",
        "clarification_question": payload["clarification_question"],
        "clarification_payload": payload,
        "error_type": "unsupported_query",
        "empty_fields": ["intent_type"],
    }


def _invalid_patch_result(question: str, message: str, route_type: str) -> dict[str, Any]:
    payload = build_clarification_payload(
        clarification_type="unsupported_intent",
        error_type="invalid_query",
        empty_fields=["intent_type"],
        clarification_question="无法理解这次补充信息，请重新输入完整问题。",
        detail={"route_type": route_type, "user_question": question, "error": message},
    )
    return {
        "patch_status": "invalid",
        "need_clarification": True,
        "clarification_type": "unsupported_intent",
        "clarification_question": payload["clarification_question"],
        "clarification_payload": payload,
        "error_type": "invalid_query",
        "empty_fields": ["intent_type"],
        "slot_patch": {},
    }


def _validate_router_payload(payload: dict[str, Any]) -> dict[str, Any]:
    route_type = payload.get("route_type")
    target_context = payload.get("target_context")
    if route_type not in VALID_ROUTE_TYPES:
        raise ValueError(f"未知 route_type：{route_type}")
    if target_context not in VALID_TARGET_CONTEXTS:
        raise ValueError(f"未知 target_context：{target_context}")
    return {
        "route_type": route_type,
        "target_context": target_context,
    }


def _validate_patch_payload(
    payload: dict[str, Any],
    allowed_fields: list[str],
) -> dict[str, Any]:
    patch_status = payload.get("patch_status", "ok")
    if patch_status not in VALID_PATCH_STATUSES:
        patch_status = "ok"

    result: dict[str, Any] = {"patch_status": patch_status}

    if patch_status in ("unsupported", "invalid"):
        result["slot_patch"] = {}
        return result

    if patch_status == "need_clarification":
        slot_patch = payload.get("slot_patch") or {}
        result["slot_patch"] = slot_patch
        result["clarification_question"] = payload.get("clarification_question") or "请补充更多信息。"
        result["missing_fields"] = payload.get("missing_fields") or []
        return result

    # patch_status == "ok"
    slot_patch = payload.get("slot_patch")
    if not isinstance(slot_patch, dict) or not slot_patch:
        raise ValueError("patch_status=ok 时 slot_patch 必须是非空 dict。")
    invalid_forbidden = sorted(FORBIDDEN_PATCH_KEYS & set(slot_patch))
    if invalid_forbidden:
        raise ValueError(f"slot_patch 包含禁止字段：{invalid_forbidden}")
    patch = validate_slot_patch(slot_patch, allowed_fields)
    result["slot_patch"] = patch
    return result


def _forbidden_output_keys(payload: dict[str, Any]) -> list[str]:
    forbidden = sorted(FORBIDDEN_PATCH_KEYS & set(payload))
    query_plan = payload.get("query_plan")
    if isinstance(query_plan, dict):
        forbidden.extend(f"query_plan.{key}" for key in sorted(FORBIDDEN_PATCH_KEYS & set(query_plan)))
    return forbidden


def _validate_followup_plan_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """校验 contextual_followup 直接产出的下一轮 QueryPlan draft。"""
    if not isinstance(payload, dict):
        raise ValueError("followup_result 必须是 dict。")

    forbidden_keys = _forbidden_output_keys(payload)
    if forbidden_keys:
        raise ValueError(f"followup_result 包含禁止字段：{forbidden_keys}")

    followup_action = payload.get("followup_action")
    if followup_action not in VALID_FOLLOWUP_ACTIONS:
        raise ValueError(f"未知 followup_action：{followup_action}")

    result: dict[str, Any] = {
        "followup_action": followup_action,
        "intent_candidates": payload.get("intent_candidates") or [],
        "clarification_question": payload.get("clarification_question"),
        "reason": payload.get("reason") or "",
    }

    if followup_action == "plan_and_run":
        query_plan = payload.get("query_plan")
        if not isinstance(query_plan, dict):
            raise ValueError("plan_and_run 必须提供 query_plan。")
        invalid_keys = sorted(set(query_plan) - QUERY_PLAN_KEYS)
        if invalid_keys:
            raise ValueError(f"query_plan 包含 schema 外字段：{invalid_keys}")
        normalized_plan = validate_plan(query_plan)
        if normalized_plan.get("need_clarification"):
            return {
                **result,
                "followup_action": "need_clarification",
                "query_plan": normalized_plan,
                "clarification_question": normalized_plan.get("clarification_reason") or "请补充查询条件。",
            }
        result["query_plan"] = normalized_plan
        return result

    if followup_action == "need_clarification":
        clarification_question = payload.get("clarification_question")
        if not isinstance(clarification_question, str) or not clarification_question.strip():
            raise ValueError("need_clarification 必须提供 clarification_question。")
        result["query_plan"] = None
        result["clarification_question"] = clarification_question
        return result

    result["query_plan"] = None
    return result


def _router_prompt(state: dict[str, Any]) -> str:
    context = build_clarification_context_from_state(state)
    return "\n\n".join(
        [
            _load_prompt("context_router.md"),
            _json_block("当前用户输入", state.get("user_question", "")),
            _json_block("pending_query_plan", state.get("pending_query_plan")),
            _json_block("clarification_context", context),
            _json_block("last_successful_query_plan", state.get("last_successful_query_plan")),
        ]
    )


def _patch_prompt(name: str, state: dict[str, Any], base_plan_field: str) -> str:
    return "\n\n".join(
        [
            _load_prompt(name),
            _json_block("当前用户输入", state.get("user_question", "")),
            _json_block("base_query_plan", state.get(base_plan_field)),
            _json_block("clarification_context", build_clarification_context_from_state(state)),
        ]
    )


def _followup_plan_prompt(state: dict[str, Any]) -> str:
    return "\n\n".join(
        [
            _load_prompt("followup_plan.md"),
            _json_block("当前用户输入", state.get("user_question", "")),
            _json_block("last_successful_query_plan", state.get("last_successful_query_plan")),
        ]
    )


def context_router_node(state: dict[str, Any]) -> dict[str, Any]:
    """LLM 上下文路由节点，只输出上下文关系判断。"""
    question = state.get("user_question", "")
    try:
        payload = invoke_json_prompt(_router_prompt(state))
        routed = _validate_router_payload(payload)
    except Exception as exc:
        return _unsupported_context_result(question, f"上下文路由失败：{exc}", "ambiguous")

    route_type = routed["route_type"]
    target_context = routed["target_context"]
    if route_type == "clarification_answer" and (
        target_context != "pending_query_plan" or not state.get("pending_query_plan")
    ):
        return _unsupported_context_result(question, "补答路由缺少 pending_query_plan 目标。", "ambiguous")
    if route_type == "contextual_followup" and (
        target_context != "last_successful_query_plan" or not state.get("last_successful_query_plan")
    ):
        return _unsupported_context_result(question, "续问路由缺少 last_successful_query_plan 目标。", "ambiguous")
    if route_type in {"ambiguous", "irrelevant"}:
        return _unsupported_context_result(question, f"route_type={route_type}", route_type)

    if route_type == "new_query":
        routed.update(_clear_pending_state())
    return routed


def clarification_patch_node(state: dict[str, Any]) -> dict[str, Any]:
    """LLM 澄清补答抽取节点，只输出 slot_patch。"""
    candidate_patch = _candidate_company_patch(state)
    if candidate_patch:
        return candidate_patch

    context = build_clarification_context_from_state(state)
    allowed_fields = list(context.get("empty_fields") or context.get("pending_empty_fields") or [])
    try:
        payload = invoke_json_prompt(_patch_prompt("clarification_patch.md", state, "pending_query_plan"))
        return {
            **_validate_patch_payload(payload, allowed_fields),
            "route_type": "clarification_answer",
        }
    except Exception as exc:
        return _invalid_patch_result(state.get("user_question", ""), f"澄清补丁抽取失败：{exc}", "clarification_answer")


def followup_patch_node(state: dict[str, Any]) -> dict[str, Any]:
    """LLM 上下文续问抽取节点，输出 patch_status + slot_patch。"""
    try:
        payload = invoke_json_prompt(_patch_prompt("followup_patch.md", state, "last_successful_query_plan"))
        validated = _validate_patch_payload(payload, FOLLOWUP_ALLOWED_FIELDS)
        patch_status = validated.get("patch_status", "ok")
        result: dict[str, Any] = {
            **validated,
            "route_type": "contextual_followup",
        }
        # need_clarification 时保存 pending 并携带澄清信息
        if patch_status == "need_clarification":
            slot_patch = validated.get("slot_patch") or {}
            base_plan = deepcopy(state.get("last_successful_query_plan") or {})
            # 把已提取的 slot_patch 合入 base_plan 作为 pending 的起点
            if slot_patch.get("metric_mentions"):
                base_plan["metric_mentions"] = slot_patch["metric_mentions"]
            result["need_clarification"] = True
            result["clarification_question"] = validated.get("clarification_question")
            result["missing_fields"] = validated.get("missing_fields", [])
            result["empty_fields"] = validated.get("missing_fields", [])
            result["pending_query_plan"] = base_plan
            result["pending_empty_fields"] = validated.get("missing_fields", [])
            result["pending_clarification_type"] = "missing_params"
        return result
    except Exception as exc:
        return _invalid_patch_result(state.get("user_question", ""), f"续问补丁抽取失败：{exc}", "contextual_followup")


def _followup_plan_clarification_result(
    *,
    followup_action: str,
    question: str,
    message: str,
    error_type: str,
    intent_candidates: list[Any] | None = None,
    reason: str = "",
) -> dict[str, Any]:
    payload = build_clarification_payload(
        clarification_type="unsupported_intent",
        error_type=error_type,
        empty_fields=["intent_type"],
        clarification_question=message,
        detail={
            "route_type": "contextual_followup",
            "user_question": question,
            "followup_action": followup_action,
            "intent_candidates": intent_candidates or [],
            "reason": reason,
        },
    )
    return {
        "route_type": "contextual_followup",
        "target_context": "last_successful_query_plan",
        "followup_result": {
            "followup_action": followup_action,
            "query_plan": None,
            "intent_candidates": intent_candidates or [],
            "clarification_question": message,
            "reason": reason,
        },
        "followup_action": followup_action,
        "need_clarification": True,
        "clarification_type": "unsupported_intent",
        "clarification_question": payload["clarification_question"],
        "clarification_payload": payload,
        "error_type": error_type,
        "empty_fields": ["intent_type"],
    }


def followup_plan_node(state: dict[str, Any]) -> dict[str, Any]:
    """基于上一轮成功 QueryPlan 直接生成下一轮完整 QueryPlan draft。"""
    question = state.get("user_question", "")
    if not isinstance(state.get("last_successful_query_plan"), dict):
        return _followup_plan_clarification_result(
            followup_action="unsupported",
            question=question,
            message="缺少可继承的上一轮成功查询，请重新输入完整问题。",
            error_type="unsupported_query",
            reason="不存在 last_successful_query_plan",
        )

    try:
        payload = invoke_json_prompt(_followup_plan_prompt(state))
        followup_result = _validate_followup_plan_payload(payload)
    except Exception as exc:
        return _followup_plan_clarification_result(
            followup_action="invalid",
            question=question,
            message="无法理解这次追问，请重新输入完整问题。",
            error_type="invalid_query",
            reason=str(exc),
        )

    action = followup_result["followup_action"]
    if action == "plan_and_run":
        normalized_plan = followup_result["query_plan"]
        result = clear_execution_state_after_merge({})
        result.update(_state_from_plan(normalized_plan))
        result["merged_query_plan"] = normalized_plan
        result["followup_result"] = {
            "followup_action": "plan_and_run",
            "query_plan": normalized_plan,
            "intent_candidates": followup_result.get("intent_candidates") or [],
            "clarification_question": None,
            "reason": followup_result.get("reason") or "",
        }
        result["followup_action"] = "plan_and_run"
        result["route_type"] = "contextual_followup"
        result["target_context"] = "last_successful_query_plan"
        result["need_clarification"] = False
        return result

    if action == "need_clarification":
        return _followup_plan_clarification_result(
            followup_action="need_clarification",
            question=question,
            message=followup_result["clarification_question"],
            error_type="clarification_required",
            intent_candidates=followup_result.get("intent_candidates") or [],
            reason=followup_result.get("reason") or "",
        )

    error_type = "unsupported_query" if action == "unsupported" else "invalid_query"
    message = (
        followup_result.get("clarification_question")
        or "无法基于上一轮查询理解这次追问，请重新输入完整问题。"
    )
    return _followup_plan_clarification_result(
        followup_action=action,
        question=question,
        message=message,
        error_type=error_type,
        intent_candidates=followup_result.get("intent_candidates") or [],
        reason=followup_result.get("reason") or "",
    )


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


def merge_clarification_patch_node(state: dict[str, Any]) -> dict[str, Any]:
    """确定性合并澄清补答 slot_patch。"""
    context = build_clarification_context_from_state(state)
    try:
        result = _merge_plan_patch(
            state.get("pending_query_plan"),
            state.get("slot_patch"),
            context.get("empty_fields") or context.get("pending_empty_fields") or [],
        )
    except Exception as exc:
        return _invalid_patch_result(state.get("user_question", ""), f"澄清补丁合并失败：{exc}", "clarification_answer")

    merged_query_plan = result.get("merged_query_plan")
    result.update(_clear_pending_state())
    result["slot_patch"] = deepcopy(state.get("slot_patch"))
    result["merged_query_plan"] = merged_query_plan
    result["route_type"] = "clarification_answer"
    result["target_context"] = "pending_query_plan"
    return result


def merge_followup_patch_node(state: dict[str, Any]) -> dict[str, Any]:
    """按 patch_status 分流合并上下文续问 slot_patch。"""
    patch_status = state.get("patch_status", "ok")

    # need_clarification：保存新的 pending，不进入执行链路
    if patch_status == "need_clarification":
        slot_patch = state.get("slot_patch") or {}
        # 基于 last_successful_query_plan 和已有 slot_patch 构造待补完的 pending
        base_plan = deepcopy(state.get("last_successful_query_plan") or {})
        if slot_patch.get("metric_mentions"):
            base_plan["metric_mentions"] = slot_patch["metric_mentions"]
        pending_plan = base_plan

        result: dict[str, Any] = {
            "patch_status": "need_clarification",
            "route_type": "contextual_followup",
            "target_context": "last_successful_query_plan",
            "need_clarification": True,
            "clarification_type": "missing_params",
            "clarification_question": state.get("clarification_question") or "请补充更多信息。",
            "empty_fields": state.get("missing_fields") or state.get("empty_fields") or [],
            "pending_query_plan": pending_plan,
            "pending_empty_fields": state.get("missing_fields") or state.get("empty_fields") or [],
            "pending_clarification_type": "missing_params",
            "slot_patch": slot_patch,
            "sql": None,
            "query_result": None,
            "final_answer": None,
            "merged_query_plan": None,
        }
        return result

    # unsupported / invalid：构建澄清响应
    if patch_status in ("unsupported", "invalid"):
        return _invalid_patch_result(
            state.get("user_question", ""),
            f"patch_status={patch_status}",
            "contextual_followup",
        )

    # patch_status == "ok"：正常合并
    try:
        result = _merge_plan_patch(
            state.get("last_successful_query_plan"),
            state.get("slot_patch"),
            FOLLOWUP_ALLOWED_FIELDS,
        )
    except Exception as exc:
        return _invalid_patch_result(state.get("user_question", ""), f"续问补丁合并失败：{exc}", "contextual_followup")

    result["patch_status"] = "ok"
    result["slot_patch"] = deepcopy(state.get("slot_patch"))
    result["route_type"] = "contextual_followup"
    result["target_context"] = "last_successful_query_plan"
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
    "followup_plan_node",
    "merge_clarification_patch_node",
    "merge_followup_patch_node",
    "remember_successful_query_plan_node",
]
