-- 作用：
-- 1. 创建附件3标准最终表：
--    - balance_sheet
--    - income_sheet
--    - cash_flow_sheet
-- 2. 本脚本严格使用最终交付结构，不再使用工程中间宽表结构。
-- 3. 本脚本不会创建 *_raw / *_num / *_method 等工程字段。
--
-- 使用前提：
-- 1. 已完成基础库表初始化。
-- 2. attachment3_field_dict 已按当前附件3字典导入。
-- 3. 如需保留旧数据，请先自行备份；本脚本会 DROP 原表。
--
-- 执行方式：
-- psql -d teddy_b -f sql/03_create_attachment3_final_tables.sql

DROP TABLE IF EXISTS balance_sheet;
CREATE TABLE balance_sheet (
    serial_number INTEGER NOT NULL,
    stock_code VARCHAR(32) NOT NULL,
    stock_abbr VARCHAR(128),
    company_name VARCHAR(255),
    report_year INTEGER NOT NULL,
    report_period VARCHAR(8) NOT NULL,
    asset_cash_and_cash_equivalents DECIMAL(20,2),
    asset_accounts_receivable DECIMAL(20,2),
    asset_inventory DECIMAL(20,2),
    asset_trading_financial_assets DECIMAL(20,2),
    asset_construction_in_progress DECIMAL(20,2),
    asset_total_assets DECIMAL(20,2),
    asset_total_assets_yoy_growth DECIMAL(10,4),
    liability_accounts_payable DECIMAL(20,2),
    liability_advance_from_customers DECIMAL(20,2),
    liability_total_liabilities DECIMAL(20,2),
    liability_total_liabilities_yoy_growth DECIMAL(10,4),
    liability_and_equity_total DECIMAL(20,2),
    liability_contract_liabilities DECIMAL(20,2),
    liability_short_term_loans DECIMAL(20,2),
    asset_liability_ratio DECIMAL(10,4),
    equity_unappropriated_profit DECIMAL(20,2),
    equity_total_equity DECIMAL(20,2),
    CONSTRAINT balance_sheet_pk PRIMARY KEY (stock_code, report_year, report_period)
);
CREATE UNIQUE INDEX balance_sheet_serial_number_uq ON balance_sheet (serial_number);
CREATE INDEX balance_sheet_year_period_idx ON balance_sheet (report_year, report_period);
ALTER TABLE balance_sheet ADD CONSTRAINT balance_sheet_report_period_chk CHECK (report_period IN ('Q1', 'HY', 'Q3', 'FY'));


DROP TABLE IF EXISTS income_sheet;
CREATE TABLE income_sheet (
    serial_number INTEGER NOT NULL,
    stock_code VARCHAR(32) NOT NULL,
    stock_abbr VARCHAR(128),
    company_name VARCHAR(255),
    report_year INTEGER NOT NULL,
    report_period VARCHAR(8) NOT NULL,
    net_profit DECIMAL(20,2),
    net_profit_yoy_growth DECIMAL(10,4),
    other_income DECIMAL(20,2),
    total_operating_revenue DECIMAL(20,2),
    operating_revenue_yoy_growth DECIMAL(10,4),
    operating_expense_cost_of_sales DECIMAL(20,2),
    operating_expense_selling_expenses DECIMAL(20,2),
    operating_expense_administrative_expenses DECIMAL(20,2),
    operating_expense_financial_expenses DECIMAL(20,2),
    operating_expense_rnd_expenses DECIMAL(20,2),
    operating_expense_taxes_and_surcharges DECIMAL(20,2),
    total_operating_expenses DECIMAL(20,2),
    operating_profit DECIMAL(20,2),
    total_profit DECIMAL(20,2),
    asset_impairment_loss DECIMAL(20,2),
    credit_impairment_loss DECIMAL(20,2),
    CONSTRAINT income_sheet_pk PRIMARY KEY (stock_code, report_year, report_period)
);
CREATE UNIQUE INDEX income_sheet_serial_number_uq ON income_sheet (serial_number);
CREATE INDEX income_sheet_year_period_idx ON income_sheet (report_year, report_period);
ALTER TABLE income_sheet ADD CONSTRAINT income_sheet_report_period_chk CHECK (report_period IN ('Q1', 'HY', 'Q3', 'FY'));


DROP TABLE IF EXISTS cash_flow_sheet;
CREATE TABLE cash_flow_sheet (
    serial_number INTEGER NOT NULL,
    stock_code VARCHAR(32) NOT NULL,
    stock_abbr VARCHAR(128),
    company_name VARCHAR(255),
    report_year INTEGER NOT NULL,
    report_period VARCHAR(8) NOT NULL,
    net_cash_flow DECIMAL(20,2),
    net_cash_flow_yoy_growth DECIMAL(10,4),
    operating_cf_net_amount DECIMAL(20,2),
    operating_cf_ratio_of_net_cf DECIMAL(10,4),
    operating_cf_cash_from_sales DECIMAL(20,2),
    investing_cf_net_amount DECIMAL(20,2),
    investing_cf_ratio_of_net_cf DECIMAL(10,4),
    investing_cf_cash_for_investments DECIMAL(20,2),
    investing_cf_cash_from_investment_recovery DECIMAL(20,2),
    financing_cf_cash_from_borrowing DECIMAL(20,2),
    financing_cf_cash_for_debt_repayment DECIMAL(20,2),
    financing_cf_net_amount DECIMAL(20,2),
    financing_cf_ratio_of_net_cf DECIMAL(10,4),
    CONSTRAINT cash_flow_sheet_pk PRIMARY KEY (stock_code, report_year, report_period)
);
CREATE UNIQUE INDEX cash_flow_sheet_serial_number_uq ON cash_flow_sheet (serial_number);
CREATE INDEX cash_flow_sheet_year_period_idx ON cash_flow_sheet (report_year, report_period);
ALTER TABLE cash_flow_sheet ADD CONSTRAINT cash_flow_sheet_report_period_chk CHECK (report_period IN ('Q1', 'HY', 'Q3', 'FY'));
