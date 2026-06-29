# 财报 PDF 数据提取总结

## 结论

PDF 抽取模块负责将非结构化财报转换为可查询的结构化财务数据库，是后续问数 Agent 的数据底座。

它提供的不是一批临时解析文本，而是一套可复用的数据基础：

- 公司、年份、报告期明确的财报文件索引。
- 标准化后的三大财务报表数据。
- 可被 Agent 直接查询的结构化财务表。
- 字段级来源追踪和质量校验结果。
- 支撑公司查询、指标查询、趋势、同比、对比、排名和派生指标计算的数据口径。

Agent 后续回答依赖这些结构化表，而不是直接读取 PDF 或让 LLM 临时解释整份年报。

## 数据来源

数据来源是本地财报 PDF 文件，默认放在：

```text
input/reports/
```

这些 PDF 通常来自上市公司定期报告，包含年度报告、半年度报告、一季报、三季报等。PDF 原文属于非结构化或半结构化材料，适合人工阅读，但不适合直接做稳定查询。

抽取模块会从文件名、文件路径和 PDF 内容中识别基础元数据：

- 股票代码。
- 公司简称。
- 公司全称。
- 报告年份。
- 报告期。
- 报告文件路径。
- 财报解析状态。

这些信息先进入 `report_file_index`，形成后续抽取、校验和 Agent 查询的文件级索引。

## PDF 解析流程

PDF 解析流程以 Python pipeline 为主入口，通过 `run_pipeline.bat` 或 `scripts/pdf_extraction/run_pipeline.py` 执行。

整体流程如下：

```text
财报 PDF
  -> 扫描文件并建立文件索引
  -> 导入公司维表和别名
  -> 导入目标字段字典
  -> 逐页解析 PDF 文本
  -> 定位三大财务报表
  -> 提取报表相关文本块
  -> 按规则抽取目标字段
  -> 清洗并写入最终财务表
  -> 生成 lineage、覆盖率和一致性校验结果
```

这条链路强调可复现和可续跑：

- 每次运行生成 `run_id`。
- 运行日志、运行统计和质量报告按 `run_id` 关联。
- 支持按步骤、文件数量、文件 ID 局部执行。
- 页面解析结果可缓存，避免重复解析大批量 PDF。

因此，PDF 抽取不是一次性脚本，而是可以批量处理、局部重跑、质量回溯的数据生产流程。

## 财务报表定位

财报 PDF 中三大财务报表通常位于正文中部，页面布局、标题写法和表格形态并不完全一致。抽取模块会先定位目标报表，再做字段抽取。

当前重点定位三类报表：

- 资产负债表。
- 利润表。
- 现金流量表。

定位结果会记录到报表定位相关表和运行产物中，用于判断某份 PDF 是否找到了可用的报表区域。后续字段抽取只围绕这些已定位的报表区域展开，避免在整份 PDF 全文中盲目搜索字段。

这一步为 Agent 提供的价值是：结构化数据来自明确的财务报表区域，而不是 PDF 任意文本片段。

## 字段抽取

字段抽取的目标是把报表中的行项目转换为标准字段。

抽取对象包括：

- 资产负债表字段，例如货币资金、应收账款、存货、总资产、总负债、所有者权益合计等。
- 利润表字段，例如营业收入、营业成本、营业利润、利润总额、净利润等。
- 现金流量表字段，例如经营活动现金流量净额、投资活动现金流量净额、筹资活动现金流量净额、现金及现金等价物净增加额等。

抽取模块主要基于字段字典、别名规则、行项目匹配和数值清洗完成，不依赖 LLM 对整份 PDF 做自由抽取。

抽取结果会保留：

- 最终字段名。
- 抽取值。
- 来源文本。
- 来源页码。
- 抽取方法。
- 抽取状态。
- 置信度或诊断信息。

这些字段级来源信息会写入 `final_table_lineage`，用于后续追溯“某个数据库数值来自 PDF 的哪里”。

## 指标映射

PDF 抽取模块解决的是“PDF 字段到数据库字段”的映射；Agent 查询模块解决的是“用户自然语言指标到数据库字段”的映射。两者通过标准字段体系衔接。

抽取侧会把 PDF 中不同叫法的报表项目归一到标准字段，例如：

- “营业收入”“营业总收入”归入利润表收入相关字段。
- “货币资金”“现金及现金等价物”按字段规则映射到资产负债表或现金流量表中的对应字段。
- “经营活动产生的现金流量净额”归入现金流量表经营现金流字段。

Agent 侧的 `data/metric_dictionary.json` 再把用户可问的财务指标映射到这些结构化字段：

- 基础指标直接指向表和字段。
- 派生指标通过公式引用基础指标。
- 指标别名用于支持不同中文问法。

因此，PDF 抽取输出的字段命名必须稳定。只有字段稳定，Agent 才能安全地生成 SQL、做趋势计算、同比计算和公司对比。

## 结构化入库

抽取后的数据会写入 PostgreSQL 中的最终财务表：

- `balance_sheet`：资产负债表。
- `income_sheet`：利润表。
- `cash_flow_sheet`：现金流量表。

