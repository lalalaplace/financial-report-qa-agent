"""多轮上下文澄清补答真实 LLM 流程测试。"""

from __future__ import annotations

import os
from typing import Any

import pytest

from agent.nodes import slot_nodes
from agent.nodes.context_llm_nodes import (
    clarification_patch_node,
    context_router_node,
    merge_clarification_patch_node,
)
from agent.nodes.execute_sql_node import review_and_execute_sql_node
from agent.nodes.sql_nodes.point_sql import generate_point_sql_node
from agent.services.llm_json_service import load_dotenv_if_available


def _real_llm_enabled() -> bool:
    load_dotenv_if_available()
    has_key = any(
        os.getenv(name)
        for name in ("AGENT_LLM_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY")
    )
    return os.getenv("RUN_REAL_LLM_TESTS") == "1" and has_key


pytestmark = pytest.mark.skipif(
    not _real_llm_enabled(),
    reason="需要设置 RUN_REAL_LLM_TESTS=1 并配置真实 LLM API Key。",
)


def _pending_missing_company_plan() -> dict[str, Any]:
    return {
        "intent_type": "single_metric_query",
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
        "rank_direction": None,
        "limit": None,
        "change_metric": None,
        "need_clarification": True,
        "clarification_reason": "请补充要查询的公司。",
    }


