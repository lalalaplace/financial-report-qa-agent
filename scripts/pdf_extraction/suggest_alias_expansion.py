import argparse
import os
import json
import re
import sys
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, List, Set

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
STATEMENT_JSON_DIR = PROJECT_ROOT / "output" / "pdf_extraction" / "statement_json"

TARGET_FIELDS = {
    "balance_sheet.equity_total_equity": {
        "final_table": "balance_sheet",
        "statement_type": "balance_sheet",
        "aliases": [
            "所有者权益合计",
            "股东权益合计",
            "所有者权益（或股东权益）合计",
            "股东权益总计",
            "权益合计",
            "所有者权益总计",
        ],
        "keywords": ["所有者权益", "股东权益", "权益", "合计", "总计"],
    },
    "balance_sheet.liability_and_equity_total": {
        "final_table": "balance_sheet",
        "statement_type": "balance_sheet",
        "aliases": [
            "负债和所有者权益总计",
            "负债及所有者权益总计",
            "负债和股东权益总计",
            "负债及股东权益总计",
            "负债和权益总计",
            "负债及权益总计",
            "负债和所有者权益（或股东权益）总计",
        ],
        "keywords": ["负债", "所有者权益", "股东权益", "权益", "总计"],
    },
    "income.total_operating_revenue": {
        "final_table": "income_sheet",
        "statement_type": "income",
        "aliases": [
            "营业收入",
            "营业总收入",
            "一、营业收入",
            "一、营业总收入",
        ],
        "keywords": ["营业收入", "营业总收入"],
    },
}


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description="基于 statement_json 生成关键字段别名扩展建议。")
    parser.add_argument("--run-id", required=True, help="需要分析的 run_id。")
    return parser.parse_args()


def normalize_text(value) -> str:
    """标准化行名文本。"""
    if value is None:
        return ""
    text = str(value)
    text = text.replace("\u3000", " ").replace("\xa0", " ")
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[：:;；,，.。()（）【】\\[\\]一二三四五六七八九十、]+", "", text)
    text = re.sub(r"\d+", "", text)
    return text.strip()


def field_name(field_code: str) -> str:
    """从 field_code 提取最终字段名。"""
    return field_code.split(".", 1)[1]


