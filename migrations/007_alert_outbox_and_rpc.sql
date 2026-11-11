-- ==============================================================================
-- PriceWatch: Alert Outbox & Atomic Batch Claim RPC
-- Migration: 007_alert_outbox_and_rpc.sql
-- ==============================================================================

CREATE TABLE IF NOT EXISTS public.alert_outbox (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chat_id BIGINT NOT NULL,
    message_html TEXT NOT NULL,
    photo_url TEXT,
    reply_markup JSONB,
    status TEXT NOT NULL DEFAULT 'PENDING', -- PENDING, PROCESSING, SENT, FAILED
    attempts INT NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_outbox_pending ON public.alert_outbox (status, next_attempt_at)
WHERE status = 'PENDING';

ALTER TABLE public.alert_outbox ENABLE ROW LEVEL SECURITY;

-- Atomic batch claim RPC for Tornado outbox drainer (FOR UPDATE SKIP LOCKED)
CREATE OR REPLACE FUNCTION claim_outbox_alerts(p_batch_size INT)
RETURNS SETOF public.alert_outbox
LANGUAGE sql
SECURITY DEFINER
AS $$
    UPDATE public.alert_outbox
    SET 
        status = 'PROCESSING',
        attempts = attempts + 1
    WHERE id IN (
        SELECT id
        FROM public.alert_outbox
        WHERE status = 'PENDING'
          AND next_attempt_at <= NOW()
          AND attempts < 5
        ORDER BY created_at ASC
        LIMIT p_batch_size
        FOR UPDATE SKIP LOCKED
    )
    RETURNING *;
$$;
