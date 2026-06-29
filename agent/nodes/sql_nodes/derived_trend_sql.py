"""派生指标趋势 SQL：逐指标生成独立 SQL，跨表时使用 years CTE。"""

from __future__ import annotations

from typing import Any

from agent.constants import DEFAULT_REPORT_PERIOD, TABLE_ALIASES
from agent.state import AgentState
from agent.tools.metric_tools import load_metric_dictionary
from agent.nodes.sql_nodes.derived_common import resolve_derived_formula, resolve_derived_tables


def generate_derived_trend_sql_node(state: AgentState) -> dict:
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
            "clarification_question": "趋势查询暂仅支持单公司。",
        }

    company = companies[0]
    report_period = state.get("report_period") or DEFAULT_REPORT_PERIOD

    time_mode = state.get("time_mode") or "recent_n"
    report_year = state.get("report_year")
    if time_mode == "explicit_range":
        start_year = state.get("start_year")
        end_year = state.get("end_year")
    else:
        recent_n = state.get("recent_n_years") or 5
        end_year = report_year
        start_year = end_year - recent_n + 1 if end_year else None

    if start_year is None or end_year is None:
        return {
            "need_clarification": True,
            "clarification_question": "趋势查询需要明确的年份范围。",
        }

    stock_code = company["stock_code"].replace("'", "''")
    metric_dict = load_metric_dictionary()

    derived_trend_sqls: list[dict[str, Any]] = []

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
        {num_alias}.report_year,
        '{report_period}' AS report_period,
        {num_alias}.{num_info['field']} AS numerator_value,
        {num_alias}.{den_info['field']} AS denominator_value
    FROM company_dim c
    LEFT JOIN {num_table} {num_alias}
        ON c.stock_code = {num_alias}.stock_code
        AND {num_alias}.report_year BETWEEN {start_year} AND {end_year}
        AND {num_alias}.report_period = '{report_period}'
    WHERE c.stock_code = '{stock_code}'
    ORDER BY {num_alias}.report_year
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
        SELECT report_year FROM {num_table}
        WHERE stock_code = '{stock_code}' AND report_year BETWEEN {start_year} AND {end_year} AND report_period = '{report_period}'
        UNION
        SELECT report_year FROM {den_table}
        WHERE stock_code = '{stock_code}' AND report_year BETWEEN {start_year} AND {end_year} AND report_period = '{report_period}'
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

        derived_trend_sqls.append({
            "metric_key": derived_metric["metric_key"],
            "sql": sql,
        })

    if not derived_trend_sqls:
        return {
            "need_clarification": True,
            "clarification_question": "派生指标公式依赖的基础指标未找到，请检查配置。",
        }

    return {"derived_trend_sqls": derived_trend_sqls}
