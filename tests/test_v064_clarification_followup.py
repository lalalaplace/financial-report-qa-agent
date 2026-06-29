from __future__ import annotations

from typing import Any

from agent.nodes.context_nodes import (
    clarification_patch_node,
    context_router_node,
    followup_patch_node,
)
from agent.services.clarification_followup import (
    detect_and_extract_contextual_patch,
    detect_and_extract_slot_patch,
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


def test_detect_followup_company_answer_builds_only_mentions_patch():
    result = detect_and_extract_slot_patch(
        user_input="贵州茅台",
        pending_query_plan=_query_plan(),
        clarification_context={"empty_fields": ["companies"]},
    )

    assert result.is_clarification_answer is True
    assert result.slot_patch == {"company_mentions": ["贵州茅台"]}
    assert "companies" not in result.slot_patch


def test_detect_followup_rejects_complete_new_question():
    result = detect_and_extract_slot_patch(
        user_input="贵州茅台2023年净利润同比增长率是多少？",
        pending_query_plan=_query_plan(),
        clarification_context={"empty_fields": ["companies"]},
    )

    assert result.is_clarification_answer is False
    assert result.slot_patch == {}


def test_context_router_routes_clarification_answer_then_patch_merges_plan():
    routed = context_router_node(
        {
            "user_question": "贵州茅台",
            "pending_query_plan": _query_plan(),
            "pending_clarification_type": "missing_company",
            "pending_empty_fields": ["companies"],
        }
    )

    assert routed["route_type"] == "clarification_answer"
    assert routed["slot_patch"] == {"company_mentions": ["贵州茅台"]}

    result = clarification_patch_node(
        {
            "pending_query_plan": _query_plan(),
            "pending_empty_fields": ["companies"],
            **routed,
            "sql": "SELECT 1",
            "final_answer": "旧回答",
        }
    )

    assert result["query_plan"]["company_mentions"] == ["贵州茅台"]
    assert result["company_mentions"] == ["贵州茅台"]
    assert result["metric_mentions"] == ["营业收入"]
    assert result["slot_patch"] == {"company_mentions": ["贵州茅台"]}
    assert result["merged_query_plan"]["company_mentions"] == ["贵州茅台"]
    assert result["pending_query_plan"] is None
    assert result["sql"] is None
    assert result["final_answer"] is None


def test_context_router_clears_pending_when_input_is_new_question():
    result = context_router_node(
        {
            "user_question": "贵州茅台2023年净利润同比增长率是多少？",
            "pending_query_plan": _query_plan(),
            "pending_clarification_type": "missing_company",
            "pending_empty_fields": ["companies"],
        }
    )

    assert result["route_type"] == "new_query"
    assert result["pending_query_plan"] is None
    assert result["slot_patch"] is None
    assert result["merged_query_plan"] is None


def test_contextual_followup_patch_updates_last_successful_query_plan():
    result = detect_and_extract_contextual_patch(
        user_input="那净利润呢",
        last_successful_query_plan=_query_plan(companies=["贵州茅台"], metrics=["营业收入"]),
    )

    assert result.is_clarification_answer is True
    assert result.slot_patch == {"metric_mentions": ["净利润"]}

    merged = followup_patch_node(
        {
            "last_successful_query_plan": _query_plan(companies=["贵州茅台"], metrics=["营业收入"]),
            "slot_patch": result.slot_patch,
        }
    )

    assert merged["route_type"] == "contextual_followup"
    assert merged["company_mentions"] == ["贵州茅台"]
    assert merged["metric_mentions"] == ["营业收入", "净利润"]
    assert merged["merged_query_plan"]["metric_mentions"] == ["营业收入", "净利润"]
