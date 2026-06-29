import argparse
import csv
import json
from pathlib import Path
from typing import Any, Dict, Iterable

import psycopg2

from db_config import get_db_config


DB_CONFIG = get_db_config()

PROJECT_ROOT = Path(__file__).resolve().parents[2]
VALIDATION_DIR = PROJECT_ROOT / "output" / "pdf_extraction" / "validation"
VALIDATION_TYPES = ("balance_sheet_identity", "cash_flow_identity")
VALIDATION_STATUSES = ("passed", "warning", "failed", "skipped")
STABLE_FINAL_TABLES = ("balance_sheet", "income_sheet", "cash_flow_sheet")


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description="对比两轮财务校验结果。")
    parser.add_argument("--old-run-id", required=True, help="旧 run_id。")
    parser.add_argument("--new-run-id", required=True, help="新 run_id。")
    return parser.parse_args()


def load_json(path: Path) -> Dict[str, Any]:
    """读取 JSON 文件。"""
    if not path.exists():
        raise FileNotFoundError(f"缺少报告文件：{path}")
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def count_csv_rows(path: Path) -> int:
    """统计 CSV 数据行数量。"""
    if not path.exists():
        raise FileNotFoundError(f"缺少问题导出文件：{path}")
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return sum(1 for _ in csv.DictReader(f))


def normalize_status_counts(value: Dict[str, Any]) -> Dict[str, int]:
    """补齐状态计数字段，便于跨 run 对比。"""
    return {status: int(value.get(status) or 0) for status in VALIDATION_STATUSES}


def subtract_dict(new_value: Dict[str, Any], old_value: Dict[str, Any]) -> Dict[str, Any]:
    """计算两个字典的数值差异。"""
    keys = sorted(set(old_value) | set(new_value))
    diff: Dict[str, Any] = {}
    for key in keys:
        old_item = old_value.get(key, 0)
        new_item = new_value.get(key, 0)
        if isinstance(old_item, dict) or isinstance(new_item, dict):
            diff[key] = subtract_dict(
                new_item if isinstance(new_item, dict) else {},
                old_item if isinstance(old_item, dict) else {},
            )
        else:
            diff[key] = new_item - old_item
    return diff


