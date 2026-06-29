"""Agent 使用的 SQL 安全审查和执行工具。"""

import re
from typing import Callable, TypeVar

from db.readonly_executor import execute_readonly_sql

try:
    from langchain_core.tools import tool
except ImportError:
    F = TypeVar("F", bound=Callable)

    def tool(func: F) -> F:
        return func


FORBIDDEN_KEYWORDS = [
    "insert",
    "update",
    "delete",
    "drop",
    "alter",
    "truncate",
    "create",
    "grant",
    "revoke",
    "copy",
    "execute",
    "call",
]

ALLOWED_TABLES = {
    "company_dim",
    "company_alias",
    "report_file_index",
    "balance_sheet",
    "income_sheet",
    "cash_flow_sheet",
    "core_performance",
}

# V0.5.1：SQL 函数白名单，仅允许安全的内置函数
# cast / round / coalesce / nullif 为派生指标排名 SQL 所需
ALLOWED_SQL_FUNCTIONS = {
    "cast",
    "count",
    "rank",
    "round",
    "coalesce",
    "nullif",
}

# 函数检测时排除的 SQL 关键字（避免 SELECT( 等被误判为函数调用）
_FUNCTION_CHECK_EXCLUDED = {
    "select", "from", "where", "and", "or", "on", "as", "in", "not", "null",
    "is", "like", "between", "exists", "case", "when", "then", "else", "end",
    "join", "left", "right", "inner", "outer", "cross", "full", "natural",
    "using", "having", "group", "order", "by", "asc", "desc", "limit", "offset",
    "union", "all", "any", "some", "distinct", "into", "with", "values", "set",
    "true", "false", "primary", "key", "foreign", "references", "index",
    "unique", "check", "default", "constraint", "table", "view", "if", "begin",
    "declare", "return", "language", "over", "partition", "rows", "range",
    "unbounded", "preceding", "following", "current", "row", "only", "fetch",
    "next", "first", "last", "nulls",
}


def review_sql(sql: str) -> dict:
    sql_lower = sql.lower().strip()

    if ";" in sql_lower.rstrip(";"):
        return {
            "is_safe": False,
            "reason": "Multiple SQL statements are not allowed.",
            "corrected_sql": None,
        }

    for keyword in FORBIDDEN_KEYWORDS:
        if re.search(rf"\b{keyword}\b", sql_lower):
            return {
                "is_safe": False,
                "reason": f"Forbidden SQL keyword detected: {keyword}",
                "corrected_sql": None,
            }

    if not (sql_lower.startswith("select") or sql_lower.startswith("with")):
        return {
            "is_safe": False,
            "reason": "Only SELECT or WITH queries are allowed.",
            "corrected_sql": None,
        }

    mentioned_tables = set(
        re.findall(
            r"\bfrom\s+([a-zA-Z_][a-zA-Z0-9_]*)|\bjoin\s+([a-zA-Z_][a-zA-Z0-9_]*)",
            sql_lower,
        )
    )
    flat_tables = {table for pair in mentioned_tables for table in pair if table}

    cte_names = set()
    if sql_lower.startswith("with"):
        cte_names = set(
            re.findall(r"(?:\bwith\b|,)\s*([a-zA-Z_][a-zA-Z0-9_]*)\s+as\s*\(", sql_lower)
        )

    unknown_tables = flat_tables - ALLOWED_TABLES - cte_names
    if unknown_tables:
        return {
            "is_safe": False,
            "reason": f"Unknown or forbidden tables: {sorted(unknown_tables)}",
            "corrected_sql": None,
        }

    # V0.5.1：函数白名单检查，防止调用危险函数（如 pg_read_file、pg_sleep 等）
    # 先排除 SQL 关键字，避免 SELECT( 等被误判
    called_functions = (
        set(re.findall(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", sql_lower))
        - _FUNCTION_CHECK_EXCLUDED
    )
    unknown_functions = called_functions - ALLOWED_SQL_FUNCTIONS
    if unknown_functions:
        return {
            "is_safe": False,
            "reason": f"Forbidden SQL functions: {sorted(unknown_functions)}",
            "corrected_sql": None,
        }

    # V0.5.2：无公司过滤的 ORDER BY 必须伴随 LIMIT（防全表排序无界查询）
    # 排名查询特征：WHERE 中无 stock_code 过滤 → 全市场扫描，必须有 LIMIT
    # 其他查询（point/compare/trend/yoy）均在 WHERE 子句中有 stock_code =/IN 过滤
    # 仅检查 WHERE 之后的内容，避免 SELECT/ON 子句中的列引用干扰
    has_order_by = bool(re.search(r"\border\s+by\b", sql_lower))
    has_limit = bool(re.search(r"\blimit\s+\d+", sql_lower))
    if has_order_by and not has_limit:
        where_match = re.search(r"\bwhere\b", sql_lower)
        after_where = sql_lower[where_match.start():] if where_match else ""
        has_company_filter = bool(re.search(r"\bstock_code\b", after_where))
        if not has_company_filter:
            return {
                "is_safe": False,
                "reason": "全表 ORDER BY 查询缺少 LIMIT，拒绝执行。",
                "corrected_sql": None,
            }

    # V0.5.2：LIMIT 上限校验（与 ranking_validator 保持一致）
    if has_limit:
        limit_match = re.search(r"\blimit\s+(\d+)", sql_lower)
        if limit_match and int(limit_match.group(1)) > 50:
            return {
                "is_safe": False,
                "reason": f"LIMIT {limit_match.group(1)} 超过最大允许值（50）。",
                "corrected_sql": None,
            }

    return {
        "is_safe": True,
        "reason": "SQL passed basic safety checks.",
        "corrected_sql": sql,
    }


@tool
def execute_financial_sql(sql: str) -> dict:
    """
    Execute a validated read-only SQL query on the financial statement database.
    Use this tool only after SQL safety review.
    """
    review = review_sql(sql)

    if not review["is_safe"]:
        return {
            "success": False,
            "columns": [],
            "rows": [],
            "row_count": 0,
            "error": review["reason"],
        }

    return execute_readonly_sql(sql)
