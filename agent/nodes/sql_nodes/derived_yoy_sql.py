"""派生指标同比 SQL：每指标一条，用 years CTE + LEFT JOIN 保证两行。"""

from __future__ import annotations

from typing import Any

from agent.constants import DEFAULT_REPORT_PERIOD, TABLE_ALIASES
from agent.state import AgentState
from agent.tools.metric_tools import load_metric_dictionary
from agent.nodes.sql_nodes.derived_common import resolve_derived_formula, resolve_derived_tables


def generate_derived_yoy_sql_node(state: AgentState) -> dict:
    if state.get("need_clarification"):
        return {}

    metrics = state.get("metrics") or []
    if not metrics:
        return {
            "need_clarification": True,
            "clarification_question": "请说明你要查询的派生财务指标，例如资产负债率、净利率。",
        }

    companies = state.get("companies") or []
    if len(companies) != 1:
        return {
            "need_clarification": True,
            "clarification_question": "派生指标同比查询暂仅支持单公司。",
        }

    company = companies[0]
    report_period = state.get("report_period") or DEFAULT_REPORT_PERIOD
    report_year = state.get("report_year")

    if report_year is None:
        return {
            "need_clarification": True,
            "clarification_question": "派生指标同比查询需要明确的报告年份。",
        }

    stock_code = company["stock_code"].replace("'", "''")
    prev_year = report_year - 1
    metric_dict = load_metric_dictionary()

    derived_yoy_sqls: list[dict[str, Any]] = []

    for derived_metric in metrics:
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
    y.report_year,
    '{report_period}' AS report_period,
    {num_alias}.{num_info['field']} AS numerator_value,
    {num_alias}.{den_info['field']} AS denominator_value
FROM company_dim c
CROSS JOIN (
    SELECT {prev_year} AS report_year
    UNION ALL
    SELECT {report_year} AS report_year
) y
LEFT JOIN {num_table} {num_alias}
    ON {num_alias}.stock_code = c.stock_code
    AND {num_alias}.report_year = y.report_year
    AND {num_alias}.report_period = '{report_period}'
WHERE c.stock_code = '{stock_code}'
ORDER BY y.report_year
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
    SELECT {prev_year} AS report_year
    UNION ALL
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
WHERE c.stock_code = '{stock_code}'
ORDER BY y.report_year
"""
        derived_yoy_sqls.append({
            "metric_key": derived_metric["metric_key"],
            "sql": sql,
        })

    if not derived_yoy_sqls:
        return {
            "need_clarification": True,
            "clarification_question": "派生指标公式依赖的基础指标未找到，请检查配置。",
        }

    return {"derived_yoy_sqls": derived_yoy_sqls}
