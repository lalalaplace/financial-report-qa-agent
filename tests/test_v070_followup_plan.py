"""V0.7 contextual_followup 生成下一轮 QueryPlan draft 的回归测试。"""

from __future__ import annotations

from typing import Any

import pytest

from agent.nodes import slot_nodes
from agent.nodes import context_llm_nodes
from agent.nodes.context_llm_nodes import (
    context_router_node,
    followup_plan_node,
    remember_successful_query_plan_node,
)
from agent.nodes.execute_sql_node import review_and_execute_sql_node
from agent.nodes.sql_nodes.point_sql import generate_point_sql_node
from agent.nodes.sql_nodes.yoy_sql import generate_yoy_sql_node
from agent.routing import route_after_context_router, route_by_intent


def _point_plan(
    *,
    companies: list[str] | None = None,
    metrics: list[str] | None = None,
    intent_type: str = "single_metric_query",
) -> dict[str, Any]:
    return {
        "intent_type": intent_type,
        "company_mentions": companies or ["华润三九"],
        "metric_mentions": metrics or ["营业收入"],
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
        "rank_direction": None,
        "limit": None,
        "change_metric": None,
        "need_clarification": False,
        "clarification_reason": None,
    }


def _yoy_plan() -> dict[str, Any]:
    plan = _point_plan()
    plan["intent_type"] = "yoy_query"
    plan["time_range"] = {
        "mode": "single_year",
        "report_year": 2024,
        "recent_n_years": None,
        "start_year": 2024,
        "end_year": 2024,
        "report_years": [2024],
    }
    return plan


def test_contextual_followup_uses_shared_planner_with_inherited_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    state = {
        "user_question": "同比呢",
        "last_successful_query_plan": _point_plan(),
    }
    payloads = iter(
        [
            {"route_type": "contextual_followup", "target_context": "last_successful_query_plan"},
            _followup_payload(_yoy_plan(), "基于上一轮计划切换为同比查询。"),
        ]
    )
    monkeypatch.setattr(
        context_llm_nodes,
        "invoke_json_prompt",
        lambda _prompt: next(payloads),
    )

    routed = context_router_node(state)
    result = followup_plan_node({**state, **routed})

    assert routed["route_type"] == "contextual_followup"
    assert result["intent_type"] == "yoy_query"
    assert result["company_mentions"] == ["华润三九"]
    assert result["metric_mentions"] == ["营业收入"]
    assert result["report_year"] == 2024
    assert result["query_spec"]["operation"] == "yoy_query"
    assert result["query_spec"]["execution_mode"] == "deterministic"


def _followup_payload(query_plan: dict[str, Any], reason: str = "测试生成下一轮 QueryPlan。") -> dict[str, Any]:
    return {
        "followup_action": "plan_and_run",
        "query_plan": query_plan,
        "intent_candidates": [],
        "clarification_question": None,
        "reason": reason,
    }


def _stub_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    company_db = {
        "华润三九": {
            "stock_code": "000999",
            "stock_abbr": "华润三九",
            "company_name": "华润三九医药股份有限公司",
        },
        "云南白药": {
            "stock_code": "000538",
            "stock_abbr": "云南白药",
            "company_name": "云南白药集团股份有限公司",
        },
    }

    def fake_resolve_company(query_text: str) -> dict[str, Any]:
        for name, candidate in company_db.items():
            if name in query_text:
                return {
                    "matched": True,
                    "need_clarification": False,
                    "candidates": [candidate],
                }
        return {"matched": False, "need_clarification": True, "candidates": []}

    def fake_execute_sql(_sql: str) -> dict[str, Any]:
        return {
            "success": True,
            "columns": ["stock_code", "company_name", "report_year", "value"],
            "rows": [["000999", "华润三九医药股份有限公司", 2024, 1]],
            "row_count": 1,
            "error": None,
        }

    monkeypatch.setattr(slot_nodes, "resolve_company", fake_resolve_company)
    monkeypatch.setattr(
        "agent.nodes.execute_sql_handlers._invoke_execute_financial_sql",
        fake_execute_sql,
    )


def _run_standard_chain(state: dict[str, Any]) -> dict[str, Any]:
    current = dict(state)
    current.update(slot_nodes.resolve_company_node(current))
    current.update(slot_nodes.map_metric_node(current))
    current.update(slot_nodes.check_slots_node(current))
    assert current["need_clarification"] is False

    route = route_by_intent(current)
    if route == "generate_yoy_sql":
        current.update(generate_yoy_sql_node(current))
    else:
        assert route == "generate_point_sql"
        current.update(generate_point_sql_node(current))
    assert current.get("sql")

    current.update(review_and_execute_sql_node(current))
    return current