三张表使用统一主键口径：

```text
stock_code + report_year + report_period
```

同时保留公司简称、公司名称和标准财务字段。这样 Agent 可以按公司、年份、报告期和指标稳定查询。

除最终表外，入库链路还会维护：

- `company_dim`：公司主数据。
- `company_alias`：公司别名，用于 Agent 公司标准化。
- `report_file_index`：财报文件索引。
- `final_table_lineage`：最终字段来源追踪。
- `financial_validation_result`：财务一致性校验结果。

这些表共同构成 Agent 的数据基础：既能查数，也能解释数据来源和质量边界。

## 一致性校验

结构化入库后，系统会对部分财务关系做一致性校验。

典型校验包括：

- 资产负债表恒等关系。
- 总资产、总负债、所有者权益相关字段的完整性。
- 最终表非空字段和 lineage 记录是否一致。
- 来源页码、来源文本、来源结果 ID 是否完整。

一致性校验不会自动改写最终财务表数值。它的职责是记录诊断结果，帮助判断当前数据是否足以支撑 Agent 回答。

这对 Agent 很重要：Agent 可以基于结构化数据回答，但系统仍然保留质量报告，避免把抽取链路包装成“绝对无误”的黑盒。

## 字段覆盖率

字段覆盖率用于衡量 PDF 抽取对目标字段的命中情况。

当前运行记录中，最近一次大规模 pipeline 统计为：

| 指标 | 数值 |
| --- | --- |
| `run_id` | `20260609_r161002` |
| 测试文件数 | 4921 |
| 成功数 | 4921 |
| 失败数 | 0 |
| 空结果数 | 24 |
| 写入字段数 | 51540 |
| 目标字段数 | 60537 |
| 字段非空率 | 85.14% |
| 关键字段总数 | 34357 |
| 关键字段命中数 | 29337 |
| 关键字段命中率 | 85.39% |

这些统计来自 `output/runtime/run_history.csv` 和对应的运行摘要。

字段覆盖率的作用不是证明所有 PDF 字段都已完整抽取，而是说明当前结构化数据已经能覆盖一批核心财务问数场景。对于未覆盖字段，系统会通过缺失统计、alias missing、entry missing、lineage 和 validation 报告暴露问题。

## 当前抽取结果

当前抽取结果已经形成三张稳定的最终财务表：

- 资产负债表：支持总资产、总负债、所有者权益、货币资金、应收账款、存货等查询。
- 利润表：支持营业收入、营业成本、营业利润、利润总额、净利润等查询。
- 现金流量表：支持经营、投资、筹资活动现金流量净额和现金流净额等查询。

从最近大规模运行看：

- pipeline 可以完成数千份文件级任务的批处理。
- 三大报表均有结构化结果，其中运行摘要按报表类型统计了资产负债表、利润表和现金流量表的处理结果。
- 结构化入库已产生可被 Agent 查询的最终财务字段。
- lineage 和质量报告能够说明字段来源、缺失原因和部分一致性问题。

这意味着 Agent 已经具备结构化问数的数据基础，可以支持：

- 单公司单指标查询。
- 多指标查询。
- 多年趋势查询。
- 同比查询。
- 公司横向对比。
- 排名查询。
- 基于基础字段的派生指标查询。

## 对 Agent 的数据支撑

PDF 抽取模块为 Agent 提供四类基础能力。

### 1. 可查询的数据表

Agent 不需要读取 PDF，只需要查询标准表：

- `balance_sheet`
- `income_sheet`
- `cash_flow_sheet`

这使 Agent 的回答可以基于 SQL 查询结果，而不是基于 LLM 对 PDF 的临时理解。

### 2. 稳定的公司维度

公司主表和别名表让 Agent 可以把用户输入的公司简称、全称或股票代码标准化为 `stock_code`。

这支撑了：

- “华润三九 2024 年营业收入是多少？”
- “云南白药和同仁堂谁的净利润更高？”
- “贵州茅台近五年趋势如何？”

### 3. 稳定的指标字段

最终财务表字段和指标字典建立了统一指标口径。Agent 可以把“营业收入”“净利润”“经营现金流”等用户表达映射到具体表字段。

这支撑了：

- 基础指标查询。
- 多指标查询。
- 趋势和同比计算。
- 派生指标公式计算。

### 4. 可追溯的质量基础

lineage 和 validation 让系统知道字段来自哪里、哪些字段缺失、哪些恒等关系未通过。

这支撑了：

- 数据质量排查。
- 抽取结果解释。
- 后续优化字段规则。
- 对 Agent 回答边界的判断。

## 局限性

当前 PDF 抽取模块仍有明确边界。

1. 不保证所有 PDF 版式都能完整解析。
   不同公司、不同年份的财报版式差异较大，表格边界、换行、跨页和合并单元格会影响抽取效果。

2. 不保证所有字段都已覆盖。
   当前重点覆盖三大报表中的核心字段，部分细分字段、母公司口径字段或现金流补充字段仍可能未支持。

