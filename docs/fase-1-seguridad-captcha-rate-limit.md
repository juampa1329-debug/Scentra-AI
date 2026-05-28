# Fase 1 - Seguridad base: CAPTCHA y rate limiting

Esta fase agrega una capa defensiva configurable para Scentra SaaS sin romper desarrollo local.

## Que protege

- Login del portal cliente.
- Registro demo de 30 dias.
- Login del portal admin.
- Bootstrap local del primer admin.

## Proveedor CAPTCHA

Proveedor elegido: Cloudflare Turnstile.

Motivo: tiene un plan gratuito amplio, UX menos invasiva que reCAPTCHA y no exige vender datos de comportamiento a Google.

## Variables backend

En la API:

```env
SAAS_CAPTCHA_ENABLED=true
SAAS_CAPTCHA_PROVIDER=turnstile
TURNSTILE_SECRET_KEY=0x4AAAA...
SAAS_RATE_LIMIT_ENABLED=true
```

En local puedes dejar:

```env
SAAS_CAPTCHA_ENABLED=false
TURNSTILE_SECRET_KEY=
```

## Variables frontend cliente

En la app cliente:

```env
VITE_CAPTCHA_ENABLED=true
VITE_TURNSTILE_SITE_KEY=0x4AAAA...
```

## Variables frontend admin

En el admin:

```env
VITE_CAPTCHA_ENABLED=true
VITE_TURNSTILE_SITE_KEY=0x4AAAA...
```

## Rate limits iniciales

- Registro: 5 intentos por hora por IP/email.
- Login cliente: 8 fallos cada 15 minutos por IP/email.
- Login admin: 6 fallos cada 15 minutos por IP/email.
- Bootstrap admin local: 3 intentos por hora.

## Auditoria

El backend crea automaticamente la tabla `saas_security_events` si no existe.

Registra:

- evento
- principal/email
- IP
- user agent
- estado: `attempt`, `success`, `failed`, `blocked`
- razon
- metadata JSON

## Como activar en Coolify

1. Crea un sitio en Cloudflare Turnstile.
2. Agrega `app.scentra-ai.online` y `admin.scentra-ai.online` como dominios permitidos.
3. Copia el site key en los frontends como `VITE_TURNSTILE_SITE_KEY`.
4. Copia el secret key en la API como `TURNSTILE_SECRET_KEY`.
5. Activa `SAAS_CAPTCHA_ENABLED=true` en API y `VITE_CAPTCHA_ENABLED=true` en ambos frontends.
6. Redeploy de API, frontend cliente y admin frontend.

## Nota

El CAPTCHA es opcional por variable. Si `SAAS_CAPTCHA_ENABLED=false`, el backend acepta login/registro sin token CAPTCHA, ideal para local y pruebas internas.
