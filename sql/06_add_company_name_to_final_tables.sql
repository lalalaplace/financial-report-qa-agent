BEGIN;

ALTER TABLE IF EXISTS public.balance_sheet
    ADD COLUMN IF NOT EXISTS company_name VARCHAR(255);

ALTER TABLE IF EXISTS public.income_sheet
    ADD COLUMN IF NOT EXISTS company_name VARCHAR(255);

ALTER TABLE IF EXISTS public.cash_flow_sheet
    ADD COLUMN IF NOT EXISTS company_name VARCHAR(255);

COMMIT;
