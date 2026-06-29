"""V0.6.0 统一澄清 payload schema。

节点只负责返回结构化澄清信息；自然语言补问由 answer 层或后续
clarification_service 统一生成。
"""

from typing import Any, Literal, TypedDict


ClarificationErrorType = Literal[
    "clarification_required",
    "unsupported_query",
    "invalid_query",
    "planner_failed",
    "standardization_failed",
]

ClarificationType = Literal[
    "missing_company",
    "ambiguous_company",
    "missing_metric",
    "ambiguous_metric",
    "missing_year",
    "invalid_year_range",
    "missing_ranking_limit",
    "invalid_ranking_limit",
    "unsupported_intent",
    "unsupported_metric_for_intent",
    "invalid_compare_company_count",
    "invalid_ranking_direction",
]

EmptyField = Literal[
    "companies",
    "metrics",
    "start_year",
    "end_year",
    "report_year",
    "ranking_limit",
    "ranking_direction",
    "compare_companies",
    "intent_type",
]


ERROR_CLARIFICATION_REQUIRED = "clarification_required"
ERROR_UNSUPPORTED_QUERY = "unsupported_query"
ERROR_INVALID_QUERY = "invalid_query"
ERROR_PLANNER_FAILED = "planner_failed"
ERROR_STANDARDIZATION_FAILED = "standardization_failed"

MISSING_COMPANY = "missing_company"
AMBIGUOUS_COMPANY = "ambiguous_company"
MISSING_METRIC = "missing_metric"
AMBIGUOUS_METRIC = "ambiguous_metric"
MISSING_YEAR = "missing_year"
INVALID_YEAR_RANGE = "invalid_year_range"
MISSING_RANKING_LIMIT = "missing_ranking_limit"
INVALID_RANKING_LIMIT = "invalid_ranking_limit"
UNSUPPORTED_INTENT = "unsupported_intent"
UNSUPPORTED_METRIC_FOR_INTENT = "unsupported_metric_for_intent"
INVALID_COMPARE_COMPANY_COUNT = "invalid_compare_company_count"
INVALID_RANKING_DIRECTION = "invalid_ranking_direction"

CLARIFICATION_ERROR_TYPES = {
    ERROR_CLARIFICATION_REQUIRED,
    ERROR_UNSUPPORTED_QUERY,
    ERROR_INVALID_QUERY,
    ERROR_PLANNER_FAILED,
    ERROR_STANDARDIZATION_FAILED,
}

CLARIFICATION_TYPES = {
    MISSING_COMPANY,
    AMBIGUOUS_COMPANY,
    MISSING_METRIC,
    AMBIGUOUS_METRIC,
    MISSING_YEAR,
    INVALID_YEAR_RANGE,
    MISSING_RANKING_LIMIT,
    INVALID_RANKING_LIMIT,
    UNSUPPORTED_INTENT,
    UNSUPPORTED_METRIC_FOR_INTENT,
    INVALID_COMPARE_COMPANY_COUNT,
    INVALID_RANKING_DIRECTION,
}

EMPTY_FIELDS = {
    "companies",
    "metrics",
    "start_year",
    "end_year",
    "report_year",
    "ranking_limit",
    "ranking_direction",
    "compare_companies",
    "intent_type",
}


class ClarificationCandidate(TypedDict, total=False):
    candidate_type: str
    raw_mention: str
    normalized_name: str
    code: str
    metric_key: str
    display_name: str
    confidence: float
    source: str
    reason: str


class ClarificationPayload(TypedDict, total=False):
    need_clarification: bool
    clarification_type: ClarificationType | str
    clarification_question: str
    error_type: ClarificationErrorType | str
    empty_fields: list[EmptyField | str]
    clarification_candidates: list[ClarificationCandidate]
    detail: dict[str, Any]


def validate_clarification_payload(payload: dict[str, Any]) -> ClarificationPayload:
    """校验澄清 payload 的最小结构，返回可继续传递的 payload。"""
    if not isinstance(payload, dict):
        raise ValueError("clarification payload 必须是 dict。")
    if payload.get("need_clarification") is not True:
        raise ValueError("need_clarification 必须为 True。")

    clarification_type = payload.get("clarification_type")
    if clarification_type not in CLARIFICATION_TYPES:
        raise ValueError(f"未知 clarification_type：{clarification_type}")

    error_type = payload.get("error_type")
    if error_type not in CLARIFICATION_ERROR_TYPES:
        raise ValueError(f"未知 error_type：{error_type}")

    empty_fields = payload.get("empty_fields")
    if not isinstance(empty_fields, list):
        raise ValueError("empty_fields 必须是 list。")
    invalid_empty_fields = [field for field in empty_fields if field not in EMPTY_FIELDS]
    if invalid_empty_fields:
        raise ValueError(f"未知 empty_fields：{invalid_empty_fields}")

    candidates = payload.get("clarification_candidates")
    if not isinstance(candidates, list):
        raise ValueError("clarification_candidates 必须是 list。")
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise ValueError("clarification_candidates 中的候选项必须是 dict。")

    question = payload.get("clarification_question", "")
    if not isinstance(question, str):
        raise ValueError("clarification_question 必须是 str。")

    detail = payload.get("detail", {})
    if not isinstance(detail, dict):
        raise ValueError("detail 必须是 dict。")

    return {
        "need_clarification": True,
        "clarification_type": clarification_type,
        "clarification_question": question,
        "error_type": error_type,
        "empty_fields": empty_fields,
        "clarification_candidates": candidates,
        "detail": detail,
    }


def build_clarification_payload(
    *,
    clarification_type: ClarificationType | str,
    clarification_question: str = "",
    error_type: ClarificationErrorType | str = ERROR_CLARIFICATION_REQUIRED,
    empty_fields: list[EmptyField | str] | None = None,
    clarification_candidates: list[ClarificationCandidate] | None = None,
    detail: dict[str, Any] | None = None,
) -> ClarificationPayload:
    """构造统一澄清 payload，避免各节点重复拼字段。"""
    payload = {
        "need_clarification": True,
        "clarification_type": clarification_type,
        "clarification_question": clarification_question,
        "error_type": error_type,
        "empty_fields": empty_fields or [],
        "clarification_candidates": clarification_candidates or [],
        "detail": detail or {},
    }
    return validate_clarification_payload(payload)


__all__ = [
    "AMBIGUOUS_COMPANY",
    "AMBIGUOUS_METRIC",
    "CLARIFICATION_ERROR_TYPES",
    "CLARIFICATION_TYPES",
    "EMPTY_FIELDS",
    "ERROR_CLARIFICATION_REQUIRED",
    "ERROR_INVALID_QUERY",
    "ERROR_PLANNER_FAILED",
    "ERROR_STANDARDIZATION_FAILED",
    "ERROR_UNSUPPORTED_QUERY",
    "INVALID_COMPARE_COMPANY_COUNT",
    "INVALID_RANKING_DIRECTION",
    "INVALID_RANKING_LIMIT",
    "INVALID_YEAR_RANGE",
    "MISSING_COMPANY",
    "MISSING_METRIC",
    "MISSING_RANKING_LIMIT",
    "MISSING_YEAR",
    "UNSUPPORTED_INTENT",
    "UNSUPPORTED_METRIC_FOR_INTENT",
    "ClarificationCandidate",
    "ClarificationErrorType",
    "ClarificationPayload",
    "ClarificationType",
    "EmptyField",
    "build_clarification_payload",
    "validate_clarification_payload",
]
