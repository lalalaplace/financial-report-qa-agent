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


def generate_compare_sql_node(state: AgentState) -> dict:
    """多公司对比 SQL：按财务表分组，每表一条 SQL，共享 company 集合。

    输出 compare_sqls: [{"table": "income_sheet", "metric_keys": [...], "sql": "..."}, ...]
    """
    if state.get("need_clarification"):
        return {}

    metrics = state.get("metrics") or []
    if not metrics:
        return {
            "need_clarification": True,
            "clarification_question": "请说明你要对比的财务指标。",
        }

    companies = state.get("companies") or []
    if len(companies) < 2:
        return {
            "need_clarification": True,
            "clarification_question": "请提供至少两家公司进行对比。",
        }

    report_year = state.get("report_year")
    report_period = state.get("report_period") or DEFAULT_REPORT_PERIOD

    if report_year is None:
        return {
            "need_clarification": True,
            "clarification_question": "请说明对比的年份，例如 2024 年。",
        }

    stock_codes = [c["stock_code"].replace("'", "''") for c in companies]
    stock_codes_str = ", ".join(f"'{code}'" for code in stock_codes)

    metrics_by_table = _group_metrics_by_table(metrics)
    unknown_tables = sorted(set(metrics_by_table) - set(TABLE_ALIASES))
    if unknown_tables:
        return {
            "need_clarification": True,
            "clarification_question": f"暂不支持这些指标表：{unknown_tables}。",
        }

    compare_sqls: list[dict[str, Any]] = []

    for table, table_metrics in metrics_by_table.items():
        table_alias = TABLE_ALIASES[table]
        metric_keys: list[str] = []
        metric_select_lines: list[str] = []

        for metric in table_metrics:
            metric_keys.append(metric["metric_key"])
            column_alias = _metric_column_alias(metric)
            metric_select_lines.append(
                f"        {table_alias}.{metric['field']} AS {column_alias}"
            )

        sql = f"""
    SELECT
        c.stock_code,
        c.stock_abbr,
        c.company_name,
        {table_alias}.report_year,
        '{report_period}' AS report_period,
{",\n".join(metric_select_lines)}
    FROM company_dim c
    LEFT JOIN {table} {table_alias}
        ON c.stock_code = {table_alias}.stock_code
       AND {table_alias}.report_year = {report_year}
       AND {table_alias}.report_period = '{report_period}'
    WHERE c.stock_code IN ({stock_codes_str})
    ORDER BY c.stock_code
    """

        compare_sqls.append({
            "table": table,
            "metric_keys": metric_keys,
            "sql": sql,
        })

    return {"compare_sqls": compare_sqls}

__all__ = ['generate_compare_sql_node']
