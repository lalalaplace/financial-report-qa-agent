"""受控 LLM SQL 的请求、响应和校验结果结构。"""

from __future__ import annotations

from typing import Any, Literal, TypedDict


SqlGenerationMode = Literal["template", "llm_sql", "unsupported"]


class LlmSqlRequest(TypedDict, total=False):
    flexible_sql_spec: dict[str, Any]
    postgresql_constraints: dict[str, Any]
    allowed_tables: list[str]
    allowed_columns: dict[str, list[str]]
    metric_bindings: list[dict[str, Any]]
    max_rows: int
    required_output_fields: list[str]
    sql_task_type: str



class LlmSqlResponse(TypedDict, total=False):
    sql: str
    explanation: str
    used_tables: list[str]
    used_fields: list[str]
    assumptions: list[str]
    confidence: float | None
    cannot_generate: bool
    error_type: str | None
    error_message: str | None


class LlmSqlValidationResult(TypedDict, total=False):
    is_valid: bool
    error_type: str | None
    error_message: str | None
    used_tables: list[str]
    used_fields: list[str]
    guard_passed: bool
    semantic_guard_passed: bool


def metric_bindings_from_metrics(metrics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把已标准化指标压缩为 LLM 可使用的字段绑定。"""
    bindings: list[dict[str, Any]] = []
    for metric in metrics:
        bindings.append(
            {
                "metric_key": metric.get("metric_key"),
                "metric_name": metric.get("metric_name"),
                "metric_type": metric.get("metric_type", "base"),
                "table": metric.get("table"),
                "field": metric.get("field"),
                "formula": metric.get("formula"),
            }
        )
    return bindings


__all__ = [
    "LlmSqlRequest",
    "LlmSqlResponse",
    "LlmSqlValidationResult",
    "SqlGenerationMode",
    "metric_bindings_from_metrics",
]
