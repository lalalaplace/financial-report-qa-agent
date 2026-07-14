"""构建 LLM Answer 可消费的结构化结果上下文。"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal
from typing import Any


MAX_ROWS_PASSED_TO_LLM = 50


def _json_safe_value(value: Any) -> Any:
    """将数据库返回值归一化为 JSON 可序列化值。"""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe_value(item) for item in value]
    return value


def _json_safe_dict(value: dict[str, Any]) -> dict[str, Any]:
    return {str(key): _json_safe_value(item) for key, item in value.items()}


def _rows_from_query_result(query_result: object) -> list[dict[str, Any]]:
    if not isinstance(query_result, dict):
        return []
    columns = query_result.get("columns") or []
    rows = query_result.get("rows") or []
    if not isinstance(columns, list) or not isinstance(rows, list):
        return []
    normalized: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, dict):
            normalized.append(_json_safe_dict(dict(row)))
        elif isinstance(row, (list, tuple)):
            normalized.append(_json_safe_dict(dict(zip(columns, row))))
    return normalized


def _rows_from_analysis_result(analysis_result: object) -> list[dict[str, Any]]:
    if not isinstance(analysis_result, dict):
        return []
    rows = analysis_result.get("rows")
    if isinstance(rows, list):
        return [_json_safe_dict(dict(row)) for row in rows if isinstance(row, dict)]
    return []


def _final_task_id(task_results: dict[str, Any]) -> str | None:
    if not task_results:
        return None
    return next(reversed(task_results.keys()))


def _rows_from_task_results(task_results: object, final_task_id: str | None) -> list[dict[str, Any]]:
    if not isinstance(task_results, dict) or not task_results:
        return []
    task = task_results.get(final_task_id) if final_task_id else None
    if not isinstance(task, dict):
        task = next((value for value in reversed(task_results.values()) if isinstance(value, dict)), {})
    rows = _rows_from_analysis_result(task.get("analysis_result"))
    if rows:
        return rows
    return _rows_from_query_result(task.get("query_result"))


def _null_fields(rows: list[dict[str, Any]]) -> list[str]:
    fields: set[str] = set()
    for row in rows:
        for key, value in row.items():
            if value is None:
                fields.add(str(key))
    return sorted(fields)


def _result_quality(rows: list[dict[str, Any]], total_row_count: int | None) -> dict[str, Any]:
    row_count = total_row_count if isinstance(total_row_count, int) else len(rows)
    truncated = len(rows) > MAX_ROWS_PASSED_TO_LLM or row_count > MAX_ROWS_PASSED_TO_LLM
    passed_rows = rows[:MAX_ROWS_PASSED_TO_LLM]
    warnings: list[str] = []
    nulls = _null_fields(passed_rows)
    if truncated:
        warnings.append(f"结果共 {row_count} 行，仅传入前 {MAX_ROWS_PASSED_TO_LLM} 行用于回答。")
    if nulls:
        warnings.append("部分字段为空，可能表示数据缺失、上年值为 0 或无法计算。")
    return {
        "row_count": row_count,
        "is_empty": row_count == 0 or not rows,
        "is_truncated": truncated,
        "max_rows_passed_to_llm": MAX_ROWS_PASSED_TO_LLM,
        "null_fields": nulls,
        "warnings": warnings,
    }


def _metric_metadata(metrics: object) -> list[dict[str, Any]]:
    if not isinstance(metrics, list):
        return []
    fields = ("metric_key", "metric_name", "metric_type", "unit", "scale", "precision", "formula")
    return [
        _json_safe_dict({key: metric.get(key) for key in fields if key in metric})
        for metric in metrics
        if isinstance(metric, dict)
    ]


def _execution_status(state: dict[str, Any]) -> dict[str, Any]:
    sql_validation = state.get("llm_sql_validation") or state.get("sql_review") or {}
    semantic_validation = state.get("sql_semantic_validation") or {}
    dry_run_result = state.get("dry_run_result") or {}
    return {
        "sql_generation_mode": state.get("sql_generation_mode"),
        "sql_guard_passed": bool(sql_validation.get("is_valid", sql_validation.get("is_safe", state.get("sql_generation_mode") == "template"))),
        "semantic_guard_passed": bool(semantic_validation.get("is_valid", semantic_validation.get("semantic_guard_passed", state.get("sql_generation_mode") == "template"))),
        "dry_run_passed": bool(dry_run_result.get("success", state.get("sql_generation_mode") == "template")),
    }


def _task_role(task_result: dict[str, Any]) -> str:
    task_plan = task_result.get("task_plan") if isinstance(task_result.get("task_plan"), dict) else {}
    intent = task_result.get("intent_type") or task_plan.get("intent")
    if task_plan.get("company_source") == "dependency":
        return "ranking"
    if intent == "yoy_query":
        return "yoy"
    if intent == "ranking_query":
        return "ranking"
    return "synthesis"


def _task_results_summary(task_results: object) -> list[dict[str, Any]]:
    if not isinstance(task_results, dict):
        return []
    summary: list[dict[str, Any]] = []
    for task_id, result in task_results.items():
        if not isinstance(result, dict):
            continue
        query_result = result.get("query_result") if isinstance(result.get("query_result"), dict) else {}
        analysis = result.get("analysis_result") if isinstance(result.get("analysis_result"), dict) else {}
        summary.append(
            {
                "task_id": task_id,
                "role": _task_role(result),
                "success": result.get("business_success", result.get("sql_success")),
                "sql_generation_mode": result.get("sql_generation_mode"),
                "row_count": query_result.get("row_count") or len(analysis.get("rows") or []),
                "analysis_type": analysis.get("analysis_type"),
                "error_type": result.get("error_type") or result.get("sql_generation_error_type") or result.get("error_category"),
                "clarification_question": result.get("clarification_question"),
            }
        )
    return summary


def _artifact_summary(state: dict[str, Any]) -> dict[str, Any]:
    artifacts = state.get("task_artifacts")
    if not isinstance(artifacts, dict):
        return {}
    return {
        key: {
            "artifact_type": value.get("artifact_type") if isinstance(value, dict) else None,
            "row_count": len(value.get("rows") or []) if isinstance(value, dict) else None,
        }
        for key, value in artifacts.items()
    }


def build_answer_context(state: dict[str, Any], *, execution: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """把执行完成的状态整理为 LLM Answer 输入。"""
    query_type = "llm_sql" if state.get("sql_generation_mode") == "llm_sql" else state.get("query_type") or "single"
    task_results = state.get("task_results")
    final_task_id = state.get("final_task_id") or (_final_task_id(task_results) if isinstance(task_results, dict) else None)
    composite_analysis = state.get("composite_analysis_result") if isinstance(state.get("composite_analysis_result"), dict) else {}
    failed_task_id = composite_analysis.get("failed_task_id")

    if query_type == "composite":
        rows = _rows_from_task_results(task_results, final_task_id)
        total_row_count = len(rows)
    else:
        execution_state = execution
        result_state = result
        rows = _rows_from_analysis_result(result_state.get("analysis_result")) or _rows_from_query_result(execution_state.get("execution_result"))
        query_result = execution_state.get("execution_result") if isinstance(execution_state.get("execution_result"), dict) else {}
        total_row_count = query_result.get("row_count") if isinstance(query_result.get("row_count"), int) else len(rows)

    quality = _result_quality(rows, total_row_count)
    if query_type == "composite" and state.get("composite_success") is False:
        failed_text = f"复合查询未成功完成，失败任务：{failed_task_id or 'unknown'}，错误类型：{state.get('composite_error_type') or 'unknown'}。"
        quality.setdefault("warnings", []).append(failed_text)
    requirement = state.get("llm_sql_requirement") if isinstance(state.get("llm_sql_requirement"), dict) else {}
    return {
        "original_question": state.get("user_question") or "",
        "query_type": query_type,
        "final_answer_mode": state.get("final_answer_mode") or (state.get("composite_query_plan") or {}).get("final_answer_mode"),
        "plan_summary": _json_safe_value(deepcopy(state.get("query_plan") or state.get("composite_query_plan") or state.get("task_plan") or {})),
        "metric_metadata": _metric_metadata(state.get("metrics")),
        "result_rows": rows[:MAX_ROWS_PASSED_TO_LLM],
        "result_quality": quality,
        "execution_status": _execution_status(state),
        "task_results_summary": _task_results_summary(task_results),
        "task_artifact_summary": _artifact_summary(state),
        "final_task_id": final_task_id,
        "failed_task_id": failed_task_id,
        "composite_success": state.get("composite_success"),
        "composite_error_type": state.get("composite_error_type"),
        "llm_sql_requirement": _json_safe_value(deepcopy(requirement)) if requirement else None,
        "template_gap_reason": state.get("template_gap_reason"),
        "requirement_type": state.get("requirement_type") or requirement.get("requirement_type"),
        "filters": _json_safe_value(deepcopy(requirement.get("filters") or [])),
        "order_by": _json_safe_value(deepcopy(requirement.get("order_by"))),
        "limit": requirement.get("limit") or state.get("limit"),
        "expected_output": _json_safe_value(deepcopy(requirement.get("expected_output"))),
    }


def build_answer_context_from_contract(state: dict[str, Any], result_contract: dict[str, Any]) -> dict[str, Any]:
    """正式回答链路只从 ResultContract 派生回答上下文。"""
    rows = [dict(row) for row in result_contract.get("evidence_rows") or [] if isinstance(row, dict)]
    row_count = result_contract.get("row_count") if isinstance(result_contract.get("row_count"), int) else len(rows)
    return {
        "original_question": state.get("user_question") or "",
        "metric_metadata": _metric_metadata(state.get("metrics")),
        "result_rows": rows,
        "result_quality": {
            "row_count": row_count,
            "is_empty": row_count == 0,
            "is_truncated": bool(result_contract.get("result_truncated")),
            "max_rows_passed_to_llm": result_contract.get("max_display_rows"),
            "warnings": [],
        },
        "result_contract": deepcopy(result_contract),
    }


def build_answer_context_node(state: dict[str, Any]) -> dict[str, Any]:
    execution = state.get("execution") if isinstance(state.get("execution"), dict) else {}
    result = state.get("result") if isinstance(state.get("result"), dict) else {}
    context = build_answer_context(state, execution=execution, result=result)
    return {
        "answer_context": context,
        "answer_context_summary": {
            "query_type": context.get("query_type"),
            "row_count": (context.get("result_quality") or {}).get("row_count"),
            "is_empty": (context.get("result_quality") or {}).get("is_empty"),
            "final_answer_mode": context.get("final_answer_mode"),
            "requirement_type": context.get("requirement_type"),
        },
    }


__all__ = ["MAX_ROWS_PASSED_TO_LLM", "build_answer_context", "build_answer_context_from_contract", "build_answer_context_node"]