def _run_followup_plan(monkeypatch: pytest.MonkeyPatch, user_question: str, payload: dict[str, Any]) -> dict[str, Any]:
    monkeypatch.setattr(context_llm_nodes, "invoke_json_prompt", lambda _prompt: payload)
    return followup_plan_node(
        {
            "user_question": user_question,
            "last_successful_query_plan": _point_plan(),
            "companies": [{"stock_code": "old"}],
            "metrics": [{"metric_key": "old"}],
            "sql": "DROP TABLE company_dim",
            "sql_review": {"is_safe": False},
            "query_result": {"success": True},
            "analysis_result": {"old": True},
            "business_success": True,
            "error_type": "old_error",
            "empty_fields": ["metrics"],
            "need_clarification": True,
            "clarification_question": "旧澄清",
        }
    )


def test_followup_plan_replaces_metric_and_enters_standard_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_dependencies(monkeypatch)
    result = _run_followup_plan(
        monkeypatch,
        "那净利润呢？",
        _followup_payload(_point_plan(metrics=["净利润"])),
    )

    plan = result["query_plan"]
    assert result["followup_action"] == "plan_and_run"
    assert plan["intent_type"] == "single_metric_query"
    assert plan["company_mentions"] == ["华润三九"]
    assert plan["metric_mentions"] == ["净利润"]
    assert result["need_clarification"] is False
    assert result["companies"] == []
    assert result["metrics"] == []
    assert result["sql"] is None
    assert result["error_type"] is None

    current = _run_standard_chain(result)
    assert current["sql_review"]["is_safe"] is True
    assert current["sql_success"] is True


def test_followup_plan_replaces_company_and_enters_standard_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_dependencies(monkeypatch)
    result = _run_followup_plan(
        monkeypatch,
        "换成云南白药呢？",
        _followup_payload(_point_plan(companies=["云南白药"])),
    )

    plan = result["query_plan"]
    assert plan["intent_type"] == "single_metric_query"
    assert plan["company_mentions"] == ["云南白药"]
    assert plan["metric_mentions"] == ["营业收入"]
    assert result["need_clarification"] is False

    current = _run_standard_chain(result)
    assert current["sql_review"]["is_safe"] is True
    assert current["sql_success"] is True


def test_followup_plan_transitions_to_yoy_and_enters_sql_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_dependencies(monkeypatch)
    result = _run_followup_plan(
        monkeypatch,
        "那同比呢？",
        _followup_payload(_yoy_plan()),
    )

    plan = result["query_plan"]
    assert plan["intent_type"] == "yoy_query"
    assert plan["company_mentions"] == ["华润三九"]
    assert plan["metric_mentions"] == ["营业收入"]
    assert plan["time_range"]["report_year"] == 2024
    assert plan["time_range"]["start_year"] == 2024
    assert plan["time_range"]["end_year"] == 2024
    assert result["need_clarification"] is False

    current = _run_standard_chain(result)
    assert route_by_intent(current) == "generate_yoy_sql"
    assert current["sql_review"]["is_safe"] is True
    assert current["sql_success"] is True


def test_followup_plan_ranking_followup_requires_clarification(monkeypatch: pytest.MonkeyPatch) -> None:
    result = _run_followup_plan(
        monkeypatch,
        "那排名呢？",
        {
            "followup_action": "need_clarification",
            "query_plan": None,
            "intent_candidates": ["rank_position_query", "ranking_query"],
            "clarification_question": "你想查询华润三九排名第几，还是查询公司排名列表？",
            "reason": "排名续问存在两种解释。",
        },
    )

    assert result["followup_action"] == "need_clarification"
    assert result["need_clarification"] is True
    assert result["error_type"] == "clarification_required"
    assert result["followup_result"]["intent_candidates"] == ["rank_position_query", "ranking_query"]
    assert result.get("sql") is None


def test_context_router_full_new_question_still_routes_new_query(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        context_llm_nodes,
        "invoke_json_prompt",
        lambda _prompt: {"route_type": "new_query", "target_context": "none"},
    )

    result = context_router_node(
        {
            "user_question": "云南白药 2024 年净利润是多少？",
            "pending_query_plan": None,
            "last_successful_query_plan": _point_plan(),
        }
    )

    assert result["route_type"] == "new_query"
    assert route_after_context_router(result) == "llm_plan_query"


@pytest.mark.parametrize(
    ("business_success", "need_clarification", "error_type"),
    [
        (False, False, "unsupported_query"),
        (True, True, "clarification_required"),
        (True, False, "invalid_query"),
    ],
)
def test_failed_or_clarification_round_does_not_overwrite_last_successful_plan(
    business_success: bool,
    need_clarification: bool,
    error_type: str,
) -> None:
    result = remember_successful_query_plan_node(
        {
            "business_success": business_success,
            "need_clarification": need_clarification,
            "error_type": error_type,
            "query_plan": _point_plan(companies=["云南白药"]),
            "last_successful_query_plan": _point_plan(),
        }
    )

    assert result == {}
