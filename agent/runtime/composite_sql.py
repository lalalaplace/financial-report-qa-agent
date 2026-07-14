"""V0.8.4 复合查询 SQL 模板与结果集派生分析。"""

from __future__ import annotations

from typing import Any

from agent.constants import TABLE_ALIASES
from agent.services.sql_builders import _group_metrics_by_table, _metric_column_alias
from agent.tools.metric_tools import load_metric_dictionary
from agent.nodes.sql_nodes.derived_common import resolve_derived_formula, resolve_derived_tables


def _quote_sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def build_revenue_profit_intersection_sql(
    *,
    report_year: int,
    report_period: str,
    top_limit: int = 20,
) -> tuple[str, dict[str, Any]]:
    """构建营业收入 TopN 与净利润 TopN 交集，并按净利率排序的确定性 SQL。"""
    if not isinstance(report_year, int):
        raise ValueError("set_intersection requires report_year")
    if not isinstance(top_limit, int) or top_limit < 1 or top_limit > 50:
        raise ValueError(f"invalid set_intersection limit: {top_limit}")

    sql = f"""
    WITH revenue_top AS (
        SELECT
            i.stock_code,
            i.report_year,
            i.total_operating_revenue,
            i.net_profit
        FROM income_sheet i
        WHERE i.report_year = {report_year}
          AND i.report_period = '{report_period}'
          AND i.total_operating_revenue IS NOT NULL
          AND i.net_profit IS NOT NULL
          AND i.total_operating_revenue != 0
        ORDER BY i.total_operating_revenue DESC, i.stock_code ASC
        LIMIT {top_limit}
    ),
    profit_top AS (
        SELECT
            i.stock_code,
            i.report_year,
            i.total_operating_revenue,
            i.net_profit
        FROM income_sheet i
        WHERE i.report_year = {report_year}
          AND i.report_period = '{report_period}'
          AND i.total_operating_revenue IS NOT NULL
          AND i.net_profit IS NOT NULL
          AND i.total_operating_revenue != 0
        ORDER BY i.net_profit DESC, i.stock_code ASC
        LIMIT {top_limit}
    )
    SELECT
        c.stock_code,
        c.stock_abbr,
        c.company_name,
        r.report_year,
        '{report_period}' AS report_period,
        r.total_operating_revenue,
        r.net_profit,
        ROUND(CAST(r.net_profit AS NUMERIC) / NULLIF(CAST(r.total_operating_revenue AS NUMERIC), 0), 8) AS net_profit_margin
    FROM revenue_top r
    JOIN profit_top p
      ON r.stock_code = p.stock_code
    JOIN company_dim c
      ON c.stock_code = r.stock_code
    ORDER BY net_profit_margin DESC, c.stock_code ASC
    LIMIT {top_limit}
    """
    return sql, {
        "requirement_type": "set_intersection",
        "base_metrics": ["total_operating_revenue", "net_profit"],
        "derived_metric": "net_profit_margin",
        "report_year": report_year,
        "report_period": report_period,
        "top_limit": top_limit,
        "rank_direction": "desc",
    }


def _company_codes_from_artifact(company_set: list[Any]) -> list[str]:
    stock_codes: list[str] = []
    for item in company_set:
        if isinstance(item, str):
            stock_codes.append(item)
        elif isinstance(item, dict) and item.get("stock_code"):
            stock_codes.append(str(item["stock_code"]))
    return list(dict.fromkeys(stock_codes))


def build_company_set_yoy_sqls(
    *,
    metrics: list[dict[str, Any]],
    company_set: list[Any],
    report_period: str,
    report_year: int,
) -> list[str]:
    """为指定公司集合生成多指标同比查询 SQL。"""
    stock_codes = _company_codes_from_artifact(company_set)
    if not stock_codes:
        raise ValueError("company_set_yoy requires non-empty company_set")

    prev_year = report_year - 1
    stock_code_list = ", ".join(_quote_sql_literal(code) for code in stock_codes)
    sqls: list[str] = []

    for table, table_metrics in _group_metrics_by_table(metrics).items():
        if table not in TABLE_ALIASES:
            raise ValueError(f"unsupported metric table: {table}")
        table_alias = TABLE_ALIASES[table]
        metric_select_lines = []
        for metric in table_metrics:
            column_alias = _metric_column_alias(metric)
            metric_select_lines.append(
                f"        {table_alias}.{metric['field']} AS {column_alias}"
            )

        sqls.append(
            f"""
    SELECT
        c.stock_code,
        c.stock_abbr,
        c.company_name,
        {table_alias}.report_year AS report_year,
        '{report_period}' AS report_period,
{",\n".join(metric_select_lines)}
    FROM company_dim c
    LEFT JOIN {table} {table_alias}
      ON c.stock_code = {table_alias}.stock_code
     AND {table_alias}.report_year IN ({prev_year}, {report_year})
     AND {table_alias}.report_period = '{report_period}'
    WHERE c.stock_code IN ({stock_code_list})
    ORDER BY c.stock_code ASC, report_year ASC
    """
        )

    return sqls


