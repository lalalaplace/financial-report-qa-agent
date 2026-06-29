"""槽位解析与准入校验节点。"""

from __future__ import annotations

from typing import Any

from agent.constants import DEFAULT_REPORT_PERIOD, DEFAULT_QUERY_TYPE
from agent.schemas.query_plan import normalize_compare_spec
from agent.state import AgentState
from agent.tools.company_tools import resolve_company
from agent.tools.metric_tools import load_metric_dictionary, map_metrics
from agent.validators.clarification import normalize_clarification_result

from agent.services.compare_service import _compare_spec_payload, _directed_compare_reference_error, _get_compare_spec
from agent.utils.year_utils import _metric_for_latest_year_lookup, _query_latest_fy_year

from agent.nodes.slot_validators import common
from agent.nodes.slot_validators import ranking_validator
from agent.nodes.slot_validators import yoy_ranking_validator
from agent.nodes.slot_validators import trend_ranking_validator
from agent.nodes.slot_validators import rank_position_validator
from agent.nodes.slot_validators import compare_validator
from agent.nodes.slot_validators import compare_trend_validator
from agent.nodes.slot_validators import compare_yoy_validator
from agent.nodes.slot_validators import yoy_validator
from agent.nodes.slot_validators import derived_validator
from agent.nodes.slot_validators import trend_validator
from agent.nodes.slot_validators import point_validator


