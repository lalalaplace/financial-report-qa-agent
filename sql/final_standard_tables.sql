-- 附件3最终标准表建表 SQL
-- 说明：
-- 1. 字段完全按“附件3：数据库-表名及字段说明.xlsx”中的三张表定义。
-- 2. 不保留 *_raw / *_num / *_method / file_id / company_id / created_at / updated_at 等工程中间字段。
-- 3. 当前沿用你现有 pipeline 的表名：balance_sheet / income / cash_flow。
-- 4. 若你想严格按“数据库表名”sheet中的英文名称，可将 income 改为 income_sheet、cash_flow 改为 cash_flow_sheet。

DROP TABLE IF EXISTS balance_sheet;
CREATE TABLE balance_sheet (
    serial_number INT,
    stock_code VARCHAR(20) NOT NULL,
    stock_abbr VARCHAR(50),
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
    report_period VARCHAR(20) NOT NULL,
    report_year INT NOT NULL,
    CONSTRAINT uk_balance_sheet UNIQUE (stock_code, report_year, report_period)
);

DROP TABLE IF EXISTS income;
CREATE TABLE income (
    serial_number INT,
    stock_code VARCHAR(20) NOT NULL,
    stock_abbr VARCHAR(50),
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
    report_period VARCHAR(20) NOT NULL,
    report_year INT NOT NULL,
    CONSTRAINT uk_income UNIQUE (stock_code, report_year, report_period)
);

DROP TABLE IF EXISTS cash_flow;
CREATE TABLE cash_flow (
    serial_number INT,
    stock_code VARCHAR(20) NOT NULL,
    stock_abbr VARCHAR(50),
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
    report_period VARCHAR(20) NOT NULL,
    report_year INT NOT NULL,
    CONSTRAINT uk_cash_flow UNIQUE (stock_code, report_year, report_period)
);
