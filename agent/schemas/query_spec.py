"""统一查询规格 QuerySpec。"""

from __future__ import annotations

from typing import Any, Literal, TypedDict


ExecutionMode = Literal["deterministic", "flexible_sql", "unsupported"]
AnswerMode = Literal["fixed", "analytical"]


class QuerySpec(TypedDict, total=False):
    execution_mode: ExecutionMode
    operation: str
    entities: list[Any]
    metrics: list[Any]
    time_scope: dict[str, Any]
    filters: list[dict[str, Any]]
    sort: list[dict[str, Any]]
    limit: int | None
    group_by: list[Any]
    set_operations: list[dict[str, Any]]
    derived_expressions: list[dict[str, Any]]
    answer_mode: AnswerMode
    unsupported_reason: str | None
    clarification_question: str | None
    is_single_database_relational_query: bool


VALID_EXECUTION_MODES = {"deterministic", "flexible_sql", "unsupported"}
VALID_ANSWER_MODES = {"fixed", "analytical"}
DEFAULT_PERIOD = "FY"
COMPARE_OPERATIONS = {
    "company_compare_query",
    "company_compare_trend_query",
    "company_compare_yoy_query",
}


def _as_list(value: object) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _as_dict(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _as_dict_list(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _as_optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _as_optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _year_range_from_filters(filters: list[dict[str, Any]]) -> tuple[int, int] | None:
    """从 QuerySpec 已表达的年份筛选补全时间范围，不重新解析原始问题。"""
    for item in filters:
        if item.get("field") not in {"year", "report_year"} or item.get("operator") != "between":
            continue
        value = item.get("value")
        if not isinstance(value, list) or len(value) != 2:
            continue
        start_year, end_year = (_as_optional_int(value[0]), _as_optional_int(value[1]))
        if start_year is not None and end_year is not None:
            return min(start_year, end_year), max(start_year, end_year)
    return None


def _metric_name(value: object) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, dict):
        for key in ("metric", "metric_key", "metric_name", "metric_mention"):
            metric = value.get(key)
            if isinstance(metric, str) and metric.strip():
                return metric.strip()
    return None


def _collect_metric_mentions(spec: QuerySpec) -> list[str]:
    mentions: list[str] = []
    for metric in spec.get("metrics") or []:
        metric_name = _metric_name(metric)
        if metric_name:
            mentions.append(metric_name)
    for item in spec.get("filters") or []:
        metric_name = _metric_name(item)
        if metric_name:
            mentions.append(metric_name)
    for item in spec.get("sort") or []:
        metric_name = _metric_name(item)
        if metric_name:
            mentions.append(metric_name)
    for item in spec.get("set_operations") or []:
        metric_name = _metric_name(item)
        if metric_name:
            mentions.append(metric_name)
    for item in spec.get("derived_expressions") or []:
        metric_name = _metric_name(item)
        if metric_name:
            mentions.append(metric_name)
    return list(dict.fromkeys(mentions))


def _collect_company_mentions(spec: QuerySpec) -> list[str]:
    mentions: list[str] = []
    for entity in spec.get("entities") or []:
        if isinstance(entity, str) and entity.strip():
            mentions.append(entity.strip())
        elif isinstance(entity, dict):
            for key in ("company", "company_name", "stock_code", "stock_abbr", "name"):
                value = entity.get(key)
                if isinstance(value, str) and value.strip():
                    mentions.append(value.strip())
                    break
    return list(dict.fromkeys(mentions))


def normalize_query_spec(value: object) -> QuerySpec:
    """规范化 Planner 输出的统一查询规格。"""
    raw = _as_dict(value)
    execution_mode = raw.get("execution_mode")
    if execution_mode not in VALID_EXECUTION_MODES:
        execution_mode = "unsupported"

    answer_mode = raw.get("answer_mode")
    if answer_mode not in VALID_ANSWER_MODES:
        answer_mode = "fixed" if execution_mode == "deterministic" else "analytical"

    time_scope = _as_dict(raw.get("time_scope"))
    if "period" not in time_scope:
        time_scope["period"] = DEFAULT_PERIOD

    entities = [
        item for item in _as_list(raw.get("entities"))
        if not (isinstance(item, str) and item.strip() in {"公司", "企业", "上市公司", "全部公司", "所有公司"})
    ]
    operation = _as_optional_text(raw.get("operation")) or "unknown"
    if operation == "rank_query":
        operation = "ranking_query"
    limit = _as_optional_int(raw.get("limit"))
    clarification_question = _as_optional_text(raw.get("clarification_question"))
    unsupported_reason = _as_optional_text(raw.get("unsupported_reason"))
    filters = _as_dict_list(raw.get("filters"))
    set_operations = _as_dict_list(raw.get("set_operations"))
    year_range = _year_range_from_filters(filters)
    if year_range and not isinstance(time_scope.get("year"), int):
        time_scope["start_year"], time_scope["end_year"] = year_range
    has_yoy_semantics = any(
        "同比" in str(item)
        for item in [
            *_as_list(raw.get("metrics")),
            *_as_dict_list(raw.get("filters")),
            *_as_dict_list(raw.get("sort")),
            *_as_dict_list(raw.get("derived_expressions")),
        ]
    )
    has_sort = bool(_as_dict_list(raw.get("sort")))
    filter_count = len(filters)
    set_operation_types = {
        item.get("type") for item in set_operations if isinstance(item.get("type"), str)
    }
    has_top_n = "top_n" in set_operation_types
    has_intersection = "intersection" in set_operation_types
    has_direction_filters = "filter" in set_operation_types
    has_chained_top_n = any(
        item.get("type") == "top_n" and isinstance(item.get("input"), str) and item.get("input")
        for item in set_operations
    )
    # 公司对比属于已注册的确定性能力。Planner 即使误标为 flexible_sql，
    # 也不能让实体标准化按单公司逻辑把两个明确公司误判为候选歧义。
    if operation in COMPARE_OPERATIONS:
        execution_mode = "deterministic"
    # 指定实体且不截取 Top N 的排名，语义是查询名次而不是生成排名列表。
    if operation in {"ranking_query", "point_ranking", "company_ranking", "entity_ranking"} and entities and limit is None:
        operation = "rank_position_query"
    if execution_mode == "deterministic" and has_yoy_semantics and operation not in {
        "yoy_ranking_query", "company_compare_yoy_query", "derived_yoy_query"
    }:
        operation = "yoy_query"
    if execution_mode == "flexible_sql":
        if has_chained_top_n:
            operation = "nested_top_n"
        elif has_top_n and (not has_intersection or len(set_operations) <= 2):
            operation = "topn_then_filter"
        elif has_direction_filters and has_intersection:
            operation = "yoy_direction_filter_sort"
        elif filter_count >= 2 and has_yoy_semantics:
            operation = "yoy_direction_filter_sort" if has_sort else "multi_metric_yoy_filter"
    if operation == "set_intersection_ranking" and not has_intersection:
        operation = "nested_top_n"
    # 给定目标年份时，同比口径固定为与上一年度比较，无需再次澄清。
    if has_yoy_semantics and isinstance(time_scope.get("year"), int):
        clarification_question = None
    # 缺少槽位属于可澄清问题，不能同时标记为能力不支持。
    if clarification_question:
        unsupported_reason = None

    return {
        "execution_mode": execution_mode,
        "operation": operation,
        "entities": entities,
        "metrics": _as_list(raw.get("metrics")),
        "time_scope": time_scope,
        "filters": filters,
        "sort": _as_dict_list(raw.get("sort")),
        "limit": limit,
        "group_by": _as_list(raw.get("group_by")),
        "set_operations": set_operations,
        "derived_expressions": _as_dict_list(raw.get("derived_expressions")),
        "answer_mode": answer_mode,
        "unsupported_reason": unsupported_reason,
        "clarification_question": clarification_question,
        "is_single_database_relational_query": execution_mode != "unsupported" and not unsupported_reason,
    }


def query_spec_metric_mentions(spec: QuerySpec) -> list[str]:
    return _collect_metric_mentions(spec)


def query_spec_company_mentions(spec: QuerySpec) -> list[str]:
    return _collect_company_mentions(spec)


def query_spec_report_year(spec: QuerySpec) -> int | None:
    time_scope = spec.get("time_scope") or {}
    return _as_optional_int(time_scope.get("year") or time_scope.get("report_year"))


def query_spec_report_period(spec: QuerySpec) -> str:
    time_scope = spec.get("time_scope") or {}
    period = time_scope.get("period") or time_scope.get("report_period") or DEFAULT_PERIOD
    return period if isinstance(period, str) and period else DEFAULT_PERIOD


__all__ = [
    "AnswerMode",
    "ExecutionMode",
    "QuerySpec",
    "normalize_query_spec",
    "query_spec_company_mentions",
    "query_spec_metric_mentions",
    "query_spec_report_period",
    "query_spec_report_year",
]
