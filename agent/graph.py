"""Agent 图装配：构建 langgraph StateGraph，连接节点与路由。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

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
from agent.nodes.execute_sql_node import review_and_execute_sql_node
from agent.nodes.answer_nodes.answer_dispatcher import generate_answer_node
from agent.nodes.answer_nodes.clarify_answer import build_clarification_response_node, generate_unsupported_answer_node
from agent.nodes.answer_nodes.derived_answer import generate_derived_answer_node, generate_derived_yoy_answer_node
from agent.nodes.answer_nodes.trend_answer import generate_derived_trend_answer_node
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
from agent.routing import route_after_context_router, route_after_patch_node, should_end_after_plan, should_end_after_slot_check, should_end_after_sql_generation, route_analysis
from agent.graph_runtime import LoggedCompiledGraph, SimpleCompiledGraph

try:
    from langgraph.graph import END, START, StateGraph
except ImportError:
    START = "__start__"
    END = "__end__"
    StateGraph = None


def build_graph():
    if StateGraph is None:
        return SimpleCompiledGraph()

    graph = StateGraph(AgentState)
    graph.add_node("context_router", context_router_node)
    graph.add_node("clarification_patch", clarification_patch_node)
    graph.add_node("followup_patch", followup_patch_node)
    graph.add_node("followup_plan", followup_plan_node)
    graph.add_node("merge_clarification_patch", merge_clarification_patch_node)
    graph.add_node("merge_followup_patch", merge_followup_patch_node)
    graph.add_node("llm_plan_query", llm_plan_query_node)
    graph.add_node("resolve_company", resolve_company_node)
    graph.add_node("map_metric", map_metric_node)
    graph.add_node("check_slots", check_slots_node)
    graph.add_node("generate_point_sql", generate_point_sql_node)
    graph.add_node("generate_trend_sql", generate_trend_sql_node)
    graph.add_node("generate_derived_trend_sql", generate_derived_trend_sql_node)
    graph.add_node("generate_yoy_sql", generate_yoy_sql_node)
    graph.add_node("generate_derived_yoy_sql", generate_derived_yoy_sql_node)
    graph.add_node("generate_derived_sql", generate_derived_sql_node)
    graph.add_node("generate_compare_sql", generate_compare_sql_node)
    graph.add_node("generate_derived_compare_sql", generate_derived_compare_sql_node)
    graph.add_node("generate_compare_trend_sql", generate_compare_trend_sql_node)
    graph.add_node("generate_derived_compare_trend_sql", generate_derived_compare_trend_sql_node)
    graph.add_node("generate_compare_yoy_sql", generate_compare_yoy_sql_node)
    graph.add_node("generate_derived_compare_yoy_sql", generate_derived_compare_yoy_sql_node)
    graph.add_node("generate_ranking_sql", generate_ranking_sql_node)
    graph.add_node("generate_yoy_ranking_sql", generate_yoy_ranking_sql_node)
    graph.add_node("generate_trend_ranking_sql", generate_trend_ranking_sql_node)
    graph.add_node("generate_rank_position_sql", generate_rank_position_sql_node)
    graph.add_node("generate_unsupported_answer", generate_unsupported_answer_node)
    graph.add_node("build_clarification_response", build_clarification_response_node)
    graph.add_node("review_and_execute_sql", review_and_execute_sql_node)
    graph.add_node("analyze_trend", analyze_trend_node)
    graph.add_node("analyze_yoy", analyze_yoy_node)
    graph.add_node("analyze_derived_trend", analyze_derived_trend_node)
    graph.add_node("analyze_derived_yoy", analyze_derived_yoy_node)
    graph.add_node("analyze_derived_metric", analyze_derived_metric_node)
    graph.add_node("analyze_compare", analyze_compare_node)
    graph.add_node("analyze_derived_compare", analyze_derived_compare_node)
    graph.add_node("analyze_compare_trend", analyze_compare_trend_node)
    graph.add_node("analyze_derived_compare_trend", analyze_derived_compare_trend_node)
    graph.add_node("analyze_compare_yoy", analyze_compare_yoy_node)
    graph.add_node("analyze_derived_compare_yoy", analyze_derived_compare_yoy_node)
    graph.add_node("analyze_ranking", analyze_ranking_node)
    graph.add_node("analyze_yoy_ranking", analyze_yoy_ranking_node)
    graph.add_node("analyze_trend_ranking", analyze_trend_ranking_node)
    graph.add_node("analyze_rank_position", analyze_rank_position_node)
    graph.add_node("generate_answer", generate_answer_node)
    graph.add_node("generate_derived_answer", generate_derived_answer_node)
    graph.add_node("generate_derived_trend_answer", generate_derived_trend_answer_node)
    graph.add_node("generate_derived_yoy_answer", generate_derived_yoy_answer_node)
    graph.add_node("remember_successful_query_plan", remember_successful_query_plan_node)

    graph.add_edge(START, "context_router")
    graph.add_conditional_edges("context_router", route_after_context_router, {
        "llm_plan_query": "llm_plan_query",
        "clarification_patch": "clarification_patch",
        "followup_patch": "followup_patch",
        "followup_plan": "followup_plan",
        "build_clarification_response": "build_clarification_response",
    })
    graph.add_conditional_edges("clarification_patch", route_after_patch_node, {"merge_clarification_patch": "merge_clarification_patch", "merge_followup_patch": "merge_followup_patch", "build_clarification_response": "build_clarification_response"})
    graph.add_conditional_edges("followup_patch", route_after_patch_node, {"merge_clarification_patch": "merge_clarification_patch", "merge_followup_patch": "merge_followup_patch", "build_clarification_response": "build_clarification_response"})
    graph.add_conditional_edges("merge_clarification_patch", should_end_after_plan, {"resolve_company": "resolve_company", "build_clarification_response": "build_clarification_response"})
    graph.add_conditional_edges("merge_followup_patch", should_end_after_plan, {"resolve_company": "resolve_company", "build_clarification_response": "build_clarification_response"})
    graph.add_conditional_edges("followup_plan", should_end_after_plan, {"resolve_company": "resolve_company", "build_clarification_response": "build_clarification_response"})
    graph.add_conditional_edges("llm_plan_query", should_end_after_plan, {"resolve_company": "resolve_company", "build_clarification_response": "build_clarification_response"})
    graph.add_edge("resolve_company", "map_metric")
    graph.add_edge("map_metric", "check_slots")
    graph.add_conditional_edges("check_slots", should_end_after_slot_check, {
        "generate_point_sql": "generate_point_sql", "generate_trend_sql": "generate_trend_sql",
        "generate_derived_trend_sql": "generate_derived_trend_sql", "generate_yoy_sql": "generate_yoy_sql",
        "generate_derived_yoy_sql": "generate_derived_yoy_sql", "generate_derived_sql": "generate_derived_sql",
        "generate_compare_sql": "generate_compare_sql", "generate_derived_compare_sql": "generate_derived_compare_sql",
        "generate_compare_trend_sql": "generate_compare_trend_sql", "generate_derived_compare_trend_sql": "generate_derived_compare_trend_sql",
        "generate_compare_yoy_sql": "generate_compare_yoy_sql", "generate_derived_compare_yoy_sql": "generate_derived_compare_yoy_sql",
        "generate_ranking_sql": "generate_ranking_sql", "generate_yoy_ranking_sql": "generate_yoy_ranking_sql",
        "generate_trend_ranking_sql": "generate_trend_ranking_sql",
        "generate_rank_position_sql": "generate_rank_position_sql",
        "generate_unsupported_answer": "generate_unsupported_answer",
        "build_clarification_response": "build_clarification_response",
        "generate_answer": "generate_answer",
    })

    sql_nodes = [
        "generate_point_sql", "generate_trend_sql", "generate_derived_trend_sql", "generate_yoy_sql",
        "generate_derived_yoy_sql", "generate_derived_sql", "generate_compare_sql", "generate_derived_compare_sql",
        "generate_compare_trend_sql", "generate_derived_compare_trend_sql", "generate_compare_yoy_sql",
        "generate_derived_compare_yoy_sql", "generate_ranking_sql", "generate_yoy_ranking_sql",
        "generate_trend_ranking_sql",
        "generate_rank_position_sql",
        "generate_unsupported_answer",
    ]
    for node_name in sql_nodes:
        graph.add_conditional_edges(node_name, should_end_after_sql_generation, {"review_and_execute_sql": "review_and_execute_sql", "build_clarification_response": "build_clarification_response"})

    graph.add_conditional_edges("review_and_execute_sql", route_analysis, {
        "analyze_yoy": "analyze_yoy", "analyze_derived_yoy": "analyze_derived_yoy",
        "analyze_derived_metric": "analyze_derived_metric", "analyze_derived_trend": "analyze_derived_trend",
        "analyze_trend": "analyze_trend", "analyze_compare": "analyze_compare",
        "analyze_derived_compare": "analyze_derived_compare", "analyze_compare_trend": "analyze_compare_trend",
        "analyze_derived_compare_trend": "analyze_derived_compare_trend", "analyze_compare_yoy": "analyze_compare_yoy",
        "analyze_derived_compare_yoy": "analyze_derived_compare_yoy", "analyze_ranking": "analyze_ranking",
        "analyze_yoy_ranking": "analyze_yoy_ranking", "analyze_trend_ranking": "analyze_trend_ranking",
        "analyze_rank_position": "analyze_rank_position",
    })

    for node_name in ["analyze_compare", "analyze_derived_compare", "analyze_compare_trend", "analyze_derived_compare_trend", "analyze_compare_yoy", "analyze_derived_compare_yoy", "analyze_yoy", "analyze_trend", "analyze_ranking", "analyze_yoy_ranking", "analyze_trend_ranking", "analyze_rank_position"]:
        graph.add_edge(node_name, "generate_answer")
    graph.add_edge("analyze_derived_trend", "generate_derived_trend_answer")
    graph.add_edge("analyze_derived_yoy", "generate_derived_yoy_answer")
    graph.add_edge("analyze_derived_metric", "generate_derived_answer")
    graph.add_edge("generate_derived_answer", "remember_successful_query_plan")
    graph.add_edge("generate_derived_trend_answer", "remember_successful_query_plan")
    graph.add_edge("generate_derived_yoy_answer", "remember_successful_query_plan")
    graph.add_edge("build_clarification_response", END)
    graph.add_edge("generate_answer", "remember_successful_query_plan")
    graph.add_edge("remember_successful_query_plan", END)
    return LoggedCompiledGraph(graph.compile())


app = build_graph()


if __name__ == "__main__":
    result = app.invoke({"user_question": "华润三九近五年营业收入趋势如何？"})
    print(result["final_answer"])
    print("\n")
    print(json.dumps(result.get("query_plan"), ensure_ascii=False, indent=2))
