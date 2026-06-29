"""V0.6.0 澄清 schema、构造器与补问服务测试。"""

import pytest

from agent.schemas.clarification import (
    ERROR_CLARIFICATION_REQUIRED,
    ERROR_UNSUPPORTED_QUERY,
    validate_clarification_payload,
)
from agent.services.clarification_service import build_clarification_question
from agent.nodes import slot_nodes
from agent.validators.clarification import (
    make_ambiguous_company_payload,
    make_ambiguous_metric_payload,
    make_invalid_year_range_payload,
    make_missing_company_payload,
    make_missing_metric_payload,
    make_missing_ranking_limit_payload,
    make_missing_year_payload,
    make_unsupported_intent_payload,
)


def test_missing_company_payload_and_question():
    payload = make_missing_company_payload()

    assert payload["need_clarification"] is True
    assert payload["clarification_type"] == "missing_company"
    assert payload["error_type"] == ERROR_CLARIFICATION_REQUIRED
    assert payload["empty_fields"] == ["companies"]
    assert "哪家公司" in build_clarification_question(payload)


def test_ambiguous_company_payload_and_question():
    payload = make_ambiguous_company_payload(
        candidates=[
            {
                "candidate_type": "company",
                "raw_mention": "茅台",
                "normalized_name": "贵州茅台",
                "code": "600519",
                "display_name": "贵州茅台",
                "confidence": 0.92,
                "source": "company_alias",
            }
        ]
    )

    question = build_clarification_question(payload)
    assert payload["clarification_type"] == "ambiguous_company"
    assert payload["empty_fields"] == ["companies"]
    assert "贵州茅台" in question
    assert "600519" in question


def test_missing_metric_payload_and_question():
    payload = make_missing_metric_payload()

    assert payload["clarification_type"] == "missing_metric"
    assert payload["empty_fields"] == ["metrics"]
    assert "财务指标" in build_clarification_question(payload)


def test_ambiguous_metric_payload_and_question():
    payload = make_ambiguous_metric_payload(
        candidates=[
            {
                "candidate_type": "metric",
                "raw_mention": "利润",
                "metric_key": "net_profit",
                "display_name": "净利润",
                "confidence": 0.86,
                "source": "metric_dictionary",
            }
        ]
    )

    question = build_clarification_question(payload)
    assert payload["clarification_type"] == "ambiguous_metric"
    assert payload["empty_fields"] == ["metrics"]
    assert "净利润" in question


def test_missing_year_payload_and_question():
    payload = make_missing_year_payload()

    assert payload["clarification_type"] == "missing_year"
    assert payload["empty_fields"] == ["report_year"]
    assert "年份" in build_clarification_question(payload)


def test_invalid_year_range_payload_and_question():
    payload = make_invalid_year_range_payload(detail={"start_year": 2024, "end_year": 2022})

    assert payload["clarification_type"] == "invalid_year_range"
    assert payload["empty_fields"] == ["start_year", "end_year"]
    assert payload["detail"] == {"start_year": 2024, "end_year": 2022}
    assert "年份范围" in build_clarification_question(payload)


def test_missing_ranking_limit_payload_and_question():
    payload = make_missing_ranking_limit_payload()

    assert payload["clarification_type"] == "missing_ranking_limit"
    assert payload["empty_fields"] == ["ranking_limit"]
    assert "多少家公司" in build_clarification_question(payload)


def test_unsupported_intent_payload_and_question():
    payload = make_unsupported_intent_payload(detail={"reason": "多指标综合排名"})

    assert payload["clarification_type"] == "unsupported_intent"
    assert payload["error_type"] == ERROR_UNSUPPORTED_QUERY
    assert payload["empty_fields"] == ["intent_type"]
    assert "多指标综合排名" in build_clarification_question(payload)


def test_validate_rejects_unknown_empty_field():
    with pytest.raises(ValueError):
        validate_clarification_payload(
            {
                "need_clarification": True,
                "clarification_type": "missing_company",
                "clarification_question": "",
                "error_type": ERROR_CLARIFICATION_REQUIRED,
                "empty_fields": ["缺少公司"],
                "clarification_candidates": [],
                "detail": {},
            }
        )


def test_resolve_company_node_outputs_status_without_direct_clarification(monkeypatch):
    def fake_resolve_company(_mention):
        return {
            "need_clarification": True,
            "candidates": [
                {
                    "stock_code": "600519",
                    "stock_abbr": "贵州茅台",
                    "company_name": "贵州茅台股份有限公司",
                    "match_type": "alias",
                    "score": 0.92,
                }
            ],
        }

    monkeypatch.setattr(slot_nodes, "resolve_company", fake_resolve_company)

    result = slot_nodes.resolve_company_node(
        {
            "intent_type": "single_metric_query",
            "company_mentions": ["茅台"],
            "user_question": "茅台 2024 年营业收入",
        }
    )

    assert "need_clarification" not in result
    assert "clarification_question" not in result
    assert result["companies"] == []
    assert result["company_candidates"][0]["stock_code"] == "600519"
    assert result["company_resolution_status"] == "ambiguous"


def test_map_metric_node_outputs_status_without_direct_clarification(monkeypatch):
    def fake_map_metrics(_mention):
        return {
            "need_clarification": True,
            "metrics": [
                {
                    "metric_key": "net_profit",
                    "metric_name": "净利润",
                    "metric_type": "base",
                    "table": "income_sheet",
                    "field": "net_profit",
                    "unit": "yuan",
                }
            ],
        }

    monkeypatch.setattr(slot_nodes, "map_metrics", fake_map_metrics)

    result = slot_nodes.map_metric_node(
        {
            "metric_mentions": ["利润"],
            "user_question": "贵州茅台 2024 年利润",
        }
    )

    assert "need_clarification" not in result
    assert "clarification_question" not in result
    assert result["metrics"] == []
    assert result["metric_candidates"][0]["metric_key"] == "net_profit"
    assert result["metric_resolution_status"] == "ambiguous"
