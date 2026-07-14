CREATE TABLE attachment3_field_dict (
    field_id BIGSERIAL PRIMARY KEY,
    target_table VARCHAR(50) NOT NULL,   -- core_performance / balance_sheet / income / cash_flow
    field_code VARCHAR(100) NOT NULL UNIQUE,
    field_name_cn VARCHAR(200) NOT NULL,
    data_type VARCHAR(50),
    field_desc TEXT,
    sort_order INTEGER
);

CREATE TABLE attachment3_extract_result (
    result_id BIGSERIAL PRIMARY KEY,
    file_id BIGINT NOT NULL REFERENCES report_file_index(file_id),
    company_id BIGINT,
    stock_code VARCHAR(20),
    stock_abbr VARCHAR(100),
    report_year INTEGER,
    report_period VARCHAR(20),
    target_table VARCHAR(50) NOT NULL,
    field_code VARCHAR(100),
    field_name_cn VARCHAR(200),
    value_text TEXT,
    source_page_range VARCHAR(50),
    source_text TEXT,
    extract_method VARCHAR(50),   -- rule / llm / hybrid
    llm_status VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE attachment3_validation_result (
    validation_id BIGSERIAL PRIMARY KEY,
    file_id BIGINT NOT NULL REFERENCES report_file_index(file_id),
    target_table VARCHAR(50),
    validation_rule VARCHAR(200),
    validation_status VARCHAR(50),
    validation_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);