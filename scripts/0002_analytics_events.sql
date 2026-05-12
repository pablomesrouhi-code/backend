-- Standalone DDL for analytics_events (mirrors Alembic 0002_analytics_events).
-- Run against the same database as DATABASE_URL after 0001_initial is applied.

CREATE TABLE IF NOT EXISTS analytics_events (
    id UUID NOT NULL,
    event_type VARCHAR(64) NOT NULL,
    path TEXT NULL,
    referrer TEXT NULL,
    ip_address TEXT NULL,
    user_agent TEXT NULL,
    country_iso VARCHAR(8) NULL,
    mm_risk_score NUMERIC(10, 4) NULL,
    mm_is_vpn BOOLEAN NULL,
    mm_is_proxy BOOLEAN NULL,
    mm_is_tor BOOLEAN NULL,
    mm_is_hosting BOOLEAN NULL,
    ipqs_vpn BOOLEAN NULL,
    ipqs_proxy BOOLEAN NULL,
    ipqs_tor BOOLEAN NULL,
    counts_as_trusted BOOLEAN NOT NULL,
    raw_flags JSONB NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    CONSTRAINT analytics_events_pkey PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS ix_analytics_events_created_at ON analytics_events (created_at);

CREATE INDEX IF NOT EXISTS ix_analytics_events_counts_trusted_created ON analytics_events (counts_as_trusted, created_at);

CREATE INDEX IF NOT EXISTS ix_analytics_events_event_type_created ON analytics_events (event_type, created_at);
