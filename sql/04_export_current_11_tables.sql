--
-- PostgreSQL database dump
--

\restrict yJRM4MXstJuCOafb102ybiW51eo0magj8tTn7VaxkoYpJJ7gEXiOkCaVKNb53jo

-- Dumped from database version 18.3
-- Dumped by pg_dump version 18.3

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: attachment3_extract_result; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.attachment3_extract_result (
    result_id bigint NOT NULL,
    file_id bigint NOT NULL,
    company_id bigint,
    stock_code character varying(20),
    stock_abbr character varying(100),
    report_year integer,
    report_period character varying(20),
    target_table character varying(50) NOT NULL,
    field_code character varying(100),
    field_name_cn character varying(200),
    value_text text,
    source_page_range character varying(50),
    source_text text,
    extract_method character varying(50),
    llm_status character varying(50),
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    raw_line_name text,
    normalized_line_name text,
    source_page integer,
    source_column_role character varying(64),
    unit character varying(32),
    confidence double precision,
    extra_info_json text
);


--
-- Name: attachment3_extract_result_result_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.attachment3_extract_result_result_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: attachment3_extract_result_result_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.attachment3_extract_result_result_id_seq OWNED BY public.attachment3_extract_result.result_id;


--
-- Name: attachment3_field_dict; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.attachment3_field_dict (
    field_id bigint NOT NULL,
    target_table character varying(50) NOT NULL,
    field_code character varying(100) NOT NULL,
    field_name_cn character varying(200) NOT NULL,
    data_type character varying(50),
    field_desc text,
    sort_order integer
);


--
-- Name: attachment3_field_dict_field_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.attachment3_field_dict_field_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: attachment3_field_dict_field_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.attachment3_field_dict_field_id_seq OWNED BY public.attachment3_field_dict.field_id;


