# Frontend SaaS (plan de implementacion)

## Meta
Crear interfaz para operacion multi-tenant y billing sin acoplar dominios hardcoded.

## Pantallas MVP
1. Login.
2. Selector de tenant.
3. Inbox tenant-aware.
4. Integraciones por tenant.
5. Billing/plan/uso.
6. Seguridad (usuarios y roles por tenant).

## Reglas tecnicas
1. `VITE_API_BASE` obligatorio por ambiente.
2. Token en almacenamiento seguro.
3. No consumir endpoints legacy desde vistas SaaS.

## Scaffold actual
1. Login.
2. Registro de owner + tenant.
3. Selector de tenant.
4. Vista inicial de tenants.
5. Inbox con lectura y respuesta encolada.
6. Webhooks con rotacion de token/firma HMAC.
7. Integraciones basicas por tenant.

## Arranque local
1. `npm install`
2. `npm run dev`
