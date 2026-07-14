"""V0.8.1 Planner 复合查询输出回归测试。"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from agent.nodes import llm_plan_query
from agent.nodes.composite_task_planner_node import reject_composite_if_single_database_relational_query
from agent.routing import should_end_after_plan


class _FakeLLM:
    def __init__(self, payload: dict[str, Any]):
        self.payload = payload

    def invoke(self, _prompt: str) -> SimpleNamespace:
        return SimpleNamespace(content=json.dumps(self.payload, ensure_ascii=False))


def _single_query_plan() -> dict[str, Any]:
    return {
        "intent_type": "ranking_query",
        "company_mentions": [],
        "metric_mentions": ["营业收入"],
        "report_period": "FY",
        "time_range": {
            "mode": "single_year",
            "report_year": 2024,
            "recent_n_years": None,
            "start_year": None,
            "end_year": None,
            "report_years": [],
        },
        "compare_spec": None,
        "rank_direction": "desc",
        "limit": 10,
        "change_metric": None,
        "need_clarification": False,
        "clarification_reason": None,
    }


def _composite_payload() -> dict[str, Any]:
    return {
        "query_type": "composite",
        "final_answer_mode": "synthesis",
        "clarification_required": False,
        "clarification_question": None,
        "tasks": [
            {
                "task_id": "task_top10_profit",
                "intent": "ranking_query",
                "metric_mentions": ["净利润"],
                "company_mentions": [],
                "company_source": "all_companies",
                "time": {"mode": "single_year", "report_year": 2024},
                "ranking": {
                    "rank_by": "净利润",
                    "rank_direction": "desc",
                    "limit": 10,
                },
                "depends_on": [],
                "output_artifact": {
                    "artifact_key": "top10_companies",
                    "artifact_type": "company_set",
                },
            },
            {
                "task_id": "task_top10_yoy",
                "intent": "yoy_query",
                "metric_mentions": ["净利润", "营业收入"],
                "company_mentions": [],
                "company_source": "dependency",
                "time": {"mode": "single_year", "report_year": 2024},
                "ranking": None,
                "depends_on": [
                    {
                        "task_id": "task_top10_profit",
                        "artifact_key": "top10_companies",
                        "consume_as": "company_mentions",
                    }
                ],
                "output_artifact": {
                    "artifact_key": "top10_yoy_metrics",
                    "artifact_type": "metric_table",
                },
            },
            {
                "task_id": "task_largest_yoy",
                "intent": "yoy_ranking_query",
                "metric_mentions": ["净利润", "营业收入"],
                "company_mentions": [],
                "company_source": "dependency",
                "time": {"mode": "single_year", "report_year": 2024},
                "ranking": {
                    "rank_by": "yoy_rate",
                    "rank_direction": "desc",
                    "limit": 1,
                    "secondary_rank_by": "同比上涨幅度",
                },
                "depends_on": [
                    {
                        "task_id": "task_top10_yoy",
                        "artifact_key": "top10_yoy_metrics",
                        "consume_as": "input_rows",
                    }
                ],
                "output_artifact": {
                    "artifact_key": "largest_yoy_company",
                    "artifact_type": "ranking_table",
                },
            },
        ],
    }


def test_planner_keeps_legacy_single_query_plan(monkeypatch) -> None:
    monkeypatch.setattr(llm_plan_query, "_build_llm", lambda: _FakeLLM(_single_query_plan()))

    result = llm_plan_query.llm_plan_query_node({"user_question": "2024 年营收前 10 是哪些？"})

    assert result["query_type"] == "single"
    assert result["query_plan"]["intent_type"] == "ranking_query"
    assert result["composite_query_plan"] is None
    assert result["need_clarification"] is False


def test_planner_accepts_wrapped_single_query_plan(monkeypatch) -> None:
    monkeypatch.setattr(
        llm_plan_query,
        "_build_llm",
        lambda: _FakeLLM({"query_type": "single", "query_plan": _single_query_plan()}),
    )

    result = llm_plan_query.llm_plan_query_node({"user_question": "2024 年营收前 10 是哪些？"})

    assert result["query_type"] == "single"
    assert result["query_plan"]["intent_type"] == "ranking_query"
    assert result["intent_type"] == "ranking_query"


def test_planner_outputs_composite_query_plan_and_does_not_force_single_intent(monkeypatch) -> None:
    monkeypatch.setattr(llm_plan_query, "_build_llm", lambda: _FakeLLM(_composite_payload()))

    result = llm_plan_query.llm_plan_query_node(
        {
            "user_question": (
                "2024年净利润最高的top10企业是哪些？这些企业的净利润、营业收入年同比是多少？"
                "年同比上涨幅度最大的是哪家企业？"
            )
        }
    )

    plan = result["composite_query_plan"]
    assert result["query_type"] == "composite"
    assert result["query_plan"] is None
    assert "intent_type" not in result
    assert [task["intent"] for task in plan["tasks"]] == [
        "ranking_query",
        "yoy_query",
        "yoy_ranking_query",
    ]
    assert plan["tasks"][1]["company_source"] == "dependency"
    assert plan["tasks"][1]["depends_on"][0]["consume_as"] == "company_mentions"
    assert plan["tasks"][2]["depends_on"][0]["artifact_key"] == "top10_yoy_metrics"
    assert result["task_execution_order"] == [
        "task_top10_profit",
        "task_top10_yoy",
        "task_largest_yoy",
    ]
    assert result["task_dag"]["clarification_required"] is False
    assert should_end_after_plan(result) == "execute_composite_query"


def test_planner_accepts_composite_query_alias(monkeypatch) -> None:
    payload = _composite_payload()
    payload["query_type"] = "composite_query"
    monkeypatch.setattr(llm_plan_query, "_build_llm", lambda: _FakeLLM(payload))

    result = llm_plan_query.llm_plan_query_node({"user_question": "复合查询"})

    assert result["composite_query_plan"]["query_type"] == "composite"


def test_single_database_relational_query_is_rejected_before_composite_planning() -> None:
    with pytest.raises(ValueError, match="禁止进入 CompositePlan"):
        reject_composite_if_single_database_relational_query(
            {"is_single_database_relational_query": True}
        )
