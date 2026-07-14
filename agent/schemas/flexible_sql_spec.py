"""Flexible SQL 正式结构化规格。"""

from __future__ import annotations

from typing import Any, Literal, TypedDict


ExpectedResultShape = Literal["scalar", "single_row", "table", "time_series"]


class OutputColumn(TypedDict, total=False):
    name: str
    source: str | None
    expression: str | None
    role: str | None


class JoinSpec(TypedDict, total=False):
    left_table: str
    right_table: str
    on: list[str]
    join_type: str


class FilterSpec(TypedDict, total=False):
    metric: str | None
    field: str | None
    operator: str
    value: Any
    calculation: str | None


class RankingSpec(TypedDict, total=False):
    metric: str | None
    direction: str
    limit: int | None
    partition_by: list[str]
    output: str | None


class SetOperationSpec(TypedDict, total=False):
    type: str
    metric: str | None
    n: int | None
    inputs: list[str]
    output: str | None


class StageSpec(TypedDict, total=False):
    stage_id: str
    operation: str
    input_stage: str
    metric: str | None
    limit: int | None
    partition: list[str]
    order: str
    inputs: list[str]
    exclude_null_metric: bool


class DerivedExpression(TypedDict, total=False):
    name: str
    expression: str
    dependencies: list[str]


class TimeConstraint(TypedDict, total=False):
    year: int | None
    period: str | None
    field: str | None


class OrderSpec(TypedDict, total=False):
    metric: str | None
    field: str | None
    direction: str


class Threshold(TypedDict, total=False):
    metric: str
    operator: str
    user_value: int | float
    unit: str
    normalized_value: int | float


class SemanticSQLContract(TypedDict, total=False):
    """由系统生成、SQL 生成与修复过程均不可修改的执行语义合同。"""
    required_tables: list[str]
    required_columns: list[str]
    metric_formula_id: str | None
    formula_dependencies: list[str]
    time_periods: list[int]
    report_period: str
    normalized_thresholds: list[Threshold]
    required_filters: list[FilterSpec]
    required_sort: list[OrderSpec]
    required_limit: int | None
    stages: list[StageSpec]
    metric_sources: list[dict[str, Any]]


class FlexibleSQLSpec(TypedDict, total=False):
    question: str
    operation: str
    stages: list[StageSpec]
    final_order: list[OrderSpec]
    display_limit: int | None
    entity_constraints: list[dict[str, str]]
    output_columns: list[OutputColumn]
    source_tables: list[str]
    joins: list[JoinSpec]
    filters: list[FilterSpec]
    ranking_rules: list[RankingSpec]
    set_operations: list[SetOperationSpec]
    derived_metrics: list[DerivedExpression]
    time_constraints: list[TimeConstraint]
    grouping: list[str]
    ordering: list[OrderSpec]
    limit: int | None
    expected_grain: str
    expected_result_shape: ExpectedResultShape
    semantic_contract: SemanticSQLContract


