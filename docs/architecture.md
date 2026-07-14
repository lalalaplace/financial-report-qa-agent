# 系统架构说明

> 2026-07-14 正式收尾状态：确定性通道与 Flexible SQL V1 的能力边界、执行合同和受控失败路径均已固化。历史六例单轮结果 1/6（`output/dual_channel_e2e/result_20260714_103304.summary.json`）仅用于问题追溯，不再作为 V1 的验收口径。

## 结论

本项目不是简单把用户问题转发给 LLM，再让 LLM 自由生成答案。系统被拆成两条有明确边界的工程链路：

1. PDF 数据提取链路：用可复现的 Python pipeline 把财报 PDF 转成结构化数据库，并记录字段来源、运行日志和质量校验结果。
2. Agent 查询链路：用 LangGraph 把自然语言问题约束为 QueryPlan，再经过公司标准化、指标映射、槽位校验、SQL 模板生成、SQL Guard 和只读执行，最后基于查询结果生成回答。

LLM 在系统中只承担有限职责：理解自然语言、生成结构化计划、判断多轮上下文关系、抽取澄清补丁，以及在确定性主答案之后生成补充洞察。LLM 不直接操作数据库，不直接执行 SQL，不直接决定最终财务数值，也不重新计算同比、差额、排名或派生指标。

## 总体架构

```text
财报 PDF
  -> PDF 文件扫描
  -> 页面文本解析与缓存
  -> 财务报表定位
  -> 报表文本块提取
  -> 字段规则抽取
  -> 最终财务表写入
  -> 字段级 lineage 和一致性校验
  -> PostgreSQL 结构化数据库
  -> LangGraph Agent
  -> QueryPlan
  -> 公司标准化和指标映射
  -> 槽位校验和统一澄清
  -> 固定 SQL 模板生成
  -> SQL Guard
  -> 只读 SQL 执行
  -> 分析节点
  -> 确定性中文主答案
  -> LLM 补充洞察
  -> 最终回答
```

核心目录：

- `scripts/pdf_extraction/`：PDF 提取、清洗、入库主链路。
- `sql/`：数据库表结构和校验表结构。
- `agent/`：LangGraph Agent、QueryPlan、槽位标准化、SQL 生成、分析和回答。
- `db/readonly_executor.py`：Agent 专用只读数据库执行器。
- `data/metric_dictionary.json`：指标字典和派生指标公式配置。

## PDF 数据提取链路

PDF 提取链路的入口是 `scripts/pdf_extraction/run_pipeline.py`，也可以通过 `run_pipeline.bat` 调用。该入口以步骤配置的方式串联多个 Python 脚本，每一步都有明确输入、输出和日志。

当前主流程步骤：

| 步骤 | 脚本 | 职责 |
| --- | --- | --- |
| `scan_reports` | `scan_reports.py` | 扫描 PDF，写入 `report_file_index` |
| `import_company` | `import_company.py` | 导入公司维表和别名表 |
| `import_attachment3_dict` | `import_attachment3_dict.py` | 导入附件 3 字段字典 |
| `parse_pdf_pages` | `parse_pdf_pages.py` | 逐页解析 PDF，生成页面级缓存 |
| `locate_financial_statements` | `locate_financial_statements.py` | 定位三大财务报表页码 |
| `extract_statement_blocks` | `extract_statement_blocks.py` | 提取报表定向文本 JSON |
| `extract_attachment3_rule_based` | `extract_attachment3_rule_based.py` | 基于规则抽取目标字段 |
| `load_attachment3_results_to_sql` | `load_attachment3_results_to_sql.py` | 清洗抽取结果并写入最终财务表 |

这条链路的设计重点是可复现和可排查：

- 每次运行生成 `run_id`，用于关联日志、指标、lineage 和校验结果。
- 支持 `--from-step`、`--to-step`、`--file-id`、`--limit` 等参数，方便断点续跑和局部验证。
- pipeline 汇总写入 `output/runtime/logs/run_summary_<run_id>.md`。
- 运行统计写入 `output/runtime/run_history.csv`，不依赖人工手动维护单项记录。
- PDF 抽取以规则链路为主，不把整份 PDF 交给 LLM 做自由抽取。

