"""受约束的 LLM 综合回答节点。"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from agent.nodes.final_answer_formatter import format_llm_answer_response
from agent.nodes.answer_assembler import assemble_contract_answer, validate_assembled_answer_sections
from agent.nodes.deterministic_table_renderer import render_deterministic_table
from agent.nodes.result_context_builder import build_answer_context
from agent.nodes.result_contract_builder import build_result_contract
from agent.services.llm_json_service import invoke_json_prompt
from agent.validators.answer_validator import validate_llm_answer_narrative


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_prompt() -> str:
    return (PROJECT_ROOT / "agent" / "prompts" / "llm_answer_synthesis.md").read_text(encoding="utf-8")


def _build_prompt(answer_context: dict[str, Any], result_contract: dict[str, Any]) -> str:
    payload = {
        "answer_context": {
            "original_question": answer_context.get("original_question"),
            "result_quality": answer_context.get("result_quality"),
            "metric_metadata": answer_context.get("metric_metadata"),
        },
        "result_contract": deepcopy(result_contract),
        "constraints": {
            "output_json_only": True,
            "do_not_generate_sql": True,
            "do_not_modify_results": True,
            "do_not_generate_table": True,
            "narrative_only": True,
        },
    }
    return _load_prompt() + "\n\n输入：\n" + json.dumps(payload, ensure_ascii=False, indent=2)


def _execution_failed(state: dict[str, Any]) -> str | None:
    if state.get("need_clarification"):
        return state.get("clarification_question") or "查询条件需要澄清。"
    if state.get("query_type") == "composite" and state.get("composite_success") is False:
        failed_task_id = None
        analysis = state.get("composite_analysis_result")
        if isinstance(analysis, dict):
            failed_task_id = analysis.get("failed_task_id")
        reason = state.get("composite_error_type") or "composite_task_failed"
        return f"复合查询任务 {failed_task_id or 'unknown'} 未成功完成，错误类型：{reason}。"
    if state.get("sql_generation_error_type") in {
        "SQL_UNSAFE",
        "SQL_FIELD_NOT_ALLOWED",
        "SQL_TABLE_NOT_ALLOWED",
        "SQL_SEMANTIC_INVALID",
        "YOY_MISSING_PREVIOUS_YEAR",
        "LLM_SQL_VALIDATION_FAILED",
    }:
        return state.get("sql_generation_error_message") or state.get("clarification_question") or "SQL 校验未通过。"
    query_result = state.get("query_result")
    if isinstance(query_result, dict) and query_result.get("success") is False:
        return query_result.get("error") or "SQL 执行失败。"
    return None


def _error_result(message: str, error_type: str, answer_context: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "answer_mode": "llm_answer",
        "final_answer": message,
        "business_success": False,
        "answer_context": answer_context,
        "answer_error_type": error_type,
        "answer_validation": {"is_valid": False, "error_type": error_type, "error_message": message},
        "error_type": error_type,
    }


def _fallback_response(answer_context: dict[str, Any], deterministic_table: dict[str, Any]) -> dict[str, Any]:
    quality = answer_context.get("result_quality") if isinstance(answer_context.get("result_quality"), dict) else {}
    is_empty = bool(quality.get("is_empty"))
    return {
        "answer_type": "empty_result" if is_empty else "table_with_summary",
        "title": "查询结果",
        "summary": "未查询到符合条件的公司。" if is_empty else "根据数据库查询结果，符合条件的公司如下。",
        "table": deterministic_table,
        "key_findings": [],
        "method_note": "本回答基于已执行查询结果自动生成。",
        "data_note": "表格数据来自结构化查询结果。",
        "warnings": quality.get("warnings") if isinstance(quality.get("warnings"), list) else [],
    }


def _merge_llm_response(raw_response: dict[str, Any], deterministic_table: dict[str, Any], answer_context: dict[str, Any]) -> dict[str, Any]:
    quality = answer_context.get("result_quality") if isinstance(answer_context.get("result_quality"), dict) else {}
    merged = dict(raw_response)
    if quality.get("is_empty"):
        merged["answer_type"] = "empty_result"
    elif merged.get("answer_type") not in {"ranking_table", "table_with_summary", "single_value"}:
        merged["answer_type"] = "table_with_summary"
    merged["table"] = deterministic_table
    return merged


def _llm_table_validation(raw_response: object, answer_context: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(raw_response, dict):
        return None
    table = raw_response.get("table")
    if not isinstance(table, dict):
        return None
    rows = table.get("rows")
    if not isinstance(rows, list) or not rows:
        return None
    validation = validate_llm_answer_response(raw_response, answer_context)
    return None if validation.get("is_valid") else validation


def _fallback_result(
    *,
    answer_context: dict[str, Any],
    deterministic_table: dict[str, Any],
    raw_response: object,
    validation: dict[str, Any],
) -> dict[str, Any]:
    fallback = _fallback_response(answer_context, deterministic_table)
    final_validation = validate_llm_answer_response(fallback, answer_context)
    return {
        "answer_mode": "deterministic_fallback",
        "answer_context": answer_context,
        "deterministic_table": deterministic_table,
        "table_source": "result_rows",
        "llm_answer_raw_response": raw_response,
        "llm_answer_parsed": fallback,
        "llm_answer_failed": True,
        "answer_validation": validation,
        "llm_answer_validation": validation,
        "final_answer_validation": final_validation,
        "answer_error_type": validation.get("error_type") or "ANSWER_VALIDATION_FAILED",
        "final_answer": format_llm_answer_response(fallback),
        "business_success": not ((answer_context.get("result_quality") or {}).get("is_empty")),
        "error_type": None,
    }


def llm_answer_synthesis_node(state: dict[str, Any]) -> dict[str, Any]:
    """只基于已执行结构化结果生成最终回答。"""
    execution = state.get("execution") if isinstance(state.get("execution"), dict) else {}
    result = state.get("result") if isinstance(state.get("result"), dict) else {}
    answer_context = state.get("answer_context") if isinstance(state.get("answer_context"), dict) else build_answer_context(state, execution=execution, result=result)
    result_contract = result.get("result_contract") if isinstance(result.get("result_contract"), dict) else build_result_contract(state, execution=execution, result=result)
    deterministic_table = state.get("deterministic_table") if isinstance(state.get("deterministic_table"), dict) else render_deterministic_table(result_contract)
    answer_context = {
        **answer_context,
        "result_contract": result_contract,
        "generated_table": {
            "columns": deterministic_table.get("columns"),
            "rows_preview": (deterministic_table.get("rows") or [])[:5],
            "row_count": deterministic_table.get("row_count"),
            "source": deterministic_table.get("source"),
        },
        "result_rows_preview": (answer_context.get("result_rows") or [])[:5],
    }

    failure = _execution_failed(state)
    if failure:
        return _error_result(f"查询未成功完成：{failure}", state.get("sql_generation_error_type") or "QUERY_EXECUTION_FAILED", answer_context)

    try:
        raw_response = invoke_json_prompt(_build_prompt(answer_context, result_contract), profile="narrative")
    except Exception as exc:
        raw_response = {
            "answer_type": "empty_result" if result_contract.get("row_count") == 0 else "table_with_summary",
            "title": "查询结果",
            "summary": "未查询到符合条件的记录。" if result_contract.get("row_count") == 0 else "根据结构化查询结果，符合条件的记录如下。",
            "key_findings": [],
            "method_note": "本回答基于已执行查询结果自动生成。",
            "data_note": "表格数据由系统根据查询结果确定性渲染。",
            "warnings": [f"LLM 摘要生成失败：{exc}"],
        }

    if not isinstance(raw_response, dict):
        raw_response = _fallback_response(answer_context, deterministic_table)

    narrative_validation = validate_llm_answer_narrative(raw_response, answer_context)
    original_narrative_validation = narrative_validation
    llm_answer_failed = False
    if not narrative_validation.get("is_valid"):
        llm_answer_failed = True
        raw_response = _fallback_response(answer_context, deterministic_table)
        fallback_narrative_validation = validate_llm_answer_narrative(raw_response, answer_context)
    else:
        fallback_narrative_validation = narrative_validation

    final_response = {**raw_response, "table": deterministic_table}
    final_answer = assemble_contract_answer(
        result_contract=result_contract,
        deterministic_table=deterministic_table,
        narrative=raw_response,
    )
    assembly_validation = validate_assembled_answer_sections(
        result_contract=result_contract,
        deterministic_table=deterministic_table,
        final_answer=final_answer,
    )

    return {
        "answer_mode": "llm_answer",
        "answer_context": answer_context,
        "result_contract": result_contract,
        "deterministic_table": deterministic_table,
        "table_source": "result_rows",
        "llm_answer_raw_response": raw_response,
        "llm_answer_parsed": final_response,
        "answer_validation": assembly_validation,
        "llm_answer_validation": original_narrative_validation,
        "final_narrative_validation": fallback_narrative_validation,
        "final_answer_validation": assembly_validation,
        "answer_validation_passed": assembly_validation.get("is_valid") is True,
        "llm_answer_failed": llm_answer_failed,
        "answer_error_type": assembly_validation.get("error_type"),
        "final_answer": final_answer,
        "business_success": result_contract.get("row_count", 0) > 0,
        "error_type": assembly_validation.get("error_type"),
    }


__all__ = ["llm_answer_synthesis_node"]
