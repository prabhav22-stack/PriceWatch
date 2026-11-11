-- Migration 006: Enable Row Level Security (RLS) on all public tables
-- Resolves Supabase critical security alert: rls_disabled_in_public
-- 
-- Backend Python services (Telegram bot, polling workers, TMA API server)
-- connect using SUPABASE_SERVICE_ROLE_KEY, which bypasses RLS automatically.
-- Enabling RLS prevents unauthorized external access via the public anon key.

-- Core schema tables
ALTER TABLE IF EXISTS public.users ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.canonical_listings ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.price_observations ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.notification_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.job_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.amul_stock_history ENABLE ROW LEVEL SECURITY;

-- Legacy tables if present
ALTER TABLE IF EXISTS public.price_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.tracked_products ENABLE ROW LEVEL SECURITY;
