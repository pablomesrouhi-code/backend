-- Optional manual fix (same as Alembic 0004_drop_cod_network): run on nabtalabo DB if migrations are skipped.
ALTER TABLE public.orders DROP COLUMN IF EXISTS cod_network_error;
ALTER TABLE public.orders DROP COLUMN IF EXISTS cod_network_sent_at;
ALTER TABLE public.orders DROP COLUMN IF EXISTS cod_network_lead_id;
