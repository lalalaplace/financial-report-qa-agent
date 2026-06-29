import argparse
import json
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, List, Optional

import psycopg2

from db_config import get_db_config


DB_CONFIG = get_db_config()

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = PROJECT_ROOT / "output" / "pdf_extraction" / "validation"
VALIDATION_TABLE_MAP = {
    "balance_sheet_identity": "balance_sheet",
    "cash_flow_identity": "cash_flow_sheet",
}
NON_FIELD_KEYS = {
    "liability_and_equity_field_name",
    "exchange_field_name",
    "identity_check_mode",
}
BALANCE_SHEET_FIELDS = [
    "asset_total_assets",
    "liability_total_liabilities",
    "equity_total_equity",
    "liability_and_equity_total",
]
CURRENT_PERIOD_HINTS = ("期末", "本期", "current_period", "ending_balance")
PREVIOUS_PERIOD_HINTS = ("期初", "上期", "上年", "上期期末", "previous_period")
PREVIOUS_PERIOD_ROLE_VALUES = {"previous_period", "beginning_balance", "prior_period"}


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description="导出 failed 校验案例的最终字段来源。")
    parser.add_argument("--run-id", required=True, help="需要导出 failed 来源的 run_id。")
    return parser.parse_args()


def fetch_failed_cases(conn, run_id: str) -> List[Dict]:
    """读取 failed 校验记录。"""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
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
        WHERE run_id = %s
          AND validation_status = 'failed'
        ORDER BY validation_type, file_id, report_year, report_period
        """,
        (run_id,),
    )
    columns = [item[0] for item in cur.description]
    rows = [dict(zip(columns, row)) for row in cur.fetchall()]
    cur.close()
    return rows


def fetch_lineage(conn, run_id: str, case: Dict, final_table: str, final_field: str) -> Dict:
    """读取单个最终字段的 lineage。"""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            final_field,
            final_value,
            source_page_no,
            source_text,
            extract_method,
            confidence,
            diagnostic_json
        FROM final_table_lineage
        WHERE run_id = %s
          AND file_id = %s
          AND stock_code = %s
          AND report_year = %s
          AND report_period = %s
          AND final_table = %s
          AND final_field = %s
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (
            run_id,
            case.get("file_id"),
            case.get("stock_code"),
            case.get("report_year"),
            case.get("report_period"),
            final_table,
            final_field,
        ),
    )
    row = cur.fetchone()
    columns = [item[0] for item in cur.description]
    cur.close()
    if not row:
        return {
            "field_name": final_field,
            "value": (case.get("related_fields") or {}).get(final_field),
            "source_page_no": None,
            "source_text": None,
            "extract_method": None,
            "confidence": None,
            "diagnostic_json": None,
            "period_role_risk_flag": "",
            "lineage_found": False,
        }

    payload = dict(zip(columns, row))
    period_role_risk_flag = detect_final_field_period_risk(
        payload.get("source_text"),
        payload.get("diagnostic_json"),
    )
    return {
        "field_name": final_field,
        "value": payload.get("final_value"),
        "source_page_no": payload.get("source_page_no"),
        "source_text": payload.get("source_text"),
        "extract_method": payload.get("extract_method"),
        "confidence": payload.get("confidence"),
        "diagnostic_json": payload.get("diagnostic_json"),
        "period_role_risk_flag": period_role_risk_flag,
        "lineage_found": True,
    }


def to_decimal(value) -> Optional[Decimal]:
    """转为 Decimal，无法转换时返回 None。"""
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def stringify_payload(value) -> str:
    """将 lineage 文本和诊断信息统一转成可检索文本。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


def detect_final_field_period_risk(source_text, diagnostic_json) -> str:
    """识别最终字段是否来自上期列。"""
    diagnostic = diagnostic_json if isinstance(diagnostic_json, dict) else {}
    source_text_value = stringify_payload(source_text)
    combined_text = f"{source_text_value}\n{stringify_payload(diagnostic)}"
    role_values = {
        str(diagnostic.get("source_column_role") or "").strip(),
        str(diagnostic.get("selection_period_role") or "").strip(),
    }
    if "previous" in role_values or any(role in role_values for role in PREVIOUS_PERIOD_ROLE_VALUES):
        return "final_field_previous_period_column"
    if diagnostic.get("selection_risk_flag") == "previous_period_used_without_current_candidate":
        return "final_field_previous_period_column"
    if any(hint in combined_text for hint in PREVIOUS_PERIOD_HINTS):
        return "final_field_possible_previous_period_column"
    return ""


