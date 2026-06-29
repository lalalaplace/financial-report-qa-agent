"""指定公司排名位置查询 SQL 生成节点。"""

from __future__ import annotations

from agent.constants import DEFAULT_REPORT_PERIOD, TABLE_ALIASES
from agent.nodes.sql_nodes.derived_common import resolve_derived_formula, resolve_derived_tables
from agent.services.sql_builders import _metric_column_alias
from agent.state import AgentState
from agent.tools.metric_tools import load_metric_dictionary


def _guard_rank_position_params(companies: list, metrics: list, rank_direction: str) -> None:
    if len(companies) != 1:
        raise ValueError("rank_position_query requires exactly one company")
    if len(metrics) != 1:
        raise ValueError("rank_position_query requires exactly one metric")
    if rank_direction not in ("asc", "desc"):
        raise ValueError(f"invalid rank_direction: {rank_direction}")


def build_base_rank_position_sql(
    *,
    metric: dict,
    company: dict,
    report_year: int,
    report_period: str,
    rank_direction: str,
) -> str:
    table = metric["table"]
    field = metric["field"]
    table_alias = TABLE_ALIASES[table]
    column_alias = _metric_column_alias(metric)
    sql_direction = "DESC" if rank_direction == "desc" else "ASC"
    stock_code = company["stock_code"].replace("'", "''")

    return f"""
    WITH ranked AS (
        SELECT
            c.stock_code,
            c.stock_abbr,
            c.company_name,
            {table_alias}.report_year,
            {table_alias}.report_period,
            {table_alias}.{field} AS {column_alias},
            RANK() OVER (
                ORDER BY {table_alias}.{field} {sql_direction}
            ) AS rank_no,
            COUNT(*) OVER () AS total_count
        FROM company_dim c
        JOIN {table} {table_alias}
            ON c.stock_code = {table_alias}.stock_code
        WHERE {table_alias}.report_year = {report_year}
          AND {table_alias}.report_period = '{report_period}'
          AND {table_alias}.{field} IS NOT NULL
    )
    SELECT
        stock_code,
        stock_abbr,
        company_name,
        report_year,
        report_period,
        {column_alias},
        rank_no,
        total_count
    FROM ranked
    WHERE stock_code = '{stock_code}'
    """


def build_derived_rank_position_sql(
    *,
    metric: dict,
    company: dict,
    num_info: dict,
    den_info: dict,
    num_table: str,
    den_table: str,
    num_alias: str,
    den_alias: str,
    report_year: int,
    report_period: str,
    rank_direction: str,
) -> str:
    column_alias = metric["metric_key"]
    num_field = num_info["field"]
    den_field = den_info["field"]
    sql_direction = "DESC" if rank_direction == "desc" else "ASC"
    stock_code = company["stock_code"].replace("'", "''")

    if num_table == den_table:
        safe_division = (
            f"ROUND(CAST({num_alias}.{num_field} AS DOUBLE) "
            f"/ NULLIF(CAST({num_alias}.{den_field} AS DOUBLE), 0), 8)"
        )
        from_clause = f"""
        FROM company_dim c
        JOIN {num_table} {num_alias}
            ON c.stock_code = {num_alias}.stock_code
        WHERE {num_alias}.report_year = {report_year}
          AND {num_alias}.report_period = '{report_period}'
          AND {num_alias}.{num_field} IS NOT NULL
          AND {num_alias}.{den_field} IS NOT NULL
          AND {num_alias}.{den_field} != 0
        """
        year_expr = f"{num_alias}.report_year"
        period_expr = f"{num_alias}.report_period"
    else:
        safe_division = (
            f"ROUND(CAST({num_alias}.{num_field} AS DOUBLE) "
            f"/ NULLIF(CAST({den_alias}.{den_field} AS DOUBLE), 0), 8)"
        )
        from_clause = f"""
        FROM company_dim c
        JOIN {num_table} {num_alias}
            ON c.stock_code = {num_alias}.stock_code
        JOIN {den_table} {den_alias}
            ON c.stock_code = {den_alias}.stock_code
           AND {den_alias}.report_year = {num_alias}.report_year
           AND {den_alias}.report_period = {num_alias}.report_period
        WHERE {num_alias}.report_year = {report_year}
          AND {num_alias}.report_period = '{report_period}'
          AND {num_alias}.{num_field} IS NOT NULL
          AND {den_alias}.{den_field} IS NOT NULL
          AND {den_alias}.{den_field} != 0
        """
        year_expr = f"{num_alias}.report_year"
        period_expr = f"{num_alias}.report_period"

    return f"""
    WITH metric_values AS (
        SELECT
            c.stock_code,
            c.stock_abbr,
            c.company_name,
            {year_expr} AS report_year,
            {period_expr} AS report_period,
            {safe_division} AS {column_alias}
        {from_clause}
    ),
    ranked AS (
        SELECT
            stock_code,
            stock_abbr,
            company_name,
            report_year,
            report_period,
            {column_alias},
            RANK() OVER (
                ORDER BY {column_alias} {sql_direction}
            ) AS rank_no,
            COUNT(*) OVER () AS total_count
        FROM metric_values
    )
    SELECT
        stock_code,
        stock_abbr,
        company_name,
        report_year,
        report_period,
        {column_alias},
        rank_no,
        total_count
    FROM ranked
    WHERE stock_code = '{stock_code}'
    """


