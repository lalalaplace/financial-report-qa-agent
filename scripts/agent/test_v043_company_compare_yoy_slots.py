"""V0.4.3 公司同比对比准入规则测试。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.nodes.slot_nodes import check_slots_node
from agent.nodes.answer_nodes.clarify_answer import build_clarification_response_node


COMPANIES = [
    {"stock_code": "000999", "stock_abbr": "华润三九", "company_name": "华润三九医药股份有限公司"},
    {"stock_code": "600519", "stock_abbr": "贵州茅台", "company_name": "贵州茅台酒股份有限公司"},
]

BASE_METRIC = {
    "metric_key": "total_operating_revenue",
    "metric_name": "营业收入",
    "metric_type": "base",
    "table": "income_sheet",
    "field": "total_operating_revenue",
    "unit": "yuan",
}

DERIVED_METRIC = {
    "metric_key": "net_profit_margin",
    "metric_name": "净利率",
    "metric_type": "derived",
    "unit": "percent",
    "formula": {"numerator": "net_profit", "denominator": "total_operating_revenue"},
}


def _state(**overrides):
    state = {
        "intent_type": "company_compare_yoy_query",
        "companies": COMPANIES,
        "metrics": [BASE_METRIC],
        "report_year": 2024,
        "report_period": "FY",
        "warnings": [],
    }
    state.update(overrides)
    return state


def test_company_compare_yoy_requires_two_companies():
    """公司同比对比至少需要两家公司。"""
    result = check_slots_node(_state(companies=COMPANIES[:1]))

    assert result["need_clarification"] is True
    assert result["error_type"] == "clarification_required"
    assert result["clarification_type"] == "missing_company"
    assert result["empty_fields"] == ["companies"]


def test_company_compare_yoy_requires_metric():
    """公司同比对比至少需要一个指标。"""
    result = check_slots_node(_state(metrics=[]))

    assert result["need_clarification"] is True
    assert result["error_type"] == "clarification_required"
    assert result["clarification_type"] == "missing_metric"
    assert result["empty_fields"] == ["metrics"]


def test_company_compare_yoy_requires_report_year():
    """公司同比对比需要明确报告年份。"""
    result = check_slots_node(_state(report_year=None))

    assert result["need_clarification"] is True
    assert result["error_type"] == "clarification_required"
    assert result["clarification_type"] == "missing_year"
    assert result["empty_fields"] == ["report_year"]


def test_company_compare_yoy_rejects_mixed_metric_types():
    """公司同比对比暂不支持原始指标和派生指标混合。"""
    result = check_slots_node(_state(metrics=[BASE_METRIC, DERIVED_METRIC]))

    assert result["need_clarification"] is True
    assert result["error_type"] == "unsupported_query"
    assert result["clarification_type"] == "unsupported_metric_for_intent"
    assert result["empty_fields"] == ["metrics"]

    answer = build_clarification_response_node(result)
    assert answer["error_type"] == "unsupported_query"
    assert "混合同比对比" in answer["final_answer"]


def test_company_compare_yoy_ready_fills_report_years():
    """准入通过时补齐上一年和当年。"""
    result = check_slots_node(_state(report_years=[]))

    assert result["need_clarification"] is False
    assert result["error_type"] is None
    assert result["report_period"] == "FY"
    assert result["time_mode"] == "single_year"
    assert result["report_years"] == [2023, 2024]


if __name__ == "__main__":
    tests = [
        test_company_compare_yoy_requires_two_companies,
        test_company_compare_yoy_requires_metric,
        test_company_compare_yoy_requires_report_year,
        test_company_compare_yoy_rejects_mixed_metric_types,
        test_company_compare_yoy_ready_fills_report_years,
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