--
-- Name: attachment3_validation_result; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.attachment3_validation_result (
    validation_id bigint NOT NULL,
    file_id bigint NOT NULL,
    target_table character varying(50),
    validation_rule character varying(200),
    validation_status character varying(50),
    validation_message text,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: attachment3_validation_result_validation_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.attachment3_validation_result_validation_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: attachment3_validation_result_validation_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.attachment3_validation_result_validation_id_seq OWNED BY public.attachment3_validation_result.validation_id;


--
-- Name: balance_sheet; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.balance_sheet (
    serial_number integer NOT NULL,
    stock_code character varying(32) NOT NULL,
    stock_abbr character varying(128),
    report_year integer NOT NULL,
    report_period character varying(8) NOT NULL,
    asset_cash_and_cash_equivalents numeric(20,2),
    asset_accounts_receivable numeric(20,2),
    asset_inventory numeric(20,2),
    asset_trading_financial_assets numeric(20,2),
    asset_construction_in_progress numeric(20,2),
    asset_total_assets numeric(20,2),
    asset_total_assets_yoy_growth numeric(10,4),
    liability_accounts_payable numeric(20,2),
    liability_advance_from_customers numeric(20,2),
    liability_total_liabilities numeric(20,2),
    liability_total_liabilities_yoy_growth numeric(10,4),
    liability_and_equity_total numeric(20,2),
    liability_contract_liabilities numeric(20,2),
    liability_short_term_loans numeric(20,2),
    asset_liability_ratio numeric(10,4),
    equity_unappropriated_profit numeric(20,2),
    equity_total_equity numeric(20,2),
    CONSTRAINT balance_sheet_report_period_chk CHECK (((report_period)::text = ANY ((ARRAY['Q1'::character varying, 'HY'::character varying, 'Q3'::character varying, 'FY'::character varying])::text[])))
);


--
-- Name: cash_flow_sheet; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cash_flow_sheet (
    serial_number integer NOT NULL,
    stock_code character varying(32) NOT NULL,
    stock_abbr character varying(128),
    report_year integer NOT NULL,
    report_period character varying(8) NOT NULL,
    net_cash_flow numeric(20,2),
    net_cash_flow_yoy_growth numeric(10,4),
    operating_cf_net_amount numeric(20,2),
    operating_cf_ratio_of_net_cf numeric(10,4),
    operating_cf_cash_from_sales numeric(20,2),
    investing_cf_net_amount numeric(20,2),
    investing_cf_ratio_of_net_cf numeric(10,4),
    investing_cf_cash_for_investments numeric(20,2),
    investing_cf_cash_from_investment_recovery numeric(20,2),
    financing_cf_cash_from_borrowing numeric(20,2),
    financing_cf_cash_for_debt_repayment numeric(20,2),
    financing_cf_net_amount numeric(20,2),
    financing_cf_ratio_of_net_cf numeric(10,4),
    CONSTRAINT cash_flow_sheet_report_period_chk CHECK (((report_period)::text = ANY ((ARRAY['Q1'::character varying, 'HY'::character varying, 'Q3'::character varying, 'FY'::character varying])::text[])))
);


--
-- Name: company_alias; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.company_alias (
    alias_id bigint NOT NULL,
    company_id bigint NOT NULL,
    alias_name character varying(200) NOT NULL,
    alias_type character varying(50) NOT NULL,
    is_primary boolean DEFAULT false,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: company_alias_alias_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.company_alias_alias_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: company_alias_alias_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.company_alias_alias_id_seq OWNED BY public.company_alias.alias_id;


--
-- Name: company_dim; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.company_dim (
    company_id bigint NOT NULL,
    stock_code character varying(6) NOT NULL,
    stock_abbr character varying(100) NOT NULL,
    company_name character varying(200) NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: company_dim_company_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.company_dim_company_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: company_dim_company_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.company_dim_company_id_seq OWNED BY public.company_dim.company_id;


--
-- Name: core_performance; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.core_performance (
    file_id bigint NOT NULL,
    company_id bigint,
    stock_code character varying(32),
    stock_abbr character varying(128),
    report_year integer,
    report_period character varying(32),
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    serial_number_raw text,
    serial_number_num numeric,
    serial_number_method character varying(64),
    stock_code_raw text,
    stock_code_num numeric,
    stock_code_method character varying(64),
    stock_abbr_raw text,
    stock_abbr_num numeric,
    stock_abbr_method character varying(64),
    eps_raw text,
    eps_num numeric,
    eps_method character varying(64),
    total_operating_revenue_raw text,
    total_operating_revenue_num numeric,
    total_operating_revenue_method character varying(64),
    operating_revenue_yoy_growth_raw text,
    operating_revenue_yoy_growth_num numeric,
    operating_revenue_yoy_growth_method character varying(64),
    operating_revenue_qoq_growth_raw text,
    operating_revenue_qoq_growth_num numeric,
    operating_revenue_qoq_growth_method character varying(64),
    net_profit_10k_yuan_raw text,
    net_profit_10k_yuan_num numeric,
    net_profit_10k_yuan_method character varying(64),
    net_profit_yoy_growth_raw text,
    net_profit_yoy_growth_num numeric,
    net_profit_yoy_growth_method character varying(64),
    net_profit_qoq_growth_raw text,
    net_profit_qoq_growth_num numeric,
    net_profit_qoq_growth_method character varying(64),
    net_asset_per_share_raw text,
    net_asset_per_share_num numeric,
    net_asset_per_share_method character varying(64),
    roe_raw text,
    roe_num numeric,
    roe_method character varying(64),
    operating_cf_per_share_raw text,
    operating_cf_per_share_num numeric,
    operating_cf_per_share_method character varying(64),
    net_profit_excl_non_recurring_raw text,
    net_profit_excl_non_recurring_num numeric,
    net_profit_excl_non_recurring_method character varying(64),
    net_profit_excl_non_recurring_yoy_raw text,
    net_profit_excl_non_recurring_yoy_num numeric,
    net_profit_excl_non_recurring_yoy_method character varying(64),
    gross_profit_margin_raw text,
    gross_profit_margin_num numeric,
    gross_profit_margin_method character varying(64),
    net_profit_margin_raw text,
    net_profit_margin_num numeric,
    net_profit_margin_method character varying(64),
    roe_weighted_excl_non_recurring_raw text,
    roe_weighted_excl_non_recurring_num numeric,
    roe_weighted_excl_non_recurring_method character varying(64),
    report_period_raw text,
    report_period_num numeric,
    report_period_method character varying(64),
    report_year_raw text,
    report_year_num numeric,
    report_year_method character varying(64)
);


--
-- Name: income_sheet; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.income_sheet (
    serial_number integer NOT NULL,
    stock_code character varying(32) NOT NULL,
    stock_abbr character varying(128),
    report_year integer NOT NULL,
    report_period character varying(8) NOT NULL,
    net_profit numeric(20,2),
    net_profit_yoy_growth numeric(10,4),
    other_income numeric(20,2),
    total_operating_revenue numeric(20,2),
    operating_revenue_yoy_growth numeric(10,4),
    operating_expense_cost_of_sales numeric(20,2),
    operating_expense_selling_expenses numeric(20,2),
    operating_expense_administrative_expenses numeric(20,2),
    operating_expense_financial_expenses numeric(20,2),
    operating_expense_rnd_expenses numeric(20,2),
    operating_expense_taxes_and_surcharges numeric(20,2),
    total_operating_expenses numeric(20,2),
    operating_profit numeric(20,2),
    total_profit numeric(20,2),
    asset_impairment_loss numeric(20,2),
    credit_impairment_loss numeric(20,2),
    CONSTRAINT income_sheet_report_period_chk CHECK (((report_period)::text = ANY ((ARRAY['Q1'::character varying, 'HY'::character varying, 'Q3'::character varying, 'FY'::character varying])::text[])))
);


--
-- Name: report_file_index; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.report_file_index (
    file_id bigint NOT NULL,
    company_id bigint,
    stock_code character varying(6),
    stock_abbr character varying(100),
    company_name character varying(200),
    file_name character varying(255) NOT NULL,
    file_path text NOT NULL,
    report_year integer,
    report_period character varying(20),
    match_method character varying(50),
    parse_status character varying(50) DEFAULT 'pending'::character varying,
    is_summary boolean,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    source_exchange character varying(32),
    report_type_text character varying(255)
);


--
-- Name: report_file_index_file_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.report_file_index_file_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: report_file_index_file_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.report_file_index_file_id_seq OWNED BY public.report_file_index.file_id;


--
-- Name: report_statement_locator; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.report_statement_locator (
    id bigint NOT NULL,
    file_id bigint NOT NULL,
    statement_type character varying(32) NOT NULL,
    page_start integer,
    page_end integer,
    locator_method character varying(64) NOT NULL,
    locator_status character varying(32) NOT NULL,
    source_text text,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    end_page_guess integer,
    title_text text,
    matched_keywords text,
    header_text text,
    is_consolidated boolean,
    is_parent_only boolean,
    locator_confidence double precision,
    candidate_rank integer,
    extra_info_json text
);


--
-- Name: report_statement_locator_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.report_statement_locator_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: report_statement_locator_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.report_statement_locator_id_seq OWNED BY public.report_statement_locator.id;


--
-- Name: attachment3_extract_result result_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.attachment3_extract_result ALTER COLUMN result_id SET DEFAULT nextval('public.attachment3_extract_result_result_id_seq'::regclass);


--
-- Name: attachment3_field_dict field_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.attachment3_field_dict ALTER COLUMN field_id SET DEFAULT nextval('public.attachment3_field_dict_field_id_seq'::regclass);


--
-- Name: attachment3_validation_result validation_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.attachment3_validation_result ALTER COLUMN validation_id SET DEFAULT nextval('public.attachment3_validation_result_validation_id_seq'::regclass);


--
-- Name: company_alias alias_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.company_alias ALTER COLUMN alias_id SET DEFAULT nextval('public.company_alias_alias_id_seq'::regclass);


--
-- Name: company_dim company_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.company_dim ALTER COLUMN company_id SET DEFAULT nextval('public.company_dim_company_id_seq'::regclass);


--
-- Name: report_file_index file_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.report_file_index ALTER COLUMN file_id SET DEFAULT nextval('public.report_file_index_file_id_seq'::regclass);


--
-- Name: report_statement_locator id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.report_statement_locator ALTER COLUMN id SET DEFAULT nextval('public.report_statement_locator_id_seq'::regclass);


--
-- Name: attachment3_extract_result attachment3_extract_result_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.attachment3_extract_result
    ADD CONSTRAINT attachment3_extract_result_pkey PRIMARY KEY (result_id);


--
-- Name: attachment3_field_dict attachment3_field_dict_field_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.attachment3_field_dict
    ADD CONSTRAINT attachment3_field_dict_field_code_key UNIQUE (field_code);


--
-- Name: attachment3_field_dict attachment3_field_dict_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.attachment3_field_dict
    ADD CONSTRAINT attachment3_field_dict_pkey PRIMARY KEY (field_id);


--
-- Name: attachment3_validation_result attachment3_validation_result_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.attachment3_validation_result
    ADD CONSTRAINT attachment3_validation_result_pkey PRIMARY KEY (validation_id);


--
-- Name: balance_sheet balance_sheet_pk; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.balance_sheet
    ADD CONSTRAINT balance_sheet_pk PRIMARY KEY (stock_code, report_year, report_period);


--
-- Name: cash_flow_sheet cash_flow_sheet_pk; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cash_flow_sheet
    ADD CONSTRAINT cash_flow_sheet_pk PRIMARY KEY (stock_code, report_year, report_period);


--
-- Name: company_alias company_alias_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.company_alias
    ADD CONSTRAINT company_alias_pkey PRIMARY KEY (alias_id);


--
-- Name: company_dim company_dim_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.company_dim
    ADD CONSTRAINT company_dim_pkey PRIMARY KEY (company_id);


--
-- Name: company_dim company_dim_stock_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.company_dim
    ADD CONSTRAINT company_dim_stock_code_key UNIQUE (stock_code);


--
-- Name: core_performance core_performance_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.core_performance
    ADD CONSTRAINT core_performance_pkey PRIMARY KEY (file_id);


--
-- Name: income_sheet income_sheet_pk; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.income_sheet
    ADD CONSTRAINT income_sheet_pk PRIMARY KEY (stock_code, report_year, report_period);


--
-- Name: report_file_index report_file_index_file_path_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.report_file_index
    ADD CONSTRAINT report_file_index_file_path_key UNIQUE (file_path);


--
-- Name: report_file_index report_file_index_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.report_file_index
    ADD CONSTRAINT report_file_index_pkey PRIMARY KEY (file_id);


--
-- Name: report_statement_locator report_statement_locator_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.report_statement_locator
    ADD CONSTRAINT report_statement_locator_pkey PRIMARY KEY (id);


--
-- Name: balance_sheet_serial_number_uq; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX balance_sheet_serial_number_uq ON public.balance_sheet USING btree (serial_number);


--
-- Name: balance_sheet_year_period_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX balance_sheet_year_period_idx ON public.balance_sheet USING btree (report_year, report_period);


--
-- Name: cash_flow_sheet_serial_number_uq; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX cash_flow_sheet_serial_number_uq ON public.cash_flow_sheet USING btree (serial_number);


--
-- Name: cash_flow_sheet_year_period_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX cash_flow_sheet_year_period_idx ON public.cash_flow_sheet USING btree (report_year, report_period);


--
-- Name: core_performance_company_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX core_performance_company_id_idx ON public.core_performance USING btree (company_id);


--
-- Name: core_performance_report_period_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX core_performance_report_period_idx ON public.core_performance USING btree (report_year, report_period);


--
-- Name: idx_attachment3_extract_result_file_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_attachment3_extract_result_file_id ON public.attachment3_extract_result USING btree (file_id);


--
-- Name: idx_attachment3_extract_result_file_target_field; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_attachment3_extract_result_file_target_field ON public.attachment3_extract_result USING btree (file_id, target_table, field_code);


--
-- Name: idx_attachment3_extract_result_method; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_attachment3_extract_result_method ON public.attachment3_extract_result USING btree (extract_method);


--
-- Name: idx_attachment3_extract_result_target_table; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_attachment3_extract_result_target_table ON public.attachment3_extract_result USING btree (target_table);


--
-- Name: idx_attachment3_field_dict_target_table; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_attachment3_field_dict_target_table ON public.attachment3_field_dict USING btree (target_table);


--
-- Name: idx_attachment3_validation_result_file_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_attachment3_validation_result_file_id ON public.attachment3_validation_result USING btree (file_id);


--
-- Name: idx_company_alias_alias_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_company_alias_alias_name ON public.company_alias USING btree (alias_name);


--
-- Name: idx_company_alias_company_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_company_alias_company_id ON public.company_alias USING btree (company_id);


--
-- Name: idx_company_dim_company_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_company_dim_company_name ON public.company_dim USING btree (company_name);


--
-- Name: idx_company_dim_stock_abbr; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_company_dim_stock_abbr ON public.company_dim USING btree (stock_abbr);


--
-- Name: idx_report_file_index_company_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_report_file_index_company_id ON public.report_file_index USING btree (company_id);


--
-- Name: idx_report_file_index_parse_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_report_file_index_parse_status ON public.report_file_index USING btree (parse_status);


--
-- Name: idx_report_file_index_report_year_period; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_report_file_index_report_year_period ON public.report_file_index USING btree (report_year, report_period);


--
-- Name: idx_report_file_index_stock_code; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_report_file_index_stock_code ON public.report_file_index USING btree (stock_code);


--
-- Name: idx_report_statement_locator_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_report_statement_locator_status ON public.report_statement_locator USING btree (locator_status);


--
-- Name: income_sheet_serial_number_uq; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX income_sheet_serial_number_uq ON public.income_sheet USING btree (serial_number);


--
-- Name: income_sheet_year_period_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX income_sheet_year_period_idx ON public.income_sheet USING btree (report_year, report_period);


--
-- Name: uk_company_alias_company_alias_type; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uk_company_alias_company_alias_type ON public.company_alias USING btree (company_id, alias_name, alias_type);


--
-- Name: uk_report_statement_locator_file_statement; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uk_report_statement_locator_file_statement ON public.report_statement_locator USING btree (file_id, statement_type);


--
-- Name: attachment3_extract_result attachment3_extract_result_file_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.attachment3_extract_result
    ADD CONSTRAINT attachment3_extract_result_file_id_fkey FOREIGN KEY (file_id) REFERENCES public.report_file_index(file_id);


--
-- Name: attachment3_validation_result attachment3_validation_result_file_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.attachment3_validation_result
    ADD CONSTRAINT attachment3_validation_result_file_id_fkey FOREIGN KEY (file_id) REFERENCES public.report_file_index(file_id);


--
-- Name: company_alias company_alias_company_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.company_alias
    ADD CONSTRAINT company_alias_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.company_dim(company_id);


--
-- Name: report_file_index report_file_index_company_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.report_file_index
    ADD CONSTRAINT report_file_index_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.company_dim(company_id);


--
-- Name: report_statement_locator report_statement_locator_file_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.report_statement_locator
    ADD CONSTRAINT report_statement_locator_file_id_fkey FOREIGN KEY (file_id) REFERENCES public.report_file_index(file_id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

\unrestrict yJRM4MXstJuCOafb102ybiW51eo0magj8tTn7VaxkoYpJJ7gEXiOkCaVKNb53jo
