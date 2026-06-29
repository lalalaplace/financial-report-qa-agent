"""多公司同比对比验证器。"""

from agent.state import AgentState
from agent.constants import DEFAULT_REPORT_PERIOD
from agent.services.compare_service import (
    _compare_spec_payload,
    _directed_compare_reference_error,
    _get_compare_spec,
)


def validate(state: AgentState) -> dict:
    compare_spec = _get_compare_spec(state)
    companies = state.get("companies") or []
    metrics = state.get("metrics") or []
    warnings = list(state.get("warnings") or [])

    if len(companies) < 2:
        return {
            "need_clarification": True,
            "clarification_question": "请提供至少两家公司进行同比对比。",
            "business_success": False,
            "error_type": "clarify_company",
            "empty_fields": [],
        }

    if len(metrics) < 1:
        return {
            "need_clarification": True,
            "clarification_question": "请说明你要对比同比变化的财务指标。",
            "business_success": False,
            "error_type": "clarify_metric",
            "empty_fields": [],
        }

    report_year = state.get("report_year")
    if report_year is None:
        return {
            "need_clarification": True,
            "clarification_question": "请说明同比对比的年份，例如 2024 年。",
            "business_success": False,
            "error_type": "clarify_year",
            "empty_fields": [],
        }

    metric_types = {m.get("metric_type", "base") for m in metrics}
    if "base" in metric_types and "derived" in metric_types:
        return {
            "need_clarification": True,
            "clarification_question": "当前版本暂不支持原始指标和派生指标混合同比对比，请分别查询。",
            "business_success": False,
            "error_type": "unsupported_mixed_compare_yoy",
            "empty_fields": [],
        }

    report_period = state.get("report_period") or DEFAULT_REPORT_PERIOD
    report_years = state.get("report_years") or [report_year - 1, report_year]
    compare_reference_error = _directed_compare_reference_error(compare_spec or {})
    if compare_reference_error:
        return compare_reference_error

    return {
        "report_year": report_year,
        "report_period": report_period,
        "time_mode": state.get("time_mode") or "single_year",
        "report_years": report_years,
        "compare_spec": compare_spec,
        "need_clarification": False,
        "clarification_question": None,
        "error_type": None,
        "warnings": warnings,
    }
