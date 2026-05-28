# AGENTS.md - Verticalizacion SaaS

Dominio nuevo para Fase 10. Scope: `saas-version/backend/app_saas/verticals/`.

## Reglas

- Mantener los packs idempotentes por tenant.
- No activar triggers, flows o campanas automaticamente sin preflight humano.
- No crear agentes automaticamente salvo que el payload lo solicite.
- Preservar `tenant_id` en cada query y llamar `set_tenant_context` desde el router.
- No duplicar recursos si el pack se aplica mas de una vez.
- No hardcodear secretos, credenciales ni endpoints externos.
- Mantener compatibilidad con CRM, Campaigns y AI Agents existentes.

## Zonas Sensibles

- `saas_tenants.industry_code` define el onboarding vertical del tenant.
- `vertical_pack_json` guarda snapshot del pack aplicado; no debe contener datos sensibles.
- Triggers sembrados por pack deben quedar `is_active = FALSE`.
- Flows sembrados por pack deben quedar `status = 'draft'`.
- La creacion de agentes debe respetar limites de plan y tipos permitidos.

