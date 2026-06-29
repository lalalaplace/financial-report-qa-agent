"""同比查询验证器。"""

from agent.state import AgentState
from agent.constants import DEFAULT_REPORT_PERIOD


def validate(
    state: AgentState,
    report_period: str,
    warnings: list[str],
) -> dict:
    metrics = state.get("metrics") or []

    report_year = state.get("report_year")
    if report_year is None:
        return {
            "need_clarification": True,
            "clarification_question": "请问你想查询哪一年的同比变化？例如 2024 年营业收入同比增长多少。",
            "business_success": False,
            "error_type": "missing_report_year",
            "empty_fields": [],
        }
    if not isinstance(report_year, int) or report_year < 1900:
        return {
            "need_clarification": True,
            "clarification_question": f"报告年份 {report_year} 无效，请提供有效的年份（如 2024）。",
            "business_success": False,
            "error_type": "invalid_report_year",
            "empty_fields": [],
        }

    metric_types = {m.get("metric_type", "base") for m in metrics}
    if "base" in metric_types and "derived" in metric_types:
        return {
            "need_clarification": False,
            "business_success": False,
            "error_type": "unsupported_mixed_yoy",
            "empty_fields": [],
        }

    return {
        "report_year": report_year,
        "report_period": report_period,
        "need_clarification": False,
        "clarification_question": None,
        "error_type": None,
        "warnings": warnings,
    }
