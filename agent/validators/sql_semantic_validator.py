"""受控 LLM SQL 的业务语义校验。"""

from __future__ import annotations

import re
from typing import Any


def _reject(error_type: str, message: str) -> dict[str, Any]:
    return {
        "is_valid": False,
        "error_type": error_type,
        "error_message": message,
        "semantic_guard_passed": False,
    }


def _mapped_metric_fields(metrics: list[dict[str, Any]]) -> set[str]:
    fields: set[str] = set()
    for metric in metrics:
        table = metric.get("table")
        field = metric.get("field")
        if table and field:
            fields.add(str(field).lower())
            fields.add(f"{table}.{field}".lower())
    return fields


def _sql_has_yoy_formula(sql_lower: str) -> bool:
    has_zero_guard = bool(
        re.search(r"nullif\s*\([^,]+,\s*0\s*\)", sql_lower)
        or ("case" in sql_lower and re.search(r"[a-zA-Z_][a-zA-Z0-9_.]*\s*=\s*0", sql_lower))
    )
    has_abs_previous = "abs(" in sql_lower
    has_change_formula = "-" in sql_lower and "/" in sql_lower
    return has_zero_guard and has_abs_previous and has_change_formula


def _sql_scales_yoy_as_percent(sql_lower: str) -> bool:
    """同比事实层保存小数比例，展示层才转换为百分比。"""
    return bool(re.search(r"\*\s*100(?:\.0+)?\b", sql_lower))


def _validate_filter_literals(sql_lower: str, spec: dict[str, Any]) -> dict[str, Any] | None:
    """确保结构化筛选的比较符和阈值没有在 SQL 中丢失。"""
    contract = spec.get("semantic_contract") if isinstance(spec.get("semantic_contract"), dict) else {}
    contract_thresholds = contract.get("normalized_thresholds") if isinstance(contract.get("normalized_thresholds"), list) else []
    for item in spec.get("filters") or []:
        if not isinstance(item, dict):
            continue
        operator, value = item.get("operator"), item.get("value")
        if operator not in {"=", "!=", "<>", ">", ">=", "<", "<="} or not isinstance(value, (int, float)):
            continue
        metric = str(item.get("metric") or "").lower()
        normalized_value = next(
            (
                threshold.get("normalized_value")
                for threshold in contract_thresholds
                if isinstance(threshold, dict)
                and str(threshold.get("metric") or "").lower() == metric
                and threshold.get("operator") == operator
                and isinstance(threshold.get("normalized_value"), (int, float))
            ),
            None,
        )
        # 合同已完成百分比等单位归一化，旧校验不可再次按原始字面量判断。
        values = [normalized_value] if normalized_value is not None else [value / 100] if ("yoy" in metric or "同比" in metric) else [value]
        if not any(re.search(rf"{re.escape(operator)}\s*{re.escape(format(candidate, 'g'))}(?:\b|\.)", sql_lower) for candidate in values):
            return _reject("SQL_FILTER_CONSTRAINT_MISSING", f"SQL 缺少筛选条件 {operator} {value}。")
    return None


def _is_set_intersection_request(request: dict[str, Any]) -> bool:
    requirement = request.get("sql_requirement")
    requirement_type = requirement.get("requirement_type") if isinstance(requirement, dict) else None
    task_type = str(request.get("sql_task_type") or "").lower()
    spec = request.get("flexible_sql_spec") if isinstance(request.get("flexible_sql_spec"), dict) else {}
    stages = spec.get("stages") if isinstance(spec.get("stages"), list) else []
    return (
        requirement_type == "set_intersection"
        or task_type == "set_intersection"
        or spec.get("operation") == "set_intersection_ranking"
        or any(isinstance(stage, dict) and stage.get("operation") == "intersection" for stage in stages)
    )


def _metric_field(metric_name: object, request: dict[str, Any]) -> str | None:
    if not isinstance(metric_name, str) or not metric_name:
        return None
    for binding in request.get("metric_bindings") or []:
        if isinstance(binding, dict) and binding.get("metric_name") == metric_name:
            field = binding.get("field")
            return str(field).lower() if isinstance(field, str) and field else None
    return None


def _validate_top_n_null_filters(sql_lower: str, request: dict[str, Any]) -> dict[str, Any] | None:
    spec = request.get("flexible_sql_spec") if isinstance(request.get("flexible_sql_spec"), dict) else {}
    stages = spec.get("stages") if isinstance(spec.get("stages"), list) else []
    for stage in stages:
        if not isinstance(stage, dict) or stage.get("operation") != "top_n" or not stage.get("exclude_null_metric"):
            continue
        field = _metric_field(stage.get("metric"), request)
        if field and not re.search(rf"\b{re.escape(field)}\b\s+is\s+not\s+null", sql_lower):
            return _reject("SQL_SEMANTIC_INVALID", f"Top N 阶段必须在排序前过滤 {field} 为空的行。")
    return None


