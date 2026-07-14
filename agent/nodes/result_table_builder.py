"""基于 result_rows 确定性构造最终回答表格。"""

from __future__ import annotations

from typing import Any


DEFAULT_MAX_DISPLAY_ROWS = 50
IDENTITY_COLUMNS = ("rank", "stock_code", "stock_abbr", "company_name")
RATE_HINTS = ("rate", "ratio", "margin", "yoy", "pct", "percent", "净利率", "同比", "比率")
AMOUNT_HINTS = ("revenue", "profit", "assets", "amount", "income", "cash", "营业收入", "净利润", "金额")


def _is_rate_column(column: str) -> bool:
    lower = column.lower()
    return any(hint in lower or hint in column for hint in RATE_HINTS)


def _is_amount_column(column: str) -> bool:
    lower = column.lower()
    return any(hint in lower or hint in column for hint in AMOUNT_HINTS)


def _format_cell(column: str, value: Any, *, value_type: str | None = None) -> Any:
    if value is None:
        return "无法计算" if _is_rate_column(column) else "-"
    if isinstance(value, bool):
        return value
    try:
        number = float(value)
    except (TypeError, ValueError):
        return value
    if value_type == "percentage_points":
        return f"{number:.2f}%"
    if _is_rate_column(column):
        return f"{number * 100:.2f}%"
    if _is_amount_column(column) and abs(number) >= 10_000_000:
        return f"{number / 100_000_000:,.2f} 亿元"
    return value


def _metric_fields(answer_context: dict[str, Any]) -> list[str]:
    fields: list[str] = []
    for metric in answer_context.get("metric_metadata") or []:
        if not isinstance(metric, dict):
            continue
        for key in ("metric_key", "field", "metric_name"):
            value = metric.get(key)
            if isinstance(value, str) and value:
                fields.append(value)
    requirement = answer_context.get("llm_sql_requirement") if isinstance(answer_context.get("llm_sql_requirement"), dict) else {}
    order_by = requirement.get("order_by") if isinstance(requirement.get("order_by"), dict) else answer_context.get("order_by")
    if isinstance(order_by, dict):
        for key in ("metric_key", "field", "metric_mention"):
            value = order_by.get(key)
            if isinstance(value, str) and value:
                fields.append(value)
    for item in requirement.get("filters") or answer_context.get("filters") or []:
        if not isinstance(item, dict):
            continue
        for key in ("metric_key", "field", "metric_mention"):
            value = item.get(key)
            if isinstance(value, str) and value:
                fields.append(value)
    return list(dict.fromkeys(fields))


def _choose_columns(rows: list[dict[str, Any]], answer_context: dict[str, Any]) -> list[str]:
    if not rows:
        return []
    available = list(rows[0].keys())
    columns: list[str] = []
    for column in IDENTITY_COLUMNS:
        if column in available:
            columns.append(column)
    metric_fields = _metric_fields(answer_context)
    for wanted in metric_fields:
        for column in available:
            if column == wanted or column.lower() == wanted.lower():
                columns.append(column)
    for column in available:
        if column not in columns:
            columns.append(column)
    return list(dict.fromkeys(columns))


def build_result_table(answer_context: dict[str, Any], *, max_display_rows: int = DEFAULT_MAX_DISPLAY_ROWS) -> dict[str, Any]:
    """从 answer_context.result_rows 生成最终表格。"""
    result_rows = [dict(row) for row in answer_context.get("result_rows") or [] if isinstance(row, dict)]
    quality = answer_context.get("result_quality") if isinstance(answer_context.get("result_quality"), dict) else {}
    display_rows = result_rows[:max_display_rows]
    columns = _choose_columns(display_rows, answer_context)
    rows = [
        {column: _format_cell(column, row.get(column)) for column in columns}
        for row in display_rows
    ]
    total_count = quality.get("row_count") if isinstance(quality.get("row_count"), int) else len(result_rows)
    return {
        "columns": columns,
        "rows": rows,
        "source": "result_rows",
        "row_count": len(rows),
        "is_truncated": bool(quality.get("is_truncated")) or total_count > len(rows),
    }


def build_result_table_node(state: dict[str, Any]) -> dict[str, Any]:
    context = state.get("answer_context") if isinstance(state.get("answer_context"), dict) else {}
    table = build_result_table(context)
    return {
        "deterministic_table": table,
        "table_source": "result_rows",
    }


__all__ = ["build_result_table", "build_result_table_node"]
