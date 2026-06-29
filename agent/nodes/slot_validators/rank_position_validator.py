"""指定公司排名位置查询的槽位校验。"""

from agent.constants import DEFAULT_REPORT_PERIOD
from agent.state import AgentState


_VALID_RANK_DIRECTIONS = {"asc", "desc"}

_ERROR_MESSAGES = {
    "missing_company": "请说明要查询哪家公司的排名。",
    "multiple_companies_not_supported": "当前排名位置查询只支持单家公司，请只保留一家目标公司。",
    "missing_metric": "请说明要查询哪个指标的排名。",
    "multiple_metrics_not_supported": "当前排名位置查询只支持单个指标，请只保留一个指标。",
    "missing_year": "请说明要查询哪一年的排名。",
    "unsupported_rank_position_time_mode": "排名位置查询只支持单一年份，暂不支持多年区间或趋势排名。",
    "missing_rank_direction": "请说明排名方向，例如从高到低或从低到高。",
}


def _fail(error_type: str) -> dict:
    return {
        "need_clarification": True,
        "clarification_question": _ERROR_MESSAGES.get(error_type, "请补充排名查询条件。"),
        "business_success": False,
        "error_type": error_type,
        "empty_fields": [],
    }


def _ok(**kwargs) -> dict:
    return {
        "need_clarification": False,
        "clarification_question": None,
        "error_type": None,
        "empty_fields": [],
        **kwargs,
    }


def validate(state: AgentState) -> dict:
    companies = state.get("companies") or []
    metrics = state.get("metrics") or []
    report_year = state.get("report_year")
    report_period = state.get("report_period") or DEFAULT_REPORT_PERIOD
    time_range = state.get("time_range") or {}
    time_mode = state.get("time_mode") or time_range.get("mode", "unspecified")
    rank_direction = state.get("rank_direction")

    if len(companies) == 0:
        return _fail("missing_company")
    if len(companies) > 1:
        return _fail("multiple_companies_not_supported")
    if len(metrics) == 0:
        return _fail("missing_metric")
    if len(metrics) > 1:
        return _fail("multiple_metrics_not_supported")
    if not report_year:
        return _fail("missing_year")
    if time_mode != "single_year":
        return _fail("unsupported_rank_position_time_mode")
    if rank_direction not in _VALID_RANK_DIRECTIONS:
        return _fail("missing_rank_direction")

    return _ok(
        report_year=report_year,
        report_period=report_period,
        rank_direction=rank_direction,
        limit=None,
    )


__all__ = ["validate"]
