import argparse
import os
import json
import re
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

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = PROJECT_ROOT / "output" / "pdf_extraction" / "validation"
TARGET_FIELDS = [
    "balance_sheet.asset_total_assets",
    "balance_sheet.liability_total_liabilities",
]
PREVIOUS_ROLES = {"previous_period", "beginning_balance", "prior_period"}
CURRENT_ROLES = {"current_period", "ending_balance", "current_amount", "current"}


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description="审计有候选但未进入最终表的关键字段。")
    parser.add_argument("--run-id", required=True, help="需要分析的 run_id。")
    return parser.parse_args()


def parse_extra_info(value) -> Dict:
    """解析 extra_info_json。"""
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def parse_source_text_fields(source_text: Optional[str]) -> Dict[str, str]:
    """从 source_text 中提取 key=value 字段。"""
    result = {}
    if not source_text:
        return result
    for line in str(source_text).splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key and key not in result:
            result[key] = value.strip()
    return result


def normalize_final_field(field_code: str) -> str:
    """从 field_code 得到最终字段名。"""
    return field_code.split(".", 1)[1]


def fetch_run_keys(conn, run_id: str) -> List[Dict]:
    """读取本轮资产负债表样本键。"""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT DISTINCT ON (file_id, stock_code, report_year, report_period)
            file_id,
            stock_code,
            report_year,
            report_period
        FROM final_table_lineage
        WHERE run_id = %s AND final_table = 'balance_sheet'
        ORDER BY file_id, stock_code, report_year, report_period
        """,
        (run_id,),
    )
    rows = [
        {
            "file_id": int(row[0]),
            "stock_code": row[1],
            "report_year": int(row[2]),
            "report_period": row[3],
        }
        for row in cur.fetchall()
    ]
    cur.close()
    return rows


def fetch_final_values(conn, keys: List[Dict]) -> Dict[Tuple[int, str, int, str], Dict[str, object]]:
    """读取目标字段最终值。"""
    if not keys:
        return {}
    values_sql = ",".join(["(%s,%s,%s,%s)"] * len(keys))
    params = []
    for row in keys:
        params.extend([row["file_id"], row["stock_code"], row["report_year"], row["report_period"]])
    cur = conn.cursor()
    cur.execute(
        f"""
        WITH keys(file_id, stock_code, report_year, report_period) AS (
            VALUES {values_sql}
        )
        SELECT
            keys.file_id,
            keys.stock_code,
            keys.report_year,
            keys.report_period,
            final.asset_total_assets,
            final.liability_total_liabilities
        FROM keys
        LEFT JOIN balance_sheet AS final
          ON final.stock_code = keys.stock_code
         AND final.report_year = keys.report_year
         AND final.report_period = keys.report_period
        """,
        params,
    )
    result = {}
    for row in cur.fetchall():
        result[(int(row[0]), row[1], int(row[2]), row[3])] = {
            "asset_total_assets": row[4],
            "liability_total_liabilities": row[5],
        }
    cur.close()
    return result


def fetch_lineage_fields(conn, run_id: str) -> Dict[Tuple[int, str, int, str, str], bool]:
    """读取本轮已有字段 lineage。"""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT file_id, stock_code, report_year, report_period, final_field
        FROM final_table_lineage
        WHERE run_id = %s AND final_table = 'balance_sheet'
          AND final_field IN ('asset_total_assets', 'liability_total_liabilities')
        """,
        (run_id,),
    )
    result = {}
    for file_id, stock_code, report_year, report_period, final_field in cur.fetchall():
        result[(int(file_id), stock_code, int(report_year), report_period, final_field)] = True
    cur.close()
    return result


