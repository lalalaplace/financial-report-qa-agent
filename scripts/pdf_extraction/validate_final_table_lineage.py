import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

import psycopg2

from db_config import get_db_config


DB_CONFIG = get_db_config()

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = PROJECT_ROOT / "output" / "pdf_extraction" / "validation"
FINAL_TABLES = ["balance_sheet", "income_sheet", "cash_flow_sheet", "core_performance"]
BASE_COLUMNS = {"serial_number", "file_id", "company_id", "stock_code", "stock_abbr", "company_name", "report_year", "report_period", "created_at", "updated_at"}


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description="验证 final_table_lineage 覆盖情况。")
    parser.add_argument("--run-id", required=True, help="需要验证的 run_id。")
    return parser.parse_args()


def fetch_count(conn, query: str, params: tuple = ()) -> int:
    """执行 count 查询。"""
    cur = conn.cursor()
    cur.execute(query, params)
    value = int(cur.fetchone()[0] or 0)
    cur.close()
    return value


def fetch_table_columns(conn, table_name: str) -> List[str]:
    """读取表字段。"""
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


def calculate_final_non_empty_count(conn, run_id: str, table_name: str) -> Optional[int]:
    """统计当前 run_id 相关逻辑键在最终表中的业务字段非空数量。"""
    columns = [column for column in fetch_table_columns(conn, table_name) if column not in BASE_COLUMNS]
    if not columns:
        return 0
    expressions = " + ".join(f"CASE WHEN {column} IS NOT NULL THEN 1 ELSE 0 END" for column in columns)
    try:
        return fetch_count(
            conn,
            f"""
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
            """,
            (run_id, table_name),
        )
    except Exception:
        conn.rollback()
        return None


def build_report(conn, run_id: str) -> Dict:
    """生成 lineage 验证报告。"""
    total_rows = fetch_count(conn, "SELECT COUNT(*) FROM final_table_lineage WHERE run_id = %s", (run_id,))
    cur = conn.cursor()
    cur.execute(
        """
        SELECT final_table, COUNT(*)
        FROM final_table_lineage
        WHERE run_id = %s
        GROUP BY final_table
        ORDER BY final_table
        """,
        (run_id,),
    )
    by_table = {row[0]: int(row[1]) for row in cur.fetchall()}
    cur.close()

    def coverage(column: str) -> float:
        if total_rows == 0:
            return 0.0
        covered = fetch_count(
            conn,
            f"SELECT COUNT(*) FROM final_table_lineage WHERE run_id = %s AND {column} IS NOT NULL AND {column}::text <> ''",
            (run_id,),
        )
        return round(covered / total_rows, 6)

    final_non_empty_by_table = {table: calculate_final_non_empty_count(conn, run_id, table) for table in FINAL_TABLES}
    lineage_vs_final = {}
    for table in FINAL_TABLES:
        lineage_count = by_table.get(table, 0)
        final_count = final_non_empty_by_table.get(table)
        if final_count is None or final_count == 0:
            ratio = None
        else:
            ratio = round(lineage_count / final_count, 6)
        lineage_vs_final[table] = {
            "lineage_rows": lineage_count,
            "final_non_empty_fields": final_count,
            "lineage_to_final_non_empty_ratio": ratio,
        }

    return {
        "run_id": run_id,
        "total_lineage_rows": total_rows,
        "rows_by_final_table": by_table,
        "source_result_id_coverage": coverage("source_result_id"),
        "source_page_no_coverage": coverage("source_page_no"),
        "source_text_coverage": coverage("source_text"),
        "lineage_vs_final_non_empty": lineage_vs_final,
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
    output_path = OUTPUT_DIR / f"lineage_validation_report_{args.run_id}.json"
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"output={output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