def _last_limit(sql_lower: str) -> int | None:
    matches = re.findall(r"\blimit\s+(\d+)", sql_lower)
    if not matches:
        return None
    return int(matches[-1])


def _validate_set_intersection_sql(sql_lower: str) -> dict[str, Any] | None:
    """校验双 Top20 交集查询不能退化为单 TopN 或默认 Top10。"""
    for field in ("total_operating_revenue", "net_profit"):
        if not re.search(rf"\b{field}\b", sql_lower):
            return _reject("SQL_SEMANTIC_INVALID", f"set_intersection SQL 必须使用 {field}。")

    top20_blocks = re.findall(r"\border\s+by\b.*?\blimit\s+20\b", sql_lower, re.DOTALL)
    if len(top20_blocks) < 2:
        return _reject("SQL_SEMANTIC_INVALID", "set_intersection SQL 必须分别构建两个 Top20 集合。")
    has_revenue_top20 = any(re.search(r"\border\s+by\b[^)]*\btotal_operating_revenue\b", block) for block in top20_blocks)
    has_profit_top20 = any(re.search(r"\border\s+by\b[^)]*\bnet_profit\b", block) for block in top20_blocks)
    if not has_revenue_top20 or not has_profit_top20:
        return _reject("SQL_SEMANTIC_INVALID", "set_intersection SQL 必须分别按营业收入和净利润构建 Top20。")

    final_limit = _last_limit(sql_lower)
    if final_limit == 10:
        return _reject("SQL_SEMANTIC_INVALID", "set_intersection 最终结果不能使用 LIMIT 10。")
    if final_limit is not None and final_limit < 20:
        return _reject("SQL_SEMANTIC_INVALID", "set_intersection 最终 LIMIT 不能小于交集基准 Top20。")

    has_intersection_join = bool(
        re.search(r"\bjoin\b[\s\S]+?\bon\b[\s\S]+?\bstock_code\b", sql_lower)
        or re.search(r"\bintersect\b", sql_lower)
        or re.search(r"\bstock_code\b\s+in\s*\(", sql_lower)
    )
    if not has_intersection_join:
        return _reject("SQL_SEMANTIC_INVALID", "set_intersection SQL 必须按 stock_code 取两个公司集合的交集。")

    if not re.search(r"\btotal_operating_revenue\b\s+is\s+not\s+null", sql_lower):
        return _reject("SQL_SEMANTIC_INVALID", "set_intersection SQL 必须过滤营业收入为空的行。")
    if not re.search(r"\bnet_profit\b\s+is\s+not\s+null", sql_lower):
        return _reject("SQL_SEMANTIC_INVALID", "set_intersection SQL 必须过滤净利润为空的行。")
    has_non_zero_revenue = bool(
        re.search(r"\btotal_operating_revenue\b\s*(?:!=|<>)\s*0", sql_lower)
        or re.search(r"\btotal_operating_revenue\b\s*>\s*0", sql_lower)
        or re.search(r"nullif\s*\([^)]*\btotal_operating_revenue\b[^)]*,\s*0\s*\)", sql_lower)
        or ("case" in sql_lower and re.search(r"\btotal_operating_revenue\b\s*=\s*0", sql_lower))
        or (
            "case" in sql_lower
            and re.search(r"[a-zA-Z_][a-zA-Z0-9_.]*revenue[a-zA-Z0-9_.]*\s*=\s*0", sql_lower)
            and "/" in sql_lower
        )
    )
    if not has_non_zero_revenue:
        return _reject("SQL_SEMANTIC_INVALID", "set_intersection SQL 必须防止营业收入为 0。")

    return None