def fetch_candidates(conn, file_ids: List[int]) -> Dict[Tuple[int, str], List[Dict]]:
    """读取目标字段候选。"""
    result: Dict[Tuple[int, str], List[Dict]] = {}
    if not file_ids:
        return result
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            result_id,
            file_id,
            stock_code,
            report_year,
            report_period,
            field_code,
            value_text,
            raw_line_name,
            normalized_line_name,
            source_column_role,
            source_text,
            confidence,
            extract_method,
            source_page,
            extra_info_json
        FROM attachment3_extract_result
        WHERE target_table = 'balance_sheet'
          AND field_code = ANY(%s)
          AND file_id = ANY(%s)
          AND COALESCE(value_text, '') <> ''
        ORDER BY file_id, field_code, confidence DESC NULLS LAST, result_id
        """,
        (TARGET_FIELDS, file_ids),
    )
    for row in cur.fetchall():
        extra_info = parse_extra_info(row[14])
        source_fields = parse_source_text_fields(row[10])
        field_code = row[5]
        item = {
            "result_id": row[0],
            "file_id": int(row[1]),
            "stock_code": row[2],
            "report_year": int(row[3]),
            "report_period": row[4],
            "target_field": field_code,
            "final_field": normalize_final_field(field_code),
            "raw_row_name": row[7],
            "normalized_row_name": row[8],
            "raw_col_name": source_fields.get("column_label") or extra_info.get("column_label"),
            "col_role": row[9] or source_fields.get("column_role") or extra_info.get("column_role"),
            "value": row[6],
            "confidence": row[11],
            "extract_method": row[12],
            "source_page": row[13],
            "selection_risk_flag": extra_info.get("selection_risk_flag") or extra_info.get("column_role_warning") or "",
            "column_role_warning": extra_info.get("column_role_warning") or "",
            "used_fallback_role": extra_info.get("used_fallback_role"),
            "cell_resolution": extra_info.get("cell_resolution"),
        }
        result.setdefault((int(row[1]), field_code), []).append(item)
    cur.close()
    return result


def infer_rejection_reason(candidates: List[Dict], final_value, has_lineage: bool) -> str:
    """推断候选未进入最终字段的原因。"""
    if final_value is not None:
        return "final_value_present_not_rejected"
    if has_lineage:
        return "selected_but_removed_by_validation"
    roles = {str(item.get("col_role") or "") for item in candidates}
    warnings = {str(item.get("column_role_warning") or "") for item in candidates}
    if roles and roles.issubset(PREVIOUS_ROLES):
        return "previous_period_only_candidate"
    if roles & CURRENT_ROLES and "only_non_target_column_role" in warnings:
        return "current_candidate_with_column_role_warning"
    if roles & CURRENT_ROLES:
        return "current_candidate_not_selected_or_loader_validation_rejected"
    if "only_non_target_column_role" in warnings:
        return "candidate_column_role_unstable"
    return "candidate_not_selected_unknown"


def build_report(conn, run_id: str) -> Dict:
    """生成候选拒绝审计报告。"""
    keys = fetch_run_keys(conn, run_id)
    final_values = fetch_final_values(conn, keys)
    lineage_fields = fetch_lineage_fields(conn, run_id)
    candidate_map = fetch_candidates(conn, [row["file_id"] for row in keys])
    cases = []
    for row in keys:
        key = (row["file_id"], row["stock_code"], row["report_year"], row["report_period"])
        for field_code in TARGET_FIELDS:
            final_field = normalize_final_field(field_code)
            candidates = candidate_map.get((row["file_id"], field_code), [])
            final_value = (final_values.get(key) or {}).get(final_field)
            has_lineage = lineage_fields.get((*key, final_field), False)
            if not candidates or final_value is not None:
                continue
            top_candidates = candidates[:5]
            cases.append(
                {
                    "file_id": row["file_id"],
                    "stock_code": row["stock_code"],
                    "report_year": row["report_year"],
                    "report_period": row["report_period"],
                    "target_field": field_code,
                    "final_field": final_field,
                    "final_value_is_null": final_value is None,
                    "lineage_exists": has_lineage,
                    "candidate_count": len(candidates),
                    "top_candidates": top_candidates,
                    "suspected_rejection_reason": infer_rejection_reason(candidates, final_value, has_lineage),
                }
            )
    reason_counts = {}
    for case in cases:
        reason = case["suspected_rejection_reason"]
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
    return {
        "run_id": run_id,
        "target_fields": TARGET_FIELDS,
        "case_count": len(cases),
        "suspected_rejection_reason_distribution": dict(sorted(reason_counts.items())),
        "cases": cases,
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
    output_path = OUTPUT_DIR / f"candidate_rejection_audit_{args.run_id}.json"
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"run_id": args.run_id, "output": str(output_path), "case_count": report["case_count"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