## 结构化数据库

数据库分为主数据、文件索引、中间结果、最终财务表、来源追踪和质量校验几类。

### 主数据和文件索引

`sql/02_create_base_tables.sql` 定义了 Agent 和 PDF pipeline 共同依赖的基础表：

- `company_dim`：公司主表，包含 `stock_code`、`stock_abbr`、`company_name`。
- `company_alias`：公司别名表，用于公司标准化。
- `report_file_index`：PDF 文件索引，记录文件路径、公司、年份、报告期和解析状态。
- `report_statement_locator`：三大报表定位结果。

### 最终财务表

`sql/03_create_attachment3_final_tables.sql` 定义三张面向查询的最终标准表：

- `balance_sheet`：资产负债表。
- `income_sheet`：利润表。
- `cash_flow_sheet`：现金流量表。

三张表以 `(stock_code, report_year, report_period)` 作为主键，保留公司名称、股票简称、年份、报告期和标准字段。Agent 查询只面向这些结构化表和公司维表，不直接查询 PDF 或临时文件。

### 来源追踪和质量校验

`final_table_lineage` 记录最终字段的来源：

- 最终表和最终字段：`final_table`、`final_field`。
- 最终值：`final_value`。
- 来源页和来源文本：`source_page_no`、`source_text`、`source_raw_value`。
- 抽取状态和置信度：`extract_method`、`extract_status`、`confidence`。
- 诊断信息：`diagnostic_json`。

`financial_validation_result` 记录财务一致性校验结果，包括校验类型、状态、期望值、实际值、差异值、差异比例和相关字段。

因此，最终回答依赖的是可查询的结构化数据，数据质量问题可以回溯到字段来源和校验记录。

## Agent 执行链路

Agent 的唯一运行入口是 `agent/graph.py` 中的 LangGraph 双通道主图。缺少 `langgraph` 时会显式失败；系统不再回退到旧线性执行器，避免不同部署环境走出不同的业务链路。

## LLM 硬超时与阶段追踪

所有正式 LLM 阶段（上下文路由、QuerySpec 规划、Flexible SQL 生成、SQL Repair、Narrative）均同时使用 SDK 请求超时和独立 worker 进程硬超时。硬超时会终止该次 worker，返回 `*_HARD_TIMEOUT`，不会等待 E2E 外层案例超时。

每个正式图节点写入 `stage_traces`，包含节点起止时间、状态、错误码和 LLM 事件。LLM 事件记录请求 PID、请求开始、响应接收、响应解析和超时范围，因此可区分请求未返回、节点后处理失败和进程生命周期问题。

## 真实验收集

确定性通道固定验收单点、同比、趋势、排名、排名位置与追问六类真实数据库案例；当前结果为 6/6 通过。

Flexible SQL V1 仅正式验收三类能力：多条件同比筛选与排序、两个明确 Top N 的单次交集、已注册公式派生指标的筛选或排序。每类至少 3 个不同问题，每题运行 3 次，总计 `27/27`；SQL 执行成功率、结果基准一致率和语义合同通过率均须为 100%。

嵌套 Top N、任意多阶段集合运算、自由派生公式，以及无法明确来源表和连接关系的跨表查询均不纳入正式支持。验收目标为 100% 返回 `UNSUPPORTED_FLEXIBLE_SQL`、0 条候选 SQL 被执行，而不是要求生成成功。

每个正式支持案例保存 QuerySpec、FlexibleSQLSpec、SemanticSQLContract、最终 SQL、Guard、合同校验、Dry Run、ResultContract、阶段追踪和只读基准 SQL 对比。只有合同通过、SQL 执行成功、股票代码集合与排序均与基准一致，且回答校验通过时，案例才可计为成功。总体红线为静默事实错误 0、错误结果进入回答节点 0。

历史六例基准与超时探测记录保存在 `output/dual_channel_e2e/`，用于定位 LLM 超时和旧链路问题，不再用于证明或否定 V1 的正式验收结果。详细口径见 [Flexible SQL V1 验收边界](flexible_sql_v1_acceptance.md)。

主链路如下：