def _stub_company_and_executor(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_resolve_company(_query_text: str) -> dict[str, Any]:
        return {
            "matched": True,
            "need_clarification": False,
            "candidates": [
                {
                    "stock_code": "600519",
                    "stock_abbr": "贵州茅台",
                    "company_name": "贵州茅台酒股份有限公司",
                }
            ],
        }

    def fake_execute_sql(_sql: str) -> dict[str, Any]:
        return {
            "success": True,
            "columns": ["stock_code", "company_name", "report_year", "operating_revenue"],
            "rows": [["600519", "贵州茅台酒股份有限公司", 2024, 1]],
            "row_count": 1,
            "error": None,
        }

    monkeypatch.setattr(slot_nodes, "resolve_company", fake_resolve_company)
    monkeypatch.setattr(
        "agent.nodes.execute_sql_handlers._invoke_execute_financial_sql",
        fake_execute_sql,
    )


def test_clarification_answer_real_llm_merges_then_restandardizes_and_passes_sql_guard(
    monkeypatch: pytest.MonkeyPatch,
):
    _stub_company_and_executor(monkeypatch)
    state = {
        "user_question": "贵州茅台",
        "pending_query_plan": _pending_missing_company_plan(),
        "pending_clarification_type": "missing_company",
        "pending_empty_fields": ["companies"],
        "sql": "DROP TABLE company_dim",
        "final_answer": "旧回答",
        "companies": [{"stock_code": "000000"}],
        "metrics": [{"metric_key": "old_metric"}],
    }

    routed = context_router_node(state)
    assert routed["route_type"] == "clarification_answer"

    patched = clarification_patch_node({**state, **routed})
    assert patched["route_type"] == "clarification_answer"
    assert patched["slot_patch"]["company_mentions"]

    merged = merge_clarification_patch_node({**state, **routed, **patched})
    assert merged["need_clarification"] is False
    assert merged["pending_query_plan"] is None
    assert merged["sql"] is None
    assert merged["final_answer"] is None
    assert merged["companies"] == []
    assert merged["metrics"] == []
    assert merged["query_plan"]["company_mentions"]

    current = {**state, **merged}
    current.update(slot_nodes.resolve_company_node(current))
    current.update(slot_nodes.map_metric_node(current))
    current.update(slot_nodes.check_slots_node(current))
    assert current["need_clarification"] is False
    assert current["company_resolution_status"] == "resolved"
    assert current["metric_resolution_status"] == "resolved"

    current.update(generate_point_sql_node(current))
    assert current["sql"]
    current.update(review_and_execute_sql_node(current))

    assert current["sql_review"]["is_safe"] is True
    assert current["sql_success"] is True
    assert current["query_result"]["success"] is True


# ── 3.2 缺指标 → 补指标 ──


def _pending_missing_metric_plan() -> dict[str, Any]:
    return {
        "intent_type": "single_metric_query",
        "company_mentions": ["贵州茅台"],
        "metric_mentions": [],
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
        "need_clarification": True,
        "clarification_reason": "请说明要查询的财务指标。",
    }


def test_clarification_answer_missing_metric_full_flow(
    monkeypatch: pytest.MonkeyPatch,
):
    """3.2 缺指标补指标：Q1 缺指标 → Q2 补"营业收入"，重新 map_metric 后执行。"""
    _stub_company_and_executor(monkeypatch)
    state = {
        "user_question": "营业收入",
        "pending_query_plan": _pending_missing_metric_plan(),
        "pending_clarification_type": "missing_metric",
        "pending_empty_fields": ["metrics"],
        "sql": "DROP TABLE company_dim",
        "final_answer": "旧回答",
        "companies": [{"stock_code": "000000"}],
        "metrics": [{"metric_key": "old_metric"}],
    }

    routed = context_router_node(state)
    assert routed["route_type"] == "clarification_answer"

    patched = clarification_patch_node({**state, **routed})
    assert patched["route_type"] == "clarification_answer"
    assert patched["slot_patch"]["metric_mentions"]
    assert any("营业收入" in item for item in patched["slot_patch"]["metric_mentions"])

    merged = merge_clarification_patch_node({**state, **routed, **patched})
    assert merged["need_clarification"] is False
    assert merged["pending_query_plan"] is None
    assert merged["sql"] is None
    assert merged["final_answer"] is None
    assert merged["companies"] == []
    assert merged["metrics"] == []
    assert "贵州茅台" in merged["query_plan"]["company_mentions"]

    current = {**state, **merged}
    current.update(slot_nodes.resolve_company_node(current))
    current.update(slot_nodes.map_metric_node(current))
    current.update(slot_nodes.check_slots_node(current))
    assert current["need_clarification"] is False
    assert current["metric_resolution_status"] == "resolved"

    current.update(generate_point_sql_node(current))
    assert current["sql"]
    current.update(review_and_execute_sql_node(current))

    assert current["sql_review"]["is_safe"] is True
    assert current["sql_success"] is True
    assert current["query_result"]["success"] is True


# ── 3.3 缺年份 → 补年份 ──


def _pending_missing_year_plan() -> dict[str, Any]:
    return {
        "intent_type": "single_metric_query",
        "company_mentions": ["贵州茅台"],
        "metric_mentions": ["营业收入"],
        "report_period": "FY",
        "time_range": {
            "mode": "unspecified",
            "report_year": None,
            "recent_n_years": None,
            "start_year": None,
            "end_year": None,
            "report_years": [],
        },
        "compare_spec": None,
        "rank_direction": None,
        "limit": None,
        "change_metric": None,
        "need_clarification": True,
        "clarification_reason": "请说明要查询的年份。",
    }


def test_clarification_answer_missing_year_full_flow(
    monkeypatch: pytest.MonkeyPatch,
):
    """3.3 缺年份补年份：Q1 缺年份 → Q2 补"2024年"，合并后进入 SQL 链路。"""
    _stub_company_and_executor(monkeypatch)
    state = {
        "user_question": "2024年",
        "pending_query_plan": _pending_missing_year_plan(),
        "pending_clarification_type": "missing_year",
        "pending_empty_fields": ["report_year"],
        "sql": "DROP TABLE company_dim",
        "final_answer": "旧回答",
        "companies": [{"stock_code": "000000"}],
        "metrics": [{"metric_key": "old_metric"}],
    }

    routed = context_router_node(state)
    assert routed["route_type"] == "clarification_answer"

    patched = clarification_patch_node({**state, **routed})
    assert patched["route_type"] == "clarification_answer"
    patch = patched["slot_patch"]
    year_fields = {patch.get("start_year"), patch.get("end_year"), patch.get("report_year")}
    assert 2024 in year_fields

    merged = merge_clarification_patch_node({**state, **routed, **patched})
    assert merged["need_clarification"] is False
    assert merged["pending_query_plan"] is None
    assert merged["sql"] is None
    assert merged["final_answer"] is None
    assert merged["companies"] == []
    assert merged["metrics"] == []

    current = {**state, **merged}
    current.update(slot_nodes.resolve_company_node(current))
    current.update(slot_nodes.map_metric_node(current))
    current.update(slot_nodes.check_slots_node(current))
    assert current["need_clarification"] is False

    current.update(generate_point_sql_node(current))
    assert current["sql"]
    current.update(review_and_execute_sql_node(current))

    assert current["sql_review"]["is_safe"] is True
    assert current["sql_success"] is True
    assert current["query_result"]["success"] is True


# ── 3.4 ranking 缺 top_n / direction → 补答 ──


def _pending_ranking_missing_params_plan() -> dict[str, Any]:
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
        "rank_direction": None,
        "limit": None,
        "change_metric": None,
        "need_clarification": True,
        "clarification_reason": "请说明排名范围和方向。",
    }


