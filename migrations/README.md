# Migraciones SaaS

## Orden recomendado
1. `001_saas_core.sql`
2. `002_tenant_columns_non_breaking.sql`
3. `003_conversations_cutover.sql`
4. `004_rls_policies.sql`
5. `005_saas_webhook_events.sql`
6. `006_saas_crm_core.sql`
7. `007_webhook_signature_hardening.sql`
8. `008_outbound_messages.sql`

## Estrategia
1. Aplicar primero en `dev`.
2. Validar en `staging` con snapshot real anonimizado.
3. Ejecutar `prod` por ventanas controladas.

## Perfiles
1. `core`: aplica migraciones SaaS puras (`001`, `005`, `006`, `007`, `008`, futuras core).
2. `legacy`: aplica tambien migraciones de conversion desde el sistema actual (`002`, `003`, `004`).

## Importante
`003_conversations_cutover.sql` es un corte potencialmente disruptivo.
Debe ejecutarse solo despues de validar compatibilidad de queries y workers.