```text
context_router
  -> merge_context / irrelevant_answer / query_planner / clarification_answer
  -> entity_normalization -> query_spec_validator -> capability_router
     -> deterministic_sql_builder -> sql_guard -> execute_sql
        -> deterministic_result_analyzer -> fixed_answer_renderer
     -> flexible_sql_spec_builder -> llm_sql_generator -> sql_guard -> semantic_validate -> dry_run -> execute_sql
        -> result_contract_builder -> deterministic_table + llm_narrative
        -> answer_assembler -> answer_validator
  -> remember_successful_query_plan
```

关键工程边界：

- `context_router` 只判断本轮输入和上下文的关系。
- `merge_context` 只合并允许的上下文补丁；`query_planner` 生成 `QuerySpec`。
- `entity_normalization` 完成公司与指标标准化，`query_spec_validator` 负责澄清与能力边界校验。
- `capability_router` 在 SQL 生成前显式选择通道：模板可覆盖的问题进入确定性通道；仅 V1 正式支持的集合运算、多条件筛选和已注册派生指标进入受控灵活 SQL 通道；超出结构化数据库能力或 V1 支持边界的问题直接拒答。
- 确定性通道只使用已注册的 SQL 构建器和固定回答渲染器。
- 灵活 SQL 通道先从 QuerySpec 生成不可变 SemanticSQLContract，再向 LLM 提供合同与白名单 schema。候选 SQL 必须通过静态校验、合同校验、试运行；Repair 只能修复 SQL 实现且必须携带原合同，修复后重新执行完整校验。任何不支持结构均返回 `UNSUPPORTED_FLEXIBLE_SQL`，不会进入执行。
- 两条通道都经 SQL Guard 与只读执行器；灵活通道的表格由结果合同确定性生成，LLM 仅补充叙述，校验失败时回退为确定性叙述。

这种拆分让每个节点都有单一职责，也让错误可以落到具体阶段，而不是混在一个大 prompt 里。

## QueryPlan 机制

QueryPlan 是自然语言问题进入执行链路前的结构化合同，定义在 `agent/schemas/query_plan.py`。

核心字段包括：

- `intent_type`：查询意图，例如单指标、趋势、同比、公司对比、排名、排名位置。
- `company_mentions`：用户提到的公司文本。
- `metric_mentions`：用户提到的指标文本。
- `report_period`：报告期，支持 `FY`、`H1`、`Q1`、`Q3`。
- `time_range`：时间范围，支持单年、近 N 年、显式区间和未指定。
- `compare_spec`：公司对比的方向和对象。
- `rank_direction`、`limit`、`change_metric`：排名类查询参数。
- `need_clarification`、`clarification_reason`：规划阶段发现的信息缺口。

`validate_plan()` 会对 LLM 输出做归一化和边界修正：

- 未知 intent 归为 `unknown`。
- 未指定报告期默认补为 `FY`。
- 趋势查询缺省为近 5 年。
- 近 N 年限制在合理范围内。
- 排名参数限制为结构化字段，而不是自由文本。
- 对同比、公司对比、趋势对比等 intent 做基本槽位校验。

因此，LLM 输出不能直接进入数据库执行层，必须先变成受 schema 约束的 QueryPlan。

## 公司标准化

公司标准化由 `agent/tools/company_tools.py` 和 `agent/nodes/slot_nodes.py` 完成。

处理逻辑：

1. 从用户文本或 QueryPlan 的 `company_mentions` 中提取公司简称、全称或股票代码。
2. 查询 `company_dim` 和 `company_alias`。
3. 根据股票代码、精确名称、别名、文本包含关系和短词匹配打分。
4. 返回标准公司对象：`stock_code`、`stock_abbr`、`company_name`。
5. 如果没有候选或候选不唯一，进入统一澄清链路。

Agent 后续 SQL 统一使用标准化后的 `stock_code`，避免把用户输入的公司别名直接拼进查询逻辑。

## 指标映射

指标映射由 `agent/tools/metric_tools.py` 基于 `data/metric_dictionary.json` 完成。

指标字典定义：

