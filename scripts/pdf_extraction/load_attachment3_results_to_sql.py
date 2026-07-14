import argparse
import os
import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

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
PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATEMENT_JSON_DIR = PROJECT_ROOT / "output" / "pdf_extraction" / "statement_json"
LINEAGE_SOURCE_TABLE = "attachment3_extract_result"

SUPPORTED_TARGET_TABLES = ["balance_sheet", "income", "cash_flow", "core_performance"]
SOURCE_TO_FINAL_TABLE = {
    "balance_sheet": "balance_sheet",
    "income": "income_sheet",
    "cash_flow": "cash_flow_sheet",
}
METHOD_PRIORITY = {
    "manual_backfill": 0,
    "rule": 1,
    "rule_candidate_fill": 2,
}
PERIOD_ORDER = {
    "Q1": 1,
    "HY": 2,
    "Q3": 3,
    "FY": 4,
}
MIN_REVENUE_FOR_TINY_PROFIT_CHECK = Decimal("100000000")
MAX_TINY_PROFIT_ABS_VALUE = Decimal("1000")
REQUIRED_KEY_COLUMNS = ["stock_code", "report_year", "report_period"]
BASE_OPTIONAL_COLUMNS = ["serial_number", "stock_abbr", "company_name"]
SKIP_FINAL_FIELD_NAMES = {
    "file_id",
    "company_id",
    "serial_number",
    "stock_code",
    "stock_abbr",
    "report_year",
    "report_period",
}
BALANCE_SHEET_STRICT_CURRENT_FIELDS = {
    "asset_total_assets",
    "liability_total_liabilities",
    "equity_total_equity",
    "liability_and_equity_total",
}
CURRENT_PERIOD_ROLES = {
    "current_period",
    "ending_balance",
    "current_amount",
    "current",
    "期末余额",
    "本期金额",
    "本期",
}
PREVIOUS_PERIOD_ROLES = {
    "previous_period",
    "beginning_balance",
    "prior_period",
    "期初余额",
    "上年年末余额",
    "上年末",
    "年初余额",
    "上期末",
}
CURRENT_PERIOD_HINTS = ("期末", "本期", "current_period", "ending_balance", "current_amount")
PREVIOUS_PERIOD_HINTS = ("期初", "上年年末", "上年末", "年初", "上期", "previous_period", "beginning_balance", "prior_period")
EXTRA_FIELD_DEFINITIONS = {
    "balance_sheet": [
        {
            "target_table": "balance_sheet",
            "field_code": "balance_sheet.liability_and_equity_total",
            "final_field_name": "liability_and_equity_total",
            "field_name_cn": "负债和所有者权益总计",
            "data_type": "decimal",
            "sort_order": 9991,
        }
    ]
}
EXTRA_FINAL_TABLE_COLUMNS = {
    "balance_sheet": {
        "liability_and_equity_total": "DECIMAL(20,2)",
    }
}
EQUITY_TOTAL_EQUITY_EXPLICIT_ALIASES = {
    "所有者权益合计",
    "股东权益合计",
    "所有者权益（或股东权益）合计",
    "所有者权益(或股东权益)合计",
    "股东权益总计",
    "权益合计",
    "所有者权益总计",
    "（或股东权益）合计",
    "(或股东权益)合计",
}
EQUITY_TOTAL_EQUITY_FORBIDDEN_ROW_TOKENS = [
    "资产总计",
    "负债合计",
    "负债和所有者权益总计",
    "负债及所有者权益总计",
    "负债和所有者权益（或股东权益）总计",
    "负债和所有者权益(或股东权益)总计",
    "负债及所有者权益（或股东权益）总计",
    "负债及所有者权益(或股东权益)总计",
    "少数股东权益",
    "归属于母公司所有者权益",
]


def configure_console() -> None:
    """配置控制台编码，避免 Windows 输出异常。"""
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


def safe_text(text) -> str:
    """将任意对象转换为安全文本。"""
    if text is None:
        return ""
    try:
        return str(text)
    except Exception:
        return repr(text)


def safe_print(*args) -> None:
    """安全输出。"""
    text = " ".join(safe_text(arg) for arg in args)
    try:
        print(text)
    except UnicodeEncodeError:
        encoded = text.encode("utf-8", errors="replace").decode("utf-8", errors="replace")
        print(encoded)


def normalize_text(value) -> str:
    """标准化文本。"""
    if value is None:
        return ""
    text = str(value)
    text = text.replace("\u3000", " ")
    text = text.replace("\xa0", " ")
    return text.strip()


def compact_text(value) -> str:
    """压缩空白和括号变体，便于行名判断。"""
    text = normalize_text(value)
    text = text.replace("（", "(").replace("）", ")")
    return re.sub(r"\s+", "", text)


def normalize_stock_code(value) -> str:
    """统一股票代码格式。"""
    text = normalize_text(value)
    if not text:
        return ""
    if text.endswith(".0"):
        text = text[:-2]
    text = re.sub(r"\s+", "", text)
    if text.isdigit() and len(text) <= 6:
        return text.zfill(6)
    return text


def normalize_period(period: Optional[str]) -> Optional[str]:
    """统一报告期枚举值。"""
    if period is None:
        return None

    period_text = normalize_text(period).upper()
    mapping = {
        "Q1": "Q1",
        "FIRST_QUARTER": "Q1",
        "HY": "HY",
        "H1": "HY",
        "SEMIANNUAL": "HY",
        "SEMI_ANNUAL": "HY",
        "HALF_YEAR": "HY",
        "Q3": "Q3",
        "THIRD_QUARTER": "Q3",
        "FY": "FY",
        "ANNUAL": "FY",
        "YEAR": "FY",
        "YEARLY": "FY",
    }
    return mapping.get(period_text, period_text)


def should_skip_final_field_name(final_field_name: str) -> bool:
    """过滤不应回写到最终标准表的元字段。"""
    normalized_name = normalize_text(final_field_name)
    return normalized_name in SKIP_FINAL_FIELD_NAMES


def parse_args():
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description="从 attachment3_extract_result 择优取值并写入附件3标准最终表。")
    parser.add_argument("--file-id", type=int, nargs="*", help="仅处理指定 file_id，可传多个。")
    parser.add_argument("--limit", type=int, help="若未指定 --file-id，则只处理前 N 个 file_id。")
    parser.add_argument("--run-id", help="本轮运行编号，用于写入 final_table_lineage。")
    parser.add_argument(
        "--target-table",
        choices=SUPPORTED_TARGET_TABLES,
        nargs="*",
        help="仅处理指定 target_table，可传多个。",
    )
    return parser.parse_args()


