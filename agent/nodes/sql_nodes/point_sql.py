"""从 graph.py 拆出的业务实现。"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.constants import DEFAULT_REPORT_PERIOD, TABLE_ALIASES
from agent.state import AgentState
from agent.services.sql_builders import _group_metrics_by_table, _metric_column_alias


def generate_point_sql_node(state: AgentState) -> dict:
    if state.get("need_clarification"):
        return {}

    metrics = state.get("metrics") or []
    if not metrics:
        return {
            "need_clarification": True,
            "clarification_question": "请说明你要查询的财务指标，例如总资产、营业收入、净利润或经营现金流。",
        }

    report_year = state.get("report_year")
    report_period = state.get("report_period") or DEFAULT_REPORT_PERIOD

    companies = state.get("companies") or []
    if len(companies) != 1:
        if state.get("intent_type") == "company_compare_query" and len(companies) > 1:
            return {
                "need_clarification": True,
                "clarification_question": "多公司对比查询功能开发中，请暂时分别查询各公司。",
            }
        return {
            "need_clarification": True,
            "clarification_question": "请明确要查询的公司。",
        }

    company = companies[0]
    company_name = company["company_name"]

    if company_name is None:
        return {
            "need_clarification": True,
            "clarification_question": "请说明你要查询的公司名称。",
        }

    if report_year is None:
        return {
            "need_clarification": True,
            "clarification_question": "请说明你要查询的报告年份，例如 2024 年。",
        }

    stock_code = company["stock_code"].replace("'", "''")
    metrics_by_table = _group_metrics_by_table(metrics)

    unknown_tables = sorted(set(metrics_by_table) - set(TABLE_ALIASES))
    if unknown_tables:
        return {
            "need_clarification": True,
            "clarification_question": f"暂不支持这些指标表：{unknown_tables}。",
        }

    report_year_columns = [
        f"{TABLE_ALIASES[table]}.report_year"
        for table in metrics_by_table
    ]
    if len(report_year_columns) == 1:
        report_year_expr = f"{report_year_columns[0]} AS report_year"
    else:
        report_year_expr = "COALESCE(" + ", ".join(report_year_columns) + ") AS report_year"

    metric_select_lines = []
    for metric in metrics:
        table_alias = TABLE_ALIASES[metric["table"]]
        column_alias = _metric_column_alias(metric)
        metric_select_lines.append(
            f"        {table_alias}.{metric['field']} AS {column_alias}"
        )

    joins = []
    for table in metrics_by_table:
        table_alias = TABLE_ALIASES[table]
        joins.append(
            f"""LEFT JOIN {table} {table_alias}
      ON c.stock_code = {table_alias}.stock_code
     AND {table_alias}.report_year = {report_year}
     AND {table_alias}.report_period = '{report_period}'"""
        )

    sql = f"""
    SELECT
        c.stock_code,
        c.stock_abbr,
        c.company_name,
        {report_year_expr},
        '{report_period}' AS report_period,
{",\n".join(metric_select_lines)}
    FROM company_dim c
    {"\n    ".join(joins)}
    WHERE c.stock_code = '{stock_code}'
    """

    return {
        "sql": sql,
    }

__all__ = ['generate_point_sql_node']
