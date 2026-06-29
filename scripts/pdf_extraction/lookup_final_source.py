import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

import psycopg2

from db_config import get_db_config


DB_CONFIG = get_db_config()

SUPPORTED_FINAL_TABLES = ["balance_sheet", "income_sheet", "cash_flow_sheet", "core_performance"]


def normalize_text(value) -> str:
    """统一转为去空白字符串。"""
    if value is None:
        return ""
    return str(value).strip()


def normalize_stock_code(value: str) -> str:
    """统一股票代码为 6 位。"""
    text = normalize_text(value)
    if text.isdigit() and len(text) <= 6:
        return text.zfill(6)
    return text


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description="查询最终表字段值及其 lineage 来源。")
    parser.add_argument("--stock-code", required=True, help="股票代码。")
    parser.add_argument("--year", required=True, type=int, help="报告年份。")
    parser.add_argument("--period", default="FY", help="报告期，默认 FY。")
    parser.add_argument("--field", required=True, help="最终字段名。")
    parser.add_argument("--table", choices=SUPPORTED_FINAL_TABLES, help="最终表名，可选。")
    return parser.parse_args()


def fetch_latest_lineage(
    conn,
    stock_code: str,
    report_year: int,
    report_period: str,
    final_field: str,
    final_table: Optional[str],
) -> List[Dict]:
    """读取匹配字段的最新 lineage。"""
    where_parts = [
        "stock_code = %s",
        "report_year = %s",
        "report_period = %s",
        "final_field = %s",
    ]
    params: List = [stock_code, report_year, report_period, final_field]
    if final_table:
        where_parts.append("final_table = %s")
        params.append(final_table)

    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT DISTINCT ON (final_table, final_field)
            run_id,
            file_id,
            stock_code,
            company_name,
            report_year,
            report_period,
            final_table,
            final_field,
            final_value,
            source_table,
            source_result_id,
            source_page_no,
            source_text,
            source_raw_value,
            extract_method,
            extract_status,
            confidence,
            diagnostic_json,
            created_at
        FROM final_table_lineage
        WHERE {' AND '.join(where_parts)}
        ORDER BY final_table, final_field, created_at DESC, id DESC
        """,
        params,
    )
    columns = [item[0] for item in cur.description]
    rows = [dict(zip(columns, row)) for row in cur.fetchall()]
    cur.close()
    return rows


def main() -> int:
    """命令行入口。"""
    args = parse_args()
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        rows = fetch_latest_lineage(
            conn=conn,
            stock_code=normalize_stock_code(args.stock_code),
            report_year=args.year,
            report_period=normalize_text(args.period).upper(),
            final_field=normalize_text(args.field),
            final_table=normalize_text(args.table) or None,
        )
    finally:
        conn.close()

    payload = {"query": vars(args), "count": len(rows), "results": rows}
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0 if rows else 1


if __name__ == "__main__":
    sys.exit(main())

