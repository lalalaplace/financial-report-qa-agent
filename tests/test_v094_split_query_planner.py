"""V0.9.4 query_planner 职责拆分测试。"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from agent.nodes import llm_plan_query
from agent.nodes.composite_task_planner_node import repair_composite_plan_from_slots
from agent.nodes.clarification_decision_node import normalize_clarification_decision
from agent.nodes.intent_classifier_node import normalize_intent_classification
from agent.nodes.slot_extraction_node import normalize_slot_extraction


class _FakeLLM:
    def __init__(self, payload: dict[str, Any]):
        self.payload = payload

    def invoke(self, _prompt: str) -> SimpleNamespace:
        return SimpleNamespace(content=json.dumps(self.payload, ensure_ascii=False))


def test_intent_classification_normalizer_keeps_unknown_structured() -> None:
    result = normalize_intent_classification(
        {
            "planner_stage": "intent_classification",
            "query_type": "single",
            "intent_type": "unknown",
            "is_structured_database_question": True,
        }
    )

    assert result["intent_type"] == "unknown"
    assert result["is_structured_database_question"] is True
    assert result["needs_composite_task_plan"] is False


def test_slot_extraction_normalizer_builds_query_plan_slots() -> None:
    result = normalize_slot_extraction(
        {
            "company_mentions": ["华润三九"],
            "metric_mentions": ["营业收入"],
            "report_period": "FY",
            "time_range": {"mode": "single_year", "report_year": 2024},
            "rank_direction": None,
            "limit": None,
        },
        "single_metric_query",
    )

    assert result["company_mentions"] == ["华润三九"]
    assert result["metric_mentions"] == ["营业收入"]
    assert result["time_range"]["report_year"] == 2024


def test_split_planner_single_query_still_returns_compatible_query_plan(monkeypatch) -> None:
    monkeypatch.setattr(
        llm_plan_query,
        "_build_llm",
        lambda: _FakeLLM(
            {
                "planner_stage": "intent_classification",
                "query_type": "single",
                "intent_type": "single_metric_query",
                "is_structured_database_question": True,
                "needs_composite_task_plan": False,
            }
        ),
    )
    monkeypatch.setattr(
        "agent.nodes.slot_extraction_node.invoke_json_prompt",
        lambda _prompt: {
            "company_mentions": ["华润三九"],
            "metric_mentions": ["营业收入"],
            "report_period": "FY",
            "time_range": {"mode": "single_year", "report_year": 2024},
            "compare_spec": None,
            "rank_direction": None,
            "limit": None,
            "change_metric": None,
        },
    )

    result = llm_plan_query.llm_plan_query_node({"user_question": "华润三九 2024 年营业收入是多少？"})

    assert result["planner_stage"] == "split_planner"
    assert result["query_type"] == "single"
    assert result["query_plan"]["intent_type"] == "single_metric_query"
    assert result["company_mentions"] == ["华润三九"]
    assert result["metric_mentions"] == ["营业收入"]
    assert result["report_year"] == 2024
    assert result["need_clarification"] is False


def test_split_planner_composite_query_uses_composite_task_planner(monkeypatch) -> None:
    monkeypatch.setattr(
        llm_plan_query,
        "_build_llm",
        lambda: _FakeLLM(
            {
                "planner_stage": "intent_classification",
                "query_type": "composite",
                "intent_type": "ranking_query",
                "is_structured_database_question": True,
                "needs_composite_task_plan": True,
            }
        ),
    )
    monkeypatch.setattr(
        "agent.nodes.slot_extraction_node.invoke_json_prompt",
        lambda _prompt: {
            "company_mentions": [],
            "metric_mentions": ["营业收入", "净利率"],
            "report_period": "FY",
            "time_range": {"mode": "single_year", "report_year": 2024},
            "rank_direction": "desc",
            "limit": 30,
        },
    )
    monkeypatch.setattr(
        "agent.nodes.composite_task_planner_node.invoke_json_prompt",
        lambda _prompt: {
            "query_type": "composite",
            "final_answer_mode": "synthesis",
            "clarification_required": False,
            "clarification_question": None,
            "tasks": [
                {
                    "task_id": "task_1",
                    "intent": "ranking_query",
                    "metric_mentions": ["营业收入"],
                    "company_mentions": [],
                    "company_source": "all_companies",
                    "time": {"mode": "single_year", "report_year": 2024},
                    "ranking": {"rank_by": "营业收入", "rank_direction": "desc", "limit": 30},
                    "depends_on": [],
                    "output_artifact": {"artifact_key": "top30_revenue", "artifact_type": "company_set"},
                },
                {
                    "task_id": "task_2",
                    "intent": "ranking_query",
                    "metric_mentions": ["净利率"],
                    "company_mentions": [],
                    "company_source": "dependency",
                    "time": {"mode": "single_year", "report_year": 2024},
                    "ranking": {"rank_by": "净利率", "rank_direction": "desc", "limit": 10},
                    "depends_on": [{"task_id": "task_1", "artifact_key": "top30_revenue", "consume_as": "company_mentions"}],
                    "output_artifact": {"artifact_key": "top10_margin", "artifact_type": "ranking_table"},
                },
            ],
        },
    )

    result = llm_plan_query.llm_plan_query_node(
        {"user_question": "2024 年营业收入前 30 家公司中，净利率最高的前 10 家是谁？"}
    )

    assert result["planner_stage"] == "split_planner"
    assert result["query_type"] == "composite"
    assert result["query_plan"] is None
    assert [task["task_id"] for task in result["composite_query_plan"]["tasks"]] == ["task_1", "task_2"]
    assert result["task_execution_order"] == ["task_1", "task_2"]


def test_composite_plan_repair_fills_llm_missing_dependency_and_ranking_slots() -> None:
    payload = {
        "query_type": "composite",
        "tasks": [
            {
                "task_id": "task_1",
                "intent": "unknown",
                "metric_mentions": ["营业收入"],
                "company_mentions": [],
                "company_source": "unspecified",
                "time": {},
                "ranking": {"rank_by": None, "rank_direction": "desc", "limit": 30},
                "depends_on": [],
                "output_artifact": {"artifact_key": "top30_revenue", "artifact_type": "unspecified"},
            },
            {
                "task_id": "task_2",
                "intent": "unknown",
                "metric_mentions": ["净利率"],
                "company_mentions": [],
                "company_source": "dependency",
                "time": {},
                "ranking": {"rank_by": None, "rank_direction": "desc", "limit": 10},
                "depends_on": [],
                "output_artifact": {"artifact_key": "top10_margin", "artifact_type": "unspecified"},
            },
        ],
    }
    slot_extraction = {
        "time_range": {"mode": "single_year", "report_year": 2024},
    }

    repaired = repair_composite_plan_from_slots(payload, slot_extraction)
    tasks = repaired["tasks"]

    assert tasks[0]["intent"] == "ranking_query"
    assert tasks[0]["company_source"] == "all_companies"
    assert tasks[0]["time"]["report_year"] == 2024
    assert tasks[0]["ranking"]["rank_by"] == "营业收入"
    assert tasks[0]["output_artifact"]["artifact_type"] == "company_set"
    assert tasks[1]["intent"] == "ranking_query"
    assert tasks[1]["time"]["report_year"] == 2024
    assert tasks[1]["ranking"]["rank_by"] == "净利率"
    assert tasks[1]["output_artifact"]["artifact_type"] == "ranking_table"
    assert tasks[1]["depends_on"] == [
        {
            "task_id": "task_1",
            "artifact_key": "top30_revenue",
            "consume_as": "company_mentions",
        }
    ]


def test_clarification_decision_normalizer() -> None:
    result = normalize_clarification_decision(
        {
            "decision": "need_clarification",
            "clarification_question": "请说明指标。",
            "missing_fields": ["metric_mentions"],
        }
    )

    assert result["decision"] == "need_clarification"
    assert result["missing_fields"] == ["metric_mentions"]
