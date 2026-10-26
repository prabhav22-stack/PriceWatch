-- ==============================================================================
-- PriceWatch 2.0: Canonical Schema & Scheduling Engine
-- Migration: 001_initial_v2_schema.sql
-- ==============================================================================

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- 1. USERS TABLE (Telegram Identity & Settings)
CREATE TABLE IF NOT EXISTS public.users (
    telegram_id BIGINT PRIMARY KEY,               -- Telegram user ID (64-bit integer)
    username TEXT,
    first_name TEXT,
    default_pincode VARCHAR(10),                  -- Default Indian pincode (e.g. '842002')
    is_active BOOLEAN NOT NULL DEFAULT TRUE,      -- Set FALSE if user blocks the bot (HTTP 403)
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 2. CANONICAL LISTINGS (Deduplicated unique Store + Product + Variant + Pincode)
CREATE TABLE IF NOT EXISTS public.canonical_listings (
    id BIGSERIAL PRIMARY KEY,
    provider_code VARCHAR(64) NOT NULL,           -- e.g. 'shopify:nakpro.com', 'amazon_fresh'
    provider_tier SMALLINT NOT NULL DEFAULT 1,    -- 1=API/JSON, 2=LD+JSON, 3=HTML, 4=Playwright
    external_product_id VARCHAR(128) NOT NULL,    -- ASIN, Shopify handle, or URL hash
    external_variant_id VARCHAR(128) NOT NULL DEFAULT 'default',
    pincode VARCHAR(10) NOT NULL DEFAULT '',      -- '' for national pricing, '842002' for regional
    canonical_url TEXT NOT NULL,
    product_title TEXT NOT NULL,
    variant_title TEXT,                           -- e.g. '1 kg / Chocolate'
    package_quantity VARCHAR(64),                 -- e.g. '1000g'
    currency CHAR(3) NOT NULL DEFAULT 'INR',

    -- Current materialized state (All prices in integer PAISE: Rs 1,499.00 = 149900)
    last_price_paise BIGINT,
    last_mrp_paise BIGINT,
    last_available BOOLEAN,
    last_seller_name TEXT,
    last_checked_at TIMESTAMPTZ,
    last_changed_at TIMESTAMPTZ,

    -- Scheduling, Leasing & Backoff State
    is_monitored BOOLEAN NOT NULL DEFAULT TRUE,   -- Active while has active subscriptions
    check_interval_minutes INTEGER NOT NULL DEFAULT 30,
    next_check_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    locked_until TIMESTAMPTZ,                     -- Lease expiration timestamp
    lock_owner VARCHAR(128),                      -- Worker ID / GitHub Run ID
    consecutive_failures SMALLINT NOT NULL DEFAULT 0,
    last_error_code VARCHAR(64),
    last_error_message TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_canonical_listing UNIQUE (provider_code, external_product_id, external_variant_id, pincode),
    CONSTRAINT chk_prices_positive CHECK (
        (last_price_paise IS NULL OR last_price_paise > 0) AND
        (last_mrp_paise IS NULL OR last_mrp_paise >= last_price_paise)
    )
);

-- 3. USER SUBSCRIPTIONS (Many-to-Many link between Users and Canonical Listings)
CREATE TABLE IF NOT EXISTS public.subscriptions (
    id BIGSERIAL PRIMARY KEY,
    telegram_id BIGINT NOT NULL REFERENCES public.users(telegram_id) ON DELETE CASCADE,
    listing_id BIGINT NOT NULL REFERENCES public.canonical_listings(id) ON DELETE CASCADE,
    target_price_paise BIGINT NOT NULL CHECK (target_price_paise > 0),
    notify_on_restock BOOLEAN NOT NULL DEFAULT TRUE,
    notify_on_further_drop_pct SMALLINT NOT NULL DEFAULT 2, -- Re-alert if price drops >= 2% below last_alerted
    is_active BOOLEAN NOT NULL DEFAULT TRUE,

    -- Per-subscription alert state
    last_alerted_price_paise BIGINT,
    last_alerted_at TIMESTAMPTZ,
    alert_rearmed BOOLEAN NOT NULL DEFAULT TRUE,  -- Reset to TRUE when price rises >3% above target or OOS

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_user_listing UNIQUE (telegram_id, listing_id)
);

-- 4. PRICE OBSERVATIONS (Compact Price History)
CREATE TABLE IF NOT EXISTS public.price_observations (
    id BIGSERIAL PRIMARY KEY,
    listing_id BIGINT NOT NULL REFERENCES public.canonical_listings(id) ON DELETE CASCADE,
    price_paise BIGINT,                           -- NULL if Out of Stock with hidden price
    mrp_paise BIGINT,
    available BOOLEAN NOT NULL,
    seller_name TEXT,
    extraction_method VARCHAR(32) NOT NULL,       -- e.g. 'shopify_js', 'json_ld', 'playwright_dom'
    is_verified BOOLEAN NOT NULL DEFAULT TRUE,
    observed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 5. NOTIFICATION LOG (Transactional Outbox & Deduplication Ledger)
CREATE TABLE IF NOT EXISTS public.notification_log (
    id BIGSERIAL PRIMARY KEY,
    subscription_id BIGINT NOT NULL REFERENCES public.subscriptions(id) ON DELETE CASCADE,
    observation_id BIGINT REFERENCES public.price_observations(id) ON DELETE SET NULL,
    alert_type VARCHAR(32) NOT NULL,              -- 'TARGET_REACHED', 'FURTHER_DROP', 'RESTOCK_AT_TARGET'
    price_paise BIGINT NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL UNIQUE, -- Deterministic key preventing duplicate alerts
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING',-- 'PENDING', 'SENT', 'FAILED_RETRYABLE', 'FAILED_PERMANENT'
    telegram_message_id BIGINT,
    retry_count SMALLINT NOT NULL DEFAULT 0,
    next_retry_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    error_detail TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sent_at TIMESTAMPTZ
);

-- 6. JOB RUNS (Observability & Worker Audit Log)
CREATE TABLE IF NOT EXISTS public.job_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    worker_id VARCHAR(128) NOT NULL,              -- e.g. 'gha-http-run-9812374'
    tier_filter VARCHAR(16) NOT NULL,             -- 'HTTP' or 'BROWSER'
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    listings_claimed INTEGER NOT NULL DEFAULT 0,
    listings_succeeded INTEGER NOT NULL DEFAULT 0,
    listings_failed INTEGER NOT NULL DEFAULT 0,
    alerts_sent INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(20) NOT NULL DEFAULT 'RUNNING'
);

-- ==============================================================================
-- PERFORMANCE INDEXES
-- ==============================================================================

-- Fast due-check polling for workers (Partial index)
CREATE INDEX IF NOT EXISTS idx_listings_due_check
    ON public.canonical_listings (provider_tier, next_check_at)
    WHERE is_monitored = TRUE;

-- Fast lookup of active subscriptions when a listing price is updated
CREATE INDEX IF NOT EXISTS idx_subscriptions_active_listing
    ON public.subscriptions (listing_id)
    WHERE is_active = TRUE;

-- Fast user tracking view
CREATE INDEX IF NOT EXISTS idx_subscriptions_user_active
    ON public.subscriptions (telegram_id)
    WHERE is_active = TRUE;

-- Fast rolling median and price history lookup
CREATE INDEX IF NOT EXISTS idx_observations_listing_time
    ON public.price_observations (listing_id, observed_at DESC);

-- Outbox worker index for pending/retryable notifications
CREATE INDEX IF NOT EXISTS idx_notifications_pending
    ON public.notification_log (next_retry_at)
    WHERE status IN ('PENDING', 'FAILED_RETRYABLE');

-- ==============================================================================
-- ATOMIC WORKER BATCH LEASE FUNCTION (FOR UPDATE SKIP LOCKED)
-- ==============================================================================

CREATE OR REPLACE FUNCTION public.claim_due_listings(
    p_worker_id VARCHAR,
    p_max_tier SMALLINT,
    p_min_tier SMALLINT DEFAULT 1,
    p_batch_size INTEGER DEFAULT 25,
    p_lease_seconds INTEGER DEFAULT 300
)
RETURNS SETOF public.canonical_listings
LANGUAGE sql
AS $$
    UPDATE public.canonical_listings
    SET
        locked_until = NOW() + make_interval(secs => p_lease_seconds),
        lock_owner = p_worker_id,
        updated_at = NOW()
    WHERE id IN (
        SELECT id
        FROM public.canonical_listings
        WHERE is_monitored = TRUE
          AND provider_tier BETWEEN p_min_tier AND p_max_tier
          AND next_check_at <= NOW()
          AND (locked_until IS NULL OR locked_until < NOW())
        ORDER BY next_check_at ASC
        LIMIT p_batch_size
        FOR UPDATE SKIP LOCKED
    )
    RETURNING *;
$$;
