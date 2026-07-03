"""V0.4.5 error_type 归一化测试。"""

import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.nodes.execute_sql_node import review_and_execute_sql_node


REMOVED_ERROR_TYPES = {
    "sql_error",
    "partial_sql_error",
    "unsafe_sql",
    "planner_error",
}

CORE_ERROR_TYPES = {
    "clarify_company",
    "clarify_metric",
    "clarify_year",
    "clarify_compare_reference",
    "unsupported_ranking_query",
    "unsupported_mixed_compare",
    "unsupported_mixed_compare_trend",
    "unsupported_mixed_compare_yoy",
    "compare_unavailable",
    "partial_compare_unavailable",
    "derived_compare_unavailable",
    "partial_derived_compare_unavailable",
    "compare_trend_unavailable",
    "partial_compare_trend_unavailable",
    "derived_compare_trend_unavailable",
    "partial_derived_compare_trend_unavailable",
    "compare_yoy_unavailable",
    "partial_compare_yoy_unavailable",
    "derived_compare_yoy_unavailable",
    "partial_derived_compare_yoy_unavailable",
    "sql_guard_failed",
    "sql_execution_error",
    "route_error",
    "planner_parse_error",
    "schema_validation_error",
}


def test_sql_execution_failure_uses_core_error_type():
    with mock.patch("agent.nodes.execute_sql_handlers.review_sql", return_value={
        "is_safe": True,
        "reason": "",
        "corrected_sql": None,
    }):
        with mock.patch("agent.nodes.execute_sql_handlers._invoke_execute_financial_sql", return_value={
            "success": False,
            "columns": [],
            "rows": [],
            "row_count": 0,
            "error": "database unavailable",
        }):
            result = review_and_execute_sql_node({"sql": "SELECT 1"})

    assert result["error_type"] == "sql_execution_error"
    assert result["error_type"] in CORE_ERROR_TYPES


def test_removed_error_types_are_not_literal_error_type_values():
    source_files = [
        Path("agent/graph.py"),
        Path("agent/nodes/llm_plan_query.py"),
    ]
    for path in source_files:
        text = path.read_text(encoding="utf-8")
        for error_type in REMOVED_ERROR_TYPES:
            assert f'"error_type": "{error_type}"' not in text


if __name__ == "__main__":
    tests = [
        test_sql_execution_failure_uses_core_error_type,
        test_removed_error_types_are_not_literal_error_type_values,
    ]
    for test in tests:
        test()
    print("V0.4.5 error_type schema tests passed")
