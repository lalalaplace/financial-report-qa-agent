"""V0.4.5 compare 结果结构统一测试。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.nodes.analyze_nodes.compare_analysis import analyze_compare_node, analyze_derived_compare_node
from agent.nodes.analyze_nodes.compare_trend_analysis import analyze_compare_trend_node, analyze_derived_compare_trend_node
from agent.nodes.analyze_nodes.compare_yoy_analysis import analyze_compare_yoy_node, analyze_derived_compare_yoy_node


COMPANIES = [
    {"stock_code": "000001", "stock_abbr": "A公司", "company_name": "A公司"},
    {"stock_code": "000002", "stock_abbr": "B公司", "company_name": "B公司"},
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
    "scale": 100,
    "precision": 2,
}

COMPARE_SPEC = {
    "operator": "higher",
    "target": None,
    "subject_company": None,
    "reference_company": None,
}

REQUIRED_RESULT_KEYS = {
    "metric_key",
    "metric_name",
    "metric_type",
    "unit",
    "status",
    "items",
    "compare_spec",
    "conclusion",
}

REQUIRED_CONCLUSION_KEYS = {
    "operator",
    "target",
    "winner_company",
    "loser_company",
    "diff",
    "diff_unit",
}


def _assert_compare_contract(result: dict, metric_type: str):
    assert REQUIRED_RESULT_KEYS <= set(result)
    assert REQUIRED_CONCLUSION_KEYS <= set(result["conclusion"])
    assert result["metric_type"] == metric_type
    assert result["compare_spec"]["operator"] == "higher"
    assert result["conclusion"]["operator"] == "higher"


def test_compare_result_schema_for_all_compare_families():
    base_point = analyze_compare_node({
        "intent_type": "company_compare_query",
        "companies": COMPANIES,
        "metrics": [BASE_METRIC],
        "report_year": 2024,
        "compare_spec": COMPARE_SPEC,
        "compare_query_results": [{
            "success": True,
            "columns": [
                "stock_code",
                "report_year",
                "income_sheet__total_operating_revenue",
            ],
            "rows": [
                ["000001", 2024, 100.0],
                ["000002", 2024, 200.0],
            ],
        }],
    })["compare_result"][0]
    _assert_compare_contract(base_point, "base")
    assert base_point["conclusion"]["target"] == "metric_value"

    derived_point = analyze_derived_compare_node({
        "intent_type": "company_compare_query",
        "companies": COMPANIES,
        "metrics": [DERIVED_METRIC],
        "report_year": 2024,
        "compare_spec": COMPARE_SPEC,
        "derived_compare_query_results": {
            "net_profit_margin": {
                "sql_success": True,
                "row_count": 2,
                "columns": ["stock_code", "numerator_value", "denominator_value"],
                "rows": [
                    ["000001", 10.0, 100.0],
                    ["000002", 30.0, 100.0],
                ],
            }
        },
    })["derived_compare_result"][0]
    _assert_compare_contract(derived_point, "derived")
    assert derived_point["status"] == "ok"

    base_trend = analyze_compare_trend_node({
        "intent_type": "company_compare_trend_query",
        "companies": COMPANIES,
        "metrics": [BASE_METRIC],
        "report_years": [2023, 2024],
        "compare_spec": COMPARE_SPEC,
        "compare_trend_query_results": [{
            "success": True,
            "columns": [
                "stock_code",
                "report_year",
                "income_sheet__total_operating_revenue",
            ],
            "rows": [
                ["000001", 2023, 100.0],
                ["000001", 2024, 120.0],
                ["000002", 2023, 200.0],
                ["000002", 2024, 250.0],
            ],
        }],
    })["compare_trend_result"][0]
    _assert_compare_contract(base_trend, "base")
    assert base_trend["conclusion"]["target"] == "latest_value"

    derived_trend = analyze_derived_compare_trend_node({
        "intent_type": "company_compare_trend_query",
        "companies": COMPANIES,
        "metrics": [DERIVED_METRIC],
        "report_years": [2023, 2024],
        "compare_spec": COMPARE_SPEC,
        "derived_compare_trend_query_results": {
            "net_profit_margin": {
                "sql_success": True,
                "row_count": 4,
                "columns": [
                    "stock_code",
                    "report_year",
                    "numerator_value",
                    "denominator_value",
                ],
                "rows": [
                    ["000001", 2023, 10.0, 100.0],
                    ["000001", 2024, 12.0, 100.0],
                    ["000002", 2023, 20.0, 100.0],
                    ["000002", 2024, 25.0, 100.0],
                ],
            }
        },
    })["derived_compare_trend_result"][0]
    _assert_compare_contract(derived_trend, "derived")

    base_yoy = analyze_compare_yoy_node({
        "intent_type": "company_compare_yoy_query",
        "companies": COMPANIES,
        "metrics": [BASE_METRIC],
        "report_year": 2024,
        "compare_spec": COMPARE_SPEC,
        "compare_yoy_query_results": [{
            "success": True,
            "columns": [
                "stock_code",
                "report_year",
                "income_sheet__total_operating_revenue",
            ],
            "rows": [
                ["000001", 2023, 100.0],
                ["000001", 2024, 110.0],
                ["000002", 2023, 100.0],
                ["000002", 2024, 130.0],
            ],
        }],
    })["compare_yoy_result"][0]
    _assert_compare_contract(base_yoy, "base")
    assert base_yoy["conclusion"]["target"] == "yoy_rate"

    derived_yoy = analyze_derived_compare_yoy_node({
        "intent_type": "company_compare_yoy_query",
        "companies": COMPANIES,
        "metrics": [DERIVED_METRIC],
        "report_year": 2024,
        "compare_spec": COMPARE_SPEC,
        "derived_compare_yoy_query_results": {
            "net_profit_margin": {
                "sql_success": True,
                "row_count": 4,
                "columns": [
                    "stock_code",
                    "report_year",
                    "numerator_value",
                    "denominator_value",
                ],
                "rows": [
                    ["000001", 2023, 10.0, 100.0],
                    ["000001", 2024, 15.0, 100.0],
                    ["000002", 2023, 20.0, 100.0],
                    ["000002", 2024, 30.0, 100.0],
                ],
            }
        },
    })["derived_compare_yoy_result"][0]
    _assert_compare_contract(derived_yoy, "derived")
    assert derived_yoy["conclusion"]["target"] == "derived_change"


if __name__ == "__main__":
    test_compare_result_schema_for_all_compare_families()
    print("V0.4.5 compare result schema tests passed")
