"""多公司趋势对比验证器。"""

from agent.state import AgentState
from agent.constants import DEFAULT_REPORT_PERIOD
from agent.schemas.query_plan import DEFAULT_TREND_RECENT_N_YEARS
from agent.services.compare_service import (
    _compare_spec_payload,
    _directed_compare_reference_error,
    _get_compare_spec,
)
from agent.utils.year_utils import _metric_for_latest_year_lookup, _query_latest_fy_year


def validate(state: AgentState) -> dict:
    compare_spec = _get_compare_spec(state)
    companies = state.get("companies") or []
    metrics = state.get("metrics") or []
    warnings = list(state.get("warnings") or [])

    if len(companies) < 2:
        return {
            "need_clarification": True,
            "clarification_question": "请提供至少两家公司进行趋势对比。",
            "business_success": False,
            "error_type": "clarify_company",
            "empty_fields": [],
        }

    if not metrics:
        return {
            "need_clarification": True,
            "clarification_question": "请说明你要对比趋势的财务指标。",
            "business_success": False,
            "error_type": "clarify_metric",
            "empty_fields": [],
        }

    metric_types = {m.get("metric_type", "base") for m in metrics}
    if "base" in metric_types and "derived" in metric_types:
        return {
            "need_clarification": True,
            "clarification_question": "当前版本暂不支持原始指标和派生指标混合趋势对比，请分别查询。",
            "business_success": False,
            "error_type": "unsupported_mixed_compare_trend",
            "empty_fields": [],
        }

    report_period = state.get("report_period") or DEFAULT_REPORT_PERIOD
    time_mode = state.get("time_mode")
    if not time_mode or time_mode == "unspecified":
        time_mode = "recent_n"
        recent_n = state.get("recent_n_years") or DEFAULT_TREND_RECENT_N_YEARS
    else:
        recent_n = state.get("recent_n_years")

    if time_mode == "explicit_range":
        start_year = state.get("start_year")
        end_year = state.get("end_year")
        if start_year is None or end_year is None:
            return {
                "need_clarification": True,
                "clarification_question": "公司趋势对比需要明确的年份范围，例如 2022 到 2024。",
                "business_success": False,
                "error_type": "clarify_year_range",
                "empty_fields": [],
            }
        report_year = end_year
        report_years = list(range(start_year, end_year + 1))
    else:
        report_year = state.get("report_year")
        if report_year is None:
            latest_metric = _metric_for_latest_year_lookup(metrics[0])
            latest_year = _query_latest_fy_year(companies[0], latest_metric)
            if latest_year is None:
                return {
                    "need_clarification": True,
                    "clarification_question": "请说明趋势对比的报告年份；当前数据库未能确定最新年报年份。",
                    "business_success": False,
                    "error_type": "need_clarification",
                    "empty_fields": [],
                }
            report_year = latest_year
            warnings.append(
                f"你未指定年份，我将默认以最新年报（{latest_year} 年）为终点进行趋势对比。"
            )
        recent_n = recent_n or 5
        report_years = list(range(report_year - recent_n + 1, report_year + 1))

    if len(report_years) < 2:
        return {
            "need_clarification": True,
            "clarification_question": "公司趋势对比需要至少两个报告年份，例如 2022 到 2024，或近三年。",
            "business_success": False,
            "error_type": "clarify_year",
            "empty_fields": [],
        }

    compare_reference_error = _directed_compare_reference_error(compare_spec or {})
    if compare_reference_error:
        return compare_reference_error

    return {
        "report_year": report_year,
        "report_period": report_period,
        "time_mode": time_mode,
        "recent_n_years": recent_n,
        "report_years": report_years,
        "compare_spec": compare_spec,
        "need_clarification": False,
        "clarification_question": None,
        "error_type": None,
        "warnings": warnings,
    }
