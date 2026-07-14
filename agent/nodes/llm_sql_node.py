"""受控 LLM SQL 生成节点，仅生成候选 SQL。"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from agent.schemas.llm_sql import metric_bindings_from_metrics
from agent.services.llm_json_service import invoke_json_prompt
from agent.tools.sql_tools import ALLOWED_TABLES


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _allowed_schema(metrics: list[dict[str, Any]], semantic_contract: dict[str, Any] | None = None) -> dict[str, list[str]]:
    schema: dict[str, set[str]] = {"company_dim": {"stock_code", "stock_abbr", "company_name"}}
    for metric in metrics:
        table, field = metric.get("table"), metric.get("field")
        if table in ALLOWED_TABLES and isinstance(field, str):
            schema.setdefault(table, {"stock_code", "report_year", "report_period"}).add(field)
    for qualified in (semantic_contract or {}).get("required_columns") or []:
        if not isinstance(qualified, str) or "." not in qualified:
            continue
        table, field = qualified.rsplit(".", 1)
        if table in ALLOWED_TABLES:
            schema.setdefault(table, {"stock_code", "report_year", "report_period"}).add(field)
    return {name: sorted(columns) for name, columns in schema.items()}


def _build_request(state: dict[str, Any]) -> dict[str, Any]:
    execution = state.get("execution") if isinstance(state.get("execution"), dict) else {}
    spec = execution.get("flexible_sql_spec")
    metrics = [item for item in state.get("metrics") or [] if isinstance(item, dict)]
    if not isinstance(spec, dict) or not metrics:
        raise ValueError("Flexible SQL 缺少已编译规格或标准化指标。")
    semantic_contract = spec.get("semantic_contract") if isinstance(spec.get("semantic_contract"), dict) else {}
    columns = _allowed_schema(metrics, semantic_contract)
    return {
        "flexible_sql_spec": deepcopy(spec),
        "allowed_tables": sorted(columns), "allowed_columns": columns,
        "metric_bindings": metric_bindings_from_metrics(metrics), "max_rows": min(max(int(spec.get("limit") or 50), 1), 50),
        "required_output_fields": ["stock_code", "report_year"],
        "sql_dialect": "duckdb",
        "sql_constraints": {
            "read_only": True,
            "single_statement": True,
            "select_star_allowed": False,
            "allow_cte_join_aggregate_window": True,
        },
    }


def _prompt(request: dict[str, Any]) -> str:
    template = (PROJECT_ROOT / "agent" / "prompts" / "flexible_sql_generator.md").read_text(encoding="utf-8")
    return template + "\n\n输入：\n" + json.dumps(request, ensure_ascii=False, indent=2)


def generate_llm_sql_node(state: dict[str, Any]) -> dict[str, Any]:
    """调用模型并返回未经校验的候选 SQL。"""
    try:
        request = _build_request(state)
        payload = invoke_json_prompt(_prompt(request), profile="sql_generator")
    except Exception as exc:
        return {"sql_generation_mode": "llm_sql", "sql_generation_status": "failed", "sql_generation_error_type": getattr(exc, "error_code", "LLM_SQL_GENERATION_FAILED"), "sql_generation_error_message": str(exc)}
    sql = payload.get("sql") if isinstance(payload, dict) else None
    if not isinstance(sql, str) or not sql.strip():
        return {"sql_generation_mode": "llm_sql", "sql_generation_status": "failed", "sql_generation_error_type": "LLM_SQL_GENERATION_FAILED", "sql_generation_error_message": "LLM SQL 未返回有效 SQL。", "llm_sql_raw_response": payload}
    return {"sql": sql, "llm_sql_candidate": sql, "llm_sql_request": request, "llm_sql_raw_response": payload, "sql_generation_mode": "llm_sql", "sql_generation_status": "success", "sql_generation_error_type": None, "sql_generation_error_message": None}


def _tabular_analysis_from_query_result(query_result: dict[str, Any]) -> dict[str, Any]:
    columns = query_result.get("columns") or []
    rows = [dict(zip(columns, row)) for row in query_result.get("rows") or []]
    return {"analysis_result": {"analysis_type": "llm_sql_tabular", "row_count": len(rows), "is_empty": not rows, "rows": rows}, "business_success": bool(rows), "error_type": None if rows else "empty_llm_sql_result"}


__all__ = ["generate_llm_sql_node", "_tabular_analysis_from_query_result"]
