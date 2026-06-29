"""V0.6.2 澄清上下文保存与 QueryPlan 合并规则测试。"""

from agent.nodes.answer_nodes.clarify_answer import build_clarification_response_node
from agent.services.query_plan_merge_service import merge_query_plan
from agent.utils.logger import build_agent_run_log
from agent.validators.clarification import normalize_clarification_result


def _base_query_plan() -> dict:
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
        "need_clarification": False,
        "clarification_reason": None,
    }


def test_normalized_clarification_saves_pending_context():
    state = {
        "query_plan": _base_query_plan(),
        "intent_type": "single_metric_query",
        "company_candidates": [],
        "metric_candidates": [],
        "company_resolution_status": "unresolved",
    }

    result = normalize_clarification_result(
        {
            "need_clarification": True,
            "error_type": "company_not_found",
        },
        state,
    )

    assert result["pending_query_plan"] == state["query_plan"]
    assert result["pending_clarification_type"] == "missing_company"
    assert result["pending_empty_fields"] == ["companies"]
    assert result["pending_candidates"] == []
    assert result["slot_patch"] is None
    assert result["merged_query_plan"] is None


def test_merge_query_plan_with_slot_patch_appends_lists_and_updates_scalars():
    pending_query_plan = _base_query_plan()
    slot_patch = {
        "company_mentions": ["贵州茅台"],
        "metric_mentions": ["净利润"],
        "limit": 10,
    }

    merged = merge_query_plan(pending_query_plan, slot_patch, ["companies", "metrics", "ranking_limit"])

    assert merged["company_mentions"] == ["贵州茅台"]
    assert merged["metric_mentions"] == ["营业收入", "净利润"]
    assert merged["limit"] == 10
    assert merged["need_clarification"] is False
    assert merged["clarification_reason"] is None


def test_merge_query_plan_with_slot_patch_updates_time_range():
    pending_query_plan = _base_query_plan()
    pending_query_plan["time_range"] = {
        "mode": "unspecified",
        "report_year": None,
        "recent_n_years": None,
        "start_year": None,
        "end_year": None,
        "report_years": [],
    }

    merged = merge_query_plan(
        pending_query_plan,
        {
            "time_mode": "single_year",
            "report_year": 2024,
        },
        ["report_year"],
    )

    assert merged["time_range"]["mode"] == "single_year"
    assert merged["time_range"]["report_year"] == 2024


def test_clarification_answer_node_saves_planner_level_pending_context():
    query_plan = _base_query_plan()
    result = build_clarification_response_node(
        {
            "query_plan": query_plan,
            "need_clarification": True,
            "clarification_question": "请说明要查询哪家公司。",
        }
    )

    assert result["pending_query_plan"] == query_plan
    assert result["pending_clarification_type"] == "missing_company"
    assert result["pending_empty_fields"] == []
    assert result["pending_candidates"] == []


def test_agent_log_records_pending_clarification_context():
    query_plan = _base_query_plan()
    record = build_agent_run_log(
        {
            "user_question": "2024 年营业收入",
            "query_plan": query_plan,
            "intent_type": "single_metric_query",
            "companies": [],
            "metrics": [],
            "business_success": False,
            "error_type": "clarification_required",
            "pending_query_plan": query_plan,
            "pending_clarification_type": "missing_company",
            "pending_empty_fields": ["companies"],
            "pending_candidates": [],
            "slot_patch": {"company_mentions": ["贵州茅台"]},
            "merged_query_plan": {
                **query_plan,
                "company_mentions": ["贵州茅台"],
            },
        }
    )

    assert record["pending_query_plan"] == query_plan
    assert record["pending_clarification_type"] == "missing_company"
    assert record["pending_empty_fields"] == ["companies"]
    assert record["slot_patch"] == {"company_mentions": ["贵州茅台"]}
    assert record["merged_query_plan"]["company_mentions"] == ["贵州茅台"]
