import argparse
import os
import csv
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import psycopg2

from extract_attachment3_rule_based import (
    extract_cell,
    fetch_field_dict,
    find_column,
    find_row,
    parse_table_structure,
    should_skip_statement_field,
)
from statement_table_schema import load_normalized_table_json, normalize_text


DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "teddy_b",
    "user": "postgres",
    "password": os.environ["DB_PASSWORD"],
}

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATEMENT_JSON_DIR = PROJECT_ROOT / "output" / "pdf_extraction" / "statement_json"
OUTPUT_DIR = PROJECT_ROOT / "output" / "pdf_extraction" / "manual_backfill"
STATEMENT_TARGET_TABLE_MAP = {
    "balance_sheet": "balance_sheet",
    "income": "income",
    "cash_flow": "cash_flow",
}
SKIP_FINAL_FIELD_NAMES = {
    "serial_number",
    "stock_code",
    "stock_abbr",
    "report_year",
    "report_period",
}
CSV_HEADERS = [
    "file_id",
    "file_name",
    "stock_code",
    "stock_abbr",
    "report_year",
    "report_period",
    "statement_type",
    "target_table",
    "field_code",
    "field_name_cn",
    "source_page_range_hint",
    "source_text_hint",
    "current_rule_value",
    "manual_value",
    "manual_source_page_range",
    "manual_source_text",
    "manual_note",
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


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description="导出附件3人工补录任务 CSV。")
    parser.add_argument("--file-id", type=int, nargs="*", help="仅处理指定 file_id，可传多个。")
    parser.add_argument("--statement-type", choices=list(STATEMENT_TARGET_TABLE_MAP.keys()), nargs="*", help="仅处理指定报表类型。")
    parser.add_argument("--target-table", choices=list(STATEMENT_TARGET_TABLE_MAP.values()), nargs="*", help="仅处理指定目标表。")
    parser.add_argument("--limit", type=int, help="最多处理前 N 个 statement_json 文件。")
    return parser.parse_args()


def ensure_output_dir() -> None:
    """确保输出目录存在。"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def parse_json_name(file_name: str) -> Optional[Dict]:
    """从文件名解析 file_id 与 statement_type。"""
    import re

    match = re.match(r"file_(\d+)_(balance_sheet|income|cash_flow)\.json$", file_name)
    if not match:
        return None
    return {"file_id": int(match.group(1)), "statement_type": match.group(2)}


def list_statement_json_files(
    file_ids: Optional[List[int]] = None,
    statement_types: Optional[List[str]] = None,
    limit: Optional[int] = None,
) -> List[Path]:
    """列出待处理的 statement_json 文件。"""
    if not STATEMENT_JSON_DIR.exists():
        raise FileNotFoundError(f"statement_json 目录不存在：{STATEMENT_JSON_DIR}")

    file_id_filter = set(file_ids or [])
    statement_type_filter = set(statement_types or [])
    files: List[Path] = []
    for path in sorted(STATEMENT_JSON_DIR.glob("file_*_*.json")):
        parsed = parse_json_name(path.name)
        if parsed is None:
            continue
        if file_id_filter and parsed["file_id"] not in file_id_filter:
            continue
        if statement_type_filter and parsed["statement_type"] not in statement_type_filter:
            continue
        files.append(path)

    if limit is not None:
        files = files[:limit]
    return files


def fetch_report_meta(conn, file_ids: Optional[List[int]] = None) -> Dict[int, Dict]:
    """读取报表元数据。"""
    params: List = []
    where_sql = ""
    if file_ids:
        where_sql = "WHERE file_id = ANY(%s)"
        params.append(file_ids)

    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT
            file_id,
            file_name,
            stock_code,
            stock_abbr,
            report_year,
            report_period
        FROM report_file_index
        {where_sql}
        ORDER BY file_id
        """,
        params,
    )
    rows = cur.fetchall()
    cur.close()

    meta_map: Dict[int, Dict] = {}
    for row in rows:
        meta_map[row[0]] = {
            "file_id": row[0],
            "file_name": normalize_text(row[1]),
            "stock_code": normalize_text(row[2]),
            "stock_abbr": normalize_text(row[3]),
            "report_year": row[4],
            "report_period": normalize_text(row[5]),
        }
    return meta_map


