"""派生指标多公司对比 SQL。"""

from __future__ import annotations

from typing import Any

from agent.constants import DEFAULT_REPORT_PERIOD, TABLE_ALIASES
from agent.state import AgentState
from agent.tools.metric_tools import load_metric_dictionary
from agent.nodes.sql_nodes.derived_common import (
    resolve_derived_formula,
    resolve_derived_tables,
    stock_codes_str,
)


def generate_derived_compare_sql_node(state: AgentState) -> dict:
    if state.get("need_clarification"):
        return {}

    metrics = state.get("metrics") or []
    if not metrics:
        return {
            "need_clarification": True,
            "clarification_question": "请说明你要对比的派生财务指标。",
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

    stock_codes = stock_codes_str(companies)
    metric_dict = load_metric_dictionary()

    derived_compare_sqls: list[dict[str, Any]] = []

    for derived_metric in metrics:
        if derived_metric.get("metric_type") != "derived":
            continue

        resolved = resolve_derived_formula(derived_metric, metric_dict)
        if not resolved:
            continue
        num_info, den_info = resolved

        tables = resolve_derived_tables(num_info, den_info)
        if not tables:
            continue
        num_table, den_table, num_alias, den_alias = tables

        if num_table == den_table:
            sql = f"""
    SELECT
        c.stock_code,
        c.stock_abbr,
        c.company_name,
        {num_alias}.report_year,
        '{report_period}' AS report_period,
        {num_alias}.{num_info['field']} AS numerator_value,
        {num_alias}.{den_info['field']} AS denominator_value
    FROM company_dim c
    LEFT JOIN {num_table} {num_alias}
        ON c.stock_code = {num_alias}.stock_code
       AND {num_alias}.report_year = {report_year}
       AND {num_alias}.report_period = '{report_period}'
    WHERE c.stock_code IN ({stock_codes})
    ORDER BY c.stock_code
    """
        else:
            sql = f"""
    SELECT
        c.stock_code,
        c.stock_abbr,
        c.company_name,
        y.report_year,
        '{report_period}' AS report_period,
        {num_alias}.{num_info['field']} AS numerator_value,
        {den_alias}.{den_info['field']} AS denominator_value
    FROM company_dim c
    CROSS JOIN (
        SELECT {report_year} AS report_year
    ) y
    LEFT JOIN {num_table} {num_alias}
        ON {num_alias}.stock_code = c.stock_code
       AND {num_alias}.report_year = y.report_year
       AND {num_alias}.report_period = '{report_period}'
    LEFT JOIN {den_table} {den_alias}
        ON {den_alias}.stock_code = c.stock_code
       AND {den_alias}.report_year = y.report_year
       AND {den_alias}.report_period = '{report_period}'
    WHERE c.stock_code IN ({stock_codes})
    ORDER BY c.stock_code
    """

        derived_compare_sqls.append({
            "metric_key": derived_metric["metric_key"],
            "sql": sql,
        })

    if not derived_compare_sqls:
        return {
            "need_clarification": True,
            "clarification_question": "派生指标公式依赖的基础指标未找到，请检查配置。",
        }

    return {"derived_compare_sqls": derived_compare_sqls}
