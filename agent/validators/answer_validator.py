"""LLM 综合回答校验器。"""

from __future__ import annotations

import re
from typing import Any


ALLOWED_ANSWER_TYPES = {
    "single_value",
    "ranking_table",
    "table_with_summary",
    "empty_result",
    "error_explanation",
}

IDENTITY_FIELDS = ("stock_code", "company_name", "stock_abbr", "公司", "公司名称")
UNSUPPORTED_NARRATIVE_TERMS = ("可能受", "原因是", "导致", "由于", "行业周期", "业务结构调整", "预测", "未来走势")


def _as_dict(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _as_list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _row_identity(row: dict[str, Any]) -> tuple[str, ...]:
    return tuple(str(row.get(field)) for field in IDENTITY_FIELDS if row.get(field) is not None)


def _result_identities(rows: list[dict[str, Any]]) -> set[str]:
    identities: set[str] = set()
    for row in rows:
        for value in _row_identity(row):
            identities.add(value)
    return identities


def _value_allowed(value: Any, source_row: dict[str, Any]) -> bool:
    if value is None:
        return True
    if value in {"-", "无法计算", "无数据"}:
        return True
    if value in source_row.values():
        return True
    text = str(value)
    for source_value in source_row.values():
        if source_value is None:
            continue
        source_text = str(source_value)
        if text == source_text or source_text in text:
            return True
        try:
            number = float(source_value)
        except (TypeError, ValueError):
            continue
        candidates = {
            f"{number:.2f}",
            f"{number * 100:.2f}%",
            f"{number / 100_000_000:.2f}",
            f"{number / 100_000_000:,.2f}",
            f"{number / 100_000_000:,.2f} 亿元",
        }
        if any(candidate in text for candidate in candidates):
            return True
    return False


def _match_source_row(answer_row: dict[str, Any], result_rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    answer_identity = _row_identity(answer_row)
    if answer_identity:
        for row in result_rows:
            source_identity = set(_row_identity(row))
            if any(value in source_identity for value in answer_identity):
                return row
    if len(result_rows) == 1:
        return result_rows[0]
    return None


def _text_payload(response: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("title", "summary", "method_note", "data_note"):
        value = response.get(key)
        if isinstance(value, str):
            parts.append(value)
    for key in ("key_findings", "warnings"):
        values = response.get(key)
        if isinstance(values, list):
            parts.extend(item for item in values if isinstance(item, str))
    return "\n".join(parts)


def _narrative_valid(response: dict[str, Any], result_rows: list[dict[str, Any]], result_contract: dict[str, Any] | None = None) -> dict[str, Any] | None:
    text = _text_payload(response)
    if not text:
        return None
    for term in UNSUPPORTED_NARRATIVE_TERMS:
        if term in text:
            return {"is_valid": False, "error_type": "ANSWER_VALIDATION_FAILED", "error_message": f"回答包含无证据支持的叙述：{term}"}
    allowed = _result_identities(result_rows)
    for code in re.findall(r"\b\d{6}\b", text):
        if code not in allowed:
            return {
                "is_valid": False,
                "error_type": "ANSWER_VALIDATION_FAILED",
                "error_message": f"回答文字包含 result_rows 外的股票代码：{code}",
            }
    display_values = {
        str(value)
        for row in (result_contract or {}).get("display_rows") or []
        if isinstance(row, dict)
        for value in row.values()
    }
    for percentage in re.findall(r"-?\d+(?:\.\d+)?%", text):
        if percentage not in display_values:
            return {
                "is_valid": False,
                "error_type": "ANSWER_VALIDATION_FAILED",
                "error_message": f"回答文字包含与 ResultContract 展示值不一致的百分比：{percentage}",
            }
    return None


def validate_llm_answer_response(response: object, answer_context: dict[str, Any]) -> dict[str, Any]:
    """校验最终回答是否只基于 result_rows。"""
    if not isinstance(response, dict):
        return {"is_valid": False, "error_type": "ANSWER_VALIDATION_FAILED", "error_message": "LLM Answer 不是 JSON 对象。"}

    answer_type = response.get("answer_type")
    if answer_type not in ALLOWED_ANSWER_TYPES:
        return {"is_valid": False, "error_type": "ANSWER_VALIDATION_FAILED", "error_message": "answer_type 不合法。"}

    result_rows = [dict(row) for row in _as_list(answer_context.get("result_rows")) if isinstance(row, dict)]
    quality = _as_dict(answer_context.get("result_quality"))
    table = _as_dict(response.get("table"))
    answer_rows = [dict(row) for row in _as_list(table.get("rows")) if isinstance(row, dict)]

    if quality.get("is_empty"):
        if answer_type != "empty_result" or answer_rows:
            return {
                "is_valid": False,
                "error_type": "ANSWER_VALIDATION_FAILED",
                "error_message": "查询结果为空时不能输出非空表格。",
            }
        return {"is_valid": True, "error_type": None, "error_message": None, "answer_validation_passed": True}

    if result_rows and not answer_rows:
        return {
            "is_valid": False,
            "error_type": "ANSWER_VALIDATION_FAILED",
            "error_message": "查询结果非空时，最终表格必须包含来自 result_rows 的数据行。",
        }

    result_identities = _result_identities(result_rows)
    for answer_row in answer_rows:
        source_row = _match_source_row(answer_row, result_rows)
        if source_row is None:
            identity = _row_identity(answer_row)
            if identity and not any(value in result_identities for value in identity):
                return {
                    "is_valid": False,
                    "error_type": "ANSWER_VALIDATION_FAILED",
                    "error_message": f"回答表格包含查询结果中不存在的公司：{identity[0]}",
                }
            return {
                "is_valid": False,
                "error_type": "ANSWER_VALIDATION_FAILED",
                "error_message": "回答表格包含无法匹配到 result_rows 的行。",
            }
        for value in answer_row.values():
            if not _value_allowed(value, source_row):
                return {
                    "is_valid": False,
                    "error_type": "ANSWER_VALIDATION_FAILED",
                    "error_message": f"回答表格包含 result_rows 无法推出的值：{value}",
                }

    narrative_error = _narrative_valid(response, result_rows, _as_dict(answer_context.get("result_contract")))
    if narrative_error:
        return narrative_error

    return {
        "is_valid": True,
        "error_type": None,
        "error_message": None,
        "answer_validation_passed": True,
    }


def validate_llm_answer_narrative(response: object, answer_context: dict[str, Any]) -> dict[str, Any]:
    """只校验 LLM 叙述，不要求 LLM 生成表格行。"""
    if not isinstance(response, dict):
        return {"is_valid": False, "error_type": "ANSWER_VALIDATION_FAILED", "error_message": "LLM Answer 不是 JSON 对象。"}
    answer_type = response.get("answer_type")
    if answer_type not in ALLOWED_ANSWER_TYPES:
        return {"is_valid": False, "error_type": "ANSWER_VALIDATION_FAILED", "error_message": "answer_type 不合法。"}
    result_rows = [dict(row) for row in _as_list(answer_context.get("result_rows")) if isinstance(row, dict)]
    narrative_error = _narrative_valid(response, result_rows, _as_dict(answer_context.get("result_contract")))
    if narrative_error:
        return narrative_error
    return {
        "is_valid": True,
        "error_type": None,
        "error_message": None,
        "answer_validation_passed": True,
    }


__all__ = ["validate_llm_answer_response", "validate_llm_answer_narrative"]
