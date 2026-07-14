import argparse
import os
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import psycopg2
from psycopg2 import sql

from key_metrics_config import KEY_METRICS, V1_FILL_RATE_METRIC_TYPES


DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "teddy_b",
    "user": "postgres",
    "password": os.environ["DB_PASSWORD"],
}

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = PROJECT_ROOT / "output" / "pdf_extraction" / "validation"
STATEMENT_JSON_DIR = PROJECT_ROOT / "output" / "pdf_extraction" / "statement_json"

FINAL_TO_SOURCE_TABLE = {
    "balance_sheet": "balance_sheet",
    "income_sheet": "income",
    "cash_flow_sheet": "cash_flow",
}
FINAL_TABLES = list(FINAL_TO_SOURCE_TABLE.keys())
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
SUGGESTED_ACTION_BY_REASON = {
    "no_candidate_found": "add_alias_mapping / improve_row_matching",
    "candidate_exists_but_not_selected": "improve_candidate_selection",
    "selected_but_not_loaded": "inspect_loader_field_whitelist",
    "validation_field_mapping_issue": "inspect_validation_mapping",
    "no_statement_json": "inspect_statement_locator_or_statement_json_generation",
    "unknown": "manual_inspection",
}


LogicalKey = Tuple[int, str, int, str]


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description="分析最终表字段覆盖率和缺失漏斗。")
    parser.add_argument("--run-id", required=True, help="需要分析的 run_id。")
    return parser.parse_args()


def fetch_table_columns(conn, table_name: str) -> List[str]:
    """读取数据库表字段。"""
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


def fetch_field_dict(conn, source_table: str) -> Dict[str, Dict]:
    """读取附件 3 字段字典，并按最终字段名索引。"""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            field_code,
            split_part(field_code, '.', 2) AS final_field_name,
            field_name_cn,
            data_type,
            sort_order
        FROM attachment3_field_dict
        WHERE target_table = %s
        ORDER BY sort_order, field_code
        """,
        (source_table,),
    )
    result = {}
    for field_code, final_field_name, field_name_cn, data_type, sort_order in cur.fetchall():
        if not final_field_name or final_field_name in BASE_COLUMNS:
            continue
        result[final_field_name] = {
            "field_code": field_code,
            "field_name_cn": field_name_cn,
            "data_type": data_type,
            "sort_order": sort_order,
        }
    cur.close()
    if source_table == "balance_sheet":
        result.setdefault(
            "liability_and_equity_total",
            {
                "field_code": "balance_sheet.liability_and_equity_total",
                "field_name_cn": "负债和所有者权益总计",
                "data_type": "decimal",
                "sort_order": 9991,
            },
        )
    return result


def fetch_run_keys(conn, run_id: str, final_table: str) -> List[Dict]:
    """读取本轮 final_table_lineage 覆盖的报表键。"""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT DISTINCT ON (file_id, stock_code, report_year, report_period)
            file_id,
            stock_code,
            report_year,
            report_period
        FROM final_table_lineage
        WHERE run_id = %s AND final_table = %s
        ORDER BY file_id, stock_code, report_year, report_period
        """,
        (run_id, final_table),
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


def logical_key(row: Dict) -> LogicalKey:
    """构造包含 file_id 的逻辑键，避免同公司同期间多文件混淆。"""
    return (int(row["file_id"]), row["stock_code"], int(row["report_year"]), row["report_period"])


