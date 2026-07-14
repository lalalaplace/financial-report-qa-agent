"""目标主图结构测试。"""

from __future__ import annotations

from agent.graph import build_graph
from agent.nodes.target_graph_nodes import llm_insight_node_adapter
from agent.nodes.llm_insight import should_run_llm_insight


def test_target_graph_contains_required_nodes() -> None:
    graph = build_graph().compiled_graph.get_graph()
    required_nodes = {
        "context_router",
        "merge_context",
        "irrelevant_answer",
        "query_planner",
        "entity_normalization",
        "query_spec_validator",
        "capability_router",
        "deterministic_sql_builder",
        "flexible_sql_spec_builder",
        "llm_sql_generator",
        "sql_guard",
        "semantic_validate",
        "dry_run",
        "execute_sql",
        "llm_insight",
        "result_contract_builder",
        "deterministic_table",
        "llm_narrative",
        "answer_assembler",
        "answer_validator",
        "remember_successful_plan",
    }

    assert required_nodes <= set(graph.nodes)


def test_target_graph_contains_key_edges() -> None:
    graph = build_graph().compiled_graph.get_graph()
    edges = {(edge.source, edge.target) for edge in graph.edges}

    assert ("__start__", "context_router") in edges
    assert ("query_planner", "entity_normalization") in edges
    assert ("entity_normalization", "query_spec_validator") in edges
    assert ("deterministic_sql_builder", "sql_guard") in edges
    assert ("flexible_sql_spec_builder", "llm_sql_generator") in edges
    assert ("llm_sql_generator", "sql_guard") in edges
    assert ("llm_sql_repair", "sql_guard") in edges
    assert ("dry_run", "execute_sql") in edges
    assert ("fixed_answer_renderer", "llm_insight") in edges
    assert ("llm_insight", "remember_successful_plan") in edges
    assert ("result_contract_builder", "deterministic_table") in edges
    assert ("result_contract_builder", "llm_narrative") in edges
    assert ("answer_assembler", "answer_validator") in edges
    assert ("answer_validator", "llm_insight") in edges


def test_llm_insight_adapter_appends_only_validated_supplement(monkeypatch) -> None:
    monkeypatch.setattr(
        "agent.nodes.llm_insight.llm_insight_node",
        lambda _state: {
            "llm_analysis": {
                "insight": "同比增速反映相邻两期的变化。",
                "interpretation_boundary": "不能据此推断长期趋势。",
                "suggested_followup": "可继续查看近三年同比趋势。",
            },
            "llm_analysis_success": True,
            "llm_analysis_error": None,
        },
    )

    result = llm_insight_node_adapter({"final_answer": "营业收入同比增长 11.63%。"})

    assert "补充解读：" in result["final_answer"]
    assert "可继续分析：" in result["final_answer"]


def test_verified_flexible_sql_can_run_llm_insight_with_unknown_intent() -> None:
    assert should_run_llm_insight(
        {
            "business_success": True,
            "error_type": None,
            "intent_type": "unknown",
            "final_answer": "查询结果",
            "execution": {"execution_mode": "flexible_sql"},
            "query_result": {"success": True, "rows": [["000999"]], "row_count": 1},
        }
    ) is True