- `metric_key`：系统内部指标键。
- `metric_name`：中文指标名。
- `metric_type`：基础指标或派生指标。
- `table`、`field`：基础指标对应的最终财务表和字段。
- `aliases`：中文别名。
- `query_types`：支持的查询类型。
- `formula`：派生指标依赖的分子和分母。
- `scale`、`precision`：派生指标展示规则。

映射时按别名长度优先匹配，支持一个问题命中多个指标。对于“现金流”“利润”这类宽泛表达，会返回候选并触发澄清，而不是强行猜测。

派生指标不会让 LLM 临时编公式，而是从指标字典中读取公式，再由 SQL 节点解析为基础字段查询或计算。

## SQL 模板生成

SQL 不是由 LLM 直接自由生成，而是由固定节点按 intent 生成。路由逻辑在 `agent/routing.py`，SQL 节点位于 `agent/nodes/sql_nodes/`。

典型 SQL 生成节点：

- `generate_point_sql_node`：单年单指标或多指标查询。
- `generate_trend_sql_node`：趋势查询。
- `generate_yoy_sql_node`：同比查询。
- `generate_compare_sql_node`：公司横向对比。
- `generate_compare_trend_sql_node`：公司趋势对比。
- `generate_compare_yoy_sql_node`：公司同比对比。
- `generate_ranking_sql_node`：全市场排名。
- `generate_yoy_ranking_sql_node`：同比增速排名。
- `generate_trend_ranking_sql_node`：区间增长排名。
- `generate_rank_position_sql_node`：指定公司排名位置。
- `generate_derived_*`：派生指标查询、趋势、同比和对比。

SQL 生成只使用已经标准化的公司、指标、年份和报告期。表名和字段来自 `TABLE_ALIASES`、指标字典和固定 SQL 构造函数，不由用户输入直接决定。

排名查询额外在 SQL 生成层做参数防护：

- `limit` 必须存在。
- `limit` 必须在 1 到 50 之间。
- `rank_direction` 只能是 `asc` 或 `desc`。
- 排序增加股票代码作为二级排序，保证结果稳定。

## SQL Guard

SQL Guard 分为 Agent 工具层审查和数据库执行层兜底。

### 工具层审查

`agent/tools/sql_tools.py` 的 `review_sql()` 会检查：

- 禁止多语句。
- 只允许 `SELECT` 或 `WITH`。
- 禁止 `insert`、`update`、`delete`、`drop`、`alter`、`truncate`、`create`、`grant`、`revoke`、`copy`、`execute`、`call` 等关键字。
- 只允许访问白名单表：`company_dim`、`company_alias`、`report_file_index`、`balance_sheet`、`income_sheet`、`cash_flow_sheet`、`core_performance`。
- 只允许白名单函数：`cast`、`count`、`rank`、`round`、`coalesce`、`nullif`。
- 无公司过滤的全表 `ORDER BY` 必须带 `LIMIT`。
- `LIMIT` 不能超过 50。

### 执行层兜底

`db/readonly_executor.py` 再做一次更靠近数据库的保护：

- 空 SQL 拒绝。
- 多语句拒绝。
- 非 `SELECT` / `WITH` 拒绝。
- 写操作和危险关键字拒绝。
- 函数白名单再次校验。
- 所有 SQL 外包一层 `LIMIT`，默认最多 200 行，硬上限 1000 行。
- PostgreSQL 下设置 `statement_timeout`，默认 10000 毫秒。

这意味着即使上游 SQL 节点出现缺陷，执行器仍然不会执行写操作或多语句。

## 只读执行

Agent 的数据库访问集中在 `db/readonly_executor.py`。

执行入口是 `execute_readonly_sql()`：

```text
SQL 字符串
  -> 去除结尾分号
  -> 多语句检查
  -> 只读检查
  -> 函数白名单检查
  -> 包装 LIMIT
  -> 设置 statement_timeout
  -> SQLAlchemy 执行
  -> 返回 columns、rows、row_count、error
```

返回结构是统一的：

- `success`：是否执行成功。
- `columns`：列名。
- `rows`：二维结果数组。
- `row_count`：返回行数。
- `error`：错误信息。

执行失败不会抛到回答层自由处理，而是转换为结构化错误，供后续节点判断。

## 统一澄清出口

系统不会在多个节点各自拼接随意的追问，而是统一走澄清响应节点。

