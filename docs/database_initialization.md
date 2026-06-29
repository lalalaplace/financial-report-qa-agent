# 数据库初始化

## 账号建议

PDF 抽取流程需要写入权限，用于导入报告索引、抽取结果、lineage 和最终财务表。

Agent 查询流程建议使用只读账号，只允许查询结构化财务表和维表。

## 本地数据准备

本仓库不提供原始财报 PDF、竞赛附件 Excel、完整数据库或大型运行产物。完整复现 PDF 抽取流程前，需要在本地准备：

- `input/reports/`：上市公司财报 PDF。
- `input/attachment/`：竞赛附件 Excel，例如公司基础信息和“附件3：数据库-表名及字段说明.xlsx”。
- PostgreSQL：用于存储公司维表、文件索引、抽取结果、lineage 和校验结果。
- `.env`：从 `.env.example` 复制后填写本地 `DATABASE_URL` 或 `DB_*` 配置。

`examples/sample_pdf_manifest.csv` 只是脱敏路径样例，用于说明 manifest 字段形态，不是可直接运行的数据集。

## 初始化顺序

根据实际需要执行 SQL。建议顺序：

```bash
psql "$DATABASE_URL" -f sql/01_create_tables.sql
psql "$DATABASE_URL" -f sql/02_create_base_tables.sql
psql "$DATABASE_URL" -f sql/03_create_attachment3_final_tables.sql
psql "$DATABASE_URL" -f sql/04_create_final_table_lineage.sql
psql "$DATABASE_URL" -f sql/05_create_financial_validation_result.sql
psql "$DATABASE_URL" -f sql/06_add_company_name_to_final_tables.sql
```

如果只需要 Agent 查询已存在的标准财务表，可按目标环境选择执行 `sql/final_standard_tables.sql` 或使用已有数据库结构。

## 环境变量

优先使用：

```text
DATABASE_URL=postgresql+psycopg2://user:password@localhost:5432/financial_data
```

PDF 抽取脚本也支持拆分配置：

```text
DB_HOST=localhost
DB_PORT=5432
DB_NAME=financial_data
DB_USER=user
DB_PASSWORD=password
```

不要提交 `.env`。
