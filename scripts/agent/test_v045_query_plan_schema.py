"""V0.4.5 QueryPlan schema 固化测试。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.schemas.query_plan import validate_plan


def test_non_compare_query_allows_null_compare_spec():
    plan = validate_plan({
        "intent_type": "trend_query",
        "company_mentions": ["华润三九"],
        "metric_mentions": ["营业收入"],
        "report_period": "FY",
        "time_range": {
            "mode": "explicit_range",
            "start_year": 2022,
            "end_year": 2024,
        },
        "compare_spec": {"operator": "higher"},
    })

    assert plan["compare_spec"] is None
    assert plan["clarification_reason"] is None


def test_compare_query_defaults_compare_spec_operator_to_general():
    plan = validate_plan({
        "intent_type": "company_compare_query",
        "company_mentions": ["华润三九", "贵州茅台"],
        "metric_mentions": ["营业收入"],
        "report_period": "FY",
        "time_range": {"mode": "single_year", "report_year": 2024},
        "compare_spec": None,
    })

    assert plan["compare_spec"] == {
        "operator": "general",
        "target": None,
        "subject_company": None,
        "reference_company": None,
    }


def test_company_compare_trend_query_generates_report_years():
    explicit_plan = validate_plan({
        "intent_type": "company_compare_trend_query",
        "company_mentions": ["华润三九", "贵州茅台"],
        "metric_mentions": ["营业收入"],
        "report_period": "FY",
        "time_range": {
            "mode": "explicit_range",
            "start_year": 2022,
            "end_year": 2024,
        },
    })
    assert explicit_plan["time_range"]["report_years"] == [2022, 2023, 2024]

    recent_plan = validate_plan({
        "intent_type": "company_compare_trend_query",
        "company_mentions": ["华润三九", "贵州茅台"],
        "metric_mentions": ["营业收入"],
        "report_period": "FY",
        "time_range": {
            "mode": "recent_n",
            "report_year": 2024,
            "recent_n_years": 3,
        },
    })
    assert recent_plan["time_range"]["report_years"] == [2022, 2023, 2024]


def test_company_compare_yoy_query_requires_report_year():
    missing_year = validate_plan({
        "intent_type": "company_compare_yoy_query",
        "company_mentions": ["华润三九", "贵州茅台"],
        "metric_mentions": ["营业收入"],
        "report_period": "FY",
        "time_range": {"mode": "unspecified"},
    })
    assert missing_year["need_clarification"] is True
    assert "年份" in missing_year["clarification_reason"]

    ready = validate_plan({
        "intent_type": "company_compare_yoy_query",
        "company_mentions": ["华润三九", "贵州茅台"],
        "metric_mentions": ["营业收入"],
        "report_period": "FY",
        "time_range": {"mode": "single_year", "report_year": 2024},
    })
    assert ready["time_range"]["report_year"] == 2024
    assert ready["time_range"]["report_years"] == [2023, 2024]


if __name__ == "__main__":
    tests = [
        test_non_compare_query_allows_null_compare_spec,
        test_compare_query_defaults_compare_spec_operator_to_general,
        test_company_compare_trend_query_generates_report_years,
        test_company_compare_yoy_query_requires_report_year,
    ]
    for test in tests:
        test()
    print("V0.4.5 QueryPlan schema tests passed")
