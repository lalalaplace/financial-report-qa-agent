"""V0.6.2 多轮补问 pending 状态预留测试。"""

from agent.nodes.answer_nodes.clarify_answer import build_clarification_response_node
from agent.schemas.clarification import build_clarification_payload
from agent.validators.clarification import normalize_clarification_result


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
        "need_clarification": False,
        "clarification_reason": None,
    }


def test_clarification_response_saves_pending_state_from_payload():
    query_plan = _query_plan()
    payload = build_clarification_payload(
        clarification_type="ambiguous_company",
        empty_fields=["companies"],
        clarification_candidates=[
            {
                "candidate_type": "company",
                "raw_mention": "茅台",
                "normalized_name": "贵州茅台",
                "code": "600519",
                "display_name": "贵州茅台",
            }
        ],
    )

    result = build_clarification_response_node(
        {
            "query_plan": query_plan,
            "need_clarification": True,
            "clarification_payload": payload,
        }
    )

    assert result["pending_query_plan"] == query_plan
    assert result["pending_clarification_type"] == "ambiguous_company"
    assert result["pending_empty_fields"] == ["companies"]
    assert result["pending_candidates"] == payload["clarification_candidates"]
    assert result["slot_patch"] is None
    assert result["merged_query_plan"] is None


def test_normalized_clarification_saves_missing_ranking_limit_context():
    query_plan = {
        **_query_plan(),
        "intent_type": "ranking_query",
        "company_mentions": [],
        "rank_direction": "desc",
        "limit": None,
    }
    result = normalize_clarification_result(
        {
            "need_clarification": True,
            "error_type": "missing_limit",
        },
        {
            "query_plan": query_plan,
            "intent_type": "ranking_query",
            "metrics": [{"metric_key": "operating_revenue"}],
        },
    )

    assert result["pending_query_plan"] == query_plan
    assert result["pending_clarification_type"] == "missing_ranking_limit"
    assert result["pending_empty_fields"] == ["ranking_limit"]
    assert result["pending_candidates"] == []


def test_unsupported_intent_saves_pending_but_does_not_merge():
    query_plan = {**_query_plan(), "intent_type": "unknown"}
    payload = build_clarification_payload(
        clarification_type="unsupported_intent",
        error_type="unsupported_query",
        empty_fields=["intent_type"],
    )

    result = build_clarification_response_node(
        {
            "query_plan": query_plan,
            "need_clarification": True,
            "clarification_payload": payload,
            "slot_patch": {"intent_type": "ranking_query"},
        }
    )

    assert result["pending_query_plan"] == query_plan
    assert result["pending_clarification_type"] == "unsupported_intent"
    assert result["pending_empty_fields"] == ["intent_type"]
    assert result["merged_query_plan"] is None
