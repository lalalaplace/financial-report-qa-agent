"""派生指标查询验证器。"""

from agent.state import AgentState
from agent.constants import DEFAULT_REPORT_PERIOD


def validate(
    state: AgentState,
    report_period: str,
    warnings: list[str],
) -> dict:
    report_year = state.get("report_year")
    if report_year is None:
        return {
            "need_clarification": True,
            "clarification_question": "派生指标查询需要明确的报告年份，例如 2024 年资产负债率是多少。",
            "business_success": False,
            "error_type": "need_clarification",
            "empty_fields": [],
        }
    if not isinstance(report_year, int) or report_year < 1900:
        return {
            "need_clarification": True,
            "clarification_question": f"报告年份 {report_year} 无效，请提供有效的年份（如 2024）。",
            "business_success": False,
            "error_type": "need_clarification",
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