3. 不自动修正最终表数值。
   一致性校验只记录问题，不根据恒等式自动改写数据库值。

4. 部分来源绑定仍可能不够精细。
   个别字段可能能找到页面文本来源，但无法稳定证明其来自同一个结构化表格段。

5. 覆盖率不是准确率。
   非空率说明字段被抽取到，不等于所有字段都完全正确。准确性仍需要结合 lineage、财务一致性校验和抽样复核判断。

6. 当前主要服务财务问数场景。
   模块优先抽取 Agent 需要的结构化财务指标，不覆盖公告全文理解、管理层讨论分析、审计意见全文问答等非结构化问答场景。

## 总结

PDF 抽取模块的核心价值是把财报 PDF 从“只能人工阅读的文件”转换为“可以被 SQL 和 Agent 查询的结构化财务数据库”。

它为 Agent 提供了：

- 标准公司维度。
- 标准财务指标字段。
- 三大报表结构化数据。
- 字段级来源追踪。
- 覆盖率和一致性校验。
- 可批量重跑和持续改进的数据生产链路。

因此，后续问数 Agent 的能力不是建立在 LLM 对 PDF 的自由理解上，而是建立在这套可查询、可追溯、可校验的结构化数据底座上。
## 运行命令参考

本节集中保存 README 中移出的 PDF pipeline、数据库初始化、lineage 查询、validation 和历史验收命令。

### 完整 PDF pipeline

跑完整流程：

```bat
run_pipeline.bat
```

等价于调用：

```bat
python scripts\pdf_extraction\run_pipeline.py
```

只处理指定 `file_id`：

```bat
run_pipeline.bat --file-id 123 456
```

限制处理数量：

```bat
run_pipeline.bat --limit 20
```

只处理指定报表类型：

```bat
run_pipeline.bat --statement-type balance_sheet income cash_flow
```

只写入指定最终表：

```bat
run_pipeline.bat --target-table balance_sheet income
```

从某一步开始：

```bat
run_pipeline.bat --from-step locate_financial_statements
```

执行到某一步：

```bat
run_pipeline.bat --to-step extract_attachment3_rule_based
```

强制刷新页面缓存后重新定位：

```bat
python scripts\pdf_extraction\locate_financial_statements.py --file-id 123 --force-page-parse
```

步骤名支持脚本名、脚本名去掉 `.py` 后的名称，或 pipeline 中定义的步骤序号。

### 数据库初始化和 SQL 文件

建表和数据库维护 SQL 位于 `sql/`。常用初始化顺序以当前环境实际表状态为准，通常先创建基础表，再创建最终表、lineage 表和 validation 表：

```bat
psql -f sql\02_create_base_tables.sql
psql -f sql\03_create_attachment3_final_tables.sql
psql -f sql\04_create_final_table_lineage.sql
psql -f sql\05_create_financial_validation_result.sql
```

当前 SQL 文件清单：

- `sql/01_create_tables.sql`
- `sql/02_create_base_tables.sql`
- `sql/03_create_attachment3_final_tables.sql`
- `sql/04_create_final_table_lineage.sql`
- `sql/05_create_financial_validation_result.sql`
- `sql/06_add_company_name_to_final_tables.sql`
- `sql/check_rule.sql`
- `sql/core.sql`
- `sql/final_standard_tables.sql`

### lineage 查询命令

查询最终表字段来源：

```bat
python scripts\pdf_extraction\lookup_final_source.py --stock-code 000999 --year 2022 --period FY --table balance_sheet --field asset_cash_and_cash_equivalents
```

校验最终表 lineage 覆盖情况：

```bat
python scripts\pdf_extraction\validate_final_table_lineage.py --run-id <run_id>
```

lineage 查询会返回最终值和来源信息，包括 `file_id`、`source_result_id`、`source_page_no`、`source_text`、`source_raw_value`、`extract_method`、`extract_status`、`confidence`、`run_id` 和 `diagnostic_json`。

### validation 脚本命令

生成最终表质量报告：

```bat
python scripts\pdf_extraction\generate_final_table_quality_report.py --run-id <run_id>
```

执行财务一致性校验：

```bat
python scripts\pdf_extraction\validate_financial_consistency.py --run-id <run_id>
```

导出校验问题明细：

```bat
python scripts\pdf_extraction\export_validation_issues.py --run-id <run_id>
```

导出校验失败字段来源：

```bat
python scripts\pdf_extraction\export_failed_validation_sources.py --run-id <run_id>
```

对比两次校验结果：

```bat
python scripts\pdf_extraction\compare_validation_runs.py --base-run-id <base_run_id> --target-run-id <target_run_id>
```

定位报表质量检查：

```bat
python scripts\pdf_extraction\statement_locator_quality.py --run-id <run_id>
```

### 历史验收脚本

当前 Agent 测试入口：

```bat
python -m pytest tests
```

如需按历史版本分组运行当前仍保留的回归测试，可以使用：

```bat
python scripts\run_v06_test_suite.py
```

早期 V0.4/V0.5 的独立脚本没有随 clean repo 发布，历史场景已合并到当前 `tests/` 下的正式测试。
