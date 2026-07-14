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
    fetch_field_dict,
    find_column,
    find_row,
    parse_table_structure,
    should_skip_statement_field,
    extract_cell,
)
from statement_table_schema import load_normalized_table_json, normalize_text


DB_CONFIG = {"host": "localhost", "port": 5432, "dbname": "teddy_b", "user": "postgres", "password": os.environ["DB_PASSWORD"]}
PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = PROJECT_ROOT / "output" / "pdf_extraction" / "missing_analysis"
AUTO_METHODS = {"rule", "rule_candidate_fill", "manual_backfill"}
STATEMENT_JSON_DIR = PROJECT_ROOT / "output" / "pdf_extraction" / "statement_json"
STATEMENT_TARGET_TABLE_MAP = {"balance_sheet": "balance_sheet", "income": "income", "cash_flow": "cash_flow"}
SKIP_FINAL_FIELD_NAMES = {"serial_number", "stock_code", "stock_abbr", "report_year", "report_period"}


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
    if value is None:
        return ""
    try:
        return str(value)
    except Exception:
        return repr(value)


def safe_print(*args) -> None:
    text = " ".join(safe_text(arg) for arg in args)
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("utf-8", errors="replace").decode("utf-8", errors="replace"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="导出附件3缺失分析报表 CSV。")
    parser.add_argument("--file-id", type=int, nargs="*", help="仅处理指定 file_id，可传多个。")
    parser.add_argument("--statement-type", choices=list(STATEMENT_TARGET_TABLE_MAP.keys()), nargs="*", help="仅处理指定报表类型。")
    parser.add_argument("--target-table", choices=list(STATEMENT_TARGET_TABLE_MAP.values()), nargs="*", help="仅处理指定目标表。")
    parser.add_argument("--limit", type=int, help="最多处理前 N 个 statement_json 文件。")
    return parser.parse_args()


def parse_json_name(file_name: str) -> Optional[Dict]:
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
    return files[:limit] if limit is not None else files


def build_hint(field: Dict, table: Dict, statement_type: str) -> Tuple[str, str]:
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


def ensure_output_dir() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def fetch_report_meta(conn, file_ids: Optional[List[int]] = None) -> Dict[int, Dict]:
    params: List = []
    where_sql = ""
    if file_ids:
        where_sql = "WHERE file_id = ANY(%s)"
        params.append(file_ids)
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT file_id, file_name, stock_code, stock_abbr, report_year, report_period
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
            "file_name": normalize_text(row[1]),
            "stock_code": normalize_text(row[2]),
            "stock_abbr": normalize_text(row[3]),
            "report_year": row[4],
            "report_period": normalize_text(row[5]),
        }
        for row in rows
    }


