# Coolify production

Guia corta para publicar Scentra +AI SaaS con dominios separados.

## Dominios recomendados
1. Sitio de presentacion: `https://scentra-ai.online`
2. Portal cliente: `https://app.scentra-ai.online`
3. Portal admin: `https://admin.scentra-ai.online`
4. API compartida: `https://api.scentra-ai.online`

## DNS
Todos estos registros pueden apuntar a la misma IP publica del servidor donde corre Coolify. Coolify/Traefik/Caddy se encarga de enrutar por dominio.

| Tipo | Nombre | Apunta a |
| --- | --- | --- |
| A | `@` | `<IP_PUBLICA_DEL_SERVIDOR_COOLIFY>` |
| A | `app` | `<IP_PUBLICA_DEL_SERVIDOR_COOLIFY>` |
| A | `admin` | `<IP_PUBLICA_DEL_SERVIDOR_COOLIFY>` |
| A | `api` | `<IP_PUBLICA_DEL_SERVIDOR_COOLIFY>` |

Si el proveedor DNS permite CNAME para subdominios, tambien puedes usar:

```text
app   CNAME   scentra-ai.online
admin CNAME   scentra-ai.online
api   CNAME   scentra-ai.online
```

Mantén `@` como registro `A` hacia la IP publica. No uses IP privada/local.

## Variables backend API / worker / migrate
Si usas el Postgres incluido en el Docker Compose, coloca estas variables en el recurso Docker Compose de Coolify. Coolify las entrega a `db`, `api`, `migrate` y `worker`.

```env
POSTGRES_DB=scentra_saas
POSTGRES_USER=scentra_saas
POSTGRES_PASSWORD=<password_seguro_postgres>
DATABASE_URL=postgresql+psycopg2://scentra_saas:<password_seguro_postgres>@db:5432/scentra_saas

SAAS_ENV=production
SAAS_JWT_SECRET=<secreto_largo_aleatorio>
SAAS_JWT_ISSUER=scentra-ai
SAAS_ACCESS_TOKEN_MINUTES=15
SAAS_REFRESH_TOKEN_DAYS=15
SAAS_CORS_ORIGINS=https://app.scentra-ai.online,https://admin.scentra-ai.online
SAAS_TRIAL_DAYS=30
SAAS_TRIAL_PLAN_CODE=starter
SAAS_MIGRATION_PROFILE=core
SAAS_WORKER_NAME=worker-production

SCENTRA_META_ACCESS_TOKEN=
SCENTRA_WHATSAPP_BUSINESS_ACCOUNT_ID=
SCENTRA_META_GRAPH_VERSION=v22.0
SCENTRA_META_TIMEOUT_SEC=15
```

`POSTGRES_PASSWORD` y la clave dentro de `DATABASE_URL` deben ser exactamente iguales.

`SCENTRA_META_ACCESS_TOKEN` puede quedar vacio si todavia no vas a enviar WhatsApp real.

Si usas un WABA global para pruebas, define tambien:

```env
SCENTRA_META_ACCESS_TOKEN=<token_permanente_meta_whatsapp_cloud>
SCENTRA_WHATSAPP_BUSINESS_ACCOUNT_ID=<waba_id>
```

En modo SaaS real multi-cliente, lo ideal es que cada empresa tenga su propia integracion WhatsApp Cloud y que el token se guarde como secreto por tenant. La variable `SCENTRA_META_ACCESS_TOKEN` queda como fallback global para pruebas, demos o una primera operacion con un solo WABA.

## Variables portal cliente
Estas variables de Vite deben estar disponibles en buildtime:

```env
VITE_API_BASE=https://api.scentra-ai.online
```

## Variables portal admin
Estas variables de Vite deben estar disponibles en buildtime:

```env
VITE_API_BASE=https://api.scentra-ai.online
VITE_CLIENT_APP_BASE=https://app.scentra-ai.online
```

## Que es `SCENTRA_META_ACCESS_TOKEN`
Es el token secreto que usa el backend para hablar con Meta Graph API / WhatsApp Cloud.

Se usa para:
1. Sincronizar plantillas de WhatsApp desde Meta.
2. Crear plantillas en el WABA para que entren a aprobacion.
3. Enviar mensajes reales desde el worker cuando la integracion usa `Meta Cloud real`.

No es:
1. El token de login del usuario.
2. El `verify token` del webhook.
3. Una variable que deba ir en el frontend.

En Coolify no deberia exponerse al build del frontend. Para servicios backend, puede quedar como runtime secret. Marca `Is Multiline` solo si el valor tuviera saltos de linea; normalmente un token de Meta no los tiene.

## Webhook Meta
Meta necesita una URL publica HTTPS. En local, `localhost` no sirve para recibir webhooks reales sin tunel.

URL base de webhook en produccion:

```text
https://api.scentra-ai.online/saas/v1/webhooks/whatsapp/<endpoint_key>
```

El `verify token` lo genera Scentra al crear el endpoint webhook y se muestra una sola vez. Ese token es distinto a `SCENTRA_META_ACCESS_TOKEN`.

## Demo 30 dias
Al registrarse, una empresa nueva queda en:

```text
tenant.status = trial
subscription.status = trial
plan_code = starter
current_period_end = ahora + 30 dias
```

El admin puede cambiar el estado a `active`, `past_due`, `suspended` o `cancelled` desde el panel admin.

Pendiente antes de cobros reales:
1. Job diario que venza trials expirados.
2. Checkout Stripe o MercadoPago.
3. Webhooks de pago que pasen `trial` a `active` o `past_due`.
4. Secretos Meta por tenant con cifrado o secret manager.
