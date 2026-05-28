# Fase 2 - Scentra Admin en produccion

Esta fase deja el panel interno `admin.scentra-ai.online` listo para operar clientes, planes, suscripciones, feature flags y limites de AI Agents sin mezclarlo con el portal del cliente.

## Arquitectura

- Portal cliente: `https://app.scentra-ai.online`
- Portal admin: `https://admin.scentra-ai.online`
- API compartida: `https://api.scentra-ai.online`
- Base de datos: Postgres SaaS centralizada

El Admin usa la misma API SaaS, pero solo permite acceso con `platform_role`:

- `superadmin`
- `platform_admin`
- `billing_admin`
- `support`
- `viewer`

## App Coolify recomendada

Opcion A, Compose unificado:

- `docker-compose.saas.yml` incluye `admin-frontend`.
- El router Traefik `scentra_admin_https` usa la regla Host para `admin.scentra-ai.online`.
- El healthcheck interno del admin es `/health`.
- El servicio local se expone en `127.0.0.1:${SAAS_ADMIN_HOST_PORT:-8011}`.

Variables buildtime para Compose:

```env
ADMIN_VITE_API_BASE=https://api.scentra-ai.online
ADMIN_VITE_CLIENT_APP_BASE=https://app.scentra-ai.online
ADMIN_VITE_CAPTCHA_ENABLED=true
ADMIN_VITE_TURNSTILE_SITE_KEY=0x4AAAA...
ADMIN_VITE_BOOTSTRAP_ENABLED=false
```

Opcion B, app separada:

- Nombre: `Scentra Admin Frontend`
- Repositorio: mismo repo
- Branch: `main`
- Build Pack: `Dockerfile`
- Base Directory: `saas-version/admin-frontend`
- Dockerfile Location: `Dockerfile`
- Dominio: `https://admin.scentra-ai.online`

Variables buildtime del admin:

```env
VITE_API_BASE=https://api.scentra-ai.online
VITE_CLIENT_APP_BASE=https://app.scentra-ai.online
VITE_CAPTCHA_ENABLED=true
VITE_TURNSTILE_SITE_KEY=0x4AAAA...
VITE_ADMIN_BOOTSTRAP_ENABLED=false
```

## API requerida

En la app API:

```env
SAAS_CORS_ORIGINS=https://app.scentra-ai.online,https://admin.scentra-ai.online,https://api.scentra-ai.online,https://scentra-ai.online,https://www.scentra-ai.online
SAAS_CAPTCHA_ENABLED=true
TURNSTILE_SECRET_KEY=0x4AAAA...
```

## Seed seguro del primer admin

El bootstrap HTTP queda cerrado en produccion. Para crear o actualizar el primer admin, ejecutar dentro del contenedor API o en Coolify Terminal:

```bash
SAAS_ADMIN_EMAIL=admin@scentra-ai.online \
SAAS_ADMIN_PASSWORD='usa-una-clave-larga-y-unica' \
SAAS_ADMIN_FULL_NAME='Scentra Admin' \
SAAS_ADMIN_ROLE=superadmin \
python -m app_saas.tools.create_platform_admin
```

Tambien puedes pasar argumentos:

```bash
python -m app_saas.tools.create_platform_admin \
  --email admin@scentra-ai.online \
  --password 'usa-una-clave-larga-y-unica' \
  --full-name 'Scentra Admin' \
  --role superadmin
```

Requisitos:

- La clave debe tener minimo 12 caracteres.
- El rol debe ser uno de los roles plataforma soportados.
- El comando es idempotente: si el email ya existe, actualiza clave, nombre, estado y rol.

Con Compose tambien existe el perfil puntual `admin-seed`:

```bash
SAAS_ADMIN_EMAIL=admin@scentra-ai.online \
SAAS_ADMIN_PASSWORD='usa-una-clave-larga-y-unica' \
SAAS_ADMIN_FULL_NAME='Scentra Admin' \
SAAS_ADMIN_ROLE=superadmin \
docker compose -f docker-compose.saas.yml --profile admin-seed run --rm platform-admin-seed
```

## Que administra el panel

- Empresas/clientes.
- Estado de empresa: active, trial, paused, past_due, suspended, cancelled.
- Plan de cada empresa.
- Feature flags por empresa.
- Planes SaaS: limites de mensajes, usuarios, integraciones, campanas, broadcasts, tokens AI.
- Limites de AI Agents por plan:
  - agentes totales
  - agentes activos
  - memorias archivadas
  - tipos de agente permitidos
  - builder activo/inactivo
- Suscripciones y cambio manual de estado.
- Impersonacion de soporte con expiracion corta.
- Operaciones de colas: webhooks, outbound y triggers.

## DNS

Los subdominios deben apuntar a la IP publica del VPS/Coolify:

- `app.scentra-ai.online`
- `admin.scentra-ai.online`
- `api.scentra-ai.online`

Usar registros `A` a la IP publica del servidor. Si usas proxy Cloudflare, asegurate de que HTTPS/SSL este en modo Full o Full Strict.

## Validacion post-deploy

1. Abrir `https://admin.scentra-ai.online/health`, debe responder `ok`.
2. Entrar a `https://admin.scentra-ai.online`.
3. Confirmar que el CAPTCHA se muestra si esta activo.
4. Login con el admin creado por seed.
5. Revisar:
   - Overview
   - Empresas
   - Planes
   - Suscripciones
   - Operacion
6. Crear/editar un plan y confirmar que AI Agents queda con limites propios.
7. Activar/desactivar una empresa y confirmar estado en Empresas/Suscripciones.
8. Cambiar plan de una empresa y confirmar limites/feature flags efectivos.
9. Revisar Auditoria y Colas despues de los cambios.

## Nota operativa

No uses el bootstrap local en produccion. El camino recomendado es el comando `create_platform_admin`, porque no deja un endpoint publico abierto para crear superadmins.
