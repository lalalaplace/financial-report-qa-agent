"""PDF 抽取流程数据库配置。"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_env_file() -> None:
    """读取本地 .env；已有环境变量优先。"""
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def get_db_config() -> dict[str, object]:
    """返回 psycopg2.connect 可直接使用的连接参数。"""
    load_env_file()
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        parsed = urlparse(database_url)
        return {
            "host": parsed.hostname or "localhost",
            "port": parsed.port or 5432,
            "dbname": parsed.path.lstrip("/"),
            "user": parsed.username,
            "password": parsed.password,
        }

    required = {
        "host": os.getenv("DB_HOST"),
        "port": int(os.getenv("DB_PORT", "5432")),
        "dbname": os.getenv("DB_NAME"),
        "user": os.getenv("DB_USER"),
        "password": os.getenv("DB_PASSWORD"),
    }
    missing = [key for key, value in required.items() if value in (None, "")]
    if missing:
        raise RuntimeError(f"缺少数据库环境变量：{', '.join(missing)}")
    return required


def get_project_root() -> Path:
    """返回项目根目录。"""
    return PROJECT_ROOT


def get_output_root() -> Path:
    """返回运行产物目录。"""
    return Path(os.getenv("OUTPUT_ROOT", str(PROJECT_ROOT / "output"))).resolve()


def get_report_root() -> Path:
    """返回本地 PDF 输入目录。"""
    return Path(os.getenv("REPORT_ROOT", str(PROJECT_ROOT / "input" / "reports"))).resolve()
