# Financial Report Intelligence Agent

![Tests](https://github.com/lalalaplace/financial-report-qa-agent/actions/workflows/tests.yml/badge.svg)

> 财报 PDF 结构化与受控 LLM 财务问数系统：从上市公司年报 PDF 抽取三大财务报表，构建 PostgreSQL 数据库，并通过 LangGraph 提供中文财务问数能力。

**技术栈：** Python · LangGraph · LangChain · PostgreSQL · SQLAlchemy · Pydantic · Pytest

## 项目概览

本项目将“从非结构化财报中得到可信财务事实”拆分为两条可验证链路：先将 PDF 转为可追溯、可校验的结构化数据，再将自然语言问题转为受控查询，并基于已执行的 SQL 结果作答。

```text
上市公司年报 PDF
  -> 报表定位、字段抽取与标准化
  -> 字段级 Lineage 与财务一致性校验
  -> PostgreSQL 结构化财务数据库
  -> LangGraph 查询规划
  -> 确定性 SQL / 受控 LLM SQL
  -> SQL Guard、试运行与只读执行
  -> 结构化财务回答
```

LLM 不直接读取整份 PDF，也不自由生成财务数值。最终答案中的指标和表格来自数据库查询结果；受控 LLM SQL 只能生成候选 SQL，不能改变指标来源、公式、阈值或查询范围。

## 核心成果

| 维度 | 当前结果 |
| --- | --- |
| 数据规模 | 索引 **2,540** 份财报文件，覆盖 **71** 家公司、2022–2025 年 |
| 最终财务表 | 资产负债表 810 行、利润表 775 行、现金流量表 799 行；三表均覆盖 69 家公司 |
| 指标能力 | 指标字典覆盖 20 个可问指标：15 个基础指标与 5 个注册派生指标 |
| 基础问数 | 单/多指标、趋势、同比、派生指标、公司对比、排名及排名位置 |
| 多轮交互 | 槽位补充、公司或指标替换、上下文追问；待澄清状态与成功查询状态隔离 |
| 复杂查询 | 多条件同比筛选、两个明确 Top N 的单次交集、注册派生指标筛选/排序 |
| 安全边界 | SQL Guard、表字段白名单、语义合同、试运行、只读执行与受控拒绝 |
| 自动化验证 | 当前离线测试：**213 passed, 30 skipped** |

数据范围和字段口径详见 [数据目录](docs/data_catalog.md)，PDF 处理与质量校验详见 [抽取总结](docs/extraction_summary.md)。

## 系统架构

![流程图](docs/流程图.png)

- **确定性通道：** 已注册查询由固定 SQL 节点构建，保证常见财务问数稳定可复现。
- **Flexible SQL 通道：** 仅接收结构化规格与不可变语义合同；候选 SQL 必须通过白名单、只读限制、合同校验和试运行。
- **受控拒绝：** 嵌套 Top N、多阶段集合运算、自由派生公式和来源不明确的跨表查询返回 `UNSUPPORTED_FLEXIBLE_SQL`，不执行候选 SQL。

实现细节见 [Agent 工作流](docs/agent_workflow.md) 与 [系统架构](docs/architecture.md)。

## 关键技术设计

### 可追溯的财报数据生产链路

不同年报的表名、页码、列名和别名并不统一。系统使用“候选页定位 -> 报表块提取 -> 字段字典映射 -> 一致性校验”的流程，并记录字段级 Lineage，避免无法追溯的值直接进入最终财务表。

### QueryPlan 驱动的确定性查询

LLM 负责识别查询语义，系统负责将公司、指标、年份和报告期标准化。已知查询由固定 SQL 实现，LLM 不直接决定财务事实，也不修改查询结果。

### 语义合同约束的 Flexible SQL

对正式支持的复杂结构，系统将指标来源、注册公式、阈值、报告期、排序和限制编译为不可变合同。LLM 仅负责 SQL 写法；任何改变公式、尺度或集合范围的候选 SQL 都会被拒绝。

### 多轮状态隔离

`pending_query_plan` 保存待澄清问题，`last_successful_query_plan` 仅保存成功查询。后续追问通过 `slot_patch` 合并条件，失败结果不会污染后续上下文。

## 技术难点与解决方案

| 难点 | 解决方案 |
| --- | --- |
| 财报 PDF 表格结构不统一 | 候选页定位、字段映射、一致性校验与字段级 Lineage |
| SQL 可执行但语义错误 | 不可变语义合同约束来源、公式、阈值和时间范围；候选 SQL 必须校验与试运行 |
| 多轮追问污染状态 | 待澄清与成功查询状态分区，失败链路不覆盖最近成功结果 |
| 回答出现静默事实错误 | 数值与表格由查询结果确定性生成，LLM 仅生成受限摘要并接受答案校验 |

## Demo

最小 Demo 使用虚构公司和合成财务数据，不包含原始财报或生产数据库。启动 PostgreSQL 后，将 `.env.example` 中的 `DATABASE_URL` 调整为：

```text
postgresql+psycopg2://demo_user:demo_password@localhost:5432/financial_demo
```

```bash
docker compose -f docker-compose.demo.yml up -d
python scripts/agent_demo_cli.py
```

示例问题见 [demo/demo_questions.txt](demo/demo_questions.txt)。运行 Agent 仍需要配置模型服务；不配置模型时可运行离线测试验证图结构和确定性逻辑。

### 合成数据快速体验

```text
星河医药 2024 年营业收入是多少？
星河医药 2024 年营业收入同比增长多少？
星河医药和远景健康 2024 年谁的净利润更高？
2024 年营业收入最高的前 3 家公司是谁？
```

### 完整数据效果展示

以下案例基于本地完整竞赛数据运行，不包含在公开仓库的合成数据集中。

```text
华润三九 2024 年营业收入是多少？
同比呢？
换成云南白药呢？
```

完整普通模式、Trace 模式和复杂查询案例见 [Demo 案例](docs/demo_cases.md)。

## 能力范围与验收

| 能力类别 | 示例 |
| --- | --- |
| 基础查询 | 单指标、多指标、注册派生指标 |
| 时间分析 | 多年趋势、同比变化、区间增长 |
| 横向分析 | 公司对比、趋势对比、同比对比 |
| 排名分析 | Top N、同比排名、指定公司排名位置 |
| 多轮交互 | 补充公司、替换指标、上下文追问 |
| 复杂查询 | 多条件同比、Top N 交集、注册派生指标筛选 |

Flexible SQL 的正式支持边界、拒绝规则和验收口径见 [Flexible SQL V1 验收说明](docs/flexible_sql_v1_acceptance.md)。

## 快速开始

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Linux/macOS：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

复制 `.env.example` 为 `.env`，填写 PostgreSQL 连接和模型服务配置；不要提交 `.env`、原始 PDF、数据库文件或运行产物。

```bat
python scripts\agent_demo_cli.py
python -m pytest tests
```

PDF 结构化流程入口为 `run_pipeline.bat`；运行前需准备本地财报 PDF 和 PostgreSQL。详细流程见 [抽取总结](docs/extraction_summary.md)。

## 项目结构

```text
agent/                    LangGraph 问数 Agent、节点、状态与校验器
db/                       只读 SQL 执行与安全控制
data/                     指标字典等轻量配置
scripts/pdf_extraction/   PDF 抽取、清洗、校验与入库流程
scripts/evaluation/       可选评估脚本
scripts/archive/          历史调试与验收脚本
sql/                      表结构、导出与校验 SQL
tests/                    Agent 自动化测试
docs/                     架构、数据目录、Demo 与验收文档
```

完整目录说明见 [仓库结构](docs/REPOSITORY_LAYOUT.md)。

## 详细文档

- [数据目录](docs/data_catalog.md)
- [PDF 抽取总结](docs/extraction_summary.md)
- [Agent 工作流](docs/agent_workflow.md)
- [系统架构](docs/architecture.md)
- [Demo 案例](docs/demo_cases.md)
- [更新记录](CHANGELOG.md)

## 限制与数据说明

- 数据覆盖医药相关上市公司 2022–2025 年的本地财报索引；覆盖率不等同于字段完全正确，需结合 Lineage、一致性校验和抽样复核判断。
- 不支持 PDF 原文或管理层访谈推理、外部新闻/行情、投资建议、股价预测和任意 SQL 执行。
- 原始 PDF、数据库、运行日志和大型运行产物不随仓库发布，需在本地准备。
