"""受控 LLM SQL 的静态安全校验。

当前仓库没有根目录依赖清单可直接加入 sqlglot，因此这里采用保守的
token/正则校验。该实现优先拒绝可疑 SQL，不承担完整 SQL AST 解析能力。
"""

from __future__ import annotations

import re
from typing import Any

from agent.tools.sql_tools import ALLOWED_SQL_FUNCTIONS, ALLOWED_TABLES, ALLOWED_TABLE_COLUMNS


DANGEROUS_KEYWORDS = {
    "attach",
    "alter",
    "copy",
    "create",
    "delete",
    "drop",
    "export",
    "insert",
    "install",
    "load",
    "pragma",
    "update",
}

SQL_KEYWORDS = {
    "abs",
    "and",
    "as",
    "asc",
    "between",
    "by",
    "case",
    "coalesce",
    "count",
    "current_value",
    "desc",
    "distinct",
    "double",
    "else",
    "end",
    "from",
    "group",
    "having",
    "in",
    "is",
    "join",
    "left",
    "limit",
    "not",
    "null",
    "nullif",
    "on",
    "or",
    "order",
    "over",
    "partition",
    "previous_value",
    "rank",
    "row_number",
    "lag",
    "dense_rank",
    "round",
    "select",
    "then",
    "when",
    "where",
    "with",
    "decimal",
    "float",
    "integer",
    "varchar",
}


def _clean_sql(sql: str) -> str:
    return sql.strip().rstrip(";")


def _cte_names(sql_lower: str) -> set[str]:
    if not sql_lower.startswith("with"):
        return set()
    return set(re.findall(r"(?:\bwith\b|,)\s*([a-zA-Z_][a-zA-Z0-9_]*)\s+as\s*\(", sql_lower))


