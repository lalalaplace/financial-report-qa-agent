"""受控 LLM SQL 修复节点。"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from agent.services.llm_json_service import invoke_json_prompt


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_prompt() -> str:
    prompt_path = PROJECT_ROOT / "agent" / "prompts" / "llm_sql_repair.md"
    return prompt_path.read_text(encoding="utf-8")


def _build_prompt(repair_input: dict[str, Any]) -> str:
    payload = {
        "flexible_sql_spec": deepcopy(repair_input.get("flexible_sql_spec") or {}),
        "semantic_sql_contract": deepcopy(repair_input.get("semantic_sql_contract") or {}),
        "contract_violations": deepcopy(repair_input.get("contract_violations") or {}),
        "allowed_tables": deepcopy(repair_input.get("allowed_tables") or []),
        "allowed_columns": deepcopy(repair_input.get("allowed_columns") or {}),
        "metric_bindings": deepcopy(repair_input.get("metric_bindings") or []),
        "candidate_sql": repair_input.get("candidate_sql") or "",
        "validation_error": deepcopy(repair_input.get("validation_error") or {}),
        "repair_hint": repair_input.get("repair_hint"),
        "max_rows": repair_input.get("max_rows"),
    }
    return _load_prompt() + "\n\n输入：\n" + json.dumps(payload, ensure_ascii=False, indent=2)


def llm_sql_repair_node(repair_input: dict[str, Any]) -> dict[str, Any]:
    """调用 LLM 修复 SQL，返回候选 SQL 与修复摘要。"""
    payload = invoke_json_prompt(_build_prompt(repair_input), profile="sql_repair")
    if not isinstance(payload, dict):
        raise ValueError("SQL 修复器未返回 JSON 对象。")
    sql = payload.get("sql")
    if not isinstance(sql, str) or not sql.strip():
        raise ValueError("SQL 修复器未返回有效 SQL。")
    repair_summary = payload.get("repair_summary")
    return {
        "sql": sql,
        "repair_summary": repair_summary if isinstance(repair_summary, str) else "",
    }


__all__ = ["llm_sql_repair_node"]
