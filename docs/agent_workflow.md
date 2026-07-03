# Agent 执行链路说明

## 结论

当前 Agent 是一条受控的 LangGraph 执行链路，不是“自然语言直接转 SQL”的自由问答系统。

核心原则：

- LLM 只输出 `QueryPlan`、`route`、`slot_patch` 或结果补充洞察。
- LLM 不直接写 SQL。
- LLM 不修改查询结果，不重新计算财务数值。
- SQL 不由自然语言自由生成。
- 不允许文本转 SQL fallback。
- 不支持的意图、缺失槽位或歧义输入必须进入澄清或拒答链路。

## 当前 Graph 链路

```text
user_question
  -> context_router
  -> llm_plan_query / clarification_patch / followup_patch
  -> merge_clarification_patch / merge_followup_patch
  -> resolve_company
  -> map_metric
  -> check_slots
  -> route_by_intent
  -> generate_sql
  -> review_and_execute_sql
  -> analyze
  -> generate_answer
  -> llm_insight
  -> assemble_final_answer
  -> remember_successful_query_plan
```

## 节点说明

### user_question

`user_question`：负责承载用户本轮输入；不负责保存执行结果，不负责决定查询意图。

### context_router

`context_router`：负责判断本轮输入是新问题、澄清补答、上下文追问、歧义输入还是无关输入；不负责生成 QueryPlan，不负责生成 SQL。

输出只允许是上下文路由结果，例如 `route_type` 和 `target_context`。

### llm_plan_query

`llm_plan_query`：负责把新问题解析成结构化 `QueryPlan`；不负责公司标准化，不负责指标标准化，不负责生成 SQL。

LLM 在这里只能输出受 schema 约束的 QueryPlan，包括 intent、公司提及、指标提及、时间范围、报告期、对比参数、排名参数和澄清标记。

### clarification_patch

`clarification_patch`：负责从用户的澄清补答中抽取 `slot_patch`；不负责重写完整 QueryPlan，不负责执行查询。

该节点只面向上一轮 `pending_query_plan`，用于补齐缺失槽位。

### followup_patch

`followup_patch`：负责从上下文追问中抽取 `slot_patch`；不负责重新解释全部历史对话，不负责生成 SQL。

该节点只面向上一轮成功保存的 `last_successful_query_plan`，用于处理“那净利润呢”“换成云南白药呢”这类局部变更。

### merge_clarification_patch

`merge_clarification_patch`：负责把澄清补答的 `slot_patch` 确定性合并回 `pending_query_plan`；不负责调用 LLM，不负责跳过后续校验。

合并后仍需继续走公司标准化、指标映射和槽位校验。

### merge_followup_patch

`merge_followup_patch`：负责把追问的 `slot_patch` 确定性合并回 `last_successful_query_plan`；不负责直接复用上一轮 SQL。

合并后会形成新的查询计划，并重新进入标准执行链路。

### resolve_company

`resolve_company`：负责把公司提及解析为标准公司对象，例如 `stock_code`、`stock_abbr`、`company_name`；不负责猜测公司，不负责生成 SQL。

如果公司缺失、无法解析或存在多个候选，进入澄清链路。

### map_metric

`map_metric`：负责把指标提及映射到指标字典中的标准指标；不负责临时创造指标，不负责临时编写派生公式。

基础指标必须映射到固定表字段，派生指标必须来自指标字典中的公式定义。

### check_slots

`check_slots`：负责按 intent 校验必要槽位是否齐全；不负责补猜缺失信息，不负责绕过不支持场景。

它检查公司、指标、年份、报告期、对比公司数量、排名方向、排名数量等执行前条件。

### route_by_intent

`route_by_intent`：负责根据 `intent_type` 和指标类型选择 SQL 生成节点；不负责生成 SQL，不负责执行 SQL。

典型路由包括：

- `single_metric_query`、`multi_metric_query` -> `generate_point_sql`
- `trend_query` -> `generate_trend_sql` 或 `generate_derived_trend_sql`
- `yoy_query` -> `generate_yoy_sql` 或 `generate_derived_yoy_sql`
- `company_compare_query` -> `generate_compare_sql` 或 `generate_derived_compare_sql`
- `ranking_query` -> `generate_ranking_sql`
- `rank_position_query` -> `generate_rank_position_sql`

未知或不支持的 intent 不会进入文本转 SQL fallback。

### generate_sql

`generate_sql`：负责由固定 SQL 节点生成对应查询 SQL；不负责理解自然语言，不负责接受用户自由 SQL。

这里的 `generate_sql` 是一组固定节点，包括：

- `generate_point_sql`
- `generate_trend_sql`
- `generate_yoy_sql`
- `generate_derived_sql`
- `generate_compare_sql`
- `generate_compare_trend_sql`
- `generate_compare_yoy_sql`
- `generate_ranking_sql`
- `generate_yoy_ranking_sql`
- `generate_trend_ranking_sql`
- `generate_rank_position_sql`
- 对应的 `generate_derived_*` 节点

