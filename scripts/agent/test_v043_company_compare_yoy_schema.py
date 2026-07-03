"""V0.4.3 公司同比对比 QueryPlan schema 测试。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.schemas.query_plan import validate_plan


def test_company_compare_yoy_plan_keeps_unified_shape():
    """公司同比对比应保留统一输出结构，并补齐上一年和当年。"""
    plan = validate_plan({
        "intent_type": "company_compare_yoy_query",
        "company_mentions": ["华润三九", "贵州茅台"],
        "metric_mentions": ["营业收入"],
        "report_period": "FY",
        "time_range": {
            "mode": "single_year",
            "report_year": 2024,
            "recent_n_years": None,
            "start_year": None,
            "end_year": None,
            "report_years": [],
        },
        "need_clarification": False,
        "clarification_reason": None,
    })

    assert plan == {
        "intent_type": "company_compare_yoy_query",
        "company_mentions": ["华润三九", "贵州茅台"],
        "metric_mentions": ["营业收入"],
        "report_period": "FY",
        "time_range": {
            "mode": "single_year",
            "report_year": 2024,
            "recent_n_years": None,
            "start_year": None,
            "end_year": None,
            "report_years": [2023, 2024],
        },
        "compare_spec": {
            "operator": "general",
            "target": None,
            "subject_company": None,
            "reference_company": None,
        },
        "rank_direction": None,
        "limit": None,
        "change_metric": None,
        "need_clarification": False,
        "clarification_reason": None,
    }


def test_company_compare_yoy_requires_two_companies():
    """公司同比对比至少需要两家公司。"""
    plan = validate_plan({
        "intent_type": "company_compare_yoy_query",
        "company_mentions": ["华润三九"],
        "metric_mentions": ["营业收入"],
        "report_period": "FY",
        "time_range": {"mode": "single_year", "report_year": 2024},
    })

    assert plan["need_clarification"] is True
    assert "至少两家公司" in plan["clarification_reason"]


def test_company_compare_yoy_requires_metric():
    """公司同比对比需要明确指标。"""
    plan = validate_plan({
        "intent_type": "company_compare_yoy_query",
        "company_mentions": ["华润三九", "贵州茅台"],
        "metric_mentions": [],
        "report_period": "FY",
        "time_range": {"mode": "single_year", "report_year": 2024},
    })

    assert plan["need_clarification"] is True
    assert "指标" in plan["clarification_reason"]


def test_company_compare_yoy_requires_report_year():
    """公司同比对比需要明确当年年份。"""
    plan = validate_plan({
        "intent_type": "company_compare_yoy_query",
        "company_mentions": ["华润三九", "贵州茅台"],
        "metric_mentions": ["营业收入"],
        "report_period": "FY",
        "time_range": {"mode": "unspecified"},
    })

    assert plan["need_clarification"] is True
    assert "年份" in plan["clarification_reason"]


if __name__ == "__main__":
    tests = [
        test_company_compare_yoy_plan_keeps_unified_shape,
        test_company_compare_yoy_requires_two_companies,
        test_company_compare_yoy_requires_metric,
        test_company_compare_yoy_requires_report_year,
    ]
    passed = 0
    for test in tests:
        try:
            test()
            print(f"OK  {test.__name__}")
            passed += 1
        except Exception as exc:
            print(f"FAIL {test.__name__}: {exc}")
    print(f"\n{passed}/{len(tests)} passed")
