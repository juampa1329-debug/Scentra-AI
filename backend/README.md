# Backend SaaS (plan de implementacion)

## Meta
Exponer API SaaS bajo `/saas/v1` con auth, tenant context, RBAC y procesamiento async.

## Modulos sugeridos
1. `app_saas/auth/`
2. `app_saas/tenants/`
3. `app_saas/integrations/`
4. `app_saas/billing/`
5. `app_saas/workers/`
6. `app_saas/shared/`

## Primeros entregables
1. Middleware `TenantContext`.
2. Guardias `require_role`.
3. Endpoints:
   - `POST /saas/v1/auth/login`
   - `POST /saas/v1/auth/register`
   - `POST /saas/v1/auth/refresh`
   - `POST /saas/v1/auth/switch-tenant`
4. Endpoints:
   - `GET /saas/v1/conversations`
   - `GET /saas/v1/conversations/{phone}/messages`

## Implementado en este scaffold
1. `app_saas/main.py` con routers bajo `/saas/v1`.
2. `auth` con registro, login, refresh, switch tenant y `me`.
3. `tenants` con listado, creacion y patch del tenant activo.
4. `crm` con conversaciones/mensajes filtrados por `tenant_id`.
5. `integrations` con listado y upsert por tenant.
6. `billing` con subscription, limits y usage.
7. `workers/runner.py` como entrypoint inicial para workers.
8. `tools/migrate.py` para aplicar migraciones SQL versionadas.
9. `webhooks` con endpoints por tenant, verificacion, firma HMAC, eventos idempotentes y procesamiento manual.
10. `crm` con envio de respuestas al inbox usando cola `saas_outbound_messages`.
11. `workers/dispatch.py` como worker base para mensajes salientes.
12. `billing` con overview de plan/uso, listado de planes y cambio de plan local para pruebas.
13. Enforcement de limites en integraciones y mensajes salientes.

## Variables minimas
1. `DATABASE_URL`
2. `SAAS_JWT_SECRET`
3. `SAAS_CORS_ORIGINS`