def fetch_existing_results(
    conn,
    file_ids: Optional[List[int]] = None,
    target_tables: Optional[List[str]] = None,
) -> Dict[Tuple[int, str, str, str], Dict]:
    """读取现有中间结果。"""
    where_parts = ["COALESCE(field_code, '') <> ''"]
    params: List = []

    if file_ids:
        where_parts.append("file_id = ANY(%s)")
        params.append(file_ids)

    if target_tables:
        where_parts.append("target_table = ANY(%s)")
        params.append(target_tables)

    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT
            file_id,
            target_table,
            field_code,
            extract_method,
            value_text,
            source_page_range,
            source_text
        FROM attachment3_extract_result
        WHERE {' AND '.join(where_parts)}
        ORDER BY file_id, target_table, field_code, extract_method
        """,
        params,
    )
    rows = cur.fetchall()
    cur.close()

    result_map: Dict[Tuple[int, str, str, str], Dict] = {}
    for row in rows:
        key = (row[0], normalize_text(row[1]), normalize_text(row[2]), normalize_text(row[3]))
        result_map[key] = {
            "value_text": normalize_text(row[4]),
            "source_page_range": normalize_text(row[5]),
            "source_text": normalize_text(row[6]),
        }
    return result_map


def build_hint(field: Dict, table: Dict, statement_type: str) -> Tuple[str, str]:
    """为缺失字段生成定位提示。"""
    row_matches = find_row(field.get("aliases", []), table)
    if not row_matches:
        return "", ""

    best_match = row_matches[0]
    row = best_match["row"]
    column_index = find_column(table=table, statement_type=statement_type, prefer_current=True)
    cell = extract_cell(row, column_index) if column_index is not None else None

    page_hint = str(row.get("page_no") or "")
    source_parts = [
        f"候选行名={normalize_text(row.get('row_label'))}",
        f"匹配别名={normalize_text(best_match.get('alias'))}",
    ]
    if cell is not None:
        source_parts.append(f"候选列={normalize_text(cell.get('column_label'))}")
        source_parts.append(f"候选值={normalize_text(cell.get('value_text'))}")
    source_line = normalize_text(row.get("source_text"))
    if source_line:
        source_parts.append(f"原始行={source_line[:300]}")
    return page_hint, "\n".join(part for part in source_parts if part)


def build_task_rows(
    conn,
    json_files: List[Path],
    report_meta_map: Dict[int, Dict],
    existing_result_map: Dict[Tuple[int, str, str, str], Dict],
) -> List[Dict]:
    """构造待补录任务行。"""
    task_rows: List[Dict] = []

    for json_path in json_files:
        table_payload = load_normalized_table_json(json_path)
        statement_type = table_payload.statement_type
        target_table = STATEMENT_TARGET_TABLE_MAP[statement_type]
        report_meta = report_meta_map.get(table_payload.file_id, {})
        field_dict = fetch_field_dict(conn, target_table)
        table = parse_table_structure(table_payload)

        for field in field_dict:
            field_code = field["field_code"]
            final_field_name = normalize_text(field_code.split(".", 1)[1] if "." in field_code else field_code)
            if should_skip_statement_field(field_code):
                continue
            if final_field_name in SKIP_FINAL_FIELD_NAMES:
                continue

            rule_key = (table_payload.file_id, target_table, field_code, "rule")
            candidate_fill_key = (table_payload.file_id, target_table, field_code, "rule_candidate_fill")
            manual_key = (table_payload.file_id, target_table, field_code, "manual_backfill")

            rule_result = existing_result_map.get(rule_key)
            candidate_fill_result = existing_result_map.get(candidate_fill_key)
            manual_result = existing_result_map.get(manual_key)

            if manual_result and normalize_text(manual_result.get("value_text")):
                continue
            if rule_result and normalize_text(rule_result.get("value_text")):
                continue
            if candidate_fill_result and normalize_text(candidate_fill_result.get("value_text")):
                continue

            page_hint, text_hint = build_hint(field, table, statement_type)
            task_rows.append(
                {
                    "file_id": table_payload.file_id,
                    "file_name": report_meta.get("file_name", ""),
                    "stock_code": report_meta.get("stock_code", table_payload.stock_code),
                    "stock_abbr": report_meta.get("stock_abbr", table_payload.stock_abbr),
                    "report_year": report_meta.get("report_year", table_payload.report_year),
                    "report_period": report_meta.get("report_period", table_payload.report_period),
                    "statement_type": statement_type,
                    "target_table": target_table,
                    "field_code": field_code,
                    "field_name_cn": field["field_name_cn"],
                    "source_page_range_hint": page_hint,
                    "source_text_hint": text_hint,
                    "current_rule_value": normalize_text(rule_result.get("value_text")) if rule_result else "",
                    "manual_value": "",
                    "manual_source_page_range": "",
                    "manual_source_text": "",
                    "manual_note": "",
                }
            )

    return task_rows


def write_csv(task_rows: List[Dict]) -> Path:
    """写出任务 CSV。"""
    ensure_output_dir()
    output_path = OUTPUT_DIR / f"manual_backfill_tasks_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    with output_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_HEADERS)
        writer.writeheader()
        writer.writerows(task_rows)
    return output_path


def print_summary(task_rows: List[Dict]) -> None:
    """输出统计摘要。"""
    by_statement_type: Dict[str, int] = defaultdict(int)
    by_file_id: Dict[int, int] = defaultdict(int)
    for row in task_rows:
        by_statement_type[row["statement_type"]] += 1
        by_file_id[int(row["file_id"])] += 1

    safe_print(f"缺失任务总数：{len(task_rows)}")
    for statement_type, count in sorted(by_statement_type.items()):
        safe_print(f"[按报表类型] statement_type={statement_type} | missing_fields={count}")

    top_items = sorted(by_file_id.items(), key=lambda item: (-item[1], item[0]))[:20]
    for file_id, count in top_items:
        safe_print(f"[按文件缺失 Top] file_id={file_id} | missing_fields={count}")


def main() -> int:
    """主流程。"""
    configure_console()
    args = parse_args()

    statement_types = args.statement_type
    if args.target_table:
        target_statement_types = {key for key, value in STATEMENT_TARGET_TABLE_MAP.items() if value in set(args.target_table)}
        statement_types = sorted(target_statement_types if statement_types is None else set(statement_types) & target_statement_types)

    json_files = list_statement_json_files(
        file_ids=args.file_id,
        statement_types=statement_types,
        limit=args.limit,
    )
    safe_print(f"待扫描 statement_json 数量：{len(json_files)}")
    if not json_files:
        safe_print("没有可导出的 statement_json 文件。")
        return 0

    file_ids = sorted({parse_json_name(path.name)["file_id"] for path in json_files if parse_json_name(path.name)})
    target_tables = sorted({STATEMENT_TARGET_TABLE_MAP[parse_json_name(path.name)["statement_type"]] for path in json_files if parse_json_name(path.name)})

    conn = psycopg2.connect(**DB_CONFIG)
    try:
        report_meta_map = fetch_report_meta(conn, file_ids=file_ids)
        existing_result_map = fetch_existing_results(conn, file_ids=file_ids, target_tables=target_tables)
        task_rows = build_task_rows(conn, json_files, report_meta_map, existing_result_map)
    finally:
        conn.close()

    if not task_rows:
        safe_print("当前范围内没有需要人工补录的字段。")
        return 0

    output_path = write_csv(task_rows)
    print_summary(task_rows)
    safe_print(f"已导出人工补录任务：{output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