def field_source_by_name(field_sources: List[Dict]) -> Dict[str, Dict]:
    """按字段名索引来源记录。"""
    return {item.get("field_name"): item for item in field_sources}


def detect_suspected_reasons(case: Dict, field_sources: List[Dict]) -> List[str]:
    """根据字段来源和校验差异生成初步归因。"""
    reasons = []
    related_fields = case.get("related_fields") or {}
    validation_type = case.get("validation_type")
    source_by_field = field_source_by_name(field_sources)

    source_pages = {
        item.get("source_page_no")
        for item in field_sources
        if item.get("lineage_found") and item.get("source_page_no") is not None
    }
    if len(source_pages) > 1:
        reasons.append("possible_mixed_statement_pages")

    for item in field_sources:
        source_text = stringify_payload(item.get("source_text"))
        diagnostic_json = item.get("diagnostic_json") or {}
        diagnostic_text = stringify_payload(diagnostic_json)
        combined_text = f"{source_text}\n{diagnostic_text}".lower()

        if item.get("lineage_found") and not source_text:
            reasons.append("missing_lineage_source_text")
        if item.get("period_role_risk_flag"):
            reasons.append(item["period_role_risk_flag"])
        is_parent_only = diagnostic_json.get("is_parent_only") is True if isinstance(diagnostic_json, dict) else False
        if "母公司" in combined_text or is_parent_only or '"is_parent_only": true' in combined_text:
            reasons.append("possible_parent_company_statement")
        if (
            "column_role=previous_period" in combined_text
            or '"source_column_role": "previous_period"' in combined_text
            or '"column_role": "previous_period"' in combined_text
            or "期初" in combined_text
            or "上期" in combined_text
            or "上年" in combined_text
            or "年初" in combined_text
        ):
            reasons.append("possible_previous_period_column")

    liability_and_equity_source = source_by_field.get("liability_and_equity_total")
    if (
        validation_type == "balance_sheet_identity"
        and (
            related_fields.get("liability_and_equity_total") is None
            or not liability_and_equity_source
            or not liability_and_equity_source.get("lineage_found")
        )
    ):
        reasons.append("missing_liability_and_equity_total")

    asset_total = to_decimal(related_fields.get("asset_total_assets"))
    liability_and_equity_total = to_decimal(related_fields.get("liability_and_equity_total"))
    if validation_type == "balance_sheet_identity" and asset_total is not None and liability_and_equity_total is not None:
        denominator = max(abs(asset_total), abs(liability_and_equity_total))
        if denominator and abs(asset_total - liability_and_equity_total) / denominator > Decimal("0.01"):
            reasons.append("possible_wrong_row_or_unit")

    return sorted(set(reasons)) or ["unclassified"]


def related_field_names(case: Dict) -> List[str]:
    """从 related_fields 中提取需要回查的最终字段名。"""
    related_fields = case.get("related_fields") or {}
    return [
        field_name
        for field_name, value in related_fields.items()
        if field_name not in NON_FIELD_KEYS and not field_name.endswith("_field_name")
    ]


def build_export(conn, run_id: str, failed_cases: List[Dict]) -> Dict:
    """构造 failed 来源导出内容。"""
    cases = []
    for case in failed_cases:
        validation_type = case.get("validation_type")
        final_table = VALIDATION_TABLE_MAP.get(validation_type)
        fields = []
        if final_table:
            for field_name in related_field_names(case):
                fields.append(fetch_lineage(conn, run_id, case, final_table, field_name))
        suspected_reasons = detect_suspected_reasons(case, fields)

        cases.append(
            {
                "file_id": case.get("file_id"),
                "stock_code": case.get("stock_code"),
                "company_name": case.get("company_name"),
                "report_year": case.get("report_year"),
                "report_period": case.get("report_period"),
                "validation_type": validation_type,
                "validation_status": case.get("validation_status"),
                "expected_value": case.get("expected_value"),
                "actual_value": case.get("actual_value"),
                "diff_value": case.get("diff_value"),
                "diff_ratio": case.get("diff_ratio"),
                "related_fields": case.get("related_fields"),
                "message": case.get("message"),
                "final_table": final_table,
                "suspected_reason": suspected_reasons,
                "field_sources": fields,
            }
        )

    return {
        "run_id": run_id,
        "failed_count": len(cases),
        "cases": cases,
    }