def fetch_final_values(conn, table_name: str, keys: List[Dict], fields: List[str], actual_columns: Set[str]) -> Dict[LogicalKey, Dict[str, object]]:
    """读取最终表中本轮键集对应字段值。"""
    if not keys:
        return {}
    selected_fields = [field for field in fields if field in actual_columns]
    if not selected_fields:
        return {logical_key(row): {} for row in keys}

    field_sql = sql.SQL(", ").join(
        sql.SQL("final.{field}").format(field=sql.Identifier(field))
        for field in selected_fields
    )
    query = sql.SQL(
        """
        WITH keys(file_id, stock_code, report_year, report_period) AS (
            VALUES {values}
        )
        SELECT
            keys.file_id,
            keys.stock_code,
            keys.report_year,
            keys.report_period,
            {field_sql}
        FROM keys
        LEFT JOIN {table_name} AS final
          ON final.stock_code = keys.stock_code
         AND final.report_year = keys.report_year
         AND final.report_period = keys.report_period
        """
    ).format(
        values=sql.SQL(", ").join(sql.SQL("(%s, %s, %s, %s)") for _ in keys),
        field_sql=field_sql,
        table_name=sql.Identifier(table_name),
    )
    params = []
    for row in keys:
        params.extend([row["file_id"], row["stock_code"], row["report_year"], row["report_period"]])

    cur = conn.cursor()
    cur.execute(query, params)
    result = {}
    for row in cur.fetchall():
        key = (int(row[0]), row[1], int(row[2]), row[3])
        result[key] = dict(zip(selected_fields, row[4:]))
    cur.close()
    return result


