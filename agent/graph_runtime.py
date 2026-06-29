"""Agent 运行时：装饰后的 CompiledGraph 及无 langgraph 降级。"""

from __future__ import annotations

from typing import Any

from agent.constants import DEFAULT_QUERY_TYPE
from agent.state import AgentState
from agent.nodes.context_llm_nodes import (
    clarification_patch_node,
    context_router_node,
    followup_patch_node,
    followup_plan_node,
    merge_clarification_patch_node,
    merge_followup_patch_node,
    remember_successful_query_plan_node,
)
from agent.nodes.llm_plan_query import llm_plan_query_node
from agent.nodes.slot_nodes import resolve_company_node, map_metric_node, check_slots_node
from agent.nodes.sql_nodes.point_sql import generate_point_sql_node
from agent.nodes.sql_nodes.trend_sql import generate_trend_sql_node
from agent.nodes.sql_nodes.yoy_sql import generate_yoy_sql_node
from agent.nodes.sql_nodes.derived_sql import (
    generate_derived_sql_node,
    generate_derived_trend_sql_node,
    generate_derived_yoy_sql_node,
    generate_derived_compare_sql_node,
    generate_derived_compare_trend_sql_node,
    generate_derived_compare_yoy_sql_node,
)
from agent.nodes.sql_nodes.compare_sql import generate_compare_sql_node
from agent.nodes.sql_nodes.compare_trend_sql import generate_compare_trend_sql_node
from agent.nodes.sql_nodes.compare_yoy_sql import generate_compare_yoy_sql_node
from agent.nodes.sql_nodes.ranking_sql import generate_ranking_sql_node
from agent.nodes.sql_nodes.yoy_ranking_sql import generate_yoy_ranking_sql_node
from agent.nodes.sql_nodes.trend_ranking_sql import generate_trend_ranking_sql_node
from agent.nodes.sql_nodes.rank_position_sql import generate_rank_position_sql_node
from agent.nodes.answer_nodes.answer_dispatcher import generate_answer_node
from agent.nodes.answer_nodes.clarify_answer import build_clarification_response_node, generate_unsupported_answer_node
from agent.nodes.answer_nodes.derived_answer import generate_derived_answer_node, generate_derived_yoy_answer_node
from agent.nodes.answer_nodes.trend_answer import generate_derived_trend_answer_node
from agent.nodes.execute_sql_node import review_and_execute_sql_node
from agent.nodes.analyze_nodes.trend_analysis import analyze_trend_node, analyze_derived_trend_node
from agent.nodes.analyze_nodes.yoy_analysis import analyze_yoy_node, analyze_derived_yoy_node
from agent.nodes.analyze_nodes.derived_analysis import analyze_derived_metric_node
from agent.nodes.analyze_nodes.compare_analysis import analyze_compare_node, analyze_derived_compare_node
from agent.nodes.analyze_nodes.compare_trend_analysis import analyze_compare_trend_node, analyze_derived_compare_trend_node
from agent.nodes.analyze_nodes.compare_yoy_analysis import analyze_compare_yoy_node, analyze_derived_compare_yoy_node
from agent.nodes.analyze_nodes.ranking_analysis import analyze_ranking_node
from agent.nodes.analyze_nodes.yoy_ranking_analysis import analyze_yoy_ranking_node
from agent.nodes.analyze_nodes.trend_ranking_analysis import analyze_trend_ranking_node
from agent.nodes.analyze_nodes.rank_position_analysis import analyze_rank_position_node
from agent.routing import route_by_intent
from agent.utils.logger import log_agent_run


