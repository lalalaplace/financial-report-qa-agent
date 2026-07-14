"""分区 AgentState 的隔离与兼容测试。"""

from __future__ import annotations

from typing import Any

from agent.nodes import target_graph_nodes
from agent.schemas.state_sections import error_update, merge_state_section
from agent.target_graph_routing import route_after_dry_run, route_after_flexible_sql_spec, route_after_semantic_validate, route_after_sql_guard


def test_state_section_reducer_merges_parallel_outputs() -> None:
    left = {"narrative": {"summary": "摘要"}}
    right = {"validation": {"is_valid": True}}

    assert merge_state_section(left, right) == {**left, **right}


def test_error_update_records_exact_stage() -> None:
    result = error_update("dry_run", "DRY_RUN_FAILED", "SQL 无法执行", retryable=True)

    assert result["error"]["error_stage"] == "dry_run"
    assert result["error"]["retryable"] is True


def test_query_planner_clears_previous_error(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "agent.nodes.llm_plan_query.llm_plan_query_node",
        lambda _state: {"query_spec": {"execution_mode": "deterministic", "operation": "point_query"}},
    )

    result = target_graph_nodes.query_planner_node({
        "user_question": "测试问题",
        "error": {"error_stage": "execution", "error_type": "OLD_ERROR", "error_message": "旧错误"},
    })

    assert result["planning"]["query_spec"]["operation"] == "point_query"
    assert result["conversation"]["user_question"] == "测试问题"
    assert result["error"]["error_stage"] is None


def test_llm_sql_failure_isolated_in_execution_and_error(monkeypatch: Any) -> None:
    monkeypatch.setattr(target_graph_nodes, "generate_llm_sql_node", lambda _state: {
        "sql_generation_status": "failed",
        "failed_stage": "sql_guard",
        "sql_generation_error_type": "SQL_UNSAFE",
        "sql_generation_error_message": "包含不允许的语句",
        "llm_sql_candidate": "DELETE FROM t",
    })

    result = target_graph_nodes.llm_sql_generator_node({})

    assert result["execution"]["execution_mode"] == "flexible_sql"
    assert result["execution"]["sql_attempts"][0]["success"] is False
    assert result["error"]["error_stage"] == "sql_guard"
    assert "answer" not in result


def test_llm_sql_generator_reads_partitioned_spec_before_legacy_field(monkeypatch: Any) -> None:
    received: dict[str, Any] = {}

    def fake_generator(state: dict[str, Any]) -> dict[str, Any]:
        received["spec"] = state.get("execution", {}).get("flexible_sql_spec")
        return {
            "sql": "SELECT 1",
            "sql_generation_status": "success",
            "llm_sql_validation": {"is_valid": True},
            "dry_run_result": {"success": True},
        }

    monkeypatch.setattr(target_graph_nodes, "generate_llm_sql_node", fake_generator)
    partitioned_spec = {"question": "来自分区"}
    result = target_graph_nodes.llm_sql_generator_node({
        "flexible_sql_spec": {"question": "旧字段"},
        "execution": {"execution_mode": "flexible_sql", "flexible_sql_spec": partitioned_spec},
    })

    assert received["spec"] == partitioned_spec
    assert result["flexible_sql_spec"] == partitioned_spec
    assert "guard_result" not in result["execution"]


def test_dry_run_routing_reads_execution_partition() -> None:
    assert route_after_dry_run({
        "sql_generation_mode": "llm_sql",
        "dry_run_result": {"success": False},
        "execution": {"execution_mode": "flexible_sql", "dry_run_result": {"success": True}},
    }) == "execute_sql"


def test_formal_execute_ignores_legacy_sql_families(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        target_graph_nodes,
        "execute_partitioned_sql_node",
        lambda execution: {"query_result": {"success": True, "rows": [], "columns": [], "row_count": 0}},
    )

    result = target_graph_nodes.execute_sql_node({
        "yoy_sqls": ["SELECT stale_sql"],
        "execution": {"generated_sql": "SELECT current_sql"},
    })

    assert result["execution"]["execution_result"]["success"] is True


def test_flexible_sql_routes_through_separate_validation_stages() -> None:
    state = {"planning": {"capability_decision": {"execution_mode": "flexible_sql"}}}

    assert route_after_sql_guard(state) == "semantic_validate"
    assert route_after_semantic_validate(state) == "dry_run"


def test_semantic_validation_failure_can_be_repaired_once() -> None:
    state = {
        "execution": {"execution_mode": "flexible_sql"},
        "error": {"error_stage": "semantic_validate"},
    }

    assert route_after_semantic_validate(state) == "llm_sql_repair"
    state["sql_repair_attempted"] = True
    assert route_after_semantic_validate(state) == "controlled_failure"


def test_flexible_sql_spec_compilation_failure_does_not_enter_generator() -> None:
    state = {"error": {"error_stage": "sql_generation"}}

    assert route_after_flexible_sql_spec(state) == "controlled_failure"
