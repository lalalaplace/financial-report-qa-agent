"""能力路由测试：SQL 生成前显式决策。"""

from __future__ import annotations

from typing import Any

from agent.nodes.capability_router import route_query_capability
from agent.nodes.sql_generation_router import route_sql_generation


def _state(query_spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "user_question": "测试问题",
        "query_spec": query_spec,
        "intent_type": query_spec.get("operation", "unknown"),
        "metric_mentions": ["营业收入"],
        "metrics": [{"metric_key": "total_operating_revenue", "metric_name": "营业收入", "metric_type": "base"}],
        "report_year": 2024,
        "report_period": "FY",
    }


def test_set_operations_route_to_flexible_sql_before_template() -> None:
    decision = route_query_capability(
        _state(
            {
                "execution_mode": "deterministic",
                "operation": "ranking_query",
                "set_operations": [{"type": "intersection"}],
                "filters": [],
                "sort": [],
            }
        )
    )

    assert decision["execution_mode"] == "flexible_sql"


def test_query_spec_declared_mode_does_not_override_capability_decision() -> None:
    decision = route_query_capability(
        _state(
            {
                "execution_mode": "flexible_sql",
                "operation": "single_metric_query",
                "filters": [],
                "sort": [],
                "set_operations": [],
            }
        )
    )

    assert decision["execution_mode"] == "deterministic"


def test_template_failure_does_not_fallback_to_llm_sql(monkeypatch: Any) -> None:
    called = {"llm": False}

    def fake_llm_sql(_state: dict[str, Any]) -> dict[str, Any]:
        called["llm"] = True
        return {"sql_generation_mode": "llm_sql"}

    monkeypatch.setattr("agent.nodes.sql_generation_router.generate_llm_sql_node", fake_llm_sql)

    result = route_sql_generation(
        _state(
            {
                "execution_mode": "deterministic",
                "operation": "single_metric_query",
                "filters": [],
                "sort": [],
                "set_operations": [],
            }
        ),
        template_nodes={"generate_point_sql": lambda _state: {"error_type": "template_bug"}},
    )

    assert result["sql_generation_mode"] == "unsupported"
    assert result["sql_generation_error_type"] == "template_bug"
    assert called["llm"] is False


def test_flexible_sql_does_not_try_template_first(monkeypatch: Any) -> None:
    called = {"template": False, "llm": False}

    def fake_template(_state: dict[str, Any]) -> dict[str, Any]:
        called["template"] = True
        return {"sql": "SELECT 1"}

    def fake_llm_sql(_state: dict[str, Any]) -> dict[str, Any]:
        called["llm"] = True
        return {"sql_generation_mode": "llm_sql", "sql": "SELECT 2"}

    monkeypatch.setattr("agent.nodes.sql_generation_router.generate_llm_sql_node", fake_llm_sql)

    state = _state(
        {
            "execution_mode": "flexible_sql",
            "operation": "set_intersection_ranking",
            "filters": [],
            "sort": [{"metric": "净利率", "direction": "desc"}],
            "set_operations": [{"type": "intersection"}],
        }
    )
    state["force_llm_sql"] = True
    state["llm_sql_requirement"] = {
        "can_use_llm_sql": True,
        "reason": "database_answerable_template_gap",
        "template_status": "missing",
        "read_only": True,
        "metric_mentions": ["营业收入", "净利率"],
        "company_mentions": [],
        "report_year": 2024,
        "report_period": "FY",
        "needs": {"prediction": False, "external_data": False, "text_understanding": False, "pdf_evidence": False},
    }

    result = route_sql_generation(state, template_nodes={"generate_point_sql": fake_template})

    assert result["sql_generation_mode"] == "llm_sql"
    assert called["llm"] is True
    assert called["template"] is False
