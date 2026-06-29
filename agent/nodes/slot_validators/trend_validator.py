"""趋势查询验证器。"""

from agent.state import AgentState
from agent.constants import DEFAULT_REPORT_PERIOD
from agent.schemas.query_plan import DEFAULT_TREND_RECENT_N_YEARS
from agent.utils.year_utils import _metric_for_latest_year_lookup, _query_latest_fy_year


def validate(
    state: AgentState,
    report_period: str,
    warnings: list[str],
) -> dict:
    metrics = state.get("metrics") or []
    companies = state.get("companies") or []
    company_candidates = state.get("company_candidates") or []
    metric_candidates = state.get("metric_candidates") or []

    metric_types = {m.get("metric_type", "base") for m in metrics}
    if "base" in metric_types and "derived" in metric_types:
        return {
            "need_clarification": True,
            "clarification_question": "当前版本暂不支持原始指标和派生指标混合趋势查询。你可以分别查询原始指标趋势和派生指标趋势。",
            "business_success": False,
            "error_type": "unsupported_mixed_trend",
            "empty_fields": [],
        }

    time_mode = state.get("time_mode")
    if not time_mode or time_mode == "unspecified":
        time_mode = "recent_n"
        recent_n = state.get("recent_n_years") or DEFAULT_TREND_RECENT_N_YEARS
    else:
        recent_n = state.get("recent_n_years")

    report_year = state.get("report_year")
    if report_year is None:
        company_for_lookup = companies[0] if companies else company_candidates[0]
        metric_for_lookup = metrics[0] if metrics else metric_candidates[0]
        latest_year = _query_latest_fy_year(company_for_lookup, metric_for_lookup)
        if latest_year is None:
            return {
                "need_clarification": True,
                "clarification_question": "请说明趋势查询的报告年份；当前数据库未能确定最新年报年份。",
                "business_success": False,
                "error_type": "need_clarification",
                "empty_fields": [],
            }
        report_year = latest_year
        warnings.append(
            f"你未指定年份，我将默认以最新年报（{latest_year} 年）为终点进行趋势查询。"
        )

    return {
        "report_year": report_year,
        "report_period": report_period,
        "time_mode": time_mode,
        "recent_n_years": recent_n,
        "need_clarification": False,
        "clarification_question": None,
        "error_type": None,
        "warnings": warnings,
    }
