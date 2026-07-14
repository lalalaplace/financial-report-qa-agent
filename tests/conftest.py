"""测试环境不创建真实 LLM 子进程；硬超时行为由专门测试覆盖。"""

import pytest


@pytest.fixture(autouse=True)
def _disable_llm_hard_timeout_in_unit_tests(monkeypatch):
    monkeypatch.setenv("LLM_HARD_TIMEOUT_ENABLED", "0")
