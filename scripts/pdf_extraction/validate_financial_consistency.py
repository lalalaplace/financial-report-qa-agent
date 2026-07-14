import argparse
import os
import json
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, List, Optional

import psycopg2
from psycopg2.extras import execute_values


DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "teddy_b",
    "user": "postgres",
    "password": os.environ["DB_PASSWORD"],
}

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = PROJECT_ROOT / "output" / "pdf_extraction" / "validation"
STATUS_VALUES = ["passed", "warning", "failed", "skipped"]
REQUIRED_CASH_FLOW_FIELDS = [
    "net_cash_flow",
    "operating_cf_net_amount",
    "investing_cf_net_amount",
    "financing_cf_net_amount",
]
OPTIONAL_EXCHANGE_RATE_FIELDS = [
    "exchange_rate_effect",
    "effect_of_exchange_rate_changes",
    "effect_of_exchange_rate_changes_on_cash",
    "effect_of_fx_rate_changes_on_cash",
]
LIABILITY_AND_EQUITY_TOTAL_FIELDS = [
    "liability_and_equity_total",
    "liabilities_and_equity_total",
    "total_liabilities_and_equity",
    "total_liabilities_and_owner_equity",
]


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description="校验最终表财务一致性。")
    parser.add_argument("--run-id", required=True, help="需要校验的 run_id。")
    return parser.parse_args()


def to_decimal(value) -> Optional[Decimal]:
    """转为 Decimal，空值返回 None。"""
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def decimal_to_float(value: Optional[Decimal]) -> Optional[float]:
    """将 Decimal 转为 JSON 友好的 float。"""
    if value is None:
        return None
    return float(value)


def parse_json_object(value) -> Dict:
    """解析 JSON 对象，无法解析时返回空字典。"""
    if isinstance(value, dict):
        return value
    if value is None:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def parse_extra_info(diagnostic: Dict) -> Dict:
    """读取 lineage 里保留的抽取 extra_info。"""
    return parse_json_object((diagnostic or {}).get("extract_extra_info_json"))


def extract_lineage_scope(diagnostic) -> Dict:
    """提取校验口径需要的 lineage 字段。"""
    diagnostic_json = parse_json_object(diagnostic)
    extra_info = parse_extra_info(diagnostic_json)
    return {
        "table_id": diagnostic_json.get("table_id") or extra_info.get("table_id"),
        "is_consolidated": diagnostic_json.get("is_consolidated"),
        "is_parent_company": diagnostic_json.get("is_parent_only"),
        "col_role": diagnostic_json.get("selection_period_role") or diagnostic_json.get("source_column_role") or extra_info.get("column_role"),
    }


def values_conflict(left, right) -> bool:
    """只在两边都有值且不相等时认为冲突。"""
    if left is None or right is None or left == "" or right == "":
        return False
    return left != right


def lineage_scope_compatible(left: Dict, right: Dict) -> bool:
    """判断两个字段来源口径是否一致或不冲突。"""
    for key in ("table_id", "is_consolidated", "is_parent_company", "col_role"):
        if values_conflict(left.get(key), right.get(key)):
            return False
    return True


def identity_passes(actual_value: Optional[Decimal], expected_value: Optional[Decimal]) -> bool:
    """判断恒等式差异率是否在 1% 内。"""
    if actual_value is None or expected_value is None:
        return False
    diff_ratio = calculate_diff_ratio(actual_value - expected_value, expected_value, actual_value)
    return diff_ratio is not None and diff_ratio <= 0.01


def calculate_diff_ratio(diff_value: Optional[Decimal], expected_value: Optional[Decimal], actual_value: Optional[Decimal]) -> Optional[float]:
    """计算相对差异率。"""
    if diff_value is None:
        return None
    denominator_candidates = [abs(value) for value in (expected_value, actual_value) if value is not None and value != 0]
    if not denominator_candidates:
        return 0.0 if diff_value == 0 else None
    denominator = max(denominator_candidates)
    return float(abs(diff_value) / denominator)


def decide_status(diff_ratio: Optional[float], optional_warning: bool = False) -> str:
    """根据差异率判断状态。"""
    if diff_ratio is None:
        return "warning"
    if diff_ratio <= 0.01:
        return "warning" if optional_warning else "passed"
    return "failed"


