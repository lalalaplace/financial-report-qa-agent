-- 说明：
-- 1. 本脚本用于补齐当前代码实际依赖的基础表结构，可重复执行。
-- 2. 已存在的表不会重建；缺失字段、缺失约束、缺失索引会自动补齐。
-- 3. 附件3相关中间表已由 01_create_tables.sql 创建，本脚本主要补基础主表与兼容字段。


BEGIN;


-- ========================================
-- 1. 公司主数据
-- ========================================

CREATE TABLE IF NOT EXISTS company_dim (
    company_id BIGSERIAL PRIMARY KEY,
    stock_code VARCHAR(20) NOT NULL,
    stock_abbr VARCHAR(100) NOT NULL,
    company_name VARCHAR(255) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE company_dim
    ADD COLUMN IF NOT EXISTS stock_code VARCHAR(20),
    ADD COLUMN IF NOT EXISTS stock_abbr VARCHAR(100),
    ADD COLUMN IF NOT EXISTS company_name VARCHAR(255),
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

CREATE UNIQUE INDEX IF NOT EXISTS company_dim_stock_code_key
    ON company_dim (stock_code);

CREATE INDEX IF NOT EXISTS idx_company_dim_stock_abbr
    ON company_dim (stock_abbr);

CREATE INDEX IF NOT EXISTS idx_company_dim_company_name
    ON company_dim (company_name);


CREATE TABLE IF NOT EXISTS company_alias (
    alias_id BIGSERIAL PRIMARY KEY,
    company_id BIGINT NOT NULL,
    alias_name VARCHAR(255) NOT NULL,
    alias_type VARCHAR(64) NOT NULL,
    is_primary BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE company_alias
    ADD COLUMN IF NOT EXISTS company_id BIGINT,
    ADD COLUMN IF NOT EXISTS alias_name VARCHAR(255),
    ADD COLUMN IF NOT EXISTS alias_type VARCHAR(64),
    ADD COLUMN IF NOT EXISTS is_primary BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'company_alias_company_id_fkey'
    ) THEN
        ALTER TABLE company_alias
            ADD CONSTRAINT company_alias_company_id_fkey
            FOREIGN KEY (company_id)
            REFERENCES company_dim(company_id);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_company_alias_company_id
    ON company_alias (company_id);

CREATE INDEX IF NOT EXISTS idx_company_alias_alias_name
    ON company_alias (alias_name);

CREATE UNIQUE INDEX IF NOT EXISTS uk_company_alias_company_alias_type
    ON company_alias (company_id, alias_name, alias_type);


-- ========================================
-- 2. 财报文件索引
-- ========================================

CREATE TABLE IF NOT EXISTS report_file_index (
    file_id BIGSERIAL PRIMARY KEY,
    company_id BIGINT,
    stock_code VARCHAR(20),
    stock_abbr VARCHAR(100),
    company_name VARCHAR(255),
    file_name VARCHAR(255) NOT NULL,
    file_path TEXT NOT NULL,
    report_year INTEGER,
    report_period VARCHAR(32),
    source_exchange VARCHAR(32),
    report_type_text VARCHAR(255),
    match_method VARCHAR(64),
    parse_status VARCHAR(32),
    is_summary BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE report_file_index
    ADD COLUMN IF NOT EXISTS company_id BIGINT,
    ADD COLUMN IF NOT EXISTS stock_code VARCHAR(20),
    ADD COLUMN IF NOT EXISTS stock_abbr VARCHAR(100),
    ADD COLUMN IF NOT EXISTS company_name VARCHAR(255),
    ADD COLUMN IF NOT EXISTS file_name VARCHAR(255),
    ADD COLUMN IF NOT EXISTS file_path TEXT,
    ADD COLUMN IF NOT EXISTS report_year INTEGER,
    ADD COLUMN IF NOT EXISTS report_period VARCHAR(32),
    ADD COLUMN IF NOT EXISTS source_exchange VARCHAR(32),
    ADD COLUMN IF NOT EXISTS report_type_text VARCHAR(255),
    ADD COLUMN IF NOT EXISTS match_method VARCHAR(64),
    ADD COLUMN IF NOT EXISTS parse_status VARCHAR(32),
    ADD COLUMN IF NOT EXISTS is_summary BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'report_file_index_company_id_fkey'
    ) THEN
        ALTER TABLE report_file_index
            ADD CONSTRAINT report_file_index_company_id_fkey
            FOREIGN KEY (company_id)
            REFERENCES company_dim(company_id);
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS report_file_index_file_path_key
    ON report_file_index (file_path);

CREATE INDEX IF NOT EXISTS idx_report_file_index_company_id
    ON report_file_index (company_id);

CREATE INDEX IF NOT EXISTS idx_report_file_index_stock_code
    ON report_file_index (stock_code);

CREATE INDEX IF NOT EXISTS idx_report_file_index_parse_status
    ON report_file_index (parse_status);

CREATE INDEX IF NOT EXISTS idx_report_file_index_report_year_period
    ON report_file_index (report_year, report_period);


-- ========================================
-- 3. 三大报表定位表
-- ========================================

CREATE TABLE IF NOT EXISTS report_statement_locator (
    id BIGSERIAL PRIMARY KEY,
    file_id BIGINT NOT NULL,
    statement_type VARCHAR(32) NOT NULL,
    page_start INTEGER,
    page_end INTEGER,
    locator_method VARCHAR(64) NOT NULL,
    locator_status VARCHAR(32) NOT NULL,
    source_text TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE report_statement_locator
    ADD COLUMN IF NOT EXISTS file_id BIGINT,
    ADD COLUMN IF NOT EXISTS statement_type VARCHAR(32),
    ADD COLUMN IF NOT EXISTS page_start INTEGER,
    ADD COLUMN IF NOT EXISTS page_end INTEGER,
    ADD COLUMN IF NOT EXISTS locator_method VARCHAR(64),
    ADD COLUMN IF NOT EXISTS locator_status VARCHAR(32),
    ADD COLUMN IF NOT EXISTS source_text TEXT,
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'report_statement_locator_file_id_fkey'
    ) THEN
        ALTER TABLE report_statement_locator
            ADD CONSTRAINT report_statement_locator_file_id_fkey
            FOREIGN KEY (file_id)
            REFERENCES report_file_index(file_id)
            ON DELETE CASCADE;
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uk_report_statement_locator_file_statement
    ON report_statement_locator (file_id, statement_type);

CREATE INDEX IF NOT EXISTS idx_report_statement_locator_status
    ON report_statement_locator (locator_status);


-- ========================================
-- 4. 对附件3中间表补索引
-- ========================================

CREATE INDEX IF NOT EXISTS idx_attachment3_field_dict_target_table
    ON attachment3_field_dict (target_table);

CREATE INDEX IF NOT EXISTS idx_attachment3_extract_result_file_id
    ON attachment3_extract_result (file_id);

CREATE INDEX IF NOT EXISTS idx_attachment3_extract_result_target_table
    ON attachment3_extract_result (target_table);

CREATE INDEX IF NOT EXISTS idx_attachment3_extract_result_file_target_field
    ON attachment3_extract_result (file_id, target_table, field_code);

CREATE INDEX IF NOT EXISTS idx_attachment3_extract_result_method
    ON attachment3_extract_result (extract_method);

CREATE INDEX IF NOT EXISTS idx_attachment3_validation_result_file_id
    ON attachment3_validation_result (file_id);


COMMIT;
