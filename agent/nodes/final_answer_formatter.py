"""把 LLM Answer JSON 格式化为 final_answer 字符串。"""

from __future__ import annotations

from typing import Any


RATE_FIELD_HINTS = ("rate", "ratio", "margin", "同比", "率")
AMOUNT_FIELD_HINTS = ("revenue", "profit", "assets", "amount", "收入", "利润", "资产", "金额")


def _is_rate_field(column: str) -> bool:
    lower = column.lower()
    return any(hint in lower or hint in column for hint in RATE_FIELD_HINTS)


def _is_amount_field(column: str) -> bool:
    lower = column.lower()
    return any(hint in lower or hint in column for hint in AMOUNT_FIELD_HINTS)


def _format_value(column: str, value: Any) -> str:
    if value is None:
        return "无法计算"
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, str):
        return value
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if column.lower() == "report_year":
        return str(int(number)) if number.is_integer() else str(value)
    if _is_rate_field(column):
        return f"{number * 100:.2f}%"
    if _is_amount_field(column) and abs(number) >= 10_000_000:
        return f"{number / 100_000_000:,.2f} 亿元"
    return f"{number:,.2f}"


def _sort_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if all(isinstance(row.get("rank"), int) for row in rows):
        return sorted(rows, key=lambda row: row.get("rank"))
    return rows


def _format_table(table: dict[str, Any]) -> list[str]:
    columns = table.get("columns") if isinstance(table.get("columns"), list) else []
    rows = table.get("rows") if isinstance(table.get("rows"), list) else []
    dict_rows = [dict(row) for row in rows if isinstance(row, dict)]
    if not columns and dict_rows:
        columns = list(dict_rows[0].keys())
    if not columns or not dict_rows:
        return []
    lines = [
        "| " + " | ".join(str(column) for column in columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for row in _sort_rows(dict_rows):
        lines.append("| " + " | ".join(_format_value(str(column), row.get(column)) for column in columns) + " |")
    return lines


def format_llm_answer_response(response: dict[str, Any]) -> str:
    """格式化校验后的 LLM Answer。"""
    parts: list[str] = []
    title = response.get("title")
    if isinstance(title, str) and title.strip():
        parts.append(title.strip())
    summary = response.get("summary")
    if isinstance(summary, str) and summary.strip():
        parts.append(summary.strip())

    table = response.get("table") if isinstance(response.get("table"), dict) else {}
    table_lines = _format_table(table)
    if table_lines:
        parts.append("\n".join(table_lines))

    key_findings = response.get("key_findings")
    if isinstance(key_findings, list) and key_findings:
        findings = [item for item in key_findings if isinstance(item, str) and item.strip()]
        if findings:
            parts.append("关键发现：\n" + "\n".join(f"- {item}" for item in findings))

    method_note = response.get("method_note")
    if isinstance(method_note, str) and method_note.strip():
        parts.append(f"方法说明：{method_note.strip()}")

    data_note = response.get("data_note")
    if isinstance(data_note, str) and data_note.strip():
        parts.append(f"数据说明：{data_note.strip()}")

    warnings = response.get("warnings")
    if isinstance(warnings, list) and warnings:
        warning_items = [item for item in warnings if isinstance(item, str) and item.strip()]
        if warning_items:
            parts.append("注意事项：\n" + "\n".join(f"- {item}" for item in warning_items))

    return "\n\n".join(part for part in parts if part).strip()


__all__ = ["format_llm_answer_response"]
