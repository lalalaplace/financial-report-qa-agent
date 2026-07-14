"""V0.8.2 Task DAG 构建与校验测试。"""

from __future__ import annotations

import pytest

from agent.runtime.task_graph import (
    TaskGraphValidationError,
    build_task_dag,
    topological_sort,
    validate_task_dependencies,
)


def _valid_tasks() -> list[dict]:
    return [
        {
            "task_id": "t1",
            "intent": "ranking_query",
            "metric_mentions": ["净利润"],
            "company_mentions": [],
            "company_source": "all_companies",
            "time": {"mode": "single_year", "report_year": 2024},
            "ranking": {"rank_by": "净利润", "rank_direction": "desc", "limit": 10},
            "depends_on": [],
            "output_artifact": {
                "artifact_key": "top10_companies",
                "artifact_type": "company_set",
            },
        },
        {
            "task_id": "t2",
            "intent": "yoy_query",
            "metric_mentions": ["净利润", "营业收入"],
            "company_mentions": [],
            "company_source": "dependency",
            "time": {"mode": "single_year", "report_year": 2024},
            "ranking": None,
            "depends_on": [
                {
                    "task_id": "t1",
                    "artifact_key": "top10_companies",
                    "consume_as": "company_mentions",
                }
            ],
            "output_artifact": {
                "artifact_key": "top10_yoy_metrics",
                "artifact_type": "metric_table",
            },
        },
        {
            "task_id": "t3",
            "intent": "yoy_ranking_query",
            "metric_mentions": ["净利润", "营业收入"],
            "company_mentions": [],
            "company_source": "dependency",
            "time": {"mode": "single_year", "report_year": 2024},
            "ranking": {
                "rank_by": "yoy_rate",
                "rank_direction": "desc",
                "limit": 1,
            },
            "depends_on": [
                {
                    "task_id": "t2",
                    "artifact_key": "top10_yoy_metrics",
                    "consume_as": "input_rows",
                }
            ],
            "output_artifact": {
                "artifact_key": "largest_yoy_company",
                "artifact_type": "ranking_table",
            },
        },
    ]


def test_topological_sort_returns_executable_order() -> None:
    ordered_tasks = topological_sort(list(reversed(_valid_tasks())))

    assert [task["task_id"] for task in ordered_tasks] == ["t1", "t2", "t3"]


def test_build_task_dag_indexes_artifacts_and_order() -> None:
    dag = build_task_dag(_valid_tasks())

    assert dag["task_ids"] == ["t1", "t2", "t3"]
    assert dag["clarification_required"] is False
    assert set(dag["artifacts_by_key"]) == {
        "top10_companies",
        "top10_yoy_metrics",
        "largest_yoy_company",
    }


def test_validate_task_dependencies_rejects_duplicate_task_id() -> None:
    tasks = _valid_tasks()
    tasks[1]["task_id"] = "t1"

    with pytest.raises(TaskGraphValidationError, match="重复 task_id"):
        validate_task_dependencies(tasks)


def test_validate_task_dependencies_rejects_missing_dependency() -> None:
    tasks = _valid_tasks()
    tasks[1]["depends_on"][0]["task_id"] = "missing"

    with pytest.raises(TaskGraphValidationError, match="依赖不存在的任务"):
        validate_task_dependencies(tasks)


def test_validate_task_dependencies_rejects_cycle() -> None:
    tasks = _valid_tasks()
    tasks[0]["depends_on"] = [
        {
            "task_id": "t3",
            "artifact_key": "largest_yoy_company",
            "consume_as": "input_rows",
        }
    ]

    with pytest.raises(TaskGraphValidationError, match="循环依赖"):
        validate_task_dependencies(tasks)


def test_validate_task_dependencies_rejects_missing_artifact_output() -> None:
    tasks = _valid_tasks()
    tasks[1]["depends_on"][0]["artifact_key"] = "missing_artifact"

    with pytest.raises(TaskGraphValidationError, match="不是任务 t1 的产物"):
        validate_task_dependencies(tasks)


def test_build_task_dag_marks_missing_slots_as_clarification() -> None:
    tasks = _valid_tasks()
    tasks[0]["metric_mentions"] = []
    tasks[0]["time"] = {"mode": "unspecified", "report_year": None}
    tasks[0]["ranking"] = {"rank_by": "净利润"}

    dag = build_task_dag(tasks)

    assert dag["clarification_required"] is True
    assert "任务 t1 缺少指标" in dag["clarification_reasons"]
    assert "任务 t1 排名缺少年份" in dag["clarification_reasons"]
    assert "任务 t1 排名缺少 top_n" in dag["clarification_reasons"]
    assert "任务 t1 排名缺少排序方向" in dag["clarification_reasons"]
    assert dag["clarification_question"]
