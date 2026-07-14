"""区间增长排名查询 SQL 生成节点。"""

from __future__ import annotations

from agent.constants import DEFAULT_REPORT_PERIOD, TABLE_ALIASES
from agent.services.sql_builders import _metric_column_alias
from agent.state import AgentState


def _guard_trend_ranking_params(limit: int | None, rank_direction: str | None) -> None:
    if limit is None:
        raise ValueError("trend_ranking_query requires limit")
    if not isinstance(limit, int) or limit < 1 or limit > 50:
        raise ValueError(f"invalid trend ranking limit: {limit}")
    if rank_direction not in ("asc", "desc"):
        raise ValueError(f"invalid rank_direction: {rank_direction}")


def build_base_trend_ranking_sql(
    *,
    metric: dict,
    start_year: int,
    end_year: int,
    report_period: str,
    rank_direction: str,
    limit: int,
) -> str:
    table = metric["table"]
    field = metric["field"]
    sql_direction = "DESC" if rank_direction == "desc" else "ASC"

    return f"""
    SELECT
        c.stock_code,
        c.stock_abbr,
        c.company_name,
        start_t.report_year AS start_year,
        end_t.report_year AS end_year,
        start_t.report_period,
        start_t.{field} AS start_value,
        end_t.{field} AS end_value,
        (
            CAST(end_t.{field} AS DOUBLE PRECISION)
            - CAST(start_t.{field} AS DOUBLE PRECISION)
        ) / NULLIF(CAST(start_t.{field} AS DOUBLE PRECISION), 0) AS growth_rate
    FROM {table} start_t
    JOIN {table} end_t
        ON start_t.stock_code = end_t.stock_code
       AND start_t.report_period = end_t.report_period
    JOIN company_dim c
        ON start_t.stock_code = c.stock_code
    WHERE start_t.report_year = {start_year}
      AND end_t.report_year = {end_year}
      AND start_t.report_period = '{report_period}'
      AND start_t.{field} IS NOT NULL
      AND end_t.{field} IS NOT NULL
      AND start_t.{field} != 0
    ORDER BY growth_rate {sql_direction}, c.stock_code ASC
    LIMIT {limit}
    """


def generate_trend_ranking_sql_node(state: AgentState) -> dict:
    if state.get("need_clarification"):
        return {}

    metrics = state.get("metrics") or []
    if not metrics:
        return {
            "need_clarification": True,
            "clarification_question": "请说明你要按哪个指标的区间增长率排名。",
            "error_type": "missing_metric",
        }

    metric = metrics[0]
    if metric.get("metric_type", "base") != "base":
        return {
            "need_clarification": True,
            "clarification_question": "V0.5.4 暂不支持派生指标的区间增长排名。",
            "error_type": "unsupported_metric_type",
        }

    table = metric.get("table", "")
    if table not in TABLE_ALIASES:
        return {
            "need_clarification": True,
            "clarification_question": f"暂不支持指标表 {table} 的区间增长排名查询。",
            "error_type": "unsupported_metric_type",
        }

    start_year = state.get("start_year")
    end_year = state.get("end_year")
    if start_year is None:
        return {
            "need_clarification": True,
            "clarification_question": "请说明区间增长排名的起始年份。",
            "error_type": "missing_start_year",
        }
    if end_year is None:
        return {
            "need_clarification": True,
            "clarification_question": "请说明区间增长排名的结束年份。",
            "error_type": "missing_end_year",
        }

    report_period = state.get("report_period") or DEFAULT_REPORT_PERIOD
    rank_direction = state.get("rank_direction")
    limit = state.get("limit")

    try:
        _guard_trend_ranking_params(limit, rank_direction)
    except ValueError as exc:
        return {
            "need_clarification": True,
            "clarification_question": f"区间增长排名参数异常：{exc}",
            "error_type": "invalid_limit",
        }

    sql = build_base_trend_ranking_sql(
        metric=metric,
        start_year=start_year,
        end_year=end_year,
        report_period=report_period,
        rank_direction=rank_direction,
        limit=limit,
    )

    return {
        "sql": sql,
        "sql_metadata": {
            "metric_key": metric["metric_key"],
            "metric_name": metric["metric_name"],
            "metric_type": "base",
            "table": table,
            "field": metric["field"],
            "column_alias": _metric_column_alias(metric),
            "start_year": start_year,
            "end_year": end_year,
            "rank_direction": rank_direction,
            "limit": limit,
            "change_metric": "growth_rate",
        },
    }


__all__ = [
    "_guard_trend_ranking_params",
    "build_base_trend_ranking_sql",
    "generate_trend_ranking_sql_node",
]
