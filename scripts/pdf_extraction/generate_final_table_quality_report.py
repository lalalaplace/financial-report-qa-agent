import argparse
import os
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

import psycopg2
from psycopg2 import sql


DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "teddy_b",
    "user": "postgres",
    "password": os.environ["DB_PASSWORD"],
}

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = PROJECT_ROOT / "output" / "pdf_extraction" / "validation"
FINAL_TABLES = ["balance_sheet", "income_sheet", "cash_flow_sheet"]
BASE_COLUMNS = {
    "serial_number",
    "file_id",
    "company_id",
    "stock_code",
    "stock_abbr",
    "company_name",
    "report_year",
    "report_period",
    "created_at",
    "updated_at",
}


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description="生成最终表质量报告。")
    parser.add_argument("--run-id", required=True, help="需要统计的 run_id。")
    return parser.parse_args()


def fetch_one(conn, query, params: tuple = ()):
    """执行查询并返回单行。"""
    cur = conn.cursor()
    cur.execute(query, params)
    row = cur.fetchone()
    cur.close()
    return row


def fetch_table_columns(conn, table_name: str) -> List[str]:
    """读取最终表字段。"""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s
        ORDER BY ordinal_position
        """,
        (table_name,),
    )
    rows = [row[0] for row in cur.fetchall()]
    cur.close()
    return rows


def fetch_distribution(conn, run_id: str, table_name: str, column_name: str) -> Dict[str, int]:
    """统计 lineage 中某个字段的分布。"""
    cur = conn.cursor()
    cur.execute(
        sql.SQL(
            """
            SELECT COALESCE({column}::text, ''), COUNT(*)
            FROM final_table_lineage
            WHERE run_id = %s AND final_table = %s
            GROUP BY COALESCE({column}::text, '')
            ORDER BY COUNT(*) DESC, COALESCE({column}::text, '')
            """
        ).format(column=sql.Identifier(column_name)),
        (run_id, table_name),
    )
    result = {(row[0] or "unknown"): int(row[1]) for row in cur.fetchall()}
    cur.close()
    return result


def calculate_final_non_null_count(conn, run_id: str, table_name: str) -> Optional[int]:
    """统计当前 run 相关最终表记录的业务字段非空数量。"""
    columns = [column for column in fetch_table_columns(conn, table_name) if column not in BASE_COLUMNS]
    if not columns:
        return 0

    expressions = sql.SQL(" + ").join(
        sql.SQL("CASE WHEN {column} IS NOT NULL THEN 1 ELSE 0 END").format(column=sql.Identifier(column))
        for column in columns
    )
    query = sql.SQL(
        """
        WITH lineage_keys AS (
            SELECT DISTINCT stock_code, report_year, report_period
            FROM final_table_lineage
            WHERE run_id = %s AND final_table = %s
        )
        SELECT COALESCE(SUM({expressions}), 0)
        FROM {table_name} AS final
        INNER JOIN lineage_keys AS keys
            ON final.stock_code = keys.stock_code
           AND final.report_year = keys.report_year
           AND final.report_period = keys.report_period
        """
    ).format(expressions=expressions, table_name=sql.Identifier(table_name))
    try:
        row = fetch_one(conn, query, (run_id, table_name))
        return int(row[0] or 0)
    except Exception:
        conn.rollback()
        return None


def build_table_report(conn, run_id: str, table_name: str) -> Dict:
    """生成单张最终表质量统计。"""
    row = fetch_one(
        conn,
        """
        WITH lineage_keys AS (
            SELECT DISTINCT stock_code, report_year, report_period
            FROM final_table_lineage
            WHERE run_id = %s AND final_table = %s
        )
        SELECT COUNT(*)
        FROM lineage_keys AS keys
        INNER JOIN {table_name} AS final
            ON final.stock_code = keys.stock_code
           AND final.report_year = keys.report_year
           AND final.report_period = keys.report_period
        """.format(table_name=table_name),
        (run_id, table_name),
    )
    row_count = int(row[0] or 0)

    lineage_row = fetch_one(
        conn,
        """
        SELECT
            COUNT(*),
            AVG(confidence),
            SUM(CASE WHEN source_page_no IS NOT NULL THEN 1 ELSE 0 END),
            SUM(CASE WHEN source_text IS NOT NULL AND source_text::text <> '' THEN 1 ELSE 0 END)
        FROM final_table_lineage
        WHERE run_id = %s AND final_table = %s
        """,
        (run_id, table_name),
    )
    lineage_count = int(lineage_row[0] or 0)
    confidence_avg = float(lineage_row[1]) if lineage_row[1] is not None else None
    source_page_count = int(lineage_row[2] or 0)
    source_text_count = int(lineage_row[3] or 0)
    non_null_count = calculate_final_non_null_count(conn, run_id, table_name)

    if non_null_count in (None, 0):
        lineage_coverage = None
    else:
        lineage_coverage = round(lineage_count / non_null_count, 6)

    return {
        "row_count": row_count,
        "non_null_field_count": non_null_count,
        "lineage_count": lineage_count,
        "lineage_coverage": lineage_coverage,
        "extract_method_distribution": fetch_distribution(conn, run_id, table_name, "extract_method"),
        "extract_status_distribution": fetch_distribution(conn, run_id, table_name, "extract_status"),
        "confidence_avg": round(confidence_avg, 6) if confidence_avg is not None else None,
        "source_page_no_coverage": round(source_page_count / lineage_count, 6) if lineage_count else 0.0,
        "source_text_coverage": round(source_text_count / lineage_count, 6) if lineage_count else 0.0,
    }


def build_report(conn, run_id: str) -> Dict:
    """生成最终表质量报告。"""
    table_reports = {table: build_table_report(conn, run_id, table) for table in FINAL_TABLES}
    return {
        "run_id": run_id,
        "stable_final_tables": FINAL_TABLES,
        "note": "当前稳定刷新范围不包含 core_performance。",
        "tables": table_reports,
    }


def main() -> int:
    """命令行入口。"""
    args = parse_args()
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        report = build_report(conn, args.run_id)
    finally:
        conn.close()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / f"final_table_quality_report_{args.run_id}.json"
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"output={output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
