"""V0.8.2 Task DAG 构建与校验。"""

from __future__ import annotations

from typing import Any, TypedDict

from agent.schemas.task_plan import TaskArtifact, TaskPlan, normalize_task_plan


RANKING_INTENTS = {
    "ranking_query",
    "yoy_ranking_query",
    "trend_ranking_query",
    "secondary_ranking_query",
}
COMPANY_REQUIRED_INTENTS = {
    "single_metric_query",
    "multi_metric_query",
    "trend_query",
    "yoy_query",
    "derived_metric_query",
    "company_compare_query",
    "company_compare_trend_query",
    "company_compare_yoy_query",
    "rank_position_query",
}
COMPANY_DEPENDENCY_CONSUMES = {"company_mentions", "filter_scope", "ranking_scope"}


class TaskGraphValidationError(ValueError):
    """Task DAG 结构不可执行时抛出。"""


class TaskDag(TypedDict, total=False):
    tasks_by_id: dict[str, TaskPlan]
    execution_order: list[TaskPlan]
    task_ids: list[str]
    artifacts_by_key: dict[str, TaskArtifact]
    clarification_required: bool
    clarification_reasons: list[str]
    clarification_question: str | None


def _normalize_tasks(tasks: list[TaskPlan] | list[dict[str, Any]]) -> list[TaskPlan]:
    return [
        normalize_task_plan(task, index + 1)
        for index, task in enumerate(tasks)
        if isinstance(task, dict)
    ]


