"""高层意图分类节点。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent.schemas.query_plan import VALID_INTENT_TYPES
from agent.services.llm_json_service import invoke_json_prompt


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROMPT_PATH = PROJECT_ROOT / "agent" / "prompts" / "intent_classifier.md"


def _load_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def normalize_intent_classification(payload: object) -> dict[str, Any]:
    raw = payload if isinstance(payload, dict) else {}
    query_type = raw.get("query_type")
    if query_type not in {"single", "composite"}:
        query_type = "composite" if raw.get("needs_composite_task_plan") is True else "single"
    intent_type = raw.get("intent_type")
    if intent_type not in VALID_INTENT_TYPES:
        intent_type = "unknown"
    return {
        "planner_stage": "intent_classification",
        "query_type": query_type,
        "intent_type": intent_type,
        "is_structured_database_question": raw.get("is_structured_database_question") is not False,
        "needs_composite_task_plan": query_type == "composite" or raw.get("needs_composite_task_plan") is True,
        "reason": raw.get("reason") if isinstance(raw.get("reason"), str) else None,
    }


def build_intent_classifier_prompt(question: str) -> str:
    return _load_prompt() + "\n\n用户问题：\n" + question


def classify_intent_node(state: dict[str, Any]) -> dict[str, Any]:
    question = state.get("user_question") or ""
    payload = invoke_json_prompt(build_intent_classifier_prompt(question))
    classification = normalize_intent_classification(payload)
    return {
        "intent_classification": classification,
        "query_type": classification["query_type"],
        "intent_type": classification["intent_type"],
        "planner_stage": "intent_classification",
    }


__all__ = [
    "build_intent_classifier_prompt",
    "classify_intent_node",
    "normalize_intent_classification",
]
