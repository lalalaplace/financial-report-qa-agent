"""ranking / rank_position 执行层 SQL Guard 回归测试。"""

from __future__ import annotations

from sqlalchemy import create_engine, text

from agent.nodes.sql_nodes.ranking_sql import build_base_ranking_sql
from agent.nodes.sql_nodes.rank_position_sql import build_base_rank_position_sql
from agent.tools.sql_tools import review_sql
from db import readonly_executor


BASE_METRIC = {
    "table": "income_sheet",
    "field": "operating_revenue",
    "metric_key": "operating_revenue",
    "metric_name": "营业收入",
    "metric_type": "base",
    "unit": "yuan",
}


def _build_sqlite_engine(company_count: int = 250):
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE company_dim (
                    stock_code TEXT PRIMARY KEY,
                    stock_abbr TEXT,
                    company_name TEXT
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE income_sheet (
                    stock_code TEXT,
                    report_year INTEGER,
                    report_period TEXT,
                    operating_revenue REAL
                )
                """
            )
        )
        for index in range(1, company_count + 1):
            stock_code = f"{index:06d}"
            conn.execute(
                text(
                    """
                    INSERT INTO company_dim (stock_code, stock_abbr, company_name)
                    VALUES (:stock_code, :stock_abbr, :company_name)
                    """
                ),
                {
                    "stock_code": stock_code,
                    "stock_abbr": f"公司{index}",
                    "company_name": f"测试公司{index}",
                },
            )
            conn.execute(
                text(
                    """
                    INSERT INTO income_sheet (
                        stock_code, report_year, report_period, operating_revenue
                    )
                    VALUES (:stock_code, 2024, 'FY', :operating_revenue)
                    """
                ),
                {
                    "stock_code": stock_code,
                    "operating_revenue": float(company_count - index + 1),
                },
            )
    return engine


def _target_company(stock_code: str = "000250") -> dict:
    return {
        "stock_code": stock_code,
        "stock_abbr": f"公司{int(stock_code)}",
        "company_name": f"测试公司{int(stock_code)}",
    }


def test_ranking_query_sql_passes_review_sql():
    sql = build_base_ranking_sql(
        metric=BASE_METRIC,
        report_year=2024,
        report_period="FY",
        rank_direction="desc",
        limit=10,
    )

    review = review_sql(sql)

    assert review["is_safe"] is True


def test_rank_position_query_sql_passes_review_sql():
    sql = build_base_rank_position_sql(
        metric=BASE_METRIC,
        company=_target_company(),
        report_year=2024,
        report_period="FY",
        rank_direction="desc",
    )

    review = review_sql(sql)

    assert review["is_safe"] is True


def test_readonly_executor_allows_rank_position_window_functions(monkeypatch):
    engine = _build_sqlite_engine()
    monkeypatch.setattr(readonly_executor, "get_engine", lambda: engine)
    sql = build_base_rank_position_sql(
        metric=BASE_METRIC,
        company=_target_company("000250"),
        report_year=2024,
        report_period="FY",
        rank_direction="desc",
    )

    result = readonly_executor.execute_readonly_sql(sql)

    assert result["success"] is True
    assert result["row_count"] == 1
    row = dict(zip(result["columns"], result["rows"][0]))
    assert row["rank_no"] == 250
    assert row["total_count"] == 250


def test_readonly_executor_still_rejects_non_whitelisted_functions(monkeypatch):
    engine = _build_sqlite_engine()
    monkeypatch.setattr(readonly_executor, "get_engine", lambda: engine)

    result = readonly_executor.execute_readonly_sql("SELECT random()")

    assert result["success"] is False
    assert "Forbidden SQL functions" in result["error"]
    assert "random" in result["error"]


def test_readonly_outer_limit_does_not_change_rank_position(monkeypatch):
    engine = _build_sqlite_engine(company_count=250)
    monkeypatch.setattr(readonly_executor, "get_engine", lambda: engine)
    sql = build_base_rank_position_sql(
        metric=BASE_METRIC,
        company=_target_company("000250"),
        report_year=2024,
        report_period="FY",
        rank_direction="desc",
    ).strip().rstrip(";")

    with engine.connect() as conn:
        raw_result = conn.execute(text(sql))
        raw_columns = list(raw_result.keys())
        raw_row = dict(zip(raw_columns, list(raw_result.fetchone())))

    limited_result = readonly_executor.execute_readonly_sql(sql, limit=200)
    limited_row = dict(zip(limited_result["columns"], limited_result["rows"][0]))

    assert limited_result["success"] is True
    assert raw_row["rank_no"] == 250
    assert raw_row["total_count"] == 250
    assert limited_row["rank_no"] == raw_row["rank_no"]
    assert limited_row["total_count"] == raw_row["total_count"]
