"""LLM JSON 调用工具。"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from time import perf_counter
from pathlib import Path
from typing import Any, Literal

from agent.utils.stage_trace import record_llm_event


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-flash"
DEFAULT_LLM_TIMEOUT_SECONDS = 60
DEFAULT_LLM_MAX_TOKENS = 2400
LLMProfile = Literal["planner", "sql_generator", "sql_repair", "narrative"]
_PROFILE_ERROR_PREFIX = {"planner": "PLANNER", "sql_generator": "SQL_GENERATION", "sql_repair": "SQL_REPAIR", "narrative": "NARRATIVE"}

_PROFILE_DEFAULTS: dict[LLMProfile, dict[str, Any]] = {
    "planner": {"timeout": 45, "max_tokens": 1000, "thinking": "disabled"},
    "sql_generator": {"timeout": 40, "max_tokens": 1600, "thinking": "disabled"},
    "sql_repair": {"timeout": 30, "max_tokens": 1600, "thinking": "disabled"},
    "narrative": {"timeout": 60, "max_tokens": 1200, "thinking": "disabled"},
}


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


def _positive_int(value: str | None, default: int) -> int:
    try:
        return max(1, int(value)) if value else default
    except ValueError:
        return default


def build_llm(profile: LLMProfile = "planner"):
    """按节点职责创建 LLM，避免所有节点复用同一模型配置。"""
    load_dotenv_if_available()

    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:
        raise RuntimeError("未安装 langchain_openai，无法调用 LLM。") from exc

    defaults = _PROFILE_DEFAULTS[profile]
    prefix = profile.upper()
    model = (
        get_optional_env(f"{prefix}_LLM_MODEL", "AGENT_LLM_MODEL", "OPENAI_MODEL", "DEEPSEEK_MODEL")
        or DEFAULT_DEEPSEEK_MODEL
    )
    api_key = get_required_env(
        "AGENT_LLM_API_KEY",
        "OPENAI_API_KEY",
        "DEEPSEEK_API_KEY",
    )
    base_url = (
        get_optional_env(f"{prefix}_LLM_BASE_URL", "AGENT_LLM_BASE_URL", "OPENAI_BASE_URL", "DEEPSEEK_BASE_URL")
        or DEFAULT_DEEPSEEK_BASE_URL
    )

    kwargs: dict[str, Any] = {
        "model": model,
        "temperature": 0,
        "api_key": api_key,
    }
    if base_url:
        kwargs["base_url"] = base_url
    kwargs["timeout"] = _positive_int(
        get_optional_env(f"{prefix}_LLM_TIMEOUT_SECONDS", "AGENT_LLM_TIMEOUT_SECONDS"),
        defaults["timeout"],
    )
    kwargs["max_tokens"] = max(256, _positive_int(
        get_optional_env(f"{prefix}_LLM_MAX_TOKENS", "AGENT_LLM_MAX_TOKENS"),
        defaults["max_tokens"],
    ))
    thinking = (get_optional_env(f"{prefix}_LLM_THINKING") or defaults["thinking"]).lower()
    if thinking not in {"enabled", "disabled"}:
        raise ValueError(f"{prefix}_LLM_THINKING 只能为 enabled 或 disabled")
    kwargs["extra_body"] = {"thinking": {"type": thinking}}
    if thinking == "enabled":
        kwargs["reasoning_effort"] = (
            get_optional_env(f"{prefix}_LLM_REASONING_EFFORT")
            or defaults.get("reasoning_effort", "high")
        )

    return ChatOpenAI(**kwargs)


def _invoke_with_hard_timeout(prompt: str, profile: LLMProfile) -> dict[str, Any]:
    """以独立进程执行 LLM 调用，确保超时后不会遗留阻塞线程或连接。"""
    if os.getenv("LLM_HARD_TIMEOUT_ENABLED", "1").strip().lower() in {"0", "false", "no"}:
        response = build_llm(profile).invoke(prompt)
        return {
            "ok": True,
            "content": response.content,
            "response_metadata": getattr(response, "response_metadata", {}) or {},
            "usage_metadata": getattr(response, "usage_metadata", None) or {},
        }
    timeout_seconds = _positive_int(
        get_optional_env(f"{profile.upper()}_LLM_TIMEOUT_SECONDS", "AGENT_LLM_TIMEOUT_SECONDS"),
        _PROFILE_DEFAULTS[profile]["timeout"],
    )
    process = subprocess.Popen(
        [sys.executable, "-m", "agent.services.llm_worker"],
        cwd=PROJECT_ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    request_started_at = datetime.now(timezone.utc).isoformat()
    record_llm_event({"event": "llm_request_started", "profile": profile, "pid": process.pid, "request_started_at": request_started_at})
    try:
        stdout, stderr = process.communicate(json.dumps({"profile": profile, "prompt": prompt}, ensure_ascii=False), timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        error = TimeoutError(f"{profile} LLM 调用超过 {timeout_seconds} 秒")
        error.error_code = f"{_PROFILE_ERROR_PREFIX[profile]}_HARD_TIMEOUT"
        error.timeout_scope = "llm_request"
        raise error
    try:
        message = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{profile} LLM 子进程未返回有效结果，退出码：{process.returncode}，错误：{stderr.strip()}") from exc
    if not message.get("ok"):
        error = RuntimeError(f"LLM 子进程调用失败：{message.get('error_type')}: {message.get('error_message')}")
        error.worker_error_type = message.get("error_type")
        raise error
    record_llm_event({"event": "llm_response_received", "profile": profile, "pid": process.pid, "response_received_at": datetime.now(timezone.utc).isoformat(), "finish_reason": message["response_metadata"].get("finish_reason")})
    return message


def invoke_json_prompt(prompt: str, *, profile: LLMProfile = "planner") -> dict[str, Any]:
    started = perf_counter()
    defaults = _PROFILE_DEFAULTS[profile]
    record_llm_event({"event": "request_start", "profile": profile, "max_tokens": defaults["max_tokens"], "thinking_enabled": defaults["thinking"] == "enabled"})
    try:
        response = _invoke_with_hard_timeout(prompt, profile)
    except Exception as exc:
        timeout = isinstance(exc, TimeoutError) or "timeout" in str(exc).lower()
        prefix = _PROFILE_ERROR_PREFIX[profile]
        error_code = getattr(exc, "error_code", None) or (f"{prefix}_TIMEOUT" if timeout else f"{prefix}_CALL_FAILED")
        record_llm_event({"event": "stage_completed", "profile": profile, "duration_ms": round((perf_counter() - started) * 1000, 3), "timeout_type": getattr(exc, "timeout_scope", None), "error_code": error_code, "error_message": str(exc)})
        exc.error_code = error_code
        raise
    metadata = response["response_metadata"]
    finish_reason = metadata.get("finish_reason")
    usage = response["usage_metadata"] or metadata.get("token_usage")
    record_llm_event({"event": "llm_response_parsed", "profile": profile, "response_parsed_at": datetime.now(timezone.utc).isoformat()})
    record_llm_event({"event": "stage_completed", "profile": profile, "duration_ms": round((perf_counter() - started) * 1000, 3), "finish_reason": finish_reason, "token_usage": usage, "timeout_type": None})
    if finish_reason == "length":
        error = RuntimeError(f"{profile} 响应因长度限制被截断。")
        error.error_code = "SQL_GENERATION_TRUNCATED" if profile == "sql_generator" else f"{profile.upper()}_TRUNCATED"
        raise error
    return extract_json(response["content"])


__all__ = [
    "build_llm",
    "DEFAULT_LLM_TIMEOUT_SECONDS",
    "DEFAULT_LLM_MAX_TOKENS",
    "LLMProfile",
    "extract_json",
    "get_optional_env",
    "get_required_env",
    "invoke_json_prompt",
    "load_dotenv_if_available",
]
