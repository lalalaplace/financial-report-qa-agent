"""从 graph.py 拆出的业务实现。"""

from __future__ import annotations

from agent.constants import DEFAULT_QUERY_TYPE
from agent.state import AgentState


def route_after_context_router(state: AgentState) -> str:
    route_type = state.get("route_type") or "new_query"
    if route_type == "clarification_answer":
        return "clarification_patch"
    if route_type == "contextual_followup":
        return "followup_plan"
    if route_type in {"ambiguous", "irrelevant"} or state.get("need_clarification"):
        return "build_clarification_response"
    return "llm_plan_query"


def route_after_patch_node(state: AgentState) -> str:
    if state.get("need_clarification"):
        return "build_clarification_response"
    route_type = state.get("route_type")
    if route_type == "clarification_answer":
        return "merge_clarification_patch"
    if route_type == "contextual_followup":
        return "merge_followup_patch"
    return "build_clarification_response"


def should_end_after_plan(state: AgentState) -> str:
    if state.get("need_clarification"):
        return "build_clarification_response"
    return "resolve_company"

def should_end_after_slot_check(state: AgentState) -> str:
    if state.get("need_clarification"):
        return "build_clarification_response"
    return route_by_intent(state)

def route_trend_metric_type(state: AgentState) -> str:
    """trend_query 路由：根据指标类型分流到对应的 SQL 生成节点。"""
    metrics = state.get("metrics", [])
    metric_types = {m.get("metric_type", "base") for m in metrics}
    if metric_types == {"derived"}:
        return "generate_derived_trend_sql"
    if metric_types <= {"base"}:
        return "generate_trend_sql"
    return "generate_unsupported_answer"

def route_yoy_metric_type(state: AgentState) -> str:
    """yoy_query 路由：base → 原 yoy SQL，derived → 派生 yoy SQL，混合 → unsupported"""
    metrics = state.get("metrics", [])
    metric_types = {m.get("metric_type", "base") for m in metrics}
    if metric_types == {"derived"}:
        return "generate_derived_yoy_sql"
    if metric_types <= {"base"}:
        return "generate_yoy_sql"
    return "generate_unsupported_answer"

def route_compare_metric_type(state: AgentState) -> str:
    """company_compare_query 路由：全 base → compare_sql，全 derived → derived_compare_sql，混合 → unsupported。"""
    metrics = state.get("metrics", [])
    metric_types = {m.get("metric_type", "base") for m in metrics}
    if metric_types == {"derived"}:
        return "generate_derived_compare_sql"
    if metric_types <= {"base"}:
        return "generate_compare_sql"
    return "generate_unsupported_answer"

def route_compare_yoy_metric_type(state: AgentState) -> str:
    """company_compare_yoy_query 路由：base/derived 分别路由，混合 → unsupported。"""
    metrics = state.get("metrics", [])
    metric_types = {m.get("metric_type", "base") for m in metrics}
    if metric_types == {"derived"}:
        return "generate_derived_compare_yoy_sql"
    if metric_types <= {"base"}:
        return "generate_compare_yoy_sql"
    return "generate_unsupported_answer"

def route_compare_trend_metric_type(state: AgentState) -> str:
    """company_compare_trend_query 路由：base 与 derived 分流，混合不支持。"""
    metrics = state.get("metrics", [])
    metric_types = {m.get("metric_type", "base") for m in metrics}
    if metric_types == {"derived"}:
        return "generate_derived_compare_trend_sql"
    if metric_types <= {"base"}:
        return "generate_compare_trend_sql"
    return "generate_unsupported_answer"

def route_by_intent(state: AgentState) -> str:
    intent = state.get("intent_type") or "unknown"
    if intent == "trend_query":
        return route_trend_metric_type(state)
    if intent == "yoy_query":
        return route_yoy_metric_type(state)
    if intent == "company_compare_query":
        return route_compare_metric_type(state)
    if intent == "company_compare_trend_query":
        return route_compare_trend_metric_type(state)
    if intent == "company_compare_yoy_query":
        return route_compare_yoy_metric_type(state)
    if intent == "yoy_ranking_query":
        metrics = state.get("metrics", [])
        metric_types = {m.get("metric_type", "base") for m in metrics}
        if metric_types <= {"base"}:
            return "generate_yoy_ranking_sql"
        return "generate_unsupported_answer"
    if intent == "trend_ranking_query":
        metrics = state.get("metrics", [])
        metric_types = {m.get("metric_type", "base") for m in metrics}
        if metric_types <= {"base"}:
            return "generate_trend_ranking_sql"
        return "generate_unsupported_answer"
    if intent == "rank_position_query":
        metrics = state.get("metrics", [])
        metric_types = {m.get("metric_type", "base") for m in metrics}
        if metric_types <= {"base", "derived"}:
            return "generate_rank_position_sql"
        return "generate_unsupported_answer"
    routing = {
        "single_metric_query": "generate_point_sql",
        "multi_metric_query": "generate_point_sql",
        "derived_metric_query": "generate_derived_sql",
        "ranking_query": "generate_ranking_sql",
    }
    return routing.get(intent, "generate_answer")

def should_end_after_sql_generation(state: AgentState) -> str:
    if state.get("need_clarification"):
        return "build_clarification_response"
    return "review_and_execute_sql"

def route_analysis(state: AgentState) -> str:
    """根据 intent_type 路由到对应的分析节点。"""
    intent_type = state.get("intent_type") or DEFAULT_QUERY_TYPE
    if intent_type == "yoy_query":
        metrics = state.get("metrics") or []
        metric_types = {m.get("metric_type", "base") for m in metrics}
        if metric_types == {"derived"}:
            return "analyze_derived_yoy"
        return "analyze_yoy"
    if intent_type == "derived_metric_query":
        return "analyze_derived_metric"
    if intent_type == "trend_query":
        metrics = state.get("metrics") or []
        metric_types = {m.get("metric_type", "base") for m in metrics}
        if metric_types == {"derived"}:
            return "analyze_derived_trend"
    if intent_type == "company_compare_query":
        metrics = state.get("metrics") or []
        metric_types = {m.get("metric_type", "base") for m in metrics}
        if metric_types == {"derived"}:
            return "analyze_derived_compare"
        return "analyze_compare"
    if intent_type == "company_compare_trend_query":
        metrics = state.get("metrics") or []
        metric_types = {m.get("metric_type", "base") for m in metrics}
        if metric_types == {"derived"}:
            return "analyze_derived_compare_trend"
        return "analyze_compare_trend"
    if intent_type == "company_compare_yoy_query":
        metrics = state.get("metrics") or []
        metric_types = {m.get("metric_type", "base") for m in metrics}
        if metric_types == {"derived"}:
            return "analyze_derived_compare_yoy"
        return "analyze_compare_yoy"
    if intent_type == "ranking_query":
        return "analyze_ranking"
    if intent_type == "yoy_ranking_query":
        return "analyze_yoy_ranking"
    if intent_type == "trend_ranking_query":
        return "analyze_trend_ranking"
    if intent_type == "rank_position_query":
        return "analyze_rank_position"
    return "analyze_trend"

__all__ = ['route_after_context_router', 'route_after_patch_node', 'should_end_after_plan', 'should_end_after_slot_check', 'route_trend_metric_type', 'route_yoy_metric_type', 'route_compare_metric_type', 'route_compare_yoy_metric_type', 'route_compare_trend_metric_type', 'route_by_intent', 'should_end_after_sql_generation', 'route_analysis']
