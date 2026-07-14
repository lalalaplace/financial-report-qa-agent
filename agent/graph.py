"""财报问数双通道主图。"""
from __future__ import annotations

from agent.graph_runtime import LoggedCompiledGraph
from agent.nodes.answer_nodes.clarify_answer import build_clarification_response_node
from agent.nodes.context_llm_nodes import (
    context_router_node,
    remember_successful_query_plan_node,
)
from agent.nodes.target_graph_nodes import (
    answer_assembler_node,
    answer_validator_node,
    capability_boundary_answer_node,
    capability_router_node,
    controlled_failure_node,
    deterministic_result_analyzer_node,
    deterministic_sql_builder_node,
    deterministic_table_node,
    dry_run_node,
    entity_normalization_node,
    execute_sql_node,
    fixed_answer_renderer_node,
    flexible_sql_spec_builder_node,
    irrelevant_answer_node,
    llm_insight_node_adapter,
    llm_narrative_node,
    llm_sql_generator_node,
    llm_sql_repair_node_adapter,
    merge_context_node,
    query_planner_node,
    query_spec_validator_node,
    result_contract_builder_node,
    semantic_validate_node,
    sql_guard_node,
)
from agent.state import AgentState
from agent.target_graph_routing import (
    route_after_capability_router,
    route_after_context_router_target,
    route_after_dry_run,
    route_after_execute_sql,
    route_after_flexible_sql_spec,
    route_after_llm_sql_generator,
    route_after_query_spec_validator,
    route_after_semantic_validate,
    route_after_sql_guard,
)
from agent.utils.stage_trace import traced_node

try:
    from langgraph.graph import END, START, StateGraph
except ImportError:
    END, START, StateGraph = "__end__", "__start__", None


def register_nodes(graph: StateGraph) -> None:
    """注册主图节点，并统一注入阶段追踪。"""
    nodes = {
        "context_router": context_router_node,
        "merge_context": merge_context_node,
        "irrelevant_answer": irrelevant_answer_node,
        "query_planner": query_planner_node,
        "entity_normalization": entity_normalization_node,
        "query_spec_validator": query_spec_validator_node,
        "clarification_answer": build_clarification_response_node,
        "capability_boundary_answer": capability_boundary_answer_node,
        "capability_router": capability_router_node,
        "deterministic_sql_builder": deterministic_sql_builder_node,
        "sql_guard": sql_guard_node,
        "semantic_validate": semantic_validate_node,
        "execute_sql": execute_sql_node,
        "deterministic_result_analyzer": deterministic_result_analyzer_node,
        "fixed_answer_renderer": fixed_answer_renderer_node,
        "llm_insight": llm_insight_node_adapter,
        "flexible_sql_spec_builder": flexible_sql_spec_builder_node,
        "llm_sql_generator": llm_sql_generator_node,
        "llm_sql_repair": llm_sql_repair_node_adapter,
        "controlled_failure": controlled_failure_node,
        "dry_run": dry_run_node,
        "result_contract_builder": result_contract_builder_node,
        "deterministic_table": deterministic_table_node,
        "llm_narrative": llm_narrative_node,
        "answer_assembler": answer_assembler_node,
        "answer_validator": answer_validator_node,
        "remember_successful_plan": remember_successful_query_plan_node,
    }
    for name, node in nodes.items():
        graph.add_node(name, traced_node(name, node))