def resolve_run_id(raw_run_id: Optional[str]) -> str:
    """解析本轮 lineage 使用的 run_id。"""
    normalized = normalize_text(raw_run_id)
    if normalized:
        return normalized
    return "manual_" + datetime.now().strftime("%Y%m%d_r%H%M%S")


def parse_statement_json_name(file_name: str) -> Optional[Tuple[int, str]]:
    """从 statement_json 文件名中解析 file_id 和报表类型。"""
    match = re.match(r"file_(\d+)_(balance_sheet|income|cash_flow)\.json$", file_name)
    if not match:
        return None
    return int(match.group(1)), match.group(2)


def resolve_scope_file_ids_from_statement_json(limit: Optional[int]) -> Optional[List[int]]:
    """优先按 statement_json 中存在的 file_id 限流，保持与抽取阶段一致。"""
    if limit is None or not STATEMENT_JSON_DIR.exists():
        return None

    file_ids = set()
    for path in STATEMENT_JSON_DIR.glob("file_*_*.json"):
        parsed = parse_statement_json_name(path.name)
        if parsed is None:
            continue
        file_ids.add(parsed[0])

    if not file_ids:
        return None
    return sorted(file_ids)[:limit]


def fetch_table_columns(conn, table_name: str) -> Set[str]:
    """读取目标表真实列集合。"""
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
    rows = cur.fetchall()
    cur.close()
    return {row[0] for row in rows}


def ensure_extra_final_table_columns(conn, final_table_name: str) -> None:
    """确保新增诊断字段对应的最终表列存在。"""
    columns = EXTRA_FINAL_TABLE_COLUMNS.get(final_table_name) or {}
    if not columns:
        return
    cur = conn.cursor()
    try:
        for column_name, column_type in columns.items():
            cur.execute(
                sql.SQL("ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS {column_name} {column_type}").format(
                    table_name=sql.Identifier(final_table_name),
                    column_name=sql.Identifier(column_name),
                    column_type=sql.SQL(column_type),
                )
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


def ensure_final_table_lineage_schema(conn) -> None:
    """确保最终字段 lineage 表存在。"""
    cur = conn.cursor()
    try:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS final_table_lineage (
                id BIGSERIAL PRIMARY KEY,
                run_id TEXT NOT NULL,
                file_id BIGINT NOT NULL,
                stock_code VARCHAR(32),
                company_name VARCHAR(255),
                report_year INTEGER,
                report_period VARCHAR(32),
                final_table VARCHAR(128) NOT NULL,
                final_field VARCHAR(128) NOT NULL,
                final_value TEXT,
                source_table VARCHAR(128) NOT NULL DEFAULT 'attachment3_extract_result',
                source_result_id BIGINT,
                source_page_no INTEGER,
                source_text TEXT,
                source_raw_value TEXT,
                extract_method VARCHAR(128),
                extract_status VARCHAR(128),
                confidence DOUBLE PRECISION,
                diagnostic_json JSONB,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT final_table_lineage_unique_run_field UNIQUE (
                    run_id,
                    file_id,
                    final_table,
                    final_field,
                    report_year,
                    report_period
                )
            )
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_final_table_lineage_lookup
            ON final_table_lineage (stock_code, report_year, report_period, final_table, final_field)
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_final_table_lineage_source_result
            ON final_table_lineage (source_result_id)
            """
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


def fetch_field_dict(conn, target_table: str) -> List[Dict]:
    """读取字段字典，并生成最终标准列名。"""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            target_table,
            field_code,
            split_part(field_code, '.', 2) AS final_field_name,
            field_name_cn,
            data_type,
            sort_order
        FROM attachment3_field_dict
        WHERE target_table = %s
        ORDER BY sort_order, field_code
        """,
        (target_table,),
    )
    rows = list(cur.fetchall())
    cur.close()
    existing_field_codes = {normalize_text(row[1]) for row in rows}

    fields: List[Dict] = []
    for row in rows:
        final_field_name = normalize_text(row[2])
        if not final_field_name or should_skip_final_field_name(final_field_name):
            continue
        fields.append(
            {
                "target_table": row[0],
                "field_code": row[1],
                "final_field_name": final_field_name,
                "field_name_cn": row[3],
                "data_type": normalize_text(row[4]),
                "sort_order": row[5],
            }
        )
    for extra_field in EXTRA_FIELD_DEFINITIONS.get(target_table, []):
        if extra_field["field_code"] in existing_field_codes:
            continue
        if should_skip_final_field_name(extra_field["final_field_name"]):
            continue
        fields.append(dict(extra_field))
    return fields


def resolve_scope_file_ids(conn, file_ids: Optional[List[int]], limit: Optional[int]) -> Optional[List[int]]:
    """解析本次处理范围的 file_id 集合。"""
    if file_ids:
        return sorted(set(file_ids))
    if limit is None:
        return None

    statement_json_file_ids = resolve_scope_file_ids_from_statement_json(limit)
    if statement_json_file_ids is not None:
        return statement_json_file_ids

    cur = conn.cursor()
    cur.execute(
        """
        SELECT file_id
        FROM report_file_index
        ORDER BY file_id
        LIMIT %s
        """,
        (limit,),
    )
    rows = cur.fetchall()
    cur.close()
    return [row[0] for row in rows]


def fetch_report_meta(conn, file_ids: Optional[List[int]] = None) -> Dict[int, Dict]:
    """读取报告元数据。"""
    params: List = []
    where_sql = ""
    if file_ids:
        where_sql = "WHERE file_id = ANY(%s)"
        params.append(file_ids)

    report_columns = fetch_table_columns(conn, "report_file_index")
    is_summary_sql = "COALESCE(is_summary, FALSE) AS is_summary" if "is_summary" in report_columns else "FALSE AS is_summary"

    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT
            file_id,
            stock_code,
            stock_abbr,
            company_name,
            report_year,
            report_period,
            {is_summary_sql}
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
            "stock_code": normalize_stock_code(row[1]),
            "stock_abbr": normalize_text(row[2]),
            "company_name": normalize_text(row[3]),
            "report_year": row[4],
            "report_period": normalize_period(row[5]),
            "is_summary": bool(row[6]),
        }
    return meta_map


def build_logical_key_from_meta(meta: Dict) -> Optional[Tuple[str, int, str]]:
    """根据元数据构造逻辑键。"""
    stock_code = normalize_stock_code(meta.get("stock_code"))
    report_year = meta.get("report_year")
    report_period = normalize_period(meta.get("report_period"))
    if not stock_code or report_year is None or not report_period:
        return None
    return stock_code, report_year, report_period