def _table_aliases(sql_lower: str, cte_names: set[str]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    table_pattern = re.compile(r"\b(from|join)\s+([a-zA-Z_][a-zA-Z0-9_]*)")
    for match in table_pattern.finditer(sql_lower):
        table = match.group(2)
        if table in cte_names:
            aliases[table] = "__cte__"
        else:
            aliases[table] = table

    alias_pattern = re.compile(
        r"\b(?:from|join)\s+([a-zA-Z_][a-zA-Z0-9_]*)\s+(?:as\s+)?([a-zA-Z_][a-zA-Z0-9_]*)"
    )
    for match in alias_pattern.finditer(sql_lower):
        table, alias = match.group(1), match.group(2)
        if alias in SQL_KEYWORDS:
            continue
        aliases[alias] = "__cte__" if table in cte_names else table
    return aliases


def _mentioned_tables(sql_lower: str) -> set[str]:
    matches = re.findall(
        r"\bfrom\s+([a-zA-Z_][a-zA-Z0-9_]*)|\bjoin\s+([a-zA-Z_][a-zA-Z0-9_]*)",
        sql_lower,
    )
    return {item for pair in matches for item in pair if item}


def _allowed_columns(allowed_columns: dict[str, list[str]] | None) -> dict[str, set[str]]:
    if allowed_columns:
        return {table: set(columns) for table, columns in allowed_columns.items()}
    return {table: set(columns) for table, columns in ALLOWED_TABLE_COLUMNS.items()}


REPAIRABLE_ERROR_TYPES = {
    "SELECT_STAR_NOT_ALLOWED",
    "MISSING_LIMIT",
    "RANKING_MISSING_ORDER_BY",
    "OUTPUT_FIELD_MISSING",
    "COLUMN_ALIAS_MISSING",
    "YOY_MISSING_ZERO_PROTECTION",
    "YOY_MISSING_PREVIOUS_YEAR",
}


def _is_select_star_error(error_type: str, message: str) -> bool:
    message_lower = message.lower()
    return error_type in {"SELECT_STAR_NOT_ALLOWED", "SQL_FIELD_NOT_ALLOWED"} and (
        "select *" in message_lower or ".*" in message_lower
    )


def _repairable_info(error_type: str, message: str) -> tuple[bool, str | None]:
    if _is_select_star_error(error_type, message):
        return True, "删除所有 SELECT * 和 table_alias.*，在每个 CTE 与最终 SELECT 中显式列出白名单字段。"
    if error_type in REPAIRABLE_ERROR_TYPES:
        hints = {
            "MISSING_LIMIT": "为明细查询补充不超过 max_rows 的 LIMIT。",
            "RANKING_MISSING_ORDER_BY": "排名或 TopN 查询必须补齐 ORDER BY 和 LIMIT。",
            "OUTPUT_FIELD_MISSING": "补齐 expected_output.must_include 要求的输出字段。",
            "COLUMN_ALIAS_MISSING": "为计算字段补充明确别名。",
            "YOY_MISSING_ZERO_PROTECTION": "同比计算必须使用 NULLIF 或 CASE WHEN 保护上年值为 0 的情况。",
            "YOY_MISSING_PREVIOUS_YEAR": "同比查询必须同时包含当前年份和上一年份。",
        }
        return True, hints.get(error_type, "按 validation_error 修复 SQL，但不得改变用户问题语义。")
    if error_type == "SQL_SEMANTIC_INVALID" and "limit" in message.lower():
        return True, "为明细查询补充不超过 max_rows 的 LIMIT。"
    return False, None


def _reject(error_type: str, message: str, **extra: Any) -> dict[str, Any]:
    repairable, repair_hint = _repairable_info(error_type, message)
    return {
        "is_valid": False,
        "error_type": error_type,
        "error_message": message,
        "guard_passed": False,
        "repairable": repairable,
        "repair_hint": repair_hint,
        **extra,
    }


def validate_llm_sql_static(
    sql: str,
    *,
    allowed_tables: list[str] | None = None,
    allowed_columns: dict[str, list[str]] | None = None,
    allowed_functions: set[str] | None = None,
    max_rows: int = 50,
    require_report_year: bool = True,
) -> dict[str, Any]:
    """校验 LLM 生成 SQL 是否满足只读、表字段白名单和行数约束。"""
    sql_clean = _clean_sql(sql)
    sql_lower = sql_clean.lower()
    allowed_table_set = set(allowed_tables or sorted(ALLOWED_TABLES))
    allowed_column_map = _allowed_columns(allowed_columns)
    allowed_function_set = set(allowed_functions or ALLOWED_SQL_FUNCTIONS) | {"abs"}

    if not sql_clean:
        return _reject("SQL_UNSAFE", "SQL 为空。")
    if ";" in sql_clean:
        return _reject("SQL_UNSAFE", "不允许多语句 SQL。")
    if not (sql_lower.startswith("select") or sql_lower.startswith("with")):
        return _reject("SQL_UNSAFE", "只允许 SELECT 或 WITH SELECT。")
    for keyword in DANGEROUS_KEYWORDS:
        if re.search(rf"\b{keyword}\b", sql_lower):
            return _reject("SQL_UNSAFE", f"检测到禁止关键字：{keyword}。")
    if re.search(r"\bselect\s+\*", sql_lower) or re.search(r"\b[a-zA-Z_][a-zA-Z0-9_]*\.\*", sql_lower):
        return _reject("SQL_FIELD_NOT_ALLOWED", "不允许 SELECT *。")

    ctes = _cte_names(sql_lower)
    tables = _mentioned_tables(sql_lower)
    real_tables = tables - ctes
    unknown_tables = real_tables - allowed_table_set
    if unknown_tables:
        return _reject(
            "SQL_TABLE_NOT_ALLOWED",
            f"SQL 访问了非白名单表：{sorted(unknown_tables)}。",
            used_tables=sorted(real_tables),
        )

    alias_to_table = _table_aliases(sql_lower, ctes)
    used_fields: set[str] = set()
    for qualifier, column in re.findall(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z_][a-zA-Z0-9_]*)\b", sql_lower):
        table = alias_to_table.get(qualifier)
        if table is None:
            matching_tables = [name for name in real_tables if column in allowed_column_map.get(name, set())]
            if len(matching_tables) == 1:
                table = matching_tables[0]
            else:
                return _reject("SQL_FIELD_NOT_ALLOWED", f"未知字段限定符：{qualifier}。", used_tables=sorted(real_tables))
        if table == "__cte__":
            used_fields.add(column)
            continue
        if column not in allowed_column_map.get(table, set()):
            matching_tables = [name for name in real_tables if column in allowed_column_map.get(name, set())]
            if len(matching_tables) == 1:
                table = matching_tables[0]
            else:
                return _reject("SQL_FIELD_NOT_ALLOWED", f"字段不在白名单内：{table}.{column}。", used_tables=sorted(real_tables))
        used_fields.add(f"{table}.{column}")

    known_unqualified_columns = set().union(*allowed_column_map.values()) if allowed_column_map else set()
    select_match = re.search(r"\bselect\b(?P<select>.*?)\bfrom\b", sql_lower, re.DOTALL)
    if select_match:
        select_clause = select_match.group("select")
        called_in_select = set(re.findall(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", select_clause))
        output_aliases = set(re.findall(r"\bas\s+([a-zA-Z_][a-zA-Z0-9_]*)\b", select_clause))
        bare_tokens = set(re.findall(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\b", select_clause))
        bare_tokens -= SQL_KEYWORDS
        bare_tokens -= output_aliases
        bare_tokens -= set(alias_to_table)
        bare_tokens -= allowed_function_set
        bare_tokens -= called_in_select
        for token in bare_tokens:
            if token in {"current_value", "previous_value"}:
                continue
            if token not in known_unqualified_columns and not token.isdigit():
                return _reject("SQL_FIELD_NOT_ALLOWED", f"字段不在白名单内：{token}。", used_tables=sorted(real_tables))

    called_functions = set(re.findall(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", sql_lower))
    unknown_functions = called_functions - SQL_KEYWORDS - ctes - allowed_function_set
    if unknown_functions:
        return _reject("SQL_UNSAFE", f"函数不在白名单内：{sorted(unknown_functions)}。", used_tables=sorted(real_tables))

    if require_report_year and real_tables.intersection({"income_sheet", "balance_sheet", "cash_flow_sheet", "core_performance"}):
        if not re.search(r"\breport_year\b\s*(=|in|between)", sql_lower):
            return _reject("SQL_SEMANTIC_INVALID", "财报事实表查询必须显式约束 report_year。", used_tables=sorted(real_tables))

    if len(real_tables) >= 2 and re.search(r"\bjoin\b", sql_lower) and not re.search(r"\bon\b[^;]*\bstock_code\b", sql_lower):
        return _reject("SQL_SEMANTIC_INVALID", "多表 JOIN 必须包含 stock_code 连接条件。", used_tables=sorted(real_tables))

    has_group_or_aggregate = bool(re.search(r"\b(group\s+by|count\s*\(|sum\s*\(|avg\s*\(|min\s*\(|max\s*\()", sql_lower))
    limit_matches = re.findall(r"\blimit\s+(\d+)", sql_lower)
    final_limit = int(limit_matches[-1]) if limit_matches else None
    if final_limit is not None and final_limit > max_rows:
        return _reject("SQL_SEMANTIC_INVALID", f"LIMIT 超过最大允许行数 {max_rows}。", used_tables=sorted(real_tables))
    if not has_group_or_aggregate and final_limit is None:
        return _reject("SQL_SEMANTIC_INVALID", "非聚合明细查询必须包含 LIMIT。", used_tables=sorted(real_tables))

    if re.search(r"\btop\b|\border\s+by\b", sql_lower) and final_limit is None:
        return _reject("RANKING_MISSING_ORDER_BY", "TopN 或排序类查询必须包含 LIMIT。", used_tables=sorted(real_tables))

    return {
        "is_valid": True,
        "error_type": None,
        "error_message": None,
        "used_tables": sorted(real_tables),
        "used_fields": sorted(used_fields),
        "guard_passed": True,
    }


__all__ = ["validate_llm_sql_static"]