def register_context_edges(graph: StateGraph) -> None:
    """注册上下文识别、规划和能力路由边。"""
    graph.add_edge(START, "context_router")
    graph.add_conditional_edges(
        "context_router",
        route_after_context_router_target,
        {
            "merge_context": "merge_context",
            "irrelevant_answer": "irrelevant_answer",
            "query_planner": "query_planner",
            "clarification_answer": "clarification_answer",
        },
    )
    graph.add_edge("merge_context", "entity_normalization")
    graph.add_edge("query_planner", "entity_normalization")
    graph.add_edge("entity_normalization", "query_spec_validator")
    graph.add_conditional_edges(
        "query_spec_validator",
        route_after_query_spec_validator,
        {
            "clarification_answer": "clarification_answer",
            "capability_boundary_answer": "capability_boundary_answer",
            "capability_router": "capability_router",
        },
    )
    graph.add_conditional_edges(
        "capability_router",
        route_after_capability_router,
        {
            "deterministic_sql_builder": "deterministic_sql_builder",
            "flexible_sql_spec_builder": "flexible_sql_spec_builder",
            "clarification_answer": "clarification_answer",
            "capability_boundary_answer": "capability_boundary_answer",
        },
    )


def register_execution_edges(graph: StateGraph) -> None:
    """注册确定性 SQL 与 Flexible SQL 的执行和防护边。"""
    graph.add_edge("deterministic_sql_builder", "sql_guard")
    graph.add_conditional_edges(
        "flexible_sql_spec_builder",
        route_after_flexible_sql_spec,
        {"llm_sql_generator": "llm_sql_generator", "controlled_failure": "controlled_failure"},
    )
    graph.add_conditional_edges(
        "llm_sql_generator",
        route_after_llm_sql_generator,
        {"sql_guard": "sql_guard", "controlled_failure": "controlled_failure"},
    )
    graph.add_edge("llm_sql_repair", "sql_guard")
    graph.add_conditional_edges(
        "sql_guard",
        route_after_sql_guard,
        {
            "execute_sql": "execute_sql",
            "semantic_validate": "semantic_validate",
            "llm_sql_repair": "llm_sql_repair",
            "controlled_failure": "controlled_failure",
        },
    )
    graph.add_conditional_edges(
        "semantic_validate",
        route_after_semantic_validate,
        {
            "dry_run": "dry_run",
            "llm_sql_repair": "llm_sql_repair",
            "controlled_failure": "controlled_failure",
        },
    )
    graph.add_conditional_edges(
        "dry_run",
        route_after_dry_run,
        {
            "execute_sql": "execute_sql",
            "controlled_failure": "controlled_failure",
            "llm_sql_repair": "llm_sql_repair",
        },
    )


def register_answer_edges(graph: StateGraph) -> None:
    """注册双通道结果组装与结束边。"""
    graph.add_conditional_edges(
        "execute_sql",
        route_after_execute_sql,
        {
            "deterministic_result_analyzer": "deterministic_result_analyzer",
            "result_contract_builder": "result_contract_builder",
        },
    )
    graph.add_edge("deterministic_result_analyzer", "fixed_answer_renderer")
    graph.add_edge("fixed_answer_renderer", "llm_insight")
    graph.add_edge("result_contract_builder", "deterministic_table")
    graph.add_edge("result_contract_builder", "llm_narrative")
    graph.add_edge("deterministic_table", "answer_assembler")
    graph.add_edge("llm_narrative", "answer_assembler")
    graph.add_edge("answer_assembler", "answer_validator")
    graph.add_edge("answer_validator", "llm_insight")
    graph.add_edge("llm_insight", "remember_successful_plan")
    for name in (
        "clarification_answer",
        "irrelevant_answer",
        "capability_boundary_answer",
        "controlled_failure",
        "remember_successful_plan",
    ):
        graph.add_edge(name, END)


def build_graph() -> LoggedCompiledGraph:
    """构建并编译双通道主图。"""
    if StateGraph is None:
        raise RuntimeError(
            "财报问数 Agent 需要 langgraph；为避免进入与双通道主图不一致的旧执行链路，"
            "已禁止线性降级执行。"
        )
    graph = StateGraph(AgentState)
    register_nodes(graph)
    register_context_edges(graph)
    register_execution_edges(graph)
    register_answer_edges(graph)
    return LoggedCompiledGraph(graph.compile())


app = build_graph()
compiled_graph = app.compiled_graph
