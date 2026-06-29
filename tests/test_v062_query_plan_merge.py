"""V0.6.2 QueryPlan 合并规则测试。"""

import pytest

from agent.services.query_plan_merge_service import (
    clear_execution_state_after_merge,
    merge_query_plan,
    validate_slot_patch,
)


def _query_plan() -> dict:
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
        "clarification_reason": "请补充查询条件。",
    }


def test_merge_company_mentions_for_missing_company():
    merged = merge_query_plan(
        _query_plan(),
        {"company_mentions": ["贵州茅台"]},
        ["companies"],
    )

    assert merged["company_mentions"] == ["贵州茅台"]
    assert merged["metric_mentions"] == ["营业收入"]
    assert merged["need_clarification"] is False
    assert merged["clarification_reason"] is None


def test_merge_metric_mentions_for_missing_metric():
    plan = _query_plan()
    plan["metric_mentions"] = []

    merged = merge_query_plan(
        plan,
        {"metric_mentions": ["净利润"]},
        ["metrics"],
    )

    assert merged["metric_mentions"] == ["净利润"]


def test_merge_single_report_year_for_missing_year():
    plan = _query_plan()
    plan["time_range"] = {"mode": "unspecified", "report_year": None}

    merged = merge_query_plan(
        plan,
        {"time_mode": "single_year", "report_year": 2023},
        ["report_year"],
    )

    assert merged["time_range"]["mode"] == "single_year"
    assert merged["time_range"]["report_year"] == 2023


def test_merge_year_range_for_invalid_year_range():
    plan = _query_plan()
    plan["intent_type"] = "trend_query"
    plan["time_range"] = {"mode": "explicit_range", "start_year": 2024, "end_year": 2022}

    merged = merge_query_plan(
        plan,
        {"time_mode": "explicit_range", "start_year": 2022, "end_year": 2024},
        ["start_year", "end_year"],
    )

    assert merged["time_range"]["mode"] == "explicit_range"
    assert merged["time_range"]["start_year"] == 2022
    assert merged["time_range"]["end_year"] == 2024


def test_merge_ranking_limit_for_missing_ranking_limit():
    plan = _query_plan()
    plan["intent_type"] = "ranking_query"
    plan["limit"] = None

    merged = merge_query_plan(
        plan,
        {"ranking_limit": 10},
        ["ranking_limit"],
    )

    assert merged["limit"] == 10


def test_slot_patch_cannot_override_non_empty_fields():
    with pytest.raises(ValueError, match="非缺失字段"):
        validate_slot_patch(
            {"metric_mentions": ["净利润"]},
            ["companies"],
        )


def test_merge_rejects_non_missing_field_override():
    with pytest.raises(ValueError, match="非缺失字段"):
        merge_query_plan(
            _query_plan(),
            {"company_mentions": ["贵州茅台"], "metric_mentions": ["净利润"]},
            ["companies"],
        )


def test_unsupported_intent_has_no_allowed_merge_fields():
    with pytest.raises(ValueError, match="不支持 QueryPlan 合并"):
        merge_query_plan(
            _query_plan(),
            {"intent_type": "ranking_query"},
            ["intent_type"],
        )


def test_clear_execution_state_after_merge_removes_old_runtime_outputs():
    state = {
        "query_plan": _query_plan(),
        "merged_query_plan": {**_query_plan(), "company_mentions": ["贵州茅台"]},
        "companies": [{"stock_code": "600519"}],
        "metrics": [{"metric_key": "operating_revenue"}],
        "sql": "SELECT 1",
        "query_result": {"success": True, "rows": [[1]]},
        "analysis_result": {"row_count": 1},
        "final_answer": "旧回答",
        "business_success": True,
        "need_clarification": True,
    }

    cleaned = clear_execution_state_after_merge(state)

    assert cleaned["companies"] == []
    assert cleaned["metrics"] == []
    assert cleaned["sql"] is None
    assert cleaned["query_result"] is None
    assert cleaned["analysis_result"] is None
    assert cleaned["final_answer"] is None
    assert cleaned["business_success"] is None
    assert cleaned["need_clarification"] is False
    assert state["sql"] == "SELECT 1"