def build_scope_key_map(meta_map: Dict[int, Dict]) -> Dict[Tuple[str, int, str], Set[int]]:
    """构造逻辑键到 file_id 集合的映射。"""
    scope_key_map: Dict[Tuple[str, int, str], Set[int]] = defaultdict(set)
    for file_id, meta in meta_map.items():
        logical_key = build_logical_key_from_meta(meta)
        if logical_key is None:
            continue
        scope_key_map[logical_key].add(file_id)
    return scope_key_map


def fetch_extract_results(conn, target_table: str, file_ids: Optional[List[int]] = None) -> List[Dict]:
    """读取候选抽取结果，并补齐择优所需信息。"""
    params: List = [target_table]
    file_filter_sql = ""
    if file_ids:
        file_filter_sql = "AND e.file_id = ANY(%s)"
        params.append(file_ids)

    extract_columns = fetch_table_columns(conn, "attachment3_extract_result")
    report_columns = fetch_table_columns(conn, "report_file_index")
    locator_columns = fetch_table_columns(conn, "report_statement_locator")

    result_confidence_sql = "COALESCE(e.confidence, 0) AS result_confidence" if "confidence" in extract_columns else "0 AS result_confidence"
    result_id_sql = "e.result_id AS source_result_id" if "result_id" in extract_columns else "NULL AS source_result_id"
    extra_info_sql = "COALESCE(e.extra_info_json, '') AS extract_extra_info_json" if "extra_info_json" in extract_columns else "'' AS extract_extra_info_json"
    is_summary_sql = "COALESCE(r.is_summary, FALSE) AS is_summary" if "is_summary" in report_columns else "FALSE AS is_summary"

    if locator_columns:
        locator_confidence_sql = (
            "COALESCE(l.locator_confidence, 0) AS locator_confidence"
            if "locator_confidence" in locator_columns else "0 AS locator_confidence"
        )
        is_consolidated_sql = (
            "COALESCE(l.is_consolidated, FALSE) AS is_consolidated"
            if "is_consolidated" in locator_columns else "FALSE AS is_consolidated"
        )
        is_parent_only_sql = (
            "COALESCE(l.is_parent_only, FALSE) AS is_parent_only"
            if "is_parent_only" in locator_columns else "FALSE AS is_parent_only"
        )
        locator_join_sql = """
        LEFT JOIN report_statement_locator l
            ON e.file_id = l.file_id
           AND e.target_table = l.statement_type
        """
    else:
        locator_confidence_sql = "0 AS locator_confidence"
        is_consolidated_sql = "FALSE AS is_consolidated"
        is_parent_only_sql = "FALSE AS is_parent_only"
        locator_join_sql = ""

    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT
            {result_id_sql},
            e.file_id,
            e.field_code,
            e.value_text,
            e.extract_method,
            {result_confidence_sql},
            e.raw_line_name,
            e.normalized_line_name,
            e.source_page,
            e.source_column_role,
            e.source_text,
            {extra_info_sql},
            r.stock_code,
            r.stock_abbr,
            r.company_name,
            r.report_year,
            r.report_period,
            {is_summary_sql},
            {locator_confidence_sql},
            {is_consolidated_sql},
            {is_parent_only_sql}
        FROM attachment3_extract_result e
        INNER JOIN report_file_index r
            ON e.file_id = r.file_id
        {locator_join_sql}
        WHERE e.target_table = %s
          AND e.extract_method IN ('rule', 'rule_candidate_fill', 'manual_backfill')
          AND COALESCE(e.field_code, '') <> ''
          AND COALESCE(e.value_text, '') <> ''
          {file_filter_sql}
        ORDER BY e.file_id, e.field_code, e.extract_method
        """,
        params,
    )
    rows = cur.fetchall()
    cur.close()

    results: List[Dict] = []
    for row in rows:
        results.append(
            {
                "source_result_id": row[0],
                "file_id": row[1],
                "field_code": normalize_text(row[2]),
                "value_text": row[3],
                "extract_method": normalize_text(row[4]),
                "result_confidence": float(row[5] or 0.0),
                "raw_line_name": normalize_text(row[6]),
                "normalized_line_name": normalize_text(row[7]),
                "source_page": row[8],
                "source_column_role": normalize_text(row[9]),
                "source_text": normalize_text(row[10]),
                "extract_extra_info_json": normalize_text(row[11]),
                "stock_code": normalize_stock_code(row[12]),
                "stock_abbr": normalize_text(row[13]),
                "company_name": normalize_text(row[14]),
                "report_year": row[15],
                "report_period": normalize_period(row[16]),
                "is_summary": bool(row[17]),
                "locator_confidence": float(row[18] or 0.0),
                "is_consolidated": bool(row[19]),
                "is_parent_only": bool(row[20]),
                "target_table": target_table,
            }
        )
    return results


def is_valid_candidate(row: Dict) -> bool:
    """判断候选结果是否可用于最终表。"""
    value_text = normalize_text(row.get("value_text"))
    extract_method = normalize_text(row.get("extract_method"))
    if not value_text:
        return False

    if extract_method == "rule":
        return True
    if extract_method == "manual_backfill":
        return True
    if extract_method == "rule_candidate_fill":
        return True
    return False


def parse_value(value_text: str, data_type: str):
    """按字段类型解析最终值。"""
    raw_text = normalize_text(value_text)
    if raw_text == "":
        return None

    dtype = normalize_text(data_type).lower()
    cleaned = raw_text.replace(",", "")
    cleaned = cleaned.replace("（", "(").replace("）", ")")
    cleaned = cleaned.replace("－", "-").replace("—", "-").replace("–", "-")
    cleaned = cleaned.strip()

    null_tokens = {"", "-", "--", "---", "不适用", "n/a", "nan", "无"}
    if cleaned.lower() in null_tokens:
        return None

    parentheses_match = re.match(r"^\((.+)\)$", cleaned)
    if parentheses_match:
        cleaned = f"-{parentheses_match.group(1).strip()}"

    cleaned = re.sub(r"\s+", "", cleaned)
    if cleaned.endswith("%"):
        cleaned = cleaned[:-1]

    if "int" in dtype:
        try:
            return int(Decimal(cleaned))
        except (InvalidOperation, ValueError):
            return None

    if "decimal" in dtype or "numeric" in dtype:
        try:
            return Decimal(cleaned)
        except (InvalidOperation, ValueError):
            return None

    if "varchar" in dtype or "char" in dtype or "text" in dtype:
        return raw_text

    return raw_text


def get_decimal_value(record: Dict, field_name: str) -> Optional[Decimal]:
    """读取记录中的数值字段并转为 Decimal。"""
    value = record.get(field_name)
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return None


def add_rejection(rejections: List[str], field_name: str, reason: str) -> None:
    """记录字段被拦截的原因。"""
    rejections.append(f"{field_name}:{reason}")


def parse_rejection_field(rejection: str) -> str:
    """从校验拦截文本中取出最终字段名。"""
    return rejection.split(":", 1)[0].strip()


def build_rejection_source_context(rejections: List[str], selected_candidates: Dict[str, Dict]) -> str:
    """生成校验拦截对应的来源行信息，便于从日志直接定位错抽来源。"""
    field_names: List[str] = []
    for rejection in rejections:
        field_name = parse_rejection_field(rejection)
        field_names.extend(name for name in field_name.split("/") if name)
    source_parts: List[str] = []
    for item_field_name in field_names:
        candidate = selected_candidates.get(item_field_name)
        if not candidate:
            continue
        source_parts.append(
            ",".join(
                [
                    f"field={item_field_name}",
                    f"file_id={candidate.get('file_id')}",
                    f"method={candidate.get('extract_method')}",
                    f"raw_line={normalize_text(candidate.get('raw_line_name'))}",
                    f"normalized_line={normalize_text(candidate.get('normalized_line_name'))}",
                    f"value={normalize_text(candidate.get('value_text'))}",
                    f"role={normalize_text(candidate.get('source_column_role'))}",
                    f"page={candidate.get('source_page')}",
                    f"confidence={candidate.get('result_confidence')}",
                ]
            )
        )
    if not source_parts:
        return "source=未找到已选候选"
    return "sources=" + " || ".join(source_parts)


def apply_record_validations(target_table: str, record: Dict, selected_candidates: Optional[Dict[str, Dict]] = None) -> Tuple[Dict, List[str]]:
    """对最终记录做业务合理性校验。"""
    validated = dict(record)
    rejections: List[str] = []
    selected_candidates = selected_candidates or {}

    if target_table == "balance_sheet":
        total_assets = get_decimal_value(validated, "asset_total_assets")
        component_fields = [
            "asset_cash_and_cash_equivalents",
            "asset_accounts_receivable",
            "asset_inventory",
            "asset_trading_financial_assets",
            "asset_construction_in_progress",
            "liability_total_liabilities",
            "equity_total_equity",
        ]
        component_values = [
            value
            for value in (get_decimal_value(validated, field_name) for field_name in component_fields)
            if value is not None
        ]
        if total_assets is not None and component_values and total_assets < max(component_values):
            validated["asset_total_assets"] = None
            add_rejection(rejections, "asset_total_assets", "小于关键组成项或负债/权益，判定为错值")

        total_liabilities = get_decimal_value(validated, "liability_total_liabilities")
        if total_assets is not None and total_liabilities is not None and total_liabilities > total_assets:
            validated["liability_total_liabilities"] = None
            add_rejection(rejections, "liability_total_liabilities", "大于总资产，判定为错值")

        total_equity = get_decimal_value(validated, "equity_total_equity")
        if total_assets is not None and total_assets > 0 and total_equity is not None:
            if abs(total_equity) < total_assets * Decimal("0.01"):
                validated["equity_total_equity"] = None
                add_rejection(rejections, "equity_total_equity", "suspicious_too_small:小于总资产 1%，疑似抽到附注列、序号列或行次列")
            elif total_equity == total_assets:
                equity_candidate = selected_candidates.get("equity_total_equity") or {}
                if not is_explicit_equity_total_candidate(equity_candidate):
                    validated["equity_total_equity"] = None
                    add_rejection(rejections, "equity_total_equity", "suspicious_equal_asset_total:等于总资产且行名不是明确权益合计")

    if target_table == "income":
        total_revenue = get_decimal_value(validated, "total_operating_revenue")
        net_profit = get_decimal_value(validated, "net_profit")
        if (
            total_revenue is not None
            and total_revenue >= MIN_REVENUE_FOR_TINY_PROFIT_CHECK
            and net_profit is not None
            and abs(net_profit) <= MAX_TINY_PROFIT_ABS_VALUE
        ):
            validated["net_profit"] = None
            add_rejection(rejections, "net_profit", "营业收入很大但净利润接近 0/1，疑似抽到序号或标记")

    if target_table == "cash_flow":
        net_fields = [
            "operating_cf_net_amount",
            "investing_cf_net_amount",
            "financing_cf_net_amount",
        ]
        non_null_values = [get_decimal_value(validated, field_name) for field_name in net_fields]
        non_null_values = [value for value in non_null_values if value is not None]
        if len(non_null_values) >= 3 and len(set(non_null_values)) == 1:
            for field_name in net_fields:
                validated[field_name] = None
            add_rejection(rejections, "operating/investing/financing_cf_net_amount", "三个净额完全相同，疑似重复填值")

    return validated, rejections


def build_row_priority(row: Dict) -> Tuple:
    """构造显式择优排序键。"""
    return (
        1 if row.get("is_summary") else 0,
        0 if row.get("is_consolidated") else 1,
        1 if row.get("is_parent_only") else 0,
        METHOD_PRIORITY.get(normalize_text(row.get("extract_method")), 999),
        -float(row.get("result_confidence") or 0.0),
        -float(row.get("locator_confidence") or 0.0),
        int(row.get("file_id") or 0),
    )


def parse_json_object(value) -> Dict:
    """解析 JSON 对象文本，无法解析时返回空字典。"""
    if isinstance(value, dict):
        return value
    text = normalize_text(value)
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def candidate_row_texts(candidate: Dict) -> List[str]:
    """读取候选行名相关文本。"""
    extra_info = parse_json_object(candidate.get("extract_extra_info_json"))
    return [
        candidate.get("raw_line_name", ""),
        candidate.get("normalized_line_name", ""),
        extra_info.get("matched_variant", ""),
    ]


def is_explicit_equity_total_candidate(candidate: Dict) -> bool:
    """判断权益合计候选是否来自明确行名。"""
    allowed = {compact_text(alias) for alias in EQUITY_TOTAL_EQUITY_EXPLICIT_ALIASES if compact_text(alias)}
    return any(compact_text(text) in allowed for text in candidate_row_texts(candidate) if compact_text(text))


def has_forbidden_equity_total_row(candidate: Dict) -> bool:
    """判断权益候选是否命中禁止行名。"""
    for text in candidate_row_texts(candidate):
        compact_value = compact_text(text)
        if not compact_value:
            continue
        if any(compact_text(token) and compact_text(token) in compact_value for token in EQUITY_TOTAL_EQUITY_FORBIDDEN_ROW_TOKENS):
            return True
    return False


def is_low_confidence_equity_rule_fallback(candidate: Dict) -> bool:
    """识别低置信 candidate_fill_rule_fallback。"""
    extra_info = parse_json_object(candidate.get("extract_extra_info_json"))
    fill_stage = normalize_text(extra_info.get("fill_stage"))
    row_match_score = extra_info.get("row_match_score")
    try:
        score = float(row_match_score if row_match_score is not None else candidate.get("result_confidence") or 0.0)
    except (TypeError, ValueError):
        score = 0.0
    if score <= 1:
        score *= 100
    return fill_stage == "candidate_fill_rule_fallback" and score < 85


def parse_source_text_fields(source_text: str) -> Dict[str, str]:
    """从 source_text 中提取 key=value 形式的来源字段。"""
    result: Dict[str, str] = {}
    for line in normalize_text(source_text).splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key and key not in result:
            result[key] = value.strip()
    return result


def get_candidate_raw_col_name(candidate: Dict) -> str:
    """读取候选值的原始列名。"""
    source_fields = parse_source_text_fields(candidate.get("source_text"))
    extra_info = parse_json_object(candidate.get("extract_extra_info_json"))
    return normalize_text(source_fields.get("column_label") or extra_info.get("column_label"))


def classify_period_role(candidate: Dict) -> str:
    """将候选值列角色归类为 current、previous 或 unknown。"""
    role = normalize_text(candidate.get("source_column_role"))
    raw_col_name = get_candidate_raw_col_name(candidate)
    source_text = normalize_text(candidate.get("source_text"))
    extra_text = normalize_text(candidate.get("extract_extra_info_json"))
    combined_text = "\n".join([role, raw_col_name, source_text, extra_text])

    if role in CURRENT_PERIOD_ROLES:
        return "current"
    if role in PREVIOUS_PERIOD_ROLES:
        return "previous"
    if any(hint in combined_text for hint in PREVIOUS_PERIOD_HINTS):
        return "previous"
    if any(hint in combined_text for hint in CURRENT_PERIOD_HINTS):
        return "current"
    return "unknown"


def is_balance_sheet_amount_field(target_table: str, field_def: Dict) -> bool:
    """判断是否为资产负债表金额类字段。"""
    if target_table != "balance_sheet":
        return False
    data_type = normalize_text(field_def.get("data_type")).lower()
    return "decimal" in data_type or "numeric" in data_type or "int" in data_type


def select_final_candidate(target_table: str, field_def: Dict, candidates: List[Dict]) -> Optional[Dict]:
    """按最终表写入规则选择候选值。"""
    if not candidates:
        return None
    if target_table == "balance_sheet" and field_def.get("final_field_name") == "equity_total_equity":
        candidates = [
            candidate
            for candidate in candidates
            if not has_forbidden_equity_total_row(candidate)
            and not is_low_confidence_equity_rule_fallback(candidate)
        ]
        if not candidates:
            return None
    if not is_balance_sheet_amount_field(target_table, field_def):
        best = sorted(candidates, key=build_row_priority)[0]
        best["selection_period_role"] = classify_period_role(best)
        best["selection_risk_flag"] = ""
        return best

    annotated = []
    for candidate in candidates:
        item = dict(candidate)
        item["selection_period_role"] = classify_period_role(item)
        item["selection_raw_col_name"] = get_candidate_raw_col_name(item)
        annotated.append(item)

    current_candidates = [item for item in annotated if item["selection_period_role"] == "current"]
    unknown_candidates = [item for item in annotated if item["selection_period_role"] == "unknown"]
    previous_candidates = [item for item in annotated if item["selection_period_role"] == "previous"]

    if current_candidates:
        best = sorted(current_candidates, key=build_row_priority)[0]
        best["selection_risk_flag"] = ""
        return best
    if unknown_candidates:
        best = sorted(unknown_candidates, key=build_row_priority)[0]
        best["selection_risk_flag"] = "unknown_period_role_no_current_candidate"
        return best
    if previous_candidates and field_def.get("final_field_name") in BALANCE_SHEET_STRICT_CURRENT_FIELDS:
        return None
    if previous_candidates:
        best = sorted(previous_candidates, key=build_row_priority)[0]
        best["selection_risk_flag"] = "previous_period_used_without_current_candidate"
        best["result_confidence"] = min(float(best.get("result_confidence") or 0.0), 0.3)
        return best
    return sorted(annotated, key=build_row_priority)[0]


def build_priority_reason(row: Dict) -> str:
    """生成择优原因文本。"""
    return (
        f"is_summary={row.get('is_summary')} | "
        f"is_consolidated={row.get('is_consolidated')} | "
        f"is_parent_only={row.get('is_parent_only')} | "
        f"extract_method={row.get('extract_method')} | "
        f"result_confidence={row.get('result_confidence')} | "
        f"locator_confidence={row.get('locator_confidence')} | "
        f"selection_period_role={row.get('selection_period_role')} | "
        f"selection_risk_flag={row.get('selection_risk_flag')} | "
        f"file_id={row.get('file_id')}"
    )


def build_candidate_records(
    target_table: str,
    field_defs: List[Dict],
    candidate_rows: List[Dict],
) -> Tuple[List[Dict], List[Dict], List[str], List[str], Set[Tuple[str, int, str]]]:
    """将中间抽取结果聚合成附件3标准记录，并输出择优审计日志。"""
    field_map = {field["field_code"]: field for field in field_defs}
    grouped_candidates: Dict[Tuple[str, int, str], Dict[str, List[Dict]]] = defaultdict(lambda: defaultdict(list))
    base_record_map: Dict[Tuple[str, int, str], Dict] = {}

    for row in candidate_rows:
        if not is_valid_candidate(row):
            continue
        field_def = field_map.get(row["field_code"])
        if field_def is None:
            continue

        logical_key = build_logical_key_from_meta(row)
        if logical_key is None:
            continue

        parsed_value = parse_value(row["value_text"], field_def["data_type"])
        if parsed_value is None:
            continue

        final_field_name = field_def["final_field_name"]
        if should_skip_final_field_name(final_field_name):
            continue
        candidate = dict(row)
        candidate["parsed_value"] = parsed_value
        candidate["final_field_name"] = final_field_name
        candidate["field_name_cn"] = field_def.get("field_name_cn")
        grouped_candidates[logical_key][final_field_name].append(candidate)
        base_record_map.setdefault(
            logical_key,
            {
                "stock_code": logical_key[0],
                "stock_abbr": normalize_text(row.get("stock_abbr")),
                "company_name": normalize_text(row.get("company_name")),
                "report_year": logical_key[1],
                "report_period": logical_key[2],
            },
        )

    records: List[Dict] = []
    lineage_rows: List[Dict] = []
    validation_logs: List[str] = []
    selection_logs: List[str] = []
    selected_keys: Set[Tuple[str, int, str]] = set()

    sorted_keys = sorted(
        grouped_candidates.keys(),
        key=lambda item: (item[0], item[1], PERIOD_ORDER.get(item[2], 999), item[2]),
    )

    for logical_key in sorted_keys:
        record = dict(base_record_map[logical_key])
        field_candidates = grouped_candidates[logical_key]
        selected_candidates: Dict[str, Dict] = {}
        for field_def in field_defs:
            final_field_name = field_def["final_field_name"]
            candidates = field_candidates.get(final_field_name, [])
            if not candidates:
                continue
            best_candidate = select_final_candidate(target_table, field_def, candidates)
            if best_candidate is None:
                selection_logs.append(
                    " | ".join(
                        [
                            f"target_table={target_table}",
                            f"stock_code={logical_key[0]}",
                            f"report_year={logical_key[1]}",
                            f"report_period={logical_key[2]}",
                            f"field_name={final_field_name}",
                            "decision=skip_previous_period_only_candidate",
                        ]
                    )
                )
                continue
            record[final_field_name] = best_candidate["parsed_value"]
            selected_candidates[final_field_name] = best_candidate
            selection_logs.append(
                " | ".join(
                    [
                        f"target_table={target_table}",
                        f"stock_code={logical_key[0]}",
                        f"report_year={logical_key[1]}",
                        f"report_period={logical_key[2]}",
                        f"field_code={best_candidate['field_code']}",
                        f"source_file_id={best_candidate['file_id']}",
                        f"source_extract_method={best_candidate['extract_method']}",
                        f"source_confidence={best_candidate['result_confidence']}",
                        f"source_target_table={best_candidate['target_table']}",
                        f"selection_period_role={best_candidate.get('selection_period_role')}",
                        f"selection_risk_flag={best_candidate.get('selection_risk_flag')}",
                        f"reason={build_priority_reason(best_candidate)}",
                    ]
                )
            )

        validated_record, rejections = apply_record_validations(target_table, record, selected_candidates)
        records.append(validated_record)
        selected_keys.add(logical_key)
        for final_field_name, candidate in selected_candidates.items():
            final_value = validated_record.get(final_field_name)
            if final_value is None:
                continue
            lineage_rows.append(
                {
                    "file_id": candidate.get("file_id"),
                    "stock_code": logical_key[0],
                    "company_name": normalize_text(candidate.get("company_name")),
                    "report_year": logical_key[1],
                    "report_period": logical_key[2],
                    "final_field": final_field_name,
                    "final_value": final_value,
                    "source_result_id": candidate.get("source_result_id"),
                    "source_page_no": candidate.get("source_page"),
                    "source_text": normalize_text(candidate.get("source_text")),
                    "source_raw_value": normalize_text(candidate.get("value_text")),
                    "extract_method": normalize_text(candidate.get("extract_method")),
                    "extract_status": normalize_text(candidate.get("extract_method")),
                    "confidence": float(candidate.get("result_confidence") or 0.0),
                    "diagnostic_json": {
                        "field_code": candidate.get("field_code"),
                        "field_name_cn": candidate.get("field_name_cn"),
                        "raw_line_name": candidate.get("raw_line_name"),
                        "normalized_line_name": candidate.get("normalized_line_name"),
                        "source_column_role": candidate.get("source_column_role"),
                        "selection_period_role": candidate.get("selection_period_role"),
                        "selection_raw_col_name": candidate.get("selection_raw_col_name"),
                        "selection_risk_flag": candidate.get("selection_risk_flag"),
                        "locator_confidence": candidate.get("locator_confidence"),
                        "is_summary": candidate.get("is_summary"),
                        "is_consolidated": candidate.get("is_consolidated"),
                        "is_parent_only": candidate.get("is_parent_only"),
                        "priority_reason": build_priority_reason(candidate),
                        "extract_extra_info_json": candidate.get("extract_extra_info_json"),
                    },
                }
            )

        if rejections:
            validation_logs.append(
                " | ".join(
                    [
                        f"stock_code={logical_key[0]}",
                        f"report_year={logical_key[1]}",
                        f"report_period={logical_key[2]}",
                        f"target_table={target_table}",
                        f"rejections={';'.join(rejections)}",
                        build_rejection_source_context(rejections, selected_candidates),
                    ]
                )
            )

    return records, lineage_rows, validation_logs, selection_logs, selected_keys


def build_insert_plan(conn, final_table_name: str, field_defs: List[Dict]) -> Tuple[List[str], List[str], Set[str]]:
    """探测目标表真实列，并生成本次实际写入列集合。"""
    actual_columns = fetch_table_columns(conn, final_table_name)
    if not actual_columns:
        raise RuntimeError(f"最终表不存在或不可访问：{final_table_name}")

    missing_required = [column for column in REQUIRED_KEY_COLUMNS if column not in actual_columns]
    if missing_required:
        raise RuntimeError(
            f"最终表缺少必要列：table={final_table_name} | missing_required={','.join(missing_required)}"
        )

    desired_columns = BASE_OPTIONAL_COLUMNS + REQUIRED_KEY_COLUMNS
    for field in field_defs:
        final_field_name = field["final_field_name"]
        if final_field_name not in desired_columns:
            desired_columns.append(final_field_name)

    missing_optional = [column for column in desired_columns if column not in actual_columns and column not in REQUIRED_KEY_COLUMNS]
    insert_columns = [column for column in desired_columns if column in actual_columns]

    safe_print(f"[目标表列] table={final_table_name} | actual_columns={','.join(sorted(actual_columns))}")
    if missing_optional:
        safe_print(f"[缺失可选列] table={final_table_name} | missing_optional={','.join(missing_optional)}")
    safe_print(f"[实际写入列] table={final_table_name} | insert_columns={','.join(insert_columns)}")

    return insert_columns, missing_optional, actual_columns


def fetch_existing_serial_numbers(
    conn,
    final_table_name: str,
    logical_keys: Iterable[Tuple[str, int, str]],
) -> Tuple[Dict[Tuple[str, int, str], int], int]:
    """读取已有序号，并返回当前最大序号。"""
    key_list = sorted(set(logical_keys))
    cur = conn.cursor()
    try:
        cur.execute(f"SELECT COALESCE(MAX(serial_number), 0) FROM {final_table_name}")
        max_serial = int(cur.fetchone()[0] or 0)
        if not key_list:
            return {}, max_serial

        execute_values(
            cur,
            f"""
            SELECT target.stock_code, target.report_year, target.report_period, target.serial_number
            FROM {final_table_name} AS target
            INNER JOIN (VALUES %s) AS scope(stock_code, report_year, report_period)
                ON target.stock_code = scope.stock_code
               AND target.report_year = scope.report_year
               AND target.report_period = scope.report_period
            """,
            key_list,
            template="(%s, %s, %s)",
            page_size=200,
        )
        rows = cur.fetchall()
        serial_map = {(row[0], row[1], row[2]): int(row[3]) for row in rows if row[3] is not None}
        return serial_map, max_serial
    finally:
        cur.close()


def upsert_records(conn, final_table_name: str, insert_columns: List[str], records: List[Dict]) -> int:
    """按附件3标准字段写入最终表。"""
    if not records:
        return 0

    values = [tuple(record.get(column) for column in insert_columns) for record in records]
    update_columns = [column for column in insert_columns if column not in REQUIRED_KEY_COLUMNS]

    if update_columns:
        conflict_action = sql.SQL("DO UPDATE SET {updates}").format(
            updates=sql.SQL(", ").join(
                sql.SQL("{column} = EXCLUDED.{column}").format(column=sql.Identifier(column))
                for column in update_columns
            )
        )
    else:
        conflict_action = sql.SQL("DO NOTHING")

    query = sql.SQL(
        """
        INSERT INTO {table} ({columns})
        VALUES %s
        ON CONFLICT ({conflict_keys})
        {conflict_action}
        """
    ).format(
        table=sql.Identifier(final_table_name),
        columns=sql.SQL(", ").join(sql.Identifier(column) for column in insert_columns),
        conflict_keys=sql.SQL(", ").join(sql.Identifier(column) for column in REQUIRED_KEY_COLUMNS),
        conflict_action=conflict_action,
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


def upsert_final_table_lineage(
    conn,
    run_id: str,
    final_table_name: str,
    lineage_rows: List[Dict],
) -> int:
    """写入最终字段级 lineage，按 run_id 和字段唯一键防重复。"""
    if not lineage_rows:
        return 0

    insert_columns = [
        "run_id",
        "file_id",
        "stock_code",
        "company_name",
        "report_year",
        "report_period",
        "final_table",
        "final_field",
        "final_value",
        "source_table",
        "source_result_id",
        "source_page_no",
        "source_text",
        "source_raw_value",
        "extract_method",
        "extract_status",
        "confidence",
        "diagnostic_json",
    ]
    values = []
    for row in lineage_rows:
        payload = {
            "run_id": run_id,
            "file_id": row.get("file_id"),
            "stock_code": row.get("stock_code"),
            "company_name": row.get("company_name"),
            "report_year": row.get("report_year"),
            "report_period": row.get("report_period"),
            "final_table": final_table_name,
            "final_field": row.get("final_field"),
            "final_value": normalize_text(row.get("final_value")),
            "source_table": LINEAGE_SOURCE_TABLE,
            "source_result_id": row.get("source_result_id"),
            "source_page_no": row.get("source_page_no"),
            "source_text": row.get("source_text"),
            "source_raw_value": row.get("source_raw_value"),
            "extract_method": row.get("extract_method"),
            "extract_status": row.get("extract_status"),
            "confidence": row.get("confidence"),
            "diagnostic_json": json.dumps(row.get("diagnostic_json") or {}, ensure_ascii=False),
        }
        values.append(tuple(payload[column] for column in insert_columns))

    update_columns = [column for column in insert_columns if column != "id"]
    cur = conn.cursor()
    try:
        execute_values(
            cur,
            f"""
            INSERT INTO final_table_lineage ({', '.join(insert_columns)})
            VALUES %s
            ON CONFLICT (
                run_id,
                file_id,
                final_table,
                final_field,
                report_year,
                report_period
            )
            DO UPDATE SET
                stock_code = EXCLUDED.stock_code,
                company_name = EXCLUDED.company_name,
                final_value = EXCLUDED.final_value,
                source_table = EXCLUDED.source_table,
                source_result_id = EXCLUDED.source_result_id,
                source_page_no = EXCLUDED.source_page_no,
                source_text = EXCLUDED.source_text,
                source_raw_value = EXCLUDED.source_raw_value,
                extract_method = EXCLUDED.extract_method,
                extract_status = EXCLUDED.extract_status,
                confidence = EXCLUDED.confidence,
                diagnostic_json = EXCLUDED.diagnostic_json,
                created_at = CURRENT_TIMESTAMP
            """,
            values,
            template="(" + ",".join(["%s"] * len(insert_columns[:-1])) + ", %s::jsonb)",
            page_size=200,
        )
        conn.commit()
        return len(values)
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


def delete_final_rows_by_keys(conn, final_table_name: str, logical_keys: Iterable[Tuple[str, int, str]]) -> int:
    """按逻辑键删除最终表旧记录。"""
    key_list = sorted(set(logical_keys))
    if not key_list:
        return 0

    cur = conn.cursor()
    try:
        execute_values(
            cur,
            f"""
            DELETE FROM {final_table_name} AS target
            USING (VALUES %s) AS stale(stock_code, report_year, report_period)
            WHERE target.stock_code = stale.stock_code
              AND target.report_year = stale.report_year
              AND target.report_period = stale.report_period
            """,
            key_list,
            template="(%s, %s, %s)",
            page_size=200,
        )
        deleted_count = cur.rowcount
        conn.commit()
        return deleted_count
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


def clear_final_table(conn, final_table_name: str) -> int:
    """全量重建时清空目标最终表，避免 serial_number 唯一约束冲突。"""
    cur = conn.cursor()
    try:
        cur.execute(f"DELETE FROM {final_table_name}")
        deleted_count = cur.rowcount
        conn.commit()
        return deleted_count
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


def resequence_serial_numbers(conn, final_table_name: str) -> int:
    """按最终表全量数据重新连续编号 serial_number。"""
    cur = conn.cursor()
    try:
        cur.execute(
            sql.SQL(
                """
                WITH ordered AS (
                    SELECT
                        stock_code,
                        report_year,
                        report_period,
                        ROW_NUMBER() OVER (
                            ORDER BY
                                stock_code,
                                report_year,
                                CASE report_period
                                    WHEN 'Q1' THEN 1
                                    WHEN 'HY' THEN 2
                                    WHEN 'Q3' THEN 3
                                    WHEN 'FY' THEN 4
                                    ELSE 999
                                END,
                                report_period
                        ) AS new_serial_number
                    FROM {table}
                )
                UPDATE {table} AS target
                SET serial_number = ordered.new_serial_number
                FROM ordered
                WHERE target.stock_code = ordered.stock_code
                  AND target.report_year = ordered.report_year
                  AND target.report_period = ordered.report_period
                """
            ).format(table=sql.Identifier(final_table_name))
        )
        updated_count = cur.rowcount
        conn.commit()
        return updated_count
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


def process_target_table(
    conn,
    target_table: str,
    run_id: str,
    scope_file_ids: Optional[List[int]] = None,
    is_full_rebuild: bool = False,
) -> None:
    """处理单个中间目标表并写入对应最终表。"""
    if target_table == "core_performance":
        safe_print(
            "[跳过] target_table=core_performance | "
            "attachment3_extract_result 中可能有 core_performance 抽取结果；"
            "但当前 loader 仅实际刷新 balance_sheet / income_sheet / cash_flow_sheet，"
            "core_performance 最终表是否刷新取决于 loader 当前支持范围。"
        )
        return

    final_table_name = SOURCE_TO_FINAL_TABLE.get(target_table)
    if not final_table_name:
        safe_print(f"[跳过] target_table={target_table} | 原因=未配置最终表映射")
        return

    ensure_extra_final_table_columns(conn, final_table_name)
    field_defs = fetch_field_dict(conn, target_table)
    if not field_defs:
        safe_print(f"[跳过] target_table={target_table} | 原因=attachment3_field_dict 中无字段定义")
        return

    scope_meta = fetch_report_meta(conn, scope_file_ids) if scope_file_ids else {}
    scope_key_map = build_scope_key_map(scope_meta)
    if scope_file_ids:
        safe_print(f"[处理范围] target_table={target_table} | file_ids={','.join(str(file_id) for file_id in scope_file_ids)}")

    candidate_rows = fetch_extract_results(conn, target_table, file_ids=scope_file_ids)
    records, lineage_rows, validation_logs, selection_logs, selected_keys = build_candidate_records(target_table, field_defs, candidate_rows)

    if scope_file_ids:
        stale_keys = set(scope_key_map.keys()) - selected_keys
        deleted_count = delete_final_rows_by_keys(conn, final_table_name, stale_keys)
        safe_print(
            f"[范围清理] target_table={target_table} | final_table={final_table_name} | "
            f"stale_keys={len(stale_keys)} | deleted_rows={deleted_count}"
        )
        for logical_key in sorted(stale_keys):
            file_id_text = ",".join(str(file_id) for file_id in sorted(scope_key_map.get(logical_key, set())))
            safe_print(
                f"[清理旧记录] target_table={target_table} | "
                f"stock_code={logical_key[0]} | report_year={logical_key[1]} | report_period={logical_key[2]} | "
                f"source_file_ids={file_id_text} | reason=当前范围内无候选结果"
            )

    if not records:
        safe_print(f"[跳过] target_table={target_table} | 原因=最终标准记录为空")
        return

    insert_columns, missing_optional, _actual_columns = build_insert_plan(conn, final_table_name, field_defs)
    effective_insert_columns = list(insert_columns)
    if is_full_rebuild:
        deleted_count = clear_final_table(conn, final_table_name)
        safe_print(f"[全量清空] final_table={final_table_name} | deleted_rows={deleted_count}")
    if not is_full_rebuild and "serial_number" in insert_columns:
        logical_keys = [
            (record["stock_code"], record["report_year"], record["report_period"])
            for record in records
        ]
        existing_serial_map, max_serial = fetch_existing_serial_numbers(conn, final_table_name, logical_keys)
        next_serial = max_serial
        for record in records:
            logical_key = (record["stock_code"], record["report_year"], record["report_period"])
            if logical_key in existing_serial_map:
                record["serial_number"] = existing_serial_map[logical_key]
            else:
                next_serial += 1
                record["serial_number"] = next_serial
        safe_print(
            f"[子集更新] final_table={final_table_name} | "
            f"existing_serials={len(existing_serial_map)} | start_new_serial={max_serial + 1}"
        )

    for index, record in enumerate(
        sorted(
            records,
            key=lambda item: (
                item["stock_code"],
                item["report_year"],
                PERIOD_ORDER.get(item["report_period"], 999),
                item["report_period"],
            ),
        ),
        start=1,
    ):
        if is_full_rebuild and "serial_number" in insert_columns:
            record["serial_number"] = index

    upsert_count = upsert_records(conn, final_table_name, effective_insert_columns, records)
    lineage_count = upsert_final_table_lineage(conn, run_id, final_table_name, lineage_rows)

    if is_full_rebuild and "serial_number" in insert_columns:
        resequenced_rows = resequence_serial_numbers(conn, final_table_name)
        safe_print(f"[重排序号] final_table={final_table_name} | resequence_rows={resequenced_rows}")
    else:
        safe_print(f"[跳过重排] final_table={final_table_name} | 原因=当前为子集更新或目标表无 serial_number 列")

    safe_print(
        f"[完成] source_target_table={target_table} | "
        f"final_table={final_table_name} | "
        f"source_rows={len(candidate_rows)} | "
        f"upsert_rows={upsert_count} | "
        f"lineage_rows={lineage_count} | "
        f"validation_rejections={len(validation_logs)} | "
        f"missing_optional_columns={len(missing_optional)}"
    )
    for log_line in selection_logs:
        safe_print(f"[择优] {log_line}")
    for log_line in validation_logs:
        safe_print(f"[拦截] {log_line}")


def main() -> int:
    """主流程。"""
    configure_console()
    args = parse_args()
    run_id = resolve_run_id(args.run_id)
    target_tables = args.target_table or SUPPORTED_TARGET_TABLES
    failed_tables = []

    conn = psycopg2.connect(**DB_CONFIG)
    try:
        ensure_final_table_lineage_schema(conn)
        scope_file_ids = resolve_scope_file_ids(conn, args.file_id, args.limit)
        is_full_rebuild = scope_file_ids is None

        for target_table in target_tables:
            try:
                process_target_table(
                    conn,
                    target_table,
                    run_id=run_id,
                    scope_file_ids=scope_file_ids,
                    is_full_rebuild=is_full_rebuild,
                )
            except Exception as exc:
                conn.rollback()
                safe_print(f"[失败] target_table={target_table} | error={safe_text(exc)}")
                failed_tables.append(target_table)
    finally:
        conn.close()

    if failed_tables:
        safe_print(f"[加载总结] failed_target_tables={','.join(failed_tables)} | failed_count={len(failed_tables)}")
        return 1
    safe_print("[加载总结] failed_target_tables=0 | failed_count=0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
