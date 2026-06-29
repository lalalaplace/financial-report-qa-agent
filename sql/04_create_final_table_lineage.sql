CREATE TABLE IF NOT EXISTS final_table_lineage (
    id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL,
    file_id BIGINT NOT NULL,
    stock_code VARCHAR(32),
    company_name VARCHAR(255),
    report_year INTEGER,
    report_period VARCHAR(32),
    final_table VARCHAR(128) NOT NULL,
    final_field VARCHAR(128) NOT NULL,
    final_value TEXT,
    source_table VARCHAR(128) NOT NULL DEFAULT 'attachment3_extract_result',
    source_result_id BIGINT,
    source_page_no INTEGER,
    source_text TEXT,
    source_raw_value TEXT,
    extract_method VARCHAR(128),
    extract_status VARCHAR(128),
    confidence DOUBLE PRECISION,
    diagnostic_json JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT final_table_lineage_unique_run_field UNIQUE (
        run_id,
        file_id,
        final_table,
        final_field,
        report_year,
        report_period
    )
);

CREATE INDEX IF NOT EXISTS idx_final_table_lineage_lookup
ON final_table_lineage (stock_code, report_year, report_period, final_table, final_field);

CREATE INDEX IF NOT EXISTS idx_final_table_lineage_source_result
ON final_table_lineage (source_result_id);
