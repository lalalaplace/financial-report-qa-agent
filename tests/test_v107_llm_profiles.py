"""节点级 LLM 配置回归测试。"""

from __future__ import annotations

import sys
from types import ModuleType

import pytest

from agent.services import llm_json_service


@pytest.fixture(autouse=True)
def mock_llm_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_LLM_API_KEY", "test-api-key")


def test_sql_generator_profile_explicitly_disables_thinking(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    module = ModuleType("langchain_openai")
    module.ChatOpenAI = FakeChatOpenAI
    monkeypatch.setitem(sys.modules, "langchain_openai", module)
    monkeypatch.setenv("SQL_GENERATOR_LLM_THINKING", "disabled")
    monkeypatch.setenv("SQL_GENERATOR_LLM_MAX_TOKENS", "1337")

    llm_json_service.build_llm("sql_generator")

    assert captured["extra_body"] == {"thinking": {"type": "disabled"}}
    assert captured["max_tokens"] == 1337
    assert "reasoning_effort" not in captured


def test_planner_profile_can_enable_thinking(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    module = ModuleType("langchain_openai")
    module.ChatOpenAI = FakeChatOpenAI
    monkeypatch.setitem(sys.modules, "langchain_openai", module)
    monkeypatch.setenv("PLANNER_LLM_THINKING", "enabled")

    llm_json_service.build_llm("planner")

    assert captured["extra_body"] == {"thinking": {"type": "enabled"}}
    assert captured["reasoning_effort"] == "high"


def test_sql_generator_uses_independent_default_timeout(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    module = ModuleType("langchain_openai")
    module.ChatOpenAI = FakeChatOpenAI
    monkeypatch.setitem(sys.modules, "langchain_openai", module)
    monkeypatch.delenv("SQL_GENERATOR_LLM_TIMEOUT_SECONDS", raising=False)

    llm_json_service.build_llm("sql_generator")

    assert captured["timeout"] == 40


def test_narrative_uses_sixty_second_default_timeout(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    module = ModuleType("langchain_openai")
    module.ChatOpenAI = FakeChatOpenAI
    monkeypatch.setitem(sys.modules, "langchain_openai", module)
    monkeypatch.delenv("NARRATIVE_LLM_TIMEOUT_SECONDS", raising=False)

    llm_json_service.build_llm("narrative")

    assert captured["timeout"] == 60


def test_sql_generator_length_response_is_rejected(monkeypatch) -> None:
    class FakeResponse:
        content = '{"sql": "SELECT 1"}'
        response_metadata = {"finish_reason": "length"}

    class FakeLLM:
        def invoke(self, _prompt):
            return FakeResponse()

    monkeypatch.setattr(llm_json_service, "build_llm", lambda _profile: FakeLLM())
    monkeypatch.setenv("LLM_HARD_TIMEOUT_ENABLED", "0")

    with pytest.raises(RuntimeError) as error:
        llm_json_service.invoke_json_prompt("test", profile="sql_generator")

    assert getattr(error.value, "error_code") == "SQL_GENERATION_TRUNCATED"


def test_hard_timeout_terminates_llm_worker(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeProcess:
        pid = 12345

        def __init__(self, *_args, **_kwargs):
            captured["process"] = self

        def communicate(self, *_args, **_kwargs):
            if not captured.get("killed"):
                raise llm_json_service.subprocess.TimeoutExpired("llm_worker", 1)
            return "", ""

        def kill(self):
            captured["killed"] = True

    monkeypatch.setenv("LLM_HARD_TIMEOUT_ENABLED", "1")
    monkeypatch.setattr(llm_json_service.subprocess, "Popen", FakeProcess)
    monkeypatch.setenv("SQL_GENERATOR_LLM_TIMEOUT_SECONDS", "1")

    with pytest.raises(TimeoutError) as error:
        llm_json_service.invoke_json_prompt("test", profile="sql_generator")

    assert getattr(error.value, "error_code") == "SQL_GENERATION_HARD_TIMEOUT"
    assert captured["killed"] is True
