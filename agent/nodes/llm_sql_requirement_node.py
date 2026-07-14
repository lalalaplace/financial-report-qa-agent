"""LLM SQL 需求构建节点。"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from agent.schemas.llm_sql_requirement import (
    ALLOWED_REQUIREMENT_TYPES,
    LlmSqlRequirement,
    normalize_llm_sql_requirement,
)
from agent.services.llm_json_service import invoke_json_prompt


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_prompt() -> str:
    prompt_path = PROJECT_ROOT / "agent" / "prompts" / "llm_sql_requirement.md"
    return prompt_path.read_text(encoding="utf-8")


def _metric_names(metrics: object) -> list[str]:
    if not isinstance(metrics, list):
        return []
    names: list[str] = []
    for metric in metrics:
        if not isinstance(metric, dict):
            continue
        for key in ("metric_name", "matched_alias", "metric_key"):
            value = metric.get(key)
            if isinstance(value, str) and value.strip():
                names.append(value.strip())
    return list(dict.fromkeys(names))


def _template_match_result(state: dict[str, Any]) -> dict[str, Any]:
    existing = state.get("template_match_result")
    if isinstance(existing, dict):
        return dict(existing)
    return {
        "matched": state.get("sql_generation_mode") == "template",
        "reason": state.get("template_gap_reason") or state.get("error_type"),
    }


def _build_prompt(state: dict[str, Any]) -> str:
    query_plan = state.get("query_plan") or {}
    planner_output = query_plan if isinstance(query_plan, dict) else {}
    payload = {
        "original_question": state.get("user_question") or state.get("original_question") or "",
        "planner_output": planner_output,
        "resolved_companies": deepcopy(state.get("companies") or []),
        "mapped_metrics": deepcopy(state.get("metrics") or []),
        "metric_mentions": deepcopy(state.get("metric_mentions") or []),
        "time_info": deepcopy(state.get("time_range") or {}),
        "report_year": state.get("report_year"),
        "report_period": state.get("report_period"),
        "template_match_result": _template_match_result(state),
        "template_gap_reason": state.get("template_gap_reason"),
        "available_metric_names": _metric_names(state.get("metrics")) or list(state.get("metric_mentions") or []),
        "allowed_requirement_types": list(ALLOWED_REQUIREMENT_TYPES),
    }
    return _load_prompt() + "\n\n输入：\n" + json.dumps(payload, ensure_ascii=False, indent=2)


def _rejected_result(requirement: LlmSqlRequirement) -> dict[str, Any]:
    reason = requirement.get("reason")
    if reason == "need_clarification":
        return {
            "need_clarification": True,
            "clarification_question": requirement.get("clarification_question") or "请补充关键指标、年份或排序口径。",
            "error_type": "NEED_CLARIFICATION",
            "sql_generation_mode": "unsupported",
            "llm_sql_requirement": requirement,
            "llm_sql_requirement_parsed": requirement,
            "can_use_llm_sql": False,
        }
    if reason == "template_should_handle":
        return {
            "need_clarification": False,
            "error_type": "ROUTER_CONFLICT",
            "sql_generation_mode": "unsupported",
            "sql_generation_error_type": "ROUTER_CONFLICT",
            "sql_generation_error_message": "LLM requirement 判断该问题应由模板处理。",
            "llm_sql_requirement": requirement,
            "llm_sql_requirement_parsed": requirement,
            "can_use_llm_sql": False,
        }
    return {
        "need_clarification": False,
        "error_type": "UNSUPPORTED_OUT_OF_SCOPE" if reason in {"unsupported", "unsafe_or_out_of_scope"} else "LLM_SQL_REQUIREMENT_REJECTED",
        "sql_generation_mode": "unsupported",
        "sql_generation_error_type": "UNSUPPORTED_OUT_OF_SCOPE" if reason in {"unsupported", "unsafe_or_out_of_scope"} else "LLM_SQL_REQUIREMENT_REJECTED",
        "sql_generation_error_message": requirement.get("unsupported_reason") or requirement.get("clarification_question") or reason,
        "llm_sql_requirement": requirement,
        "llm_sql_requirement_parsed": requirement,
        "can_use_llm_sql": False,
    }


def build_llm_sql_requirement_node(state: dict[str, Any]) -> dict[str, Any]:
    """判断模板缺口是否可进入受控 LLM SQL，并构建结构化需求。"""
    try:
        raw_requirement = invoke_json_prompt(_build_prompt(state))
    except Exception as exc:
        return {
            "need_clarification": False,
            "error_type": "LLM_SQL_REQUIREMENT_REJECTED",
            "sql_generation_mode": "unsupported",
            "sql_generation_error_type": "LLM_SQL_REQUIREMENT_REJECTED",
            "sql_generation_error_message": f"LLM SQL 需求构建失败：{exc}",
            "llm_sql_requirement_raw": None,
            "can_use_llm_sql": False,
        }

    requirement = normalize_llm_sql_requirement(raw_requirement)
    if requirement is None:
        return {
            "need_clarification": False,
            "error_type": "LLM_SQL_REQUIREMENT_REJECTED",
            "sql_generation_mode": "unsupported",
            "sql_generation_error_type": "LLM_SQL_REQUIREMENT_REJECTED",
            "sql_generation_error_message": "LLM SQL 需求不是 JSON 对象。",
            "llm_sql_requirement_raw": raw_requirement,
            "can_use_llm_sql": False,
        }

    base_result = {
        "llm_sql_requirement_raw": raw_requirement,
        "llm_sql_requirement_parsed": requirement,
        "llm_sql_requirement": requirement,
        "requirement_type": requirement.get("requirement_type"),
        "can_use_llm_sql": requirement.get("can_use_llm_sql") is True,
    }
    if requirement.get("can_use_llm_sql") is True and requirement.get("reason") == "database_answerable_template_gap":
        return {
            **base_result,
            "need_clarification": False,
            "error_type": "LLM_SQL_REQUIREMENT_BUILT",
        }
    rejected = _rejected_result(requirement)
    rejected.update(base_result)
    return rejected


__all__ = ["build_llm_sql_requirement_node"]
