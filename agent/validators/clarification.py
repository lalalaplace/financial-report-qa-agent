"""统一澄清 payload 构造器。"""

from __future__ import annotations

from typing import Any

from agent.schemas.clarification import (
    AMBIGUOUS_COMPANY,
    AMBIGUOUS_METRIC,
    ERROR_CLARIFICATION_REQUIRED,
    ERROR_UNSUPPORTED_QUERY,
    INVALID_YEAR_RANGE,
    INVALID_COMPARE_COMPANY_COUNT,
    INVALID_RANKING_DIRECTION,
    INVALID_RANKING_LIMIT,
    MISSING_COMPANY,
    MISSING_METRIC,
    MISSING_RANKING_LIMIT,
    MISSING_YEAR,
    UNSUPPORTED_METRIC_FOR_INTENT,
    UNSUPPORTED_INTENT,
    ClarificationCandidate,
    ClarificationPayload,
    build_clarification_payload,
)
from agent.services.clarification_context import build_pending_clarification_state
from agent.services.clarification_service import build_clarification_question


def _with_question(payload: ClarificationPayload) -> ClarificationPayload:
    if payload.get("clarification_question"):
        return payload
    payload["clarification_question"] = build_clarification_question(payload)
    return payload


def make_missing_company_payload(*, detail: dict[str, Any] | None = None) -> ClarificationPayload:
    return _with_question(
        build_clarification_payload(
            clarification_type=MISSING_COMPANY,
            error_type=ERROR_CLARIFICATION_REQUIRED,
            empty_fields=["companies"],
            detail=detail,
        )
    )


def make_ambiguous_company_payload(
    *,
    candidates: list[ClarificationCandidate],
    detail: dict[str, Any] | None = None,
) -> ClarificationPayload:
    return _with_question(
        build_clarification_payload(
            clarification_type=AMBIGUOUS_COMPANY,
            error_type=ERROR_CLARIFICATION_REQUIRED,
            empty_fields=["companies"],
            clarification_candidates=candidates,
            detail=detail,
        )
    )


def make_missing_metric_payload(*, detail: dict[str, Any] | None = None) -> ClarificationPayload:
    return _with_question(
        build_clarification_payload(
            clarification_type=MISSING_METRIC,
            error_type=ERROR_CLARIFICATION_REQUIRED,
            empty_fields=["metrics"],
            detail=detail,
        )
    )


def make_ambiguous_metric_payload(
    *,
    candidates: list[ClarificationCandidate],
    detail: dict[str, Any] | None = None,
) -> ClarificationPayload:
    return _with_question(
        build_clarification_payload(
            clarification_type=AMBIGUOUS_METRIC,
            error_type=ERROR_CLARIFICATION_REQUIRED,
            empty_fields=["metrics"],
            clarification_candidates=candidates,
            detail=detail,
        )
    )


def make_missing_year_payload(
    *,
    fields: list[str] | None = None,
    detail: dict[str, Any] | None = None,
) -> ClarificationPayload:
    return _with_question(
        build_clarification_payload(
            clarification_type=MISSING_YEAR,
            error_type=ERROR_CLARIFICATION_REQUIRED,
            empty_fields=fields or ["report_year"],
            detail=detail,
        )
    )


def make_invalid_year_range_payload(*, detail: dict[str, Any] | None = None) -> ClarificationPayload:
    return _with_question(
        build_clarification_payload(
            clarification_type=INVALID_YEAR_RANGE,
            error_type=ERROR_CLARIFICATION_REQUIRED,
            empty_fields=["start_year", "end_year"],
            detail=detail,
        )
    )


def make_missing_ranking_limit_payload(*, detail: dict[str, Any] | None = None) -> ClarificationPayload:
    return _with_question(
        build_clarification_payload(
            clarification_type=MISSING_RANKING_LIMIT,
            error_type=ERROR_CLARIFICATION_REQUIRED,
            empty_fields=["ranking_limit"],
            detail=detail,
        )
    )


def make_unsupported_intent_payload(*, detail: dict[str, Any] | None = None) -> ClarificationPayload:
    return _with_question(
        build_clarification_payload(
            clarification_type=UNSUPPORTED_INTENT,
            error_type=ERROR_UNSUPPORTED_QUERY,
            empty_fields=["intent_type"],
            detail=detail,
        )
    )


def _candidate_from_company(candidate: dict[str, Any]) -> ClarificationCandidate:
    return {
        "candidate_type": "company",
        "normalized_name": candidate.get("company_name") or candidate.get("stock_abbr") or "",
        "code": candidate.get("stock_code") or "",
        "display_name": candidate.get("stock_abbr") or candidate.get("company_name") or candidate.get("stock_code") or "",
        "confidence": candidate.get("score", 0),
        "source": candidate.get("match_type", "company_resolver"),
    }


def _candidate_from_metric(candidate: dict[str, Any]) -> ClarificationCandidate:
    return {
        "candidate_type": "metric",
        "metric_key": candidate.get("metric_key") or "",
        "display_name": candidate.get("metric_name") or candidate.get("metric_key") or "",
        "confidence": candidate.get("score", 0),
        "source": "metric_dictionary",
    }


