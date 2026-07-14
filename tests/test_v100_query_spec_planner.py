"""统一 QuerySpec Planner 测试。"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from agent.nodes import llm_plan_query
from agent.schemas.query_spec import normalize_query_spec


class _FakeLLM:
    def __init__(self, payload: dict[str, Any]):
        self.payload = payload

    def invoke(self, _prompt: str) -> SimpleNamespace:
        return SimpleNamespace(content=json.dumps(self.payload, ensure_ascii=False))


def test_query_spec_flexible_sql_set_intersection_keeps_only_query_spec_route(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        llm_plan_query,
        "_build_llm",
        lambda: _FakeLLM(
            {
                "query_spec": {
                    "execution_mode": "flexible_sql",
                    "operation": "set_intersection_ranking",
                    "entities": [],
                    "metrics": ["营业收入", "净利润", "净利率"],
                    "time_scope": {"year": 2024, "period": "FY"},
                    "filters": [],
                    "sort": [{"metric": "净利率", "direction": "desc"}],
                    "limit": None,
                    "group_by": [],
                    "set_operations": [
                        {"type": "top_n", "metric": "营业收入", "n": 20, "output": "revenue_top20"},
                        {"type": "top_n", "metric": "净利润", "n": 20, "output": "profit_top20"},
                        {"type": "intersection", "inputs": ["revenue_top20", "profit_top20"]},
                    ],
                    "derived_expressions": [],
                    "answer_mode": "analytical",
                    "unsupported_reason": None,
                    "clarification_question": None,
                }
            }
        ),
    )

    result = llm_plan_query.llm_plan_query_node(
        {"user_question": "找出 2024 年营业收入和净利润都进入前 20 的公司，并按净利率排序"}
    )

    assert result["planner_stage"] == "query_spec"
    assert result["query_type"] == "single"
    assert result["query_plan"] is None
    assert result["composite_query_plan"] is None
    assert result["query_spec"]["execution_mode"] == "flexible_sql"
    assert "force_llm_sql" not in result
    assert "sql_generation_mode" not in result
    assert "llm_sql_requirement" not in result
    assert result["answer_mode"] == "llm_answer"


def test_query_spec_deterministic_query_still_returns_compatible_query_plan(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        llm_plan_query,
        "_build_llm",
        lambda: _FakeLLM(
            {
                "query_spec": {
                    "execution_mode": "deterministic",
                    "operation": "single_metric_query",
                    "entities": ["华润三九"],
                    "metrics": ["营业收入"],
                    "time_scope": {"year": 2024, "period": "FY"},
                    "filters": [],
                    "sort": [],
                    "limit": None,
                    "group_by": [],
                    "set_operations": [],
                    "derived_expressions": [],
                    "answer_mode": "fixed",
                    "unsupported_reason": None,
                    "clarification_question": None,
                }
            }
        ),
    )

    result = llm_plan_query.llm_plan_query_node({"user_question": "华润三九 2024 年营业收入是多少？"})

    assert result["planner_stage"] == "query_spec"
    assert result["intent_type"] == "single_metric_query"
    assert result["query_type"] == "single"
    assert result["query_plan"]["intent_type"] == "single_metric_query"
    assert result["company_mentions"] == ["华润三九"]
    assert result["metric_mentions"] == ["营业收入"]
    assert result["report_year"] == 2024
    assert result["need_clarification"] is False


def test_explicit_yoy_question_corrects_point_operation(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        llm_plan_query,
        "_build_llm",
        lambda: _FakeLLM(
            {"query_spec": {
                "execution_mode": "deterministic", "operation": "point_query",
                "entities": ["华润三九"], "metrics": ["营业收入"],
                "time_scope": {"year": 2024, "period": "FY"}, "filters": [],
                "sort": [], "limit": None, "group_by": [], "set_operations": [],
                "derived_expressions": [], "answer_mode": "fixed",
                "unsupported_reason": None, "clarification_question": None,
            }}
        ),
    )

    result = llm_plan_query.llm_plan_query_node({"user_question": "华润三九 2024 年营业收入同比是多少？"})

    assert result["query_spec"]["operation"] == "yoy_query"
    assert result["query_plan"]["intent_type"] == "yoy_query"


def test_year_between_filter_becomes_query_spec_time_range() -> None:
    spec = normalize_query_spec({
        "execution_mode": "flexible_sql", "operation": "trend_query", "entities": ["华润三九"],
        "metrics": ["营业收入"], "time_scope": {"year": None, "period": "FY"},
        "filters": [{"field": "year", "operator": "between", "value": [2022, 2024]}],
    })

    state = llm_plan_query._state_from_query_spec(spec)

    assert state["time_range"]["mode"] == "explicit_range"
    assert state["time_range"]["report_years"] == [2022, 2023, 2024]


def test_flexible_operation_is_canonicalized_from_query_spec_structure() -> None:
    cross_filter = normalize_query_spec({
        "execution_mode": "flexible_sql", "operation": "metric_threshold_filter",
        "filters": [{"metric": "净利润同比", "operator": ">", "value": 50}, {"metric": "营业收入同比", "operator": "<", "value": 10}],
    })
    subset_rank = normalize_query_spec({
        "execution_mode": "flexible_sql", "operation": "set_intersection_ranking",
        "set_operations": [{"type": "top_n", "metric": "营业收入", "n": 30}, {"type": "intersection", "inputs": ["top30"]}],
    })

    assert cross_filter["operation"] == "multi_metric_yoy_filter"
    assert subset_rank["operation"] == "topn_then_filter"


def test_nested_top_n_question_converts_global_intersection_to_nested_stage() -> None:
    result = llm_plan_query._correct_explicit_operation(
        "在 2024 年营业收入前 30 的公司中，找出净利率最高的 10 家。",
        {"query_spec": {
            "execution_mode": "flexible_sql", "operation": "set_intersection_ranking",
            "set_operations": [
                {"type": "top_n", "metric": "营业收入", "n": 30, "output": "revenue_top30"},
                {"type": "top_n", "metric": "净利率", "n": 10, "output": "profit_rate_top10"},
                {"type": "intersection", "inputs": ["revenue_top30", "profit_rate_top10"]},
            ],
            "metrics": ["营业收入", "净利率"], "time_scope": {"year": 2024, "period": "FY"},
        }},
    )

    assert result["query_spec"]["operation"] == "nested_top_n"
    assert result["query_spec"]["set_operations"][1]["input"] == "revenue_top30"
