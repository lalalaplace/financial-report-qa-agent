# 项目目录说明

## 结论

当前仓库保留两条主链路：

1. `scripts/pdf_extraction/`：财报 PDF 数据提取、清洗、校验、入库链路。
2. `agent/`：LangGraph 财报问数 Agent 链路。

目录整理以最小必要调整为原则，不移动核心 Python 模块，不改变运行入口。

## 目录分类

| 路径 | 分类 | 说明 | GitHub 展示建议 |
| --- | --- | --- | --- |
| `agent/` | Agent 相关 | LangGraph 图、节点、状态、路由、服务、回答生成、校验器 | 保留 |
| `db/` | 数据库访问 | 只读 SQL 执行器等 Agent 查询依赖 | 保留 |
| `data/` | Agent 配置数据 | 指标字典等轻量结构化配置 | 保留 |
| `scripts/pdf_extraction/` | PDF 数据提取相关 | PDF 扫描、解析、报表定位、规则抽取、入库、质量校验 | 保留 |
| `scripts/agent/` | Agent 验收脚本 | 历史版本验收和场景测试脚本 | 保留 |
| `scripts/evaluation/` | 评估脚本 | 双通道、规划器和真实模型验收 | 保留，不作为默认入口 |
| `scripts/archive/` | 历史脚本 | 已冻结的 V0.x、调试和追踪脚本 | 保留，不作为主入口 |
| `sql/` | SQL/schema 相关 | 建表、导出、校验和字段补充 SQL | 保留 |
| `tests/` | 测试 | 当前 Agent 单元测试和流程测试 | 保留 |
| `prompts/` | 文档 | 历史 prompt 版本记录 | 保留，可在 README 中说明为历史设计记录 |
| `agent/prompts/` | Agent 运行资源 | Agent 当前运行使用的 prompt 模板 | 保留 |
| `input/attachment/` | 示例/字段说明输入 | 附件 3 字段说明等小体积输入 | 可保留 |
| `input/reports/` | 本地数据 | 原始财报 PDF | 不上传，已忽略 |
| `示例数据/` | 本地数据 | 原始附件、PDF、研报等大体积样例 | 不上传，已忽略 |
| `output/` | 运行产物 | 抽取结果、质量报告、运行记录、缓存 | 不上传，已忽略 |
| `logs/` | 运行日志 | Agent 或批处理运行日志 | 不上传，已忽略 |
| `.env` | 本地配置 | API Key、数据库连接等本地环境变量 | 不上传，已忽略 |
| `.env.example` | 配置模板 | 可公开的环境变量示例 | 保留 |

## 当前入口

- PDF 数据提取主入口：`run_pipeline.bat`
- 实际调用脚本：`scripts/pdf_extraction/run_pipeline.py`
- Agent 主包：`agent/`
- SQL schema：`sql/`

## 上传风险处理

不适合上传 GitHub 的内容包括：

- 原始 PDF：`input/reports/`、`示例数据/`、`*.pdf`
- 大体积运行产物：`output/`
- 本地日志：`logs/`、`*.log`
- 本地环境变量：`.env`、`.env.*`
- Python 缓存：`__pycache__/`、`*.py[cod]`、`.pytest_cache/`
- notebook 缓存：`.ipynb_checkpoints/`
- 本地数据库和分析文件：`*.db`、`*.sqlite`、`*.sqlite3`、`*.duckdb`、`*.parquet`

如果历史上已经被 Git 跟踪，需要用 `git rm --cached` 取消跟踪；本次目录整理不直接删除本地重要数据。
## 详细目录说明

本节承接 README 中移出的较长目录解释。

```text
agent/                    LangGraph 财报问数 Agent
data/                     指标字典等轻量配置
db/                       只读 SQL 执行器
docs/                     项目文档
input/                    本地输入目录
scripts/pdf_extraction/   财报 PDF 抽取与结构化流程
scripts/agent/            Agent 历史验收脚本
scripts/evaluation/       双通道与模型评估脚本
scripts/archive/          已冻结的历史调试与验收脚本
sql/                      建表、导出和校验 SQL
tests/                    Agent 测试
run_pipeline.bat          PDF 结构化流程入口
```

## 评估与历史脚本说明

`scripts/evaluation/` 保存可选的双通道、规划器和真实模型验收脚本；`scripts/archive/` 保存不再作为主入口的历史调试与验收脚本。保留这些脚本是为了追溯历史方案和必要时对比结果，不建议在主流程中继续依赖。

当前可选评估脚本包括：

- `scripts/evaluation/run_dual_channel_e2e.py`
- `scripts/evaluation/run_planner_benchmark.py`
- `scripts/evaluation/run_real_llm_smoke.py`

当前归档脚本包括：

- `scripts/archive/run_v06_test_suite.py`
- `scripts/archive/test_agent_20.py`
- `scripts/archive/trace_flexible_sql_case.py`