def _as_dict(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _as_dict_list(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _as_text_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _as_optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    return value if isinstance(value, int) else None


def _metric_mentions(requirement: dict[str, Any]) -> list[str]:
    mentions = _as_text_list(requirement.get("metric_mentions"))
    for item in _as_dict_list(requirement.get("metrics")):
        value = item.get("metric_mention") or item.get("metric")
        if isinstance(value, str) and value.strip():
            mentions.append(value.strip())
    return list(dict.fromkeys(mentions))


def _source_tables_from_metrics(metrics: list[dict[str, Any]]) -> list[str]:
    tables = [
        metric.get("table")
        for metric in metrics
        if isinstance(metric.get("table"), str) and metric.get("table")
    ]
    return sorted(set(tables))


def _metric_by_mention(metrics: list[dict[str, Any]], mention: object) -> dict[str, Any] | None:
    if not isinstance(mention, str):
        return None
    key = mention.strip().lower()
    for metric in metrics:
        candidates = (metric.get("metric_key"), metric.get("metric_name"), *(metric.get("aliases") or []))
        if any(isinstance(item, str) and item.strip().lower() == key for item in candidates):
            return metric
    return None


def _formula_contract(metric: dict[str, Any], metric_dictionary: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if metric.get("metric_type") != "derived":
        table, field = metric.get("table"), metric.get("field")
        return {"metric": metric.get("metric_key"), "required_table": table, "formula_id": None,
                "dependencies": [f"{table}.{field}"] if table and field else []}
    formula = metric.get("formula") if isinstance(metric.get("formula"), dict) else {}
    dependencies: list[str] = []
    fields: list[str] = []
    for role in ("numerator", "denominator"):
        dependency = metric_dictionary.get(formula.get(role)) if isinstance(formula.get(role), str) else None
        if not isinstance(dependency, dict) or not dependency.get("table") or not dependency.get("field"):
            raise ValueError(f"派生指标 {metric.get('metric_name') or metric.get('metric_key')} 未注册可执行公式。")
        dependencies.append(f"{dependency['table']}.{dependency['field']}")
        fields.append(str(dependency["field"]))
    return {"metric": metric.get("metric_key"), "required_table": None,
            "formula_id": " / ".join(fields), "dependencies": dependencies}


def _normalized_thresholds(filters: list[dict[str, Any]], metrics: list[dict[str, Any]]) -> list[Threshold]:
    thresholds: list[Threshold] = []
    for item in filters:
        value = item.get("value")
        if item.get("operator") not in {"=", "!=", "<>", ">", ">=", "<", "<="} or not isinstance(value, (int, float)):
            continue
        metric = _metric_by_mention(metrics, item.get("metric"))
        metric_name = str(item.get("metric") or "").lower()
        # 同比在事实层固定为小数比例，即使来源指标本身是金额单位。
        # Planner 的“5%”必须在合同阶段一次性归一化为 0.05。
        unit = "percent" if ("同比" in metric_name or "yoy" in metric_name) else (str(metric.get("unit")) if metric else "number")
        normalized = value / 100 if unit == "percent" and abs(value) > 1 else value
        thresholds.append({"metric": str(item.get("metric") or ""), "operator": item["operator"],
                           "user_value": value, "unit": unit, "normalized_value": normalized})
    return thresholds


def build_semantic_sql_contract(
    query_spec: dict[str, Any], metrics: list[dict[str, Any]], spec: FlexibleSQLSpec
) -> SemanticSQLContract:
    """从已标准化指标生成唯一的表、字段、公式、阈值与阶段约束。"""
    from agent.tools.metric_tools import load_metric_dictionary

    metric_dictionary = load_metric_dictionary()
    mentioned = list(dict.fromkeys(
        _as_text_list(query_spec.get("metrics"))
        + [str(item.get("metric")) for item in _as_dict_list(query_spec.get("filters")) if item.get("metric")]
        + [str(item.get("metric")) for item in _as_dict_list(query_spec.get("sort")) if item.get("metric")]
        + [str(item.get("metric")) for item in _as_dict_list(query_spec.get("set_operations")) if item.get("metric")]
    ))
    sources = [_formula_contract(metric, metric_dictionary) for name in mentioned if (metric := _metric_by_mention(metrics, name))]
    dependencies = sorted({item for source in sources for item in source["dependencies"]})
    tables = sorted({item.rsplit(".", 1)[0] for item in dependencies})
    time_scope = _as_dict(query_spec.get("time_scope"))
    year = _as_optional_int(time_scope.get("year") or time_scope.get("report_year"))
    derived_sources = [source for source in sources if source.get("formula_id")]
    return {
        "required_tables": tables,
        "required_columns": dependencies,
        "metric_formula_id": derived_sources[0]["formula_id"] if len(derived_sources) == 1 else None,
        "formula_dependencies": [item for source in derived_sources for item in source["dependencies"]],
        "time_periods": [year] if year is not None else [],
        "report_period": str(time_scope.get("period") or "FY"),
        "normalized_thresholds": _normalized_thresholds(_as_dict_list(query_spec.get("filters")), metrics),
        "required_filters": _as_dict_list(query_spec.get("filters")),
        "required_sort": _as_dict_list(query_spec.get("sort")),
        "required_limit": _as_optional_int(query_spec.get("limit")),
        "stages": list(spec.get("stages") or []),
        "metric_sources": sources,
    }


def validate_flexible_sql_support(query_spec: dict[str, Any], metrics: list[dict[str, Any]]) -> str | None:
    """仅允许 V1 正式支持的三类 Flexible SQL 结构。"""
    operation = str(query_spec.get("operation") or "")
    set_operations = _as_dict_list(query_spec.get("set_operations"))
    if operation == "nested_top_n" or any(item.get("input") for item in set_operations if item.get("type") == "top_n"):
        return "暂不支持任意嵌套 Top N。"
    if set_operations:
        top_n = [item for item in set_operations if item.get("type") == "top_n"]
        intersections = [item for item in set_operations if item.get("type") == "intersection"]
        if len(set_operations) != 3 or len(top_n) != 2 or len(intersections) != 1:
            return "暂不支持任意多阶段集合运算，仅支持两个 Top N 的单次交集。"
        outputs = {str(item.get("output")) for item in top_n if item.get("output")}
        inputs = set(_as_text_list(intersections[0].get("inputs")))
        if any(not isinstance(item.get("n"), int) or item["n"] <= 0 for item in top_n) or inputs != outputs:
            return "Top N 交集必须由两个明确的 Top N 阶段及其输出组成。"
    if query_spec.get("derived_expressions"):
        return "暂不支持未注册公式的自由派生指标。"
    for metric in metrics:
        if metric.get("metric_type") == "derived":
            formula = metric.get("formula")
            if not isinstance(formula, dict) or not formula.get("numerator") or not formula.get("denominator"):
                return "暂不支持未注册公式的自由派生指标。"
    return None


def _compile_stages(set_operations: list[dict[str, Any]]) -> list[StageSpec]:
    """将集合和嵌套 Top N 编译为有作用域的阶段。"""
    stages: list[StageSpec] = []
    for index, item in enumerate(set_operations, start=1):
        operation = item.get("type") if isinstance(item.get("type"), str) else "unknown"
        stage: StageSpec = {
            "stage_id": item.get("output") if isinstance(item.get("output"), str) else (
                "intersection_stage" if operation == "intersection" else f"stage_{index}"
            ),
            "operation": operation,
        }
        input_stage = item.get("input")
        if isinstance(input_stage, str) and input_stage:
            stage["input_stage"] = input_stage
        inputs = _as_text_list(item.get("inputs"))
        if inputs:
            stage["inputs"] = inputs
        metric = item.get("metric") or item.get("metric_name")
        if isinstance(metric, str) and metric:
            stage["metric"] = metric
        limit = _as_optional_int(item.get("n") if "n" in item else item.get("limit"))
        if limit is not None:
            stage["limit"] = limit
        stage["partition"] = _as_text_list(item.get("partition") or item.get("partition_by"))
        stage["order"] = item.get("direction") if item.get("direction") in {"asc", "desc"} else "desc"
        if operation == "top_n":
            stage["exclude_null_metric"] = True
        stages.append(stage)
    return stages


def flexible_sql_spec_from_requirement(
    *,
    question: str,
    requirement: dict[str, Any],
    metrics: list[dict[str, Any]],
    allowed_tables: list[str],
) -> FlexibleSQLSpec:
    """从旧 requirement 兼容生成正式 FlexibleSQLSpec。"""
    report_year = requirement.get("report_year")
    report_period = requirement.get("report_period")
    metric_mentions = _metric_mentions(requirement)
    base_universe = _as_dict(requirement.get("base_universe"))
    order_by = _as_dict(requirement.get("order_by"))
    query_spec = _as_dict(requirement.get("query_spec"))

    ranking_rules: list[RankingSpec] = []
    if base_universe.get("type") in {"ranking", "intersection"}:
        ranking_rules.append(
            {
                "metric": base_universe.get("metric_mention") if isinstance(base_universe.get("metric_mention"), str) else None,
                "direction": base_universe.get("rank_direction") or "desc",
                "limit": _as_optional_int(base_universe.get("limit")),
                "partition_by": [],
                "output": None,
            }
        )

    if order_by:
        ordering = [
            {
                "metric": order_by.get("metric_mention") if isinstance(order_by.get("metric_mention"), str) else None,
                "field": None,
                "direction": order_by.get("direction") or "desc",
            }
        ]
    else:
        ordering = []

    return {
        "question": question,
        "output_columns": [
            {"name": "stock_code", "source": "company_dim", "role": "identity"},
            {"name": "stock_abbr", "source": "company_dim", "role": "identity"},
            {"name": "company_name", "source": "company_dim", "role": "identity"},
            {"name": "report_year", "source": None, "role": "time"},
            *[
                {"name": mention, "source": None, "role": "metric"}
                for mention in metric_mentions
            ],
        ],
        "source_tables": _source_tables_from_metrics(metrics) or sorted(allowed_tables),
        "joins": [],
        "filters": [
            {
                "metric": item.get("metric_mention") or item.get("metric"),
                "field": item.get("field"),
                "operator": item.get("operator") or "=",
                "value": item.get("value"),
                "calculation": item.get("calculation"),
            }
            for item in _as_dict_list(requirement.get("filters"))
        ],
        "ranking_rules": ranking_rules,
        "set_operations": _as_dict_list(requirement.get("set_operations")) or _as_dict_list(query_spec.get("set_operations")),
        "derived_metrics": _as_dict_list(requirement.get("derived_metrics")) or _as_dict_list(query_spec.get("derived_expressions")),
        "time_constraints": [
            {"year": report_year if isinstance(report_year, int) else None, "period": report_period, "field": "report_year"}
        ],
        "grouping": _as_text_list(requirement.get("grouping")) or _as_text_list(query_spec.get("group_by")),
        "ordering": ordering,
        "limit": _as_optional_int(requirement.get("limit")),
        "expected_grain": (_as_dict(requirement.get("expected_output")).get("grain") or "company"),
        "expected_result_shape": requirement.get("expected_result_shape") or "table",
    }


def flexible_sql_spec_from_query_spec(
    query_spec: dict[str, Any],
    metrics: list[dict[str, Any]],
    allowed_tables: list[str],
    companies: list[dict[str, Any]] | None = None,
) -> FlexibleSQLSpec:
    """将已规范化 QuerySpec 确定性编译为 FlexibleSQLSpec。"""
    time_scope = _as_dict(query_spec.get("time_scope"))
    metric_mentions = _as_text_list(query_spec.get("metrics"))
    set_operations = _as_dict_list(query_spec.get("set_operations"))
    for item in [*_as_dict_list(query_spec.get("filters")), *_as_dict_list(query_spec.get("sort")), *set_operations]:
        mention = item.get("metric") or item.get("metric_name")
        if isinstance(mention, str) and mention.strip():
            metric_mentions.append(mention.strip())
    stages = _compile_stages(set_operations)
    operation = query_spec.get("operation") if isinstance(query_spec.get("operation"), str) else "structured_query"
    display_limit = _as_optional_int(query_spec.get("limit"))
    if display_limit is None and operation == "nested_top_n":
        top_n_stages = [stage for stage in stages if stage.get("operation") == "top_n" and isinstance(stage.get("limit"), int)]
        display_limit = top_n_stages[-1]["limit"] if top_n_stages else None
    return {
        "question": "",
        "operation": operation,
        "stages": stages,
        "final_order": _as_dict_list(query_spec.get("sort")),
        "display_limit": display_limit,
        "entity_constraints": [
            {"stock_code": str(company["stock_code"])}
            for company in (companies or [])
            if isinstance(company.get("stock_code"), str) and company["stock_code"]
        ],
        "output_columns": [{"name": name, "source": None, "role": "metric"} for name in list(dict.fromkeys(metric_mentions))],
        "source_tables": _source_tables_from_metrics(metrics) or sorted(allowed_tables),
        "joins": [], "filters": _as_dict_list(query_spec.get("filters")),
        "ranking_rules": [], "set_operations": set_operations,
        "derived_metrics": _as_dict_list(query_spec.get("derived_expressions")),
        "time_constraints": [{"year": _as_optional_int(time_scope.get("year")), "period": time_scope.get("period"), "field": "report_year"}],
        "grouping": _as_text_list(query_spec.get("group_by")),
        "ordering": _as_dict_list(query_spec.get("sort")), "limit": _as_optional_int(query_spec.get("limit")),
        "expected_grain": "company", "expected_result_shape": "table",
    }


def compile_flexible_sql_spec(
    query_spec: dict[str, Any],
    resolved_entities: list[dict[str, Any]],
    resolved_metrics: list[dict[str, Any]],
    schema_registry: dict[str, Any],
) -> FlexibleSQLSpec:
    """将规范化语义编译为 FlexibleSQLSpec，不读取运行时历史状态。"""
    if not isinstance(query_spec, dict) or not query_spec:
        raise ValueError("缺少 QuerySpec，无法编译 FlexibleSQLSpec。")
    if not isinstance(schema_registry, dict) or not schema_registry:
        raise ValueError("缺少 Schema Registry，无法编译 FlexibleSQLSpec。")

    metric_tables = _source_tables_from_metrics(resolved_metrics)
    unknown_tables = sorted(set(metric_tables) - set(schema_registry))
    if unknown_tables:
        raise ValueError(f"指标引用了未注册数据表：{', '.join(unknown_tables)}")
    unsupported_reason = validate_flexible_sql_support(query_spec, resolved_metrics)
    if unsupported_reason:
        raise ValueError(f"UNSUPPORTED_FLEXIBLE_SQL: {unsupported_reason}")

    spec = flexible_sql_spec_from_query_spec(
        query_spec,
        resolved_metrics,
        sorted(schema_registry),
        resolved_entities,
    )
    spec["semantic_contract"] = build_semantic_sql_contract(query_spec, resolved_metrics, spec)
    return spec


__all__ = [
    "DerivedExpression",
    "ExpectedResultShape",
    "FilterSpec",
    "FlexibleSQLSpec",
    "JoinSpec",
    "OrderSpec",
    "OutputColumn",
    "RankingSpec",
    "SemanticSQLContract",
    "SetOperationSpec",
    "StageSpec",
    "TimeConstraint",
    "compile_flexible_sql_spec",
    "build_semantic_sql_contract",
    "validate_flexible_sql_support",
    "flexible_sql_spec_from_requirement",
    "flexible_sql_spec_from_query_spec",
]
