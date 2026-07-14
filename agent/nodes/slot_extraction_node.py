"""用户问题槽位抽取节点。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent.schemas.query_plan import (
    normalize_compare_spec,
    validate_plan,
)
from agent.services.llm_json_service import invoke_json_prompt


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROMPT_PATH = PROJECT_ROOT / "agent" / "prompts" / "slot_extraction.md"


def _load_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def _default_slot_payload() -> dict[str, Any]:
    return {
        "company_mentions": [],
        "metric_mentions": [],
        "report_period": "unspecified",
        "time_range": {
            "mode": "unspecified",
            "report_year": None,
            "recent_n_years": None,
            "start_year": None,
            "end_year": None,
            "report_years": [],
        },
        "compare_spec": None,
        "rank_direction": None,
        "limit": None,
        "change_metric": None,
        "filters": [],
        "thresholds": [],
    }


def normalize_slot_extraction(payload: object, intent_type: str = "unknown") -> dict[str, Any]:
    raw = payload if isinstance(payload, dict) else {}
    merged = _default_slot_payload()
    merged.update({key: value for key, value in raw.items() if key in merged})
    plan_payload = {
        "intent_type": intent_type,
        "company_mentions": merged["company_mentions"],
        "metric_mentions": merged["metric_mentions"],
        "report_period": merged["report_period"],
        "time_range": merged["time_range"],
        "compare_spec": normalize_compare_spec(merged.get("compare_spec")) if merged.get("compare_spec") else None,
        "rank_direction": merged["rank_direction"],
        "limit": merged["limit"],
        "change_metric": merged["change_metric"],
        "need_clarification": False,
        "clarification_reason": None,
    }
    normalized_plan = validate_plan(plan_payload)
    return {
        "company_mentions": normalized_plan["company_mentions"],
        "metric_mentions": normalized_plan["metric_mentions"],
        "report_period": normalized_plan["report_period"],
        "time_range": normalized_plan["time_range"],
        "compare_spec": normalized_plan["compare_spec"],
        "rank_direction": normalized_plan["rank_direction"],
        "limit": normalized_plan["limit"],
        "change_metric": normalized_plan["change_metric"],
        "filters": raw.get("filters") if isinstance(raw.get("filters"), list) else [],
        "thresholds": raw.get("thresholds") if isinstance(raw.get("thresholds"), list) else [],
    }


def build_slot_extraction_prompt(question: str, intent_classification: dict[str, Any] | None = None) -> str:
    payload = {
        "original_question": question,
        "intent_classification": intent_classification or {},
    }
    return _load_prompt() + "\n\n输入：\n" + json.dumps(payload, ensure_ascii=False, indent=2)


def extract_slots_node(state: dict[str, Any]) -> dict[str, Any]:
    question = state.get("user_question") or ""
    intent_classification = state.get("intent_classification") if isinstance(state.get("intent_classification"), dict) else {}
    payload = invoke_json_prompt(build_slot_extraction_prompt(question, intent_classification))
    intent_type = intent_classification.get("intent_type") or state.get("intent_type") or "unknown"
    slots = normalize_slot_extraction(payload, intent_type)
    return {
        "slot_extraction": slots,
        **slots,
    }


__all__ = [
    "build_slot_extraction_prompt",
    "extract_slots_node",
    "normalize_slot_extraction",
]