def _guard_ranking_params(limit: int | None, rank_direction: str | None) -> None:
    if limit is None:
        raise ValueError("ranking_query requires limit")
    if not isinstance(limit, int) or limit < 1 or limit > 50:
        raise ValueError(f"invalid ranking limit: {limit}")
    if rank_direction not in ("asc", "desc"):
        raise ValueError(f"invalid rank_direction: {rank_direction}")


def build_company_set_ranking_sql(
    *,
    metric: dict[str, Any],
    company_set: list[Any],
    report_period: str,
    report_year: int,
    rank_direction: str,
    limit: int,
) -> tuple[str, dict[str, Any]]:
    stock_codes = _company_codes_from_artifact(company_set)
    if not stock_codes:
        raise ValueError("company_set_ranking requires non-empty company_set")
    _guard_ranking_params(limit, rank_direction)

    stock_code_list = ", ".join(_quote_sql_literal(code) for code in stock_codes)
    sql_direction = "DESC" if rank_direction == "desc" else "ASC"
    metric_type = metric.get("metric_type", "base")

    if metric_type == "base":
        table = metric["table"]
        field = metric["field"]
        if table not in TABLE_ALIASES:
            raise ValueError(f"unsupported metric table: {table}")
        table_alias = TABLE_ALIASES[table]
        column_alias = _metric_column_alias(metric)
        sql = f"""
    SELECT
        c.stock_code,
        c.stock_abbr,
        c.company_name,
        {table_alias}.report_year,
        '{report_period}' AS report_period,
        {table_alias}.{field} AS {column_alias}
    FROM company_dim c
    LEFT JOIN {table} {table_alias}
        ON c.stock_code = {table_alias}.stock_code
       AND {table_alias}.report_year = {report_year}
       AND {table_alias}.report_period = '{report_period}'
    WHERE c.stock_code IN ({stock_code_list})
      AND {table_alias}.{field} IS NOT NULL
    ORDER BY {table_alias}.{field} {sql_direction}, c.stock_code ASC
    LIMIT {limit}
    """
        return sql, {
            "metric_key": metric["metric_key"],
            "metric_name": metric["metric_name"],
            "metric_type": "base",
            "table": table,
            "field": field,
            "rank_direction": rank_direction,
            "limit": limit,
            "company_scope": "dependency",
        }

    if metric_type != "derived":
        raise ValueError(f"unsupported metric type: {metric_type}")

    metric_dict = load_metric_dictionary()
    resolved = resolve_derived_formula(metric, metric_dict)
    if not resolved:
        raise ValueError(f"unsupported derived metric: {metric.get('metric_name', '')}")
    num_info, den_info = resolved
    tables = resolve_derived_tables(num_info, den_info)
    if not tables:
        raise ValueError(f"unsupported derived metric tables: {metric.get('metric_name', '')}")

    num_table, den_table, num_alias, den_alias = tables
    num_field = num_info["field"]
    den_field = den_info["field"]
    column_alias = metric["metric_key"]
    safe_division = (
        f"ROUND(CAST({num_alias}.{num_field} AS NUMERIC) "
        f"/ NULLIF(CAST({den_alias}.{den_field} AS NUMERIC), 0), 8)"
    )
    num_metric_name = num_info.get("metric_name", num_field)
    den_metric_name = den_info.get("metric_name", den_field)

    if num_table == den_table:
        sql = f"""
    SELECT
        c.stock_code,
        c.stock_abbr,
        c.company_name,
        {num_alias}.report_year,
        '{report_period}' AS report_period,
        {safe_division} AS {column_alias}
    FROM company_dim c
    LEFT JOIN {num_table} {num_alias}
        ON c.stock_code = {num_alias}.stock_code
       AND {num_alias}.report_year = {report_year}
       AND {num_alias}.report_period = '{report_period}'
    WHERE c.stock_code IN ({stock_code_list})
      AND {num_alias}.{num_field} IS NOT NULL
      AND {num_alias}.{den_field} IS NOT NULL
      AND {num_alias}.{den_field} != 0
    ORDER BY {column_alias} {sql_direction}, c.stock_code ASC
    LIMIT {limit}
    """
    else:
        sql = f"""
    SELECT
        c.stock_code,
        c.stock_abbr,
        c.company_name,
        COALESCE({num_alias}.report_year, {den_alias}.report_year) AS report_year,
        '{report_period}' AS report_period,
        {safe_division} AS {column_alias}
    FROM company_dim c
    LEFT JOIN {num_table} {num_alias}
        ON c.stock_code = {num_alias}.stock_code
       AND {num_alias}.report_year = {report_year}
       AND {num_alias}.report_period = '{report_period}'
    LEFT JOIN {den_table} {den_alias}
        ON c.stock_code = {den_alias}.stock_code
       AND {den_alias}.report_year = {report_year}
       AND {den_alias}.report_period = '{report_period}'
    WHERE c.stock_code IN ({stock_code_list})
      AND {num_alias}.{num_field} IS NOT NULL
      AND {den_alias}.{den_field} IS NOT NULL
      AND {den_alias}.{den_field} != 0
    ORDER BY {column_alias} {sql_direction}, c.stock_code ASC
    LIMIT {limit}
    """

    return sql, {
        "metric_key": metric["metric_key"],
        "metric_name": metric["metric_name"],
        "metric_type": "derived",
        "num_table": num_table,
        "num_field": num_field,
        "den_table": den_table,
        "den_field": den_field,
        "column_alias": column_alias,
        "scale": metric.get("scale", 1),
        "precision": metric.get("precision", 2),
        "unit": metric.get("unit", "yuan"),
        "rank_direction": rank_direction,
        "limit": limit,
        "formula_display": f"{num_metric_name} / {den_metric_name}",
        "num_metric_name": num_metric_name,
        "den_metric_name": den_metric_name,
        "company_scope": "dependency",
    }


