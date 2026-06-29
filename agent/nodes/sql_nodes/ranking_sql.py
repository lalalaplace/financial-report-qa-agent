"""排名查询 SQL 生成节点（V0.5.2）。

V0.5.0 仅支持 base 指标的全市场排名。V0.5.1 扩展派生指标排名。
V0.5.2 新增 SQL 层安全防护（limit 缺失/越界/方向无效时抛 ValueError）、
二级排序保证稳定性、NULLIF 处理派生指标分母为零。

架构：generate_ranking_sql_node 为单一入口，内部按 metric_type 分发到
build_base_ranking_sql 或 build_derived_ranking_sql。派生 SQL 复用
derived_common 的公式解析和表别名解析逻辑。
"""

from __future__ import annotations

from agent.constants import DEFAULT_REPORT_PERIOD, TABLE_ALIASES
from agent.state import AgentState
from agent.services.sql_builders import _metric_column_alias
from agent.tools.metric_tools import load_metric_dictionary
from agent.nodes.sql_nodes.derived_common import (
    resolve_derived_formula,
    resolve_derived_tables,
)


# V0.5.2：SQL 层安全防护，防止 validator 漏过后生成无界查询
def _guard_ranking_params(limit, rank_direction):
    if limit is None:
        raise ValueError("ranking_query requires limit")
    if not isinstance(limit, int) or limit < 1 or limit > 50:
        raise ValueError(f"invalid ranking limit: {limit}")
    if rank_direction not in ("asc", "desc"):
        raise ValueError(f"invalid rank_direction: {rank_direction}")


def build_base_ranking_sql(
    *,
    metric: dict,
    report_year: int,
    report_period: str,
    rank_direction: str,
    limit: int,
) -> str:
    """为单个 base 指标构建全市场排名 SQL。

    Args:
        metric: 标准化后的指标对象（含 table、field、metric_key）
        report_year: 报告年份
        report_period: 报告期 FY/H1/Q1/Q3
        rank_direction: desc（降序=TopN）或 asc（升序=BottomN）
        limit: 返回行数

    Returns:
        排名查询 SQL 字符串
    """
    table = metric["table"]
    field = metric["field"]
    table_alias = TABLE_ALIASES[table]
    column_alias = _metric_column_alias(metric)

    sql_direction = "DESC" if rank_direction == "desc" else "ASC"

    return f"""
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
    WHERE {table_alias}.{field} IS NOT NULL
    ORDER BY {table_alias}.{field} {sql_direction}, c.stock_code ASC
    LIMIT {limit}
    """


def build_derived_ranking_sql(
    *,
    metric: dict,
    num_info: dict,
    den_info: dict,
    num_table: str,
    den_table: str,
    num_alias: str,
    den_alias: str,
    report_year: int,
    report_period: str,
    rank_direction: str,
    limit: int,
) -> str:
    """为单个 derived 指标构建全市场排名 SQL，在 SQL 中计算派生值并排序。

    分子/分母的表名和别名由调用方通过 resolve_derived_tables() 解析后传入，
    本函数不直接依赖 derived_common，只负责 SQL 拼接。

    Args:
        metric: 派生指标对象（含 metric_key、scale、precision）
        num_info: 分子基础指标信息（含 field）
        den_info: 分母基础指标信息（含 field）
        num_table: 分子所在表名
        den_table: 分母所在表名
        num_alias: 分子表的 SQL 别名
        den_alias: 分母表的 SQL 别名
        report_year: 报告年份
        report_period: 报告期 FY/H1/Q1/Q3
        rank_direction: desc（降序=TopN）或 asc（升序=BottomN）
        limit: 返回行数

    Returns:
        派生指标排名查询 SQL 字符串
    """
    precision = metric.get("precision", 2)
    column_alias = metric["metric_key"]
    num_field = num_info["field"]
    den_field = den_info["field"]

    sql_direction = "DESC" if rank_direction == "desc" else "ASC"

    # V0.5.2：NULLIF 处理分母为 0 / NULL，CAST 类型统一为 DOUBLE
    safe_division = (
        f"ROUND(CAST({num_alias}.{num_field} AS DOUBLE) "
        f"/ NULLIF(CAST({den_alias}.{den_field} AS DOUBLE), 0), 8)"
    )

    if num_table == den_table:
        return f"""
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
    WHERE {num_alias}.{num_field} IS NOT NULL
      AND {num_alias}.{den_field} IS NOT NULL
      AND {num_alias}.{den_field} != 0
    ORDER BY {column_alias} {sql_direction}, c.stock_code ASC
    LIMIT {limit}
    """

    return f"""
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
    WHERE {num_alias}.{num_field} IS NOT NULL
      AND {den_alias}.{den_field} IS NOT NULL
      AND {den_alias}.{den_field} != 0
    ORDER BY {column_alias} {sql_direction}, c.stock_code ASC
    LIMIT {limit}
    """


