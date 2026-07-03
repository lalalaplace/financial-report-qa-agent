"""V0.5.7.5 ranking 系列日志字段与 error_type 统一测试。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.utils.logger import build_agent_run_log


BASE_METRIC = {
    "metric_key": "operating_revenue",
    "metric_name": "营业收入",
    "metric_type": "base",
}

COMPANY = {
    "stock_code": "000999",
    "stock_abbr": "华润三九",
    "company_name": "华润三九医药股份有限公司",
}

COMMON_LOG_FIELDS = {
    "intent_type",
    "query_plan",
    "companies",
    "metrics",
    "metric_type",
    "report_year",
    "start_year",
    "end_year",
    "report_period",
    "rank_direction",
    "limit",
    "change_metric",
    "sql_success",
    "business_success",
    "error_type",
    "row_count",
    "empty_fields",
    "analysis_result_summary",
}


def _base_state(intent_type: str, analysis_result: dict) -> dict:
    return {
        "user_question": "测试 ranking 日志",
        "query_plan": {"intent_type": intent_type},
        "intent_type": intent_type,
        "companies": [],
        "metrics": [BASE_METRIC],
        "report_year": 2024,
        "report_period": "FY",
        "rank_direction": "desc",
        "limit": 10,
        "sql_success": True,
        "business_success": True,
        "error_type": None,
        "empty_fields": [],
        "analysis_result": analysis_result,
    }


def test_value_ranking_log_fields_are_stable():
    record = build_agent_run_log(
        _base_state(
            "ranking_query",
            {
                "analysis_type": "ranking",
                "report_year": 2024,
                "row_count": 1,
                "is_empty": False,
                "rows": [{"rank": 1, "company_name": "A公司", "metric_value": 100.0}],
                "result_summary": {"first_company_name": "A公司"},
            },
        )
    )

    assert COMMON_LOG_FIELDS <= set(record)
    assert record["ranking_mode"] == "value_ranking"
    assert record["metric_value_field"] == "metric_value"
    assert record["metric_type"] == "base"
    assert record["row_count"] == 1
    assert record["analysis_result_summary"]["first_row"]["metric_value"] == 100.0


def test_yoy_ranking_log_fields_are_stable():
    state = _base_state(
        "yoy_ranking_query",
        {
            "analysis_type": "yoy_ranking",
            "report_year": 2024,
            "previous_year": 2023,
            "change_metric": "yoy_rate",
            "row_count": 1,
            "is_empty": False,
            "rows": [{"rank": 1, "company_name": "A公司", "yoy_rate": 0.2}],
        },
    )
    state["change_metric"] = "yoy_rate"
    record = build_agent_run_log(state)

    assert COMMON_LOG_FIELDS <= set(record)
    assert record["ranking_mode"] == "yoy_rate_ranking"
    assert record["current_year"] == 2024
    assert record["previous_year"] == 2023
    assert record["change_metric"] == "yoy_rate"


def test_trend_ranking_log_fields_are_stable():
    state = _base_state(
        "trend_ranking_query",
        {
            "analysis_type": "trend_ranking",
            "start_year": 2022,
            "end_year": 2024,
            "change_metric": "growth_rate",
            "row_count": 1,
            "is_empty": False,
            "rows": [{"rank": 1, "company_name": "A公司", "growth_rate": 0.5}],
        },
    )
    state.update({"start_year": 2022, "end_year": 2024, "change_metric": "growth_rate"})
    record = build_agent_run_log(state)

    assert COMMON_LOG_FIELDS <= set(record)
    assert record["ranking_mode"] == "growth_rate_ranking"
    assert record["start_year"] == 2022
    assert record["end_year"] == 2024
    assert record["change_metric"] == "growth_rate"


def test_rank_position_log_fields_are_stable():
    state = _base_state(
        "rank_position_query",
        {
            "analysis_type": "rank_position",
            "company_name": "华润三九",
            "report_year": 2024,
            "rank_no": 3,
            "total_count": 42,
            "row_count": 1,
            "is_empty": False,
            "result_summary": {"position_zone": "前 25%"},
        },
    )
    state["companies"] = [COMPANY]
    state["limit"] = None
    record = build_agent_run_log(state)

    assert COMMON_LOG_FIELDS <= set(record)
    assert record["ranking_mode"] == "rank_position"
    assert record["companies"] == ["华润三九"]
    assert record["rank_no"] == 3
    assert record["total_count"] == 42


def test_logger_normalizes_legacy_ranking_error_types():
    cases = {
        "sql_guard_failed": "sql_guard_rejected",
        "sql_execution_error": "sql_execution_failed",
        "derived_yoy_ranking_not_supported_v053": "unsupported_metric_type",
        "derived_trend_ranking_not_supported_v054": "unsupported_metric_type",
        "scoped_company_ranking_not_supported": "multiple_companies_not_supported",
        "unsupported_yoy_ranking_time_mode": "unsupported_time_mode",
        "invalid_yoy_ranking_params": "invalid_limit",
    }

    for raw_error_type, expected_error_type in cases.items():
        record = build_agent_run_log(
            {
                "user_question": "测试错误类型",
                "intent_type": "yoy_ranking_query",
                "metrics": [BASE_METRIC],
                "error_type": raw_error_type,
                "business_success": False,
                "analysis_result": {"analysis_type": "yoy_ranking", "row_count": 0, "is_empty": True},
            }
        )
        assert record["error_type"] == expected_error_type
