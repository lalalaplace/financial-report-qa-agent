"""从查询结果生成展示合同。"""

from __future__ import annotations

from typing import Any

from agent.nodes.result_context_builder import build_answer_context
from agent.schemas.result_contract import ResultContract


DEFAULT_MAX_DISPLAY_ROWS = 50
KEY_COLUMN_CANDIDATES = ("rank", "stock_code", "stock_abbr", "company_name", "report_year")


def _result_shape(state: dict[str, Any], rows: list[dict[str, Any]], columns: list[str]) -> str:
    if not rows:
        return "filtered_table"
    if any(column == "rank" for column in columns):
        return "ranking"
    if len(rows) == 1 and any(column in columns for column in ("stock_code", "company_name")):
        return "single_entity"
    if "report_year" in columns and len({row.get("report_year") for row in rows}) > 1:
        return "time_series"
    if state.get("intent_type") in {"company_compare_query", "company_compare_yoy_query", "company_compare_trend_query"}:
        return "comparison"
    return "filtered_table"


def _numeric_semantic(column: str, metrics: list[dict[str, Any]]) -> dict[str, Any]:
    for metric in metrics:
        if not isinstance(metric, dict):
            continue
        names = {str(metric.get(key)) for key in ("metric_key", "metric_name", "field") if metric.get(key)}
        if column not in names:
            continue
        unit = metric.get("unit")
        if unit == "percent":
            # 派生比率由 SQL 分子/分母公式计算，事实层固定为小数比例；
            # 字典中的 scale=100 是展示规则，不能当作该 SQL 结果的存储尺度。
            if metric.get("metric_type") == "derived" and metric.get("formula"):
                return {
                    "value_kind": "percentage",
                    "storage_scale": "fraction",
                    "display_precision": metric.get("display_precision", 2),
                    "display_unit": "raw",
                }
            return {
                "value_kind": metric.get("value_kind") or "percentage",
                "storage_scale": metric.get("storage_scale") or ("percent" if metric.get("scale") == 100 else "fraction"),
                "display_precision": metric.get("display_precision", 2),
                "display_unit": "raw",
            }
        return {
            "value_kind": metric.get("value_kind") or ("currency" if unit == "yuan" else "raw_number"),
            "storage_scale": metric.get("storage_scale") or "unit",
            "display_precision": metric.get("display_precision", 2),
            "display_unit": metric.get("display_unit") or "raw",
        }
    return {"value_kind": "raw_number", "storage_scale": "unit", "display_precision": 2, "display_unit": "raw"}


def _display_value(value: Any, semantic: dict[str, Any]) -> Any:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return value
    try:
        number = float(value)
    except (TypeError, ValueError):
        return value
    precision = semantic.get("display_precision", 2)
    if semantic.get("value_kind") == "percentage":
        scaled = number * 100 if semantic.get("storage_scale") == "fraction" else number
        return f"{scaled:.{precision}f}%"
    if semantic.get("value_kind") == "percentage_point":
        return f"{number:.{precision}f} 个百分点"
    if semantic.get("value_kind") == "currency" and semantic.get("display_unit") == "hundred_million_yuan":
        return f"{number / 100_000_000:.{precision}f} 亿元"
    return value


def _column_definitions(
    columns: list[str],
    metrics: list[dict[str, Any]],
    rows: list[dict[str, Any]],
) -> list[dict[str, str]]:
    definitions: list[dict[str, str]] = []
    for column in columns:
        role = "key" if column in KEY_COLUMN_CANDIDATES else "measure"
        value_type = "number"
        if column in {"stock_code", "stock_abbr", "company_name"}:
            value_type = "text"
        semantic = _numeric_semantic(column, metrics)
        definitions.append(
            {
                "name": column,
                "display_name": column,
                "role": role,
                "value_type": value_type,
                "numeric_semantic": semantic,
            }
        )
    return definitions


def build_result_contract(state: dict[str, Any], *, execution: dict[str, Any] | None = None, result: dict[str, Any] | None = None, max_display_rows: int = DEFAULT_MAX_DISPLAY_ROWS) -> ResultContract:
    """生成回答链路共享的数据合同。"""
    execution = execution if execution is not None else (state.get("execution") if isinstance(state.get("execution"), dict) else {})
    result = result if result is not None else (state.get("result") if isinstance(state.get("result"), dict) else {})
    answer_context = build_answer_context(state, execution=execution, result=result)
    rows = [dict(row) for row in answer_context.get("result_rows") or [] if isinstance(row, dict)]
    columns = list(rows[0].keys()) if rows else []
    quality = answer_context.get("result_quality") if isinstance(answer_context.get("result_quality"), dict) else {}
    row_count = quality.get("row_count") if isinstance(quality.get("row_count"), int) else len(rows)
    display_columns = [column for column in KEY_COLUMN_CANDIDATES if column in columns]
    display_columns.extend(column for column in columns if column not in display_columns)
    result_truncated = bool(quality.get("is_truncated")) or row_count > max_display_rows
    metrics = [metric for metric in state.get("metrics") or [] if isinstance(metric, dict)]
    column_contracts = _column_definitions(columns, metrics, rows)
    numeric_semantics = {item["name"]: item["numeric_semantic"] for item in column_contracts}
    evidence_rows = rows[:max_display_rows]
    display_rows = [{column: _display_value(row.get(column), numeric_semantics[column]) for column in display_columns} for row in evidence_rows]
    observations = [f"共有 {row_count} 条符合条件的记录。"] if row_count else ["未查询到符合条件的记录。"]
    return {
        "result_shape": _result_shape(state, rows, columns),
        "row_count": row_count,
        "columns": column_contracts,
        "display_columns": display_columns,
        "key_columns": [column for column in KEY_COLUMN_CANDIDATES if column in columns],
        "must_render_table": row_count > 0,
        "max_display_rows": max_display_rows,
        "result_truncated": result_truncated,
        "summary_allowed": True,
        "analysis_allowed": row_count > 0,
        "evidence_rows": evidence_rows,
        "display_rows": display_rows,
        "numeric_semantics": numeric_semantics,
        "ordering": [item for item in (state.get("query_spec") or {}).get("sort", []) if isinstance(item, dict)],
        "truncation": {"is_truncated": result_truncated, "max_display_rows": max_display_rows},
        "deterministic_observations": observations,
    }


def build_result_contract_node(state: dict[str, Any]) -> dict[str, Any]:
    return {"result_contract": build_result_contract(state)}


__all__ = ["DEFAULT_MAX_DISPLAY_ROWS", "build_result_contract", "build_result_contract_node"]
