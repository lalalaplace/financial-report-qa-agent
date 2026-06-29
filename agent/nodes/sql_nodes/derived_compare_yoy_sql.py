"""派生指标公司同比对比 SQL。"""

from __future__ import annotations

from typing import Any

from agent.constants import DEFAULT_REPORT_PERIOD, TABLE_ALIASES
from agent.state import AgentState
from agent.tools.metric_tools import load_metric_dictionary
from agent.utils.year_utils import _years_union_sql
from agent.nodes.sql_nodes.derived_common import (
    resolve_derived_formula,
    resolve_derived_tables,
    stock_codes_str,
)


def generate_derived_compare_yoy_sql_node(state: AgentState) -> dict:
    if state.get("need_clarification"):
        return {}

    metrics = [m for m in (state.get("metrics") or []) if m.get("metric_type") == "derived"]
    companies = state.get("companies") or []
    if len(companies) < 2:
        return {
            "need_clarification": True,
            "clarification_question": "请提供至少两家公司进行派生指标同比对比。",
        }
    if not metrics:
        return {
            "need_clarification": True,
            "clarification_question": "请说明你要对比同比变化的派生财务指标。",
        }

    report_year = state.get("report_year")
    if report_year is None:
        return {
            "need_clarification": True,
            "clarification_question": "派生指标同比对比需要明确报告年份。",
        }

    report_years = state.get("report_years") or [report_year - 1, report_year]
    report_years = sorted({int(year) for year in report_years})
    if len(report_years) != 2:
        report_years = [report_year - 1, report_year]

    report_period = state.get("report_period") or DEFAULT_REPORT_PERIOD
    stock_codes = stock_codes_str(companies)
    metric_dict = load_metric_dictionary()

    derived_compare_yoy_sqls: list[dict[str, Any]] = []

    for index, derived_metric in enumerate(metrics, start=1):
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
        years_sql = _years_union_sql(report_years)

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
        ON {num_alias}.stock_code = c.stock_code
       AND {num_alias}.report_year = y.report_year
       AND {num_alias}.report_period = '{report_period}'
    LEFT JOIN {den_table} {den_alias}
        ON {den_alias}.stock_code = c.stock_code
       AND {den_alias}.report_year = y.report_year
       AND {den_alias}.report_period = '{report_period}'
    WHERE c.stock_code IN ({stock_codes})
    ORDER BY c.stock_code, y.report_year
    """

        derived_compare_yoy_sqls.append({
            "sql_id": f"derived_compare_yoy_{derived_metric['metric_key']}_{index:03d}",
            "metric_key": derived_metric["metric_key"],
            "years": report_years,
            "numerator": numerator_key,
            "denominator": denominator_key,
            "scale": derived_metric.get("scale", 1),
            "sql": sql,
            "guard_passed": False,
        })

    if not derived_compare_yoy_sqls:
        return {
            "need_clarification": True,
            "clarification_question": "派生指标公式依赖的基础指标未找到，请检查配置。",
        }

    return {"derived_compare_yoy_sqls": derived_compare_yoy_sqls}
