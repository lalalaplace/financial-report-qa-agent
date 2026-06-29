from typing import Literal, TypedDict


CompareOperator = Literal[
    "higher",
    "lower",
    "difference",
    "higher_than",
    "lower_than",
    "general",
    "larger_change",
    "faster_growth",
    "larger_decline",
]


class TimeRange(TypedDict, total=False):
    mode: Literal["single_year", "recent_n", "explicit_range", "unspecified"]
    report_year: int | None
    recent_n_years: int | None
    start_year: int | None
    end_year: int | None
    report_years: list[int] | None


class CompareSpec(TypedDict, total=False):
    operator: CompareOperator
    target: str | None
    subject_company: str | None
    reference_company: str | None


class QueryPlan(TypedDict, total=False):
    intent_type: Literal[
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
        "unknown",
    ]
    company_mentions: list[str]
    metric_mentions: list[str]
    report_period: Literal["FY", "H1", "Q1", "Q3", "unspecified"]
    time_range: TimeRange
    compare_spec: CompareSpec | None
    rank_direction: Literal["desc", "asc"] | None
    limit: int | None
    change_metric: Literal["yoy_rate", "growth_rate"] | None
    need_clarification: bool
    clarification_reason: str | None


VALID_INTENT_TYPES = {
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
    "unknown",
}
VALID_REPORT_PERIODS = {"FY", "H1", "Q1", "Q3", "unspecified"}
VALID_COMPARE_OPERATORS = {
    "higher",
    "lower",
    "difference",
    "higher_than",
    "lower_than",
    "general",
    "larger_change",
    "faster_growth",
    "larger_decline",
}
VALID_TIME_RANGE_MODES = {
    "single_year",
    "recent_n",
    "explicit_range",
    "year_range",
    "unspecified",
}
DEFAULT_REPORT_PERIOD = "FY"
DEFAULT_TREND_RECENT_N_YEARS = 5
MIN_RECENT_N_YEARS = 1
MAX_RECENT_N_YEARS = 10
DEFAULT_COMPARE_SPEC: CompareSpec = {
    "operator": "general",
    "target": None,
    "subject_company": None,
    "reference_company": None,
}
VALID_RANK_DIRECTIONS = {"desc", "asc"}
DEFAULT_RANK_LIMIT = 10
MIN_RANK_LIMIT = 1
MAX_RANK_LIMIT = 100