def generate_rank_position_sql_node(state: AgentState) -> dict:
    if state.get("need_clarification"):
        return {}

    companies = state.get("companies") or []
    metrics = state.get("metrics") or []
    rank_direction = state.get("rank_direction") or "desc"
    report_year = state.get("report_year")
    report_period = state.get("report_period") or DEFAULT_REPORT_PERIOD

    try:
        _guard_rank_position_params(companies, metrics, rank_direction)
    except ValueError as exc:
        message = str(exc)
        if "company" in message:
            error_type = "missing_company"
        elif "metric" in message:
            error_type = "missing_metric"
        else:
            error_type = "missing_rank_direction"
        return {
            "need_clarification": True,
            "clarification_question": f"排名位置查询参数异常：{exc}",
            "error_type": error_type,
        }

    if report_year is None:
        return {
            "need_clarification": True,
            "clarification_question": "请说明排名查询的年份。",
            "error_type": "missing_year",
        }

    company = companies[0]
    metric = metrics[0]
    metric_type = metric.get("metric_type", "base")

    if metric_type == "base":
        table = metric.get("table", "")
        if table not in TABLE_ALIASES:
            return {
                "need_clarification": True,
                "clarification_question": f"暂不支持指标表 {table} 的排名位置查询。",
                "error_type": "unsupported_metric_type",
            }
        sql = build_base_rank_position_sql(
            metric=metric,
            company=company,
            report_year=report_year,
            report_period=report_period,
            rank_direction=rank_direction,
        )
        return {
            "sql": sql,
            "sql_metadata": {
                "metric_key": metric["metric_key"],
                "metric_name": metric["metric_name"],
                "metric_type": "base",
                "column_alias": _metric_column_alias(metric),
                "unit": metric.get("unit", "yuan"),
                "rank_direction": rank_direction,
            },
        }

    if metric_type == "derived":
        metric_dict = load_metric_dictionary()
        resolved = resolve_derived_formula(metric, metric_dict)
        if not resolved:
            return {
                "need_clarification": True,
                "clarification_question": f"派生指标 {metric.get('metric_name', '')} 的公式定义未找到。",
                "error_type": "unsupported_metric_type",
            }
        num_info, den_info = resolved
        tables = resolve_derived_tables(num_info, den_info)
        if not tables:
            return {
                "need_clarification": True,
                "clarification_question": f"派生指标 {metric.get('metric_name', '')} 依赖的数据表暂不支持排名位置查询。",
                "error_type": "unsupported_metric_type",
            }
        num_table, den_table, num_alias, den_alias = tables
        num_metric_name = num_info.get("metric_name", num_info["field"])
        den_metric_name = den_info.get("metric_name", den_info["field"])
        sql = build_derived_rank_position_sql(
            metric=metric,
            company=company,
            num_info=num_info,
            den_info=den_info,
            num_table=num_table,
            den_table=den_table,
            num_alias=num_alias,
            den_alias=den_alias,
            report_year=report_year,
            report_period=report_period,
            rank_direction=rank_direction,
        )
        return {
            "sql": sql,
            "sql_metadata": {
                "metric_key": metric["metric_key"],
                "metric_name": metric["metric_name"],
                "metric_type": "derived",
                "column_alias": metric["metric_key"],
                "unit": metric.get("unit", "percent"),
                "scale": metric.get("scale", 1),
                "precision": metric.get("precision", 2),
                "rank_direction": rank_direction,
                "formula_display": f"{num_metric_name} / {den_metric_name}",
            },
        }

    return {
        "need_clarification": True,
        "clarification_question": f"指标 {metric.get('metric_name', '')} 的类型暂不支持排名位置查询。",
        "error_type": "unsupported_metric_type",
    }


__all__ = [
    "_guard_rank_position_params",
    "build_base_rank_position_sql",
    "build_derived_rank_position_sql",
    "generate_rank_position_sql_node",
]
