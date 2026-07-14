-- 用于 Agent 本地演示的最小合成数据；不包含任何真实公司或财报数据。
-- 表、字段、主键和报告期取值与正式财务表保持一致。
CREATE TABLE company_dim (
    stock_code VARCHAR(20) PRIMARY KEY,
    stock_abbr VARCHAR(100) NOT NULL,
    company_name VARCHAR(200) NOT NULL
);

CREATE TABLE income_sheet (
    serial_number INTEGER NOT NULL,
    stock_code VARCHAR(32) NOT NULL REFERENCES company_dim(stock_code),
    stock_abbr VARCHAR(128),
    company_name VARCHAR(255),
    report_year INTEGER NOT NULL,
    report_period VARCHAR(8) NOT NULL,
    net_profit DECIMAL(20, 2),
    net_profit_yoy_growth DECIMAL(10, 4),
    total_operating_revenue DECIMAL(20, 2),
    operating_revenue_yoy_growth DECIMAL(10, 4),
    operating_profit DECIMAL(20, 2),
    total_profit DECIMAL(20, 2),
    CONSTRAINT income_sheet_pk PRIMARY KEY (stock_code, report_year, report_period),
    CONSTRAINT income_sheet_report_period_chk CHECK (report_period IN ('Q1', 'HY', 'Q3', 'FY')),
    CONSTRAINT income_sheet_serial_number_uq UNIQUE (serial_number)
);

CREATE TABLE balance_sheet (
    serial_number INTEGER NOT NULL,
    stock_code VARCHAR(32) NOT NULL REFERENCES company_dim(stock_code),
    stock_abbr VARCHAR(128),
    company_name VARCHAR(255),
    report_year INTEGER NOT NULL,
    report_period VARCHAR(8) NOT NULL,
    asset_cash_and_cash_equivalents DECIMAL(20, 2),
    asset_accounts_receivable DECIMAL(20, 2),
    asset_inventory DECIMAL(20, 2),
    asset_total_assets DECIMAL(20, 2),
    liability_total_liabilities DECIMAL(20, 2),
    liability_and_equity_total DECIMAL(20, 2),
    equity_total_equity DECIMAL(20, 2),
    CONSTRAINT balance_sheet_pk PRIMARY KEY (stock_code, report_year, report_period),
    CONSTRAINT balance_sheet_report_period_chk CHECK (report_period IN ('Q1', 'HY', 'Q3', 'FY')),
    CONSTRAINT balance_sheet_serial_number_uq UNIQUE (serial_number)
);

CREATE TABLE cash_flow_sheet (
    serial_number INTEGER NOT NULL,
    stock_code VARCHAR(32) NOT NULL REFERENCES company_dim(stock_code),
    stock_abbr VARCHAR(128),
    company_name VARCHAR(255),
    report_year INTEGER NOT NULL,
    report_period VARCHAR(8) NOT NULL,
    net_cash_flow DECIMAL(20, 2),
    operating_cf_net_amount DECIMAL(20, 2),
    investing_cf_net_amount DECIMAL(20, 2),
    financing_cf_net_amount DECIMAL(20, 2),
    CONSTRAINT cash_flow_sheet_pk PRIMARY KEY (stock_code, report_year, report_period),
    CONSTRAINT cash_flow_sheet_report_period_chk CHECK (report_period IN ('Q1', 'HY', 'Q3', 'FY')),
    CONSTRAINT cash_flow_sheet_serial_number_uq UNIQUE (serial_number)
);

INSERT INTO company_dim (stock_code, stock_abbr, company_name) VALUES
    ('DEMO001', '星河医药', '星河医药股份有限公司'),
    ('DEMO002', '远景健康', '远景健康科技有限公司'),
    ('DEMO003', '启明生物', '启明生物制药有限公司');

