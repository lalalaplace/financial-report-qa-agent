-- DeepSeek 定点补缺审计表
-- 用途：
-- 1. 保存最终表直写方案下的大模型证据链
-- 2. 保留页码、证据行、置信度、原始响应与失败原因
-- 3. 支持断点续跑与结果追溯

CREATE TABLE IF NOT EXISTS public.llm_targeted_backfill_audit (
    audit_id BIGSERIAL PRIMARY KEY,
    task_id TEXT NOT NULL,
    target_table VARCHAR(64) NOT NULL,
    target_column VARCHAR(128) NOT NULL,
    field_code VARCHAR(128),
    field_name_cn VARCHAR(255),
    company_id BIGINT,
    stock_code VARCHAR(32),
    stock_abbr VARCHAR(128),
    report_year INTEGER,
    report_period VARCHAR(16),
    file_id BIGINT,
    file_path TEXT,
    model_name VARCHAR(128),
    source_unit VARCHAR(32),
    target_unit VARCHAR(32),
    value_text TEXT,
    normalized_value NUMERIC(24, 6),
    evidence_line TEXT,
    page_no INTEGER,
    confidence DOUBLE PRECISION,
    status VARCHAR(64) NOT NULL,
    error_message TEXT,
    raw_response_json TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_llm_targeted_backfill_audit_task_id
    ON public.llm_targeted_backfill_audit (task_id);

CREATE INDEX IF NOT EXISTS idx_llm_targeted_backfill_audit_target
    ON public.llm_targeted_backfill_audit (target_table, target_column, stock_code, report_year, report_period);
