"""V0.4.4 公司对比语义增强测试。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.nodes.slot_nodes import check_slots_node
from agent.nodes.answer_nodes.answer_dispatcher import generate_answer_node
from agent.routing import route_by_intent
from agent.schemas.query_plan import validate_plan
from agent.utils.logger import build_agent_run_log


COMPANIES = [
    {"stock_code": "000001", "stock_abbr": "A公司", "company_name": "A公司"},
    {"stock_code": "000002", "stock_abbr": "B公司", "company_name": "B公司"},
]

BASE_METRIC = {
    "metric_key": "total_operating_revenue",
    "metric_name": "营业收入",
    "metric_type": "base",
    "table": "income_sheet",
    "field": "total_operating_revenue",
    "unit": "yuan",
}


def _point_state(operator: str, *, subject: str | None = None, reference: str | None = None):
    return {
        "intent_type": "company_compare_query",
        "report_year": 2024,
        "compare_spec": {
            "operator": operator,
            "target": "metric_value",
            "subject_company": subject,
            "reference_company": reference,
        },
        "compare_result": [{
            "metric_key": "total_operating_revenue",
            "metric_name": "营业收入",
            "metric_type": "base",
            "unit": "yuan",
            "year": 2024,
            "period": "FY",
            "items": [
                {"company_id": "000001", "company_name": "A公司", "value": 100.0, "status": "ok"},
                {"company_id": "000002", "company_name": "B公司", "value": 150.0, "status": "ok"},
            ],
            "winner_company": "B公司",
            "higher": "B公司",
            "lower": "A公司",
            "max_value": 150.0,
            "min_value": 100.0,
            "diff": 50.0,
            "diff_unit": "yuan",
            "status": "ok",
        }],
        "derived_compare_result": [],
    }


def _trend_state(operator: str):
    return {
        "intent_type": "company_compare_trend_query",
        "compare_spec": {"operator": operator, "target": "metric_change"},
        "compare_trend_result": [{
            "metric_key": "total_operating_revenue",
            "metric_name": "营业收入",
            "metric_type": "base",
            "unit": "yuan",
            "years": [2022, 2023, 2024],
            "items": [
                {
                    "company_id": "000001",
                    "company_name": "A公司",
                    "series": [],
                    "first_value": 100.0,
                    "last_value": 180.0,
                    "absolute_change": 80.0,
                    "change_rate": 0.8,
                    "change_unit": "yuan",
                    "status": "ok",
                },
                {
                    "company_id": "000002",
                    "company_name": "B公司",
                    "series": [],
                    "first_value": 200.0,
                    "last_value": 150.0,
                    "absolute_change": -50.0,
                    "change_rate": -0.25,
                    "change_unit": "yuan",
                    "status": "ok",
                },
            ],
            "latest_higher": "A公司",
            "latest_lower": "B公司",
            "largest_increase": "A公司",
            "largest_decline": "B公司",
            "larger_metric_change": "A公司",
            "status": "ok",
        }],
        "derived_compare_trend_result": [],
    }


def _yoy_state(operator: str):
    return {
        "intent_type": "company_compare_yoy_query",
        "compare_spec": {"operator": operator, "target": "yoy_rate"},
        "compare_yoy_result": [{
            "metric_key": "total_operating_revenue",
            "metric_name": "营业收入",
            "metric_type": "base",
            "unit": "yuan",
            "current_year": 2024,
            "previous_year": 2023,
            "items": [
                {
                    "company_id": "000001",
                    "company_name": "A公司",
                    "current_value": 130.0,
                    "previous_value": 100.0,
                    "absolute_change": 30.0,
                    "yoy_rate": 0.3,
                    "status": "ok",
                },
                {
                    "company_id": "000002",
                    "company_name": "B公司",
                    "current_value": 110.0,
                    "previous_value": 100.0,
                    "absolute_change": 10.0,
                    "yoy_rate": 0.1,
                    "status": "ok",
                },
            ],
            "winner_company": "A公司",
            "higher_yoy": "A公司",
            "lower_yoy": "B公司",
            "larger_metric_change": "A公司",
            "max_yoy_rate": 0.3,
            "min_yoy_rate": 0.1,
            "diff_yoy_rate": 0.2,
            "diff_unit": "百分点",
            "status": "ok",
        }],
        "derived_compare_yoy_result": [],
    }


def test_query_plan_accepts_compare_spec():
    plan = validate_plan({
        "intent_type": "company_compare_query",
        "company_mentions": ["A公司", "B公司"],
        "metric_mentions": ["营业收入"],
        "report_period": "FY",
        "time_range": {"mode": "single_year", "report_year": 2024},
        "compare_spec": {
            "operator": "higher_than",
            "target": "metric_value",
            "subject_company": "A公司",
            "reference_company": "B公司",
        },
    })

    assert plan["compare_spec"]["operator"] == "higher_than"
    assert plan["compare_spec"]["subject_company"] == "A公司"


def test_point_compare_higher_lower_difference_and_counterfactual():
    assert "B公司" in generate_answer_node(_point_state("higher"))["final_answer"]
    assert "A公司" in generate_answer_node(_point_state("lower"))["final_answer"]
    assert "相差" in generate_answer_node(_point_state("difference"))["final_answer"]

    answer = generate_answer_node(
        _point_state("higher_than", subject="A公司", reference="B公司")
    )["final_answer"]
    assert "并不高于" in answer
    assert "而是低" in answer

    answer = generate_answer_node(
        _point_state("lower_than", subject="B公司", reference="A公司")
    )["final_answer"]
    assert "并不低于" in answer
    assert "而是高" in answer


def test_trend_compare_larger_change_and_decline():
    answer = generate_answer_node(_trend_state("larger_change"))["final_answer"]
    assert "变化幅度更大的是A公司" in answer

    answer = generate_answer_node(_trend_state("larger_decline"))["final_answer"]
    assert "下降更多的是B公司" in answer


def test_yoy_compare_faster_growth_larger_change_and_percentage_point():
    answer = generate_answer_node(_yoy_state("faster_growth"))["final_answer"]
    assert "同比增速更高的是A公司" in answer

    answer = generate_answer_node(_yoy_state("difference"))["final_answer"]
    assert "百分点" in answer

    answer = generate_answer_node(_yoy_state("larger_change"))["final_answer"]
    assert "同比变化幅度更大的是A公司" in answer


def test_check_slots_defaults_compare_spec_and_validates_directed_reference():
    missing_metric = check_slots_node({
        "intent_type": "company_compare_query",
        "companies": COMPANIES,
        "metrics": [],
        "report_year": 2024,
    })
    assert missing_metric["error_type"] == "clarification_required"
    assert missing_metric["clarification_type"] == "missing_metric"

    missing_reference = check_slots_node({
        "intent_type": "company_compare_query",
        "companies": COMPANIES,
        "metrics": [BASE_METRIC],
        "report_year": 2024,
        "compare_spec": {"operator": "higher_than", "subject_company": "A公司"},
    })
    assert missing_reference["need_clarification"] is True
    assert missing_reference["error_type"] == "unsupported_query"
    assert missing_reference["clarification_type"] == "unsupported_intent"
    assert missing_reference["clarification_payload"]["need_clarification"] is True

    ready = check_slots_node({
        "intent_type": "company_compare_query",
        "companies": COMPANIES,
        "metrics": [BASE_METRIC],
        "report_year": 2024,
    })
    assert ready["compare_spec"]["operator"] == "general"


def test_ranking_not_routed_to_compare_and_logger_records_compare_spec():
    assert route_by_intent({"intent_type": "ranking_query"}) == "generate_ranking_sql"

    record = build_agent_run_log({
        "intent_type": "company_compare_query",
        "companies": COMPANIES,
        "metrics": [BASE_METRIC],
        "compare_spec": {"operator": "higher", "target": "metric_value"},
    })
    assert record["compare_spec"]["operator"] == "higher"


if __name__ == "__main__":
    tests = [
        test_query_plan_accepts_compare_spec,
        test_point_compare_higher_lower_difference_and_counterfactual,
        test_trend_compare_larger_change_and_decline,
        test_yoy_compare_faster_growth_larger_change_and_percentage_point,
        test_check_slots_defaults_compare_spec_and_validates_directed_reference,
        test_ranking_not_routed_to_compare_and_logger_records_compare_spec,
    ]
    for test in tests:
        test()
    print("V0.4.4 tests passed")
