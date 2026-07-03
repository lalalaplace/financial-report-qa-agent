"""V0.4.5 AgentState 字段分层稳定性测试。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.state import AgentState


REQUIRED_STATE_FIELDS = {
    "query_plan",
    "company_mentions",
    "metric_mentions",
    "time_range",
    "compare_spec",
    "companies",
    "metrics",
    "report_year",
    "report_years",
    "report_period",
    "sql",
    "sql_review",
    "compare_sqls",
    "compare_trend_sqls",
    "compare_yoy_sqls",
    "derived_compare_sqls",
    "derived_compare_trend_sqls",
    "derived_compare_yoy_sqls",
    "query_result",
    "compare_query_results",
    "compare_trend_query_results",
    "compare_yoy_query_results",
    "derived_compare_query_results",
    "derived_compare_trend_query_results",
    "derived_compare_yoy_query_results",
    "analysis_result",
    "compare_result",
    "compare_trend_result",
    "compare_yoy_result",
    "derived_compare_result",
    "derived_compare_trend_result",
    "derived_compare_yoy_result",
    "final_answer",
    "business_success",
    "error_type",
    "empty_fields",
}

COMPATIBILITY_FIELDS = {
    "company_candidates",
    "metric_candidates",
    "time_mode",
    "start_year",
    "end_year",
    "recent_n_years",
    "warnings",
    "yoy_sqls",
    "derived_sqls",
    "derived_trend_sqls",
    "derived_yoy_sqls",
    "derived_query_results",
    "derived_trend_query_results",
    "derived_yoy_query_results",
    "sql_success",
    "yoy_result",
    "derived_result",
    "derived_trend_result",
    "derived_yoy_result",
    "answer_facts",
    "need_clarification",
    "clarification_question",
    "pending_query_plan",
    "pending_clarification_type",
    "pending_empty_fields",
    "pending_candidates",
    "slot_patch",
    "merged_query_plan",
    "error_messages",
    "retry_count",
}


def test_agent_state_includes_v045_required_fields():
    fields = set(AgentState.__annotations__)
    missing = REQUIRED_STATE_FIELDS - fields
    assert not missing


def test_agent_state_keeps_runtime_compatibility_fields():
    fields = set(AgentState.__annotations__)
    missing = COMPATIBILITY_FIELDS - fields
    assert not missing


if __name__ == "__main__":
    tests = [
        test_agent_state_includes_v045_required_fields,
        test_agent_state_keeps_runtime_compatibility_fields,
    ]
    for test in tests:
        test()
    print("V0.4.5 AgentState schema tests passed")
