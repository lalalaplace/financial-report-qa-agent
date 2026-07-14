import argparse
import os
import csv
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import psycopg2


DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "teddy_b",
    "user": "postgres",
    "password": os.environ["DB_PASSWORD"],
}

EXTRACT_METHOD = "manual_backfill"
SKIP_FINAL_FIELD_NAMES = {
    "serial_number",
    "stock_code",
    "stock_abbr",
    "report_year",
    "report_period",
}
REQUIRED_COLUMNS = [
    "file_id",
    "target_table",
    "field_code",
    "field_name_cn",
    "manual_value",
]
OPTIONAL_RESULT_COLUMNS = [
    ("raw_line_name", "TEXT"),
    ("normalized_line_name", "TEXT"),
    ("source_page", "INTEGER"),
    ("source_column_role", "VARCHAR(64)"),
    ("unit", "VARCHAR(32)"),
    ("confidence", "DOUBLE PRECISION"),
    ("extra_info_json", "TEXT"),
]


def configure_console() -> None:
    """配置控制台编码。"""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None:
            continue
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def safe_text(value) -> str:
    """将任意对象转为安全文本。"""
    if value is None:
        return ""
    try:
        return str(value)
    except Exception:
        return repr(value)


def safe_print(*args) -> None:
    """安全输出。"""
    text = " ".join(safe_text(arg) for arg in args)
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("utf-8", errors="replace").decode("utf-8", errors="replace"))


def normalize_text(value) -> str:
    """标准化文本。"""
    if value is None:
        return ""
    text = str(value)
    text = text.replace("\u3000", " ")
    text = text.replace("\xa0", " ")
    return text.strip()


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description="导入人工补录 CSV，并写回 attachment3_extract_result。")
    parser.add_argument("--csv-path", required=True, help="人工补录 CSV 路径。")
    return parser.parse_args()


def get_table_columns(conn, table_name: str) -> set:
    """读取真实字段集合。"""
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
    rows = cur.fetchall()
    cur.close()
    return {row[0] for row in rows}


def ensure_extract_result_schema(conn) -> set:
    """按需补齐中间结果表可选字段。"""
    cur = conn.cursor()
    try:
        for column_name, column_type in OPTIONAL_RESULT_COLUMNS:
            cur.execute(f"ALTER TABLE attachment3_extract_result ADD COLUMN IF NOT EXISTS {column_name} {column_type}")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
    return get_table_columns(conn, "attachment3_extract_result")


def read_csv_rows(csv_path: Path) -> List[Dict]:
    """读取 CSV 行。"""
    with csv_path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        rows = []
        for index, row in enumerate(reader, start=2):
            normalized_row = {normalize_text(key): normalize_text(value) for key, value in (row or {}).items()}
            normalized_row["_line_no"] = index
            rows.append(normalized_row)
    return rows


def fetch_report_meta(conn, file_id: int) -> Optional[Dict]:
    """读取单个文件的元数据。"""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            file_id,
            company_id,
            stock_code,
            stock_abbr,
            report_year,
            report_period
        FROM report_file_index
        WHERE file_id = %s
        """,
        (file_id,),
    )
    row = cur.fetchone()
    cur.close()
    if row is None:
        return None
    return {
        "file_id": row[0],
        "company_id": row[1],
        "stock_code": normalize_text(row[2]),
        "stock_abbr": normalize_text(row[3]),
        "report_year": row[4],
        "report_period": normalize_text(row[5]),
    }


def field_exists(conn, target_table: str, field_code: str) -> bool:
    """校验字段是否存在于附件3字典。"""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT 1
        FROM attachment3_field_dict
        WHERE target_table = %s
          AND field_code = %s
        LIMIT 1
        """,
        (target_table, field_code),
    )
    row = cur.fetchone()
    cur.close()
    return row is not None


def build_insert_columns(table_columns: set) -> List[str]:
    """构造本次写入列集合。"""
    insert_columns = [
        "file_id",
        "company_id",
        "stock_code",
        "stock_abbr",
        "report_year",
        "report_period",
        "target_table",
        "field_code",
        "field_name_cn",
        "value_text",
        "source_page_range",
        "source_text",
        "extract_method",
    ]
    for column_name, _column_type in OPTIONAL_RESULT_COLUMNS:
        if column_name in table_columns:
            insert_columns.append(column_name)
    return insert_columns


def delete_existing_manual_rows(conn, file_id: int, target_table: str, field_code: str) -> int:
    """删除已有人工补录结果，保证幂等。"""
    cur = conn.cursor()
    try:
        cur.execute(
            """
            DELETE FROM attachment3_extract_result
            WHERE file_id = %s
              AND target_table = %s
              AND field_code = %s
              AND extract_method = %s
            """,
            (file_id, target_table, field_code, EXTRACT_METHOD),
        )
        deleted_rows = cur.rowcount
        conn.commit()
        return deleted_rows
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


