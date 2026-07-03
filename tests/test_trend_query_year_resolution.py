"""趋势查询年份解析回归测试。"""

from __future__ import annotations

import pytest

from agent.nodes.slot_nodes import check_slots_node
from agent.nodes.sql_nodes.trend_sql import generate_trend_sql_node
from agent.utils.year_utils import _query_latest_fy_year


def _base_state() -> dict:
    return {
        "intent_type": "trend_query",
        "companies": [
            {
                "stock_code": "000999",
                "stock_abbr": "华润三九",
                "company_name": "华润三九医药股份有限公司",
            }
        ],
        "metrics": [
            {
                "metric_key": "total_operating_revenue",
                "metric_name": "营业收入",
                "metric_type": "base",
                "table": "income_sheet",
                "field": "total_operating_revenue",
                "unit": "yuan",
            }
        ],
        "report_period": "FY",
    }


def test_explicit_range_trend_does_not_lookup_latest_year(monkeypatch: pytest.MonkeyPatch):
    """明确起止年份的趋势查询不应查询最新年报年份。"""
    def fail_lookup(_company: dict, _metric: dict) -> int | None:
        raise AssertionError("explicit_range 不应查询 latest year")

    monkeypatch.setattr(
        "agent.nodes.slot_validators.trend_validator._query_latest_fy_year",
        fail_lookup,
    )
    state = {
        **_base_state(),
        "time_mode": "explicit_range",
        "start_year": 2021,
        "end_year": 2024,
        "report_years": [2021, 2022, 2023, 2024],
    }

    result = check_slots_node(state)

    assert result["need_clarification"] is False
    assert result["report_year"] == 2024
    assert result["start_year"] == 2021
    assert result["end_year"] == 2024
    assert result["report_years"] == [2021, 2022, 2023, 2024]


def test_recent_n_trend_uses_latest_year_as_endpoint(monkeypatch: pytest.MonkeyPatch):
    """近年趋势查询用最新年报作为结束年份并生成 report_years。"""
    monkeypatch.setattr(
        "agent.nodes.slot_validators.trend_validator._query_latest_fy_year",
        lambda _company, _metric: 2024,
    )
    state = {
        **_base_state(),
        "time_mode": "recent_n",
        "recent_n_years": 4,
        "report_year": None,
        "report_years": [],
    }

    result = check_slots_node(state)

    assert result["need_clarification"] is False
    assert result["report_year"] == 2024
    assert result["start_year"] == 2021
    assert result["end_year"] == 2024
    assert result["report_years"] == [2021, 2022, 2023, 2024]


def test_recent_n_without_latest_year_requests_year_clarification(
    monkeypatch: pytest.MonkeyPatch,
):
    """查不到最新年报时应要求补年份，不应归类为 unsupported_query。"""
    monkeypatch.setattr(
        "agent.nodes.slot_validators.trend_validator._query_latest_fy_year",
        lambda _company, _metric: None,
    )
    state = {
        **_base_state(),
        "time_mode": "recent_n",
        "recent_n_years": 4,
        "report_year": None,
        "report_years": [],
    }

    result = check_slots_node(state)

    assert result["need_clarification"] is True
    assert result["error_type"] == "clarification_required"
    assert result["clarification_type"] == "missing_year"
    assert result["empty_fields"] == ["report_year"]
    assert result["error_type"] != "unsupported_query"


def test_trend_sql_prefers_resolved_report_years():
    """趋势 SQL 优先使用准入节点确认后的 report_years。"""
    state = {
        **_base_state(),
        "time_mode": "recent_n",
        "report_year": 2030,
        "recent_n_years": 2,
        "report_years": [2021, 2022, 2023, 2024],
    }

    result = generate_trend_sql_node(state)

    assert "BETWEEN 2021 AND 2024" in result["sql"]
    assert "BETWEEN 2029 AND 2030" not in result["sql"]


def test_latest_year_lookup_uses_order_by_limit(monkeypatch: pytest.MonkeyPatch):
    """最新年份探测不使用 MAX，避免被只读执行器函数白名单拦截。"""
    state = _base_state()
    captured_sql = {}

    def fake_execute(sql: str, limit: int = 100):
        captured_sql["sql"] = sql
        captured_sql["limit"] = limit
        return {"success": True, "rows": [(2024,)]}

    monkeypatch.setattr("agent.utils.year_utils.execute_readonly_sql", fake_execute)

    latest_year = _query_latest_fy_year(state["companies"][0], state["metrics"][0])

    assert latest_year == 2024
    assert "MAX(" not in captured_sql["sql"].upper()
    assert "ORDER BY report_year DESC" in captured_sql["sql"]
    assert "LIMIT 1" in captured_sql["sql"]
    assert captured_sql["limit"] == 1
