"""V0.6.0 统一澄清 payload schema 测试。"""

from agent.schemas.clarification import (
    AMBIGUOUS_COMPANY,
    CLARIFICATION_ERROR_TYPES,
    CLARIFICATION_TYPES,
    EMPTY_FIELDS,
    ERROR_CLARIFICATION_REQUIRED,
    INVALID_COMPARE_COMPANY_COUNT,
    INVALID_RANKING_DIRECTION,
    INVALID_RANKING_LIMIT,
    INVALID_YEAR_RANGE,
    MISSING_COMPANY,
    MISSING_METRIC,
    MISSING_RANKING_LIMIT,
    MISSING_YEAR,
    UNSUPPORTED_INTENT,
    build_clarification_payload,
)
from agent.state import AgentState


def test_core_error_types_are_limited():
    assert CLARIFICATION_ERROR_TYPES == {
        "clarification_required",
        "unsupported_query",
        "invalid_query",
        "planner_failed",
        "standardization_failed",
    }


def test_minimum_clarification_types_exist():
    minimum_types = {
        MISSING_COMPANY,
        AMBIGUOUS_COMPANY,
        MISSING_METRIC,
        "ambiguous_metric",
        MISSING_YEAR,
        INVALID_YEAR_RANGE,
        MISSING_RANKING_LIMIT,
        UNSUPPORTED_INTENT,
    }
    assert minimum_types <= CLARIFICATION_TYPES


def test_enhanced_clarification_types_exist():
    assert {
        INVALID_COMPARE_COMPANY_COUNT,
        INVALID_RANKING_DIRECTION,
        INVALID_RANKING_LIMIT,
        "unsupported_metric_for_intent",
    } <= CLARIFICATION_TYPES


def test_empty_fields_use_system_field_names():
    assert {
        "companies",
        "metrics",
        "start_year",
        "end_year",
        "report_year",
        "ranking_limit",
        "ranking_direction",
        "compare_companies",
        "intent_type",
    } == EMPTY_FIELDS


def test_build_clarification_payload_keeps_required_fields():
    payload = build_clarification_payload(
        clarification_type=MISSING_COMPANY,
        clarification_question="请说明要查询哪家公司。",
        empty_fields=["companies"],
    )

    assert payload["need_clarification"] is True
    assert payload["clarification_type"] == MISSING_COMPANY
    assert payload["clarification_question"] == "请说明要查询哪家公司。"
    assert payload["error_type"] == ERROR_CLARIFICATION_REQUIRED
    assert payload["empty_fields"] == ["companies"]
    assert payload["clarification_candidates"] == []
    assert payload["detail"] == {}


def test_candidate_payload_supports_company_and_metric_fields():
    payload = build_clarification_payload(
        clarification_type=AMBIGUOUS_COMPANY,
        clarification_question="请确认公司。",
        empty_fields=["companies"],
        clarification_candidates=[
            {
                "candidate_type": "company",
                "raw_mention": "茅台",
                "normalized_name": "贵州茅台",
                "code": "600519",
                "display_name": "贵州茅台",
                "confidence": 0.92,
                "source": "company_alias",
            },
            {
                "candidate_type": "metric",
                "raw_mention": "利润",
                "metric_key": "net_profit",
                "display_name": "净利润",
                "confidence": 0.86,
                "source": "metric_dictionary",
            },
        ],
    )

    assert payload["clarification_candidates"][0]["candidate_type"] == "company"
    assert payload["clarification_candidates"][0]["code"] == "600519"
    assert payload["clarification_candidates"][1]["candidate_type"] == "metric"
    assert payload["clarification_candidates"][1]["metric_key"] == "net_profit"


def test_agent_state_accepts_v060_clarification_fields():
    state: AgentState = {
        "need_clarification": True,
        "clarification_type": MISSING_YEAR,
        "clarification_question": "请说明查询年份。",
        "clarification_candidates": [],
        "clarification_payload": build_clarification_payload(
            clarification_type=MISSING_YEAR,
            clarification_question="请说明查询年份。",
            empty_fields=["report_year"],
        ),
        "error_type": ERROR_CLARIFICATION_REQUIRED,
        "empty_fields": ["report_year"],
    }

    assert state["clarification_type"] == MISSING_YEAR
    assert state["clarification_payload"]["empty_fields"] == ["report_year"]
