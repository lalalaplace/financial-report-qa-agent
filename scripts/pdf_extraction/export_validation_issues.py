import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Dict, List

import psycopg2

from db_config import get_db_config


DB_CONFIG = get_db_config()

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = PROJECT_ROOT / "output" / "pdf_extraction" / "validation"
ISSUE_STATUSES = ("failed", "warning", "skipped")
CSV_FIELDS = [
    "run_id",
    "file_id",
    "stock_code",
    "stock_code_text",
    "stock_code_excel",
    "company_name",
    "report_year",
    "report_period",
    "validation_type",
    "validation_status",
    "expected_value",
    "actual_value",
    "diff_value",
    "diff_ratio",
    "related_fields",
    "message",
    "suggested_action",
]


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description="导出财务一致性校验问题明细。")
    parser.add_argument("--run-id", required=True, help="需要导出问题的 run_id。")
    return parser.parse_args()


def normalize_json(value) -> str:
    """将 JSONB 值转为 CSV 文本。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def normalize_stock_code(value) -> str:
    """统一股票代码为 6 位文本。"""
    text = "" if value is None else str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    if text.isdigit() and len(text) <= 6:
        return text.zfill(6)
    return text


def build_suggested_action(row: Dict) -> str:
    """根据校验类型和状态生成排查建议。"""
    validation_type = row.get("validation_type")
    validation_status = row.get("validation_status")
    message = row.get("message") or ""

    if validation_status == "failed":
        if validation_type == "balance_sheet_identity":
            return "检查 asset_total_assets、liability_total_liabilities、equity_total_equity 的来源行、单位和列角色；只记录问题，不自动改值。"
        if validation_type == "cash_flow_identity":
            return "检查 net_cash_flow 及三类现金流净额来源，确认是否缺少汇率影响或期间列错配；只记录问题，不自动改值。"
        return "检查相关字段来源与数值清洗过程；只记录问题，不自动改值。"

    if validation_status == "warning":
        if "fx_effect missing" in message:
            return "确认报表是否披露汇率影响字段；当前按 0 处理，必要时补充字段映射后重跑校验。"
        return "检查 warning 信息对应字段，判断是否为字段缺失、口径差异或可接受误差。"

    if validation_status == "skipped":
        if "missing" in message:
            return "优先检查 message 中列出的缺失字段是否未抽取、未入库或字段映射缺失。"
        return "补齐校验所需字段后重跑一致性校验。"

    return ""


def fetch_issue_rows(conn, run_id: str) -> List[Dict]:
    """读取 failed、warning、skipped 校验明细。"""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            run_id,
            file_id,
            stock_code,
            company_name,
            report_year,
            report_period,
            validation_type,
            validation_status,
            expected_value,
            actual_value,
            diff_value,
            diff_ratio,
            related_fields,
            message
        FROM financial_validation_result
        WHERE run_id = %s AND validation_status IN %s
        ORDER BY
            validation_type,
            CASE validation_status
                WHEN 'failed' THEN 1
                WHEN 'warning' THEN 2
                WHEN 'skipped' THEN 3
                ELSE 4
            END,
            stock_code,
            report_year,
            report_period,
            file_id
        """,
        (run_id, ISSUE_STATUSES),
    )
    columns = [item[0] for item in cur.description]
    rows = [dict(zip(columns, row)) for row in cur.fetchall()]
    cur.close()
    return rows


def write_csv(rows: List[Dict], output_path: Path) -> None:
    """写出 CSV 文件。"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            payload = {field: row.get(field) for field in CSV_FIELDS}
            stock_code_text = normalize_stock_code(row.get("stock_code"))
            payload["stock_code_text"] = stock_code_text
            payload["stock_code_excel"] = f'="{stock_code_text}"' if stock_code_text else ""
            payload["related_fields"] = normalize_json(row.get("related_fields"))
            payload["suggested_action"] = build_suggested_action(row)
            writer.writerow(payload)


def main() -> int:
    """命令行入口。"""
    args = parse_args()
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        rows = fetch_issue_rows(conn, args.run_id)
    finally:
        conn.close()

    output_path = OUTPUT_DIR / f"validation_issues_{args.run_id}.csv"
    write_csv(rows, output_path)
    print(json.dumps({"run_id": args.run_id, "issue_count": len(rows), "output": str(output_path)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

