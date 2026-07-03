"""V0.4.5 节点职责边界回归测试。"""

import copy
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.nodes.answer_nodes.answer_dispatcher import generate_answer_node
from agent.nodes.sql_nodes.ranking_sql import generate_ranking_sql_node
from agent.nodes.execute_sql_node import review_and_execute_sql_node
from agent.routing import should_end_after_sql_generation
from agent.utils.logger import build_agent_run_log


def test_unsupported_ranking_does_not_generate_sql_or_continue_to_execute():
    state = generate_ranking_sql_node({"intent_type": "ranking_query"})

    assert state["need_clarification"] is True
    assert "sql" not in state
    assert "compare_sqls" not in state
    assert should_end_after_sql_generation(state) == "build_clarification_response"


def test_sql_guard_failure_does_not_execute_sql():
    with mock.patch("agent.nodes.execute_sql_handlers.review_sql", return_value={
        "is_safe": False,
        "reason": "blocked",
        "corrected_sql": None,
    }):
        with mock.patch("agent.nodes.execute_sql_handlers._invoke_execute_financial_sql") as execute_mock:
            result = review_and_execute_sql_node({"sql": "DROP TABLE company_dim"})

    execute_mock.assert_not_called()
    assert result["sql_success"] is False
    assert result["error_type"] == "sql_guard_failed"
    assert result["query_result"]["success"] is False


def test_logger_builds_record_without_mutating_state():
    state = {
        "intent_type": "company_compare_query",
        "companies": [{"stock_abbr": "A公司"}],
        "metrics": [{"metric_key": "revenue", "metric_type": "base"}],
        "compare_spec": {"operator": "higher"},
        "compare_result": [{"status": "ok"}],
    }
    before = copy.deepcopy(state)

    record = build_agent_run_log(state)

    assert state == before
    assert record["intent_type"] == "company_compare_query"
    assert record["compare_spec"]["operator"] == "higher"


def test_general_compare_answer_uses_analysis_winner_without_recomputing():
    state = {
        "intent_type": "company_compare_query",
        "report_year": 2024,
        "compare_spec": {"operator": "general"},
        "compare_result": [{
            "metric_name": "营业收入",
            "metric_type": "base",
            "unit": "yuan",
            "status": "ok",
            "winner_company": "分析节点给出的赢家",
            "diff": 100000000.0,
            "items": [
                {"company_name": "A公司", "value": 1.0, "status": "ok"},
                {"company_name": "B公司", "value": 2.0, "status": "ok"},
            ],
        }],
        "derived_compare_result": [],
    }

    with mock.patch("agent.nodes.answer_nodes.compare_answer._select_extreme_item") as select_mock:
        answer = generate_answer_node(state)

    select_mock.assert_not_called()
    assert "分析节点给出的赢家" in answer["final_answer"]


if __name__ == "__main__":
    tests = [
        test_unsupported_ranking_does_not_generate_sql_or_continue_to_execute,
        test_sql_guard_failure_does_not_execute_sql,
        test_logger_builds_record_without_mutating_state,
        test_general_compare_answer_uses_analysis_winner_without_recomputing,
    ]
    for test in tests:
        test()
    print("V0.4.5 node responsibility tests passed")
