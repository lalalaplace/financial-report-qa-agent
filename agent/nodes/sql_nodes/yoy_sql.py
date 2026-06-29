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

from agent.services.sql_builders import _build_yoy_sql_for_table, _group_metrics_by_table


def generate_yoy_sql_node(state: AgentState) -> dict:
    """同比查询 SQL：按表分组生成，单表一条 SQL，多表多条 SQL。

    每条 SQL 拉取当年 + 上年数据，不做跨表 JOIN。
    """
    if state.get("need_clarification"):
        return {}

    metrics = state.get("metrics") or []
    if not metrics:
        return {
            "need_clarification": True,
            "clarification_question": "请说明你要查询的财务指标。",
        }

    companies = state.get("companies") or []
    if len(companies) != 1:
        return {
            "need_clarification": True,
            "clarification_question": "同比查询暂仅支持单公司。",
        }

    company = companies[0]
    report_period = state.get("report_period") or DEFAULT_REPORT_PERIOD
    report_year = state.get("report_year")

    if report_year is None:
        return {
            "need_clarification": True,
            "clarification_question": "同比查询需要明确的报告年份。",
        }

    metrics_by_table = _group_metrics_by_table(metrics)
    unknown_tables = sorted(set(metrics_by_table) - set(TABLE_ALIASES))
    if unknown_tables:
        return {
            "need_clarification": True,
            "clarification_question": f"暂不支持这些指标表：{unknown_tables}。",
        }

    sqls: list[str] = []
    for table, table_metrics in metrics_by_table.items():
        sql = _build_yoy_sql_for_table(
            table=table,
            table_metrics=table_metrics,
            company=company,
            report_period=report_period,
            report_year=report_year,
        )
        sqls.append(sql)

    if len(sqls) == 1:
        return {"sql": sqls[0]}
    return {"yoy_sqls": sqls}

__all__ = ['generate_yoy_sql_node']