def insert_manual_row(conn, insert_columns: List[str], row_data: Dict) -> None:
    """插入单条人工补录结果。"""
    cur = conn.cursor()
    try:
        values = tuple(row_data.get(column) for column in insert_columns)
        placeholders = ", ".join(["%s"] * len(insert_columns))
        cur.execute(
            f"""
            INSERT INTO attachment3_extract_result ({", ".join(insert_columns)})
            VALUES ({placeholders})
            """,
            values,
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


def validate_row(row: Dict) -> Tuple[bool, str]:
    """校验 CSV 行基础格式。"""
    for column in REQUIRED_COLUMNS:
        if not normalize_text(row.get(column)):
            return False, f"缺少必填列 {column}"

    try:
        int(normalize_text(row.get("file_id")))
    except ValueError:
        return False, "file_id 不是合法整数"

    field_code = normalize_text(row.get("field_code"))
    final_field_name = normalize_text(field_code.split(".", 1)[1] if "." in field_code else field_code)
    if final_field_name in SKIP_FINAL_FIELD_NAMES:
        return False, f"字段 {field_code} 属于元数据字段，不允许人工补录"

    if not normalize_text(row.get("manual_value")):
        return False, "manual_value 为空"

    return True, ""


def main() -> int:
    """主流程。"""
    configure_console()
    args = parse_args()
    csv_path = Path(args.csv_path).resolve()
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV 文件不存在：{csv_path}")

    rows = read_csv_rows(csv_path)
    safe_print(f"读取 CSV 行数：{len(rows)} | path={csv_path}")
    if not rows:
        safe_print("CSV 内容为空，无需导入。")
        return 0

    conn = psycopg2.connect(**DB_CONFIG)
    table_columns = ensure_extract_result_schema(conn)
    insert_columns = build_insert_columns(table_columns)

    imported_count = 0
    skipped_count = 0
    failed_count = 0
    failed_lines: List[str] = []

    try:
        for row in rows:
            line_no = row["_line_no"]
            ok, reason = validate_row(row)
            if not ok:
                skipped_count += 1
                safe_print(f"[跳过] line={line_no} | reason={reason}")
                continue

            file_id = int(normalize_text(row["file_id"]))
            target_table = normalize_text(row["target_table"])
            field_code = normalize_text(row["field_code"])
            field_name_cn = normalize_text(row["field_name_cn"])

            try:
                report_meta = fetch_report_meta(conn, file_id)
                if report_meta is None:
                    raise RuntimeError(f"report_file_index 中不存在 file_id={file_id}")
                if not field_exists(conn, target_table, field_code):
                    raise RuntimeError(f"字段不存在：target_table={target_table}, field_code={field_code}")

                delete_previous = delete_existing_manual_rows(conn, file_id, target_table, field_code)
                extra_info = {
                    "manual_note": normalize_text(row.get("manual_note")),
                    "source": "csv_manual_backfill",
                    "csv_path": str(csv_path),
                    "csv_line_no": line_no,
                }
                row_data = {
                    "file_id": file_id,
                    "company_id": report_meta["company_id"],
                    "stock_code": report_meta["stock_code"],
                    "stock_abbr": report_meta["stock_abbr"],
                    "report_year": report_meta["report_year"],
                    "report_period": report_meta["report_period"],
                    "target_table": target_table,
                    "field_code": field_code,
                    "field_name_cn": field_name_cn,
                    "value_text": normalize_text(row.get("manual_value")),
                    "source_page_range": normalize_text(row.get("manual_source_page_range")),
                    "source_text": normalize_text(row.get("manual_source_text")),
                    "extract_method": EXTRACT_METHOD,
                    "raw_line_name": "",
                    "normalized_line_name": "",
                    "source_page": None,
                    "source_column_role": "manual_backfill",
                    "unit": "",
                    "confidence": 1.0,
                    "extra_info_json": json.dumps(extra_info, ensure_ascii=False),
                }
                insert_manual_row(conn, insert_columns, row_data)
                imported_count += 1
                safe_print(
                    f"[导入] line={line_no} | file_id={file_id} | target_table={target_table} | "
                    f"field_code={field_code} | deleted_old_rows={delete_previous}"
                )
            except Exception as exc:
                failed_count += 1
                failed_lines.append(f"line={line_no}: {safe_text(exc)}")
                safe_print(f"[失败] line={line_no} | file_id={file_id} | field_code={field_code} | error={safe_text(exc)}")
    finally:
        conn.close()

    safe_print(
        f"导入完成：imported={imported_count} | skipped={skipped_count} | failed={failed_count}"
    )
    if failed_lines:
        safe_print("失败明细：")
        for item in failed_lines:
            safe_print(item)

    return 1 if failed_count > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
