import argparse
import os
import re
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional, Tuple

import psycopg2
from psycopg2 import sql
from psycopg2.extras import execute_values

DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "teddy_b",
    "user": "postgres",
    "password": os.environ["DB_PASSWORD"],
}

TARGET_TABLES = ["balance_sheet", "income", "cash_flow"]
METHOD_PRIORITY = {"rule": 1}


def normalize_text(value) -> str:
    if value is None:
        return ""
    text = str(value).replace("\u3000", " ").replace("\xa0", " ").strip()
    return text


def normalize_period(period: Optional[str]) -> Optional[str]:
    mapping = {
        "Q1": "Q1",
        "H1": "H1",
        "HY": "H1",
        "Q3": "Q3",
        "ANNUAL": "ANNUAL",
        "FY": "ANNUAL",
    }
    if period is None:
        return None
    return mapping.get(str(period).strip().upper(), str(period).strip().upper())


def parse_value(value_text: str, data_type: str):
    raw = normalize_text(value_text)
    if raw == "":
        return None

    dtype = normalize_text(data_type).lower()
    null_tokens = {"", "-", "--", "---", "—", "——", "不适用", "n/a", "nan", "无"}
    cleaned = raw.replace(",", "").replace("（", "(").replace("）", ")").strip()
    if cleaned.lower() in null_tokens:
        return None

    m = re.match(r"^\((.+)\)$", cleaned)
    if m:
        cleaned = "-" + m.group(1).strip()

    cleaned = cleaned.rstrip("%").strip()

    try:
        if "int" in dtype:
            return int(Decimal(cleaned))
        if "decimal" in dtype or "numeric" in dtype:
            return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return None

    return raw


def fetch_field_defs(conn, target_table: str) -> List[Dict]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT field_code, split_part(field_code, '.', 2) AS field_name, field_name_cn, data_type, sort_order
        FROM attachment3_field_dict
        WHERE target_table = %s
        ORDER BY sort_order, field_code
        """,
        (target_table,),
    )
    rows = cur.fetchall()
    cur.close()
    return [
        {
            "field_code": row[0],
            "field_name": row[1],
            "field_name_cn": row[2],
            "data_type": row[3],
            "sort_order": row[4],
        }
        for row in rows
    ]


def fetch_report_meta(conn, file_ids: Optional[List[int]] = None) -> Dict[int, Dict]:
    params = []
    where_sql = "WHERE COALESCE(parse_status, 'pending') IN ('pending', 'parsed')"
    if file_ids:
        where_sql += " AND file_id = ANY(%s)"
        params.append(file_ids)

    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT file_id, stock_code, stock_abbr, report_year, report_period, file_name
        FROM report_file_index
        {where_sql}
        ORDER BY file_id
        """,
        params,
    )
    rows = cur.fetchall()
    cur.close()
    return {
        row[0]: {
            "file_id": row[0],
            "stock_code": normalize_text(row[1]),
            "stock_abbr": normalize_text(row[2]),
            "report_year": row[3],
            "report_period": normalize_period(row[4]),
            "file_name": normalize_text(row[5]),
        }
        for row in rows
    }