def fetch_lineage_map(conn, run_id: str, final_table: str) -> Dict[str, Set[LogicalKey]]:
    """读取本轮字段级 lineage 覆盖。"""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT file_id, stock_code, report_year, report_period, final_field
        FROM final_table_lineage
        WHERE run_id = %s AND final_table = %s
        """,
        (run_id, final_table),
    )
    result: Dict[str, Set[LogicalKey]] = defaultdict(set)
    for file_id, stock_code, report_year, report_period, final_field in cur.fetchall():
        result[final_field].add((int(file_id), stock_code, int(report_year), report_period))
    cur.close()
    return result


def fetch_candidate_map(conn, source_table: str, field_codes: Dict[str, str], file_ids: List[int]) -> Dict[str, Set[int]]:
    """读取抽取候选覆盖。"""
    result: Dict[str, Set[int]] = defaultdict(set)
    if not field_codes or not file_ids:
        return result
    reverse = {field_code: field for field, field_code in field_codes.items()}
    cur = conn.cursor()
    cur.execute(
        """
        SELECT file_id, field_code
        FROM attachment3_extract_result
        WHERE target_table = %s
          AND field_code = ANY(%s)
          AND file_id = ANY(%s)
          AND COALESCE(value_text, '') <> ''
        """,
        (source_table, list(reverse.keys()), file_ids),
    )
    for file_id, field_code in cur.fetchall():
        field_name = reverse.get(field_code)
        if field_name:
            result[field_name].add(int(file_id))
    cur.close()
    return result


def statement_json_exists(file_id: int, source_table: str) -> bool:
    """判断指定报表 JSON 是否存在。"""
    return (STATEMENT_JSON_DIR / f"file_{file_id}_{source_table}.json").exists()


def is_value_present(value) -> bool:
    """判断最终表字段是否有值。"""
    return value is not None


def choose_suggested_action(reason_distribution: Dict[str, int]) -> str:
    """根据主要缺失原因给出下一步动作。"""
    if not reason_distribution:
        return ""
    top_reason = max(reason_distribution.items(), key=lambda item: (item[1], item[0]))[0]
    return SUGGESTED_ACTION_BY_REASON.get(top_reason, "manual_inspection")


def analyze_table(conn, run_id: str, final_table: str) -> Dict:
    """分析单张最终表的字段覆盖率。"""
    source_table = FINAL_TO_SOURCE_TABLE[final_table]
    keys = fetch_run_keys(conn, run_id, final_table)
    expected_count = len(keys)
    actual_columns = set(fetch_table_columns(conn, final_table))
    field_dict = fetch_field_dict(conn, source_table)
    business_fields = [field for field in fetch_table_columns(conn, final_table) if field not in BASE_COLUMNS]
    metric_config = KEY_METRICS.get(final_table, {})
    key_metric_source_fields = {
        config.get("source_field")
        for config in metric_config.values()
        if config.get("source_field")
    }
    all_fields = sorted(set(business_fields) | set(field_dict.keys()) | key_metric_source_fields)
    field_codes = {
        field: (field_dict.get(field) or {}).get("field_code") or f"{source_table}.{field}"
        for field in all_fields
    }
    final_values = fetch_final_values(conn, final_table, keys, all_fields, actual_columns)
    lineage_map = fetch_lineage_map(conn, run_id, final_table)
    candidate_map = fetch_candidate_map(conn, source_table, field_codes, [row["file_id"] for row in keys])
    statement_json_by_file = {row["file_id"]: statement_json_exists(row["file_id"], source_table) for row in keys}

    fields_report = {}
    table_missing_summary = Counter()
    for field_name in all_fields:
        final_field_exists = field_name in actual_columns
        final_non_null_count = 0
        missing_reasons = Counter()
        for row in keys:
            key = logical_key(row)
            final_value = (final_values.get(key) or {}).get(field_name)
            if is_value_present(final_value):
                final_non_null_count += 1
                continue

            if not final_field_exists:
                reason = "validation_field_mapping_issue"
            elif key in lineage_map.get(field_name, set()):
                reason = "selected_but_not_loaded"
            elif not statement_json_by_file.get(row["file_id"], False):
                reason = "no_statement_json"
            elif row["file_id"] in candidate_map.get(field_name, set()):
                reason = "candidate_exists_but_not_selected"
            else:
                reason = "no_candidate_found"
            missing_reasons[reason] += 1
            table_missing_summary[reason] += 1

        lineage_count = len(lineage_map.get(field_name, set()))
        candidate_count = len(candidate_map.get(field_name, set()))
        missing_count = expected_count - final_non_null_count
        reason_distribution = dict(sorted(missing_reasons.items()))
        fields_report[field_name] = {
            "expected_count": expected_count,
            "final_non_null_count": final_non_null_count,
            "final_fill_rate": round(final_non_null_count / expected_count, 6) if expected_count else 0.0,
            "lineage_count": lineage_count,
            "lineage_coverage": round(lineage_count / final_non_null_count, 6) if final_non_null_count else 0.0,
            "candidate_count": candidate_count,
            "candidate_recall_rate": round(candidate_count / expected_count, 6) if expected_count else 0.0,
            "missing_count": missing_count,
            "missing_reason_distribution": reason_distribution,
            "suggested_next_action": choose_suggested_action(reason_distribution),
            "is_key_metric": any(config.get("source_field") == field_name for config in metric_config.values()),
            "final_field_exists": final_field_exists,
            "field_code": field_codes[field_name],
        }

    return {
        "expected_count": expected_count,
        "fields": fields_report,
        "missing_reason_summary": dict(sorted(table_missing_summary.items())),
    }


def build_low_fill_outputs(table_reports: Dict[str, Dict]) -> Tuple[List[Dict], Dict[str, List[Dict]], Dict[str, int]]:
    """生成低填充率排行和全局缺失原因汇总。"""
    key_rank = []
    low_by_table = {}
    global_missing = Counter()
    for table_name, table_report in table_reports.items():
        table_low = []
        global_missing.update(table_report.get("missing_reason_summary") or {})
        for field_name, field_report in table_report["fields"].items():
            row = {
                "table_name": table_name,
                "field_name": field_name,
                "source_field": field_name,
                "metric_type": "extracted_metric",
                "included_in_v1_fill_rate": True,
                "final_fill_rate": field_report["final_fill_rate"],
                "candidate_recall_rate": field_report["candidate_recall_rate"],
                "missing_count": field_report["missing_count"],
                "top_missing_reason": next(iter(sorted(
                    field_report["missing_reason_distribution"].items(),
                    key=lambda item: (-item[1], item[0]),
                )), ("", 0))[0],
                "suggested_next_action": field_report["suggested_next_action"],
            }
            if field_report["missing_count"] and field_report["final_fill_rate"] < 0.8:
                table_low.append(row)
        for metric_name, metric_config in KEY_METRICS.get(table_name, {}).items():
            source_field = metric_config.get("source_field")
            metric_type = metric_config.get("metric_type", "extracted_metric")
            included = metric_type in V1_FILL_RATE_METRIC_TYPES and bool(source_field)
            if source_field and source_field in table_report["fields"]:
                source_report = table_report["fields"][source_field]
                metric_row = {
                    "table_name": table_name,
                    "field_name": metric_name,
                    "source_field": source_field,
                    "metric_type": metric_type,
                    "included_in_v1_fill_rate": included,
                    "final_fill_rate": source_report["final_fill_rate"],
                    "candidate_recall_rate": source_report["candidate_recall_rate"],
                    "missing_count": source_report["missing_count"],
                    "top_missing_reason": next(iter(sorted(
                        source_report["missing_reason_distribution"].items(),
                        key=lambda item: (-item[1], item[0]),
                    )), ("", 0))[0],
                    "suggested_next_action": source_report["suggested_next_action"],
                }
            else:
                expected_count = table_report.get("expected_count", 0)
                metric_row = {
                    "table_name": table_name,
                    "field_name": metric_name,
                    "source_field": source_field,
                    "metric_type": metric_type,
                    "included_in_v1_fill_rate": False,
                    "final_fill_rate": None,
                    "candidate_recall_rate": None,
                    "missing_count": None,
                    "top_missing_reason": metric_type,
                    "suggested_next_action": "add_final_table_column" if metric_type == "add_column_required" else "remove_from_v1_key_metrics",
                    "expected_count": expected_count,
                }
            key_rank.append(metric_row)
        low_by_table[table_name] = sorted(table_low, key=lambda item: (item["final_fill_rate"], -item["missing_count"], item["field_name"]))
    key_rank = sorted(
        key_rank,
        key=lambda item: (
            item["final_fill_rate"] is None,
            item["final_fill_rate"] if item["final_fill_rate"] is not None else 2,
            -(item["missing_count"] or 0),
            item["table_name"],
            item["field_name"],
        ),
    )
    return key_rank, low_by_table, dict(sorted(global_missing.items()))


def write_key_csv(run_id: str, key_rank: List[Dict]) -> Path:
    """写出关键字段覆盖率 CSV。"""
    output_path = OUTPUT_DIR / f"key_field_coverage_{run_id}.csv"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "table_name",
                "field_name",
                "source_field",
                "metric_type",
                "included_in_v1_fill_rate",
                "final_fill_rate",
                "candidate_recall_rate",
                "missing_count",
                "top_missing_reason",
                "suggested_next_action",
                "expected_count",
            ],
        )
        writer.writeheader()
        writer.writerows(key_rank)
    return output_path


def build_report(conn, run_id: str) -> Dict:
    """生成字段覆盖率报告。"""
    table_reports = {table_name: analyze_table(conn, run_id, table_name) for table_name in FINAL_TABLES}
    key_rank, low_by_table, missing_summary = build_low_fill_outputs(table_reports)
    report = {
        "run_id": run_id,
        "scope": FINAL_TABLES,
        "key_metrics": KEY_METRICS,
        "key_metric_type_summary": dict(
            sorted(
                Counter(
                    config.get("metric_type", "extracted_metric")
                    for metrics in KEY_METRICS.values()
                    for config in metrics.values()
                ).items()
            )
        ),
        "tables": table_reports,
        "key_metric_low_fill_rank": key_rank,
        "low_fill_fields_by_table": low_by_table,
        "missing_reason_summary": missing_summary,
        "suggested_next_action": choose_suggested_action(missing_summary),
    }
    return report


def main() -> int:
    """命令行入口。"""
    args = parse_args()
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        report = build_report(conn, args.run_id)
    finally:
        conn.close()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / f"field_coverage_report_{args.run_id}.json"
    csv_path = write_key_csv(args.run_id, report["key_metric_low_fill_rank"])
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"run_id": args.run_id, "output": str(output_path), "csv_output": str(csv_path)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
