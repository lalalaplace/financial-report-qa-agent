"""LLM JSON 调用工具。"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_dotenv_if_available() -> None:
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return

    try:
        from dotenv import load_dotenv
    except ImportError:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            stripped_line = line.strip()
            if not stripped_line or stripped_line.startswith("#") or "=" not in stripped_line:
                continue
            key, value = stripped_line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
        return

    load_dotenv(env_path)


def get_required_env(*names: str) -> str:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    raise RuntimeError(f"未配置环境变量：{' 或 '.join(names)}")


def get_optional_env(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None


def extract_json(text: str) -> dict[str, Any]:
    """从 LLM 文本响应中提取 JSON 对象。"""
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if match:
        try:
            parsed = json.loads(match.group(1))
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

    raise ValueError(f"无法从 LLM 响应中提取 JSON：{text[:200]}")


def build_llm():
    load_dotenv_if_available()

    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:
        raise RuntimeError("未安装 langchain_openai，无法调用 LLM。") from exc

    model = get_required_env("AGENT_LLM_MODEL", "OPENAI_MODEL", "DEEPSEEK_MODEL")
    api_key = get_required_env(
        "AGENT_LLM_API_KEY",
        "OPENAI_API_KEY",
        "DEEPSEEK_API_KEY",
    )
    base_url = get_optional_env("AGENT_LLM_BASE_URL", "OPENAI_BASE_URL", "DEEPSEEK_BASE_URL")

    kwargs: dict[str, Any] = {
        "model": model,
        "temperature": 0,
        "api_key": api_key,
    }
    if base_url:
        kwargs["base_url"] = base_url

    return ChatOpenAI(**kwargs)


def invoke_json_prompt(prompt: str) -> dict[str, Any]:
    response = build_llm().invoke(prompt)
    return extract_json(response.content)


__all__ = [
    "build_llm",
    "extract_json",
    "get_optional_env",
    "get_required_env",
    "invoke_json_prompt",
    "load_dotenv_if_available",
]

