"""多轮澄清补答识别服务。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
METRIC_DICTIONARY_PATH = PROJECT_ROOT / "data" / "metric_dictionary.json"

FORBIDDEN_PATCH_KEYS = {
    "sql",
    "sql_template",
    "table_name",
    "column_name",
    "where_clause",
    "companies",
    "metrics",
}

QUESTION_MARKERS = {
    "多少",
    "是多少",
    "什么",
    "哪些",
    "如何",
    "第几",
    "排名",
    "趋势",
    "对比",
    "同比",
    "增长率",
    "增长",
    "下降",
    "前",
    "后",
    "最高",
    "最低",
    "更高",
    "更低",
}

FILLER_WORDS = {
    "公司",
    "企业",
    "指标",
    "年度",
    "年报",
    "报告",
    "查询",
    "想查",
    "查",
    "看",
    "的",
    "是",
    "为",
    "和",
    "与",
    "及",
}

CN_NUMBERS = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


@dataclass(frozen=True)
class ClarificationPatchResult:
    is_clarification_answer: bool
    slot_patch: dict[str, Any]
    reason: str


def _compact_text(text: str) -> str:
    return "".join((text or "").strip().split())


def _pending_empty_fields(clarification_context: dict[str, Any] | None) -> list[str]:
    if not isinstance(clarification_context, dict):
        return []
    fields = clarification_context.get("empty_fields") or clarification_context.get("pending_empty_fields") or []
    return [field for field in fields if isinstance(field, str)]


def has_pending_query_plan(state: dict[str, Any]) -> bool:
    """判断当前状态是否存在可用于补答合并的 pending QueryPlan。"""
    if not isinstance(state.get("pending_query_plan"), dict):
        return False
    if state.get("clarification_context") or state.get("pending_clarification"):
        return True
    return bool(state.get("pending_clarification_type") or state.get("pending_empty_fields"))


def build_clarification_context_from_state(state: dict[str, Any]) -> dict[str, Any]:
    """兼容已有 state 字段，构造补答识别所需的澄清上下文。"""
    context = state.get("clarification_context")
    if isinstance(context, dict):
        return context
    return {
        "clarification_type": state.get("pending_clarification_type"),
        "empty_fields": list(state.get("pending_empty_fields") or []),
        "pending_empty_fields": list(state.get("pending_empty_fields") or []),
    }


def _load_metric_aliases() -> list[str]:
    try:
        import json

        with METRIC_DICTIONARY_PATH.open("r", encoding="utf-8") as file:
            metric_dict = json.load(file)
    except (OSError, ValueError):
        return []

    aliases: set[str] = set()
    for info in metric_dict.values():
        metric_name = info.get("metric_name")
        if isinstance(metric_name, str):
            aliases.add(metric_name)
        for alias in info.get("aliases") or []:
            if isinstance(alias, str):
                aliases.add(alias)
    return sorted(aliases, key=len, reverse=True)


def _extract_years(text: str) -> list[int]:
    years: list[int] = []
    for item in re.findall(r"(?<!\d)((?:19|20)\d{2})(?!\d)", text):
        year = int(item)
        if year not in years:
            years.append(year)
    return years


def _extract_metric_mentions(text: str) -> list[str]:
    compact = _compact_text(text)
    mentions: list[str] = []
    for alias in _load_metric_aliases():
        compact_alias = _compact_text(alias)
        if compact_alias and compact_alias in compact and alias not in mentions:
            mentions.append(alias)
    return mentions


def _extract_rank_limit(text: str) -> int | None:
    compact = _compact_text(text)
    match = re.search(r"(?:前|后|top|TOP)\s*(\d{1,3})", compact)
    if not match:
        match = re.search(r"(\d{1,3})\s*(?:家|名|个)?", compact)
    if match:
        value = int(match.group(1))
        return value if 1 <= value <= 100 else None

    for token, value in CN_NUMBERS.items():
        if token in compact:
            return value
    return None


def _extract_rank_direction(text: str) -> str | None:
    compact = _compact_text(text)
    if any(word in compact for word in ("最低", "最少", "最小", "倒数", "后")):
        return "asc"
    if any(word in compact for word in ("最高", "最多", "最大", "前")):
        return "desc"
    return None


def _extract_report_period(text: str) -> str | None:
    compact = _compact_text(text)
    if any(word in compact for word in ("一季报", "第一季度", "Q1", "q1")):
        return "Q1"
    if any(word in compact for word in ("半年报", "半年度", "H1", "h1")):
        return "H1"
    if any(word in compact for word in ("三季报", "第三季度", "Q3", "q3")):
        return "Q3"
    if any(word in compact for word in ("年报", "年度", "全年", "FY", "fy")):
        return "FY"
    return None


def _looks_like_complete_new_question(text: str, empty_fields: set[str]) -> bool:
    compact = _compact_text(text)
    if not compact:
        return False

    marker_count = sum(1 for marker in QUESTION_MARKERS if marker in compact)
    has_year = bool(_extract_years(compact))
    has_metric = bool(_extract_metric_mentions(compact))
    has_question_mark = "?" in compact or "？" in compact

    if marker_count >= 2:
        return True
    if has_metric and (has_year or has_question_mark or marker_count >= 1):
        return True
    if "metrics" in empty_fields and has_year and marker_count >= 1:
        return True
    return False


def _split_mentions(text: str) -> list[str]:
    cleaned = re.sub(r"(?<!\d)(?:19|20)\d{2}(?!\d)", " ", text)
    cleaned = re.sub(r"[？?，,。；;：:\s]+", " ", cleaned)
    parts = re.split(r"[、/]|和|与|及", cleaned)
    mentions: list[str] = []
    for part in parts:
        value = part.strip()
        if not value or value in FILLER_WORDS:
            continue
        if any(word in value for word in QUESTION_MARKERS):
            continue
        mentions.append(value)
    return mentions


def _build_slot_patch(user_input: str, empty_fields: set[str]) -> tuple[dict[str, Any], list[str]]:
    patch: dict[str, Any] = {}
    reasons: list[str] = []

    if {"companies", "compare_companies"} & empty_fields:
        company_mentions = _split_mentions(user_input)
        if company_mentions:
            patch["company_mentions"] = company_mentions
            reasons.append("补充了上一轮缺失的公司")

    if "metrics" in empty_fields:
        metric_mentions = _extract_metric_mentions(user_input)
        if metric_mentions:
            patch["metric_mentions"] = metric_mentions
            reasons.append("补充了上一轮缺失的指标")

    years = _extract_years(user_input)
    if "report_year" in empty_fields and years:
        patch["time_mode"] = "single_year"
        patch["report_year"] = years[-1]
        reasons.append("补充了上一轮缺失的年份")
    if {"start_year", "end_year"} & empty_fields and len(years) >= 2:
        start_year, end_year = min(years[0], years[1]), max(years[0], years[1])
        patch["time_mode"] = "explicit_range"
        patch["start_year"] = start_year
        patch["end_year"] = end_year
        reasons.append("补充了上一轮缺失的年份范围")

    if "ranking_limit" in empty_fields:
        rank_limit = _extract_rank_limit(user_input)
        if rank_limit is not None:
            patch["ranking_limit"] = rank_limit
            reasons.append("补充了上一轮缺失的排名数量")

    if "ranking_direction" in empty_fields:
        rank_direction = _extract_rank_direction(user_input)
        if rank_direction:
            patch["rank_direction"] = rank_direction
            reasons.append("补充了上一轮缺失的排名方向")

    if "report_period" in empty_fields:
        report_period = _extract_report_period(user_input)
        if report_period:
            patch["report_period"] = report_period
            reasons.append("补充了上一轮缺失的报告期")

    invalid_keys = FORBIDDEN_PATCH_KEYS & set(patch)
    if invalid_keys:
        raise ValueError(f"slot_patch 包含禁止字段：{sorted(invalid_keys)}")
    return patch, reasons


def _build_contextual_slot_patch(user_input: str) -> tuple[dict[str, Any], list[str]]:
    patch: dict[str, Any] = {}
    reasons: list[str] = []

    metric_mentions = _extract_metric_mentions(user_input)
    if metric_mentions:
        patch["metric_mentions"] = metric_mentions
        reasons.append("基于上一轮成功查询补充了指标")

    years = _extract_years(user_input)
    if len(years) >= 2:
        start_year, end_year = min(years[0], years[1]), max(years[0], years[1])
        patch["time_mode"] = "explicit_range"
        patch["start_year"] = start_year
        patch["end_year"] = end_year
        reasons.append("基于上一轮成功查询补充了年份范围")
    elif len(years) == 1:
        patch["time_mode"] = "single_year"
        patch["report_year"] = years[0]
        reasons.append("基于上一轮成功查询补充了年份")

    rank_limit = _extract_rank_limit(user_input)
    if rank_limit is not None and any(word in _compact_text(user_input) for word in ("前", "后", "top", "TOP")):
        patch["ranking_limit"] = rank_limit
        reasons.append("基于上一轮成功查询补充了排名数量")

    rank_direction = _extract_rank_direction(user_input)
    if rank_direction:
        patch["rank_direction"] = rank_direction
        reasons.append("基于上一轮成功查询补充了排名方向")

    report_period = _extract_report_period(user_input)
    if report_period:
        patch["report_period"] = report_period
        reasons.append("基于上一轮成功查询补充了报告期")

    if not metric_mentions:
        company_mentions = _split_mentions(user_input)
        if company_mentions and not years:
            patch["company_mentions"] = company_mentions
            reasons.append("基于上一轮成功查询补充了公司")

    invalid_keys = FORBIDDEN_PATCH_KEYS & set(patch)
    if invalid_keys:
        raise ValueError(f"slot_patch 包含禁止字段：{sorted(invalid_keys)}")
    return patch, reasons


def detect_and_extract_slot_patch(
    user_input: str,
    pending_query_plan: dict[str, Any],
    clarification_context: dict[str, Any],
) -> ClarificationPatchResult:
    """识别当前输入是否是上一轮澄清问题的补答，并提取 QueryPlan 补丁。"""
    if not isinstance(pending_query_plan, dict):
        return ClarificationPatchResult(False, {}, "不存在 pending_query_plan")

    empty_fields = set(_pending_empty_fields(clarification_context))
    if not empty_fields:
        return ClarificationPatchResult(False, {}, "不存在待补充字段")

    if _looks_like_complete_new_question(user_input, empty_fields):
        return ClarificationPatchResult(False, {}, "当前输入更像完整新问题")

    slot_patch, reasons = _build_slot_patch(user_input, empty_fields)
    if not slot_patch:
        return ClarificationPatchResult(False, {}, "当前输入未补充上一轮缺失字段")

    return ClarificationPatchResult(True, slot_patch, "；".join(reasons))


def detect_and_extract_contextual_patch(
    user_input: str,
    last_successful_query_plan: dict[str, Any],
) -> ClarificationPatchResult:
    """识别基于上一轮成功查询的上下文追问，并提取 QueryPlan 补丁。"""
    if not isinstance(last_successful_query_plan, dict):
        return ClarificationPatchResult(False, {}, "不存在 last_successful_query_plan")

    if _looks_like_complete_new_question(user_input, set()):
        return ClarificationPatchResult(False, {}, "当前输入更像完整新问题")

    slot_patch, reasons = _build_contextual_slot_patch(user_input)
    if not slot_patch:
        return ClarificationPatchResult(False, {}, "当前输入未形成可合并的上下文补丁")

    return ClarificationPatchResult(True, slot_patch, "；".join(reasons))


__all__ = [
    "ClarificationPatchResult",
    "build_clarification_context_from_state",
    "detect_and_extract_contextual_patch",
    "detect_and_extract_slot_patch",
    "has_pending_query_plan",
]
