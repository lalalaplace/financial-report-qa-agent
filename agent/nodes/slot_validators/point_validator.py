"""单年指标点查验证器。"""

from agent.state import AgentState
from agent.constants import DEFAULT_REPORT_PERIOD
from agent.utils.year_utils import _metric_for_latest_year_lookup, _query_latest_fy_year


def validate(
    state: AgentState,
    report_period: str,
    warnings: list[str],
) -> dict:
    report_year = state.get("report_year")
    companies = state.get("companies") or []
    company_candidates = state.get("company_candidates") or []
    metrics = state.get("metrics") or []
    metric_candidates = state.get("metric_candidates") or []

    if report_year is None:
        company_for_lookup = companies[0] if companies else company_candidates[0]
        metric_for_lookup = metrics[0] if metrics else metric_candidates[0]
        latest_year = _query_latest_fy_year(company_for_lookup, metric_for_lookup)
        if latest_year is None:
            return {
                "need_clarification": True,
                "clarification_question": "请说明你要查询的报告年份；当前数据库未能确定最新年报年份。",
                "business_success": False,
                "error_type": "need_clarification",
                "empty_fields": [],
            }
        report_year = latest_year
        warnings.append(
            f"你未指定年份，我将默认查询数据库中最新年报（{latest_year} 年）。"
        )

    return {
        "report_year": report_year,
        "report_period": report_period,
        "need_clarification": False,
        "clarification_question": None,
        "error_type": None,
        "warnings": warnings,
    }
