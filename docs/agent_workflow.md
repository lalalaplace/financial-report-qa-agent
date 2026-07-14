# Agent 执行链路说明

## 当前 V1.2 双通道主图

```text
用户问题
  -> context_router
  -> QueryPlan / QuerySpec
  -> 实体与指标标准化
  -> capability_router
     ├─ 确定性 SQL -> SQL Guard -> 执行 -> 固定答案
     └─ Flexible SQL Spec -> LLM SQL -> Guard / 语义校验 / Dry Run -> 执行 -> 结果合同
  -> 受控摘要与答案校验
```

## 关键边界

- 已注册的单指标、趋势、同比、对比和排名问题使用确定性 SQL。
- Flexible SQL 只能处理已定义的受支持结构，语义合同固定指标来源、公式、筛选、排序和时间范围。
- 所有 SQL 必须通过只读限制、表字段白名单和执行前检查；不支持结构返回 `UNSUPPORTED_FLEXIBLE_SQL`，不会执行候选 SQL。
- `pending_query_plan` 与 `last_successful_query_plan` 分离保存，避免澄清或失败轮次污染后续追问。

## 验证与追踪

每个图节点写入 `stage_traces`，记录节点状态、耗时和错误码。离线回归测试执行方式为：

```bash
python -m pytest tests -q
```

历史节点说明和 V0.x 链路仅用于追溯，见 [历史工作流说明](history/agent_workflow_legacy.md)。