def normalize_clarification_result(result: dict[str, Any], state: dict[str, Any] | None = None) -> dict[str, Any]:
    """把旧 validator 的澄清结果归一为 V0.6 payload 字段。"""
    if not result.get("need_clarification"):
        return result

    state = state or {}
    legacy_error_type = result.get("error_type") or "need_clarification"
    company_candidates = state.get("company_candidates") or result.get("company_candidates") or []
    metric_candidates = state.get("metric_candidates") or result.get("metric_candidates") or []

    company_status = state.get("company_resolution_status")
    metric_status = state.get("metric_resolution_status")

    if (
        legacy_error_type in {"clarify_company", "company_not_found", "missing_company"}
        or (legacy_error_type == "need_clarification" and company_status in {"ambiguous", "unresolved", "needs_validation"})
    ):
        if (
            state.get("intent_type") in {"company_compare_query", "company_compare_trend_query", "company_compare_yoy_query"}
            and len(company_candidates) == 1
        ):
            payload = build_clarification_payload(
                clarification_type=INVALID_COMPARE_COMPANY_COUNT,
                error_type=ERROR_CLARIFICATION_REQUIRED,
                empty_fields=["compare_companies"],
                clarification_candidates=[_candidate_from_company(candidate) for candidate in company_candidates],
                detail={"legacy_error_type": legacy_error_type},
            )
            payload = _with_question(payload)
        elif company_candidates:
            payload = make_ambiguous_company_payload(
                candidates=[_candidate_from_company(candidate) for candidate in company_candidates],
                detail={"legacy_error_type": legacy_error_type},
            )
        else:
            payload = make_missing_company_payload(detail={"legacy_error_type": legacy_error_type})
    elif (
        legacy_error_type in {"clarify_metric", "metric_not_found", "missing_metric"}
        or (legacy_error_type == "need_clarification" and metric_status in {"ambiguous", "unresolved"})
    ):
        if metric_candidates:
            payload = make_ambiguous_metric_payload(
                candidates=[_candidate_from_metric(candidate) for candidate in metric_candidates],
                detail={"legacy_error_type": legacy_error_type},
            )
        else:
            payload = make_missing_metric_payload(detail={"legacy_error_type": legacy_error_type})
    elif legacy_error_type in {"clarify_year", "missing_year", "missing_report_year", "invalid_report_year"}:
        payload = make_missing_year_payload(detail={"legacy_error_type": legacy_error_type})
    elif legacy_error_type in {"clarify_year_range", "invalid_year_range", "missing_start_year", "missing_end_year"}:
        payload = make_invalid_year_range_payload(detail={"legacy_error_type": legacy_error_type})
    elif legacy_error_type in {"missing_limit", "missing_ranking_limit"}:
        payload = make_missing_ranking_limit_payload(detail={"legacy_error_type": legacy_error_type})
    elif legacy_error_type in {"invalid_limit", "invalid_ranking_limit"}:
        payload = build_clarification_payload(
            clarification_type=INVALID_RANKING_LIMIT,
            error_type=ERROR_CLARIFICATION_REQUIRED,
            empty_fields=["ranking_limit"],
            detail={"legacy_error_type": legacy_error_type},
        )
        payload = _with_question(payload)
    elif legacy_error_type in {"missing_rank_direction", "invalid_ranking_direction"}:
        payload = build_clarification_payload(
            clarification_type=INVALID_RANKING_DIRECTION,
            error_type=ERROR_CLARIFICATION_REQUIRED,
            empty_fields=["ranking_direction"],
            detail={"legacy_error_type": legacy_error_type},
        )
        payload = _with_question(payload)
    elif legacy_error_type in {"multiple_companies_not_supported"}:
        payload = build_clarification_payload(
            clarification_type=INVALID_COMPARE_COMPANY_COUNT,
            error_type=ERROR_CLARIFICATION_REQUIRED,
            empty_fields=["compare_companies"],
            detail={"legacy_error_type": legacy_error_type},
        )
        payload = _with_question(payload)
    elif legacy_error_type in {"unsupported_metric_type"} or str(legacy_error_type).startswith("unsupported_mixed"):
        payload = build_clarification_payload(
            clarification_type=UNSUPPORTED_METRIC_FOR_INTENT,
            error_type=ERROR_UNSUPPORTED_QUERY,
            empty_fields=["metrics"],
            detail={"legacy_error_type": legacy_error_type},
        )
        payload = _with_question(payload)
    else:
        payload = make_unsupported_intent_payload(detail={"legacy_error_type": legacy_error_type})

    normalized = dict(result)
    normalized.update(payload)
    normalized["clarification_payload"] = payload
    normalized["business_success"] = False
    normalized.update(build_pending_clarification_state({**state, **normalized}))
    return normalized


__all__ = [
    "make_ambiguous_company_payload",
    "make_ambiguous_metric_payload",
    "make_invalid_year_range_payload",
    "make_missing_company_payload",
    "make_missing_metric_payload",
    "make_missing_ranking_limit_payload",
    "make_missing_year_payload",
    "make_unsupported_intent_payload",
    "normalize_clarification_result",
]
