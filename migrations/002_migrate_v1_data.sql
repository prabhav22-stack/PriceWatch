-- ==============================================================================
-- PriceWatch 2.0: Non-destructive V1 Data Migration
-- Migration: 002_migrate_v1_data.sql
-- ==============================================================================

BEGIN;

-- 1. Migrate distinct users
INSERT INTO public.users (telegram_id, default_pincode, is_active)
SELECT DISTINCT
    telegram_id::bigint,
    MAX(COALESCE(pincode, '')),
    TRUE
FROM public.tracked_products
GROUP BY telegram_id
ON CONFLICT (telegram_id) DO NOTHING;

-- 2. Migrate distinct canonical listings (deduplicating identical URL + pincode pairs)
INSERT INTO public.canonical_listings (
    provider_code,
    provider_tier,
    external_product_id,
    external_variant_id,
    pincode,
    canonical_url,
    product_title,
    last_price_paise,
    is_monitored
)
SELECT DISTINCT ON (product_url, COALESCE(pincode, ''))
    CASE
        WHEN website ILIKE '%nakpro%' THEN 'shopify:nakpro.com'
        WHEN website ILIKE '%amazon%' THEN 'amazon_fresh'
        ELSE 'generic:' || COALESCE(website, 'unknown')
    END AS provider_code,
    CASE WHEN website ILIKE '%amazon%' THEN 4 ELSE 1 END AS provider_tier,
    md5(product_url) AS external_product_id,
    COALESCE((regexp_match(product_url, 'variant=([0-9]+)'))[1], 'default') AS external_variant_id,
    COALESCE(pincode, '') AS pincode,
    product_url AS canonical_url,
    COALESCE(product_name, 'Migrated Product') AS product_title,
    CASE WHEN last_price IS NOT NULL AND last_price > 0 THEN ROUND(last_price * 100)::BIGINT ELSE NULL END,
    BOOL_OR(active) OVER (PARTITION BY product_url, COALESCE(pincode, ''))
FROM public.tracked_products
ORDER BY product_url, COALESCE(pincode, ''), id DESC
ON CONFLICT (provider_code, external_product_id, external_variant_id, pincode) DO NOTHING;

-- 3. Migrate user subscriptions and preserve last_alerted_price to prevent duplicate alerts
INSERT INTO public.subscriptions (
    telegram_id,
    listing_id,
    target_price_paise,
    is_active,
    last_alerted_price_paise,
    alert_rearmed
)
SELECT
    tp.telegram_id::bigint,
    cl.id,
    ROUND(tp.target_price * 100)::BIGINT,
    tp.active,
    CASE WHEN tp.last_alerted_price IS NOT NULL AND tp.last_alerted_price > 0
         THEN ROUND(tp.last_alerted_price * 100)::BIGINT
         ELSE NULL
    END,
    CASE WHEN tp.last_alerted_price IS NOT NULL AND tp.last_price IS NOT NULL AND tp.last_price <= tp.target_price
         THEN FALSE
         ELSE TRUE
    END
FROM public.tracked_products tp
JOIN public.canonical_listings cl
  ON cl.canonical_url = tp.product_url
 AND cl.pincode = COALESCE(tp.pincode, '')
ON CONFLICT (telegram_id, listing_id) DO NOTHING;

COMMIT;
