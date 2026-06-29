"""多轮上下文多轮状态管理真实 LLM 测试。"""

from __future__ import annotations

import os
from typing import Any

import pytest

from agent.nodes.context_llm_nodes import (
    context_router_node,
    remember_successful_query_plan_node,
)
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
        "company_mentions": companies or ["贵州茅台"],
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


def test_new_query_real_llm_clears_pending_without_touching_last_successful_plan():
    """7.4 新问题覆盖 pending：用户输入完整新问题时清理旧 pending。"""
    last_plan = _query_plan(companies=["五粮液"], metrics=["营业收入"], year=2024)
    result = context_router_node(
        {
            "user_question": "贵州茅台 2023 年净利润是多少？",
            "pending_query_plan": _query_plan(companies=[], metrics=["营业收入"]),
            "pending_clarification_type": "missing_company",
            "pending_empty_fields": ["companies"],
            "last_successful_query_plan": last_plan,
            "slot_patch": {"company_mentions": ["旧公司"]},
            "merged_query_plan": _query_plan(companies=["旧公司"]),
        }
    )

    assert result["route_type"] == "new_query"
    assert result["target_context"] == "none"
    assert result["pending_query_plan"] is None
    assert result["pending_empty_fields"] == []
    assert result["slot_patch"] is None
    assert result["merged_query_plan"] is None
    assert "last_successful_query_plan" not in result


def test_remember_successful_query_plan_only_records_successful_business_result():
    """7.3 仅当 business_success=True 且有 query_plan 时才保存。"""
    query_plan = _query_plan(companies=["贵州茅台"], metrics=["净利润"], year=2023)

    success = remember_successful_query_plan_node(
        {
            "business_success": True,
            "query_plan": query_plan,
            "last_successful_query_plan": _query_plan(companies=["五粮液"]),
        }
    )
    failed = remember_successful_query_plan_node(
        {
            "business_success": False,
            "query_plan": query_plan,
            "last_successful_query_plan": _query_plan(companies=["五粮液"]),
        }
    )
    missing_plan = remember_successful_query_plan_node(
        {
            "business_success": True,
            "query_plan": None,
        }
    )

    assert success == {"last_successful_query_plan": query_plan}
    assert failed == {}
    assert missing_plan == {}


def test_last_successful_plan_points_to_latest_success():
    """7.5 连续成功查询时 last_successful_query_plan 指向最新一次。"""
    q2_plan = _query_plan(companies=["五粮液"], metrics=["净利润"], year=2023)

    # Q2 成功
    result = remember_successful_query_plan_node(
        {
            "business_success": True,
            "query_plan": q2_plan,
            "last_successful_query_plan": _query_plan(companies=["贵州茅台"]),
        }
    )
    assert result == {"last_successful_query_plan": q2_plan}

    # Q3 成功，应覆盖 Q2
    q3_plan = _query_plan(companies=["五粮液"], metrics=["营业收入"], year=2023)
    result2 = remember_successful_query_plan_node(
        {
            "business_success": True,
            "query_plan": q3_plan,
            "last_successful_query_plan": q2_plan,
        }
    )
    assert result2 == {"last_successful_query_plan": q3_plan}
