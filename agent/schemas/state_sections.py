"""Agent 分区状态定义与合并工具。"""

from __future__ import annotations

from typing import Any, Literal, TypedDict


ErrorStage = Literal[
    "planning", "normalization", "capability_routing", "sql_generation",
    "sql_guard", "dry_run", "execution", "result_contract", "sql_repair",
    "answer_generation", "answer_validation", "narrative",
]


class ConversationState(TypedDict, total=False):
    user_question: str
    route_type: str | None
    target_context: str | None
    clarification_payload: dict[str, Any] | None
    last_successful_query_plan: dict[str, Any] | None


class PlanningState(TypedDict, total=False):
    query_spec: dict[str, Any] | None
    normalization: dict[str, Any]
    validation_status: str | None
    capability_decision: dict[str, Any] | None


class SQLAttempt(TypedDict, total=False):
    attempt: int
    sql: str | None
    stage: ErrorStage
    success: bool
    error_type: str | None
    error_message: str | None


class ExecutionState(TypedDict, total=False):
    execution_mode: Literal["deterministic", "flexible_sql", "unsupported"] | None
    deterministic_plan: dict[str, Any] | None
    flexible_sql_spec: dict[str, Any] | None
    generated_sql: str | None
    sql_attempts: list[SQLAttempt]
    guard_result: dict[str, Any] | None
    dry_run_result: dict[str, Any] | None
    execution_result: dict[str, Any] | None


class ResultState(TypedDict, total=False):
    analysis_result: dict[str, Any] | None
    result_contract: dict[str, Any] | None
    deterministic_table: dict[str, Any] | None


class AnswerState(TypedDict, total=False):
    answer_mode: str | None
    narrative: dict[str, Any] | None
    final_answer: str | None
    validation: dict[str, Any] | None
    business_success: bool | None


class ErrorState(TypedDict, total=False):
    error_stage: ErrorStage | None
    error_type: str | None
    error_message: str | None
    retryable: bool
    details: dict[str, Any]


def merge_state_section(left: dict[str, Any] | None, right: dict[str, Any] | None) -> dict[str, Any]:
    """合并同一分区的并行局部更新。"""
    return {**(left or {}), **(right or {})}


def error_update(
    stage: ErrorStage,
    error_type: str,
    message: str | None,
    *,
    retryable: bool = False,
    details: dict[str, Any] | None = None,
) -> dict[str, ErrorState]:
    """构造阶段明确的错误状态，避免复用历史错误。"""
    return {"error": {"error_stage": stage, "error_type": error_type, "error_message": message,
                      "retryable": retryable, "details": details or {}}}


__all__ = ["AnswerState", "ConversationState", "ErrorStage", "ErrorState", "ExecutionState",
           "PlanningState", "ResultState", "SQLAttempt", "error_update", "merge_state_section"]
