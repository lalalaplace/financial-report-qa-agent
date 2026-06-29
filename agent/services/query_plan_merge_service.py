"""多轮补问 QueryPlan 合并服务。

合并后的 QueryPlan 只作为下一轮查询规划输入，不得复用旧执行结果。
调用方必须重新走公司标准化、指标标准化、slot validator、SQL 生成、SQL Guard 和执行链路。
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


FIELD_PATCH_KEYS = {
    "companies": {"company_mentions"},
    "compare_companies": {"company_mentions"},
    "metrics": {"metric_mentions"},
    "report_year": {"report_year", "time_mode", "time_range"},
    "start_year": {"start_year", "time_mode", "time_range"},
    "end_year": {"end_year", "time_mode", "time_range"},
    "ranking_limit": {"ranking_limit", "limit"},
    "ranking_direction": {"rank_direction"},
    "report_period": {"report_period"},
}

EXECUTION_STATE_DEFAULTS: dict[str, Any] = {
    "companies": [],
    "metrics": [],
    "company_candidates": [],
    "metric_candidates": [],
    "company_resolution_status": None,
    "metric_resolution_status": None,
    "sql": None,
    "sql_review": None,
    "compare_sqls": [],
    "compare_trend_sqls": [],
    "compare_yoy_sqls": [],
    "derived_compare_sqls": [],
    "derived_compare_trend_sqls": [],
    "derived_compare_yoy_sqls": [],
    "yoy_sqls": [],
    "derived_sqls": [],
    "derived_trend_sqls": [],
    "derived_yoy_sqls": [],
    "query_result": None,
    "compare_query_results": [],
    "compare_trend_query_results": [],
    "compare_yoy_query_results": [],
    "derived_compare_query_results": {},
    "derived_compare_trend_query_results": {},
    "derived_compare_yoy_query_results": {},
    "derived_query_results": [],
    "derived_trend_query_results": {},
    "derived_yoy_query_results": {},
    "sql_success": None,
    "analysis_result": None,
    "compare_result": [],
    "compare_trend_result": [],
    "compare_yoy_result": [],
    "derived_compare_result": [],
    "derived_compare_trend_result": [],
    "derived_compare_yoy_result": [],
    "yoy_result": None,
    "derived_result": None,
    "derived_trend_result": None,
    "derived_yoy_result": None,
    "answer_facts": [],
    "final_answer": None,
    "business_success": None,
    "error_type": None,
    "empty_fields": [],
    "need_clarification": False,
    "clarification_type": None,
    "clarification_question": None,
    "clarification_candidates": [],
    "clarification_payload": None,
}


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _append_unique(base_items: Any, patch_items: Any) -> list[Any]:
    """按原顺序合并列表并去重。"""
    merged: list[Any] = []
    for item in _as_list(base_items) + _as_list(patch_items):
        if item not in merged:
            merged.append(item)
    return merged


def _allowed_patch_keys(pending_empty_fields: list[str] | None) -> set[str]:
    fields = set(pending_empty_fields or [])
    allowed: set[str] = set()
    for field in fields:
        allowed.update(FIELD_PATCH_KEYS.get(field, set()))
    return allowed


def validate_slot_patch(
    slot_patch: dict[str, Any] | None,
    pending_empty_fields: list[str] | None,
) -> dict[str, Any]:
    """校验补充槽位只能写入当前缺失字段对应的 QueryPlan 字段。"""
    if not isinstance(slot_patch, dict) or not slot_patch:
        raise ValueError("slot_patch 必须是非空 dict。")

    allowed_keys = _allowed_patch_keys(pending_empty_fields)
    if not allowed_keys:
        raise ValueError("当前澄清类型不支持 QueryPlan 合并。")

    invalid_keys = sorted(key for key in slot_patch if key not in allowed_keys)
    if invalid_keys:
        raise ValueError(f"slot_patch 包含非缺失字段：{invalid_keys}")

    return deepcopy(slot_patch)


def _merge_time_range(merged: dict[str, Any], patch: dict[str, Any]) -> None:
    time_range = deepcopy(merged.get("time_range") or {})
    if "time_range" in patch and isinstance(patch["time_range"], dict):
        for key, value in patch["time_range"].items():
            if value is not None:
                time_range[key] = deepcopy(value)
    if patch.get("time_mode") is not None:
        time_range["mode"] = deepcopy(patch["time_mode"])
    for key in ("report_year", "start_year", "end_year"):
        if patch.get(key) is not None:
            time_range[key] = deepcopy(patch[key])
    merged["time_range"] = time_range


def merge_query_plan(
    pending_query_plan: dict[str, Any] | None,
    slot_patch: dict[str, Any] | None,
    pending_empty_fields: list[str] | None = None,
) -> dict[str, Any] | None:
    """把用户补充槽位合并回上一轮 QueryPlan，返回待重新执行的计划。"""
    if not isinstance(pending_query_plan, dict):
        return None

    patch = validate_slot_patch(slot_patch, pending_empty_fields)
    merged = deepcopy(pending_query_plan)

    if "company_mentions" in patch:
        merged["company_mentions"] = _append_unique(
            merged.get("company_mentions"),
            patch["company_mentions"],
        )
    if "metric_mentions" in patch:
        merged["metric_mentions"] = _append_unique(
            merged.get("metric_mentions"),
            patch["metric_mentions"],
        )
    if any(key in patch for key in ("report_year", "start_year", "end_year", "time_mode", "time_range")):
        _merge_time_range(merged, patch)
    if "ranking_limit" in patch:
        merged["limit"] = deepcopy(patch["ranking_limit"])
    if "limit" in patch:
        merged["limit"] = deepcopy(patch["limit"])
    if "rank_direction" in patch:
        merged["rank_direction"] = deepcopy(patch["rank_direction"])
    if "report_period" in patch:
        merged["report_period"] = deepcopy(patch["report_period"])

    merged["need_clarification"] = False
    merged["clarification_reason"] = None
    return merged


def clear_execution_state_after_merge(state: dict[str, Any]) -> dict[str, Any]:
    """合并 QueryPlan 后清空旧标准化、SQL、执行、分析和回答状态。"""
    cleaned = deepcopy(state)
    for field, default_value in EXECUTION_STATE_DEFAULTS.items():
        cleaned[field] = deepcopy(default_value)
    return cleaned


__all__ = [
    "clear_execution_state_after_merge",
    "merge_query_plan",
    "validate_slot_patch",
]
