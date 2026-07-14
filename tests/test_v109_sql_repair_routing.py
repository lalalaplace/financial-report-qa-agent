"""SQL Repair 成功后必须清除上一次可修复错误，防止重复 Repair。"""

from agent.nodes import target_graph_nodes
from agent.target_graph_routing import route_after_semantic_validate
from agent.state import AgentState


def test_successful_sql_repair_clears_previous_semantic_error(monkeypatch) -> None:
    monkeypatch.setattr(target_graph_nodes, "llm_sql_repair_node", lambda _state: {"sql": "SELECT 1", "repair_summary": "ok"})
    result = target_graph_nodes.llm_sql_repair_node_adapter({
        "execution": {"flexible_sql_spec": {}, "generated_sql": "SELECT broken"},
        "error": {"error_stage": "semantic_validate", "error_type": "SQL_SEMANTIC_INVALID"},
    })

    assert result["error"]["error_stage"] is None
    assert result["sql_repair_attempted"] is True
    assert route_after_semantic_validate({
        "planning": {"capability_decision": {"execution_mode": "flexible_sql"}},
        **result,
    }) == "dry_run"


def test_repair_attempt_flag_is_part_of_formal_graph_state() -> None:
    assert "sql_repair_attempted" in AgentState.__annotations__
