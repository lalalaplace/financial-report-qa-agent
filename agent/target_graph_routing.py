"""目标主图路由函数。"""

from __future__ import annotations

from typing import Any


def route_after_context_router_target(state: dict[str, Any]) -> str:
    route_type = state.get("route_type") or "new_query"
    if route_type in {"clarification_answer", "contextual_followup"}:
        return "merge_context"
    if route_type == "irrelevant":
        return "irrelevant_answer"
    if route_type == "ambiguous" or state.get("need_clarification"):
        return "clarification_answer"
    return "query_planner"


def route_after_query_spec_validator(state: dict[str, Any]) -> str:
    if state.get("need_clarification"):
        return "clarification_answer"
    status = state.get("query_spec_validation_status")
    if status == "unsupported":
        return "capability_boundary_answer"
    return "capability_router"


def route_after_capability_router(state: dict[str, Any]) -> str:
    planning = state.get("planning") if isinstance(state.get("planning"), dict) else {}
    decision = planning.get("capability_decision") if isinstance(planning.get("capability_decision"), dict) else {}
    mode = decision.get("execution_mode")
    if mode == "deterministic":
        return "deterministic_sql_builder"
    if mode == "flexible_sql":
        return "flexible_sql_spec_builder"
    if mode == "clarification":
        return "clarification_answer"
    return "capability_boundary_answer"


def route_after_flexible_sql_spec(state: dict[str, Any]) -> str:
    if state.get("error", {}).get("error_stage") == "sql_generation":
        return "controlled_failure"
    return "llm_sql_generator"


def route_after_llm_sql_generator(state: dict[str, Any]) -> str:
    error = state.get("error") if isinstance(state.get("error"), dict) else {}
    if error.get("error_stage") == "sql_generation":
        return "controlled_failure"
    return "sql_guard"


def route_after_sql_guard(state: dict[str, Any]) -> str:
    if state.get("error", {}).get("error_stage") == "sql_guard":
        return "controlled_failure" if state.get("sql_repair_attempted") else "llm_sql_repair"
    return "semantic_validate" if _capability_mode(state) == "flexible_sql" else "execute_sql"


def route_after_semantic_validate(state: dict[str, Any]) -> str:
    if state.get("error", {}).get("error_stage") == "semantic_validate":
        return "controlled_failure" if state.get("sql_repair_attempted") else "llm_sql_repair"
    return "dry_run"


def route_after_dry_run(state: dict[str, Any]) -> str:
    execution = state.get("execution") if isinstance(state.get("execution"), dict) else {}
    dry_run_result = execution.get("dry_run_result") if isinstance(execution.get("dry_run_result"), dict) else {}
    if _capability_mode(state) == "flexible_sql" and dry_run_result.get("success") is not True:
        return "controlled_failure" if state.get("sql_repair_attempted") else "llm_sql_repair"
    return "execute_sql"


def route_after_execute_sql(state: dict[str, Any]) -> str:
    if _capability_mode(state) == "flexible_sql":
        return "result_contract_builder"
    return "deterministic_result_analyzer"


def _capability_mode(state: dict[str, Any]) -> str | None:
    planning = state.get("planning") if isinstance(state.get("planning"), dict) else {}
    decision = planning.get("capability_decision") if isinstance(planning.get("capability_decision"), dict) else {}
    return decision.get("execution_mode") if isinstance(decision.get("execution_mode"), str) else None


__all__ = [
    "route_after_capability_router",
    "route_after_context_router_target",
    "route_after_dry_run",
    "route_after_execute_sql",
    "route_after_flexible_sql_spec",
    "route_after_llm_sql_generator",
    "route_after_query_spec_validator",
    "route_after_sql_guard",
    "route_after_semantic_validate",
]
