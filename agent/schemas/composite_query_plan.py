"""V0.8 Composite Query Plan Schema。"""

from typing import Any, Literal, TypedDict

from agent.schemas.task_plan import TaskPlan, normalize_task_plan
from agent.schemas.llm_sql_requirement import LlmSqlRequirement, normalize_llm_sql_requirement


CompositeQueryType = Literal["single", "composite"]
FinalAnswerMode = Literal["single", "synthesis", "stepwise", "summary"]


class CompositeResult(TypedDict, total=False):
    success: bool
    task_results: dict[str, dict[str, Any]]
    artifacts: dict[str, Any]
    final_answer: str | None
    error: str | None


class CompositeQueryPlan(TypedDict, total=False):
    query_type: CompositeQueryType
    tasks: list[TaskPlan]
    final_answer_mode: FinalAnswerMode
    clarification_required: bool
    clarification_question: str | None
    llm_sql_requirement: LlmSqlRequirement | None
    warnings: list[str]


VALID_COMPOSITE_QUERY_TYPES = {"single", "single_query", "composite", "composite_query"}
VALID_FINAL_ANSWER_MODES = {"single", "synthesis", "stepwise", "summary"}


def _as_optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _validate_task_dependencies(tasks: list[TaskPlan]) -> None:
    task_ids = [task["task_id"] for task in tasks]
    if len(task_ids) != len(set(task_ids)):
        raise ValueError("CompositeQueryPlan 中存在重复 task_id")

    task_id_set = set(task_ids)
    dependency_graph: dict[str, list[str]] = {}
    for task in tasks:
        dependency_graph[task["task_id"]] = []
        for dependency in task.get("depends_on", []):
            dependency_task_id = dependency.get("task_id")
            if dependency_task_id not in task_id_set:
                raise ValueError(f"任务 {task['task_id']} 依赖不存在的任务 {dependency_task_id}")
            if dependency_task_id == task["task_id"]:
                raise ValueError(f"任务 {task['task_id']} 不能依赖自身")
            dependency_graph[task["task_id"]].append(dependency_task_id)

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(task_id: str) -> None:
        if task_id in visited:
            return
        if task_id in visiting:
            raise ValueError("CompositeQueryPlan 中存在循环依赖")
        visiting.add(task_id)
        for dependency_task_id in dependency_graph.get(task_id, []):
            visit(dependency_task_id)
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in task_ids:
        visit(task_id)


def normalize_dependency_artifact_keys(tasks: list[TaskPlan]) -> tuple[list[TaskPlan], list[str]]:
    """修正依赖 artifact_key，使其与被依赖任务的单一产物保持一致。"""
    tasks_by_id = {task["task_id"]: task for task in tasks}
    warnings: list[str] = []
    normalized_tasks: list[TaskPlan] = []

    for task in tasks:
        normalized_task = dict(task)
        normalized_dependencies = []
        for dependency in task.get("depends_on", []):
            normalized_dependency = dict(dependency)
            dependency_task_id = normalized_dependency.get("task_id")
            producer = tasks_by_id.get(dependency_task_id)
            produced_artifact = producer.get("output_artifact") if isinstance(producer, dict) else None
            produced_key = produced_artifact.get("artifact_key") if isinstance(produced_artifact, dict) else None
            dependency_key = normalized_dependency.get("artifact_key")
            if produced_key and dependency_key != produced_key:
                normalized_dependency["artifact_key"] = produced_key
                warnings.append(
                    f"任务 {task['task_id']} 依赖 {dependency_task_id} 的 artifact_key "
                    f"已由 {dependency_key or '<empty>'} 修正为 {produced_key}"
                )
            normalized_dependencies.append(normalized_dependency)
        normalized_task["depends_on"] = normalized_dependencies
        normalized_tasks.append(normalized_task)

    return normalized_tasks, warnings


def validate_composite_query_plan(plan: dict[str, Any]) -> CompositeQueryPlan:
    normalized_plan = dict(plan)

    raw_tasks = normalized_plan.get("tasks")
    tasks = [
        normalize_task_plan(task, index + 1)
        for index, task in enumerate(raw_tasks if isinstance(raw_tasks, list) else [])
        if isinstance(task, dict)
    ]
    tasks, artifact_warnings = normalize_dependency_artifact_keys(tasks)
    _validate_task_dependencies(tasks)

    query_type = normalized_plan.get("query_type")
    if query_type not in VALID_COMPOSITE_QUERY_TYPES:
        query_type = "composite" if len(tasks) > 1 else "single"
    if query_type == "single_query":
        query_type = "single"
    if query_type == "composite_query":
        query_type = "composite"

    final_answer_mode = normalized_plan.get("final_answer_mode")
    if final_answer_mode not in VALID_FINAL_ANSWER_MODES:
        final_answer_mode = "synthesis" if query_type == "composite" else "single"

    clarification_required = normalized_plan.get("clarification_required")
    if not isinstance(clarification_required, bool):
        clarification_required = False

    return {
        "query_type": query_type,
        "tasks": tasks,
        "final_answer_mode": final_answer_mode,
        "clarification_required": clarification_required,
        "clarification_question": _as_optional_text(
            normalized_plan.get("clarification_question")
        ),
        "llm_sql_requirement": normalize_llm_sql_requirement(
            normalized_plan.get("llm_sql_requirement")
        ),
        "warnings": artifact_warnings,
    }
