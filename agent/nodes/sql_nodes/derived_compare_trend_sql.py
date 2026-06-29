"""派生指标公司趋势对比 SQL。"""

from __future__ import annotations

from typing import Any

from agent.constants import DEFAULT_REPORT_PERIOD, TABLE_ALIASES
from agent.state import AgentState
from agent.tools.metric_tools import load_metric_dictionary
from agent.utils.year_utils import _resolve_trend_years, _years_union_sql
from agent.nodes.sql_nodes.derived_common import (
    resolve_derived_formula,
    resolve_derived_tables,
    stock_codes_str,
)


def generate_derived_compare_trend_sql_node(state: AgentState) -> dict:
    if state.get("need_clarification"):
        return {}

    metrics = state.get("metrics") or []
    companies = state.get("companies") or []
    if len(companies) < 2:
        return {
            "need_clarification": True,
            "clarification_question": "请提供至少两家公司进行趋势对比。",
        }
    if not metrics:
        return {
            "need_clarification": True,
            "clarification_question": "请说明你要对比趋势的派生财务指标。",
        }

    report_years = _resolve_trend_years(state)
    if len(report_years) < 2:
        return {
            "need_clarification": True,
            "clarification_question": "公司趋势对比需要明确的年份范围。",
        }

    report_period = state.get("report_period") or DEFAULT_REPORT_PERIOD
    stock_codes = stock_codes_str(companies)
    years_sql = _years_union_sql(report_years)
    metric_dict = load_metric_dictionary()

    derived_compare_trend_sqls: list[dict[str, Any]] = []
    for derived_metric in metrics:
        if derived_metric.get("metric_type") != "derived":
            continue

        formula = derived_metric.get("formula") or {}
        numerator_key = formula.get("numerator")
        denominator_key = formula.get("denominator")

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
        {years_sql}
    ) y
    LEFT JOIN {num_table} {num_alias}
        ON c.stock_code = {num_alias}.stock_code
       AND {num_alias}.report_year = y.report_year
       AND {num_alias}.report_period = '{report_period}'
    WHERE c.stock_code IN ({stock_codes})
    ORDER BY c.stock_code, y.report_year
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
        {years_sql}
    ) y
    LEFT JOIN {num_table} {num_alias}
        ON c.stock_code = {num_alias}.stock_code
       AND {num_alias}.report_year = y.report_year
       AND {num_alias}.report_period = '{report_period}'
    LEFT JOIN {den_table} {den_alias}
        ON c.stock_code = {den_alias}.stock_code
       AND {den_alias}.report_year = y.report_year
       AND {den_alias}.report_period = '{report_period}'
    WHERE c.stock_code IN ({stock_codes})
    ORDER BY c.stock_code, y.report_year
    """

        derived_compare_trend_sqls.append({
            "sql_id": f"derived_compare_trend_{derived_metric['metric_key']}_{len(derived_compare_trend_sqls) + 1:03d}",
            "metric_key": derived_metric["metric_key"],
            "years": report_years,
            "numerator": numerator_key,
            "denominator": denominator_key,
            "scale": derived_metric.get("scale", 1),
            "sql": sql,
            "guard_passed": False,
        })

    if not derived_compare_trend_sqls:
        return {
            "need_clarification": True,
            "clarification_question": "派生指标公式依赖的基础指标未找到，请检查配置。",
        }

    return {"derived_compare_trend_sqls": derived_compare_trend_sqls}
