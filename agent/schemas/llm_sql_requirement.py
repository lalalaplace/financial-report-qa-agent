"""受控 LLM SQL 需求结构。"""

from __future__ import annotations

from typing import Any, Literal, TypedDict


SQLNeedFlags = TypedDict(
    "SQLNeedFlags",
    {
        "prediction": bool,
        "external_data": bool,
        "text_understanding": bool,
        "pdf_evidence": bool,
    },
    total=False,
)

RequirementReason = Literal[
    "database_answerable_template_gap",
    "need_clarification",
    "unsupported",
    "template_should_handle",
    "unsafe_or_out_of_scope",
]

RequirementType = Literal[
    "scoped_ranking",
    "multi_metric_yoy_filter",
    "yoy_direction_filter_sort",
    "derived_metric_ranking",
    "derived_metric_filter",
    "cross_statement_filter",
    "topn_then_filter",
    "set_intersection",
    "metric_threshold_screen",
    "compare_to_group_average",
    "general_structured_query",
]

ReportPeriod = Literal["FY", "H1", "Q1", "Q3", "unspecified"]
UniverseType = Literal["all_companies", "explicit_companies", "dependency", "filtered_universe"]
CalculationType = Literal["metric_value", "yoy_rate", "derived_metric", "growth_rate"]
MetricRole = Literal[
    "base_universe_metric",
    "filter_metric",
    "sort_metric",
    "output_metric",
    "final_rank_metric",
]
FilterOperator = Literal[">", ">=", "<", "<=", "=", "!=", "is_positive", "is_negative"]
RankDirection = Literal["desc", "asc"]
ExpectedGrain = Literal["company", "company_year", "aggregate"]


class CompanyUniverse(TypedDict, total=False):
    type: UniverseType
    companies: list[Any]


class BaseUniverseRequirement(TypedDict, total=False):
    type: Literal["ranking", "filter", "intersection"]
    metric_mention: str | None
    calculation: CalculationType
    rank_direction: RankDirection | None
    limit: int | None
    filters: list[dict[str, Any]]


class RequirementMetric(TypedDict, total=False):
    metric_mention: str
    role: MetricRole
    calculation: CalculationType


class RequirementFilter(TypedDict, total=False):
    metric_mention: str
    calculation: CalculationType
    operator: FilterOperator
    value: int | float | str | None


class RequirementOrderBy(TypedDict, total=False):
    metric_mention: str
    calculation: CalculationType
    direction: RankDirection


class ExpectedOutput(TypedDict, total=False):
    grain: ExpectedGrain
    must_include: list[str]


class LlmSqlRequirement(TypedDict, total=False):
    can_use_llm_sql: bool
    reason: RequirementReason
    requirement_type: RequirementType | None
    template_status: Literal["missing"]
    read_only: bool
    report_year: int | None
    report_period: ReportPeriod | str | None
    company_universe: CompanyUniverse
    base_universe: BaseUniverseRequirement | None
    metrics: list[RequirementMetric]
    filters: list[RequirementFilter]
    order_by: RequirementOrderBy | None
    limit: int | None
    expected_output: ExpectedOutput
    needs: SQLNeedFlags
    clarification_question: str | None
    unsupported_reason: str | None

    # 兼容旧版 V0.9 受控 SQL 生成器字段。
    metric_mentions: list[str]
    company_mentions: list[str]


def _as_bool(value: object) -> bool:
    return value is True


def _as_optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _as_text_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _as_dict(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _as_dict_list(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _metric_mentions(value: dict[str, Any]) -> list[str]:
    mentions = _as_text_list(value.get("metric_mentions"))
    for metric in _as_dict_list(value.get("metrics")):
        mention = metric.get("metric_mention")
        if isinstance(mention, str) and mention.strip():
            mentions.append(mention.strip())
    for filter_item in _as_dict_list(value.get("filters")):
        mention = filter_item.get("metric_mention")
        if isinstance(mention, str) and mention.strip():
            mentions.append(mention.strip())
    for section_key in ("base_universe", "order_by"):
        section = value.get(section_key)
        if isinstance(section, dict):
            mention = section.get("metric_mention")
            if isinstance(mention, str) and mention.strip():
                mentions.append(mention.strip())
    return list(dict.fromkeys(mentions))


def normalize_llm_sql_requirement(value: object) -> LlmSqlRequirement | None:
    """规范化 LLM 输出的结构化 SQL 需求，不接受自然语言 SQL。"""
    if not isinstance(value, dict):
        return None

    needs = _as_dict(value.get("needs"))
    reason = value.get("reason") if isinstance(value.get("reason"), str) else None
    can_use_llm_sql = _as_bool(value.get("can_use_llm_sql"))
    company_universe = _as_dict(value.get("company_universe"))
    companies = company_universe.get("companies")
    return {
        "can_use_llm_sql": can_use_llm_sql,
        "reason": reason or ("database_answerable_template_gap" if can_use_llm_sql else "need_clarification"),
        "requirement_type": value.get("requirement_type") if isinstance(value.get("requirement_type"), str) else None,
        "template_status": "missing",
        "read_only": _as_bool(value.get("read_only")),
        "report_year": _as_optional_int(value.get("report_year")),
        "report_period": value.get("report_period") if isinstance(value.get("report_period"), str) else None,
        "company_universe": {
            "type": company_universe.get("type") if isinstance(company_universe.get("type"), str) else "all_companies",
            "companies": companies if isinstance(companies, list) else [],
        },
        "base_universe": _as_dict(value.get("base_universe")) or None,
        "metrics": _as_dict_list(value.get("metrics")),
        "filters": _as_dict_list(value.get("filters")),
        "order_by": _as_dict(value.get("order_by")) or None,
        "limit": _as_optional_int(value.get("limit")),
        "expected_output": _as_dict(value.get("expected_output")),
        "needs": {
            "prediction": _as_bool(needs.get("prediction")),
            "external_data": _as_bool(needs.get("external_data")),
            "text_understanding": _as_bool(needs.get("text_understanding")),
            "pdf_evidence": _as_bool(needs.get("pdf_evidence")),
        },
        "clarification_question": value.get("clarification_question") if isinstance(value.get("clarification_question"), str) else None,
        "unsupported_reason": value.get("unsupported_reason") if isinstance(value.get("unsupported_reason"), str) else None,
        "metric_mentions": _metric_mentions(value),
        "company_mentions": _as_text_list(value.get("company_mentions")),
    }


ALLOWED_REQUIREMENT_TYPES: tuple[str, ...] = (
    "scoped_ranking",
    "multi_metric_yoy_filter",
    "yoy_direction_filter_sort",
    "derived_metric_ranking",
    "derived_metric_filter",
    "cross_statement_filter",
    "topn_then_filter",
    "set_intersection",
    "metric_threshold_screen",
    "compare_to_group_average",
    "general_structured_query",
)


__all__ = [
    "ALLOWED_REQUIREMENT_TYPES",
    "LlmSqlRequirement",
    "normalize_llm_sql_requirement",
]
