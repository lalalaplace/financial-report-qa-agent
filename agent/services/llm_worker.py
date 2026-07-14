"""独立 LLM 调用进程入口，供硬超时包装器终止。"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

from agent.services.llm_json_service import build_llm


def main() -> int:
    try:
        request = json.loads(sys.stdin.read())
        profile = request["profile"]
        response = build_llm(profile).invoke(request["prompt"])
        payload: dict[str, Any] = {
            "ok": True,
            "content": response.content,
            "response_metadata": getattr(response, "response_metadata", {}) or {},
            "usage_metadata": getattr(response, "usage_metadata", None) or {},
        }
    except BaseException as exc:
        payload = {"ok": False, "error_type": type(exc).__name__, "error_message": str(exc)}
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, default=str))
    sys.stdout.flush()
    # SDK 可能保留非 daemon 的 HTTP 后台资源；结果写出后不再等待其自然回收。
    os._exit(0)


if __name__ == "__main__":
    raise SystemExit(main())