def ensure_schema(conn) -> None:
    """确保财务校验结果表存在。"""
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS financial_validation_result (
            id BIGSERIAL PRIMARY KEY,
            run_id TEXT NOT NULL,
            file_id BIGINT,
            stock_code VARCHAR(32),
            company_name VARCHAR(255),
            report_year INTEGER,
            report_period VARCHAR(32),
            validation_type VARCHAR(128) NOT NULL,
            validation_status VARCHAR(32) NOT NULL,
            expected_value NUMERIC(28, 6),
            actual_value NUMERIC(28, 6),
            diff_value NUMERIC(28, 6),
            diff_ratio DOUBLE PRECISION,
            related_fields JSONB,
            message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_financial_validation_result_run
        ON financial_validation_result (run_id, validation_type, validation_status)
        """
    )
    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_financial_validation_result_lookup
        ON financial_validation_result (stock_code, report_year, report_period)
        """
    )
    conn.commit()
    cur.close()


def fetch_table_columns(conn, table_name: str) -> List[str]:
    """读取表字段。"""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s
        """,
        (table_name,),
    )
    columns = [row[0] for row in cur.fetchall()]
    cur.close()
    return columns


def fetch_balance_rows(conn, run_id: str) -> List[Dict]:
    """读取本轮 lineage 涉及的资产负债表记录。"""
    columns = fetch_table_columns(conn, "balance_sheet")
    liability_and_equity_field = next((field for field in LIABILITY_AND_EQUITY_TOTAL_FIELDS if field in columns), None)
    liability_and_equity_select = f"final.{liability_and_equity_field}" if liability_and_equity_field else "NULL"
    cur = conn.cursor()
    cur.execute(
        f"""
        WITH lineage_keys AS (
            SELECT DISTINCT ON (stock_code, report_year, report_period)
                file_id,
                stock_code,
                company_name,
                report_year,
                report_period
            FROM final_table_lineage
            WHERE run_id = %s AND final_table = 'balance_sheet'
            ORDER BY stock_code, report_year, report_period, file_id
        ),
        balance_lineage AS (
            SELECT
                stock_code,
                report_year,
                report_period,
                final_field,
                diagnostic_json
            FROM final_table_lineage
            WHERE run_id = %s AND final_table = 'balance_sheet'
        )
        SELECT
            keys.file_id,
            keys.stock_code,
            COALESCE(final.company_name, keys.company_name) AS company_name,
            keys.report_year,
            keys.report_period,
            final.asset_total_assets,
            final.liability_total_liabilities,
            final.equity_total_equity,
            {liability_and_equity_select} AS liability_and_equity_total,
            %s AS liability_and_equity_field_name,
            asset_lineage.diagnostic_json AS asset_total_assets_diagnostic,
            liability_lineage.diagnostic_json AS liability_total_liabilities_diagnostic,
            equity_lineage.diagnostic_json AS equity_total_equity_diagnostic,
            liability_and_equity_lineage.diagnostic_json AS liability_and_equity_total_diagnostic
        FROM lineage_keys AS keys
        INNER JOIN balance_sheet AS final
            ON final.stock_code = keys.stock_code
           AND final.report_year = keys.report_year
           AND final.report_period = keys.report_period
        LEFT JOIN balance_lineage AS asset_lineage
            ON asset_lineage.stock_code = keys.stock_code
           AND asset_lineage.report_year = keys.report_year
           AND asset_lineage.report_period = keys.report_period
           AND asset_lineage.final_field = 'asset_total_assets'
        LEFT JOIN balance_lineage AS liability_lineage
            ON liability_lineage.stock_code = keys.stock_code
           AND liability_lineage.report_year = keys.report_year
           AND liability_lineage.report_period = keys.report_period
           AND liability_lineage.final_field = 'liability_total_liabilities'
        LEFT JOIN balance_lineage AS equity_lineage
            ON equity_lineage.stock_code = keys.stock_code
           AND equity_lineage.report_year = keys.report_year
           AND equity_lineage.report_period = keys.report_period
           AND equity_lineage.final_field = 'equity_total_equity'
        LEFT JOIN balance_lineage AS liability_and_equity_lineage
            ON liability_and_equity_lineage.stock_code = keys.stock_code
           AND liability_and_equity_lineage.report_year = keys.report_year
           AND liability_and_equity_lineage.report_period = keys.report_period
           AND liability_and_equity_lineage.final_field = %s
        ORDER BY keys.stock_code, keys.report_year, keys.report_period
        """,
        (run_id, run_id, liability_and_equity_field, liability_and_equity_field),
    )
    columns = [item[0] for item in cur.description]
    rows = [dict(zip(columns, row)) for row in cur.fetchall()]
    cur.close()
    return rows


def fetch_cash_flow_rows(conn, run_id: str) -> List[Dict]:
    """读取本轮 lineage 涉及的现金流量表记录。"""
    columns = fetch_table_columns(conn, "cash_flow_sheet")
    exchange_field = next((field for field in OPTIONAL_EXCHANGE_RATE_FIELDS if field in columns), None)
    exchange_select = f"final.{exchange_field}" if exchange_field else "NULL"
    cur = conn.cursor()
    cur.execute(
        f"""
        WITH lineage_keys AS (
            SELECT DISTINCT ON (stock_code, report_year, report_period)
                file_id,
                stock_code,
                company_name,
                report_year,
                report_period
            FROM final_table_lineage
            WHERE run_id = %s AND final_table = 'cash_flow_sheet'
            ORDER BY stock_code, report_year, report_period, file_id
        )
        SELECT
            keys.file_id,
            keys.stock_code,
            COALESCE(final.company_name, keys.company_name) AS company_name,
            keys.report_year,
            keys.report_period,
            final.net_cash_flow,
            final.operating_cf_net_amount,
            final.investing_cf_net_amount,
            final.financing_cf_net_amount,
            {exchange_select} AS exchange_rate_effect,
            %s AS exchange_field_name
        FROM lineage_keys AS keys
        INNER JOIN cash_flow_sheet AS final
            ON final.stock_code = keys.stock_code
           AND final.report_year = keys.report_year
           AND final.report_period = keys.report_period
        ORDER BY keys.stock_code, keys.report_year, keys.report_period
        """,
        (run_id, exchange_field),
    )
    result_columns = [item[0] for item in cur.description]
    rows = [dict(zip(result_columns, row)) for row in cur.fetchall()]
    cur.close()
    return rows


def build_result(
    run_id: str,
    row: Dict,
    validation_type: str,
    validation_status: str,
    expected_value: Optional[Decimal],
    actual_value: Optional[Decimal],
    related_fields: Dict,
    message: str,
) -> Dict:
    """构造单条校验结果。"""
    diff_value = None if expected_value is None or actual_value is None else actual_value - expected_value
    diff_ratio = calculate_diff_ratio(diff_value, expected_value, actual_value)
    return {
        "run_id": run_id,
        "file_id": row.get("file_id"),
        "stock_code": row.get("stock_code"),
        "company_name": row.get("company_name"),
        "report_year": row.get("report_year"),
        "report_period": row.get("report_period"),
        "validation_type": validation_type,
        "validation_status": validation_status,
        "expected_value": decimal_to_float(expected_value),
        "actual_value": decimal_to_float(actual_value),
        "diff_value": decimal_to_float(diff_value),
        "diff_ratio": diff_ratio,
        "related_fields": related_fields,
        "message": message,
    }


def validate_balance_sheet_identity(run_id: str, rows: List[Dict]) -> List[Dict]:
    """校验资产总计与负债加权益的一致性。"""
    results = []
    for row in rows:
        asset_total = to_decimal(row.get("asset_total_assets"))
        liability_total = to_decimal(row.get("liability_total_liabilities"))
        equity_total = to_decimal(row.get("equity_total_equity"))
        liability_and_equity_total = to_decimal(row.get("liability_and_equity_total"))
        liability_and_equity_field_name = row.get("liability_and_equity_field_name")
        related_fields = {
            "asset_total_assets": decimal_to_float(asset_total),
            "liability_total_liabilities": decimal_to_float(liability_total),
            "equity_total_equity": decimal_to_float(equity_total),
            "liability_and_equity_total": decimal_to_float(liability_and_equity_total),
            "liability_and_equity_field_name": liability_and_equity_field_name,
        }
        asset_scope = extract_lineage_scope(row.get("asset_total_assets_diagnostic"))
        liability_scope = extract_lineage_scope(row.get("liability_total_liabilities_diagnostic"))
        equity_scope = extract_lineage_scope(row.get("equity_total_equity_diagnostic"))
        liability_and_equity_scope = extract_lineage_scope(row.get("liability_and_equity_total_diagnostic"))
        combined_scope_compatible = lineage_scope_compatible(asset_scope, liability_and_equity_scope)
        split_scope_compatible = lineage_scope_compatible(asset_scope, liability_scope) and lineage_scope_compatible(asset_scope, equity_scope)
        related_fields.update(
            {
                "asset_total_assets_scope": asset_scope,
                "liability_total_liabilities_scope": liability_scope,
                "equity_total_equity_scope": equity_scope,
                "liability_and_equity_total_scope": liability_and_equity_scope,
                "liability_and_equity_scope_compatible": combined_scope_compatible,
                "split_fields_scope_compatible": split_scope_compatible,
            }
        )
        missing_fields = []
        if asset_total is None:
            missing_fields.append("missing asset_total_assets")

        can_use_split_fields = liability_total is not None and equity_total is not None
        can_use_combined_field = liability_and_equity_total is not None
        if not can_use_split_fields and not can_use_combined_field:
            if liability_total is None:
                missing_fields.append("missing liability_total_liabilities")
            if equity_total is None:
                missing_fields.append("missing equity_total_equity")
            missing_fields.append("missing liability_and_equity_total")

        if asset_total is None or (not can_use_split_fields and not can_use_combined_field):
            related_fields["identity_check_mode"] = None
            results.append(
                build_result(
                    run_id,
                    row,
                    "balance_sheet_identity",
                    "skipped",
                    None,
                    asset_total,
                    related_fields,
                    f"资产负债表恒等式字段不完整，{'; '.join(missing_fields)}，跳过校验。",
                )
            )
            continue

        split_expected_value = liability_total + equity_total if can_use_split_fields else None
        combined_identity_passes = identity_passes(asset_total, liability_and_equity_total)
        split_identity_passes = identity_passes(asset_total, split_expected_value)
        should_fallback_due_to_scope = (
            can_use_combined_field
            and can_use_split_fields
            and split_scope_compatible
            and split_identity_passes
            and (not combined_scope_compatible or not combined_identity_passes)
        )

        if should_fallback_due_to_scope:
            expected_value = split_expected_value
            identity_check_mode = "fallback_due_to_scope_mismatch"
            message = "负债和所有者权益总计与资产总计来源口径不一致，拆分项与资产总计自洽，改用负债合计加所有者权益合计校验。identity_check_mode=fallback_due_to_scope_mismatch"
        elif can_use_combined_field:
            expected_value = liability_and_equity_total
            identity_check_mode = "asset_vs_liability_and_equity_total"
            message = "资产总计优先与负债和所有者权益总计校验，差异率在 1% 内为通过。identity_check_mode=asset_vs_liability_and_equity_total"
        else:
            expected_value = split_expected_value
            identity_check_mode = "asset_vs_liability_plus_equity"
            message = "负债和所有者权益总计缺失，资产总计与负债合计加所有者权益合计校验，差异率在 1% 内为通过。identity_check_mode=asset_vs_liability_plus_equity"
        related_fields["identity_check_mode"] = identity_check_mode
        diff_value = asset_total - expected_value
        diff_ratio = calculate_diff_ratio(diff_value, expected_value, asset_total)
        status = decide_status(diff_ratio)
        results.append(
            build_result(
                run_id,
                row,
                "balance_sheet_identity",
                status,
                expected_value,
                asset_total,
                related_fields,
                message,
            )
        )
    return results


def validate_cash_flow_identity(run_id: str, rows: List[Dict]) -> List[Dict]:
    """校验现金流量净增加额与三类现金流净额的一致性。"""
    results = []
    for row in rows:
        values = {field: to_decimal(row.get(field)) for field in REQUIRED_CASH_FLOW_FIELDS}
        exchange_value = to_decimal(row.get("exchange_rate_effect"))
        exchange_field_name = row.get("exchange_field_name")
        related_fields = {field: decimal_to_float(value) for field, value in values.items()}
        related_fields["exchange_rate_effect"] = decimal_to_float(exchange_value)
        related_fields["exchange_field_name"] = exchange_field_name

        missing_fields = [field for field, value in values.items() if value is None]
        if missing_fields:
            results.append(
                build_result(
                    run_id,
                    row,
                    "cash_flow_identity",
                    "skipped",
                    None,
                    values.get("net_cash_flow"),
                    related_fields,
                    f"现金流字段不完整，missing {', '.join(missing_fields)}，跳过校验。",
                )
            )
            continue

        optional_warning = exchange_field_name is None
        effective_exchange = exchange_value or Decimal("0")
        expected_value = (
            values["operating_cf_net_amount"]
            + values["investing_cf_net_amount"]
            + values["financing_cf_net_amount"]
            + effective_exchange
        )
        actual_value = values["net_cash_flow"]
        diff_value = actual_value - expected_value
        diff_ratio = calculate_diff_ratio(diff_value, expected_value, actual_value)
        status = decide_status(diff_ratio, optional_warning=optional_warning)
        if exchange_field_name is None:
            message = "fx_effect missing, treated as 0；当前 cash_flow_sheet 无汇率影响字段，差异率在 1% 内记录 warning，超过 1% 记录 failed。"
        else:
            message = "现金及现金等价物净增加额与经营、投资、筹资现金流净额及汇率影响之和差异率在 1% 内为通过。"
        results.append(
            build_result(
                run_id,
                row,
                "cash_flow_identity",
                status,
                expected_value,
                actual_value,
                related_fields,
                message,
            )
        )
    return results


def write_results(conn, run_id: str, results: List[Dict]) -> None:
    """写入校验结果，同一 run_id 重跑时先删除旧结果。"""
    cur = conn.cursor()
    cur.execute("DELETE FROM financial_validation_result WHERE run_id = %s", (run_id,))
    if results:
        rows = [
            (
                item["run_id"],
                item["file_id"],
                item["stock_code"],
                item["company_name"],
                item["report_year"],
                item["report_period"],
                item["validation_type"],
                item["validation_status"],
                item["expected_value"],
                item["actual_value"],
                item["diff_value"],
                item["diff_ratio"],
                json.dumps(item["related_fields"], ensure_ascii=False),
                item["message"],
            )
            for item in results
        ]
        execute_values(
            cur,
            """
            INSERT INTO financial_validation_result (
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
            )
            VALUES %s
            """,
            rows,
            template="(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)",
        )
    conn.commit()
    cur.close()


def summarize_results(results: List[Dict]) -> Dict:
    """汇总校验结果。"""
    by_type: Dict[str, Dict[str, int]] = {}
    skipped_reason: Dict[str, int] = {}
    for item in results:
        type_bucket = by_type.setdefault(item["validation_type"], {status: 0 for status in STATUS_VALUES})
        type_bucket[item["validation_status"]] = type_bucket.get(item["validation_status"], 0) + 1
        if item["validation_status"] == "skipped":
            message = item.get("message") or "unknown"
            skipped_reason[message] = skipped_reason.get(message, 0) + 1
    return {
        "total_results": len(results),
        "by_validation_type": by_type,
        "skipped_reason_distribution": skipped_reason,
    }


def compact_case(item: Dict) -> Dict:
    """保留排查常用字段。"""
    return {
        "file_id": item.get("file_id"),
        "stock_code": item.get("stock_code"),
        "company_name": item.get("company_name"),
        "report_year": item.get("report_year"),
        "report_period": item.get("report_period"),
        "validation_type": item.get("validation_type"),
        "validation_status": item.get("validation_status"),
        "expected_value": item.get("expected_value"),
        "actual_value": item.get("actual_value"),
        "diff_value": item.get("diff_value"),
        "diff_ratio": item.get("diff_ratio"),
        "related_fields": item.get("related_fields"),
        "message": item.get("message"),
    }


def main() -> int:
    """命令行入口。"""
    args = parse_args()
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        ensure_schema(conn)
        results = []
        results.extend(validate_balance_sheet_identity(args.run_id, fetch_balance_rows(conn, args.run_id)))
        results.extend(validate_cash_flow_identity(args.run_id, fetch_cash_flow_rows(conn, args.run_id)))
        write_results(conn, args.run_id, results)
    finally:
        conn.close()

    report = {
        "run_id": args.run_id,
        "note": "校验失败只记录，不自动修正最终表数值；当前稳定刷新范围不包含 core_performance。",
        "summary": summarize_results(results),
        "failed_cases": [compact_case(item) for item in results if item["validation_status"] == "failed"][:20],
        "skipped_cases": [compact_case(item) for item in results if item["validation_status"] == "skipped"][:20],
        "results": results,
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / f"financial_consistency_report_{args.run_id}.json"
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"output={output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