def compact_field_source(source_by_field: Dict[str, Dict], field_name: str) -> Dict:
    """提取根因摘要需要的字段来源。"""
    source = source_by_field.get(field_name) or {}
    return {
        "field_name": field_name,
        "value": source.get("value"),
        "source_page_no": source.get("source_page_no"),
        "source_text": source.get("source_text"),
        "extract_method": source.get("extract_method"),
        "confidence": source.get("confidence"),
        "period_role_risk_flag": source.get("period_role_risk_flag"),
        "diagnostic_json": source.get("diagnostic_json"),
        "lineage_found": bool(source.get("lineage_found")),
    }


def parse_source_text_fields(source_text: Optional[str]) -> Dict[str, str]:
    """从 source_text 中提取 key=value 诊断字段。"""
    result: Dict[str, str] = {}
    if not source_text:
        return result
    for line in str(source_text).splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key and key not in result:
            result[key] = value
    return result


def parse_extra_info(diagnostic_json) -> Dict:
    """读取 extract_extra_info_json。"""
    if not isinstance(diagnostic_json, dict):
        return {}
    raw_extra = diagnostic_json.get("extract_extra_info_json")
    if isinstance(raw_extra, dict):
        return raw_extra
    if not raw_extra:
        return {}
    try:
        return json.loads(raw_extra)
    except (TypeError, json.JSONDecodeError):
        return {}


def build_deep_field_source(source: Dict) -> Dict:
    """构造资产负债表 failed 的字段级深度来源。"""
    source_text = source.get("source_text")
    source_fields = parse_source_text_fields(source_text)
    diagnostic_json = source.get("diagnostic_json") or {}
    extra_info = parse_extra_info(diagnostic_json)

    raw_row_name = (
        source_fields.get("row_label")
        or source_fields.get("value_row_label")
        or diagnostic_json.get("raw_line_name")
        or extra_info.get("value_source_row_label")
    )
    normalized_row_name = (
        source_fields.get("normalized_line_name")
        or diagnostic_json.get("normalized_line_name")
    )
    raw_col_name = (
        source_fields.get("column_label")
        or extra_info.get("column_label")
    )
    col_role = (
        source_fields.get("column_role")
        or diagnostic_json.get("source_column_role")
        or extra_info.get("column_role")
    )
    is_parent_company = False
    if isinstance(diagnostic_json, dict):
        is_parent_company = diagnostic_json.get("is_parent_only") is True
    source_text_value = stringify_payload(source_text)
    if "母公司" in source_text_value:
        is_parent_company = True

    return {
        "field_name": source.get("field_name"),
        "value": source.get("value"),
        "source_page_no": source.get("source_page_no"),
        "source_text": source_text,
        "raw_row_name": raw_row_name,
        "normalized_row_name": normalized_row_name,
        "raw_col_name": raw_col_name,
        "col_role": col_role,
        "selection_period_role": diagnostic_json.get("selection_period_role") if isinstance(diagnostic_json, dict) else None,
        "selection_raw_col_name": diagnostic_json.get("selection_raw_col_name") if isinstance(diagnostic_json, dict) else None,
        "selection_risk_flag": diagnostic_json.get("selection_risk_flag") if isinstance(diagnostic_json, dict) else None,
        "period_role_risk_flag": source.get("period_role_risk_flag"),
        "table_id": diagnostic_json.get("table_id") or extra_info.get("table_id"),
        "statement_type": extra_info.get("statement_type"),
        "is_consolidated": diagnostic_json.get("is_consolidated") if isinstance(diagnostic_json, dict) else None,
        "is_parent_company": is_parent_company,
        "extract_method": source.get("extract_method"),
        "confidence": source.get("confidence"),
        "diagnostic_json": diagnostic_json,
    }


def has_previous_period_hint(value) -> bool:
    """判断文本是否包含上期/期初含义。"""
    text = stringify_payload(value)
    return any(hint in text for hint in PREVIOUS_PERIOD_HINTS)


def has_current_period_hint(value) -> bool:
    """判断文本是否包含本期/期末含义。"""
    text = stringify_payload(value)
    return any(hint in text for hint in CURRENT_PERIOD_HINTS)