def _raw_tasks_by_id(tasks: list[TaskPlan] | list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    raw_tasks: dict[str, dict[str, Any]] = {}
    for index, task in enumerate(tasks):
        if not isinstance(task, dict):
            continue
        normalized_task = normalize_task_plan(task, index + 1)
        raw_tasks[normalized_task["task_id"]] = dict(task)
    return raw_tasks


def _task_label(task: TaskPlan) -> str:
    return task.get("task_id") or "<unknown>"


def _has_report_year(task: TaskPlan) -> bool:
    time_range = task.get("time") or {}
    if time_range.get("report_year") is not None:
        return True
    report_years = time_range.get("report_years")
    return isinstance(report_years, list) and bool(report_years)


def _has_explicit_range(task: TaskPlan) -> bool:
    time_range = task.get("time") or {}
    return time_range.get("start_year") is not None and time_range.get("end_year") is not None


def _depends_on_company_artifact(task: TaskPlan) -> bool:
    return any(
        dependency.get("consume_as") in COMPANY_DEPENDENCY_CONSUMES
        for dependency in task.get("depends_on", [])
    )


def validate_task_dependencies(tasks: list[TaskPlan] | list[dict[str, Any]]) -> None:
    normalized_tasks = _normalize_tasks(tasks)
    task_ids = [task["task_id"] for task in normalized_tasks]
    if len(task_ids) != len(set(task_ids)):
        raise TaskGraphValidationError("Task DAG 中存在重复 task_id")

    tasks_by_id = {task["task_id"]: task for task in normalized_tasks}
    artifacts_by_task_id = {
        task["task_id"]: task.get("output_artifact") or {}
        for task in normalized_tasks
    }

    for task in normalized_tasks:
        for dependency in task.get("depends_on", []):
            dependency_task_id = dependency.get("task_id")
            if dependency_task_id not in tasks_by_id:
                raise TaskGraphValidationError(
                    f"任务 {task['task_id']} 依赖不存在的任务 {dependency_task_id}"
                )
            if dependency_task_id == task["task_id"]:
                raise TaskGraphValidationError(f"任务 {task['task_id']} 不能依赖自身")

            dependency_artifact_key = dependency.get("artifact_key")
            if not dependency_artifact_key:
                raise TaskGraphValidationError(
                    f"任务 {task['task_id']} 的依赖 {dependency_task_id} 缺少 artifact_key"
                )
            produced_artifact = artifacts_by_task_id[dependency_task_id]
            if produced_artifact.get("artifact_key") != dependency_artifact_key:
                raise TaskGraphValidationError(
                    f"任务 {task['task_id']} 需要的 artifact {dependency_artifact_key} "
                    f"不是任务 {dependency_task_id} 的产物"
                )

    topological_sort(normalized_tasks)


def topological_sort(tasks: list[TaskPlan] | list[dict[str, Any]]) -> list[TaskPlan]:
    normalized_tasks = _normalize_tasks(tasks)
    tasks_by_id = {task["task_id"]: task for task in normalized_tasks}
    if len(tasks_by_id) != len(normalized_tasks):
        raise TaskGraphValidationError("Task DAG 中存在重复 task_id")

    graph = {task_id: [] for task_id in tasks_by_id}
    indegree = {task_id: 0 for task_id in tasks_by_id}
    for task in normalized_tasks:
        task_id = task["task_id"]
        for dependency in task.get("depends_on", []):
            dependency_task_id = dependency.get("task_id")
            if dependency_task_id not in tasks_by_id:
                raise TaskGraphValidationError(
                    f"任务 {task_id} 依赖不存在的任务 {dependency_task_id}"
                )
            graph[dependency_task_id].append(task_id)
            indegree[task_id] += 1

    ready = [task_id for task_id in tasks_by_id if indegree[task_id] == 0]
    execution_order: list[TaskPlan] = []
    while ready:
        task_id = ready.pop(0)
        execution_order.append(tasks_by_id[task_id])
        for next_task_id in graph[task_id]:
            indegree[next_task_id] -= 1
            if indegree[next_task_id] == 0:
                ready.append(next_task_id)

    if len(execution_order) != len(normalized_tasks):
        raise TaskGraphValidationError("Task DAG 中存在循环依赖")
    return execution_order


def _collect_slot_clarification_reasons(
    tasks: list[TaskPlan],
    raw_tasks: dict[str, dict[str, Any]],
) -> list[str]:
    reasons: list[str] = []
    for task in tasks:
        task_id = _task_label(task)
        intent = task.get("intent")
        metrics = task.get("metric_mentions") or []
        companies = task.get("company_mentions") or []
        ranking = task.get("ranking") or {}
        raw_ranking = raw_tasks.get(task_id, {}).get("ranking")
        raw_ranking = raw_ranking if isinstance(raw_ranking, dict) else {}

        if intent != "unknown" and not metrics:
            reasons.append(f"任务 {task_id} 缺少指标")

        if (
            intent in COMPANY_REQUIRED_INTENTS
            and not companies
            and not _depends_on_company_artifact(task)
        ):
            reasons.append(f"任务 {task_id} 缺少公司")

        if intent == "trend_ranking_query":
            if not _has_explicit_range(task):
                reasons.append(f"任务 {task_id} 缺少明确起止年份")
        elif intent != "unknown" and not _has_report_year(task):
            reasons.append(f"任务 {task_id} 缺少年份")

        if intent in RANKING_INTENTS:
            if not metrics:
                reasons.append(f"任务 {task_id} 排名缺少指标")
            if not _has_report_year(task) and intent != "trend_ranking_query":
                reasons.append(f"任务 {task_id} 排名缺少年份")
            if raw_ranking.get("limit") is None or ranking.get("limit") is None:
                reasons.append(f"任务 {task_id} 排名缺少 top_n")
            if raw_ranking.get("rank_direction") not in {"desc", "asc"}:
                reasons.append(f"任务 {task_id} 排名缺少排序方向")

    return list(dict.fromkeys(reasons))


def _build_clarification_question(reasons: list[str]) -> str | None:
    if not reasons:
        return None
    return "复合查询任务缺少必要条件：" + "；".join(reasons) + "。"


def build_task_dag(tasks: list[TaskPlan] | list[dict[str, Any]]) -> TaskDag:
    raw_tasks = _raw_tasks_by_id(tasks)
    normalized_tasks = _normalize_tasks(tasks)
    validate_task_dependencies(normalized_tasks)
    execution_order = topological_sort(normalized_tasks)
    clarification_reasons = _collect_slot_clarification_reasons(execution_order, raw_tasks)
    artifacts_by_key = {
        artifact["artifact_key"]: artifact
        for task in execution_order
        for artifact in [task.get("output_artifact") or {}]
        if artifact.get("artifact_key")
    }

    return {
        "tasks_by_id": {task["task_id"]: task for task in execution_order},
        "execution_order": execution_order,
        "task_ids": [task["task_id"] for task in execution_order],
        "artifacts_by_key": artifacts_by_key,
        "clarification_required": bool(clarification_reasons),
        "clarification_reasons": clarification_reasons,
        "clarification_question": _build_clarification_question(clarification_reasons),
    }
