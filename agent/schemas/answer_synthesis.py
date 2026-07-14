"""LLM 综合回答的输入输出结构。"""

from __future__ import annotations

from typing import Any, Literal, TypedDict


AnswerType = Literal[
    "single_value",
    "ranking_table",
    "table_with_summary",
    "empty_result",
    "error_explanation",
]

AnswerMode = Literal["template", "llm_answer"]


class AnswerQualityWarning(TypedDict, total=False):
    code: str
    message: str


class AnswerTable(TypedDict, total=False):
    columns: list[str]
    rows: list[dict[str, Any]]


class ResultQuality(TypedDict, total=False):
    row_count: int
    is_empty: bool
    is_truncated: bool
    max_rows_passed_to_llm: int
    null_fields: list[str]
    warnings: list[str]


class ExecutionStatus(TypedDict, total=False):
    sql_generation_mode: str | None
    sql_guard_passed: bool
    semantic_guard_passed: bool
    dry_run_passed: bool


class AnswerContext(TypedDict, total=False):
    original_question: str
    query_type: Literal["single", "composite", "llm_sql"]
    final_answer_mode: str | None
    plan_summary: dict[str, Any]
    metric_metadata: list[dict[str, Any]]
    result_rows: list[dict[str, Any]]
    result_quality: ResultQuality
    execution_status: ExecutionStatus
    task_results_summary: list[dict[str, Any]]
    task_artifact_summary: dict[str, Any]
    final_task_id: str | None
    llm_sql_requirement: dict[str, Any] | None
    template_gap_reason: str | None
    requirement_type: str | None
    filters: list[dict[str, Any]]
    order_by: dict[str, Any] | None
    limit: int | None
    expected_output: dict[str, Any] | None


class LlmAnswerResponse(TypedDict, total=False):
    answer_type: AnswerType
    title: str
    summary: str
    table: AnswerTable
    key_findings: list[str]
    method_note: str
    data_note: str
    warnings: list[str]


__all__ = [
    "AnswerContext",
    "AnswerMode",
    "AnswerQualityWarning",
    "AnswerTable",
    "AnswerType",
    "LlmAnswerResponse",
]
