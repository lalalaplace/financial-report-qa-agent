"""SQL 生成路由层：模板优先，模板缺口再进入受控 LLM SQL。"""

from __future__ import annotations

from typing import Any, Callable

from agent.nodes.answer_nodes.clarify_answer import generate_unsupported_answer_node
from agent.nodes.capability_router import route_query_capability
from agent.nodes.global_structured_query_detector import (
    has_out_of_scope_signal,
)
from agent.nodes.llm_sql_node import generate_llm_sql_node
from agent.routing import route_by_intent


TemplateNode = Callable[[dict[str, Any]], dict[str, Any]]

BLOCKED_CAPABILITY_FLAGS = {
    "prediction",
    "external_data",
    "text_understanding",
    "pdf_evidence",
}

TEMPLATE_GAP_ERRORS = {
    "TEMPLATE_GAP",
    "template_gap",
    "template_missing",
    "unsupported_intent",
    "unsupported_metric_type",
    "multiple_companies_not_supported",
    "multiple_metrics_not_supported",
    "invalid_composite_yoy_template",
}

def _has_template_sql(payload: dict[str, Any]) -> bool:
    for key in (
        "sql",
        "yoy_sqls",
        "derived_sqls",
        "derived_trend_sqls",
        "derived_yoy_sqls",
        "compare_sqls",
        "compare_trend_sqls",
        "compare_yoy_sqls",
        "derived_compare_sqls",
        "derived_compare_trend_sqls",
        "derived_compare_yoy_sqls",
    ):
        if payload.get(key):
            return True
    return False


def is_template_gap_error(error_type: str | None) -> bool:
    """判断错误是否属于模板能力缺口，而不是模板执行失败或槽位缺失。"""
    return error_type in TEMPLATE_GAP_ERRORS


def build_llm_sql_requirement_from_state(state: dict[str, Any]) -> dict[str, Any]:
    """兼容旧调用：从已标准化 state 构造最小受控 SQL 需求。"""
    metrics = state.get("metrics") or []
    metric_mentions = list(state.get("metric_mentions") or [])
    if not metric_mentions:
        metric_mentions = [
            m.get("metric_name") or m.get("metric_key")
            for m in metrics
            if isinstance(m, dict) and (m.get("metric_name") or m.get("metric_key"))
        ]

    task_plan = state.get("task_plan") if isinstance(state.get("task_plan"), dict) else {}
    ranking = task_plan.get("ranking") if isinstance(task_plan.get("ranking"), dict) else {}
    intent_type = state.get("intent_type") or task_plan.get("intent") or "general_structured_query"
    report_year = state.get("report_year")
    if report_year is None and isinstance(state.get("time_range"), dict):
        report_year = state["time_range"].get("report_year")

    return {
        "can_use_llm_sql": True,
        "reason": "database_answerable_template_gap",
        "requirement_type": "general_structured_query",
        "template_status": "missing",
        "read_only": True,
        "metric_mentions": metric_mentions,
        "company_mentions": list(state.get("company_mentions") or []),
        "report_year": report_year,
        "report_period": state.get("report_period"),
        "company_universe": {"type": "all_companies", "companies": list(state.get("companies") or [])},
        "base_universe": {
            "type": "ranking" if "ranking" in str(intent_type) else "filter",
            "metric_mention": ranking.get("rank_by") or (metric_mentions[0] if metric_mentions else None),
            "calculation": "metric_value",
            "rank_direction": state.get("rank_direction") or ranking.get("rank_direction"),
            "limit": state.get("limit") or ranking.get("limit"),
            "filters": [],
        },
        "metrics": [
            {"metric_mention": mention, "role": "output_metric", "calculation": "metric_value"}
            for mention in metric_mentions
        ],
        "filters": task_plan.get("filters", []),
        "order_by": {
            "metric_mention": ranking.get("rank_by") or (metric_mentions[0] if metric_mentions else None),
            "calculation": "metric_value",
            "direction": state.get("rank_direction") or ranking.get("rank_direction") or "desc",
        },
        "limit": state.get("limit") or ranking.get("limit"),
        "expected_output": {"grain": "company", "must_include": []},
        "needs": {
            "prediction": False,
            "external_data": False,
            "text_understanding": False,
            "pdf_evidence": False,
        },
        "clarification_question": None,
        "unsupported_reason": None,
    }


def can_use_llm_sql(state: dict[str, Any]) -> tuple[bool, str | None]:
    """判断当前任务是否允许调用受控 LLM SQL。"""
    requirement = state.get("llm_sql_requirement")
    if not isinstance(requirement, dict):
        requirement = build_llm_sql_requirement_from_state(state)
        state["llm_sql_requirement"] = requirement
    if requirement.get("can_use_llm_sql") is False:
        return False, requirement.get("clarification_question") or requirement.get("unsupported_reason") or "LLM SQL requirement 拒绝。"
    if requirement.get("reason") not in {None, "database_answerable_template_gap"}:
        return False, f"LLM SQL requirement reason 不允许执行：{requirement.get('reason')}"
    if requirement.get("template_status") != "missing" and requirement.get("reason") != "database_answerable_template_gap":
        return False, "模板状态不是明确 missing。"
    if requirement.get("read_only") is not True:
        return False, "任务不是只读查询。"
    if not (state.get("query_plan") or state.get("task_plan") or requirement):
        return False, "缺少 QueryPlan 或 task_plan。"
    if not (state.get("metrics") or requirement.get("metric_mentions") or requirement.get("metrics")):
        return False, "缺少已标准化指标。"
    if requirement.get("report_year") is None and state.get("report_year") is None:
        return False, "缺少年份槽位。"
    needs = requirement.get("needs") or {}
    blocked = sorted(flag for flag in BLOCKED_CAPABILITY_FLAGS if needs.get(flag))
    if blocked:
        return False, f"任务涉及非结构化数据库能力：{', '.join(blocked)}。"
    return True, None


