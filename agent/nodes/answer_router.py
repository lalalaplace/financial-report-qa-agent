"""回答生成路由：固定模板优先，复杂结果走 LLM Answer。"""

from __future__ import annotations

from typing import Any


SIMPLE_TEMPLATE_INTENTS = {
    "single_metric_query",
    "derived_metric_query",
    "multi_metric_query",
    "trend_query",
    "yoy_query",
    "ranking_query",
    "rank_position_query",
    "company_compare_query",
    "company_compare_trend_query",
    "company_compare_yoy_query",
    "yoy_ranking_query",
    "trend_ranking_query",
}

LLM_FINAL_ANSWER_MODES = {
    "synthesis",
    "scoped_ranking",
    "multi_condition_filter",
    "multi_metric_yoy",
    "set_intersection",
    "cross_statement_filter",
}

BLOCKING_SQL_ERRORS = {
    "SQL_UNSAFE",
    "SQL_FIELD_NOT_ALLOWED",
    "SQL_TABLE_NOT_ALLOWED",
    "SQL_SEMANTIC_INVALID",
    "YOY_MISSING_PREVIOUS_YEAR",
    "LLM_SQL_VALIDATION_FAILED",
}


def route_answer_generation(state: dict[str, Any]) -> str:
    """返回 template、llm_answer 或 error。"""
    if state.get("need_clarification"):
        return "error"
    if state.get("sql_generation_error_type") in BLOCKING_SQL_ERRORS:
        return "error"
    query_result = state.get("query_result")
    if isinstance(query_result, dict) and query_result.get("success") is False:
        return "error"
    if state.get("query_type") == "composite":
        return "llm_answer"
    if state.get("sql_generation_mode") == "llm_sql":
        return "llm_answer"
    if isinstance(state.get("llm_sql_requirement"), dict):
        return "llm_answer"
    if state.get("final_answer_mode") in LLM_FINAL_ANSWER_MODES:
        return "llm_answer"
    if state.get("composite_query_plan"):
        return "llm_answer"
    intent = state.get("intent_type") or "single_metric_query"
    if intent in SIMPLE_TEMPLATE_INTENTS and state.get("sql_generation_mode") in {None, "template"} and state.get("query_type") != "composite":
        return "template"
    return "llm_answer"


def answer_router_node(state: dict[str, Any]) -> dict[str, Any]:
    route = route_answer_generation(state)
    return {
        "answer_mode": "template" if route == "template" else "llm_answer" if route == "llm_answer" else state.get("answer_mode"),
        "answer_route": route,
    }


__all__ = ["answer_router_node", "route_answer_generation"]
