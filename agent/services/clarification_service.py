"""统一澄清补问生成服务。"""

from __future__ import annotations

from agent.schemas.clarification import (
    AMBIGUOUS_COMPANY,
    AMBIGUOUS_METRIC,
    INVALID_YEAR_RANGE,
    MISSING_COMPANY,
    MISSING_METRIC,
    MISSING_RANKING_LIMIT,
    MISSING_YEAR,
    INVALID_RANKING_LIMIT,
    INVALID_RANKING_DIRECTION,
    INVALID_COMPARE_COMPANY_COUNT,
    UNSUPPORTED_METRIC_FOR_INTENT,
    UNSUPPORTED_INTENT,
    ClarificationCandidate,
    ClarificationPayload,
    validate_clarification_payload,
)


def _candidate_name(candidate: ClarificationCandidate) -> str:
    return (
        candidate.get("display_name")
        or candidate.get("normalized_name")
        or candidate.get("metric_key")
        or candidate.get("code")
        or candidate.get("raw_mention")
        or "未知候选项"
    )


def _format_candidates(candidates: list[ClarificationCandidate]) -> str:
    if not candidates:
        return ""
    lines = []
    for index, candidate in enumerate(candidates, start=1):
        code = candidate.get("code")
        suffix = f"（{code}）" if code else ""
        lines.append(f"{index}. {_candidate_name(candidate)}{suffix}")
    return "\n".join(lines)


def build_missing_company_question(payload: ClarificationPayload) -> str:
    return "请说明要查询哪家公司，可以提供公司简称、全称或 6 位股票代码。"


def build_ambiguous_company_question(payload: ClarificationPayload) -> str:
    candidate_text = _format_candidates(payload.get("clarification_candidates", []))
    if not candidate_text:
        return "公司名称存在歧义，请提供完整公司名称或 6 位股票代码。"
    return f"请确认你指的是以下哪家公司：\n{candidate_text}"


def build_missing_metric_question(payload: ClarificationPayload) -> str:
    return "请说明要查询的财务指标，例如营业收入、净利润、总资产或净利率。"


def build_ambiguous_metric_question(payload: ClarificationPayload) -> str:
    candidate_text = _format_candidates(payload.get("clarification_candidates", []))
    if not candidate_text:
        return "指标名称存在歧义，请明确要查询的财务指标。"
    return f"请确认要查询以下哪个指标：\n{candidate_text}"


def build_missing_year_question(payload: ClarificationPayload) -> str:
    return "请说明要查询的年份，例如 2024 年。"


def build_invalid_year_range_question(payload: ClarificationPayload) -> str:
    return "年份范围不合法，请提供有效的开始年份和结束年份，例如 2022 到 2024 年。"


def build_missing_ranking_limit_question(payload: ClarificationPayload) -> str:
    return "请说明排名要返回多少家公司，例如前 10 家或后 5 家。"


def build_invalid_ranking_limit_question(payload: ClarificationPayload) -> str:
    return "排名数量不合法，请提供 1 到 100 之间的整数，例如前 10 家。"


def build_invalid_ranking_direction_question(payload: ClarificationPayload) -> str:
    return "请说明排名方向，例如最高、最低、前 10 家或后 10 家。"


def build_invalid_compare_company_count_question(payload: ClarificationPayload) -> str:
    return "对比查询需要明确两家或以上公司，请补充公司名称或 6 位股票代码。"


def build_unsupported_metric_for_intent_question(payload: ClarificationPayload) -> str:
    return "当前查询类型暂不支持所选指标组合，包括混合同比对比等场景，请拆分为单独问题后再查询。"


def build_unsupported_intent_question(payload: ClarificationPayload) -> str:
    detail = payload.get("detail", {})
    reason = detail.get("reason") if isinstance(detail, dict) else None
    if reason:
        return f"当前暂不支持该查询：{reason}。请调整问题后重试。"
    return "当前暂不支持该查询，请调整问题后重试。"


def build_clarification_question(payload: ClarificationPayload) -> str:
    """根据澄清类型生成用户可读补问。"""
    checked_payload = validate_clarification_payload(dict(payload))
    builders = {
        MISSING_COMPANY: build_missing_company_question,
        AMBIGUOUS_COMPANY: build_ambiguous_company_question,
        MISSING_METRIC: build_missing_metric_question,
        AMBIGUOUS_METRIC: build_ambiguous_metric_question,
        MISSING_YEAR: build_missing_year_question,
        INVALID_YEAR_RANGE: build_invalid_year_range_question,
        MISSING_RANKING_LIMIT: build_missing_ranking_limit_question,
        INVALID_RANKING_LIMIT: build_invalid_ranking_limit_question,
        INVALID_RANKING_DIRECTION: build_invalid_ranking_direction_question,
        INVALID_COMPARE_COMPANY_COUNT: build_invalid_compare_company_count_question,
        UNSUPPORTED_METRIC_FOR_INTENT: build_unsupported_metric_for_intent_question,
        UNSUPPORTED_INTENT: build_unsupported_intent_question,
    }
    builder = builders.get(checked_payload["clarification_type"])
    if builder is None:
        return checked_payload.get("clarification_question") or "请补充查询条件。"
    return builder(checked_payload)


__all__ = [
    "build_ambiguous_company_question",
    "build_ambiguous_metric_question",
    "build_clarification_question",
    "build_invalid_year_range_question",
    "build_invalid_compare_company_count_question",
    "build_invalid_ranking_direction_question",
    "build_invalid_ranking_limit_question",
    "build_missing_company_question",
    "build_missing_metric_question",
    "build_missing_ranking_limit_question",
    "build_missing_year_question",
    "build_unsupported_intent_question",
    "build_unsupported_metric_for_intent_question",
]
