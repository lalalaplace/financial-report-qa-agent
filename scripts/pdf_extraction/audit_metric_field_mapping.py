import argparse
import difflib
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

import psycopg2

from db_config import get_db_config

from key_metrics_config import KEY_METRICS


DB_CONFIG = get_db_config()

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = PROJECT_ROOT / "output" / "pdf_extraction" / "validation"

def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description="审计 key_metrics 与最终表字段映射。")
    parser.add_argument("--run-id", required=True, help="用于输出文件命名的 run_id。")
    return parser.parse_args()


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


def field_similarity(left: str, right: str) -> float:
    """计算字段名相似度。"""
    left_parts = set(left.split("_"))
    right_parts = set(right.split("_"))
    token_score = len(left_parts & right_parts) / max(len(left_parts | right_parts), 1)
    sequence_score = difflib.SequenceMatcher(None, left, right).ratio()
    return max(token_score, sequence_score)


def find_possible_existing_field(field_name: str, columns: List[str]) -> Optional[Dict]:
    """在同表中查找可能对应的既有字段。"""
    candidates = []
    for column in columns:
        score = field_similarity(field_name, column)
        if score >= 0.45:
            candidates.append({"field_name": column, "similarity": round(score, 6)})
    if not candidates:
        return None
    candidates.sort(key=lambda item: (-item["similarity"], item["field_name"]))
    return candidates[0]


def suggest_action(metric_type: str, possible_existing_field: Optional[Dict]) -> str:
    """根据字段缺失类型给出建议动作。"""
    if metric_type == "not_supported_in_v1":
        return "remove_from_v1_key_metrics"
    if metric_type == "add_column_required":
        return "add_final_table_column"
    if metric_type == "derived_metric":
        return "mark_as_derived_metric"
    if possible_existing_field and possible_existing_field["similarity"] >= 0.55:
        return "map_to_existing_field"
    return "add_final_table_column"


def build_report(conn, run_id: str) -> Dict:
    """生成字段映射审计报告。"""
    tables = {}
    missing_fields = []
    for table_name, key_fields in KEY_METRICS.items():
        columns = fetch_table_columns(conn, table_name)
        column_set = set(columns)
        field_rows = []
        for field_name, metric_config in key_fields.items():
            source_field = metric_config.get("source_field")
            metric_type = metric_config.get("metric_type", "extracted_metric")
            checked_field = source_field or field_name
            exists = bool(source_field and source_field in column_set)
            possible = None if exists or not source_field else find_possible_existing_field(source_field, columns)
            action = "" if exists else suggest_action(metric_type, possible)
            row = {
                "table_name": table_name,
                "field_name": field_name,
                "source_field": source_field,
                "checked_field": checked_field,
                "metric_type": metric_type,
                "final_field_exists": exists,
                "possible_existing_field": possible,
                "suggested_action": action,
            }
            field_rows.append(row)
            if not exists:
                missing_fields.append(row)
        tables[table_name] = {
            "actual_columns": columns,
            "key_metrics": field_rows,
        }
    return {
        "run_id": run_id,
        "tables": tables,
        "missing_key_metrics": missing_fields,
        "missing_key_metric_count": len(missing_fields),
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
    output_path = OUTPUT_DIR / f"metric_field_mapping_audit_{args.run_id}.json"
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"run_id": args.run_id, "output": str(output_path), "missing_key_metric_count": report["missing_key_metric_count"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

