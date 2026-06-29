"""派生指标点查 SQL：每指标一条 SQL，查 formula 所需原始字段。"""

from __future__ import annotations

from typing import Any

from agent.constants import DEFAULT_REPORT_PERIOD, TABLE_ALIASES
from agent.state import AgentState
from agent.tools.metric_tools import load_metric_dictionary
from agent.services.sql_builders import _group_metrics_by_table


def generate_derived_sql_node(state: AgentState) -> dict:
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
            "clarification_question": "派生指标查询暂仅支持单公司。",
        }

    company = companies[0]
    report_year = state.get("report_year")
    report_period = state.get("report_period") or DEFAULT_REPORT_PERIOD

    if report_year is None:
        return {
            "need_clarification": True,
            "clarification_question": "派生指标查询需要明确的报告年份。",
        }

    stock_code = company["stock_code"].replace("'", "''")
    metric_dict = load_metric_dictionary()

    sqls: list[str] = []
    for derived_metric in metrics:
        formula = derived_metric.get("formula") or {}
        base_fields: dict[str, dict] = {}
        for role in ("numerator", "denominator"):
            dep_key = formula.get(role)
            if dep_key and dep_key in metric_dict:
                base_fields[dep_key] = metric_dict[dep_key]

        if not base_fields:
            continue

        metrics_by_table = _group_metrics_by_table(list(base_fields.values()))

        unknown_tables = sorted(set(metrics_by_table) - set(TABLE_ALIASES))
        if unknown_tables:
            continue

        report_year_columns = [
            f"{TABLE_ALIASES[table]}.report_year"
            for table in metrics_by_table
        ]
        if len(report_year_columns) == 1:
            report_year_expr = f"{report_year_columns[0]} AS report_year"
        else:
            report_year_expr = "COALESCE(" + ", ".join(report_year_columns) + ") AS report_year"

        metric_select_lines = []
        for info in base_fields.values():
            table_alias = TABLE_ALIASES[info["table"]]
            column_alias = f"{info['table']}__{info['field']}"
            metric_select_lines.append(
                f"        {table_alias}.{info['field']} AS {column_alias}"
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
        sqls.append(sql)

    if not sqls:
        return {
            "need_clarification": True,
            "clarification_question": "派生指标公式依赖的基础指标未找到，请检查配置。",
        }

    if len(sqls) == 1:
        return {"sql": sqls[0]}
    return {"derived_sqls": sqls}
