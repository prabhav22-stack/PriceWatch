-- ==============================================================================
-- PriceWatch: Amul Stock History Tracking
-- Migration: 003_amul_stock_history.sql
-- ==============================================================================

CREATE TABLE IF NOT EXISTS public.amul_stock_history (
    id BIGSERIAL PRIMARY KEY,
    sku VARCHAR(128) NOT NULL,
    substore VARCHAR(64) NOT NULL,
    last_seen_in_stock_at TIMESTAMPTZ,
    first_seen_in_stock_at TIMESTAMPTZ,
    last_seen_out_of_stock_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_amul_sku_substore UNIQUE (sku, substore)
);

CREATE INDEX IF NOT EXISTS idx_amul_stock_sku_substore ON public.amul_stock_history (sku, substore);
