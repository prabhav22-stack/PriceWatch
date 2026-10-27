-- ==============================================================================
-- PriceWatch: User Preferences, Favourites, and Auto-Order Configuration
-- Migration: 004_user_preferences_and_autoorder.sql
-- ==============================================================================

ALTER TABLE public.users ADD COLUMN IF NOT EXISTS favourite_skus TEXT[] NOT NULL DEFAULT '{}';
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS tracking_style VARCHAR(16) NOT NULL DEFAULT 'always';
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS max_notify_count INTEGER NOT NULL DEFAULT 5;
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS auto_order_enabled BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS auto_order_phone VARCHAR(20);
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS auto_order_address_id TEXT;
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS auto_order_auth_token TEXT;
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS auto_order_skus TEXT[] NOT NULL DEFAULT '{}';