class SimpleCompiledGraph:
    """无 langgraph 时的线性执行降级。"""

    def invoke(self, state: AgentState) -> AgentState:
        current_state: AgentState = dict(state)

        current_state.update(context_router_node(current_state))
        route_type = current_state.get("route_type") or "new_query"
        if current_state.get("need_clarification"):
            current_state.update(build_clarification_response_node(current_state))
            log_agent_run(current_state)
            return current_state
        if route_type == "clarification_answer":
            current_state.update(clarification_patch_node(current_state))
            if current_state.get("need_clarification"):
                current_state.update(build_clarification_response_node(current_state))
                log_agent_run(current_state)
                return current_state
            current_state.update(merge_clarification_patch_node(current_state))
            if current_state.get("need_clarification"):
                current_state.update(build_clarification_response_node(current_state))
                log_agent_run(current_state)
                return current_state
        elif route_type == "contextual_followup":
            current_state.update(followup_plan_node(current_state))
            if current_state.get("need_clarification"):
                current_state.update(build_clarification_response_node(current_state))
                log_agent_run(current_state)
                return current_state
        else:
            current_state.update(llm_plan_query_node(current_state))
            if current_state.get("need_clarification"):
                current_state.update(build_clarification_response_node(current_state))
                log_agent_run(current_state)
                return current_state

        for node in [llm_plan_query_node, resolve_company_node, map_metric_node, check_slots_node]:
            if node is llm_plan_query_node:
                continue
            if current_state.get("final_answer"):
                break
            current_state.update(node(current_state))
            if node is llm_plan_query_node and current_state.get("need_clarification"):
                current_state.update(build_clarification_response_node(current_state))
                log_agent_run(current_state)
                return current_state
            if node is check_slots_node and current_state.get("need_clarification"):
                current_state.update(build_clarification_response_node(current_state))
                log_agent_run(current_state)
                return current_state

        sql_nodes = {
            "generate_point_sql": generate_point_sql_node,
            "generate_trend_sql": generate_trend_sql_node,
            "generate_derived_trend_sql": generate_derived_trend_sql_node,
            "generate_yoy_sql": generate_yoy_sql_node,
            "generate_derived_yoy_sql": generate_derived_yoy_sql_node,
            "generate_derived_sql": generate_derived_sql_node,
            "generate_compare_sql": generate_compare_sql_node,
            "generate_derived_compare_sql": generate_derived_compare_sql_node,
            "generate_compare_trend_sql": generate_compare_trend_sql_node,
            "generate_derived_compare_trend_sql": generate_derived_compare_trend_sql_node,
            "generate_compare_yoy_sql": generate_compare_yoy_sql_node,
            "generate_derived_compare_yoy_sql": generate_derived_compare_yoy_sql_node,
            "generate_ranking_sql": generate_ranking_sql_node,
            "generate_yoy_ranking_sql": generate_yoy_ranking_sql_node,
            "generate_trend_ranking_sql": generate_trend_ranking_sql_node,
            "generate_rank_position_sql": generate_rank_position_sql_node,
            "generate_unsupported_answer": generate_unsupported_answer_node,
        }
        current_state.update(sql_nodes.get(route_by_intent(current_state), generate_answer_node)(current_state))
        if current_state.get("need_clarification"):
            current_state.update(build_clarification_response_node(current_state))
            log_agent_run(current_state)
            return current_state

        current_state.update(review_and_execute_sql_node(current_state))
        intent_type = current_state.get("intent_type") or DEFAULT_QUERY_TYPE
        metric_types = {m.get("metric_type", "base") for m in (current_state.get("metrics") or [])}
        if intent_type == "company_compare_yoy_query":
            current_state.update((analyze_derived_compare_yoy_node if metric_types == {"derived"} else analyze_compare_yoy_node)(current_state))
            current_state.update(generate_answer_node(current_state))
            current_state.update(remember_successful_query_plan_node(current_state))
            log_agent_run(current_state)
            return current_state
        if intent_type == "company_compare_trend_query":
            current_state.update((analyze_derived_compare_trend_node if metric_types == {"derived"} else analyze_compare_trend_node)(current_state))
            current_state.update(generate_answer_node(current_state))
            current_state.update(remember_successful_query_plan_node(current_state))
            log_agent_run(current_state)
            return current_state
        if intent_type == "company_compare_query":
            current_state.update((analyze_derived_compare_node if metric_types == {"derived"} else analyze_compare_node)(current_state))
            current_state.update(generate_answer_node(current_state))
            current_state.update(remember_successful_query_plan_node(current_state))
            log_agent_run(current_state)
            return current_state
        if intent_type == "yoy_query":
            if metric_types == {"derived"}:
                current_state.update(analyze_derived_yoy_node(current_state))
                current_state.update(generate_derived_yoy_answer_node(current_state))
                current_state.update(remember_successful_query_plan_node(current_state))
                log_agent_run(current_state)
                return current_state
            current_state.update(analyze_yoy_node(current_state))
        elif intent_type == "derived_metric_query":
            current_state.update(analyze_derived_metric_node(current_state))
            current_state.update(generate_derived_answer_node(current_state))
            current_state.update(remember_successful_query_plan_node(current_state))
            log_agent_run(current_state)
            return current_state
        elif intent_type == "trend_query":
            if metric_types == {"derived"}:
                current_state.update(analyze_derived_trend_node(current_state))
                current_state.update(generate_derived_trend_answer_node(current_state))
                current_state.update(remember_successful_query_plan_node(current_state))
                log_agent_run(current_state)
                return current_state
            current_state.update(analyze_trend_node(current_state))
        elif intent_type == "ranking_query":
            current_state.update(analyze_ranking_node(current_state))
        elif intent_type == "yoy_ranking_query":
            current_state.update(analyze_yoy_ranking_node(current_state))
        elif intent_type == "trend_ranking_query":
            current_state.update(analyze_trend_ranking_node(current_state))
        elif intent_type == "rank_position_query":
            current_state.update(analyze_rank_position_node(current_state))
        else:
            current_state.update(analyze_trend_node(current_state))
        current_state.update(generate_answer_node(current_state))
        current_state.update(remember_successful_query_plan_node(current_state))
        log_agent_run(current_state)
        return current_state


class LoggedCompiledGraph:
    """装饰 LangGraph compiled graph，增加日志记录。"""

    def __init__(self, compiled_graph: Any) -> None:
        self.compiled_graph = compiled_graph

    def invoke(self, state: AgentState) -> AgentState:
        result = self.compiled_graph.invoke(state)
        log_agent_run(result)
        return result