def _validate_semantic_contract(sql_lower: str, contract: dict[str, Any]) -> dict[str, Any] | None:
    """按系统合同检查 SQL，不从 SQL 反推或补全业务语义。"""
    for table in contract.get("required_tables") or []:
        if isinstance(table, str) and not re.search(rf"\b(from|join)\s+{re.escape(table.lower())}\b", sql_lower):
            return _reject("SQL_CONTRACT_TABLE_MISSING", f"SQL 缺少合同要求的数据表：{table}。")
    for source in contract.get("metric_sources") or []:
        if not isinstance(source, dict) or not source.get("formula_id"):
            continue
        metric = str(source.get("metric") or "").lower()
        if metric and re.search(rf"\bnull\s+as\s+{re.escape(metric)}\b", sql_lower):
            return _reject("SQL_CONTRACT_FORMULA_INVALID", f"派生指标 {metric} 不得使用 NULL 占位。")
        dependencies = [item for item in source.get("dependencies") or [] if isinstance(item, str) and "." in item]
        if len(dependencies) == 2:
            numerator = dependencies[0].rsplit(".", 1)[1].lower()
            denominator = dependencies[1].rsplit(".", 1)[1].lower()
            # 字段可位于原表或 CTE 中；分子、分母都允许单层表别名，
            # 但字段名和除法顺序仍必须与合同完全一致。
            alias = r"(?:[a-z_][a-z0-9_]*\.)?"
            formula_pattern = (
                rf"{alias}\b{re.escape(numerator)}\b\s*/\s*"
                rf"(?:nullif\s*\(\s*)?(?:abs\s*\(\s*)?"
                rf"{alias}\b{re.escape(denominator)}\b"
            )
            if not re.search(formula_pattern, sql_lower):
                return _reject("SQL_CONTRACT_FORMULA_INVALID", f"派生指标 {metric} 未按合同公式 {source.get('formula_id')} 计算。")
    for qualified in contract.get("required_columns") or []:
        if not isinstance(qualified, str) or "." not in qualified:
            continue
        _, field = qualified.rsplit(".", 1)
        if not re.search(rf"\b{re.escape(field.lower())}\b", sql_lower):
            return _reject("SQL_CONTRACT_COLUMN_MISSING", f"SQL 缺少合同要求的指标字段：{qualified}。")
    for threshold in contract.get("normalized_thresholds") or []:
        if not isinstance(threshold, dict):
            continue
        operator, value = threshold.get("operator"), threshold.get("normalized_value")
        if operator and isinstance(value, (int, float)):
            literal = format(value, "g")
            if not re.search(rf"{re.escape(str(operator))}\s*{re.escape(literal)}(?:\b|\.)", sql_lower):
                return _reject("SQL_CONTRACT_THRESHOLD_MISSING", f"SQL 未使用合同归一化阈值：{operator} {literal}。")
    periods = [item for item in contract.get("time_periods") or [] if isinstance(item, int)]
    for year in periods:
        if str(year) not in sql_lower:
            return _reject("SQL_CONTRACT_TIME_MISSING", f"SQL 缺少合同年份：{year}。")
    report_period = contract.get("report_period")
    if isinstance(report_period, str) and report_period and "report_period" not in sql_lower:
        return _reject("SQL_CONTRACT_TIME_MISSING", "SQL 缺少合同报告期约束。")

    stages = [item for item in contract.get("stages") or [] if isinstance(item, dict)]
    known_stage_ids: set[str] = set()
    intersection_position = -1
    for stage in stages:
        stage_id = stage.get("stage_id")
        if not isinstance(stage_id, str) or not stage_id:
            return _reject("SQL_CONTRACT_STAGE_INVALID", "合同阶段缺少 stage_id。")
        if not re.search(rf"\b{re.escape(stage_id.lower())}\s+as\s*\(", sql_lower):
            return _reject("SQL_CONTRACT_STAGE_MISSING", f"SQL 缺少合同阶段：{stage_id}。")
        input_stage = stage.get("input_stage")
        inputs = stage.get("inputs") or []
        dependencies = [input_stage] if isinstance(input_stage, str) else [item for item in inputs if isinstance(item, str)]
        for dependency in dependencies:
            if dependency not in known_stage_ids or not re.search(rf"\b(from|join)\s+{re.escape(dependency.lower())}\b", sql_lower):
                return _reject("SQL_CONTRACT_STAGE_INVALID", f"阶段 {stage_id} 未按合同引用前序阶段 {dependency}。")
        if stage.get("operation") == "intersection":
            intersection_position = sql_lower.find(stage_id.lower())
            if not re.search(r"\bjoin\b[\s\S]+?\bon\b[\s\S]*?\bstock_code\b", sql_lower):
                return _reject("SQL_CONTRACT_STAGE_INVALID", "交集阶段必须通过 stock_code 连接。")
        known_stage_ids.add(stage_id)
    required_sort = [item for item in contract.get("required_sort") or [] if isinstance(item, dict)]
    if required_sort:
        order_position = sql_lower.rfind("order by")
        if order_position < 0 or (intersection_position >= 0 and order_position <= intersection_position):
            return _reject("SQL_CONTRACT_SORT_INVALID", "最终排序必须发生在合同规定的交集结果之后。")
    required_limit = contract.get("required_limit")
    if isinstance(required_limit, int) and _last_limit(sql_lower) != required_limit:
        return _reject("SQL_CONTRACT_LIMIT_INVALID", f"最终 LIMIT 必须为合同值 {required_limit}。")
    return None


