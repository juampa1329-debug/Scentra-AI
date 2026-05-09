-- 007_webhook_signature_hardening.sql
-- Endurece webhooks con firma HMAC derivada por endpoint.

ALTER TABLE saas_webhook_endpoints
ADD COLUMN IF NOT EXISTS signature_secret_salt TEXT NOT NULL DEFAULT '';

ALTER TABLE saas_webhook_endpoints
ADD COLUMN IF NOT EXISTS signature_required BOOLEAN NOT NULL DEFAULT FALSE;
