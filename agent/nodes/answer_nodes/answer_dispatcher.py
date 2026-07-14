"""回答分发入口：固定模板优先，复杂结果交给 LLM Answer。"""

from __future__ import annotations

from agent.constants import DEFAULT_QUERY_TYPE
from agent.state import AgentState
from agent.nodes.answer_nodes.clarify_answer import build_clarification_response_node
from agent.nodes.answer_nodes.point_answer import _generate_point_answer
from agent.nodes.answer_nodes.yoy_answer import _generate_yoy_answer
from agent.nodes.answer_nodes.trend_answer import (
    _generate_trend_answer,
    generate_derived_trend_answer_node,
)
from agent.nodes.answer_nodes.derived_answer import (
    generate_derived_answer_node,
    generate_derived_yoy_answer_node,
)
from agent.nodes.answer_nodes.compare_answer import _generate_compare_answer
from agent.nodes.answer_nodes.compare_trend_answer import _generate_compare_trend_answer
from agent.nodes.answer_nodes.compare_yoy_answer import _generate_compare_yoy_answer
from agent.nodes.answer_nodes.ranking_answer import generate_ranking_answer_node
from agent.nodes.answer_nodes.yoy_ranking_answer import generate_yoy_ranking_answer_node
from agent.nodes.answer_nodes.trend_ranking_answer import generate_trend_ranking_answer_node
from agent.nodes.answer_nodes.rank_position_answer import generate_rank_position_answer_node
from agent.nodes.answer_router import route_answer_generation
from agent.nodes.llm_answer_synthesis_node import llm_answer_synthesis_node


def _template_result(payload: dict) -> dict:
    payload.setdefault("answer_mode", "template")
    return payload


def generate_answer_node(state: AgentState) -> dict:
    """按回答路由选择固定模板或 LLM 综合回答。"""
    if state.get("need_clarification"):
        return build_clarification_response_node(state)

    answer_route = route_answer_generation(state)
    if answer_route == "llm_answer":
        return llm_answer_synthesis_node(state)
    if answer_route == "error":
        return {
            "answer_mode": "template",
            "final_answer": state.get("sql_generation_error_message") or state.get("clarification_question") or "查询未成功完成，无法生成回答。",
            "business_success": False,
            "error_type": state.get("sql_generation_error_type") or state.get("error_type") or "query_failed",
        }

    intent_type = state.get("intent_type") or DEFAULT_QUERY_TYPE
    metrics = state.get("metrics") or []
    metric_types = {m.get("metric_type", "base") for m in metrics}

    if intent_type == "company_compare_yoy_query":
        return _template_result(_generate_compare_yoy_answer(state))

    if intent_type == "company_compare_trend_query":
        return _template_result(_generate_compare_trend_answer(state))

    if intent_type == "company_compare_query":
        return _template_result(_generate_compare_answer(state))

    if intent_type == "derived_metric_query":
        return _template_result(generate_derived_answer_node(state))

    if intent_type == "yoy_query":
        if "derived" in metric_types:
            return _template_result(generate_derived_yoy_answer_node(state))
        return _template_result(_generate_yoy_answer(state))

    if intent_type == "trend_query":
        if "derived" in metric_types:
            return _template_result(generate_derived_trend_answer_node(state))
        return _template_result(_generate_trend_answer(state))

    if intent_type == "ranking_query":
        return _template_result(generate_ranking_answer_node(state))

    if intent_type == "yoy_ranking_query":
        return _template_result(generate_yoy_ranking_answer_node(state))

    if intent_type == "trend_ranking_query":
        return _template_result(generate_trend_ranking_answer_node(state))

    if intent_type == "rank_position_query":
        return _template_result(generate_rank_position_answer_node(state))

    return _template_result(_generate_point_answer(state))