def fetch_run_file_ids(conn, run_id: str, final_table: str) -> List[int]:
    """读取本轮指定最终表覆盖的 file_id。"""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT DISTINCT file_id
        FROM final_table_lineage
        WHERE run_id = %s AND final_table = %s
        ORDER BY file_id
        """,
        (run_id, final_table),
    )
    rows = [int(row[0]) for row in cur.fetchall()]
    cur.close()
    return rows


def fetch_candidate_file_ids(conn, field_code: str, file_ids: List[int]) -> Set[int]:
    """读取已有候选的 file_id。"""
    if not file_ids:
        return set()
    statement_type = field_code.split(".", 1)[0]
    cur = conn.cursor()
    cur.execute(
        """
        SELECT DISTINCT file_id
        FROM attachment3_extract_result
        WHERE target_table = %s
          AND field_code = %s
          AND file_id = ANY(%s)
          AND COALESCE(value_text, '') <> ''
        """,
        (statement_type, field_code, file_ids),
    )
    rows = {int(row[0]) for row in cur.fetchall()}
    cur.close()
    return rows


def fetch_used_row_names(conn, statement_type: str, file_ids: List[int]) -> Dict[int, Set[str]]:
    """读取已被抽取结果使用的行名，用于识别未匹配行。"""
    result: Dict[int, Set[str]] = defaultdict(set)
    if not file_ids:
        return result
    cur = conn.cursor()
    cur.execute(
        """
        SELECT file_id, raw_line_name, normalized_line_name
        FROM attachment3_extract_result
        WHERE target_table = %s
          AND file_id = ANY(%s)
          AND COALESCE(value_text, '') <> ''
        """,
        (statement_type, file_ids),
    )
    for file_id, raw_line_name, normalized_line_name in cur.fetchall():
        for value in (raw_line_name, normalized_line_name):
            normalized = normalize_text(value)
            if normalized:
                result[int(file_id)].add(normalized)
    cur.close()
    return result


def score_row(row_name: str, raw_line_text: str, aliases: List[str], keywords: List[str]) -> float:
    """计算 statement_json 行与目标字段的相关性分数。"""
    normalized_row = normalize_text(row_name)
    normalized_line = normalize_text(raw_line_text)
    combined = normalized_row + normalized_line
    if not combined:
        return 0.0
    alias_scores = []
    for alias in aliases:
        normalized_alias = normalize_text(alias)
        if not normalized_alias:
            continue
        if normalized_alias in combined:
            alias_scores.append(1.0)
        else:
            alias_scores.append(SequenceMatcher(None, normalized_alias, normalized_row).ratio())
    keyword_hits = sum(1 for keyword in keywords if normalize_text(keyword) in combined)
    keyword_score = keyword_hits / max(len(keywords), 1)
    return round(max(max(alias_scores or [0.0]), keyword_score), 6)


def iter_statement_rows(file_id: int, statement_type: str) -> List[Dict]:
    """读取 statement_json 行。"""
    path = STATEMENT_JSON_DIR / f"file_{file_id}_{statement_type}.json"
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = payload.get("rows") or []
    return rows if isinstance(rows, list) else []


def build_field_suggestion(conn, run_id: str, field_code: str, config: Dict) -> Dict:
    """生成单个字段的别名建议。"""
    final_table = config["final_table"]
    statement_type = config["statement_type"]
    run_file_ids = fetch_run_file_ids(conn, run_id, final_table)
    candidate_file_ids = fetch_candidate_file_ids(conn, field_code, run_file_ids)
    no_candidate_file_ids = [file_id for file_id in run_file_ids if file_id not in candidate_file_ids]
    used_rows = fetch_used_row_names(conn, statement_type, no_candidate_file_ids)
    row_counter = Counter()
    examples: Dict[str, List[Dict]] = defaultdict(list)
    score_by_row: Dict[str, float] = {}

    for file_id in no_candidate_file_ids:
        used_names = used_rows.get(file_id, set())
        for row in iter_statement_rows(file_id, statement_type):
            raw_name = row.get("raw_item_name") or row.get("raw_line_text") or ""
            normalized_name = row.get("normalized_item_name") or raw_name
            if normalize_text(raw_name) in used_names or normalize_text(normalized_name) in used_names:
                continue
            score = score_row(normalized_name, row.get("raw_line_text") or raw_name, config["aliases"], config["keywords"])
            if score < 0.55:
                continue
            display_name = str(raw_name).strip() or str(normalized_name).strip()
            row_counter[display_name] += 1
            score_by_row[display_name] = max(score_by_row.get(display_name, 0.0), score)
            if len(examples[display_name]) < 5:
                examples[display_name].append(
                    {
                        "file_id": file_id,
                        "source_page": row.get("source_page"),
                        "raw_line_text": row.get("raw_line_text"),
                        "normalized_item_name": normalized_name,
                        "score": score,
                    }
                )

    observed = []
    for row_name, count in row_counter.most_common(30):
        observed.append(
            {
                "raw_row_name": row_name,
                "count": count,
                "score": score_by_row.get(row_name),
                "examples": examples[row_name],
            }
        )

    return {
        "field_code": field_code,
        "final_field": field_name(field_code),
        "statement_type": statement_type,
        "run_file_count": len(run_file_ids),
        "candidate_file_count": len(candidate_file_ids),
        "no_candidate_file_count": len(no_candidate_file_ids),
        "baseline_suggested_aliases": config["aliases"],
        "observed_unmatched_row_suggestions": observed,
        "suggested_next_action": "review_alias_candidates_before_rule_update",
    }


def build_report(conn, run_id: str) -> Dict:
    """生成别名扩展建议报告。"""
    fields = {
        field_code: build_field_suggestion(conn, run_id, field_code, config)
        for field_code, config in TARGET_FIELDS.items()
    }
    return {
        "run_id": run_id,
        "fields": fields,
        "note": "本报告只基于 statement_json 未匹配行名生成建议，不自动修改别名或抽取规则。",
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
    output_path = OUTPUT_DIR / f"alias_expansion_suggestions_{args.run_id}.json"
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"run_id": args.run_id, "output": str(output_path)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
