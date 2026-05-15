-- Emergency: if API code expects cod_network_* on public.orders but Alembic did not run,
-- execute this in PgWeb / psql against the SAME database as DATABASE_URL (then restart API).
-- Safe to run multiple times (IF NOT EXISTS).

ALTER TABLE public.orders ADD COLUMN IF NOT EXISTS cod_network_lead_id BIGINT;
ALTER TABLE public.orders ADD COLUMN IF NOT EXISTS cod_network_sent_at TIMESTAMPTZ;
ALTER TABLE public.orders ADD COLUMN IF NOT EXISTS cod_network_error TEXT;
