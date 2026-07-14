"""V0.5.5 指定公司排名位置查询测试。"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.nodes.answer_nodes.rank_position_answer import generate_rank_position_answer_node
from agent.nodes.analyze_nodes.rank_position_analysis import analyze_rank_position_node
from agent.nodes.slot_validators import rank_position_validator
from agent.nodes.sql_nodes.rank_position_sql import (
    _guard_rank_position_params,
    build_base_rank_position_sql,
    build_derived_rank_position_sql,
    generate_rank_position_sql_node,
)
from agent.routing import route_analysis, route_by_intent
from agent.schemas.query_plan import validate_plan
from agent.tools.sql_tools import review_sql


COMPANY = {
    "stock_code": "000999",
    "stock_abbr": "华润三九",
    "company_name": "华润三九医药股份有限公司",
}

BASE_METRIC = {
    "table": "income_sheet",
    "field": "operating_revenue",
    "metric_key": "operating_revenue",
    "metric_name": "营业收入",
    "metric_type": "base",
    "unit": "yuan",
}

DERIVED_METRIC = {
    "metric_key": "net_profit_margin",
    "metric_name": "净利率",
    "metric_type": "derived",
    "unit": "percent",
    "scale": 100,
    "precision": 2,
    "formula": {"numerator": "net_profit", "denominator": "operating_revenue"},
}


def test_validate_plan_accepts_rank_position_query():
    plan = validate_plan(
        {
            "intent_type": "rank_position_query",
            "company_mentions": ["华润三九"],
            "metric_mentions": ["营业收入"],
            "report_period": "FY",
            "time_range": {"mode": "single_year", "report_year": 2024},
            "rank_direction": "desc",
            "limit": 10,
        }
    )
    assert plan["intent_type"] == "rank_position_query"
    assert plan["rank_direction"] == "desc"
    assert plan["limit"] is None


def test_validator_accepts_single_company_single_metric():
    result = rank_position_validator.validate(
        {
            "companies": [COMPANY],
            "metrics": [BASE_METRIC],
            "report_year": 2024,
            "time_mode": "single_year",
            "rank_direction": "desc",
        }
    )
    assert result["need_clarification"] is False
    assert result["limit"] is None


def test_validator_rejects_multiple_companies():
    result = rank_position_validator.validate(
        {
            "companies": [COMPANY, {**COMPANY, "stock_code": "000538"}],
            "metrics": [BASE_METRIC],
            "report_year": 2024,
            "time_mode": "single_year",
            "rank_direction": "desc",
        }
    )
    assert result["error_type"] == "multiple_companies_not_supported"


def test_validator_rejects_year_range():
    result = rank_position_validator.validate(
        {
            "companies": [COMPANY],
            "metrics": [BASE_METRIC],
            "report_year": 2024,
            "time_mode": "explicit_range",
            "rank_direction": "desc",
        }
    )
    assert result["error_type"] == "unsupported_rank_position_time_mode"


def test_base_sql_uses_rank_window_and_company_filter():
    sql = build_base_rank_position_sql(
        metric=BASE_METRIC,
        company=COMPANY,
        report_year=2024,
        report_period="FY",
        rank_direction="desc",
    )
    assert "WITH ranked AS" in sql
    assert "RANK() OVER" in sql
    assert "COUNT(*) OVER ()" in sql
    assert "i.report_year = 2024" in sql
    assert "i.report_period = 'FY'" in sql
    assert "i.operating_revenue IS NOT NULL" in sql
    assert "WHERE stock_code = '000999'" in sql


def test_derived_sql_uses_nullif_and_rank_window():
    sql = build_derived_rank_position_sql(
        metric=DERIVED_METRIC,
        company=COMPANY,
        num_info={"table": "income_sheet", "field": "net_profit", "metric_name": "净利润"},
        den_info={"table": "income_sheet", "field": "operating_revenue", "metric_name": "营业收入"},
        num_table="income_sheet",
        den_table="income_sheet",
        num_alias="i",
        den_alias="i",
        report_year=2024,
        report_period="FY",
        rank_direction="asc",
    )
    assert "NULLIF(CAST(i.operating_revenue AS NUMERIC), 0)" in sql
    assert "i.operating_revenue != 0" in sql
    assert "RANK() OVER" in sql
    assert "ORDER BY net_profit_margin ASC" in sql


def test_rank_position_sql_passes_guard():
    sql = build_base_rank_position_sql(
        metric=BASE_METRIC,
        company=COMPANY,
        report_year=2024,
        report_period="FY",
        rank_direction="desc",
    )
    review = review_sql(sql)
    assert review["is_safe"], review.get("reason")


def test_guard_rejects_invalid_inputs():
    with pytest.raises(ValueError, match="exactly one company"):
        _guard_rank_position_params([], [BASE_METRIC], "desc")
    with pytest.raises(ValueError, match="exactly one metric"):
        _guard_rank_position_params([COMPANY], [], "desc")
    with pytest.raises(ValueError, match="invalid rank_direction"):
        _guard_rank_position_params([COMPANY], [BASE_METRIC], "up")


def test_node_generates_base_sql_metadata():
    result = generate_rank_position_sql_node(
        {
            "companies": [COMPANY],
            "metrics": [BASE_METRIC],
            "report_year": 2024,
            "report_period": "FY",
            "rank_direction": "desc",
        }
    )
    assert result["sql"]
    assert result["sql_metadata"]["metric_type"] == "base"


def test_routes_rank_position():
    assert route_by_intent({"intent_type": "rank_position_query", "metrics": [BASE_METRIC]}) == "generate_rank_position_sql"
    assert route_analysis({"intent_type": "rank_position_query"}) == "analyze_rank_position"


def test_analysis_and_answer():
    state = {
        "companies": [COMPANY],
        "metrics": [BASE_METRIC],
        "report_year": 2024,
        "report_period": "FY",
        "rank_direction": "desc",
        "sql_metadata": {
            "column_alias": "income_sheet__operating_revenue",
            "unit": "yuan",
        },
        "query_result": {
            "success": True,
            "columns": [
                "stock_code",
                "stock_abbr",
                "company_name",
                "report_year",
                "report_period",
                "income_sheet__operating_revenue",
                "rank_no",
                "total_count",
            ],
            "rows": [["000999", "华润三九", "华润三九医药股份有限公司", 2024, "FY", 123456789.0, 3, 42]],
            "row_count": 1,
        },
    }
    analyzed = analyze_rank_position_node(state)
    assert analyzed["analysis_result"]["rank_no"] == 3
    assert analyzed["analysis_result"]["total_count"] == 42

    answered = generate_rank_position_answer_node({**state, **analyzed})
    assert "排名第 3 / 42" in answered["final_answer"]
    assert "123.46 万元" not in answered["final_answer"]
    assert "处于前 10% 区间" in answered["final_answer"]
    assert "属于前 25%" in answered["final_answer"]
    assert "华润三九处于" in answered["final_answer"]
    assert answered["business_success"] is True
