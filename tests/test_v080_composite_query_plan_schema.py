"""V0.8 CompositeQueryPlan Schema 回归测试。"""

import pytest

from agent.schemas.composite_query_plan import validate_composite_query_plan


def test_composite_query_plan_expresses_ranking_yoy_and_secondary_ranking() -> None:
    plan = validate_composite_query_plan(
        {
            "query_type": "composite",
            "final_answer_mode": "synthesis",
            "clarification_required": False,
            "clarification_question": None,
            "tasks": [
                {
                    "task_id": "task_top10_profit_2024",
                    "intent": "ranking_query",
                    "metric_mentions": ["净利润"],
                    "company_mentions": [],
                    "company_source": "all_companies",
                    "time": {"mode": "single_year", "report_year": 2024},
                    "ranking": {
                        "rank_by": "净利润",
                        "rank_direction": "desc",
                        "limit": 10,
                    },
                    "depends_on": [],
                    "output_artifact": {
                        "artifact_key": "top10_companies",
                        "artifact_type": "company_set",
                        "description": "2024 年净利润最高的 top10 企业",
                    },
                },
                {
                    "task_id": "task_top10_profit_and_sales_yoy",
                    "intent": "yoy_query",
                    "metric_mentions": ["净利润", "营业收入"],
                    "company_mentions": [],
                    "company_source": "dependency",
                    "time": {"mode": "single_year", "report_year": 2024},
                    "ranking": None,
                    "depends_on": [
                        {
                            "task_id": "task_top10_profit_2024",
                            "artifact_key": "top10_companies",
                            "consume_as": "company_mentions",
                        }
                    ],
                    "output_artifact": {
                        "artifact_key": "top10_yoy_metrics",
                        "artifact_type": "metric_table",
                        "description": "top10 企业的净利润和营业收入同比",
                    },
                },
                {
                    "task_id": "task_largest_yoy_increase",
                    "intent": "yoy_ranking_query",
                    "metric_mentions": ["净利润", "营业收入"],
                    "company_mentions": [],
                    "company_source": "dependency",
                    "time": {"mode": "single_year", "report_year": 2024},
                    "ranking": {
                        "rank_by": "yoy_rate",
                        "rank_direction": "desc",
                        "limit": 1,
                        "secondary_rank_by": "同比上涨幅度",
                    },
                    "depends_on": [
                        {
                            "task_id": "task_top10_profit_and_sales_yoy",
                            "artifact_key": "top10_yoy_metrics",
                            "consume_as": "input_rows",
                        }
                    ],
                    "output_artifact": {
                        "artifact_key": "largest_yoy_increase_company",
                        "artifact_type": "ranking_table",
                        "description": "同比上涨幅度最大的企业",
                    },
                },
            ],
        }
    )

    assert plan["query_type"] == "composite"
    assert plan["final_answer_mode"] == "synthesis"
    assert len(plan["tasks"]) == 3

    top10_task, yoy_task, secondary_ranking_task = plan["tasks"]
    assert top10_task["intent"] == "ranking_query"
    assert top10_task["ranking"]["limit"] == 10
    assert top10_task["output_artifact"]["artifact_type"] == "company_set"

    assert yoy_task["intent"] == "yoy_query"
    assert yoy_task["metric_mentions"] == ["净利润", "营业收入"]
    assert yoy_task["company_source"] == "dependency"
    assert yoy_task["depends_on"][0]["artifact_key"] == "top10_companies"
    assert yoy_task["depends_on"][0]["consume_as"] == "company_mentions"

    assert secondary_ranking_task["intent"] == "yoy_ranking_query"
    assert secondary_ranking_task["ranking"]["rank_by"] == "yoy_rate"
    assert secondary_ranking_task["ranking"]["limit"] == 1
    assert secondary_ranking_task["depends_on"][0]["task_id"] == "task_top10_profit_and_sales_yoy"


def test_composite_query_plan_rejects_missing_dependency_target() -> None:
    with pytest.raises(ValueError, match="依赖不存在的任务"):
        validate_composite_query_plan(
            {
                "query_type": "composite",
                "tasks": [
                    {
                        "task_id": "task_yoy",
                        "intent": "yoy_query",
                        "depends_on": [{"task_id": "task_missing"}],
                    }
                ],
            }
        )


def test_composite_query_plan_normalizes_dependency_artifact_key() -> None:
    plan = validate_composite_query_plan(
        {
            "query_type": "composite",
            "tasks": [
                {
                    "task_id": "task_1",
                    "intent": "ranking_query",
                    "metric_mentions": ["营业收入"],
                    "company_mentions": [],
                    "company_source": "all_companies",
                    "time": {"mode": "single_year", "report_year": 2024},
                    "ranking": {"rank_by": "营业收入", "rank_direction": "desc", "limit": 30},
                    "depends_on": [],
                    "output_artifact": {
                        "artifact_key": "top30_revenue",
                        "artifact_type": "company_set",
                    },
                },
                {
                    "task_id": "task_2",
                    "intent": "ranking_query",
                    "metric_mentions": ["净利率"],
                    "company_mentions": [],
                    "company_source": "dependency",
                    "time": {"mode": "single_year", "report_year": 2024},
                    "ranking": {"rank_by": "净利率", "rank_direction": "desc", "limit": 10},
                    "depends_on": [
                        {
                            "task_id": "task_1",
                            "artifact_key": "company_list",
                            "consume_as": "company_mentions",
                        }
                    ],
                    "output_artifact": {
                        "artifact_key": "top10_margin",
                        "artifact_type": "ranking_table",
                    },
                },
            ],
        }
    )

    assert plan["tasks"][1]["depends_on"][0]["artifact_key"] == "top30_revenue"
    assert plan["warnings"]
    assert "company_list" in plan["warnings"][0]
    assert "top30_revenue" in plan["warnings"][0]


def test_composite_query_plan_rejects_circular_dependency() -> None:
    with pytest.raises(ValueError, match="循环依赖"):
        validate_composite_query_plan(
            {
                "query_type": "composite",
                "tasks": [
                    {
                        "task_id": "task_a",
                        "intent": "ranking_query",
                        "depends_on": [{"task_id": "task_b"}],
                    },
                    {
                        "task_id": "task_b",
                        "intent": "yoy_query",
                        "depends_on": [{"task_id": "task_a"}],
                    },
                ],
            }
        )
