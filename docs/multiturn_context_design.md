# 多轮上下文设计总结

## 结论

多轮上下文设计解决的是财报问数 Agent 的多轮上下文问题：用户不必每一轮都重复公司、指标、年份和报告期，系统可以识别“补答”和“追问”，并把用户本轮输入合并回已有 QueryPlan。

但这套设计不是让 LLM 接管执行链路。它只允许 LLM 做三件事：

- 判断当前输入属于哪类上下文。
- 从补答或追问中抽取 `slot_patch`。
- 在意图切换但信息不足时提出澄清。

合并后的计划仍然必须重新走公司标准化、指标映射、槽位校验、SQL 生成、SQL Guard 和只读执行。

## 解决的问题

早期单轮链路中，Agent 更接近单轮查询：每次用户都需要说清楚公司、指标、年份等信息。遇到“那净利润呢”“换成五粮液呢”“2023 年的呢”这类追问时，系统很难判断应该继承哪些上下文。

多轮上下文重点解决三类问题：

1. 澄清补答
   上一轮因为缺公司、缺指标、缺年份等信息被暂停，用户下一轮只回答“贵州茅台”或“净利润”，系统能把补答合并回待完成的 QueryPlan。

2. 上下文追问
   上一轮成功查询后，用户下一轮说“那净利润呢”“换成五粮液呢”“前 20 呢”，系统能继承上一轮的 QueryPlan，并只替换本轮明确修改的槽位。

3. 意图切换但信息不足
   用户从一个成功查询追问“那排名呢”“那对比呢”时，系统能识别这不是简单换指标，而是可能发生 intent 切换；如果缺少排名方向、排名数量、对比公司等必要信息，则继续澄清，不直接执行。

## clarification_answer 是什么

`clarification_answer` 表示当前用户输入是在回答上一轮澄清问题。

典型场景：

```text
用户：2024 年营业收入是多少？
Agent：请明确要查询的公司。
用户：贵州茅台
```

第三行“贵州茅台”不是一个完整新问题，而是对上一轮缺失公司槽位的补答。系统会把它路由为：

```json
{
  "route_type": "clarification_answer",
  "target_context": "pending_query_plan"
}
```

后续 `clarification_patch` 只从这句话里抽取 `slot_patch`，例如：

```json
{
  "company_mentions": ["贵州茅台"]
}
```

它不生成 SQL，也不重写完整 QueryPlan。

## contextual_followup 是什么

`contextual_followup` 表示当前用户输入依赖上一轮成功查询才能理解。

典型场景：

```text
用户：贵州茅台 2024 年营业收入是多少？
Agent：……
用户：那净利润呢？
```

“那净利润呢？”本身缺公司和年份，但结合上一轮成功 QueryPlan 可以理解为：

```text
贵州茅台 2024 年净利润是多少？
```

系统会把它路由为：

```json
{
  "route_type": "contextual_followup",
  "target_context": "last_successful_query_plan"
}
```

后续 `followup_patch` 只抽取本轮变化，例如：

```json
{
  "metric_mentions": ["净利润"]
}
```

## intent_transition_need_clarification 是什么

`intent_transition_need_clarification` 是对多轮上下文中一类重要场景的总结名称：上下文追问触发了意图切换，但缺少新意图执行所需的关键槽位。

当前实现中，它不是一个独立的代码常量，而是表现为：

```json
{
  "patch_status": "need_clarification",
  "route_type": "contextual_followup",
  "need_clarification": true
}
```

典型场景：

```text
用户：贵州茅台 2024 年营业收入是多少？
Agent：……
用户：那排名呢？
```

“那排名呢？”可能表示从 `single_metric_query` 切换到 `ranking_query`，但它没有说明：

- 排名前几。
- 排名方向是最高还是最低。
- 是否仍使用营业收入。
- 是否仍使用 2024 年。

此时系统不能强行猜测，也不能直接执行 SQL。正确行为是保存一个新的 `pending_query_plan`，并继续澄清排名参数。

