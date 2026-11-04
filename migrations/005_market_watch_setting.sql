-- ==============================================================================
-- PriceWatch: Market Watch Brand Discount & Price Crash Alerts Setting
-- Migration: 005_market_watch_setting.sql
-- ==============================================================================

ALTER TABLE public.users ADD COLUMN IF NOT EXISTS market_watch_enabled BOOLEAN NOT NULL DEFAULT FALSE;