def merge_numeric_dicts(items: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    """合并多个分布字典。"""
    merged: Dict[str, int] = {}
    for item in items:
        for key, value in item.items():
            merged[key] = merged.get(key, 0) + int(value or 0)
    return merged


def extract_quality_metrics(report: Dict[str, Any]) -> Dict[str, Any]:
    """提取最终表质量指标。"""
    tables = report.get("tables") or {}
    coverage_by_table: Dict[str, Any] = {}
    lineage_count_by_table: Dict[str, int] = {}
    extract_method_by_table: Dict[str, Dict[str, int]] = {}

    for table in STABLE_FINAL_TABLES:
        table_report = tables.get(table) or {}
        coverage_by_table[table] = table_report.get("lineage_coverage")
        lineage_count_by_table[table] = int(table_report.get("lineage_count") or 0)
        extract_method_by_table[table] = {
            key: int(value or 0)
            for key, value in (table_report.get("extract_method_distribution") or {}).items()
        }

    return {
        "lineage_coverage_by_table": coverage_by_table,
        "lineage_count_by_table": lineage_count_by_table,
        "lineage_count_total": sum(lineage_count_by_table.values()),
        "extract_method_by_table": extract_method_by_table,
        "extract_method_total": merge_numeric_dicts(extract_method_by_table.values()),
    }


def extract_validation_metrics(report: Dict[str, Any]) -> Dict[str, Any]:
    """提取一致性校验指标。"""
    by_type = ((report.get("summary") or {}).get("by_validation_type") or {})
    validation_counts: Dict[str, Dict[str, int]] = {}
    for validation_type in VALIDATION_TYPES:
        validation_counts[validation_type] = normalize_status_counts(by_type.get(validation_type) or {})

    return {
        "validation_counts": validation_counts,
        "skipped_reason_distribution": (
            (report.get("summary") or {}).get("skipped_reason_distribution") or {}
        ),
    }


def fetch_field_lineage_count(run_id: str, final_table: str, final_field: str) -> int:
    """从 lineage 表补充字段级非空 lineage 数量。"""
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT COUNT(*)
            FROM final_table_lineage
            WHERE run_id = %s
              AND final_table = %s
              AND final_field = %s
              AND final_value IS NOT NULL
            """,
            (run_id, final_table, final_field),
        )
        return int(cur.fetchone()[0] or 0)
    finally:
        conn.close()


def build_run_metrics(run_id: str) -> Dict[str, Any]:
    """读取单个 run 的报告并汇总指标。"""
    quality_report = load_json(VALIDATION_DIR / f"final_table_quality_report_{run_id}.json")
    consistency_report = load_json(VALIDATION_DIR / f"financial_consistency_report_{run_id}.json")
    issue_count = count_csv_rows(VALIDATION_DIR / f"validation_issues_{run_id}.csv")

    quality_metrics = extract_quality_metrics(quality_report)
    validation_metrics = extract_validation_metrics(consistency_report)
    liability_and_equity_count = fetch_field_lineage_count(
        run_id,
        "balance_sheet",
        "liability_and_equity_total",
    )

    return {
        "run_id": run_id,
        **quality_metrics,
        **validation_metrics,
        "validation_issues_count": issue_count,
        "liability_and_equity_total_lineage_non_null_count": liability_and_equity_count,
    }


def build_comparison(old_run_id: str, new_run_id: str) -> Dict[str, Any]:
    """生成两轮 run 对比结果。"""
    old_metrics = build_run_metrics(old_run_id)
    new_metrics = build_run_metrics(new_run_id)

    return {
        "old_run_id": old_run_id,
        "new_run_id": new_run_id,
        "old": old_metrics,
        "new": new_metrics,
        "delta": {
            "validation_counts": subtract_dict(
                new_metrics["validation_counts"],
                old_metrics["validation_counts"],
            ),
            "validation_issues_count": (
                new_metrics["validation_issues_count"] - old_metrics["validation_issues_count"]
            ),
            "lineage_count_by_table": subtract_dict(
                new_metrics["lineage_count_by_table"],
                old_metrics["lineage_count_by_table"],
            ),
            "lineage_count_total": (
                new_metrics["lineage_count_total"] - old_metrics["lineage_count_total"]
            ),
            "lineage_coverage_by_table": {
                table: (
                    None
                    if old_metrics["lineage_coverage_by_table"].get(table) is None
                    or new_metrics["lineage_coverage_by_table"].get(table) is None
                    else new_metrics["lineage_coverage_by_table"][table]
                    - old_metrics["lineage_coverage_by_table"][table]
                )
                for table in STABLE_FINAL_TABLES
            },
            "liability_and_equity_total_lineage_non_null_count": (
                new_metrics["liability_and_equity_total_lineage_non_null_count"]
                - old_metrics["liability_and_equity_total_lineage_non_null_count"]
            ),
            "extract_method_total": subtract_dict(
                new_metrics["extract_method_total"],
                old_metrics["extract_method_total"],
            ),
            "extract_method_by_table": subtract_dict(
                new_metrics["extract_method_by_table"],
                old_metrics["extract_method_by_table"],
            ),
            "skipped_reason_distribution": subtract_dict(
                new_metrics["skipped_reason_distribution"],
                old_metrics["skipped_reason_distribution"],
            ),
        },
    }


def main() -> None:
    args = parse_args()
    comparison = build_comparison(args.old_run_id, args.new_run_id)

    VALIDATION_DIR.mkdir(parents=True, exist_ok=True)
    output_path = (
        VALIDATION_DIR
        / f"validation_compare_{args.old_run_id}_vs_{args.new_run_id}.json"
    )
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(comparison, f, ensure_ascii=False, indent=2)

    print(json.dumps({"output": str(output_path), **comparison["delta"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