INSERT INTO income_sheet (
    serial_number, stock_code, stock_abbr, company_name, report_year, report_period,
    total_operating_revenue, net_profit, operating_profit, total_profit
) VALUES
    (1, 'DEMO001', '星河医药', '星河医药股份有限公司', 2022, 'FY', 1200000000, 150000000, 180000000, 175000000),
    (2, 'DEMO001', '星河医药', '星河医药股份有限公司', 2023, 'FY', 1380000000, 180000000, 215000000, 210000000),
    (3, 'DEMO001', '星河医药', '星河医药股份有限公司', 2024, 'FY', 1560000000, 220000000, 265000000, 258000000),
    (4, 'DEMO002', '远景健康', '远景健康科技有限公司', 2022, 'FY', 980000000, 110000000, 135000000, 130000000),
    (5, 'DEMO002', '远景健康', '远景健康科技有限公司', 2023, 'FY', 1120000000, 125000000, 155000000, 150000000),
    (6, 'DEMO002', '远景健康', '远景健康科技有限公司', 2024, 'FY', 1400000000, 175000000, 215000000, 208000000),
    (7, 'DEMO003', '启明生物', '启明生物制药有限公司', 2022, 'FY', 760000000, 80000000, 96000000, 92000000),
    (8, 'DEMO003', '启明生物', '启明生物制药有限公司', 2023, 'FY', 900000000, 105000000, 128000000, 123000000),
    (9, 'DEMO003', '启明生物', '启明生物制药有限公司', 2024, 'FY', 1080000000, 145000000, 178000000, 171000000);

INSERT INTO balance_sheet (
    serial_number, stock_code, stock_abbr, company_name, report_year, report_period,
    asset_total_assets, liability_total_liabilities, liability_and_equity_total, equity_total_equity
) VALUES
    (1, 'DEMO001', '星河医药', '星河医药股份有限公司', 2022, 'FY', 2100000000, 900000000, 2100000000, 1200000000),
    (2, 'DEMO001', '星河医药', '星河医药股份有限公司', 2023, 'FY', 2350000000, 980000000, 2350000000, 1370000000),
    (3, 'DEMO001', '星河医药', '星河医药股份有限公司', 2024, 'FY', 2700000000, 1080000000, 2700000000, 1620000000),
    (4, 'DEMO002', '远景健康', '远景健康科技有限公司', 2022, 'FY', 1800000000, 850000000, 1800000000, 950000000),
    (5, 'DEMO002', '远景健康', '远景健康科技有限公司', 2023, 'FY', 1950000000, 900000000, 1950000000, 1050000000),
    (6, 'DEMO002', '远景健康', '远景健康科技有限公司', 2024, 'FY', 2250000000, 980000000, 2250000000, 1270000000),
    (7, 'DEMO003', '启明生物', '启明生物制药有限公司', 2022, 'FY', 1450000000, 720000000, 1450000000, 730000000),
    (8, 'DEMO003', '启明生物', '启明生物制药有限公司', 2023, 'FY', 1600000000, 760000000, 1600000000, 840000000),
    (9, 'DEMO003', '启明生物', '启明生物制药有限公司', 2024, 'FY', 1750000000, 810000000, 1750000000, 940000000);

INSERT INTO cash_flow_sheet (
    serial_number, stock_code, stock_abbr, company_name, report_year, report_period,
    net_cash_flow, operating_cf_net_amount, investing_cf_net_amount, financing_cf_net_amount
) VALUES
    (1, 'DEMO001', '星河医药', '星河医药股份有限公司', 2022, 'FY', 90000000, 190000000, -60000000, -40000000),
    (2, 'DEMO001', '星河医药', '星河医药股份有限公司', 2023, 'FY', 110000000, 220000000, -70000000, -40000000),
    (3, 'DEMO001', '星河医药', '星河医药股份有限公司', 2024, 'FY', 135000000, 260000000, -80000000, -45000000),
    (4, 'DEMO002', '远景健康', '远景健康科技有限公司', 2022, 'FY', 65000000, 145000000, -45000000, -35000000),
    (5, 'DEMO002', '远景健康', '远景健康科技有限公司', 2023, 'FY', 75000000, 165000000, -50000000, -40000000),
    (6, 'DEMO002', '远景健康', '远景健康科技有限公司', 2024, 'FY', 100000000, 210000000, -65000000, -45000000),
    (7, 'DEMO003', '启明生物', '启明生物制药有限公司', 2022, 'FY', 45000000, 100000000, -30000000, -25000000),
    (8, 'DEMO003', '启明生物', '启明生物制药有限公司', 2023, 'FY', 55000000, 120000000, -35000000, -30000000),
    (9, 'DEMO003', '启明生物', '启明生物制药有限公司', 2024, 'FY', 70000000, 155000000, -45000000, -40000000);
