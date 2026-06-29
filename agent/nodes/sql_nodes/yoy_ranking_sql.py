"""同比排名查询 SQL 生成节点。"""

from __future__ import annotations

from agent.constants import DEFAULT_REPORT_PERIOD, TABLE_ALIASES
from agent.services.sql_builders import _metric_column_alias
from agent.state import AgentState


def _guard_yoy_ranking_params(limit: int | None, rank_direction: str | None) -> None:
    if limit is None:
        raise ValueError("yoy_ranking_query requires limit")
    if not isinstance(limit, int) or limit < 1 or limit > 50:
        raise ValueError(f"invalid yoy ranking limit: {limit}")
    if rank_direction not in ("asc", "desc"):
        raise ValueError(f"invalid rank_direction: {rank_direction}")


def build_base_yoy_ranking_sql(
    *,
    metric: dict,
    report_year: int,
    report_period: str,
    rank_direction: str,
    limit: int,
) -> str:
    table = metric["table"]
    field = metric["field"]
    curr_alias = "curr"
    prev_alias = "prev"
    sql_direction = "DESC" if rank_direction == "desc" else "ASC"

    return f"""
    SELECT
        c.stock_code,
        c.stock_abbr,
        c.company_name,
        {curr_alias}.report_year,
        '{report_period}' AS report_period,
        {curr_alias}.{field} AS current_value,
        {prev_alias}.{field} AS previous_value,
        (
            CAST({curr_alias}.{field} AS DOUBLE)
            - CAST({prev_alias}.{field} AS DOUBLE)
        ) / NULLIF(CAST({prev_alias}.{field} AS DOUBLE), 0) AS yoy_rate
    FROM {table} {curr_alias}
    JOIN {table} {prev_alias}
        ON {curr_alias}.stock_code = {prev_alias}.stock_code
       AND {curr_alias}.report_year = {prev_alias}.report_year + 1
       AND {curr_alias}.report_period = {prev_alias}.report_period
    JOIN company_dim c
        ON {curr_alias}.stock_code = c.stock_code
    WHERE {curr_alias}.report_year = {report_year}
      AND {curr_alias}.report_period = '{report_period}'
      AND {curr_alias}.{field} IS NOT NULL
      AND {prev_alias}.{field} IS NOT NULL
      AND {prev_alias}.{field} != 0
    ORDER BY yoy_rate {sql_direction}, c.stock_code ASC
    LIMIT {limit}
    """


def generate_yoy_ranking_sql_node(state: AgentState) -> dict:
    if state.get("need_clarification"):
        return {}

    metrics = state.get("metrics") or []
    if not metrics:
        return {
            "need_clarification": True,
            "clarification_question": "请说明你要按哪个指标的同比变化排名。",
            "error_type": "missing_metric",
        }

    metric = metrics[0]
    if metric.get("metric_type", "base") != "base":
        return {
            "need_clarification": True,
            "clarification_question": "V0.5.3 暂不支持派生指标的同比排名。",
            "error_type": "unsupported_metric_type",
        }

    table = metric.get("table", "")
    if table not in TABLE_ALIASES:
        return {
            "need_clarification": True,
            "clarification_question": f"暂不支持指标表 {table} 的同比排名查询。",
            "error_type": "unsupported_metric_type",
        }

    report_year = state.get("report_year")
    if report_year is None:
        return {
            "need_clarification": True,
            "clarification_question": "请说明同比排名的年份。",
            "error_type": "missing_year",
        }

    report_period = state.get("report_period") or DEFAULT_REPORT_PERIOD
    rank_direction = state.get("rank_direction")
    limit = state.get("limit")

    try:
        _guard_yoy_ranking_params(limit, rank_direction)
    except ValueError as exc:
        return {
            "need_clarification": True,
            "clarification_question": f"同比排名参数异常：{exc}",
            "error_type": "invalid_limit",
        }

    sql = build_base_yoy_ranking_sql(
        metric=metric,
        report_year=report_year,
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
            "rank_direction": rank_direction,
            "limit": limit,
            "change_metric": "yoy_rate",
        },
    }


__all__ = [
    "_guard_yoy_ranking_params",
    "build_base_yoy_ranking_sql",
    "generate_yoy_ranking_sql_node",
]
