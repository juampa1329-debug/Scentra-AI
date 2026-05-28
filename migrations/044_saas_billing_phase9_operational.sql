-- Phase 9 operational hardening for billing and monetization.
-- Adds lifecycle/notification metadata used by the recurring billing worker,
-- provider webhook reconciliation and tenant invoice PDFs.

ALTER TABLE saas_billing_subscriptions
    ADD COLUMN IF NOT EXISTS lifecycle_last_checked_at TIMESTAMP NULL,
    ADD COLUMN IF NOT EXISTS payment_failed_notice_sent_at TIMESTAMP NULL,
    ADD COLUMN IF NOT EXISTS trial_expired_notice_sent_at TIMESTAMP NULL,
    ADD COLUMN IF NOT EXISTS suspension_notice_sent_at TIMESTAMP NULL;

ALTER TABLE saas_billing_invoices
    ADD COLUMN IF NOT EXISTS payment_failed_notice_sent_at TIMESTAMP NULL,
    ADD COLUMN IF NOT EXISTS pdf_generated_at TIMESTAMP NULL;

ALTER TABLE saas_billing_checkout_sessions
    ADD COLUMN IF NOT EXISTS last_provider_event_at TIMESTAMP NULL;

CREATE INDEX IF NOT EXISTS idx_saas_billing_subscriptions_status_period
    ON saas_billing_subscriptions (status, current_period_end, past_due_at);

CREATE INDEX IF NOT EXISTS idx_saas_billing_invoices_status_due
    ON saas_billing_invoices (status, due_at, tenant_id);

CREATE INDEX IF NOT EXISTS idx_saas_billing_provider_events_status
    ON saas_billing_provider_events (status, provider, received_at DESC);
