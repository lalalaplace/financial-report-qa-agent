"""V0.7 上下文路由真实 LLM 测试。"""

from __future__ import annotations

import os
from typing import Any

import pytest

from agent.nodes.context_llm_nodes import context_router_node
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


def _query_plan(
    *,
    companies: list[str] | None = None,
    metrics: list[str] | None = None,
    year: int = 2024,
) -> dict[str, Any]:
    return {
        "intent_type": "single_metric_query",
        "company_mentions": companies or [],
        "metric_mentions": metrics or ["营业收入"],
        "report_period": "FY",
        "time_range": {
            "mode": "single_year",
            "report_year": year,
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


def test_context_router_real_llm_routes_clarification_answer():
    result = context_router_node(
        {
            "user_question": "贵州茅台",
            "pending_query_plan": _query_plan(),
            "pending_clarification_type": "missing_company",
            "pending_empty_fields": ["companies"],
            "last_successful_query_plan": None,
        }
    )

    assert result["route_type"] == "clarification_answer"
    assert result["target_context"] == "pending_query_plan"
    assert "slot_patch" not in result


def test_context_router_real_llm_routes_contextual_followup():
    result = context_router_node(
        {
            "user_question": "那净利润呢",
            "pending_query_plan": None,
            "last_successful_query_plan": _query_plan(
                companies=["贵州茅台"],
                metrics=["营业收入"],
            ),
        }
    )

    assert result["route_type"] == "contextual_followup"
    assert result["target_context"] == "last_successful_query_plan"


def test_context_router_real_llm_keeps_complete_question_as_new_query():
    result = context_router_node(
        {
            "user_question": "贵州茅台 2023 年净利润同比增长率是多少？",
            "pending_query_plan": _query_plan(),
            "pending_clarification_type": "missing_company",
            "pending_empty_fields": ["companies"],
            "last_successful_query_plan": _query_plan(
                companies=["五粮液"],
                metrics=["营业收入"],
            ),
        }
    )

    assert result["route_type"] == "new_query"
    assert result["target_context"] == "none"
    assert result["pending_query_plan"] is None
    assert result["slot_patch"] is None
    assert result["merged_query_plan"] is None


def test_context_router_real_llm_routes_ambiguous_and_irrelevant():
    ambiguous = context_router_node(
        {
            "user_question": "那 2023 年呢",
            "pending_query_plan": None,
            "last_successful_query_plan": None,
        }
    )
    irrelevant = context_router_node(
        {
            "user_question": "今天上海天气怎么样？",
            "pending_query_plan": None,
            "last_successful_query_plan": None,
        }
    )

    assert ambiguous["route_type"] == "ambiguous"
    assert ambiguous["need_clarification"] is True
    assert irrelevant["route_type"] == "irrelevant"
    assert irrelevant["need_clarification"] is True


def test_context_router_pending_priority_over_last_successful():
    """2.4 pending 优先级验收：同时存在 pending 和 last_successful 时，
    补答输入应优先走 clarification_answer，不能误判为 contextual_followup。"""
    result = context_router_node(
        {
            "user_question": "贵州茅台",
            "pending_query_plan": _query_plan(companies=[], metrics=["营业收入"]),
            "pending_clarification_type": "missing_company",
            "pending_empty_fields": ["companies"],
            "last_successful_query_plan": _query_plan(
                companies=["五粮液"],
                metrics=["净利润"],
            ),
        }
    )

    assert result["route_type"] == "clarification_answer"
    assert result["target_context"] == "pending_query_plan"
