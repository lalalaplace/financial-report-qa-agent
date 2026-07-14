import argparse
import os
import hashlib
import json
from pathlib import Path
from typing import Dict, List, Optional

import fitz
import psycopg2

from statement_table_schema import compact_text, normalize_text


DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "teddy_b",
    "user": "postgres",
    "password": os.environ["DB_PASSWORD"],
}

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PAGE_ARTIFACT_ROOT = PROJECT_ROOT / "output" / "pdf_extraction" / "page_artifacts"
LOG_DIR = PROJECT_ROOT / "output" / "runtime" / "logs"
ARTIFACT_VERSION = "pdf_page_artifact_v1"
HASH_CHUNK_SIZE = 1024 * 1024


def calculate_file_hash(path: Path) -> str:
    """计算文件 SHA256，用于识别大小和 mtime 未变化但内容变化的情况。"""
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(HASH_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_pdf_path(file_path: str) -> Path:
    """将数据库中的路径转换为本地绝对路径。"""
    path = Path(file_path)
    if path.is_absolute():
        return path
    return (PROJECT_ROOT / path).resolve()


def build_file_artifact_dir(file_id: int) -> Path:
    """生成单个 PDF 的页面缓存目录。"""
    return PAGE_ARTIFACT_ROOT / f"file_{file_id}"


def build_page_artifact_path(file_id: int, page_no: int) -> Path:
    """生成单页缓存路径。"""
    return build_file_artifact_dir(file_id) / f"page_{page_no}.json"


def build_manifest_path(file_id: int) -> Path:
    """生成页面缓存清单路径。"""
    return build_file_artifact_dir(file_id) / "manifest.json"


def build_pdf_signature(pdf_path: Path) -> Dict:
    """生成用于判断缓存是否过期的 PDF 签名。"""
    stat = pdf_path.stat()
    return {
        "pdf_path": str(pdf_path),
        "pdf_mtime": stat.st_mtime,
        "pdf_size": stat.st_size,
        "file_hash": calculate_file_hash(pdf_path),
        "artifact_version": ARTIFACT_VERSION,
        "parser_version": ARTIFACT_VERSION,
    }


def load_manifest(file_id: int) -> Optional[Dict]:
    """读取缓存清单。"""
    manifest_path = build_manifest_path(file_id)
    if not manifest_path.exists():
        return None
    try:
        with manifest_path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except Exception:
        return None


def manifest_matches_pdf(manifest: Optional[Dict], pdf_signature: Dict) -> bool:
    """判断缓存清单是否仍对应当前 PDF。"""
    if not manifest:
        return False
    return (
        manifest.get("artifact_version") == pdf_signature["artifact_version"]
        and manifest.get("parser_version", manifest.get("artifact_version")) == pdf_signature["parser_version"]
        and manifest.get("pdf_path") == pdf_signature["pdf_path"]
        and manifest.get("pdf_size") == pdf_signature["pdf_size"]
        and float(manifest.get("pdf_mtime") or 0) == float(pdf_signature["pdf_mtime"])
        and manifest.get("file_hash") == pdf_signature["file_hash"]
    )


def parse_pdf_pages(file_id: int, file_path: str) -> List[Dict]:
    """逐页解析 PDF 文本并返回页面缓存结构。"""
    pdf_path = resolve_pdf_path(file_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF 文件不存在：{pdf_path}")

    pages: List[Dict] = []
    with fitz.open(pdf_path) as doc:
        for index, page in enumerate(doc):
            page_no = index + 1
            text = normalize_text(page.get_text("text"))
            lines = [normalize_text(line) for line in text.splitlines() if normalize_text(line)]
            rect = page.rect
            pages.append(
                {
                    "artifact_version": ARTIFACT_VERSION,
                    "file_id": file_id,
                    "page_no": page_no,
                    "page_num": page_no,
                    "text_content": text,
                    "text": text,
                    "compact_text": compact_text(text),
                    "lines": lines,
                    "text_blocks": [],
                    "table_candidates": [],
                    "page_width": float(rect.width),
                    "page_height": float(rect.height),
                    "has_text_layer": bool(text.strip()),
                    "parse_method": "fitz_text",
                    "parse_status": "parsed" if text.strip() else "empty_text",
                }
            )
    return pages


def write_page_artifacts(file_id: int, file_path: str, pages: List[Dict]) -> Path:
    """写出页面缓存和清单。"""
    pdf_path = resolve_pdf_path(file_path)
    artifact_dir = build_file_artifact_dir(file_id)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    for page in pages:
        page_no = int(page["page_no"])
        with build_page_artifact_path(file_id, page_no).open("w", encoding="utf-8", newline="\n") as file:
            json.dump(page, file, ensure_ascii=False, indent=2)

    manifest = {
        **build_pdf_signature(pdf_path),
        "file_id": file_id,
        "page_count": len(pages),
        "artifact_dir": str(artifact_dir),
    }
    with build_manifest_path(file_id).open("w", encoding="utf-8", newline="\n") as file:
        json.dump(manifest, file, ensure_ascii=False, indent=2)
    return artifact_dir


def load_page_artifacts(file_id: int, file_path: str) -> Optional[List[Dict]]:
    """读取仍有效的页面缓存。"""
    pdf_path = resolve_pdf_path(file_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF 文件不存在：{pdf_path}")

    manifest = load_manifest(file_id)
    if not manifest_matches_pdf(manifest, build_pdf_signature(pdf_path)):
        return None

    page_count = int(manifest.get("page_count") or 0)
    pages: List[Dict] = []
    for page_no in range(1, page_count + 1):
        page_path = build_page_artifact_path(file_id, page_no)
        if not page_path.exists():
            return None
        try:
            with page_path.open("r", encoding="utf-8") as file:
                page = json.load(file)
        except Exception:
            return None
        text = normalize_text(page.get("text") or page.get("text_content") or "")
        lines = [normalize_text(line) for line in page.get("lines", []) if normalize_text(line)]
        if not lines and text:
            lines = [normalize_text(line) for line in text.splitlines() if normalize_text(line)]
        page["text"] = text
        page["text_content"] = text
        page["compact_text"] = page.get("compact_text") or compact_text(text)
        page["lines"] = lines
        page["page_num"] = int(page.get("page_num") or page.get("page_no") or page_no)
        page["page_no"] = int(page.get("page_no") or page["page_num"])
        pages.append(page)
    return pages


def load_or_parse_pdf_pages(file_id: int, file_path: str, force: bool = False) -> List[Dict]:
    """优先读取页面缓存，缓存不存在或过期时重新解析 PDF。"""
    if not force:
        cached_pages = load_page_artifacts(file_id, file_path)
        if cached_pages is not None:
            return cached_pages

    pages = parse_pdf_pages(file_id, file_path)
    write_page_artifacts(file_id, file_path, pages)
    return pages


def get_page_cache_state(file_id: int, file_path: str) -> Dict:
    """返回页面缓存当前状态，供运行指标统计使用。"""
    pdf_path = resolve_pdf_path(file_path)
    signature = build_pdf_signature(pdf_path)
    manifest = load_manifest(file_id)
    if not manifest:
        return {"status": "miss", "reason": "manifest_missing", "page_count": 0}
    if not manifest_matches_pdf(manifest, signature):
        reason = "signature_mismatch"
        if manifest.get("file_hash") != signature["file_hash"]:
            reason = "file_hash_changed"
        elif manifest.get("pdf_size") != signature["pdf_size"]:
            reason = "pdf_size_changed"
        elif float(manifest.get("pdf_mtime") or 0) != float(signature["pdf_mtime"]):
            reason = "pdf_mtime_changed"
        elif manifest.get("parser_version", manifest.get("artifact_version")) != signature["parser_version"]:
            reason = "parser_version_changed"
        return {"status": "stale", "reason": reason, "page_count": int(manifest.get("page_count") or 0)}

    page_count = int(manifest.get("page_count") or 0)
    for page_no in range(1, page_count + 1):
        page_path = build_page_artifact_path(file_id, page_no)
        if not page_path.exists():
            return {"status": "stale", "reason": "page_json_missing", "page_count": page_count}
        try:
            with page_path.open("r", encoding="utf-8") as file:
                json.load(file)
        except Exception:
            return {"status": "stale", "reason": "page_json_damaged", "page_count": page_count}
    return {"status": "hit", "reason": "cache_valid", "page_count": page_count}


def write_page_cache_metrics(run_id: str, metrics: Dict) -> Path:
    """写出页面缓存阶段指标，供 pipeline 汇总合并。"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = LOG_DIR / f"page_cache_metrics_{run_id}.json"
    with path.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(metrics, file, ensure_ascii=False, indent=2)
    return path


def fetch_target_files(conn, file_ids: Optional[List[int]] = None, limit: Optional[int] = None) -> List[Dict]:
    """读取待解析文件。"""
    cur = conn.cursor()
    where_parts = ["COALESCE(parse_status, 'pending') IN ('pending', 'parsed')"]
    params: List = []
    if file_ids:
        where_parts.append("file_id = ANY(%s)")
        params.append(file_ids)

    limit_sql = ""
    if limit is not None:
        limit_sql = "LIMIT %s"
        params.append(limit)

    cur.execute(
        f"""
        SELECT file_id, file_name, file_path
        FROM report_file_index
        WHERE {' AND '.join(where_parts)}
        ORDER BY file_id
        {limit_sql}
        """,
        params,
    )
    rows = cur.fetchall()
    cur.close()
    return [{"file_id": row[0], "file_name": row[1], "file_path": row[2]} for row in rows]


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description="逐页解析 PDF 并生成页面级缓存。")
    parser.add_argument("--file-id", type=int, nargs="*", help="仅处理指定 file_id，可传多个。")
    parser.add_argument("--limit", type=int, help="限制处理文件数量。")
    parser.add_argument("--force", action="store_true", help="强制重新解析并覆盖页面缓存。")
    parser.add_argument("--run-id", help="本轮 pipeline run_id，用于写出页面缓存指标。")
    return parser.parse_args()


def main() -> int:
    """命令行入口。"""
    args = parse_args()
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        files = fetch_target_files(conn, file_ids=args.file_id, limit=args.limit)
    finally:
        conn.close()

    print(f"待解析文件数：{len(files)}")
    success_count = 0
    fail_count = 0
    cache_hit_count = 0
    cache_miss_count = 0
    cache_stale_count = 0
    force_parse_count = 0
    parsed_page_count = 0
    reused_page_count = 0
    reason_summary: Dict[str, int] = {}

    for file_meta in files:
        try:
            file_id = int(file_meta["file_id"])
            cache_state = get_page_cache_state(file_id, file_meta["file_path"])
            if args.force:
                force_parse_count += 1
            elif cache_state["status"] == "hit":
                cache_hit_count += 1
                reused_page_count += int(cache_state.get("page_count") or 0)
            elif cache_state["status"] == "stale":
                cache_stale_count += 1
            else:
                cache_miss_count += 1
            reason = cache_state.get("reason") or "unknown"
            reason_summary[reason] = reason_summary.get(reason, 0) + 1

            pages = load_or_parse_pdf_pages(
                file_id=file_id,
                file_path=file_meta["file_path"],
                force=args.force,
            )
            if args.force or cache_state["status"] != "hit":
                parsed_page_count += len(pages)
            success_count += 1
            print(
                f"[页面解析] file_id={file_meta['file_id']} | file_name={file_meta['file_name']} | "
                f"cache_status={cache_state['status']} | cache_reason={cache_state['reason']} | "
                f"pages={len(pages)} | output={build_file_artifact_dir(file_id)}"
            )
        except Exception as error:
            fail_count += 1
            print(f"[失败] file_id={file_meta['file_id']} | file_name={file_meta['file_name']} | error={error}")

    print(f"处理完成：成功 {success_count} 个，失败 {fail_count} 个。")
    if args.run_id:
        metrics_path = write_page_cache_metrics(
            args.run_id,
            {
                "run_id": args.run_id,
                "total_files": len(files),
                "success_count": success_count,
                "failed_count": fail_count,
                "cache_hit_count": cache_hit_count,
                "cache_miss_count": cache_miss_count,
                "cache_stale_count": cache_stale_count,
                "force_parse_count": force_parse_count,
                "parsed_page_count": parsed_page_count,
                "reused_page_count": reused_page_count,
                "reason_summary": reason_summary,
            },
        )
        print(f"[页面缓存指标] path={metrics_path}")
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())


