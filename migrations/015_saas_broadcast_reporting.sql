-- 015_saas_broadcast_reporting.sql
-- Campos de auditoria para reportes de difusion y estados de destinatarios.

ALTER TABLE saas_broadcast_recipients
    ADD COLUMN IF NOT EXISTS delivered_at TIMESTAMP NULL,
    ADD COLUMN IF NOT EXISTS read_at TIMESTAMP NULL,
    ADD COLUMN IF NOT EXISTS replied_at TIMESTAMP NULL,
    ADD COLUMN IF NOT EXISTS failed_at TIMESTAMP NULL,
    ADD COLUMN IF NOT EXISTS provider_message_id TEXT NOT NULL DEFAULT '';

UPDATE saas_broadcast_recipients
SET sent_at = COALESCE(sent_at, queued_at, created_at)
WHERE status IN ('sent', 'delivered', 'read', 'replied')
  AND sent_at IS NULL;

UPDATE saas_broadcast_recipients
SET failed_at = COALESCE(failed_at, updated_at, created_at)
WHERE status = 'failed'
  AND failed_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_saas_broadcast_recipients_status_created
ON saas_broadcast_recipients (tenant_id, broadcast_id, status, created_at DESC);
