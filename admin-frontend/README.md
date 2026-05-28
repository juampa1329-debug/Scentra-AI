# Scentra Admin

Panel interno para operar el SaaS de Scentra +AI.

## Ejecutar local

```powershell
npm install
npm run dev
```

URL local:

```text
http://localhost:5175
```

Backend esperado:

```text
http://localhost:8010
```

Portal cliente usado para acceso de soporte:

```text
http://localhost:5174
```

## Primer acceso local

En entorno `SAAS_ENV=local`, el formulario de login muestra la opcion `Crear primer admin local`.
Ese flujo llama a:

```text
POST /saas/v1/admin/auth/bootstrap
```

En produccion este bootstrap queda bloqueado por backend.

## Variables

```env
VITE_API_BASE=http://localhost:8010
VITE_CLIENT_APP_BASE=http://localhost:5174
VITE_CAPTCHA_ENABLED=false
VITE_TURNSTILE_SITE_KEY=
VITE_ADMIN_BOOTSTRAP_ENABLED=true
```

En produccion, no habilites `VITE_ADMIN_BOOTSTRAP_ENABLED`. Crea el primer superadmin con:

```bash
python -m app_saas.tools.create_platform_admin
```
