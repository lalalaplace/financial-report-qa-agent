"""从 graph.py 拆出的业务实现。"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.constants import DEFAULT_REPORT_PERIOD, DEFAULT_QUERY_TYPE, TABLE_ALIASES, COMPARE_INTENTS
from agent.schemas.query_plan import normalize_compare_spec
from agent.state import AgentState
from agent.tools.company_tools import resolve_company
from agent.tools.metric_tools import load_metric_dictionary, map_metrics
from agent.tools.sql_tools import execute_financial_sql, review_sql
from db.readonly_executor import execute_readonly_sql

from agent.services.sql_builders import _metric_column_alias


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

__all__ = ['_build_yoy_sql_for_table']