def validate_llm_sql_semantics(
    sql: str,
    *,
    request: dict[str, Any],
    metrics: list[dict[str, Any]],
) -> dict[str, Any]:
    """校验 SQL 是否符合已标准化任务的业务约束。"""
    sql_lower = sql.lower()
    task_type = str(request.get("sql_task_type") or "").lower()
    report_year = request.get("report_year")
    report_period = request.get("report_period")
    required_fields = {str(item).lower() for item in request.get("required_output_fields") or []}
    flexible_sql_spec = request.get("flexible_sql_spec") if isinstance(request.get("flexible_sql_spec"), dict) else {}
    semantic_contract = flexible_sql_spec.get("semantic_contract") if isinstance(flexible_sql_spec.get("semantic_contract"), dict) else {}
    entity_constraints = flexible_sql_spec.get("entity_constraints") if isinstance(flexible_sql_spec.get("entity_constraints"), list) else []
    time_constraints = flexible_sql_spec.get("time_constraints") if isinstance(flexible_sql_spec.get("time_constraints"), list) else []
    if time_constraints and isinstance(time_constraints[0], dict):
        report_year = report_year if isinstance(report_year, int) else time_constraints[0].get("year")
        report_period = report_period or time_constraints[0].get("period")

    contract_error = _validate_semantic_contract(sql_lower, semantic_contract) if semantic_contract else None
    if contract_error:
        return contract_error

    if _is_set_intersection_request(request):
        set_intersection_error = _validate_set_intersection_sql(sql_lower)
        if set_intersection_error:
            return set_intersection_error

    filter_literal_error = _validate_filter_literals(sql_lower, flexible_sql_spec)
    if filter_literal_error:
        return filter_literal_error

    top_n_null_error = _validate_top_n_null_filters(sql_lower, request)
    if top_n_null_error:
        return top_n_null_error

    if report_period and "report_period" not in sql_lower:
        return _reject("SQL_SEMANTIC_INVALID", "财报查询必须显式约束 report_period。")

    mapped_fields = _mapped_metric_fields(metrics)
    if mapped_fields:
        metric_fields_in_sql = {
            field
            for field in mapped_fields
            if re.search(rf"\b{re.escape(field.split('.')[-1])}\b", sql_lower)
        }
        if not metric_fields_in_sql:
            return _reject("SQL_SEMANTIC_INVALID", "SQL 未使用已映射指标字段。")

    unknown_metric_like = re.findall(r"\b(fake_[a-zA-Z0-9_]+|[a-zA-Z0-9_]*growth[a-zA-Z0-9_]*)\b", sql_lower)
    allowed_metric_names = {field.split(".")[-1] for field in mapped_fields}
    if any(token not in allowed_metric_names for token in unknown_metric_like):
        return _reject("SQL_FIELD_NOT_ALLOWED", f"SQL 疑似使用未映射指标字段：{sorted(set(unknown_metric_like))}。")

    if "yoy" in task_type or "yoy" in sql_lower:
        if isinstance(report_year, int):
            previous_year = report_year - 1
            if str(report_year) not in sql_lower or str(previous_year) not in sql_lower:
                return _reject("YOY_MISSING_PREVIOUS_YEAR", "同比任务必须同时包含当前年和上一年。")
        if not _sql_has_yoy_formula(sql_lower):
            return _reject("SQL_SEMANTIC_INVALID", "同比 SQL 必须包含除零保护和统一同比公式。")
        if _sql_scales_yoy_as_percent(sql_lower):
            return _reject("YOY_SCALE_INVALID", "同比事实值必须保存为小数比例，禁止在 SQL 中乘以 100。")

    staged_top_n = any(
        isinstance(stage, dict) and stage.get("operation") == "top_n"
        for stage in flexible_sql_spec.get("stages") or []
    )
    if "ranking" in task_type or "top" in task_type or staged_top_n:
        if not re.search(r"\border\s+by\b", sql_lower):
            return _reject("RANKING_MISSING_ORDER_BY", "排名任务必须包含 ORDER BY。")
        if not re.search(r"\blimit\s+\d+", sql_lower):
            return _reject("SQL_SEMANTIC_INVALID", "TopN 任务必须包含 LIMIT。")

    if required_fields:
        missing_required = sorted(field for field in required_fields if field not in sql_lower)
        if missing_required and "stock_code" in missing_required:
            return _reject("SQL_SEMANTIC_INVALID", "公司集合查询必须保留 stock_code。")

    entity_codes = {
        str(item.get("stock_code"))
        for item in entity_constraints
        if isinstance(item, dict) and item.get("stock_code")
    }
    missing_entity_codes = sorted(code for code in entity_codes if code.lower() not in sql_lower)
    if missing_entity_codes:
        return _reject("SQL_SEMANTIC_INVALID", f"SQL 缺少实体约束：{missing_entity_codes}。")

    return {
        "is_valid": True,
        "error_type": None,
        "error_message": None,
        "semantic_guard_passed": True,
    }


__all__ = ["validate_llm_sql_semantics"]
