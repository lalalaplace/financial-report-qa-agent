"""V0.5.4 区间增长排名查询测试。"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.nodes.answer_nodes.trend_ranking_answer import generate_trend_ranking_answer_node
from agent.nodes.analyze_nodes.trend_ranking_analysis import analyze_trend_ranking_node
from agent.nodes.slot_validators import trend_ranking_validator
from agent.nodes.sql_nodes.trend_ranking_sql import (
    _guard_trend_ranking_params,
    build_base_trend_ranking_sql,
    generate_trend_ranking_sql_node,
)
from agent.routing import route_analysis, route_by_intent
from agent.schemas.query_plan import validate_plan
from agent.tools.sql_tools import review_sql


BASE_METRIC = {
    "table": "income_sheet",
    "field": "operating_revenue",
    "metric_key": "operating_revenue",
    "metric_name": "营业收入",
    "metric_type": "base",
    "unit": "yuan",
}


def test_validate_plan_accepts_trend_ranking_query():
    plan = validate_plan(
        {
            "intent_type": "trend_ranking_query",
            "company_mentions": [],
            "metric_mentions": ["营业收入"],
            "report_period": "FY",
            "time_range": {
                "mode": "explicit_range",
                "start_year": 2022,
                "end_year": 2024,
            },
            "rank_direction": "desc",
            "limit": 10,
        }
    )
    assert plan["intent_type"] == "trend_ranking_query"
    assert plan["change_metric"] == "growth_rate"
    assert plan["time_range"]["mode"] == "explicit_range"


def test_validate_plan_accepts_year_range_alias():
    plan = validate_plan(
        {
            "intent_type": "trend_ranking_query",
            "company_mentions": [],
            "metric_mentions": ["营业收入"],
            "report_period": "FY",
            "time_range": {"mode": "year_range", "start_year": 2022, "end_year": 2024},
            "rank_direction": "asc",
            "limit": 5,
        }
    )
    assert plan["time_range"]["mode"] == "explicit_range"
    assert plan["change_metric"] == "growth_rate"


def test_validator_accepts_base_metric():
    result = trend_ranking_validator.validate(
        {
            "metrics": [BASE_METRIC],
            "companies": [],
            "company_mentions": [],
            "start_year": 2022,
            "end_year": 2024,
            "report_period": "FY",
            "time_range": {"mode": "explicit_range"},
            "rank_direction": "desc",
            "limit": 10,
            "change_metric": "growth_rate",
        }
    )
    assert result["need_clarification"] is False
    assert result["change_metric"] == "growth_rate"


def test_validator_rejects_relative_range():
    result = trend_ranking_validator.validate(
        {
            "metrics": [BASE_METRIC],
            "companies": [],
            "company_mentions": [],
            "start_year": 2022,
            "end_year": 2024,
            "report_period": "FY",
            "time_range": {"mode": "recent_n"},
            "rank_direction": "desc",
            "limit": 10,
            "change_metric": "growth_rate",
        }
    )
    assert result["error_type"] == "unsupported_trend_ranking_time_mode"


def test_validator_rejects_invalid_year_range():
    result = trend_ranking_validator.validate(
        {
            "metrics": [BASE_METRIC],
            "companies": [],
            "company_mentions": [],
            "start_year": 2024,
            "end_year": 2022,
            "time_range": {"mode": "explicit_range"},
            "rank_direction": "desc",
            "limit": 10,
            "change_metric": "growth_rate",
        }
    )
    assert result["error_type"] == "invalid_year_range"


def test_validator_rejects_derived_metric():
    result = trend_ranking_validator.validate(
        {
            "metrics": [{"metric_name": "净利率", "metric_type": "derived"}],
            "companies": [],
            "company_mentions": [],
            "start_year": 2022,
            "end_year": 2024,
            "time_range": {"mode": "explicit_range"},
            "rank_direction": "desc",
            "limit": 10,
            "change_metric": "growth_rate",
        }
    )
    assert result["error_type"] == "unsupported_metric_type"


def test_build_sql_contains_growth_rate_and_year_filters():
    sql = build_base_trend_ranking_sql(
        metric=BASE_METRIC,
        start_year=2022,
        end_year=2024,
        report_period="FY",
        rank_direction="desc",
        limit=10,
    )
    assert "AS growth_rate" in sql
    assert "start_t.report_year = 2022" in sql
    assert "end_t.report_year = 2024" in sql
    assert "ORDER BY growth_rate DESC, c.stock_code ASC" in sql


def test_trend_ranking_sql_passes_guard():
    sql = build_base_trend_ranking_sql(
        metric=BASE_METRIC,
        start_year=2022,
        end_year=2024,
        report_period="FY",
        rank_direction="asc",
        limit=5,
    )
    review = review_sql(sql)
    assert review["is_safe"], review.get("reason")


def test_guard_rejects_invalid_limit():
    with pytest.raises(ValueError, match="invalid trend ranking limit"):
        _guard_trend_ranking_params(51, "desc")


def test_node_generates_sql_metadata():
    result = generate_trend_ranking_sql_node(
        {
            "metrics": [BASE_METRIC],
            "need_clarification": False,
            "start_year": 2022,
            "end_year": 2024,
            "report_period": "FY",
            "rank_direction": "desc",
            "limit": 10,
        }
    )
    assert result["sql"]
    assert result["sql_metadata"]["change_metric"] == "growth_rate"


def test_routes_trend_ranking():
    assert route_by_intent({"intent_type": "trend_ranking_query", "metrics": [BASE_METRIC]}) == "generate_trend_ranking_sql"
    assert route_analysis({"intent_type": "trend_ranking_query"}) == "analyze_trend_ranking"


def test_analysis_and_answer():
    state = {
        "metrics": [BASE_METRIC],
        "start_year": 2022,
        "end_year": 2024,
        "report_period": "FY",
        "rank_direction": "desc",
        "limit": 1,
        "query_result": {
            "success": True,
            "columns": [
                "stock_code",
                "stock_abbr",
                "company_name",
                "start_year",
                "end_year",
                "report_period",
                "start_value",
                "end_value",
                "growth_rate",
            ],
            "rows": [["000001", "平安银行", "平安银行股份有限公司", 2022, 2024, "FY", 100.0, 150.0, 0.5]],
            "row_count": 1,
        },
    }
    analyzed = analyze_trend_ranking_node(state)
    assert analyzed["analysis_result"]["rows"][0]["display_growth_rate"] == "50.00%"

    answered = generate_trend_ranking_answer_node({**state, **analyzed})
    assert "增长率 50.00%" in answered["final_answer"]
    assert "区间增长率最高" in answered["final_answer"]
    assert "平均区间增长率" in answered["final_answer"]
    assert "正增长 1 家，负增长 0 家" in answered["final_answer"]
    assert answered["business_success"] is True


def test_answer_includes_trend_ranking_summary_for_topn():
    state = {
        "metrics": [BASE_METRIC],
        "start_year": 2022,
        "end_year": 2024,
        "report_period": "FY",
        "rank_direction": "desc",
        "limit": 2,
        "query_result": {
            "success": True,
            "columns": [
                "stock_code",
                "stock_abbr",
                "company_name",
                "start_year",
                "end_year",
                "report_period",
                "start_value",
                "end_value",
                "growth_rate",
            ],
            "rows": [
                ["000001", "A", "A公司", 2022, 2024, "FY", 100.0, 150.0, 0.5],
                ["000002", "B", "B公司", 2022, 2024, "FY", 100.0, 142.3, 0.423],
            ],
            "row_count": 2,
        },
    }
    analyzed = analyze_trend_ranking_node(state)
    answered = generate_trend_ranking_answer_node({**state, **analyzed})

    assert "其中，A公司区间增长率最高，为 50.00%" in answered["final_answer"]
    assert "平均区间增长率为 46.15%" in answered["final_answer"]
    assert "A公司比第二名B公司高 7.70 个百分点" in answered["final_answer"]


def test_answer_includes_trend_decline_summary_for_topn():
    state = {
        "metrics": [BASE_METRIC],
        "start_year": 2022,
        "end_year": 2024,
        "report_period": "FY",
        "rank_direction": "asc",
        "limit": 2,
        "query_result": {
            "success": True,
            "columns": [
                "stock_code",
                "stock_abbr",
                "company_name",
                "start_year",
                "end_year",
                "report_period",
                "start_value",
                "end_value",
                "growth_rate",
            ],
            "rows": [
                ["000001", "A", "A公司", 2022, 2024, "FY", 100.0, 60.0, -0.4],
                ["000002", "B", "B公司", 2022, 2024, "FY", 100.0, 80.0, -0.2],
            ],
            "row_count": 2,
        },
    }
    analyzed = analyze_trend_ranking_node(state)
    answered = generate_trend_ranking_answer_node({**state, **analyzed})

    assert "区间变化率 -40.00%" in answered["final_answer"]
    assert "区间下降最大或增长率最低" in answered["final_answer"]
    assert "平均区间变化率为 -30.00%" in answered["final_answer"]
