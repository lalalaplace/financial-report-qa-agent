# scripts 目录说明

## 结论

当前 `scripts` 目录只保留分类入口说明，脚本按职责拆到三个子目录：

- `pdf_extraction/`：当前 PDF 财报数据提取、清洗、校验、入库主流程。
- `agent/`：财务查询 Agent 的验收和测试脚本。
- `deprecated/`：已放弃或冻结的旧路线脚本，尤其是 LLM/DeepSeek/OpenAI 数据抽取方案。

## 当前主流程

主入口：

```bat
run_pipeline.bat
```

实际调用：

```bat
python scripts\pdf_extraction\run_pipeline.py
```

主流程步骤仍为：

1. `scan_reports.py`
2. `import_company.py`
3. `import_attachment3_dict.py`
4. `parse_pdf_pages.py`
5. `locate_financial_statements.py`
6. `extract_statement_blocks.py`
7. `extract_attachment3_rule_based.py`
8. `load_attachment3_results_to_sql.py`

## 分类原则

### `pdf_extraction/`

放置当前仍在维护的 PDF 数据提取相关脚本，包括：

- PDF 扫描、解析、报表定位、报表块恢复
- 附件 3 规则抽取
- 人工补录导入导出
- 最终表写入
- lineage、质量报告、财务一致性校验
- 字段覆盖率、候选拒绝原因、规则映射等排查脚本

当前维护的 PDF 抽取流程不提供本地模型候选裁决入口，字段抽取以规则链路和人工补录为准。

### `agent/`

放置面向 `agent/` 包的测试或验收脚本。该目录不参与 PDF 抽取 pipeline。

### `deprecated/`

放置已废弃脚本，包括：

- `extract_attachment3_llm_fallback.py`
- `extract_attachment3_llm_table_batch.py`
- `extract_attachment3_llm_table_batch_deepseek.py`
- `extract_attachment3_llm_table_batch_openai.py`
- `run_pipeline_deepseek.py`
- `run_pipeline_openai.py`
- `deepseek_backfill/`
- `extract_pdf_blocks.py`

这些脚本只作为历史参考，不应接回默认 pipeline。

## 修改约束

- 新增 PDF 抽取脚本默认放入 `scripts/pdf_extraction/`。
- 新增 Agent 测试脚本默认放入 `scripts/agent/`。
- 不要恢复付费模型或在线模型作为 PDF 数据抽取主流程。
- 如需引用废弃脚本，必须先说明原因和影响范围。
