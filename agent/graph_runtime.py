"""正式主图运行时支持。"""

from __future__ import annotations

from typing import Any

from agent.state import AgentState
from agent.utils.logger import log_agent_run


class SimpleCompiledGraph:
    """旧线性执行器的兼容占位符，不提供可运行路径。"""

    def invoke(self, state: AgentState) -> AgentState:
        raise RuntimeError("SimpleCompiledGraph 已废弃：请安装 langgraph 并使用双通道主图。")


class LoggedCompiledGraph:
    """装饰 LangGraph compiled graph，增加运行日志记录。"""

    def __init__(self, compiled_graph: Any) -> None:
        self.compiled_graph = compiled_graph

    def invoke(self, state: AgentState) -> AgentState:
        result = self.compiled_graph.invoke(state)
        log_agent_run(result)
        return result
