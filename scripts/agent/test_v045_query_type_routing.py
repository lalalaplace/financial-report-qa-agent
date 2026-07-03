"""V0.4.5 query type 路由稳定性回归测试。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.nodes.slot_nodes import check_slots_node
from agent.routing import route_by_intent
from agent.schemas.query_plan import VALID_INTENT_TYPES, validate_plan


EXPECTED_QUERY_TYPES = {
    "single_metric_query",
    "multi_metric_query",
    "trend_query",
    "yoy_query",
    "derived_metric_query",
    "company_compare_query",
    "company_compare_trend_query",
    "company_compare_yoy_query",
    "ranking_query",
    "yoy_ranking_query",
    "trend_ranking_query",
    "rank_position_query",
    "unknown",
}

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
    "formula": {
        "numerator": "net_profit",
        "denominator": "total_operating_revenue",
    },
}


def _ready_state(intent_type: str, metric: dict | None = None) -> dict:
    return {
        "intent_type": intent_type,
        "companies": COMPANIES,
        "metrics": [metric or BASE_METRIC],
        "report_year": 2024,
        "report_period": "FY",
        "time_mode": "single_year",
        "report_years": [2023, 2024],
    }


def test_query_type_list_is_stable():
    assert VALID_INTENT_TYPES == EXPECTED_QUERY_TYPES


def test_validate_plan_keeps_compare_trend_yoy_intents_with_derived_metric_names():
    common = {
        "company_mentions": ["A公司", "B公司"],
        "metric_mentions": ["净利率"],
        "report_period": "FY",
        "need_clarification": False,
    }

    point_plan = validate_plan({
        **common,
        "intent_type": "company_compare_query",
        "time_range": {"mode": "single_year", "report_year": 2024},
    })
    assert point_plan["intent_type"] == "company_compare_query"

    trend_plan = validate_plan({
        **common,
        "intent_type": "company_compare_trend_query",
        "time_range": {"mode": "explicit_range", "start_year": 2022, "end_year": 2024},
    })
    assert trend_plan["intent_type"] == "company_compare_trend_query"

    yoy_plan = validate_plan({
        **common,
        "intent_type": "company_compare_yoy_query",
        "time_range": {"mode": "single_year", "report_year": 2024},
    })
    assert yoy_plan["intent_type"] == "company_compare_yoy_query"


def test_route_by_intent_does_not_mix_compare_trend_yoy():
    assert route_by_intent(_ready_state("company_compare_query")) == "generate_compare_sql"
    assert (
        route_by_intent(_ready_state("company_compare_trend_query"))
        == "generate_compare_trend_sql"
    )
    assert (
        route_by_intent(_ready_state("company_compare_yoy_query"))
        == "generate_compare_yoy_sql"
    )


def test_derived_metrics_do_not_steal_compare_trend_yoy_intents():
    assert (
        route_by_intent(_ready_state("company_compare_query", DERIVED_METRIC))
        == "generate_derived_compare_sql"
    )
    assert (
        route_by_intent(_ready_state("company_compare_trend_query", DERIVED_METRIC))
        == "generate_derived_compare_trend_sql"
    )
    assert (
        route_by_intent(_ready_state("company_compare_yoy_query", DERIVED_METRIC))
        == "generate_derived_compare_yoy_sql"
    )
    assert (
        route_by_intent(_ready_state("trend_query", DERIVED_METRIC))
        == "generate_derived_trend_sql"
    )
    assert (
        route_by_intent(_ready_state("yoy_query", DERIVED_METRIC))
        == "generate_derived_yoy_sql"
    )


def test_ranking_query_routing_and_validation_v050():
    """V0.5.0：ranking_query 已支持，validator 正常校验。"""
    # 路由仍然正确
    assert route_by_intent({"intent_type": "ranking_query"}) == "generate_ranking_sql"

    # V0.5.0 有效 ranking 状态应通过校验
    valid_state = {
        "intent_type": "ranking_query",
        "companies": [],
        "company_mentions": [],
        "metrics": [BASE_METRIC],
        "metric_candidates": [],
        "report_year": 2024,
        "report_period": "FY",
        "rank_direction": "desc",
        "limit": 10,
        "time_range": {"mode": "single_year", "report_year": 2024},
    }
    checked = check_slots_node(valid_state)
    assert checked["need_clarification"] is False, (
        f"有效 ranking 状态应通过校验，实际 error_type={checked.get('error_type')}"
    )

    # 缺少 rank_direction 应触发澄清
    incomplete_state = {
        "intent_type": "ranking_query",
        "companies": [],
        "company_mentions": [],
        "metrics": [BASE_METRIC],
        "metric_candidates": [],
        "report_year": 2024,
        "report_period": "FY",
        "time_range": {"mode": "single_year", "report_year": 2024},
    }
    checked2 = check_slots_node(incomplete_state)
    assert checked2["need_clarification"] is True
    assert checked2["error_type"] == "clarification_required"
    assert checked2["clarification_type"] == "invalid_ranking_direction"
    assert checked2["empty_fields"] == ["ranking_direction"]


if __name__ == "__main__":
    tests = [
        test_query_type_list_is_stable,
        test_validate_plan_keeps_compare_trend_yoy_intents_with_derived_metric_names,
        test_route_by_intent_does_not_mix_compare_trend_yoy,
        test_derived_metrics_do_not_steal_compare_trend_yoy_intents,
        test_ranking_query_routing_and_validation_v050,
    ]
    for test in tests:
        test()
    print("V0.4.5 query type routing tests passed")
