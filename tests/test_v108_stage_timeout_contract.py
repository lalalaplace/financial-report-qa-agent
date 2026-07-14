"""正式主图 LLM 超时应落到对应节点并写入阶段追踪。"""

from __future__ import annotations

from agent.nodes import llm_plan_query, target_graph_nodes
from agent.nodes.result_contract_builder import build_result_contract
from agent.utils.stage_trace import traced_node


class _TimeoutError(TimeoutError):
    def __init__(self, code: str):
        super().__init__(code)
        self.error_code = code


def _assert_timeout(result: dict, error_stage: str, trace_stage: str, code: str) -> None:
    assert result["error"]["error_stage"] == error_stage
    assert result["error"]["error_type"] == code
    trace = result["stage_traces"][-1]
    assert trace["stage"] == trace_stage
    assert trace["status"] == "timeout"
    assert trace["error_code"] == code


def test_planner_timeout_is_attributed_to_planning(monkeypatch) -> None:
    monkeypatch.setattr(llm_plan_query, "_build_llm", lambda: (_ for _ in ()).throw(_TimeoutError("PLANNER_TIMEOUT")))

    result = traced_node("planning", target_graph_nodes.query_planner_node)({"user_question": "华润三九 2024 年营业收入是多少？"})

    _assert_timeout(result, "planning", "planning", "PLANNER_TIMEOUT")


def test_sql_generator_timeout_is_attributed_to_sql_generation(monkeypatch) -> None:
    monkeypatch.setattr(
        target_graph_nodes,
        "generate_llm_sql_node",
        lambda _state: {"sql_generation_status": "failed", "sql_generation_error_type": "SQL_GENERATION_TIMEOUT", "sql_generation_error_message": "超时"},
    )

    result = traced_node("llm_sql_generator", target_graph_nodes.llm_sql_generator_node)({"execution": {"flexible_sql_spec": {}}})

    _assert_timeout(result, "sql_generation", "llm_sql_generator", "SQL_GENERATION_TIMEOUT")


def test_sql_repair_timeout_is_attributed_to_repair(monkeypatch) -> None:
    monkeypatch.setattr(target_graph_nodes, "llm_sql_repair_node", lambda _state: (_ for _ in ()).throw(_TimeoutError("SQL_REPAIR_TIMEOUT")))

    result = traced_node("sql_repair", target_graph_nodes.llm_sql_repair_node_adapter)({"execution": {"flexible_sql_spec": {}, "generated_sql": "SELECT 1"}})

    _assert_timeout(result, "sql_repair", "sql_repair", "SQL_REPAIR_TIMEOUT")


def test_narrative_timeout_is_attributed_to_narrative(monkeypatch) -> None:
    monkeypatch.setattr(target_graph_nodes, "invoke_json_prompt", lambda *_args, **_kwargs: (_ for _ in ()).throw(_TimeoutError("NARRATIVE_TIMEOUT")))
    state = {
        "user_question": "列出公司", "execution": {"execution_result": {"success": True, "columns": ["company_name"], "rows": [["华润三九"]], "row_count": 1}},
    }
    state["result"] = {"result_contract": build_result_contract(state)}

    result = traced_node("narrative", target_graph_nodes.llm_narrative_node)(state)

    _assert_timeout(result, "narrative", "narrative", "NARRATIVE_TIMEOUT")
    assert result["answer"]["narrative"]
