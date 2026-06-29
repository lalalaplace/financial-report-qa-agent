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
from agent.utils.year_utils import _years_union_sql


def generate_compare_yoy_sql_node(state: AgentState) -> dict:
    """base 指标公司同比对比 SQL：按表分组，每表一条当年+上年明细 SQL。"""
    if state.get("need_clarification"):
        return {}

    metrics = [m for m in (state.get("metrics") or []) if m.get("metric_type") != "derived"]
    companies = state.get("companies") or []
    if len(companies) < 2:
        return {
            "need_clarification": True,
            "clarification_question": "请提供至少两家公司进行同比对比。",
        }
    if not metrics:
        return {
            "need_clarification": True,
            "clarification_question": "请说明你要对比同比变化的财务指标。",
        }

    report_year = state.get("report_year")
    if report_year is None:
        return {
            "need_clarification": True,
            "clarification_question": "公司同比对比需要明确报告年份。",
        }

    report_years = state.get("report_years") or [report_year - 1, report_year]
    report_years = sorted({int(year) for year in report_years})
    if len(report_years) != 2:
        report_years = [report_year - 1, report_year]

    report_period = state.get("report_period") or DEFAULT_REPORT_PERIOD
    stock_codes = [c["stock_code"].replace("'", "''") for c in companies]
    stock_codes_str = ", ".join(f"'{code}'" for code in stock_codes)

    metrics_by_table = _group_metrics_by_table(metrics)
    unknown_tables = sorted(set(metrics_by_table) - set(TABLE_ALIASES))
    if unknown_tables:
        return {
            "need_clarification": True,
            "clarification_question": f"暂不支持这些指标表：{unknown_tables}。",
        }

    years_sql = _years_union_sql(report_years)
    compare_yoy_sqls: list[dict[str, Any]] = []
    for index, (table, table_metrics) in enumerate(metrics_by_table.items(), start=1):
        table_alias = TABLE_ALIASES[table]
        metric_keys: list[str] = []
        metric_select_lines: list[str] = [
            f"        {table_alias}.stock_code AS {table}__record_exists"
        ]

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
        y.report_year,
        '{report_period}' AS report_period,
{",\n".join(metric_select_lines)}
    FROM company_dim c
    CROSS JOIN (
        {years_sql}
    ) y
    LEFT JOIN {table} {table_alias}
        ON c.stock_code = {table_alias}.stock_code
       AND {table_alias}.report_year = y.report_year
       AND {table_alias}.report_period = '{report_period}'
    WHERE c.stock_code IN ({stock_codes_str})
    ORDER BY c.stock_code, y.report_year
    """
        compare_yoy_sqls.append({
            "sql_id": f"compare_yoy_base_{table}_{index:03d}",
            "table": table,
            "metric_keys": metric_keys,
            "years": report_years,
            "sql": sql,
            "guard_passed": False,
        })

    return {"compare_yoy_sqls": compare_yoy_sqls}

__all__ = ['generate_compare_yoy_sql_node']
