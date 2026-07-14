import argparse
import os
import json
import sys
from pathlib import Path
from typing import Dict, List

import psycopg2


DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "teddy_b",
    "user": "postgres",
    "password": os.environ["DB_PASSWORD"],
}

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_LIMIT = 20


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description="修复 report_file_index 中的旧目录路径。")
    parser.add_argument("--old-prefix", required=True, help="需要替换的旧路径前缀。")
    parser.add_argument("--new-prefix", required=True, help="替换后的新路径前缀。")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="只预览，不更新数据库。")
    mode.add_argument("--apply", action="store_true", help="确认更新数据库。")
    return parser.parse_args()


def normalize_prefix(value: str) -> str:
    """统一路径前缀分隔符，避免 Windows 斜杠差异。"""
    return str(value).rstrip("\\/").replace("/", "\\")


def replace_prefix(file_path: str, old_prefix: str, new_prefix: str) -> str:
    """替换路径前缀。"""
    normalized_path = str(file_path).replace("/", "\\")
    if not normalized_path.startswith(old_prefix):
        return file_path
    suffix = normalized_path[len(old_prefix):].lstrip("\\/")
    return str(Path(new_prefix) / suffix)


def fetch_all_rows(conn) -> List[Dict]:
    """读取全部报告路径记录。"""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT file_id, stock_code, company_name, file_name, file_path
        FROM report_file_index
        ORDER BY file_id
        """
    )
    columns = [item[0] for item in cur.description]
    rows = [dict(zip(columns, row)) for row in cur.fetchall()]
    cur.close()
    return rows


def fetch_matching_rows(conn, old_prefix: str) -> List[Dict]:
    """读取命中旧路径前缀的记录。"""
    all_rows = fetch_all_rows(conn)
    rows = []
    for item in all_rows:
        normalized_path = str(item.get("file_path") or "").replace("/", "\\")
        if normalized_path.startswith(old_prefix):
            rows.append(item)
    return rows


def choose_repaired_path(
    old_path: str,
    old_prefix: str,
    new_prefix: str,
    used_paths: set,
) -> Dict:
    """选择不违反唯一约束的修复路径。"""
    new_path = replace_prefix(old_path, old_prefix, new_prefix)
    normalized_new_path = new_path.replace("/", "\\")
    if normalized_new_path not in used_paths:
        used_paths.add(normalized_new_path)
        return {"new_path": new_path, "path_mode": "absolute_replaced", "conflict": False}

    try:
        relative_path = str(Path(new_path).resolve().relative_to(PROJECT_ROOT.resolve()))
    except ValueError:
        relative_path = new_path
    normalized_relative_path = relative_path.replace("/", "\\")
    if normalized_relative_path not in used_paths:
        used_paths.add(normalized_relative_path)
        return {"new_path": relative_path, "path_mode": "project_relative_fallback", "conflict": True}

    used_paths.add(normalized_new_path)
    return {"new_path": new_path, "path_mode": "unresolved_conflict", "conflict": True}


def build_preview(rows: List[Dict], all_rows: List[Dict], old_prefix: str, new_prefix: str) -> Dict:
    """生成修复预览。"""
    examples = []
    existing_after_replace_count = 0
    conflict_count = 0
    relative_fallback_count = 0
    used_paths = {
        str(row.get("file_path") or "").replace("/", "\\")
        for row in all_rows
        if row not in rows
    }
    for row in rows:
        old_path = str(row.get("file_path") or "")
        repaired = choose_repaired_path(old_path, old_prefix, new_prefix, used_paths)
        new_path = repaired["new_path"]
        resolved_path = Path(new_path)
        if not resolved_path.is_absolute():
            resolved_path = PROJECT_ROOT / resolved_path
        if resolved_path.exists():
            existing_after_replace_count += 1
        if repaired["conflict"]:
            conflict_count += 1
        if repaired["path_mode"] == "project_relative_fallback":
            relative_fallback_count += 1
        if len(examples) < EXAMPLE_LIMIT:
            examples.append(
                {
                    "file_id": row.get("file_id"),
                    "stock_code": row.get("stock_code"),
                    "company_name": row.get("company_name"),
                    "file_name": row.get("file_name"),
                    "old_path": old_path,
                    "new_path": new_path,
                    "path_mode": repaired["path_mode"],
                    "new_path_exists": resolved_path.exists(),
                }
            )

    return {
        "project_root": str(PROJECT_ROOT),
        "matched_count": len(rows),
        "existing_after_replace_count": existing_after_replace_count,
        "conflict_count": conflict_count,
        "relative_fallback_count": relative_fallback_count,
        "examples": examples,
    }


def apply_updates(conn, rows: List[Dict], all_rows: List[Dict], old_prefix: str, new_prefix: str) -> int:
    """执行路径更新。"""
    cur = conn.cursor()
    updated_count = 0
    used_paths = {
        str(row.get("file_path") or "").replace("/", "\\")
        for row in all_rows
        if row not in rows
    }
    for row in rows:
        repaired = choose_repaired_path(str(row.get("file_path") or ""), old_prefix, new_prefix, used_paths)
        new_path = repaired["new_path"]
        cur.execute(
            """
            UPDATE report_file_index
            SET file_path = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE file_id = %s
            """,
            (new_path, row["file_id"]),
        )
        updated_count += cur.rowcount
    conn.commit()
    cur.close()
    return updated_count


def main() -> int:
    """命令行入口。"""
    args = parse_args()
    old_prefix = normalize_prefix(args.old_prefix)
    new_prefix = normalize_prefix(args.new_prefix)

    conn = psycopg2.connect(**DB_CONFIG)
    try:
        all_rows = fetch_all_rows(conn)
        rows = fetch_matching_rows(conn, old_prefix)
        preview = build_preview(rows, all_rows, old_prefix, new_prefix)
        payload = {
            "mode": "apply" if args.apply else "dry_run",
            "old_prefix": old_prefix,
            "new_prefix": new_prefix,
            **preview,
        }
        if args.apply:
            payload["updated_count"] = apply_updates(conn, rows, all_rows, old_prefix, new_prefix)
    finally:
        conn.close()

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