def _as_int_or_none(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _normalize_mentions(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _normalize_recent_n_years(value: object) -> int | None:
    recent_n_years = _as_int_or_none(value)
    if recent_n_years is None:
        return None
    return max(MIN_RECENT_N_YEARS, min(recent_n_years, MAX_RECENT_N_YEARS))


def _normalize_report_years(value: object) -> list[int]:
    if not isinstance(value, list):
        return []
    years: list[int] = []
    for item in value:
        year = _as_int_or_none(item)
        if year is not None and year >= 1900 and year not in years:
            years.append(year)
    return sorted(years)


def _normalize_time_range(value: object, intent_type: str) -> TimeRange:
    raw_time_range = value if isinstance(value, dict) else {}
    mode = raw_time_range.get("mode")
    if mode not in VALID_TIME_RANGE_MODES:
        mode = "unspecified"
    if mode == "year_range":
        mode = "explicit_range"

    time_range: TimeRange = {
        "mode": mode,
        "report_year": _as_int_or_none(raw_time_range.get("report_year")),
        "recent_n_years": _normalize_recent_n_years(
            raw_time_range.get("recent_n_years")
        ),
        "start_year": _as_int_or_none(raw_time_range.get("start_year")),
        "end_year": _as_int_or_none(raw_time_range.get("end_year")),
        "report_years": _normalize_report_years(raw_time_range.get("report_years")),
    }

    start_year = time_range.get("start_year")
    end_year = time_range.get("end_year")
    if start_year is not None and end_year is not None and start_year > end_year:
        time_range["start_year"], time_range["end_year"] = end_year, start_year
        start_year, end_year = end_year, start_year

    if not time_range["report_years"] and start_year is not None and end_year is not None:
        time_range["report_years"] = list(range(start_year, end_year + 1))

    report_year = time_range.get("report_year")
    if (
        intent_type == "company_compare_yoy_query"
        and time_range["mode"] == "single_year"
        and report_year is not None
        and not time_range["report_years"]
    ):
        time_range["report_years"] = [report_year - 1, report_year]

    if intent_type in ("trend_query", "company_compare_trend_query") and mode == "unspecified":
        time_range["mode"] = "recent_n"
        time_range["recent_n_years"] = DEFAULT_TREND_RECENT_N_YEARS
    elif time_range["mode"] == "recent_n" and time_range.get("recent_n_years") is None:
        time_range["recent_n_years"] = MIN_RECENT_N_YEARS

    if (
        time_range["mode"] == "recent_n"
        and report_year is not None
        and time_range.get("recent_n_years") is not None
        and not time_range["report_years"]
    ):
        recent_n_years = time_range["recent_n_years"]
        time_range["report_years"] = list(
            range(report_year - recent_n_years + 1, report_year + 1)
        )

    return time_range


def normalize_compare_spec(value: object) -> CompareSpec:
    raw_spec = value if isinstance(value, dict) else {}
    operator = raw_spec.get("operator")
    if operator not in VALID_COMPARE_OPERATORS:
        operator = "general"

    def _as_optional_str(raw_value: object) -> str | None:
        if isinstance(raw_value, str):
            stripped = raw_value.strip()
            return stripped or None
        return None

    return {
        "operator": operator,
        "target": _as_optional_str(raw_spec.get("target")),
        "subject_company": _as_optional_str(raw_spec.get("subject_company")),
        "reference_company": _as_optional_str(raw_spec.get("reference_company")),
    }


def validate_plan(plan: dict) -> dict:
    normalized_plan = dict(plan)

    intent_type = normalized_plan.get("intent_type")
    if intent_type not in VALID_INTENT_TYPES:
        intent_type = "unknown"
    normalized_plan["intent_type"] = intent_type

    report_period = normalized_plan.get("report_period")
    if report_period not in VALID_REPORT_PERIODS:
        report_period = "unspecified"
    if report_period == "unspecified":
        report_period = DEFAULT_REPORT_PERIOD
    normalized_plan["report_period"] = report_period

    normalized_plan["company_mentions"] = _normalize_mentions(
        normalized_plan.get("company_mentions")
    )
    normalized_plan["metric_mentions"] = _normalize_mentions(
        normalized_plan.get("metric_mentions")
    )
    normalized_plan["time_range"] = _normalize_time_range(
        normalized_plan.get("time_range"),
        intent_type,
    )
    if intent_type in (
        "company_compare_query",
        "company_compare_trend_query",
        "company_compare_yoy_query",
    ):
        normalized_plan["compare_spec"] = normalize_compare_spec(
            normalized_plan.get("compare_spec")
        )
    else:
        normalized_plan["compare_spec"] = None

    # ── 排名字段结构校验（业务准入在 ranking_validator） ──
    if intent_type in ("ranking_query", "yoy_ranking_query", "trend_ranking_query", "rank_position_query"):
        rank_direction = normalized_plan.get("rank_direction")
        if rank_direction not in VALID_RANK_DIRECTIONS:
            rank_direction = "desc"
        normalized_plan["rank_direction"] = rank_direction

        limit = _as_int_or_none(normalized_plan.get("limit"))
        normalized_plan["limit"] = None if intent_type == "rank_position_query" else limit
        if intent_type == "yoy_ranking_query":
            normalized_plan["change_metric"] = "yoy_rate"
        elif intent_type == "trend_ranking_query":
            normalized_plan["change_metric"] = "growth_rate"
        else:
            normalized_plan["change_metric"] = None
    else:
        normalized_plan["rank_direction"] = None
        normalized_plan["limit"] = None
        normalized_plan["change_metric"] = None

    if not isinstance(normalized_plan.get("need_clarification"), bool):
        normalized_plan["need_clarification"] = False
    if not isinstance(normalized_plan.get("clarification_reason"), str):
        normalized_plan["clarification_reason"] = None

    # ── 同比专项校验 ──
    if intent_type == "yoy_query":
        if not normalized_plan["company_mentions"]:
            normalized_plan["need_clarification"] = True
            normalized_plan["clarification_reason"] = "请说明你想查询哪家公司的同比数据。"
            return normalized_plan
        if not normalized_plan["metric_mentions"]:
            normalized_plan["need_clarification"] = True
            normalized_plan["clarification_reason"] = "请说明你想查询哪些指标的同比变化。"
            return normalized_plan
        time_range = normalized_plan.get("time_range", {})
        if time_range.get("report_year") is None:
            normalized_plan["need_clarification"] = True
            normalized_plan["clarification_reason"] = (
                "请问你想查询哪一年的同比变化？例如 2024 年营业收入同比增长多少。"
            )
            return normalized_plan

    # ── 多公司对比专项校验 ──
    if intent_type == "company_compare_query":
        if len(normalized_plan.get("company_mentions", [])) < 2:
            normalized_plan["need_clarification"] = True
            normalized_plan["clarification_reason"] = (
                "请提供至少两家公司进行对比，例如“华润三九和贵州茅台 2024 年营业收入谁更高”。"
            )
            return normalized_plan

    # ── 多公司趋势对比专项校验 ──
    if intent_type == "company_compare_yoy_query":
        if len(normalized_plan.get("company_mentions", [])) < 2:
            normalized_plan["need_clarification"] = True
            normalized_plan["clarification_reason"] = (
                "请提供至少两家公司进行同比对比，例如“华润三九和贵州茅台 2024 年营业收入同比对比”。"
            )
            return normalized_plan
        if not normalized_plan.get("metric_mentions"):
            normalized_plan["need_clarification"] = True
            normalized_plan["clarification_reason"] = (
                "请说明你想对比哪些财务指标的同比变化，例如营业收入、净利润等。"
            )
            return normalized_plan
        time_range = normalized_plan.get("time_range", {})
        if time_range.get("report_year") is None:
            normalized_plan["need_clarification"] = True
            normalized_plan["clarification_reason"] = (
                "请说明公司同比对比的年份，例如 2024 年。"
            )
            return normalized_plan

    if intent_type == "company_compare_trend_query":
        if len(normalized_plan.get("company_mentions", [])) < 2:
            normalized_plan["need_clarification"] = True
            normalized_plan["clarification_reason"] = (
                "请提供至少两家公司进行趋势对比，例如“华润三九和贵州茅台近三年营业收入趋势对比”。"
            )
            return normalized_plan
        if not normalized_plan.get("metric_mentions"):
            normalized_plan["need_clarification"] = True
            normalized_plan["clarification_reason"] = (
                "请说明你想对比哪些财务指标的趋势，例如营业收入、净利率等。"
            )
            return normalized_plan
        time_range = normalized_plan.get("time_range", {})
        if time_range.get("mode") == "single_year":
            normalized_plan["need_clarification"] = True
            normalized_plan["clarification_reason"] = (
                "公司趋势对比需要多年份范围，例如 2022 到 2024，或近三年。"
            )
            return normalized_plan
        if not normalized_plan.get("metric_mentions"):
            normalized_plan["need_clarification"] = True
            normalized_plan["clarification_reason"] = (
                "请说明你想对比哪些财务指标，例如营业收入、净利润等。"
            )
            return normalized_plan
        time_range = normalized_plan.get("time_range", {})
        if time_range.get("report_year") is None and time_range.get("mode") == "unspecified":
            normalized_plan["need_clarification"] = True
            normalized_plan["clarification_reason"] = (
                "请说明对比的年份，例如 2024 年。"
            )
            return normalized_plan

    return normalized_plan
