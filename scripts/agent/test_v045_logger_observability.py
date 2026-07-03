"""V0.4.5 日志可观测性测试。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.utils.logger import build_agent_run_log


REQUIRED_LOG_KEYS = {
    "query",
    "query_plan",
    "intent_type",
    "compare_spec",
    "companies",
    "metrics",
    "report_year",
    "report_years",
    "sqls",
    "sql_review",
    "query_results",
    "analysis_result",
    "error_type",
    "business_success",
    "final_answer",
    "failure_stage",
}


def test_log_keeps_v045_observability_fields():
    state = {
        "user_question": "A公司和B公司2024年营业收入同比对比",
        "query_plan": {"intent_type": "company_compare_yoy_query"},
        "intent_type": "company_compare_yoy_query",
        "compare_spec": {"operator": "general", "target": "yoy_rate"},
        "companies": [
            {"stock_code": "000001", "stock_abbr": "A公司"},
            {"stock_code": "000002", "stock_abbr": "B公司"},
        ],
        "metrics": [{
            "metric_key": "total_operating_revenue",
            "metric_type": "base",
        }],
        "report_year": 2024,
        "report_years": [2023, 2024],
        "report_period": "FY",
        "compare_yoy_sqls": [{
            "sql_id": "compare_yoy_base_income_sheet_001",
            "table": "income_sheet",
            "metric_keys": ["total_operating_revenue"],
            "years": [2023, 2024],
            "guard_passed": True,
            "sql": "SELECT 1",
        }],
        "sql_review": {"is_safe": True, "reason": "", "corrected_sql": None},
        "compare_yoy_query_results": [{
            "sql_id": "compare_yoy_base_income_sheet_001",
            "table": "income_sheet",
            "metric_keys": ["total_operating_revenue"],
            "years": [2023, 2024],
            "guard_passed": True,
            "success": True,
            "row_count": 4,
            "error": None,
        }],
        "compare_yoy_result": [{
            "metric_key": "total_operating_revenue",
            "metric_name": "营业收入",
            "metric_type": "base",
            "unit": "yuan",
            "status": "ok",
            "items": [],
            "compare_spec": {"operator": "general", "target": "yoy_rate"},
            "conclusion": {"winner_company": "A公司"},
        }],
        "business_success": True,
        "error_type": None,
        "final_answer": "同比对比结果。",
    }

    record = build_agent_run_log(state)

    assert REQUIRED_LOG_KEYS <= set(record)
    assert record["query"] == state["user_question"]
    assert record["sqls"][0]["sql_id"] == "compare_yoy_base_income_sheet_001"
    assert record["query_results"][0]["row_count"] == 4
    assert "compare_yoy_result" in record["analysis_result"]
    assert record["failure_stage"] is None


def test_log_can_identify_sql_guard_failure_stage():
    record = build_agent_run_log({
        "user_question": "A公司2024年营业收入",
        "query_plan": {"intent_type": "single_metric_query"},
        "intent_type": "single_metric_query",
        "companies": [{"stock_abbr": "A公司"}],
        "metrics": [{"metric_key": "total_operating_revenue"}],
        "report_year": 2024,
        "sql": "DROP TABLE company_dim",
        "sql_review": {"is_safe": False, "reason": "blocked"},
        "query_result": {
            "success": False,
            "row_count": 0,
            "error": "blocked",
        },
        "business_success": False,
        "error_type": "sql_guard_failed",
        "final_answer": "查询失败。",
    })

    assert record["failure_stage"] == "sql_guard"
    assert record["query_results"][0]["success"] is False
    assert record["sqls"][0]["sql"] == "DROP TABLE company_dim"


def test_log_failure_stage_covers_main_pipeline_steps():
    cases = [
        ("planner_parse_error", "planner"),
        ("clarify_company", "company_normalization"),
        ("clarify_metric", "metric_mapping"),
        ("clarify_year", "slot_check"),
        ("unsupported_ranking_query", "route"),
        ("sql_guard_failed", "sql_guard"),
        ("sql_execution_error", "sql_execution"),
        ("compare_unavailable", "analyze"),
    ]

    for error_type, expected_stage in cases:
        record = build_agent_run_log({
            "user_question": "测试问题",
            "error_type": error_type,
            "business_success": False,
            "final_answer": "失败。",
        })
        assert record["failure_stage"] == expected_stage

    answer_record = build_agent_run_log({
        "user_question": "测试问题",
        "business_success": False,
        "final_answer": None,
    })
    assert answer_record["failure_stage"] == "answer"


if __name__ == "__main__":
    tests = [
        test_log_keeps_v045_observability_fields,
        test_log_can_identify_sql_guard_failure_stage,
        test_log_failure_stage_covers_main_pipeline_steps,
    ]
    for test in tests:
        test()
    print("V0.4.5 logger observability tests passed")