## pending_query_plan 的作用

`pending_query_plan` 是“已经有初步 QueryPlan，但因为缺槽位暂时不能执行”的计划快照。

它主要用于澄清补答：

```text
第一次输入 -> 生成 QueryPlan -> 缺槽位 -> 保存 pending_query_plan
第二次输入 -> clarification_answer -> 抽取 slot_patch -> 合并回 pending_query_plan
```

它保存的是计划层信息，不保存 SQL 执行结果。常见来源包括：

- `llm_plan_query` 发现信息不足。
- `check_slots` 发现公司、指标、年份等槽位缺失。
- `followup_patch` 发现上下文追问发生意图切换但缺少必要参数。

只要存在 `pending_query_plan`，用户后续的简短回答就可以被判断为 `clarification_answer`。

## clarification_context 的作用

`clarification_context` 用来告诉系统“当前到底缺什么、允许补什么”。

它通常包含：

- 缺失字段，例如 `companies`、`metrics`、`report_year`、`ranking_limit`。
- 候选项，例如公司候选或指标候选。
- 澄清类型，例如缺参数、公司歧义、指标歧义。
- 当前待补完的 QueryPlan 摘要。

它的核心作用是限制 `slot_patch` 的权限。

例如当前只缺公司，用户补答只允许写入 `company_mentions`；不能借补答写入 SQL、表名、字段名，也不能随意覆盖已经明确的指标和年份。

## last_successful_query_plan 的作用

`last_successful_query_plan` 是上一轮成功回答后保存的 QueryPlan。

它只在满足以下条件时保存：

- `business_success` 为 true。
- 当前不需要澄清。
- 没有错误类型。
- 当前存在有效 `query_plan`。

它用于支撑上下文追问：

```text
上一轮成功 QueryPlan:
公司=贵州茅台，指标=营业收入，年份=2024，报告期=FY

用户追问:
那净利润呢？

slot_patch:
指标=净利润
```

合并后，新 QueryPlan 继承公司、年份、报告期，只替换指标。

失败查询、拒答、澄清状态不会覆盖 `last_successful_query_plan`，避免错误上下文污染后续对话。

## slot_patch 如何合并

`slot_patch` 是用户本轮明确补充或修改的局部槽位。

合并规则由 `agent/services/query_plan_merge_service.py` 控制，核心原则是：

- 只允许合并白名单字段。
- 澄清补答只能补当前缺失字段。
- 上下文追问只能改有限字段。
- 合并后清空旧 SQL、旧查询结果、旧分析结果和旧回答。
- 合并后调用 `validate_plan()` 重新归一化 QueryPlan。

常见合并方式：

| slot_patch 字段 | 合并目标 |
| --- | --- |
| `company_mentions` | 合并或替换 QueryPlan 中的公司提及 |
| `metric_mentions` | 合并或替换 QueryPlan 中的指标提及 |
| `report_year` | 更新 `time_range.report_year` |
| `start_year`、`end_year` | 更新时间范围 |
| `report_period` | 更新报告期 |
| `ranking_limit`、`limit` | 更新排名数量 |
| `rank_direction` | 更新排名方向 |

对于 `rank_position_query`，公司和指标续问是单槽位替换语义，避免把旧公司或旧指标错误追加到新问题中。

## 为什么合并后仍要重新标准化和 SQL Guard

合并后的 QueryPlan 只是一个新的计划，不是可直接执行的结果。

必须重新标准化和审查，原因有四点：

1. 公司提及可能变化
   “换成五粮液呢？”合并后必须重新走 `resolve_company`，把“五粮液”解析成标准 `stock_code`。

2. 指标提及可能变化
   “那净利润呢？”合并后必须重新走 `map_metric`，把“净利润”映射到指标字典中的标准字段。

3. 槽位合法性可能变化
   “那排名呢？”可能改变 intent 或执行要求，必须重新走 `check_slots`，不能继承上一轮的通过状态。

