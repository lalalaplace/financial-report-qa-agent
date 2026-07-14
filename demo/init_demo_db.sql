-- 用于 Agent 本地演示的最小合成数据；不包含任何真实公司或财报数据。
CREATE TABLE company_dim (
    stock_code VARCHAR(20) PRIMARY KEY,
    stock_abbr VARCHAR(100) NOT NULL,
    company_name VARCHAR(200) NOT NULL
);

CREATE TABLE income_sheet (
    stock_code VARCHAR(20) NOT NULL REFERENCES company_dim(stock_code),
    report_year INTEGER NOT NULL,
    report_period VARCHAR(20) NOT NULL DEFAULT '年报',
    revenue NUMERIC(18, 2),
    net_profit NUMERIC(18, 2),
    PRIMARY KEY (stock_code, report_year, report_period)
);

CREATE TABLE core_performance (
    stock_code VARCHAR(20) NOT NULL REFERENCES company_dim(stock_code),
    report_year INTEGER NOT NULL,
    report_period VARCHAR(20) NOT NULL DEFAULT '年报',
    roe NUMERIC(10, 4),
    gross_margin NUMERIC(10, 4),
    PRIMARY KEY (stock_code, report_year, report_period)
);

INSERT INTO company_dim (stock_code, stock_abbr, company_name) VALUES
    ('DEMO001', '星河医药', '星河医药股份有限公司'),
    ('DEMO002', '远景健康', '远景健康科技有限公司'),
    ('DEMO003', '启明生物', '启明生物制药有限公司');

INSERT INTO income_sheet (stock_code, report_year, revenue, net_profit) VALUES
    ('DEMO001', 2022, 1200000000, 150000000), ('DEMO001', 2023, 1380000000, 180000000), ('DEMO001', 2024, 1560000000, 220000000),
    ('DEMO002', 2022, 980000000, 110000000),  ('DEMO002', 2023, 1120000000, 125000000), ('DEMO002', 2024, 1400000000, 175000000),
    ('DEMO003', 2022, 760000000, 80000000),   ('DEMO003', 2023, 900000000, 105000000),  ('DEMO003', 2024, 1080000000, 145000000);

INSERT INTO core_performance (stock_code, report_year, roe, gross_margin) VALUES
    ('DEMO001', 2022, 0.1200, 0.4200), ('DEMO001', 2023, 0.1350, 0.4350), ('DEMO001', 2024, 0.1480, 0.4480),
    ('DEMO002', 2022, 0.1100, 0.3900), ('DEMO002', 2023, 0.1170, 0.4050), ('DEMO002', 2024, 0.1320, 0.4210),
    ('DEMO003', 2022, 0.0900, 0.3600), ('DEMO003', 2023, 0.1040, 0.3750), ('DEMO003', 2024, 0.1190, 0.3980);
