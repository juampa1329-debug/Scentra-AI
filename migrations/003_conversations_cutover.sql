-- 003_conversations_cutover.sql
-- Corte de conversations a modelo multi-tenant real.
-- Ejecutar solo despues de validar que toda la app consulta por tenant_id.

BEGIN;

-- 1) Pre-chequeo rapido (opcional)
-- SELECT phone, COUNT(*) FROM conversations GROUP BY phone HAVING COUNT(*) > 1;

-- 2) Reemplazar PK global por PK compuesta tenant+phone
ALTER TABLE conversations DROP CONSTRAINT IF EXISTS conversations_pkey;
ALTER TABLE conversations ADD CONSTRAINT conversations_pkey PRIMARY KEY (tenant_id, phone);

-- 3) Compatibilidad para mensajes (join eficiente tenant+phone)
CREATE INDEX IF NOT EXISTS idx_messages_tenant_phone ON messages (tenant_id, phone);

COMMIT;
