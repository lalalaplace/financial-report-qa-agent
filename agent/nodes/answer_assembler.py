"""合同驱动回答组装器。"""

from __future__ import annotations

from typing import Any

from agent.nodes.final_answer_formatter import _format_table


def _lines(value: object) -> list[str]:
    return [item for item in value if isinstance(item, str) and item.strip()] if isinstance(value, list) else []


def assemble_contract_answer(
    *,
    result_contract: dict[str, Any],
    deterministic_table: dict[str, Any],
    narrative: dict[str, Any],
) -> str:
    title = narrative.get("title") if isinstance(narrative.get("title"), str) else "查询结果"
    summary = narrative.get("summary") if isinstance(narrative.get("summary"), str) else ""
    parts: list[str] = [title.strip()]
    if summary.strip():
        parts.append(summary.strip())

    if result_contract.get("must_render_table"):
        table_lines = _format_table(deterministic_table)
        if table_lines:
            parts.append("\n".join(table_lines))
    elif result_contract.get("row_count") == 0:
        parts.append("未查询到符合条件的记录。")

    findings = _lines(narrative.get("key_findings"))
    if findings and result_contract.get("analysis_allowed"):
        parts.append("关键观察：\n" + "\n".join(f"- {item}" for item in findings))

    method_note = narrative.get("method_note")
    if isinstance(method_note, str) and method_note.strip():
        parts.append(f"查询口径：{method_note.strip()}")

    data_note = narrative.get("data_note")
    if isinstance(data_note, str) and data_note.strip():
        parts.append(f"数据说明：{data_note.strip()}")

    warnings = _lines(narrative.get("warnings"))
    if result_contract.get("result_truncated"):
        warnings.append(f"结果已截断，仅展示前 {result_contract.get('max_display_rows')} 行。")
    if warnings:
        parts.append("注意事项：\n" + "\n".join(f"- {item}" for item in warnings))

    return "\n\n".join(part for part in parts if part).strip()


def validate_assembled_answer_sections(
    *,
    result_contract: dict[str, Any],
    deterministic_table: dict[str, Any],
    final_answer: str,
) -> dict[str, Any]:
    if result_contract.get("must_render_table") and not deterministic_table.get("rows"):
        return {
            "is_valid": False,
            "error_type": "ANSWER_ASSEMBLY_FAILED",
            "error_message": "ResultContract 要求渲染表格，但确定性表格为空。",
        }
    if result_contract.get("must_render_table") and "|" not in final_answer:
        return {
            "is_valid": False,
            "error_type": "ANSWER_ASSEMBLY_FAILED",
            "error_message": "最终回答缺少结果表格。",
        }
    return {"is_valid": True, "error_type": None, "error_message": None, "answer_validation_passed": True}


__all__ = ["assemble_contract_answer", "validate_assembled_answer_sections"]
