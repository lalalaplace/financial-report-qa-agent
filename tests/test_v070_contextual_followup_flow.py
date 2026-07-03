"""V0.7 上下文续问真实 LLM 流程测试。"""

from __future__ import annotations

import os
from typing import Any

import pytest

from agent.nodes import slot_nodes
from agent.nodes.context_llm_nodes import (
    context_router_node,
    followup_patch_node,
    merge_followup_patch_node,
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


def _successful_plan() -> dict[str, Any]:
    return {
        "intent_type": "single_metric_query",
        "company_mentions": ["贵州茅台"],
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
        "need_clarification": False,
        "clarification_reason": None,
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
            "columns": [
                "stock_code",
                "company_name",
                "report_year",
                "operating_revenue",
                "net_profit",
            ],
            "rows": [["600519", "贵州茅台酒股份有限公司", 2024, 1, 1]],
            "row_count": 1,
            "error": None,
        }

    monkeypatch.setattr(slot_nodes, "resolve_company", fake_resolve_company)
    monkeypatch.setattr(
        "agent.nodes.execute_sql_handlers._invoke_execute_financial_sql",
        fake_execute_sql,
    )


def test_contextual_followup_real_llm_merges_then_restandardizes_and_passes_sql_guard(
    monkeypatch: pytest.MonkeyPatch,
):
    _stub_company_and_executor(monkeypatch)
    state = {
        "user_question": "那净利润呢",
        "pending_query_plan": None,
        "last_successful_query_plan": _successful_plan(),
        "sql": "DROP TABLE company_dim",
        "query_result": {"success": True, "rows": [["旧结果"]]},
        "final_answer": "旧回答",
    }

    routed = context_router_node(state)
    assert routed["route_type"] == "contextual_followup"
    assert routed["target_context"] == "last_successful_query_plan"

    patched = followup_patch_node({**state, **routed})
    assert patched["route_type"] == "contextual_followup"
    assert patched["slot_patch"]["metric_mentions"]
    assert any("净利润" in item for item in patched["slot_patch"]["metric_mentions"])

    merged = merge_followup_patch_node({**state, **routed, **patched})
    assert merged["need_clarification"] is False
    assert merged["sql"] is None
    assert merged["query_result"] is None
    assert merged["final_answer"] is None
    assert "贵州茅台" in merged["company_mentions"]
    assert "营业收入" in merged["metric_mentions"]
    assert any("净利润" in item for item in merged["metric_mentions"])

    current = {**state, **merged}
    current.update(slot_nodes.resolve_company_node(current))
    current.update(slot_nodes.map_metric_node(current))
    current.update(slot_nodes.check_slots_node(current))
    assert current["need_clarification"] is False

    current.update(generate_point_sql_node(current))
    current.update(review_and_execute_sql_node(current))

    assert current["sql_review"]["is_safe"] is True
    assert current["sql_success"] is True
    assert current["query_result"]["success"] is True


# ── 4.1 续问替换年份 ──


def _successful_plan_q3_2024() -> dict[str, Any]:
    return {
        "intent_type": "single_metric_query",
        "company_mentions": ["三金"],
        "metric_mentions": ["主营业务收入"],
        "report_period": "Q3",
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


def test_contextual_followup_replace_year_full_flow(
    monkeypatch: pytest.MonkeyPatch,
):
    """4.1 续问替换年份：Q1 三金2024Q3 → Q2"2025年第三季度的呢？"，
    继承公司和指标，只替换年份，重新执行完整链路。"""
    _stub_company_and_executor(monkeypatch)
    state = {
        "user_question": "2025年第三季度的呢？",
        "pending_query_plan": None,
        "last_successful_query_plan": _successful_plan_q3_2024(),
        "sql": "DROP TABLE company_dim",
        "query_result": {"success": True, "rows": [["旧结果"]]},
        "final_answer": "旧回答",
    }

    routed = context_router_node(state)
    assert routed["route_type"] == "contextual_followup"
    assert routed["target_context"] == "last_successful_query_plan"

    patched = followup_patch_node({**state, **routed})
    assert patched["route_type"] == "contextual_followup"
    # 补丁应包含年份替换
    patch = patched["slot_patch"]
    year_fields = {patch.get("start_year"), patch.get("end_year"), patch.get("report_year")}
    assert 2025 in year_fields

    merged = merge_followup_patch_node({**state, **routed, **patched})
    assert merged["need_clarification"] is False
    assert merged["sql"] is None
    assert merged["query_result"] is None
    assert merged["final_answer"] is None
    # 继承公司的三金
    assert "三金" in merged["company_mentions"]
    # 继承指标
    assert "主营业务收入" in merged["metric_mentions"]

    current = {**state, **merged}
    current.update(slot_nodes.resolve_company_node(current))
    current.update(slot_nodes.map_metric_node(current))
    current.update(slot_nodes.check_slots_node(current))
    assert current["need_clarification"] is False

    current.update(generate_point_sql_node(current))
    current.update(review_and_execute_sql_node(current))

    assert current["sql_review"]["is_safe"] is True
    assert current["sql_success"] is True
    assert current["query_result"]["success"] is True


# ── 4.3 续问替换公司 ──


def test_contextual_followup_replace_company_full_flow(
    monkeypatch: pytest.MonkeyPatch,
):
    """4.3 续问替换公司：Q1 贵州茅台 → Q2"换成五粮液呢？"，
    继承指标和时间，只替换公司，重新 resolve_company。"""
    _stub_company_and_executor(monkeypatch)
    state = {
        "user_question": "换成五粮液呢？",
        "pending_query_plan": None,
        "last_successful_query_plan": _successful_plan(),
        "sql": "DROP TABLE company_dim",
        "query_result": {"success": True, "rows": [["旧结果"]]},
        "final_answer": "旧回答",
    }

    routed = context_router_node(state)
    assert routed["route_type"] == "contextual_followup"
    assert routed["target_context"] == "last_successful_query_plan"

    patched = followup_patch_node({**state, **routed})
    assert patched["route_type"] == "contextual_followup"
    assert patched["slot_patch"]["company_mentions"]
    assert any("五粮液" in item for item in patched["slot_patch"]["company_mentions"])

    merged = merge_followup_patch_node({**state, **routed, **patched})
    assert merged["need_clarification"] is False
    assert merged["sql"] is None
    assert merged["query_result"] is None
    assert merged["final_answer"] is None
    # 继承指标
    assert "营业收入" in merged["metric_mentions"]

    current = {**state, **merged}
    current.update(slot_nodes.resolve_company_node(current))
    current.update(slot_nodes.map_metric_node(current))
    current.update(slot_nodes.check_slots_node(current))
    assert current["need_clarification"] is False

    current.update(generate_point_sql_node(current))
    current.update(review_and_execute_sql_node(current))

    assert current["sql_review"]["is_safe"] is True
    assert current["sql_success"] is True
    assert current["query_result"]["success"] is True


# ── 4.4 续问替换排名参数 ──


def _successful_ranking_plan() -> dict[str, Any]:
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


def test_contextual_followup_replace_rank_limit_full_flow(
    monkeypatch: pytest.MonkeyPatch,
):
    """4.4 续问替换排名参数：Q1"2024年营业收入排名前10" → Q2"前20呢？"，
    继承 ranking_query 和指标/年份，只替换 top_n。"""
    _stub_company_and_executor(monkeypatch)
    state = {
        "user_question": "前20呢？",
        "pending_query_plan": None,
        "last_successful_query_plan": _successful_ranking_plan(),
        "sql": "DROP TABLE company_dim",
        "final_answer": "旧回答",
    }

    routed = context_router_node(state)
    assert routed["route_type"] == "contextual_followup"
    assert routed["target_context"] == "last_successful_query_plan"

    patched = followup_patch_node({**state, **routed})
    assert patched["route_type"] == "contextual_followup"

    merged = merge_followup_patch_node({**state, **routed, **patched})
    assert merged["need_clarification"] is False
    assert merged["sql"] is None
    assert merged["final_answer"] is None
    assert merged["query_plan"]["intent_type"] == "ranking_query"
    assert merged["query_plan"]["limit"] == 20
    assert merged["query_plan"]["rank_direction"] == "desc"

    current = {**state, **merged}
    current.update(slot_nodes.resolve_company_node(current))
    assert current["company_resolution_status"] == "not_required"
    current.update(slot_nodes.map_metric_node(current))
    current.update(slot_nodes.check_slots_node(current))
    assert current["need_clarification"] is False


# ── 4.5 续问后仍缺槽位时继续澄清 ──


def test_contextual_followup_intent_switch_to_ranking_needs_clarification(
    monkeypatch: pytest.MonkeyPatch,
):
    """4.5 专项：Q1 贵州茅台2024营业收入成功 → Q2"那排名呢？"
    续问触发意图切换 point→ranking，但缺参数，
    patch_status=need_clarification，不进入 SQL 执行，pending 被保存。"""
    _stub_company_and_executor(monkeypatch)
    state = {
        "user_question": "那排名呢？",
        "pending_query_plan": None,
        "last_successful_query_plan": _successful_plan(),
        "sql": "DROP TABLE company_dim",
        "final_answer": "旧回答",
    }

    routed = context_router_node(state)
    assert routed["route_type"] == "contextual_followup"
    assert routed["target_context"] == "last_successful_query_plan"

    patched = followup_patch_node({**state, **routed})
    # patch 阶段就应标记 need_clarification
    assert patched["patch_status"] == "need_clarification"
    assert patched["need_clarification"] is True
    assert patched.get("clarification_question")
    assert patched.get("missing_fields")

    # 通过路由直接验证：need_clarification 时不进入 merge 链路
    from agent.routing import route_after_patch_node
    route_target = route_after_patch_node({**state, **routed, **patched})
    assert route_target == "build_clarification_response"

    # 验证 patch 阶段已保存 pending
    assert patched.get("pending_query_plan") is not None
    assert patched.get("pending_empty_fields")


def test_contextual_followup_ambiguous_keeps_clarification(
    monkeypatch: pytest.MonkeyPatch,
):
    """4.5 续问后仍缺槽位：Q1 贵州茅台2024营业收入 → Q2"那排名呢？"，
    若系统无法确定排名参数，应 need_clarification=true，不能强行执行。"""
    _stub_company_and_executor(monkeypatch)
    state = {
        "user_question": "那排名呢？",
        "pending_query_plan": None,
        "last_successful_query_plan": _successful_plan(),
        "sql": "DROP TABLE company_dim",
        "final_answer": "旧回答",
    }

    routed = context_router_node(state)
    assert routed["route_type"] == "contextual_followup"

    patched = followup_patch_node({**state, **routed})
    merged = merge_followup_patch_node({**state, **routed, **patched})

    # 应标记 need_clarification
    assert merged["need_clarification"] is True
    # 不进入执行链路
    assert merged["sql"] is None
    assert merged["final_answer"] is None
    assert merged.get("clarification_question")
