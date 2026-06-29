"""回答分发入口：根据 intent_type 将回答请求路由到对应的回答模块。"""

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
from agent.nodes.answer_nodes.compare_answer import _generate_compare_answer
from agent.nodes.answer_nodes.compare_trend_answer import _generate_compare_trend_answer
from agent.nodes.answer_nodes.compare_yoy_answer import _generate_compare_yoy_answer
from agent.nodes.answer_nodes.ranking_answer import generate_ranking_answer_node
from agent.nodes.answer_nodes.yoy_ranking_answer import generate_yoy_ranking_answer_node
from agent.nodes.answer_nodes.trend_ranking_answer import generate_trend_ranking_answer_node
from agent.nodes.answer_nodes.rank_position_answer import generate_rank_position_answer_node


def generate_answer_node(state: AgentState) -> dict:
    """回答分发：按 intent_type 路由到具体的回答生成函数。"""
    if state.get("need_clarification"):
        return build_clarification_response_node(state)

    if state.get("need_clarification"):
        return {
            "final_answer": state.get("clarification_question") or "请补充查询条件。",
            "sql_success": False,
            "business_success": False,
            "error_type": state.get("error_type") or "need_clarification",
            "empty_fields": state.get("empty_fields") or [],
        }

    intent_type = state.get("intent_type") or DEFAULT_QUERY_TYPE
    metrics = state.get("metrics") or []
    metric_types = {m.get("metric_type", "base") for m in metrics}

    if intent_type == "company_compare_yoy_query":
        return _generate_compare_yoy_answer(state)

    if intent_type == "company_compare_trend_query":
        return _generate_compare_trend_answer(state)

    if intent_type == "company_compare_query":
        return _generate_compare_answer(state)

    if intent_type == "yoy_query":
        return _generate_yoy_answer(state)

    if intent_type == "trend_query":
        if "derived" in metric_types:
            return generate_derived_trend_answer_node(state)
        return _generate_trend_answer(state)

    if intent_type == "ranking_query":
        return generate_ranking_answer_node(state)

    if intent_type == "yoy_ranking_query":
        return generate_yoy_ranking_answer_node(state)

    if intent_type == "trend_ranking_query":
        return generate_trend_ranking_answer_node(state)

    if intent_type == "rank_position_query":
        return generate_rank_position_answer_node(state)

    return _generate_point_answer(state)
