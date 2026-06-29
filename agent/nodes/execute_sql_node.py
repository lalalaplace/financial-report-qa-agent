"""SQL 执行入口节点：按 state 中 SQL family 分发到 execute_sql_handlers。"""

from __future__ import annotations

from agent.state import AgentState
from agent.nodes.execute_sql_handlers import (
    _invoke_execute_financial_sql,
    handle_yoy_sqls,
    handle_derived_sqls,
    handle_derived_trend_sqls,
    handle_derived_yoy_sqls,
    handle_compare_trend_sqls,
    handle_compare_yoy_sqls,
    handle_derived_compare_yoy_sqls,
    handle_derived_compare_trend_sqls,
    handle_compare_sqls,
    handle_derived_compare_sqls,
    handle_single_sql,
)


def review_and_execute_sql_node(state: AgentState) -> dict:
    if state.get("need_clarification"):
        return {}

    # 1. yoy 跨表多 SQL 合并
    yoy_sqls = state.get("yoy_sqls")
    if yoy_sqls:
        return handle_yoy_sqls(yoy_sqls)

    # 2. 派生指标多 SQL 逐条存储
    derived_sqls = state.get("derived_sqls")
    if derived_sqls:
        return handle_derived_sqls(derived_sqls)

    # 3. 派生指标趋势
    derived_trend_sqls = state.get("derived_trend_sqls")
    if derived_trend_sqls:
        return handle_derived_trend_sqls(derived_trend_sqls)

    # 4. 派生指标同比
    derived_yoy_sqls = state.get("derived_yoy_sqls")
    if derived_yoy_sqls:
        return handle_derived_yoy_sqls(derived_yoy_sqls)

    # 5. base 公司趋势对比
    compare_trend_sqls = state.get("compare_trend_sqls")
    if compare_trend_sqls:
        return handle_compare_trend_sqls(compare_trend_sqls)

    # 6. base 公司同比对比
    compare_yoy_sqls = state.get("compare_yoy_sqls")
    if compare_yoy_sqls:
        return handle_compare_yoy_sqls(compare_yoy_sqls)

    # 7. derived 公司同比对比
    derived_compare_yoy_sqls = state.get("derived_compare_yoy_sqls")
    if derived_compare_yoy_sqls:
        return handle_derived_compare_yoy_sqls(derived_compare_yoy_sqls)

    # 8. derived 公司趋势对比
    derived_compare_trend_sqls = state.get("derived_compare_trend_sqls")
    if derived_compare_trend_sqls:
        return handle_derived_compare_trend_sqls(derived_compare_trend_sqls)

    # 9. base 多公司对比
    compare_sqls = state.get("compare_sqls")
    if compare_sqls:
        return handle_compare_sqls(compare_sqls)

    # 10. derived 多公司对比
    derived_compare_sqls = state.get("derived_compare_sqls")
    if derived_compare_sqls:
        return handle_derived_compare_sqls(derived_compare_sqls)

    # 11. 单 SQL
    return handle_single_sql(state.get("sql"))


__all__ = ["_invoke_execute_financial_sql", "review_and_execute_sql_node"]