def values_diff_large(asset_source: Dict, liability_and_equity_source: Dict) -> bool:
    """判断资产总计与负债和所有者权益总计是否差异较大。"""
    asset_value = to_decimal(asset_source.get("value"))
    liability_and_equity_value = to_decimal(liability_and_equity_source.get("value"))
    if asset_value is None or liability_and_equity_value is None:
        return False
    denominator = max(abs(asset_value), abs(liability_and_equity_value))
    return bool(denominator and abs(asset_value - liability_and_equity_value) / denominator > Decimal("0.01"))


def infer_balance_sheet_root_cause(field_sources: Dict[str, Dict]) -> str:
    """根据资产总计和负债权益总计来源推断具体根因。"""
    asset_source = field_sources.get("asset_total_assets") or {}
    liability_and_equity_source = field_sources.get("liability_and_equity_total") or {}
    if not asset_source or not liability_and_equity_source:
        return "insufficient_lineage_diagnostics"

    required_keys = ("col_role", "raw_col_name")
    if any(asset_source.get(key) is None for key in required_keys) or any(
        liability_and_equity_source.get(key) is None for key in required_keys
    ):
        return "insufficient_lineage_diagnostics"

    asset_col_role = asset_source.get("col_role")
    liability_and_equity_col_role = liability_and_equity_source.get("col_role")
    if asset_col_role != liability_and_equity_col_role:
        return "previous_period_column_mismatch"

    asset_col_name = asset_source.get("raw_col_name")
    liability_and_equity_col_name = liability_and_equity_source.get("raw_col_name")
    if (
        has_previous_period_hint(asset_col_name) and has_current_period_hint(liability_and_equity_col_name)
    ) or (
        has_current_period_hint(asset_col_name) and has_previous_period_hint(liability_and_equity_col_name)
    ):
        return "previous_period_column_mismatch"

    asset_table_id = asset_source.get("table_id")
    liability_and_equity_table_id = liability_and_equity_source.get("table_id")
    if asset_table_id is not None and liability_and_equity_table_id is not None and asset_table_id != liability_and_equity_table_id:
        return "mixed_statement_table"

    asset_scope = (asset_source.get("is_consolidated"), asset_source.get("is_parent_company"))
    liability_and_equity_scope = (
        liability_and_equity_source.get("is_consolidated"),
        liability_and_equity_source.get("is_parent_company"),
    )
    if None not in asset_scope + liability_and_equity_scope and asset_scope != liability_and_equity_scope:
        return "mixed_consolidated_parent_scope"

    if values_diff_large(asset_source, liability_and_equity_source):
        return "possible_wrong_row_or_unit"

    return "insufficient_lineage_diagnostics"


def suggested_fix_for_root_cause(root_cause: str) -> List[str]:
    """根据具体根因给出建议修复方向。"""
    mapping = {
        "previous_period_column_mismatch": [
            "require_same_col_role_for_balance_sheet_identity_fields",
            "enhance_col_role_detection_for_balance_sheet",
        ],
        "mixed_statement_table": [
            "require_same_statement_table_for_identity_fields",
        ],
        "mixed_consolidated_parent_scope": [
            "require_same_statement_table_for_identity_fields",
        ],
        "possible_wrong_row_or_unit": [
            "inspect_unit_multiplier_or_row_mapping",
        ],
        "insufficient_lineage_diagnostics": [
            "enhance_col_role_detection_for_balance_sheet",
        ],
    }
    return mapping.get(root_cause, ["inspect_unit_multiplier_or_row_mapping"])


def build_balance_sheet_deep_dive_report(run_id: str, payload: Dict) -> Dict:
    """生成资产负债表 failed 深度归因报告。"""
    cases = []
    for case in payload.get("cases", []):
        if case.get("validation_type") != "balance_sheet_identity":
            continue
        source_by_field = field_source_by_name(case.get("field_sources") or [])
        deep_sources = {
            field_name: build_deep_field_source(source_by_field.get(field_name) or {"field_name": field_name})
            for field_name in BALANCE_SHEET_FIELDS
        }
        root_cause = infer_balance_sheet_root_cause(deep_sources)
        cases.append(
            {
                "file_id": case.get("file_id"),
                "stock_code": case.get("stock_code"),
                "company_name": case.get("company_name"),
                "report_year": case.get("report_year"),
                "report_period": case.get("report_period"),
                "identity_check_mode": (case.get("related_fields") or {}).get("identity_check_mode"),
                "expected_value": case.get("expected_value"),
                "actual_value": case.get("actual_value"),
                "diff_value": case.get("diff_value"),
                "diff_ratio": case.get("diff_ratio"),
                "field_sources": deep_sources,
                "root_cause": root_cause,
                "suggested_fix": suggested_fix_for_root_cause(root_cause),
            }
        )
    return {
        "run_id": run_id,
        "balance_sheet_failed_count": len(cases),
        "cases": cases,
    }