def fetch_existing_results(conn, file_ids: List[int], target_tables: List[str]) -> Dict[Tuple[int, str, str], List[Dict]]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT file_id, target_table, field_code, extract_method, value_text, confidence
        FROM attachment3_extract_result
        WHERE file_id = ANY(%s)
          AND target_table = ANY(%s)
          AND COALESCE(field_code, '') <> ''
          AND COALESCE(value_text, '') <> ''
        ORDER BY file_id, target_table, field_code, extract_method
        """,
        (file_ids, target_tables),
    )
    rows = cur.fetchall()
    cur.close()
    result_map: Dict[Tuple[int, str, str], List[Dict]] = defaultdict(list)
    for row in rows:
        result_map[(row[0], normalize_text(row[1]), normalize_text(row[2]))].append(
            {
                "extract_method": normalize_text(row[3]),
                "value_text": normalize_text(row[4]),
                "confidence": float(row[5] or 0.0),
            }
        )
    return result_map


def write_csv(path: Path, headers: List[str], rows: List[Dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    configure_console()
    args = parse_args()
    statement_types = args.statement_type
    if args.target_table:
        target_statement_types = {key for key, value in STATEMENT_TARGET_TABLE_MAP.items() if value in set(args.target_table)}
        statement_types = sorted(target_statement_types if statement_types is None else set(statement_types) & target_statement_types)

    json_files = list_statement_json_files(file_ids=args.file_id, statement_types=statement_types, limit=args.limit)
    safe_print(f"待分析 statement_json 数量：{len(json_files)}")
    if not json_files:
        safe_print("当前范围内没有可分析的 statement_json。")
        return 0

    file_ids = sorted({parse_json_name(path.name)["file_id"] for path in json_files if parse_json_name(path.name)})
    target_tables = sorted({STATEMENT_TARGET_TABLE_MAP[parse_json_name(path.name)["statement_type"]] for path in json_files if parse_json_name(path.name)})

    conn = psycopg2.connect(**DB_CONFIG)
    try:
        report_meta_map = fetch_report_meta(conn, file_ids=file_ids)
        existing_result_map = fetch_existing_results(conn, file_ids=file_ids, target_tables=target_tables)
        field_coverage: Dict[Tuple[str, str], Dict] = defaultdict(lambda: {"expected": 0, "hit": 0, "confidence_sum": 0.0})
        file_summary: Dict[Tuple[int, str], Dict] = defaultdict(lambda: {"expected": 0, "hit": 0})
        company_summary: Dict[Tuple[str, int, str], Dict] = defaultdict(lambda: {"total_missing": 0, "balance_sheet_missing": 0, "income_missing": 0, "cash_flow_missing": 0})
        failure_examples: List[Dict] = []

        for json_path in json_files:
            payload = load_normalized_table_json(json_path)
            statement_type = payload.statement_type
            target_table = STATEMENT_TARGET_TABLE_MAP[statement_type]
            report_meta = report_meta_map.get(payload.file_id, {})
            field_dict = fetch_field_dict(conn, target_table)
            table = parse_table_structure(payload)
            company_key = (
                normalize_text(report_meta.get("stock_code", payload.stock_code)),
                report_meta.get("report_year", payload.report_year),
                normalize_text(report_meta.get("report_period", payload.report_period)),
            )

            for field in field_dict:
                field_code = field["field_code"]
                final_field_name = normalize_text(field_code.split(".", 1)[1] if "." in field_code else field_code)
                if should_skip_statement_field(field_code) or final_field_name in SKIP_FINAL_FIELD_NAMES:
                    continue

                key = (payload.file_id, target_table, field_code)
                candidates = existing_result_map.get(key, [])
                auto_rows = [item for item in candidates if item["extract_method"] in AUTO_METHODS]
                best_auto = sorted(
                    auto_rows,
                    key=lambda item: (
                        0 if item["extract_method"] == "manual_backfill" else 1,
                        -float(item.get("confidence") or 0.0),
                    ),
                )[0] if auto_rows else None

                field_key = (target_table, field_code)
                field_coverage[field_key]["expected"] += 1
                file_summary[(payload.file_id, statement_type)]["expected"] += 1

                if best_auto:
                    field_coverage[field_key]["hit"] += 1
                    field_coverage[field_key]["confidence_sum"] += float(best_auto.get("confidence") or 0.0)
                    file_summary[(payload.file_id, statement_type)]["hit"] += 1
                    continue

                company_summary[company_key]["total_missing"] += 1
                company_summary[company_key][f"{statement_type}_missing"] += 1
                row_matches = find_row(field.get("aliases", []), table)
                best_row = row_matches[0] if row_matches else None
                page_hint, text_hint = build_hint(field, table, statement_type)
                failure_examples.append(
                    {
                        "file_id": payload.file_id,
                        "file_name": report_meta.get("file_name", ""),
                        "stock_code": company_key[0],
                        "report_year": company_key[1],
                        "report_period": company_key[2],
                        "statement_type": statement_type,
                        "target_table": target_table,
                        "field_code": field_code,
                        "field_name_cn": field["field_name_cn"],
                        "source_page_hint": page_hint,
                        "best_row_alias": normalize_text(best_row.get("alias")) if best_row else "",
                        "best_row_score": round(float(best_row.get("score") or 0.0), 4) if best_row else 0.0,
                        "parse_confidence": payload.parser_meta.get("parse_confidence"),
                        "locator_confidence": payload.locator_confidence,
                        "source_text_hint": text_hint,
                    }
                )
    finally:
        conn.close()

    ensure_output_dir()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    field_rows = []
    for (target_table, field_code), stats in sorted(field_coverage.items()):
        expected = stats["expected"]
        hit = stats["hit"]
        coverage_rate = round(hit / expected, 4) if expected else 0.0
        avg_confidence = round(stats["confidence_sum"] / hit, 4) if hit else 0.0
        field_rows.append(
            {
                "target_table": target_table,
                "field_code": field_code,
                "expected_file_count": expected,
                "hit_file_count": hit,
                "missing_file_count": expected - hit,
                "coverage_rate": coverage_rate,
                "avg_confidence": avg_confidence,
            }
        )

    file_rows = []
    for (file_id, statement_type), stats in sorted(file_summary.items()):
        expected = stats["expected"]
        hit = stats["hit"]
        file_rows.append(
            {
                "file_id": file_id,
                "statement_type": statement_type,
                "expected_field_count": expected,
                "hit_field_count": hit,
                "missing_field_count": expected - hit,
                "coverage_rate": round(hit / expected, 4) if expected else 0.0,
            }
        )

    company_rows = []
    for (stock_code, report_year, report_period), stats in sorted(company_summary.items()):
        company_rows.append(
            {
                "stock_code": stock_code,
                "report_year": report_year,
                "report_period": report_period,
                "total_missing": stats["total_missing"],
                "balance_sheet_missing": stats["balance_sheet_missing"],
                "income_missing": stats["income_missing"],
                "cash_flow_missing": stats["cash_flow_missing"],
            }
        )

    write_csv(
        OUTPUT_DIR / f"field_coverage_summary_{timestamp}.csv",
        ["target_table", "field_code", "expected_file_count", "hit_file_count", "missing_file_count", "coverage_rate", "avg_confidence"],
        field_rows,
    )
    write_csv(
        OUTPUT_DIR / f"file_missing_summary_{timestamp}.csv",
        ["file_id", "statement_type", "expected_field_count", "hit_field_count", "missing_field_count", "coverage_rate"],
        file_rows,
    )
    write_csv(
        OUTPUT_DIR / f"company_missing_summary_{timestamp}.csv",
        ["stock_code", "report_year", "report_period", "total_missing", "balance_sheet_missing", "income_missing", "cash_flow_missing"],
        company_rows,
    )
    write_csv(
        OUTPUT_DIR / f"field_failure_examples_{timestamp}.csv",
        ["file_id", "file_name", "stock_code", "report_year", "report_period", "statement_type", "target_table", "field_code", "field_name_cn", "source_page_hint", "best_row_alias", "best_row_score", "parse_confidence", "locator_confidence", "source_text_hint"],
        failure_examples,
    )

    safe_print(f"字段覆盖统计行数：{len(field_rows)}")
    safe_print(f"文件缺失统计行数：{len(file_rows)}")
    safe_print(f"公司缺失统计行数：{len(company_rows)}")
    safe_print(f"失败样本明细行数：{len(failure_examples)}")
    safe_print(f"已导出缺失分析目录：{OUTPUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
