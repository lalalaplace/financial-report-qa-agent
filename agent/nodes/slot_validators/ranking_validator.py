"""排名查询验证器（V0.5.2）。

仅负责业务准入校验；结构合法性由 query_plan schema 保证。

V0.5.2 支持边界：单年 + 单指标（base 或 derived）+ 全公司范围 + TopN/BottomN/第一名/最后一名。
"""

from agent.state import AgentState
from agent.constants import DEFAULT_REPORT_PERIOD

# V0.5.2：limit 范围 1-50
_MIN_RANK_LIMIT = 1
_MAX_RANK_LIMIT = 50
_VALID_RANK_DIRECTIONS = {"asc", "desc"}

# ── 错误类型与提示文案 ──
_ERROR_MESSAGES = {
    "missing_metric": "请说明你想按什么指标排名，例如营业收入、净利润等。",
    "missing_year": "请说明排名的年份，例如 2024 年营业收入最高的前 10 家公司。",
    "missing_rank_direction": "请说明排名方向，例如「最高」或「最低」。",
    "missing_limit": "请说明你想查看前多少家公司，例如前 10 家。",
    "unsupported_ranking_time_mode": "排名查询仅支持单一年份（如 2024 年），暂不支持跨年份范围排名。",
    "multiple_companies_not_supported": (
        "当前排名查询仅支持全市场范围，暂不支持限定特定公司的排名。"
        "如需对比特定公司，请使用公司对比功能。"
    ),
}


def _fail(error_type: str, *, detail: str = "") -> dict:
    msg = _ERROR_MESSAGES.get(error_type, "")
    if detail:
        msg = detail
    return {
        "need_clarification": True,
        "clarification_question": msg,
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
    """排名查询准入校验，返回 state 更新字典。"""
    metrics = state.get("metrics") or []
    companies = state.get("companies") or []
    company_mentions = state.get("company_mentions") or []
    rank_direction = state.get("rank_direction")
    limit = state.get("limit")
    report_year = state.get("report_year")
    report_period = state.get("report_period") or DEFAULT_REPORT_PERIOD
    time_range = state.get("time_range") or {}
    time_mode = time_range.get("mode", "unspecified")

    # 1. 必须有且只有一个指标
    if len(metrics) == 0:
        return _fail("missing_metric")
    if len(metrics) > 1:
        metric_names = "、".join([m.get("metric_name", "") for m in metrics])
        return _fail(
            "multiple_metrics_not_supported",
            detail=f"当前仅支持按单个指标排名，你提到了多个指标（{metric_names}），请选择一个。",
        )

    # 2. 不允许指定公司（全市场排名）
    if companies or company_mentions:
        return _fail("multiple_companies_not_supported")

    # 3. 必须有单一年份
    if not report_year:
        return _fail("missing_year")

    # 4. 时间模式必须是 single_year
    if time_mode != "single_year":
        return _fail("unsupported_ranking_time_mode")

    # 5. 必须有 rank_direction
    if rank_direction not in _VALID_RANK_DIRECTIONS:
        return _fail("missing_rank_direction")

    # 6. 必须有 limit
    if limit is None:
        return _fail("missing_limit")

    # 7. limit 范围校验（V0.5.2：1-50）
    if not isinstance(limit, int) or limit < _MIN_RANK_LIMIT or limit > _MAX_RANK_LIMIT:
        return _fail(
            "invalid_limit",
            detail=f"排名数量需在 {_MIN_RANK_LIMIT} 到 {_MAX_RANK_LIMIT} 之间，你输入的是 {limit}。",
        )

    return _ok(
        rank_direction=rank_direction,
        limit=limit,
        report_year=report_year,
        report_period=report_period,
    )