def fetch_chosen_rows(conn, target_table: str, file_ids: Optional[List[int]] = None) -> Dict[Tuple[int, str], Dict]:
    params = [target_table]
    where_sql = "WHERE target_table = %s"
    if file_ids:
        where_sql += " AND file_id = ANY(%s)"
        params.append(file_ids)

    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT file_id, field_code, value_text, extract_method, source_page_range
        FROM attachment3_extract_result
        {where_sql}
          AND COALESCE(value_text, '') <> ''
          AND COALESCE(field_code, '') <> ''
          AND extract_method = ANY(%s)
        ORDER BY file_id, field_code
        """,
        params + [list(METHOD_PRIORITY.keys())],
    )
    rows = cur.fetchall()
    cur.close()

    chosen: Dict[Tuple[int, str], Dict] = {}
    for file_id, field_code, value_text, extract_method, source_page_range in rows:
        key = (file_id, field_code)
        current = {
            "file_id": file_id,
            "field_code": field_code,
            "value_text": value_text,
            "extract_method": extract_method,
            "source_page_range": source_page_range,
        }
        old = chosen.get(key)
        if old is None or METHOD_PRIORITY[extract_method] < METHOD_PRIORITY[old["extract_method"]]:
            chosen[key] = current
    return chosen


def build_candidate_records(target_table: str, field_defs: List[Dict], chosen_rows: Dict[Tuple[int, str], Dict], meta_map: Dict[int, Dict]) -> List[Dict]:
    field_def_map = {f["field_code"]: f for f in field_defs}
    grouped: Dict[Tuple[str, int, str], Dict] = {}

    for (file_id, field_code), row in chosen_rows.items():
        meta = meta_map.get(file_id)
        field_def = field_def_map.get(field_code)
        if not meta or not field_def:
            continue

        stock_code = normalize_text(meta["stock_code"])
        report_year = meta["report_year"]
        report_period = normalize_period(meta["report_period"])
        if not stock_code or report_year is None or not report_period:
            continue

        logical_key = (stock_code, report_year, report_period)
        rec = grouped.setdefault(
            logical_key,
            {
                "stock_code": stock_code,
                "stock_abbr": meta["stock_abbr"],
                "report_year": report_year,
                "report_period": report_period,
                "__source_file_ids": set(),
                "__filled_count": 0,
            },
        )

        value = parse_value(row["value_text"], field_def["data_type"])
        if value is None:
            continue

        fname = field_def["field_name"]
        if rec.get(fname) is None:
            rec[fname] = value
            rec["__filled_count"] += 1

        rec["__source_file_ids"].add(file_id)

    records = []
    for _, rec in sorted(grouped.items(), key=lambda x: (x[0][0], x[0][1], x[0][2])):
        clean = {k: v for k, v in rec.items() if not k.startswith("__")}
        records.append(clean)

    for idx, rec in enumerate(records, start=1):
        rec["serial_number"] = idx

    return records


def upsert_records(conn, target_table: str, field_defs: List[Dict], records: List[Dict]) -> int:
    if not records:
        return 0

    final_columns = [f["field_name"] for f in field_defs]
    insert_columns = final_columns

    values = []
    for rec in records:
        values.append(tuple(rec.get(col) for col in insert_columns))

    update_columns = [col for col in insert_columns if col not in ("stock_code", "report_year", "report_period")]
    query = sql.SQL("""
        INSERT INTO {table} ({columns})
        VALUES %s
        ON CONFLICT (stock_code, report_year, report_period)
        DO UPDATE SET {updates}
    """).format(
        table=sql.Identifier(target_table),
        columns=sql.SQL(", ").join(sql.Identifier(c) for c in insert_columns),
        updates=sql.SQL(", ").join(
            sql.SQL("{col} = EXCLUDED.{col}").format(col=sql.Identifier(c)) for c in update_columns
        ),
    )

    cur = conn.cursor()
    try:
        execute_values(cur, query.as_string(conn), values, page_size=100)
        conn.commit()
        return len(records)
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


def process_target_table(conn, target_table: str, file_ids: Optional[List[int]] = None) -> int:
    field_defs = fetch_field_defs(conn, target_table)
    chosen_rows = fetch_chosen_rows(conn, target_table, file_ids=file_ids)
    meta_map = fetch_report_meta(conn, file_ids=file_ids)
    records = build_candidate_records(target_table, field_defs, chosen_rows, meta_map)
    upsert_count = upsert_records(conn, target_table, field_defs, records)
    print(f"[完成] target_table={target_table} | chosen_fields={len(chosen_rows)} | upsert_rows={upsert_count}")
    return upsert_count


def parse_args():
    parser = argparse.ArgumentParser(description="将 attachment3_extract_result 转换为附件3标准最终表。")
    parser.add_argument("--target-table", nargs="*", choices=TARGET_TABLES, help="仅处理指定目标表")
    parser.add_argument("--file-id", type=int, nargs="*", help="仅处理指定 file_id")
    return parser.parse_args()


def main():
    args = parse_args()
    target_tables = args.target_table or TARGET_TABLES

    conn = psycopg2.connect(**DB_CONFIG)
    try:
        for target_table in target_tables:
            process_target_table(conn, target_table, file_ids=args.file_id)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