def _route_requirement_result(requirement_result: dict[str, Any]) -> str:
    requirement = requirement_result.get("llm_sql_requirement")
    reason = requirement.get("reason") if isinstance(requirement, dict) else None
    if requirement_result.get("can_use_llm_sql") is True:
        return "llm_sql"
    if reason == "need_clarification" or requirement_result.get("need_clarification"):
        return "clarification"
    if reason in {"unsupported", "unsafe_or_out_of_scope"}:
        return "unsupported"
    if reason == "template_should_handle":
        return "router_conflict"
    return "unsupported"


def route_sql_generation(
    state: dict[str, Any],
    *,
    template_nodes: dict[str, TemplateNode],
) -> dict[str, Any]:
    """执行 SQL 生成路由，返回模板或受控 LLM SQL 节点的状态增量。"""
    capability = route_query_capability(state)
    capability_mode = capability["execution_mode"]

    if has_out_of_scope_signal(state):
        return {
            "need_clarification": False,
            "sql_generation_mode": "unsupported",
            "error_type": "UNSUPPORTED_OUT_OF_SCOPE",
            "sql_generation_error_type": "UNSUPPORTED_OUT_OF_SCOPE",
            "sql_generation_error_message": "问题需要预测、新闻、股价、PDF 原文或外部信息，当前结构化数据库无法回答。",
            "capability_decision": capability,
            "final_sql_generation_mode": "unsupported",
            "can_use_llm_sql": False,
        }

    if capability_mode == "clarification":
        return {
            "need_clarification": True,
            "clarification_question": capability.get("reason"),
            "sql_generation_mode": "unsupported",
            "sql_generation_error_type": "NEED_CLARIFICATION",
            "sql_generation_error_message": capability.get("reason"),
            "capability_decision": capability,
            "final_sql_generation_mode": "unsupported",
            "can_use_llm_sql": False,
        }

    if capability_mode == "unsupported":
        return {
            "need_clarification": False,
            "sql_generation_mode": "unsupported",
            "error_type": "UNSUPPORTED_OUT_OF_SCOPE",
            "sql_generation_error_type": "UNSUPPORTED_OUT_OF_SCOPE",
            "sql_generation_error_message": capability.get("reason"),
            "capability_decision": capability,
            "final_sql_generation_mode": "unsupported",
            "can_use_llm_sql": False,
        }

    if capability_mode == "deterministic":
        route_name = route_by_intent(state)
        template_node = template_nodes.get(route_name)
        template_result = template_node(state) if template_node else generate_unsupported_answer_node(state)
        result = dict(template_result)
        has_sql = _has_template_sql(template_result)
        result.setdefault("sql_generation_mode", "template" if has_sql else "unsupported")
        result.setdefault("template_gap_reason", None)
        result.setdefault("sql_generation_error_type", None if has_sql else result.get("error_type") or "TEMPLATE_NOT_AVAILABLE")
        result.setdefault("sql_generation_error_message", result.get("clarification_question"))
        result.setdefault("capability_decision", capability)
        result.setdefault("final_sql_generation_mode", result.get("sql_generation_mode"))
        return result

    llm_state = dict(state)
    llm_state["need_clarification"] = False
    llm_state["clarification_question"] = None
    llm_state["capability_decision"] = capability

    existing_requirement = llm_state.get("llm_sql_requirement")
    if isinstance(existing_requirement, dict) and (
        existing_requirement.get("can_use_llm_sql") is True
        or existing_requirement.get("template_status") == "missing"
    ):
        existing_requirement.setdefault("can_use_llm_sql", True)
        existing_requirement.setdefault("reason", "database_answerable_template_gap")
        requirement_result = {
            "llm_sql_requirement": existing_requirement,
            "llm_sql_requirement_parsed": existing_requirement,
            "can_use_llm_sql": True,
            "requirement_type": existing_requirement.get("requirement_type"),
            "error_type": "LLM_SQL_REQUIREMENT_BUILT",
        }
    else:
        requirement = build_llm_sql_requirement_from_state(llm_state)
        requirement_result = {
            "llm_sql_requirement": requirement,
            "llm_sql_requirement_parsed": requirement,
            "can_use_llm_sql": True,
            "requirement_type": requirement.get("requirement_type"),
            "error_type": "LLM_SQL_REQUIREMENT_BUILT",
        }

    llm_state.update(requirement_result)
    requirement_route = _route_requirement_result(requirement_result)
    if requirement_route == "llm_sql":
        allowed, reason = can_use_llm_sql(llm_state)
        if not allowed:
            return {
                **requirement_result,
                "need_clarification": False,
                "sql_generation_mode": "unsupported",
                "capability_decision": capability,
                "error_type": "LLM_SQL_REQUIREMENT_REJECTED",
                "sql_generation_error_type": "LLM_SQL_REQUIREMENT_REJECTED",
                "sql_generation_error_message": reason,
                "final_sql_generation_mode": "unsupported",
            }
        result = generate_llm_sql_node(llm_state)
        result.setdefault("capability_decision", capability)
        result.setdefault("requirement_type", requirement_result.get("requirement_type"))
        result.setdefault("can_use_llm_sql", True)
        result.setdefault("final_sql_generation_mode", result.get("sql_generation_mode"))
        return result

    requirement_result.setdefault("capability_decision", capability)
    requirement_result.setdefault("final_sql_generation_mode", "unsupported")
    return requirement_result


__all__ = [
    "build_llm_sql_requirement_from_state",
    "can_use_llm_sql",
    "is_template_gap_error",
    "route_sql_generation",
]