def analyze_company_set_yoy_result(
    *,
    query_result: dict[str, Any],
    metrics: list[dict[str, Any]],
    report_year: int,
) -> dict[str, Any]:
    """把多公司多指标同比 SQL 结果转换为行式 metric_table。"""
    if not query_result.get("success"):
        return {
            "analysis_result": {
                "analysis_type": "company_set_yoy",
                "rows": [],
                "is_empty": True,
                "error": query_result.get("error"),
            },
            "business_success": False,
            "error_type": "sql_execution_error",
        }

    columns = query_result.get("columns") or []
    raw_rows = query_result.get("rows") or []
    prev_year = report_year - 1
    values_by_company: dict[tuple[str, str], dict[int, dict[str, Any]]] = {}

    for raw_row in raw_rows:
        data = dict(zip(columns, raw_row))
        stock_code = str(data.get("stock_code") or "")
        company_name = str(data.get("company_name") or "")
        row_year = data.get("report_year")
        if not stock_code or row_year not in {prev_year, report_year}:
            continue
        values_by_company.setdefault((stock_code, company_name), {})[row_year] = data

    result_rows: list[dict[str, Any]] = []
    for (stock_code, company_name), year_rows in values_by_company.items():
        current_row = year_rows.get(report_year, {})
        previous_row = year_rows.get(prev_year, {})
        for metric in metrics:
            column_alias = _metric_column_alias(metric)
            current_value = current_row.get(column_alias)
            previous_value = previous_row.get(column_alias)
            current_float = float(current_value) if current_value is not None else None
            previous_float = float(previous_value) if previous_value is not None else None
            yoy_rate = None
            change_abs = None
            status = "ok"
            if current_float is None:
                status = "missing_current_value"
            elif previous_float is None:
                status = "missing_previous_value"
            elif previous_float == 0:
                status = "zero_previous_value"
                change_abs = current_float
            else:
                change_abs = current_float - previous_float
                yoy_rate = change_abs / abs(previous_float)

            result_rows.append(
                {
                    "stock_code": stock_code,
                    "company_name": company_name,
                    "metric_key": metric.get("metric_key"),
                    "metric_name": metric.get("metric_name"),
                    "report_year": report_year,
                    "previous_year": prev_year,
                    "current_value": current_float,
                    "previous_value": previous_float,
                    "change_abs": change_abs,
                    "yoy_rate": yoy_rate,
                    "status": status,
                }
            )

    return {
        "analysis_result": {
            "analysis_type": "company_set_yoy",
            "report_year": report_year,
            "previous_year": prev_year,
            "row_count": len(result_rows),
            "is_empty": not result_rows,
            "rows": result_rows,
        },
        "business_success": bool(result_rows),
        "error_type": None if result_rows else "empty_yoy_result",
    }


def analyze_yoy_ranking_from_metric_table(
    *,
    metric_table: dict[str, Any],
    rank_direction: str,
    limit: int,
) -> dict[str, Any]:
    """基于前序同比结果集做二次排序，不再访问数据库。"""
    rows = metric_table.get("rows") if isinstance(metric_table, dict) else []
    rows = [row for row in rows if isinstance(row, dict) and row.get("yoy_rate") is not None]
    reverse = rank_direction != "asc"
    ranked_rows = sorted(rows, key=lambda row: row["yoy_rate"], reverse=reverse)[:limit]
    result_rows = [
        {
            **row,
            "rank": index + 1,
        }
        for index, row in enumerate(ranked_rows)
    ]
    return {
        "analysis_result": {
            "analysis_type": "yoy_ranking_from_artifact",
            "rank_direction": rank_direction,
            "limit": limit,
            "row_count": len(result_rows),
            "is_empty": not result_rows,
            "rows": result_rows,
        },
        "business_success": bool(result_rows),
        "error_type": None if result_rows else "empty_yoy_ranking_result",
    }
