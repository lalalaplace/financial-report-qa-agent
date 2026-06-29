CREATE TABLE IF NOT EXISTS financial_validation_result (
    id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL,
    file_id BIGINT,
    stock_code VARCHAR(32),
    company_name VARCHAR(255),
    report_year INTEGER,
    report_period VARCHAR(32),
    validation_type VARCHAR(128) NOT NULL,
    validation_status VARCHAR(32) NOT NULL,
    expected_value NUMERIC(28, 6),
    actual_value NUMERIC(28, 6),
    diff_value NUMERIC(28, 6),
    diff_ratio DOUBLE PRECISION,
    related_fields JSONB,
    message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_financial_validation_result_run
ON financial_validation_result (run_id, validation_type, validation_status);

CREATE INDEX IF NOT EXISTS idx_financial_validation_result_lookup
ON financial_validation_result (stock_code, report_year, report_period);
