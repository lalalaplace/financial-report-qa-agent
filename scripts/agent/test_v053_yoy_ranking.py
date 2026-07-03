"""V0.5.3 同比排名查询测试。"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.nodes.answer_nodes.yoy_ranking_answer import generate_yoy_ranking_answer_node
from agent.nodes.analyze_nodes.yoy_ranking_analysis import analyze_yoy_ranking_node
from agent.nodes.slot_validators import yoy_ranking_validator
from agent.nodes.sql_nodes.yoy_ranking_sql import (
    _guard_yoy_ranking_params,
    build_base_yoy_ranking_sql,
    generate_yoy_ranking_sql_node,
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


def test_validate_plan_accepts_yoy_ranking_query():
    plan = validate_plan(
        {
            "intent_type": "yoy_ranking_query",
            "company_mentions": [],
            "metric_mentions": ["营业收入"],
            "report_period": "FY",
            "time_range": {"mode": "single_year", "report_year": 2024},
            "rank_direction": "desc",
            "limit": 10,
        }
    )
    assert plan["intent_type"] == "yoy_ranking_query"
    assert plan["change_metric"] == "yoy_rate"
    assert plan["rank_direction"] == "desc"


def test_validator_accepts_base_metric():
    result = yoy_ranking_validator.validate(
        {
            "metrics": [BASE_METRIC],
            "companies": [],
            "company_mentions": [],
            "report_year": 2024,
            "report_period": "FY",
            "time_range": {"mode": "single_year"},
            "rank_direction": "desc",
            "limit": 10,
        }
    )
    assert result["need_clarification"] is False
    assert result["change_metric"] == "yoy_rate"


def test_validator_rejects_derived_metric():
    result = yoy_ranking_validator.validate(
        {
            "metrics": [{"metric_name": "净利率", "metric_type": "derived"}],
            "companies": [],
            "company_mentions": [],
            "report_year": 2024,
            "report_period": "FY",
            "time_range": {"mode": "single_year"},
            "rank_direction": "desc",
            "limit": 10,
        }
    )
    assert result["need_clarification"] is True
    assert result["error_type"] == "unsupported_metric_type"


def test_validator_requires_limit():
    result = yoy_ranking_validator.validate(
        {
            "metrics": [BASE_METRIC],
            "companies": [],
            "company_mentions": [],
            "report_year": 2024,
            "report_period": "FY",
            "time_range": {"mode": "single_year"},
            "rank_direction": "desc",
            "limit": None,
        }
    )
    assert result["error_type"] == "missing_limit"


def test_build_sql_contains_yoy_rate_and_previous_year_join():
    sql = build_base_yoy_ranking_sql(
        metric=BASE_METRIC,
        report_year=2024,
        report_period="FY",
        rank_direction="desc",
        limit=10,
    )
    assert "AS yoy_rate" in sql
    assert "curr.report_year = prev.report_year + 1" in sql
    assert "ORDER BY yoy_rate DESC, c.stock_code ASC" in sql
    assert "LIMIT 10" in sql


def test_yoy_ranking_sql_passes_guard():
    sql = build_base_yoy_ranking_sql(
        metric=BASE_METRIC,
        report_year=2024,
        report_period="FY",
        rank_direction="asc",
        limit=5,
    )
    review = review_sql(sql)
    assert review["is_safe"], review.get("reason")


def test_guard_rejects_invalid_limit():
    with pytest.raises(ValueError, match="invalid yoy ranking limit"):
        _guard_yoy_ranking_params(51, "desc")


def test_node_generates_sql_metadata():
    result = generate_yoy_ranking_sql_node(
        {
            "metrics": [BASE_METRIC],
            "need_clarification": False,
            "report_year": 2024,
            "report_period": "FY",
            "rank_direction": "desc",
            "limit": 10,
        }
    )
    assert result["sql"]
    assert result["sql_metadata"]["change_metric"] == "yoy_rate"


def test_routes_yoy_ranking():
    assert route_by_intent({"intent_type": "yoy_ranking_query", "metrics": [BASE_METRIC]}) == "generate_yoy_ranking_sql"
    assert route_analysis({"intent_type": "yoy_ranking_query"}) == "analyze_yoy_ranking"


def test_analysis_and_answer():
    state = {
        "metrics": [BASE_METRIC],
        "report_year": 2024,
        "report_period": "FY",
        "rank_direction": "desc",
        "limit": 1,
        "query_result": {
            "success": True,
            "columns": [
                "stock_code",
                "stock_abbr",
                "company_name",
                "report_year",
                "report_period",
                "current_value",
                "previous_value",
                "yoy_rate",
            ],
            "rows": [["000001", "平安银行", "平安银行股份有限公司", 2024, "FY", 123.0, 100.0, 0.23]],
            "row_count": 1,
        },
    }
    analyzed = analyze_yoy_ranking_node(state)
    assert analyzed["analysis_result"]["rows"][0]["display_yoy_rate"] == "23.00%"

    answered = generate_yoy_ranking_answer_node({**state, **analyzed})
    assert "同比增长 23.00%" in answered["final_answer"]
    assert "同比增速最高" in answered["final_answer"]
    assert "平均同比增速" in answered["final_answer"]
    assert "正增长 1 家，负增长 0 家" in answered["final_answer"]
    assert answered["business_success"] is True


def test_answer_includes_yoy_ranking_summary_for_topn():
    state = {
        "metrics": [BASE_METRIC],
        "report_year": 2024,
        "report_period": "FY",
        "rank_direction": "desc",
        "limit": 2,
        "query_result": {
            "success": True,
            "columns": [
                "stock_code",
                "stock_abbr",
                "company_name",
                "report_year",
                "report_period",
                "current_value",
                "previous_value",
                "yoy_rate",
            ],
            "rows": [
                ["000001", "A", "A公司", 2024, "FY", 135.2, 100.0, 0.352],
                ["000002", "B", "B公司", 2024, "FY", 128.1, 100.0, 0.281],
            ],
            "row_count": 2,
        },
    }
    analyzed = analyze_yoy_ranking_node(state)
    answered = generate_yoy_ranking_answer_node({**state, **analyzed})

    assert "其中，A公司同比增速最高，为 35.20%" in answered["final_answer"]
    assert "平均同比增速为 31.65%" in answered["final_answer"]
    assert "A公司比第二名B公司高 7.10 个百分点" in answered["final_answer"]


def test_answer_includes_yoy_decline_summary_for_topn():
    state = {
        "metrics": [BASE_METRIC],
        "report_year": 2024,
        "report_period": "FY",
        "rank_direction": "asc",
        "limit": 2,
        "query_result": {
            "success": True,
            "columns": [
                "stock_code",
                "stock_abbr",
                "company_name",
                "report_year",
                "report_period",
                "current_value",
                "previous_value",
                "yoy_rate",
            ],
            "rows": [
                ["000001", "A", "A公司", 2024, "FY", 70.0, 100.0, -0.3],
                ["000002", "B", "B公司", 2024, "FY", 85.0, 100.0, -0.15],
            ],
            "row_count": 2,
        },
    }
    analyzed = analyze_yoy_ranking_node(state)
    answered = generate_yoy_ranking_answer_node({**state, **analyzed})

    assert "同比变化 -30.00%" in answered["final_answer"]
    assert "同比下降最大或增速最低" in answered["final_answer"]
    assert "平均同比变化率为 -22.50%" in answered["final_answer"]