def build_suggested_next_action(suspected_reasons: List[str]) -> str:
    """根据初步归因生成下一步排查建议。"""
    if "possible_mixed_statement_pages" in suspected_reasons:
        return "优先核对同一 failed case 中各字段是否来自同一张资产负债表页，排查合并报表与母公司报表混用。"
    if "possible_parent_company_statement" in suspected_reasons:
        return "优先核对来源是否为母公司资产负债表，必要时提高合并报表来源优先级。"
    if "possible_previous_period_column" in suspected_reasons:
        return "优先检查列角色识别，确认是否误取期初、上期或上年金额列。"
    if "missing_liability_and_equity_total" in suspected_reasons:
        return "优先补充或排查负债和所有者权益总计字段的别名、行匹配和金额列选择。"
    if "possible_wrong_row_or_unit" in suspected_reasons:
        return "优先核对 asset_total_assets 与 liability_and_equity_total 的来源行和单位，确认是否取到错误行或不同口径。"
    if "missing_lineage_source_text" in suspected_reasons:
        return "优先检查 final_table_lineage 的 source_text 写入完整性。"
    return "查看字段 lineage，人工判断字段来源行、页码、列角色和报表口径是否一致。"


def build_balance_sheet_root_cause_report(run_id: str, payload: Dict) -> Dict:
    """生成资产负债表 failed 根因摘要。"""
    cases = []
    for case in payload.get("cases", []):
        if case.get("validation_type") != "balance_sheet_identity":
            continue
        source_by_field = field_source_by_name(case.get("field_sources") or [])
        suspected_reasons = case.get("suspected_reason") or ["unclassified"]
        related_fields = case.get("related_fields") or {}
        cases.append(
            {
                "file_id": case.get("file_id"),
                "stock_code": case.get("stock_code"),
                "company_name": case.get("company_name"),
                "report_year": case.get("report_year"),
                "report_period": case.get("report_period"),
                "identity_check_mode": related_fields.get("identity_check_mode"),
                "asset_total_assets_source": compact_field_source(source_by_field, "asset_total_assets"),
                "liability_total_liabilities_source": compact_field_source(source_by_field, "liability_total_liabilities"),
                "equity_total_equity_source": compact_field_source(source_by_field, "equity_total_equity"),
                "liability_and_equity_total_source": compact_field_source(source_by_field, "liability_and_equity_total"),
                "suspected_reason": suspected_reasons,
                "suggested_next_action": build_suggested_next_action(suspected_reasons),
            }
        )
    return {
        "run_id": run_id,
        "balance_sheet_failed_count": len(cases),
        "cases": cases,
    }


def main() -> int:
    """命令行入口。"""
    args = parse_args()
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        failed_cases = fetch_failed_cases(conn, args.run_id)
        payload = build_export(conn, args.run_id, failed_cases)
    finally:
        conn.close()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / f"failed_validation_sources_{args.run_id}.json"
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    root_cause_report = build_balance_sheet_root_cause_report(args.run_id, payload)
    root_cause_path = OUTPUT_DIR / f"balance_sheet_failed_root_cause_{args.run_id}.json"
    root_cause_path.write_text(json.dumps(root_cause_report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    deep_dive_report = build_balance_sheet_deep_dive_report(args.run_id, payload)
    deep_dive_path = OUTPUT_DIR / f"balance_sheet_failed_deep_dive_{args.run_id}.json"
    deep_dive_path.write_text(json.dumps(deep_dive_report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(output_path),
                "root_cause_output": str(root_cause_path),
                "deep_dive_output": str(deep_dive_path),
                "failed_count": payload["failed_count"],
                "balance_sheet_failed_count": root_cause_report["balance_sheet_failed_count"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

