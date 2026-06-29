"""从 graph.py 拆出的业务实现。"""

from __future__ import annotations

from typing import Any

from agent.constants import TABLE_ALIASES


def _metric_column_alias(metric: dict[str, Any]) -> str:
    return f"{metric['table']}__{metric['field']}"

def _group_metrics_by_table(metrics: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for metric in metrics:
        grouped.setdefault(metric["table"], []).append(metric)
    return grouped

def _build_yoy_sql_for_table(
    table: str,
    table_metrics: list[dict[str, Any]],
    company: dict[str, Any],
    report_period: str,
    report_year: int,
) -> str:
    """为单张财务表生成同比 SQL（当年 + 上年）。"""
    prev_year = report_year - 1
    stock_code = company["stock_code"].replace("'", "''")
    table_alias = TABLE_ALIASES[table]

    metric_select_lines = []
    for metric in table_metrics:
        column_alias = _metric_column_alias(metric)
        metric_select_lines.append(
            f"        {table_alias}.{metric['field']} AS {column_alias}"
        )

    sql = f"""
    SELECT
        c.stock_code,
        c.stock_abbr,
        c.company_name,
        {table_alias}.report_year AS report_year,
        '{report_period}' AS report_period,
{",\n".join(metric_select_lines)}
    FROM company_dim c
    LEFT JOIN {table} {table_alias}
      ON c.stock_code = {table_alias}.stock_code
     AND {table_alias}.report_year IN ({prev_year}, {report_year})
     AND {table_alias}.report_period = '{report_period}'
    WHERE c.stock_code = '{stock_code}'
    ORDER BY report_year
    """
    return sql

__all__ = ['_metric_column_alias', '_group_metrics_by_table', '_build_yoy_sql_for_table']