def test_clarification_answer_ranking_params_full_flow(
    monkeypatch: pytest.MonkeyPatch,
):
    """3.4 ranking 缺 top_n/direction：Q1"2024年营业收入排名" → Q2"前10名，从高到低"，
    合并后 intent 仍为 ranking_query，通过 slot 校验。"""
    _stub_company_and_executor(monkeypatch)
    state = {
        "user_question": "前10名，从高到低",
        "pending_query_plan": _pending_ranking_missing_params_plan(),
        "pending_clarification_type": "missing_params",
        "pending_empty_fields": ["ranking_limit", "ranking_direction"],
        "sql": "DROP TABLE company_dim",
        "final_answer": "旧回答",
    }

    routed = context_router_node(state)
    assert routed["route_type"] == "clarification_answer"

    patched = clarification_patch_node({**state, **routed})
    assert patched["route_type"] == "clarification_answer"

    merged = merge_clarification_patch_node({**state, **routed, **patched})
    assert merged["need_clarification"] is False
    assert merged["pending_query_plan"] is None
    assert merged["sql"] is None
    assert merged["final_answer"] is None
    assert merged["query_plan"]["intent_type"] == "ranking_query"
    assert merged["query_plan"]["limit"] is not None
    assert merged["query_plan"]["rank_direction"] in ("desc", "asc")

    current = {**state, **merged}
    current.update(slot_nodes.resolve_company_node(current))
    assert current["company_resolution_status"] == "not_required"
    current.update(slot_nodes.map_metric_node(current))
    current.update(slot_nodes.check_slots_node(current))
    assert current["need_clarification"] is False


# ── 3.5 company_compare 缺公司 → 补公司 ──


def _pending_compare_missing_company_plan() -> dict[str, Any]:
    return {
        "intent_type": "company_compare_query",
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
        "compare_spec": {"operator": "higher", "target": None},
        "rank_direction": None,
        "limit": None,
        "change_metric": None,
        "need_clarification": True,
        "clarification_reason": "请补充要对比的公司。",
    }


def _stub_multi_company(monkeypatch: pytest.MonkeyPatch) -> None:
    company_db = {
        "贵州茅台": {
            "stock_code": "600519",
            "stock_abbr": "贵州茅台",
            "company_name": "贵州茅台酒股份有限公司",
        },
        "五粮液": {
            "stock_code": "000858",
            "stock_abbr": "五粮液",
            "company_name": "宜宾五粮液股份有限公司",
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

    monkeypatch.setattr(slot_nodes, "resolve_company", fake_resolve_company)


def test_clarification_answer_compare_company_full_flow(
    monkeypatch: pytest.MonkeyPatch,
):
    """3.5 company_compare 缺公司：Q1"比较2024年营业收入" → Q2"贵州茅台和五粮液"，
    合并后重新 resolve_company，intent 仍为 company_compare_query。"""
    _stub_multi_company(monkeypatch)
    state = {
        "user_question": "贵州茅台和五粮液",
        "pending_query_plan": _pending_compare_missing_company_plan(),
        "pending_clarification_type": "missing_company",
        "pending_empty_fields": ["companies"],
        "sql": "DROP TABLE company_dim",
        "final_answer": "旧回答",
    }

    routed = context_router_node(state)
    assert routed["route_type"] == "clarification_answer"

    patched = clarification_patch_node({**state, **routed})
    assert patched["route_type"] == "clarification_answer"
    assert patched["slot_patch"]["company_mentions"]
    assert any(
        name in patched["slot_patch"]["company_mentions"]
        for name in ("贵州茅台", "五粮液")
    )

    merged = merge_clarification_patch_node({**state, **routed, **patched})
    assert merged["need_clarification"] is False
    assert merged["pending_query_plan"] is None
    assert merged["sql"] is None
    assert merged["query_plan"]["intent_type"] == "company_compare_query"
    assert len(merged["query_plan"]["company_mentions"]) >= 2

    current = {**state, **merged}
    current.update(slot_nodes.resolve_company_node(current))
    assert len(current["companies"]) >= 2
    current.update(slot_nodes.map_metric_node(current))
    current.update(slot_nodes.check_slots_node(current))
    assert current["need_clarification"] is False
