"""从 graph.py 拆出的业务实现。"""

from __future__ import annotations

from typing import Any

from agent.schemas.query_plan import normalize_compare_spec


def _get_compare_spec(state: dict[str, Any]) -> dict[str, Any]:
    return normalize_compare_spec(state.get("compare_spec"))

def _compare_spec_payload(state: dict[str, Any]) -> dict[str, Any]:
    return {"compare_spec": _get_compare_spec(state)}

def _directed_compare_reference_error(compare_spec: dict[str, Any]) -> dict[str, Any] | None:
    if compare_spec.get("operator") not in {"higher_than", "lower_than"}:
        return None
    if compare_spec.get("subject_company") and compare_spec.get("reference_company"):
        return None
    return {
        "need_clarification": True,
        "clarification_question": "请说明定向比较中的主体公司和参照公司，例如“A 比 B 高多少”。",
        "business_success": False,
        "error_type": "clarify_compare_reference",
        "empty_fields": [],
        "compare_spec": compare_spec,
    }

__all__ = ['_get_compare_spec', '_compare_spec_payload', '_directed_compare_reference_error']
