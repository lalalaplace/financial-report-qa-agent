"""澄清与不支持决策节点。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent.services.llm_json_service import invoke_json_prompt


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROMPT_PATH = PROJECT_ROOT / "agent" / "prompts" / "clarification_decision.md"
VALID_DECISIONS = {"continue", "need_clarification", "unsupported"}


def _load_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def normalize_clarification_decision(payload: object) -> dict[str, Any]:
    raw = payload if isinstance(payload, dict) else {}
    decision = raw.get("decision")
    if decision not in VALID_DECISIONS:
        decision = "continue"
    missing_fields = raw.get("missing_fields") if isinstance(raw.get("missing_fields"), list) else []
    return {
        "decision": decision,
        "error_type": raw.get("error_type") if isinstance(raw.get("error_type"), str) else None,
        "clarification_question": raw.get("clarification_question") if isinstance(raw.get("clarification_question"), str) else None,
        "unsupported_reason": raw.get("unsupported_reason") if isinstance(raw.get("unsupported_reason"), str) else None,
        "missing_fields": [item for item in missing_fields if isinstance(item, str)],
        "reason": raw.get("reason") if isinstance(raw.get("reason"), str) else None,
    }


def build_clarification_decision_prompt(state: dict[str, Any]) -> str:
    payload = {
        "original_question": state.get("user_question"),
        "intent_classification": state.get("intent_classification"),
        "slot_extraction": state.get("slot_extraction"),
        "query_plan": state.get("query_plan"),
        "composite_query_plan": state.get("composite_query_plan"),
        "company_resolution_status": state.get("company_resolution_status"),
        "metric_resolution_status": state.get("metric_resolution_status"),
        "template_match_result": state.get("template_match_result"),
        "template_gap_reason": state.get("template_gap_reason"),
        "need_clarification": state.get("need_clarification"),
        "clarification_question": state.get("clarification_question"),
        "error_type": state.get("error_type"),
    }
    return _load_prompt() + "\n\n输入：\n" + json.dumps(payload, ensure_ascii=False, indent=2)


def clarification_decision_node(state: dict[str, Any]) -> dict[str, Any]:
    payload = invoke_json_prompt(build_clarification_decision_prompt(state))
    decision = normalize_clarification_decision(payload)
    result: dict[str, Any] = {"clarification_decision": decision}
    if decision["decision"] == "need_clarification":
        result.update(
            {
                "need_clarification": True,
                "clarification_question": decision.get("clarification_question") or "请补充查询所需信息。",
                "error_type": decision.get("error_type") or "NEED_CLARIFICATION",
                "empty_fields": decision.get("missing_fields") or [],
            }
        )
    elif decision["decision"] == "unsupported":
        result.update(
            {
                "need_clarification": False,
                "business_success": False,
                "error_type": decision.get("error_type") or "UNSUPPORTED_OUT_OF_SCOPE",
                "sql_generation_mode": "unsupported",
                "sql_generation_error_type": decision.get("error_type") or "UNSUPPORTED_OUT_OF_SCOPE",
                "sql_generation_error_message": decision.get("unsupported_reason") or decision.get("reason"),
            }
        )
    else:
        result.update({"need_clarification": False})
    return result


__all__ = [
    "build_clarification_decision_prompt",
    "clarification_decision_node",
    "normalize_clarification_decision",
]