def generate_ranking_sql_node(state: AgentState) -> dict:
    """排名查询 SQL 生成节点（V0.5.2）。

    单一入口，按 metric_type 内部分发：
    - base → build_base_ranking_sql
    - derived → resolve_derived_formula + resolve_derived_tables → build_derived_ranking_sql
    - 其他 → clarification
    """
    if state.get("need_clarification"):
        return {}

    metrics = state.get("metrics") or []
    if not metrics:
        return {
            "need_clarification": True,
            "clarification_question": "请说明你要按什么指标排名。",
            "error_type": "missing_metric",
        }

    report_year = state.get("report_year")
    report_period = state.get("report_period") or DEFAULT_REPORT_PERIOD
    rank_direction = state.get("rank_direction") or "desc"
    limit = state.get("limit")

    if report_year is None:
        return {
            "need_clarification": True,
            "clarification_question": "请说明排名的年份。",
            "error_type": "missing_year",
        }

    try:
        _guard_ranking_params(limit, rank_direction)
    except ValueError as exc:
        return {
            "need_clarification": True,
            "clarification_question": f"排名参数异常：{exc}",
            "error_type": "invalid_limit",
        }

    metric = metrics[0]
    metric_type = metric.get("metric_type", "base")

    # ── base 指标 ──
    if metric_type == "base":
        table = metric.get("table", "")
        if table not in TABLE_ALIASES:
            return {
                "need_clarification": True,
                "clarification_question": f"暂不支持指标表 {table} 的排名查询。",
                "error_type": "unsupported_metric_type",
            }

        sql = build_base_ranking_sql(
            metric=metric,
            report_year=report_year,
            report_period=report_period,
            rank_direction=rank_direction,
            limit=limit,
        )

        return {
            "sql": sql,
            "sql_metadata": {
                "metric_key": metric["metric_key"],
                "metric_name": metric["metric_name"],
                "metric_type": "base",
                "table": table,
                "field": metric["field"],
                "rank_direction": rank_direction,
                "limit": limit,
            },
        }

    # ── derived 指标 ──
    if metric_type == "derived":
        metric_dict = load_metric_dictionary()
        resolved = resolve_derived_formula(metric, metric_dict)
        if not resolved:
            return {
                "need_clarification": True,
                "clarification_question": (
                    f"派生指标 {metric.get('metric_name', '')} 的公式定义未找到，请检查配置。"
                ),
                "error_type": "unsupported_metric_type",
            }
        num_info, den_info = resolved

        tables = resolve_derived_tables(num_info, den_info)
        if not tables:
            return {
                "need_clarification": True,
                "clarification_question": (
                    f"派生指标 {metric.get('metric_name', '')} 依赖的数据表暂不支持排名查询。"
                ),
                "error_type": "unsupported_metric_type",
            }
        num_table, den_table, num_alias, den_alias = tables

        # 构建口径展示文本（供 answer 层使用）
        num_metric_name = num_info.get("metric_name", num_info["field"])
        den_metric_name = den_info.get("metric_name", den_info["field"])
        formula_display = f"{num_metric_name} / {den_metric_name}"

        sql = build_derived_ranking_sql(
            metric=metric,
            num_info=num_info,
            den_info=den_info,
            num_table=num_table,
            den_table=den_table,
            num_alias=num_alias,
            den_alias=den_alias,
            report_year=report_year,
            report_period=report_period,
            rank_direction=rank_direction,
            limit=limit,
        )

        return {
            "sql": sql,
            "sql_metadata": {
                "metric_key": metric["metric_key"],
                "metric_name": metric["metric_name"],
                "metric_type": "derived",
                "num_table": num_table,
                "num_field": num_info["field"],
                "den_table": den_table,
                "den_field": den_info["field"],
                "column_alias": metric["metric_key"],
                "scale": metric.get("scale", 1),
                "precision": metric.get("precision", 2),
                "unit": metric.get("unit", "yuan"),
                "rank_direction": rank_direction,
                "limit": limit,
                "formula_display": formula_display,
                "num_metric_name": num_metric_name,
                "den_metric_name": den_metric_name,
            },
        }

    # ── 不支持的类型 ──
    return {
        "need_clarification": True,
        "clarification_question": (
            f"指标 {metric.get('metric_name', '')} 的类型（{metric_type}）暂不支持排名查询。"
        ),
        "error_type": "unsupported_metric_type",
    }


__all__ = [
    "build_base_ranking_sql",
    "build_derived_ranking_sql",
    "generate_ranking_sql_node",
]