触发澄清的常见情况：

- 公司缺失。
- 公司候选歧义。
- 指标缺失。
- 指标表达歧义。
- 年份缺失。
- 趋势范围不合法。
- 对比公司不足。
- 排名数量缺失或越界。
- intent 不支持。
- 派生指标公式依赖缺失。
- SQL 生成阶段发现参数不完整。

路由上，`should_end_after_plan()`、`should_end_after_slot_check()`、`should_end_after_sql_generation()` 都会优先检查 `need_clarification`。一旦需要澄清，统一进入 `build_clarification_response`，不继续生成或执行 SQL。

澄清状态会保存：

- `pending_query_plan`：待补完的 QueryPlan。
- `pending_empty_fields`：缺失槽位。
- `pending_candidates`：候选项。
- `pending_clarification_type`：澄清类型。

这保证了澄清不是一次性文本提示，而是可以在下一轮继续合并回原 QueryPlan。

## 多轮上下文机制

多轮上下文由 `agent/nodes/context_llm_nodes.py` 实现，分为三类：

1. 新问题：走 `llm_plan_query` 重新生成 QueryPlan。
2. 澄清补答：基于 `pending_query_plan` 抽取 `slot_patch`，再确定性合并。
3. 上下文追问：基于 `last_successful_query_plan` 抽取 `slot_patch`，再确定性合并。

关键状态：

- `pending_query_plan`：上一轮因缺槽位暂停的计划。
- `last_successful_query_plan`：上一轮成功回答后的计划。
- `slot_patch`：本轮用户只补充的局部字段。
- `merged_query_plan`：合并后的新计划。
- `route_type`：上下文路由结果。
- `target_context`：本轮补丁作用的上下文目标。

安全边界：

- patch 只允许修改有限槽位，例如公司、指标、年份、报告期、排名数量。
- 禁止 patch 包含 `sql`、`sql_template`、`table_name`、`column_name`、`where_clause`、`companies`、`metrics` 等执行层字段。
- 合并后仍然调用 `validate_plan()` 和槽位校验。
- 成功回答后才保存 `last_successful_query_plan`。

因此，“那净利润呢”“换成云南白药呢”这类追问不会让 LLM 重写执行链路，只会生成受控的槽位补丁。

## 工程边界和安全证明

这个 Agent 的核心安全性来自分层边界，而不是依赖 prompt 约束。

1. 数据边界明确：回答只能来自 PostgreSQL 中的结构化财务表，不直接读取 PDF 原文生成财务数值。
2. 计划边界明确：自然语言先变成 QueryPlan，QueryPlan 有固定 schema、intent 枚举和字段归一化。
3. 标准化边界明确：公司必须解析到 `company_dim`，指标必须解析到指标字典。
4. 准入边界明确：缺公司、缺指标、缺年份、歧义指标和非法排名参数会先澄清。
5. SQL 边界明确：SQL 由固定节点或受控 Flexible SQL V1 节点生成，不开放任意 SQL 问答；后者必须遵守不可变语义合同。
6. 审查边界明确：执行前有 SQL Guard，检查语句类型、关键字、表白名单、函数白名单和 LIMIT。
7. 执行边界明确：最终数据库入口是只读执行器，拒绝写操作、多语句和危险函数，并设置超时和行数上限。
8. 上下文边界明确：多轮只合并允许的 slot patch，不能注入 SQL 或表字段。
9. 洞察边界明确：LLM 补充解读不参与 SQL、数值计算和成功失败判断，失败或越界时不影响主答案。
10. 可追溯边界明确：PDF pipeline 有 `run_id`、运行日志、run history、lineage 和质量校验表。

所以，LLM 主要是链路中的规划、语言理解和补充表达组件。模板缺失时的受控 LLM SQL 节点只接收结构化 SQL 需求、SemanticSQLContract 和白名单 schema，不接收自然语言原问题；候选 SQL 仍受 SQL Guard、合同校验、试运行和只读数据库执行器约束。

## 输入输出变化

本文档只说明现有系统架构，不改变程序输入输出。

## 数据库影响

本文档只引用现有表结构，不新增、不删除、不修改数据库表。
