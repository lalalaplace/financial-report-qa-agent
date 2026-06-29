"""区间增长排名查询准入校验器。

V0.5.4 仅支持：全市场、明确起止年份、单个 base 指标、按 growth_rate 排名。
"""

from agent.constants import DEFAULT_REPORT_PERIOD
from agent.state import AgentState


_MIN_LIMIT = 1
_MAX_LIMIT = 50
_VALID_RANK_DIRECTIONS = {"asc", "desc"}

_ERROR_MESSAGES = {
    "missing_metric": "请说明你想按哪个指标的区间增长率排名，例如营业收入、净利润。",
    "multiple_metrics_not_supported": "当前区间增长排名仅支持单个指标，请选择一个指标。",
    "multiple_companies_not_supported": (
        "当前区间增长排名仅支持全市场范围，暂不支持限定特定公司的区间排名。"
    ),
    "missing_start_year": "请说明区间排名的起始年份，例如 2022 到 2024 年营业收入增长最快的前 10 家公司。",
    "missing_end_year": "请说明区间排名的结束年份，例如 2022 到 2024 年营业收入增长最快的前 10 家公司。",
    "invalid_year_range": "区间增长排名要求起始年份小于结束年份。",
    "unsupported_trend_ranking_time_mode": "区间增长排名仅支持明确起止年份，暂不支持近三年这类相对年份。",
    "missing_rank_direction": "请说明区间排名方向，例如增长最快、增长率最低或下降最大。",
    "missing_limit": "请说明你想查看前多少家公司，例如前 10 家。",
    "invalid_limit": f"区间增长排名数量需要在 {_MIN_LIMIT} 到 {_MAX_LIMIT} 之间。",
    "unsupported_change_metric": "区间增长排名的 change_metric 必须为 growth_rate。",
    "unsupported_metric_type": (
        "V0.5.4 暂不支持派生指标的区间增长排名，请改用营业收入、净利润、总资产等基础指标。"
    ),
}


def _fail(error_type: str, *, detail: str | None = None) -> dict:
    return {
        "need_clarification": True,
        "clarification_question": detail or _ERROR_MESSAGES[error_type],
        "business_success": False,
        "error_type": error_type,
        "empty_fields": [],
    }


def validate(state: AgentState) -> dict:
    metrics = state.get("metrics") or []
    companies = state.get("companies") or []
    company_mentions = state.get("company_mentions") or []
    time_range = state.get("time_range") or {}
    time_mode = time_range.get("mode") or state.get("time_mode") or "unspecified"
    start_year = state.get("start_year") or time_range.get("start_year")
    end_year = state.get("end_year") or time_range.get("end_year")
    report_period = state.get("report_period") or DEFAULT_REPORT_PERIOD
    rank_direction = state.get("rank_direction")
    limit = state.get("limit")
    change_metric = state.get("change_metric") or "growth_rate"

    if not metrics:
        return _fail("missing_metric")
    if len(metrics) > 1:
        names = "、".join(m.get("metric_name", "") for m in metrics)
        return _fail(
            "multiple_metrics_not_supported",
            detail=f"当前区间增长排名仅支持单个指标，你提到了多个指标（{names}），请选择一个。",
        )

    if companies or company_mentions:
        return _fail("multiple_companies_not_supported")

    if start_year is None:
        return _fail("missing_start_year")
    if end_year is None:
        return _fail("missing_end_year")
    if start_year >= end_year:
        return _fail("invalid_year_range")

    if time_mode not in ("explicit_range", "year_range"):
        return _fail("unsupported_trend_ranking_time_mode")

    if rank_direction not in _VALID_RANK_DIRECTIONS:
        return _fail("missing_rank_direction")

    if limit is None:
        return _fail("missing_limit")

    if not isinstance(limit, int) or limit < _MIN_LIMIT or limit > _MAX_LIMIT:
        return _fail(
            "invalid_limit",
            detail=f"区间增长排名数量需要在 {_MIN_LIMIT} 到 {_MAX_LIMIT} 之间，你输入的是 {limit}。",
        )

    if change_metric != "growth_rate":
        return _fail("unsupported_change_metric")

    metric = metrics[0]
    if metric.get("metric_type", "base") != "base":
        return _fail("unsupported_metric_type")

    return {
        "need_clarification": False,
        "clarification_question": None,
        "error_type": None,
        "empty_fields": [],
        "start_year": start_year,
        "end_year": end_year,
        "report_years": [start_year, end_year],
        "report_period": report_period,
        "rank_direction": rank_direction,
        "limit": limit,
        "change_metric": "growth_rate",
    }


__all__ = ["validate"]