SQL 只能由标准化后的公司、指标、年份、报告期和固定模板生成，不能由 LLM 根据自然语言自由拼接。

### review_and_execute_sql

`review_and_execute_sql`：负责分发 SQL family、执行 SQL Guard、调用只读执行器；不负责修改业务意图，不负责放行未审查 SQL。

执行前必须经过安全审查。审查失败时返回结构化错误，不进入数据库执行。

### analyze

`analyze`：负责把 SQL 查询结果整理成业务分析结构；不负责重新查询数据库，不负责编造缺失数值。

不同 intent 会进入不同分析节点，例如趋势分析、同比分析、公司对比分析、排名分析、派生指标分析。

### generate_answer

`generate_answer`：负责把查询结果和分析结果组织成中文回答；不负责决定 SQL，不负责补写数据库不存在的数据。

回答必须基于已有查询结果、分析结构和错误状态生成。

### llm_insight

`llm_insight`：负责在确定性主答案之后生成补充洞察；不负责 QueryPlan、公司标准化、指标映射、SQL 生成、数值计算或成功失败判断。

该节点只读取 `query_result`、`analysis_result` 和主答案，输出 `llm_analysis`、`llm_analysis_success`、`llm_analysis_error`。如果 LLM 失败、输出为空或内容越界，主答案照常返回。

### assemble_final_answer

`assemble_final_answer`：负责把主答案和有效补充洞察拼接为最终答案；不负责重新分析数据。

### remember_successful_query_plan

`remember_successful_query_plan`：负责在成功回答后保存 `last_successful_query_plan`；不负责保存失败计划，不负责保存仍需澄清的计划。

该状态用于下一轮上下文追问。

## LLM 的职责边界

LLM 只出现在四类受控位置：

| 节点 | LLM 输出 | 用途 |
| --- | --- | --- |
| `context_router` | `route_type`、`target_context` | 判断本轮输入和上下文关系 |
| `llm_plan_query` | `QueryPlan` | 把新问题转成结构化计划 |
| `clarification_patch` / `followup_patch` | `slot_patch` | 补齐或修改有限槽位 |
| `llm_insight` | `llm_analysis` | 在主答案之后补充解释边界、趋势形态或样本口径 |

LLM 不允许输出以下执行层内容：

- SQL。
- 表名。
- 字段名。
- where 条件。
- SQL 模板。
- 已标准化公司对象。
- 已标准化指标对象。
- 数据库执行结果。
- 重新计算后的同比、差额、排名、均值等数值。
- 外部新闻、公告、行业背景、经营原因或投资建议。

这些内容只能由确定性工具、字典映射、SQL 节点和数据库执行器产生。

## SQL 生成边界

SQL 生成遵循固定路线：

```text
QueryPlan
  -> 公司标准化
  -> 指标映射
  -> 槽位校验
  -> intent 路由
  -> 固定 SQL 节点
  -> SQL Guard
  -> 只读执行
```

不允许以下路径：

```text
自然语言 -> LLM -> SQL
自然语言 -> 文本转 SQL fallback
用户输入 -> SQL 片段拼接
未知 intent -> 尝试生成通用 SQL
槽位缺失 -> 猜测后执行 SQL
```

如果 intent 不在已注册范围内，或者缺少执行必要槽位，系统必须进入 `build_clarification_response` 或 `generate_unsupported_answer`。

## 澄清和拒答边界

以下情况不会继续执行 SQL：

- 公司缺失或无法唯一解析。
- 指标缺失或指标表达歧义。
- 年份缺失。
- 趋势范围不合法。
- 对比公司数量不足。
- 排名数量缺失或越界。
- 指标类型与 intent 不兼容。
- intent 未注册或不支持。
- SQL 生成节点发现参数异常。
- SQL Guard 未通过。

这些情况统一进入澄清、拒答或结构化错误输出，不会触发通用文本转 SQL 兜底。

## 多轮上下文边界

多轮上下文只允许通过 `slot_patch` 修改有限字段。

允许修改的方向包括：

- 公司。
- 指标。
- 年份。
- 时间范围。
- 报告期。
- 排名数量。
- 排名方向。

不允许通过多轮上下文注入：

- SQL。
- 表名。
- 字段名。
- where 条件。
- 执行结果。
- 任意数据库操作。

因此，多轮追问只是复用上一次成功 QueryPlan 的结构，再局部替换槽位，而不是让 LLM 根据对话历史自由生成查询。

## 总结

当前 Agent 的执行链路是一个受控状态机：

- LLM 负责理解和结构化。
- 工具负责标准化公司和指标。
- validator 负责准入校验。
- router 负责选择固定 SQL 节点。
- SQL 节点负责生成受控 SQL。
- SQL Guard 和只读执行器负责安全执行。
- analyze 和 answer 节点负责基于结果组织回答。
- llm_insight 节点只在成功查询后补充解释边界，不影响主查询结果。

这条链路的关键点是：不存在自然语言到 SQL 的自由 fallback，也不存在 LLM 直接写 SQL 的执行路径。
