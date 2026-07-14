import json
import os
import sys
from datetime import datetime
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
OUTPUT_DIR = PROJECT_ROOT / "output" / "pdf_extraction" / "validation"
KNOWN_OLD_PREFIXES = [
    ]
EXAMPLE_LIMIT = 20


def resolve_report_path(file_path: str) -> Path:
    """把数据库路径转换为可检查的本地路径。"""
    path = Path(file_path)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def is_old_prefix_path(file_path: str) -> bool:
    """判断路径是否命中已知旧目录前缀。"""
    normalized = str(file_path).replace("/", "\\")
    return any(normalized.startswith(prefix) for prefix in KNOWN_OLD_PREFIXES)


def fetch_report_paths(conn) -> List[Dict]:
    """读取报告索引中的 PDF 路径。"""
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


def build_report(rows: List[Dict]) -> Dict:
    """生成路径诊断报告。"""
    existing_examples = []
    missing_examples = []
    existing_count = 0
    missing_count = 0
    old_prefix_count = 0

    for row in rows:
        file_path = str(row.get("file_path") or "")
        resolved_path = resolve_report_path(file_path)
        exists = resolved_path.exists()
        old_prefix = is_old_prefix_path(file_path)

        if exists:
            existing_count += 1
            target_examples = existing_examples
        else:
            missing_count += 1
            target_examples = missing_examples

        if old_prefix:
            old_prefix_count += 1

        if len(target_examples) < EXAMPLE_LIMIT:
            target_examples.append(
                {
                    "file_id": row.get("file_id"),
                    "stock_code": row.get("stock_code"),
                    "company_name": row.get("company_name"),
                    "file_name": row.get("file_name"),
                    "file_path": file_path,
                    "resolved_path": str(resolved_path),
                    "old_prefix": old_prefix,
                }
            )

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "project_root": str(PROJECT_ROOT),
        "total_records": len(rows),
        "existing_path_count": existing_count,
        "missing_path_count": missing_count,
        "old_prefix_count": old_prefix_count,
        "missing_examples": missing_examples,
        "existing_examples": existing_examples,
    }


def main() -> int:
    """命令行入口。"""
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        rows = fetch_report_paths(conn)
    finally:
        conn.close()

    report = build_report(rows)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = OUTPUT_DIR / f"report_path_validation_{timestamp}.json"
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(output_path), **report}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
