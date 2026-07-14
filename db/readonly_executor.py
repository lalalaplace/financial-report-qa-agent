"""Agent 专用只读 SQL 执行器。"""

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine


DEFAULT_LIMIT = 200
MAX_LIMIT = 1000
DEFAULT_TIMEOUT_MS = 10000
FORBIDDEN_SQL_PATTERN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|merge|grant|revoke|call|execute|copy|vacuum|analyze)\b",
    re.IGNORECASE,
)

# V0.5.1：SQL 函数白名单（与 agent/tools/sql_tools.py 保持一致）
_ALLOWED_SQL_FUNCTIONS = {
    "cast", "count", "rank", "row_number", "dense_rank", "lag", "abs", "round", "coalesce", "nullif",
}
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


def _load_env_file() -> None:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue

        key, value = stripped.split("=", 1)
        key = key.strip().lstrip("\ufeff")
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def get_database_url() -> str | None:
    _load_env_file()
    return os.getenv("DATABASE_URL")


def _empty_result(error: str) -> dict[str, Any]:
    return {
        "success": False,
        "columns": [],
        "rows": [],
        "row_count": 0,
        "error": error,
    }


@lru_cache(maxsize=1)
def get_engine() -> "Engine":
    database_url = get_database_url()
    if not database_url:
        raise ValueError("DATABASE_URL is not set.")

    from sqlalchemy import create_engine

    return create_engine(
        database_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
    )


def _normalize_limit(limit: int) -> int:
    if limit <= 0:
        return DEFAULT_LIMIT
    return min(limit, MAX_LIMIT)


def _is_readonly_query(sql_clean: str) -> bool:
    sql_lower = sql_clean.lower()
    if not (sql_lower.startswith("select") or sql_lower.startswith("with")):
        return False
    return FORBIDDEN_SQL_PATTERN.search(sql_clean) is None


def _build_limited_sql(sql_clean: str, limit: int) -> str:
    return f"""
    SELECT *
    FROM (
        {sql_clean}
    ) AS subquery
    LIMIT {limit}
    """


def execute_readonly_sql(
    sql: str,
    limit: int = DEFAULT_LIMIT,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
) -> dict[str, Any]:
    sql_clean = sql.strip().rstrip(";")

    if not sql_clean:
        return _empty_result("SQL is empty.")

    if ";" in sql_clean:
        return _empty_result("Multiple SQL statements are not allowed.")

    if not _is_readonly_query(sql_clean):
        return _empty_result("Only SELECT or WITH queries are allowed.")

    # V0.5.1：函数白名单检查（数据库层兜底）
    sql_lower = sql_clean.lower()
    called_functions = (
        set(re.findall(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", sql_lower))
        - _FUNCTION_CHECK_EXCLUDED
    )
    unknown_functions = called_functions - _ALLOWED_SQL_FUNCTIONS
    if unknown_functions:
        return _empty_result(
            f"Forbidden SQL functions: {sorted(unknown_functions)}"
        )

    safe_limit = _normalize_limit(limit)
    limited_sql = _build_limited_sql(sql_clean, safe_limit)

    try:
        from sqlalchemy import text
        from sqlalchemy.exc import SQLAlchemyError
    except ImportError as exc:
        return _empty_result(str(exc))

    try:
        with get_engine().connect() as conn:
            if conn.dialect.name == "postgresql" and timeout_ms > 0:
                with conn.begin():
                    conn.execute(text("SET LOCAL statement_timeout = :timeout_ms"), {"timeout_ms": timeout_ms})
                    result = conn.execute(text(limited_sql))
                    columns = list(result.keys())
                    rows = [list(row) for row in result.fetchall()]
            else:
                result = conn.execute(text(limited_sql))
                columns = list(result.keys())
                rows = [list(row) for row in result.fetchall()]

        return {
            "success": True,
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
            "error": None,
        }

    except (SQLAlchemyError, ValueError) as exc:
        return _empty_result(str(exc))


def explain_sql(sql: str, timeout_ms: int = DEFAULT_TIMEOUT_MS) -> dict[str, Any]:
    """对只读 SQL 做 EXPLAIN，用于真实执行前的轻量校验。"""
    sql_clean = sql.strip().rstrip(";")
    if not sql_clean:
        return _empty_result("SQL is empty.")
    if ";" in sql_clean:
        return _empty_result("Multiple SQL statements are not allowed.")
    if not _is_readonly_query(sql_clean):
        return _empty_result("Only SELECT or WITH queries are allowed.")

    try:
        from sqlalchemy import text
        from sqlalchemy.exc import SQLAlchemyError
    except ImportError as exc:
        return _empty_result(str(exc))

    try:
        with get_engine().connect() as conn:
            if conn.dialect.name == "postgresql" and timeout_ms > 0:
                with conn.begin():
                    conn.execute(text("SET LOCAL statement_timeout = :timeout_ms"), {"timeout_ms": timeout_ms})
                    result = conn.execute(text(f"EXPLAIN {sql_clean}"))
                    rows = [list(row) for row in result.fetchall()]
            else:
                result = conn.execute(text(f"EXPLAIN {sql_clean}"))
                rows = [list(row) for row in result.fetchall()]
        return {
            "success": True,
            "columns": ["plan"],
            "rows": rows,
            "row_count": len(rows),
            "error": None,
        }
    except (SQLAlchemyError, ValueError) as exc:
        return _empty_result(str(exc))


def dry_run_sql(sql: str, limit: int = 5, timeout_ms: int = DEFAULT_TIMEOUT_MS) -> dict[str, Any]:
    """用小 LIMIT 执行只读 SQL，验证字段、语法和基本可执行性。"""
    return execute_readonly_sql(sql, limit=limit, timeout_ms=timeout_ms)
