# Fase 5 - Monetizacion, billing y Wompi

## Objetivo

Esta fase prepara Scentra para vender planes reales con checkout, webhooks de pago, creditos manuales, facturas y bloqueo por ciclo de vida (`trial`, `active`, `past_due`, `suspended`, `cancelled`).

## Proveedores soportados

- `wompi`: checkout web firmado con llave de integridad. Recomendado para Colombia/Bancolombia.
- `mercadopago`: preferencias de checkout.
- `stripe`: checkout session de suscripcion.
- `manual`: deja una sesion pendiente para venta asistida.

## Wompi

Documentacion oficial usada:

- Widget/Web Checkout: https://docs.wompi.co/docs/colombia/widget-checkout-web/
- Eventos/webhooks: https://docs.wompi.co/docs/colombia/eventos/

### Variables necesarias en Coolify

```env
BILLING_DEFAULT_PROVIDER=wompi
BILLING_SUCCESS_URL=https://app.scentra-ai.online/?billing=success
BILLING_CANCEL_URL=https://app.scentra-ai.online/?billing=cancelled
WOMPI_ENVIRONMENT=production
WOMPI_PUBLIC_KEY=pub_prod_xxx
WOMPI_PRIVATE_KEY=prv_prod_xxx
WOMPI_INTEGRITY_KEY=integrity_xxx
WOMPI_EVENTS_KEY=events_xxx
```

Para pruebas usa `WOMPI_ENVIRONMENT=sandbox` y llaves sandbox.

### Flujo implementado

1. El cliente entra a Ajustes > Plan.
2. Selecciona proveedor `Wompi Bancolombia`.
3. Pulsa `Pagar / activar`.
4. Backend crea una sesion en `saas_billing_checkout_sessions`.
5. Backend genera URL de checkout con:
   - `public-key`
   - `currency=COP`
   - `amount-in-cents`
   - `reference`
   - `signature:integrity`
   - `redirect-url`
6. El cliente paga en Wompi.
7. Wompi llama al webhook:
   - `POST https://api.scentra-ai.online/saas/v1/billing/webhooks/wompi`
8. Backend valida la firma del evento si existe `WOMPI_EVENTS_KEY`.
9. Si la transaccion llega `APPROVED`, Scentra:
   - marca checkout como `paid`
   - activa el tenant
   - actualiza el plan
   - crea/actualiza suscripcion
   - crea factura pagada
   - registra pago

## Admin

Se agrego vista `Facturacion` en Scentra Admin para:

- Ver facturas.
- Ver creditos manuales.
- Aplicar creditos por tenant.
- Sincronizar lifecycle para trials/subscripciones vencidas.

## Creditos manuales

Los creditos activos aumentan limites efectivos. Por ahora:

- `monthly_messages` y `messages` suman al limite mensual efectivo de mensajes.
- El dashboard de billing retorna `credits` y `effective_limits`.

## Endpoints nuevos

Cliente:

- `POST /saas/v1/billing/checkout`
- `GET /saas/v1/billing/checkout-sessions`
- `GET /saas/v1/billing/invoices`
- `GET /saas/v1/billing/credits`
- `POST /saas/v1/billing/webhooks/{provider}`

Admin:

- `GET /saas/v1/admin/billing/invoices`
- `POST /saas/v1/admin/billing/invoices`
- `GET /saas/v1/admin/billing/credits`
- `POST /saas/v1/admin/billing/credits`
- `POST /saas/v1/admin/billing/lifecycle/sync`

## Pendiente recomendado

- Confirmar precios de planes en COP para Wompi.
- Configurar webhook en Wompi hacia `/saas/v1/billing/webhooks/wompi`.
- Agregar impuestos/retenciones si se requiere facturacion legal local.
- Generar factura PDF real con proveedor contable o facturacion electronica.
- Crear jobs recurrentes para `sync_billing_lifecycle`.
