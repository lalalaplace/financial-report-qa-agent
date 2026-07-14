"""V0.8 Composite Query 的子任务 Schema。"""

from typing import Any, Literal, TypedDict

from agent.schemas.query_plan import TimeRange


TaskIntent = Literal[
    "single_metric_query",
    "multi_metric_query",
    "trend_query",
    "yoy_query",
    "derived_metric_query",
    "company_compare_query",
    "company_compare_trend_query",
    "company_compare_yoy_query",
    "ranking_query",
    "yoy_ranking_query",
    "trend_ranking_query",
    "rank_position_query",
    "secondary_ranking_query",
    "unknown",
]
CompanySource = Literal["explicit", "dependency", "all_companies", "unspecified"]
ArtifactType = Literal[
    "company_set",
    "metric_table",
    "ranking_table",
    "scalar",
    "answer_fragment",
    "unspecified",
]
DependencyConsumeAs = Literal[
    "company_mentions",
    "metric_mentions",
    "filter_scope",
    "ranking_scope",
    "comparison_baseline",
    "input_rows",
]


class RankingSpec(TypedDict, total=False):
    rank_by: str | None
    rank_direction: Literal["desc", "asc"] | None
    limit: int | None
    secondary_rank_by: str | None


class TaskDependency(TypedDict, total=False):
    task_id: str
    artifact_key: str | None
    consume_as: DependencyConsumeAs


class TaskArtifact(TypedDict, total=False):
    artifact_key: str
    artifact_type: ArtifactType
    description: str | None


class TaskPlan(TypedDict, total=False):
    task_id: str
    intent: TaskIntent
    metric_mentions: list[str]
    company_mentions: list[str]
    company_source: CompanySource
    time: TimeRange
    ranking: RankingSpec | None
    depends_on: list[TaskDependency]
    output_artifact: TaskArtifact


VALID_TASK_INTENTS = {
    "single_metric_query",
    "multi_metric_query",
    "trend_query",
    "yoy_query",
    "derived_metric_query",
    "company_compare_query",
    "company_compare_trend_query",
    "company_compare_yoy_query",
    "ranking_query",
    "yoy_ranking_query",
    "trend_ranking_query",
    "rank_position_query",
    "secondary_ranking_query",
    "unknown",
}
VALID_COMPANY_SOURCES = {"explicit", "dependency", "all_companies", "unspecified"}
VALID_ARTIFACT_TYPES = {
    "company_set",
    "metric_table",
    "ranking_table",
    "scalar",
    "answer_fragment",
    "unspecified",
}
VALID_DEPENDENCY_CONSUME_AS = {
    "company_mentions",
    "metric_mentions",
    "filter_scope",
    "ranking_scope",
    "comparison_baseline",
    "input_rows",
}
VALID_RANK_DIRECTIONS = {"desc", "asc"}


def _normalize_text_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _as_optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _as_int_or_none(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def normalize_ranking_spec(value: object) -> RankingSpec | None:
    if not isinstance(value, dict):
        return None
    rank_direction = value.get("rank_direction")
    if rank_direction not in VALID_RANK_DIRECTIONS:
        rank_direction = "desc"
    return {
        "rank_by": _as_optional_text(value.get("rank_by")),
        "rank_direction": rank_direction,
        "limit": _as_int_or_none(value.get("limit")),
        "secondary_rank_by": _as_optional_text(value.get("secondary_rank_by")),
    }


def normalize_task_dependency(value: object) -> TaskDependency:
    if isinstance(value, str):
        return {
            "task_id": value.strip(),
            "artifact_key": None,
            "consume_as": "input_rows",
        }

    raw_dependency = value if isinstance(value, dict) else {}
    consume_as = raw_dependency.get("consume_as")
    if consume_as not in VALID_DEPENDENCY_CONSUME_AS:
        consume_as = "input_rows"
    return {
        "task_id": _as_optional_text(raw_dependency.get("task_id")) or "",
        "artifact_key": _as_optional_text(raw_dependency.get("artifact_key")),
        "consume_as": consume_as,
    }


def normalize_task_artifact(value: object, task_id: str) -> TaskArtifact:
    raw_artifact = value if isinstance(value, dict) else {}
    artifact_type = raw_artifact.get("artifact_type")
    if artifact_type not in VALID_ARTIFACT_TYPES:
        artifact_type = "unspecified"
    artifact_key = _as_optional_text(raw_artifact.get("artifact_key")) or f"{task_id}_artifact"
    return {
        "artifact_key": artifact_key,
        "artifact_type": artifact_type,
        "description": _as_optional_text(raw_artifact.get("description")),
    }


def normalize_task_plan(task: dict[str, Any], fallback_index: int = 1) -> TaskPlan:
    normalized_task = dict(task)

    task_id = _as_optional_text(normalized_task.get("task_id")) or f"task_{fallback_index}"
    intent = normalized_task.get("intent")
    if intent not in VALID_TASK_INTENTS:
        intent = "unknown"

    company_source = normalized_task.get("company_source")
    if company_source not in VALID_COMPANY_SOURCES:
        company_source = "unspecified"

    raw_depends_on = normalized_task.get("depends_on")
    dependencies = raw_depends_on if isinstance(raw_depends_on, list) else []

    return {
        "task_id": task_id,
        "intent": intent,
        "metric_mentions": _normalize_text_list(normalized_task.get("metric_mentions")),
        "company_mentions": _normalize_text_list(normalized_task.get("company_mentions")),
        "company_source": company_source,
        "time": normalized_task.get("time") if isinstance(normalized_task.get("time"), dict) else {},
        "ranking": normalize_ranking_spec(normalized_task.get("ranking")),
        "depends_on": [
            dependency
            for dependency in (
                normalize_task_dependency(item) for item in dependencies
            )
            if dependency.get("task_id")
        ],
        "output_artifact": normalize_task_artifact(
            normalized_task.get("output_artifact"),
            task_id,
        ),
    }