def _collect_companies(mentions: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    """逐条调用 resolve_company，并按 stock_code 去重合并。
    Returns:
        (candidates, unresolved_mentions, ambiguous_mentions)
    """
    all_candidates: list[dict[str, Any]] = []
    seen_codes: set[str] = set()
    unresolved: list[str] = []
    ambiguous: list[str] = []
    for mention in mentions:
        result = resolve_company(mention)
        mention_candidates = result.get("candidates", [])
        if not mention_candidates:
            unresolved.append(mention)
            continue
        if result.get("need_clarification"):
            ambiguous.append(mention)
        for candidate in mention_candidates:
            code = candidate.get("stock_code")
            if code and code not in seen_codes:
                seen_codes.add(code)
                all_candidates.append(candidate)
    return all_candidates, unresolved, ambiguous

def resolve_company_node(state: AgentState) -> dict:
    company_mentions = state.get("company_mentions") or []
    intent_type = state.get("intent_type") or DEFAULT_QUERY_TYPE

    if company_mentions:
        candidates, unresolved, ambiguous = _collect_companies(company_mentions)
    elif intent_type in ("ranking_query", "yoy_ranking_query", "trend_ranking_query"):
        return {
            "companies": [],
            "company_candidates": [],
            "company_resolution_status": "not_required",
        }
    else:
        result = resolve_company(state["user_question"])
        candidates = result.get("candidates", [])
        unresolved = []
        ambiguous = []

    if intent_type in ("company_compare_query", "company_compare_trend_query", "company_compare_yoy_query"):
        status = "resolved" if len(candidates) >= 2 and not ambiguous and not unresolved else "needs_validation"
        return {
            "companies": candidates if status == "resolved" else [],
            "company_candidates": [] if status == "resolved" else candidates,
            "company_resolution_status": status,
        }

    if len(candidates) == 1 and not ambiguous and not unresolved:
        return {
            "companies": candidates,
            "company_candidates": [],
            "company_resolution_status": "resolved",
        }
    status = "unresolved" if unresolved or not candidates else "ambiguous"
    return {
        "companies": [],
        "company_candidates": candidates,
        "company_resolution_status": status,
    }

def _normalize_metric(raw: dict[str, Any]) -> dict[str, Any]:
    metric_type = raw.get("metric_type", "base")
    metric: dict[str, Any] = {
        "metric_key": raw["metric_key"],
        "metric_name": raw["metric_name"],
        "metric_type": metric_type,
        "unit": raw.get("unit", "yuan"),
    }

    if metric_type == "base":
        metric["table"] = raw.get("table", "")
        metric["field"] = raw.get("field", "")
    elif metric_type == "derived":
        formula = raw.get("formula") or {}
        metric["formula"] = {
            "numerator": formula.get("numerator", ""),
            "denominator": formula.get("denominator", ""),
        }
        metric["scale"] = raw.get("scale", 1)
        metric["precision"] = raw.get("precision", 2)

    if raw.get("aliases"):
        metric["aliases"] = raw["aliases"]
    if raw.get("query_types"):
        metric["query_types"] = raw["query_types"]
    if raw.get("description"):
        metric["description"] = raw["description"]

    return metric

def map_metric_node(state: AgentState) -> dict:
    metric_mentions = state.get("metric_mentions") or []

    if metric_mentions:
        all_metrics: list[dict[str, Any]] = []
        seen_keys: set[str] = set()
        has_ambiguous_metric = False

        for mention in metric_mentions:
            result = map_metrics(mention)
            if result.get("need_clarification"):
                has_ambiguous_metric = True
            for metric in result.get("metrics", []):
                key = metric.get("metric_key")
                if key and key not in seen_keys:
                    seen_keys.add(key)
                    all_metrics.append(_normalize_metric(metric))

        if has_ambiguous_metric:
            return {
                "metrics": [],
                "metric_candidates": all_metrics,
                "metric_resolution_status": "ambiguous",
            }

        return {
            "metrics": all_metrics,
            "metric_candidates": [],
            "metric_resolution_status": "resolved" if all_metrics else "unresolved",
        }


    result = map_metrics(state["user_question"])
    all_metrics = [_normalize_metric(m) for m in result.get("metrics", [])]
    if result.get("need_clarification"):
        return {
            "metrics": [],
            "metric_candidates": all_metrics,
            "metric_resolution_status": "ambiguous",
        }
    return {
        "metrics": all_metrics,
        "metric_candidates": [],
        "metric_resolution_status": "resolved" if all_metrics else "unresolved",
    }

def check_slots_node(state: AgentState) -> dict:
    """准入检查：按 intent_type 路由到对应 validator。"""
    # 1. need_clarification 透传
    pre = common.passthrough_clarification(state)
    if pre:
        return pre

    intent_type = state.get("intent_type") or DEFAULT_QUERY_TYPE

    # 2. 排名查询
    if intent_type == "ranking_query":
        return normalize_clarification_result(ranking_validator.validate(state), state)
    if intent_type == "yoy_ranking_query":
        return normalize_clarification_result(yoy_ranking_validator.validate(state), state)
    if intent_type == "trend_ranking_query":
        return normalize_clarification_result(trend_ranking_validator.validate(state), state)
    if intent_type == "rank_position_query":
        return normalize_clarification_result(rank_position_validator.validate(state), state)

    # 3-5. 对比类查询（各 validator 内部完成准入）
    if intent_type == "company_compare_trend_query":
        return normalize_clarification_result(compare_trend_validator.validate(state), state)
    if intent_type == "company_compare_yoy_query":
        return normalize_clarification_result(compare_yoy_validator.validate(state), state)
    if intent_type == "company_compare_query":
        return normalize_clarification_result(compare_validator.validate(state), state)

    # 6-9. 非对比类公共公司/指标预检
    companies = state.get("companies") or []
    company_candidates = state.get("company_candidates") or []
    metrics = state.get("metrics") or []
    metric_candidates = state.get("metric_candidates") or []

    pre = common.company_metric_precheck(companies, company_candidates, metrics, metric_candidates)
    if pre:
        return normalize_clarification_result(pre, state)

    # 10. report_period 补齐默认值
    report_period = state.get("report_period") or DEFAULT_REPORT_PERIOD

    # 11-14. 非对比类 intent 专用验证
    warnings = list(state.get("warnings") or [])

    if intent_type == "yoy_query":
        return normalize_clarification_result(yoy_validator.validate(state, report_period, warnings), state)
    if intent_type == "derived_metric_query":
        return normalize_clarification_result(derived_validator.validate(state, report_period, warnings), state)
    if intent_type == "trend_query":
        return normalize_clarification_result(trend_validator.validate(state, report_period, warnings), state)

    return normalize_clarification_result(point_validator.validate(state, report_period, warnings), state)


__all__ = ['_collect_companies', 'resolve_company_node', '_normalize_metric', 'map_metric_node', 'check_slots_node']
