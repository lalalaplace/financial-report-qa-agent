"""V0.4.2 公司趋势对比场景测试。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.nodes.analyze_nodes.compare_trend_analysis import analyze_compare_trend_node, analyze_derived_compare_trend_node
from agent.nodes.slot_nodes import check_slots_node
from agent.nodes.answer_nodes.answer_dispatcher import generate_answer_node
from agent.nodes.sql_nodes.compare_trend_sql import generate_compare_trend_sql_node
from agent.nodes.sql_nodes.derived_sql import generate_derived_compare_trend_sql_node
from agent.routing import route_by_intent
from agent.schemas.query_plan import validate_plan
from agent.utils.logger import build_agent_run_log


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

NET_PROFIT_METRIC = {
    "metric_key": "net_profit",
    "metric_name": "净利润",
    "metric_type": "base",
    "table": "income_sheet",
    "field": "net_profit",
    "unit": "yuan",
}

TOTAL_ASSETS_METRIC = {
    "metric_key": "asset_total_assets",
    "metric_name": "总资产",
    "metric_type": "base",
    "table": "balance_sheet",
    "field": "asset_total_assets",
    "unit": "yuan",
}

DERIVED_METRIC = {
    "metric_key": "net_profit_margin",
    "metric_name": "净利率",
    "metric_type": "derived",
    "unit": "percent",
    "scale": 100,
    "precision": 2,
    "formula": {
        "numerator": "net_profit",
        "denominator": "total_operating_revenue",
    },
}


def _base_state(metrics):
    return {
        "intent_type": "company_compare_trend_query",
        "companies": COMPANIES,
        "metrics": metrics,
        "report_period": "FY",
        "time_mode": "explicit_range",
        "start_year": 2022,
        "end_year": 2024,
        "report_year": 2024,
        "report_years": [2022, 2023, 2024],
    }


def test_base_compare_trend_sql_and_answer():
    """base 指标支持多公司、多年份趋势对比。"""
    state = _base_state([BASE_METRIC])
    state.update(check_slots_node(state))

    assert not state.get("need_clarification")
    assert state["report_years"] == [2022, 2023, 2024]
    assert route_by_intent(state) == "generate_compare_trend_sql"

    state.update(generate_compare_trend_sql_node(state))
    assert len(state["compare_trend_sqls"]) == 1
    assert state["compare_trend_sqls"][0]["sql_id"] == "compare_trend_base_income_sheet_001"
    assert state["compare_trend_sqls"][0]["years"] == [2022, 2023, 2024]
    assert state["compare_trend_sqls"][0]["guard_passed"] is False
    assert "2022" in state["compare_trend_sqls"][0]["sql"]
    assert "2024" in state["compare_trend_sqls"][0]["sql"]

    state["compare_trend_query_results"] = [{
        "table": "income_sheet",
        "metric_keys": ["total_operating_revenue"],
        "success": True,
        "columns": [
            "stock_code", "stock_abbr", "company_name", "report_year", "report_period",
            "income_sheet__total_operating_revenue",
        ],
        "rows": [
            ["000999", "华润三九", "华润三九医药股份有限公司", 2022, "FY", 20_000_000_000],
            ["000999", "华润三九", "华润三九医药股份有限公司", 2023, "FY", 22_000_000_000],
            ["000999", "华润三九", "华润三九医药股份有限公司", 2024, "FY", 25_000_000_000],
            ["600519", "贵州茅台", "贵州茅台酒股份有限公司", 2022, "FY", 120_000_000_000],
            ["600519", "贵州茅台", "贵州茅台酒股份有限公司", 2023, "FY", 150_000_000_000],
            ["600519", "贵州茅台", "贵州茅台酒股份有限公司", 2024, "FY", 170_000_000_000],
        ],
        "row_count": 6,
        "error": None,
    }]
    state.update(analyze_compare_trend_node(state))
    state.update(generate_answer_node(state))

    assert state["compare_trend_result"][0]["status"] == "ok"
    assert state["compare_trend_result"][0]["years"] == [2022, 2023, 2024]
    assert state["compare_trend_result"][0]["items"][0]["series"][0]["year"] == 2022
    assert state["compare_trend_result"][0]["items"][0]["trend_direction"] == "up"
    assert state["compare_trend_result"][0]["latest_year_winner_company"] == "贵州茅台酒股份有限公司"
    assert state["compare_trend_result"][0]["largest_absolute_change_company"] == "贵州茅台酒股份有限公司"
    assert "2022 到 2024 年公司趋势对比结果如下" in state["final_answer"]
    assert "华润三九医药股份有限公司" in state["final_answer"]


def test_derived_compare_trend_sql_and_answer():
    """derived 指标支持多公司、多年份趋势对比。"""
    state = _base_state([DERIVED_METRIC])
    state.update(check_slots_node(state))

    assert route_by_intent(state) == "generate_derived_compare_trend_sql"
    state.update(generate_derived_compare_trend_sql_node(state))
    assert len(state["derived_compare_trend_sqls"]) == 1
    assert state["derived_compare_trend_sqls"][0]["sql_id"] == "derived_compare_trend_net_profit_margin_001"
    assert state["derived_compare_trend_sqls"][0]["years"] == [2022, 2023, 2024]
    assert state["derived_compare_trend_sqls"][0]["numerator"] == "net_profit"
    assert state["derived_compare_trend_sqls"][0]["denominator"] == "total_operating_revenue"
    assert state["derived_compare_trend_sqls"][0]["scale"] == 100
    assert state["derived_compare_trend_sqls"][0]["guard_passed"] is False

    state["derived_compare_trend_query_results"] = {
        "net_profit_margin": {
            "sql_success": True,
            "columns": [
                "stock_code", "stock_abbr", "company_name", "report_year", "report_period",
                "numerator_value", "denominator_value",
            ],
            "rows": [
                ["000999", "华润三九", "华润三九医药股份有限公司", 2022, "FY", 2_000_000_000, 20_000_000_000],
                ["000999", "华润三九", "华润三九医药股份有限公司", 2023, "FY", 2_420_000_000, 22_000_000_000],
                ["000999", "华润三九", "华润三九医药股份有限公司", 2024, "FY", 3_000_000_000, 25_000_000_000],
                ["600519", "贵州茅台", "贵州茅台酒股份有限公司", 2022, "FY", 60_000_000_000, 120_000_000_000],
                ["600519", "贵州茅台", "贵州茅台酒股份有限公司", 2023, "FY", 78_000_000_000, 150_000_000_000],
                ["600519", "贵州茅台", "贵州茅台酒股份有限公司", 2024, "FY", 88_400_000_000, 170_000_000_000],
            ],
            "row_count": 6,
            "error": None,
        }
    }
    state.update(analyze_derived_compare_trend_node(state))
    state.update(generate_answer_node(state))

    assert state["derived_compare_trend_result"][0]["status"] == "ok"
    assert state["derived_compare_trend_result"][0]["items"][0]["series"][0]["year"] == 2022
    assert state["derived_compare_trend_result"][0]["items"][0]["series"][0]["numerator"] == 2_000_000_000
    assert state["derived_compare_trend_result"][0]["items"][0]["series"][0]["denominator"] == 20_000_000_000
    assert state["derived_compare_trend_result"][0]["items"][0]["trend_direction"] == "up"
    assert state["derived_compare_trend_result"][0]["items"][0]["change_unit"] == "百分点"
    assert "净利率" in state["final_answer"]
    assert "%" in state["final_answer"]
    assert "相对增幅" not in state["final_answer"]


def test_mixed_compare_trend_unsupported():
    """base + derived 混合指标趋势对比不支持。"""
    state = _base_state([BASE_METRIC, DERIVED_METRIC])
    state.update(check_slots_node(state))

    assert state["need_clarification"]
    assert state["error_type"] == "unsupported_query"
    assert state["clarification_type"] == "unsupported_metric_for_intent"
    assert state["empty_fields"] == ["metrics"]


def test_query_plan_explicit_range_generates_report_years():
    """Planner schema 应从显式年份范围补齐 report_years。"""
    plan = validate_plan({
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

    assert plan["intent_type"] == "company_compare_trend_query"
    assert plan["time_range"]["report_years"] == [2022, 2023, 2024]
    assert not plan["need_clarification"]


def test_base_compare_trend_multi_metric_grouped_by_table():
    """base 多指标应按表分组生成多条 SQL。"""
    state = _base_state([BASE_METRIC, NET_PROFIT_METRIC, TOTAL_ASSETS_METRIC])
    state.update(check_slots_node(state))
    state.update(generate_compare_trend_sql_node(state))

    assert len(state["compare_trend_sqls"]) == 2
    sql_by_table = {entry["table"]: entry for entry in state["compare_trend_sqls"]}
    assert sql_by_table["income_sheet"]["metric_keys"] == [
        "total_operating_revenue",
        "net_profit",
    ]
    assert sql_by_table["balance_sheet"]["metric_keys"] == ["asset_total_assets"]
    assert sql_by_table["income_sheet"]["sql_id"] == "compare_trend_base_income_sheet_001"
    assert sql_by_table["balance_sheet"]["sql_id"] == "compare_trend_base_balance_sheet_002"


def test_base_compare_trend_partial_missing_year():
    """部分公司或部分年份缺值时，应标记 partial_compare_trend_unavailable。"""
    state = _base_state([BASE_METRIC])
    state["compare_trend_query_results"] = [{
        "table": "income_sheet",
        "metric_keys": ["total_operating_revenue"],
        "success": True,
        "columns": [
            "stock_code", "stock_abbr", "company_name", "report_year", "report_period",
            "income_sheet__total_operating_revenue",
        ],
        "rows": [
            ["000999", "华润三九", "华润三九医药股份有限公司", 2022, "FY", 20_000_000_000],
            ["000999", "华润三九", "华润三九医药股份有限公司", 2023, "FY", None],
            ["000999", "华润三九", "华润三九医药股份有限公司", 2024, "FY", 25_000_000_000],
            ["600519", "贵州茅台", "贵州茅台酒股份有限公司", 2022, "FY", None],
            ["600519", "贵州茅台", "贵州茅台酒股份有限公司", 2023, "FY", None],
            ["600519", "贵州茅台", "贵州茅台酒股份有限公司", 2024, "FY", None],
        ],
        "row_count": 6,
        "error": None,
    }]
    state.update(analyze_compare_trend_node(state))
    state.update(generate_answer_node(state))

    result = state["compare_trend_result"][0]
    assert result["status"] == "partial_compare_trend_unavailable"
    assert result["items"][0]["series"][1]["status"] == "missing_record"
    assert result["items"][1]["status"] == "no_valid_points"
    assert state["business_success"] is True
    assert state["error_type"] == "partial_compare_trend_unavailable"


def test_derived_compare_trend_zero_denominator_partial():
    """derived 指标遇到分母为 0 应标记 zero_denominator 并进入 partial。"""
    state = _base_state([DERIVED_METRIC])
    state["derived_compare_trend_query_results"] = {
        "net_profit_margin": {
            "sql_success": True,
            "columns": [
                "stock_code", "stock_abbr", "company_name", "report_year", "report_period",
                "numerator_value", "denominator_value",
            ],
            "rows": [
                ["000999", "华润三九", "华润三九医药股份有限公司", 2022, "FY", 2_000_000_000, 20_000_000_000],
                ["000999", "华润三九", "华润三九医药股份有限公司", 2023, "FY", 2_420_000_000, 0],
                ["000999", "华润三九", "华润三九医药股份有限公司", 2024, "FY", 3_000_000_000, 25_000_000_000],
                ["600519", "贵州茅台", "贵州茅台酒股份有限公司", 2022, "FY", 60_000_000_000, 120_000_000_000],
                ["600519", "贵州茅台", "贵州茅台酒股份有限公司", 2023, "FY", 78_000_000_000, 150_000_000_000],
                ["600519", "贵州茅台", "贵州茅台酒股份有限公司", 2024, "FY", 88_400_000_000, 170_000_000_000],
            ],
            "row_count": 6,
            "error": None,
        }
    }
    state.update(analyze_derived_compare_trend_node(state))
    state.update(generate_answer_node(state))

    result = state["derived_compare_trend_result"][0]
    assert result["status"] == "partial_derived_compare_trend_unavailable"
    assert result["items"][0]["series"][1]["status"] == "zero_denominator"
    assert result["items"][0]["change_unit"] == "百分点"
    assert state["error_type"] == "partial_derived_compare_trend_unavailable"
    assert "相对增幅" not in state["final_answer"]


def test_logger_records_compare_trend_fields():
    """日志应保留诊断公司趋势对比所需字段。"""
    state = _base_state([BASE_METRIC])
    state.update({
        "compare_trend_sqls": [{
            "sql_id": "compare_trend_base_income_sheet_001",
            "table": "income_sheet",
            "metric_keys": ["total_operating_revenue"],
            "years": [2022, 2023, 2024],
            "sql": "SELECT 1",
            "guard_passed": True,
        }],
        "compare_trend_query_results": [{
            "sql_id": "compare_trend_base_income_sheet_001",
            "table": "income_sheet",
            "metric_keys": ["total_operating_revenue"],
            "success": True,
            "row_count": 6,
            "error": None,
            "guard_passed": True,
        }],
        "compare_trend_result": [{
            "metric_key": "total_operating_revenue",
            "metric_name": "营业收入",
            "metric_type": "base",
            "unit": "yuan",
            "years": [2022, 2023, 2024],
            "items": [],
            "status": "ok",
        }],
        "final_answer": "answer",
        "sql_success": True,
        "business_success": True,
        "error_type": None,
    })

    record = build_agent_run_log(state)
    assert record["intent_type"] == "company_compare_trend_query"
    assert record["start_year"] == 2022
    assert record["end_year"] == 2024
    assert record["compare_trend_sqls"][0]["guard_passed"] is True
    assert record["compare_trend_query_results"][0]["row_count"] == 6
    assert record["compare_trend_result"][0]["years"] == [2022, 2023, 2024]
    assert record["compare_trend_route"] == "base"


if __name__ == "__main__":
    tests = [
        test_base_compare_trend_sql_and_answer,
        test_derived_compare_trend_sql_and_answer,
        test_mixed_compare_trend_unsupported,
        test_query_plan_explicit_range_generates_report_years,
        test_base_compare_trend_multi_metric_grouped_by_table,
        test_base_compare_trend_partial_missing_year,
        test_derived_compare_trend_zero_denominator_partial,
        test_logger_records_compare_trend_fields,
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
