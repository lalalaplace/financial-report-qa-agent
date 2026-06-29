"""槽位验证公共函数。"""

from agent.constants import DEFAULT_QUERY_TYPE, COMPARE_INTENTS
from agent.services.compare_service import _compare_spec_payload


def passthrough_clarification(state: dict) -> dict | None:
    """need_clarification 透传。返回 None 表示无需透传。"""
    if not state.get("need_clarification"):
        return None
    intent_type = state.get("intent_type") or DEFAULT_QUERY_TYPE
    result: dict = {
        "need_clarification": True,
        "business_success": False,
        "empty_fields": [],
    }
    if intent_type in COMPARE_INTENTS:
        result.update(_compare_spec_payload(state))
    return result


def company_metric_precheck(
    companies: list,
    company_candidates: list,
    metrics: list,
    metric_candidates: list,
) -> dict | None:
    """非对比类查询的公共公司/指标预检。返回 None 表示通过。"""
    if not companies and len(company_candidates) > 1:
        candidate_text = "\n".join(
            f"{i}. {c['stock_abbr']}"
            for i, c in enumerate(company_candidates, start=1)
        )
        return {
            "need_clarification": True,
            "clarification_question": f"请问你指的是以下哪家公司？\n{candidate_text}",
            "business_success": False,
            "error_type": "need_clarification",
            "empty_fields": [],
        }

    if not companies and not company_candidates:
        return {
            "need_clarification": True,
            "clarification_question": "请说明你要查询的公司，可以提供公司简称、全称或 6 位股票代码。",
            "business_success": False,
            "error_type": "company_not_found",
            "empty_fields": [],
        }

    if not metrics and metric_candidates:
        names = [m.get("metric_name", "") for m in metric_candidates]
        return {
            "need_clarification": True,
            "clarification_question": f"请明确要查询的指标：{'、'.join(names)}。",
            "business_success": False,
            "error_type": "metric_not_found",
            "empty_fields": [],
        }

    if not metrics and not metric_candidates:
        return {
            "need_clarification": True,
            "clarification_question": "请说明你要查询的财务指标，例如总资产、营业收入、净利润或经营活动现金流量净额。",
            "business_success": False,
            "error_type": "metric_not_found",
            "empty_fields": [],
        }

    return None
