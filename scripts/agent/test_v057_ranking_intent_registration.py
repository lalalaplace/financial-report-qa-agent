"""V0.5.7 ranking 系列 intent 注册一致性测试。"""

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import agent.graph as graph_module
import agent.graph_runtime as graph_runtime_module
from agent.nodes import slot_nodes
from agent.nodes.answer_nodes import answer_dispatcher
from agent.nodes.slot_validators import (
    rank_position_validator,
    trend_ranking_validator,
    yoy_ranking_validator,
)
from agent.nodes.sql_nodes import (
    rank_position_sql,
    trend_ranking_sql,
    yoy_ranking_sql,
)
from agent.nodes.analyze_nodes import (
    rank_position_analysis,
    trend_ranking_analysis,
    yoy_ranking_analysis,
)
from agent.routing import route_analysis, route_by_intent
from agent.schemas.query_plan import VALID_INTENT_TYPES, validate_plan


BASE_METRIC = {
    "table": "income_sheet",
    "field": "operating_revenue",
    "metric_key": "operating_revenue",
    "metric_name": "营业收入",
    "metric_type": "base",
    "unit": "yuan",
}

COMPANY = {
    "stock_code": "000999",
    "stock_abbr": "华润三九",
    "company_name": "华润三九医药股份有限公司",
}

RANKING_INTENTS = {
    "yoy_ranking_query": {
        "sql_route": "generate_yoy_ranking_sql",
        "analysis_route": "analyze_yoy_ranking",
        "change_metric": "yoy_rate",
    },
    "trend_ranking_query": {
        "sql_route": "generate_trend_ranking_sql",
        "analysis_route": "analyze_trend_ranking",
        "change_metric": "growth_rate",
    },
    "rank_position_query": {
        "sql_route": "generate_rank_position_sql",
        "analysis_route": "analyze_rank_position",
        "change_metric": None,
    },
}


def test_ranking_intents_are_registered_in_schema_and_routes():
    for intent, expected in RANKING_INTENTS.items():
        assert intent in VALID_INTENT_TYPES
        assert route_by_intent({"intent_type": intent, "metrics": [BASE_METRIC]}) == expected["sql_route"]
        assert route_analysis({"intent_type": intent}) == expected["analysis_route"]


def test_validate_plan_normalizes_ranking_specific_fields():
    yoy_plan = validate_plan(
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
    assert yoy_plan["change_metric"] == "yoy_rate"

    trend_plan = validate_plan(
        {
            "intent_type": "trend_ranking_query",
            "company_mentions": [],
            "metric_mentions": ["营业收入"],
            "report_period": "FY",
            "time_range": {"mode": "explicit_range", "start_year": 2022, "end_year": 2024},
            "rank_direction": "desc",
            "limit": 10,
        }
    )
    assert trend_plan["change_metric"] == "growth_rate"

    position_plan = validate_plan(
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
    assert position_plan["limit"] is None
    assert position_plan["change_metric"] is None


def test_ranking_intents_have_validators_sql_and_analysis_nodes():
    assert slot_nodes.check_slots_node(
        {
            "intent_type": "yoy_ranking_query",
            "companies": [],
            "company_mentions": [],
            "metrics": [BASE_METRIC],
            "report_year": 2024,
            "report_period": "FY",
            "time_range": {"mode": "single_year"},
            "rank_direction": "desc",
            "limit": 10,
        }
    )["need_clarification"] is False
    assert callable(yoy_ranking_validator.validate)
    assert callable(yoy_ranking_sql.generate_yoy_ranking_sql_node)
    assert callable(yoy_ranking_analysis.analyze_yoy_ranking_node)

    assert slot_nodes.check_slots_node(
        {
            "intent_type": "trend_ranking_query",
            "companies": [],
            "company_mentions": [],
            "metrics": [BASE_METRIC],
            "start_year": 2022,
            "end_year": 2024,
            "report_period": "FY",
            "time_range": {"mode": "explicit_range", "start_year": 2022, "end_year": 2024},
            "rank_direction": "desc",
            "limit": 10,
            "change_metric": "growth_rate",
        }
    )["need_clarification"] is False
    assert callable(trend_ranking_validator.validate)
    assert callable(trend_ranking_sql.generate_trend_ranking_sql_node)
    assert callable(trend_ranking_analysis.analyze_trend_ranking_node)

    assert slot_nodes.check_slots_node(
        {
            "intent_type": "rank_position_query",
            "companies": [COMPANY],
            "metrics": [BASE_METRIC],
            "report_year": 2024,
            "report_period": "FY",
            "time_mode": "single_year",
            "rank_direction": "desc",
        }
    )["need_clarification"] is False
    assert callable(rank_position_validator.validate)
    assert callable(rank_position_sql.generate_rank_position_sql_node)
    assert callable(rank_position_analysis.analyze_rank_position_node)


def test_answer_dispatcher_registers_ranking_intents(monkeypatch):
    monkeypatch.setattr(
        answer_dispatcher,
        "generate_yoy_ranking_answer_node",
        lambda state: {"answer_route": "yoy_ranking"},
    )
    monkeypatch.setattr(
        answer_dispatcher,
        "generate_trend_ranking_answer_node",
        lambda state: {"answer_route": "trend_ranking"},
    )
    monkeypatch.setattr(
        answer_dispatcher,
        "generate_rank_position_answer_node",
        lambda state: {"answer_route": "rank_position"},
    )

    assert answer_dispatcher.generate_answer_node({"intent_type": "yoy_ranking_query"})["answer_route"] == "yoy_ranking"
    assert answer_dispatcher.generate_answer_node({"intent_type": "trend_ranking_query"})["answer_route"] == "trend_ranking"
    assert answer_dispatcher.generate_answer_node({"intent_type": "rank_position_query"})["answer_route"] == "rank_position"


def test_graph_and_runtime_register_ranking_nodes():
    graph_source = inspect.getsource(graph_module.build_graph)
    runtime_source = inspect.getsource(graph_runtime_module.SimpleCompiledGraph.invoke)

    for expected in RANKING_INTENTS.values():
        assert expected["sql_route"] in graph_source
        assert expected["analysis_route"] in graph_source
        assert expected["sql_route"] in runtime_source
        assert expected["analysis_route"] in runtime_source