4. SQL 不能复用
   旧 SQL、旧查询结果、旧回答都会在合并后清空。新 SQL 必须由固定 SQL 节点重新生成，并再次通过 SQL Guard。

这能防止两个风险：

- 把上一轮 SQL 或结果错误复用到新问题。
- 让用户通过多轮补丁绕过公司标准化、指标映射或 SQL 安全审查。

## 典型多轮案例

### 案例 1：缺公司后的澄清补答

```text
用户：2024 年营业收入是多少？
Agent：请明确要查询的公司。
用户：贵州茅台
```

执行过程：

```text
第一次：生成 pending_query_plan，empty_fields 包含 companies
第二次：context_router -> clarification_answer
clarification_patch -> {"company_mentions": ["贵州茅台"]}
merge_clarification_patch -> 合并 QueryPlan
重新 resolve_company -> map_metric -> check_slots -> SQL Guard -> 执行
```

### 案例 2：成功查询后的换指标追问

```text
用户：贵州茅台 2024 年营业收入是多少？
Agent：……
用户：那净利润呢？
```

执行过程：

```text
remember_successful_query_plan 保存上一轮 QueryPlan
context_router -> contextual_followup
followup_patch -> {"metric_mentions": ["净利润"]}
merge_followup_patch -> 合并 QueryPlan
重新 map_metric，重新生成 SQL，重新 SQL Guard
```

### 案例 3：成功查询后的换公司追问

```text
用户：贵州茅台 2024 年营业收入是多少？
Agent：……
用户：换成五粮液呢？
```

执行过程：

```text
context_router -> contextual_followup
followup_patch -> {"company_mentions": ["五粮液"]}
merge_followup_patch -> 合并 QueryPlan
重新 resolve_company，不能复用贵州茅台的 stock_code
```

### 案例 4：成功排名后的换排名数量

```text
用户：2024 年营业收入排名前 10 的公司是谁？
Agent：……
用户：前 20 呢？
```

执行过程：

```text
context_router -> contextual_followup
followup_patch -> {"limit": 20}
merge_followup_patch -> 更新 QueryPlan.limit
重新 check_slots，重新生成 ranking SQL，重新 SQL Guard
```

### 案例 5：追问触发意图切换但缺参数

```text
用户：贵州茅台 2024 年营业收入是多少？
Agent：……
用户：那排名呢？
```

执行过程：

```text
context_router -> contextual_followup
followup_patch -> patch_status=need_clarification
保存新的 pending_query_plan
不进入 SQL 执行
继续询问排名方向或排名数量
```

这就是本文档中的 `intent_transition_need_clarification`。

## 当前边界

多轮上下文有明确边界：

- 只支持围绕财务问数的上下文补答和追问。
- 不支持跨很长历史对话自由检索，只使用当前状态中的 `pending_query_plan` 和 `last_successful_query_plan`。
- 不支持用户通过追问注入 SQL、表名、字段名或 where 条件。
- 不支持把无关输入强行合并到上一轮查询。
- 完整新问题必须走 `new_query`，不能因为存在上下文就强行续问。
- 没有 `pending_query_plan` 时不能走 `clarification_answer`。
- 没有 `last_successful_query_plan` 时不能走 `contextual_followup`。
- 意图切换但缺参数时必须澄清，不能猜测执行。
- 合并后的 QueryPlan 不复用旧 SQL、旧结果、旧回答。
- 多轮上下文只负责计划层合并，不改变 SQL Guard 和只读执行边界。

## 总结

多轮上下文的核心设计是把多轮上下文从“自然语言记忆”变成“QueryPlan + slot_patch 的确定性合并”。

它让 Agent 可以自然处理补答和追问，但仍然保持工程边界：

- LLM 只判断 route 和抽取 slot_patch。
- `pending_query_plan` 承接未完成查询。
- `last_successful_query_plan` 承接成功查询的续问。
- `clarification_context` 限制补丁权限。
- 合并后重新走完整执行链路。
- SQL Guard 和只读执行始终生效。
