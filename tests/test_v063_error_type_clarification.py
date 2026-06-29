"""V0.6.3 error_type、澄清出口与 SimpleCompiledGraph 链路稳定性测试。"""

from __future__ import annotations

import inspect

import agent.graph_runtime as graph_runtime_module
import agent.routing as routing_module
from agent.nodes.answer_nodes.clarify_answer import generate_unsupported_answer_node
from agent.nodes.slot_nodes import check_slots_node


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

COMPANY = {
    "stock_code": "000999",
    "stock_abbr": "华润三九",
    "company_name": "华润三九医药股份有限公司",
}


def _assert_clarification_fields(result: dict, expected_error_type: str, expected_empty_fields: list[str]) -> None:
    assert result["need_clarification"] is True
    assert result["business_success"] is False
    assert isinstance(result["clarification_question"], str)
    assert result["clarification_question"]
    assert result["error_type"] == expected_error_type
    assert result["empty_fields"] == expected_empty_fields


def test_unknown_unsupported_error_type_uses_neutral_fallback():
    result = generate_unsupported_answer_node({"error_type": "unsupported_future_case"})

    assert result["need_clarification"] is True
    assert result["business_success"] is False
    assert result["error_type"] == "unsupported_future_case"
    assert result["final_answer"] == result["clarification_question"]
    assert "混合趋势" not in result["final_answer"]
    assert "当前版本暂不支持该查询" in result["final_answer"]


def test_known_unsupported_error_type_keeps_specific_message():
    result = generate_unsupported_answer_node({"error_type": "unsupported_mixed_yoy"})

    assert "混合同比" in result["final_answer"]
    assert result["error_type"] == "unsupported_mixed_yoy"


def test_slot_missing_company_outputs_stable_clarification_fields():
    result = check_slots_node(
        {
            "intent_type": "single_metric_query",
            "companies": [],
            "company_candidates": [],
            "metrics": [BASE_METRIC],
            "metric_candidates": [],
            "report_year": 2024,
            "report_period": "FY",
        }
    )

    _assert_clarification_fields(result, "clarification_required", ["companies"])
    assert result["clarification_type"] == "missing_company"


def test_slot_missing_metric_outputs_stable_clarification_fields():
    result = check_slots_node(
        {
            "intent_type": "single_metric_query",
            "companies": [COMPANY],
            "company_candidates": [],
            "metrics": [],
            "metric_candidates": [],
            "report_year": 2024,
            "report_period": "FY",
        }
    )

    _assert_clarification_fields(result, "clarification_required", ["metrics"])
    assert result["clarification_type"] == "missing_metric"


def test_slot_missing_year_outputs_stable_clarification_fields():
    result = check_slots_node(
        {
            "intent_type": "yoy_query",
            "companies": [COMPANY],
            "company_candidates": [],
            "metrics": [BASE_METRIC],
            "metric_candidates": [],
            "report_year": None,
            "report_period": "FY",
        }
    )

    _assert_clarification_fields(result, "clarification_required", ["report_year"])
    assert result["clarification_type"] == "missing_year"


def test_slot_missing_ranking_limit_outputs_stable_clarification_fields():
    result = check_slots_node(
        {
            "intent_type": "ranking_query",
            "companies": [],
            "company_mentions": [],
            "metrics": [BASE_METRIC],
            "metric_candidates": [],
            "report_year": 2024,
            "report_period": "FY",
            "rank_direction": "desc",
            "limit": None,
            "time_range": {"mode": "single_year", "report_year": 2024},
        }
    )

    _assert_clarification_fields(result, "clarification_required", ["ranking_limit"])
    assert result["clarification_type"] == "missing_ranking_limit"


def test_simple_compiled_graph_has_supported_intent_chains_registered():
    runtime_source = inspect.getsource(graph_runtime_module.SimpleCompiledGraph.invoke)
    routing_source = inspect.getsource(routing_module)
    expected_tokens = {
        "single_metric_query": ["generate_point_sql", "review_and_execute_sql_node", "generate_answer_node"],
        "multi_metric_query": ["generate_point_sql", "review_and_execute_sql_node", "generate_answer_node"],
        "derived_metric_query": ["generate_derived_sql", "analyze_derived_metric_node", "generate_derived_answer_node"],
        "trend_query": ["generate_trend_sql", "generate_derived_trend_sql", "analyze_trend_node", "analyze_derived_trend_node", "generate_derived_trend_answer_node"],
        "yoy_query": ["generate_yoy_sql", "generate_derived_yoy_sql", "analyze_yoy_node", "analyze_derived_yoy_node", "generate_derived_yoy_answer_node"],
        "company_compare_query": ["generate_compare_sql", "generate_derived_compare_sql", "analyze_compare_node", "analyze_derived_compare_node", "generate_answer_node"],
        "company_compare_trend_query": ["generate_compare_trend_sql", "generate_derived_compare_trend_sql", "analyze_compare_trend_node", "analyze_derived_compare_trend_node", "generate_answer_node"],
        "company_compare_yoy_query": ["generate_compare_yoy_sql", "generate_derived_compare_yoy_sql", "analyze_compare_yoy_node", "analyze_derived_compare_yoy_node", "generate_answer_node"],
        "ranking_query": ["generate_ranking_sql", "analyze_ranking_node", "generate_answer_node"],
        "yoy_ranking_query": ["generate_yoy_ranking_sql", "analyze_yoy_ranking_node", "generate_answer_node"],
        "trend_ranking_query": ["generate_trend_ranking_sql", "analyze_trend_ranking_node", "generate_answer_node"],
        "rank_position_query": ["generate_rank_position_sql", "analyze_rank_position_node", "generate_answer_node"],
    }

    for intent_type, tokens in expected_tokens.items():
        assert intent_type in routing_source or intent_type in runtime_source
        for token in tokens:
            assert token in runtime_source
