# Fase 3 - Observabilidad operativa

Esta fase agrega una primera capa de monitoreo interno para operar Scentra en produccion sin depender solo de logs de Coolify.

## Objetivos implementados

- Correlation IDs por request con headers `X-Request-ID` y `X-Correlation-ID`.
- Health global desde el panel admin.
- Snapshot de colas operativas:
  - webhooks entrantes
  - outbound messages
  - triggers programados
  - respuestas IA pendientes
- Diagnostico por canal/proveedor.
- Dead-letter normalizado para errores de webhooks, outbound, triggers e IA.
- Acciones admin para sincronizar y resolver dead-letters.

## Endpoints admin

Todos requieren token de plataforma con rol `superadmin`, `platform_admin` o `support`.

```txt
GET  /saas/v1/admin/observability/health
GET  /saas/v1/admin/observability/dead-letter?status=open&limit=100
POST /saas/v1/admin/observability/dead-letter/sync?limit=200
POST /saas/v1/admin/observability/dead-letter/{event_id}/resolve
GET  /saas/v1/admin/operations/queues
```

## Dead-letter

La migracion `031_saas_observability_dead_letter.sql` crea la tabla `saas_dead_letter_events`. El servicio tambien puede crearla de forma defensiva si aun no se aplico la migracion.

Por ahora funciona como un indice operativo de errores detectados en tablas existentes:

- `saas_webhook_events` con `status = error` o `error` no vacio.
- `saas_outbound_messages` con `failed`, `blocked`, `retry` o error activo.
- `saas_trigger_scheduled_messages` fallidos o con `last_error`.
- `saas_ai_pending_replies` fallidos o con `last_error`.

Esto evita mover eventos reales de sus tablas de origen y permite operar sin perder trazabilidad.

## Vista Admin

En `Scentra Admin` aparece la nueva seccion `Salud`.

Muestra:

- Estado global del API.
- Backlog total.
- Errores operativos.
- Integraciones conectadas.
- Estado del worker embebido.
- Diagnostico por canal.
- Dead-letters abiertos.

## Correlation IDs

El backend acepta estos headers si vienen de proxy/cliente:

```txt
X-Request-ID
X-Correlation-ID
```

Si no vienen, genera un UUID nuevo. La respuesta siempre devuelve ambos headers para facilitar seguimiento en navegador, API y logs.

## Siguiente paso recomendado

La proxima fase puede profundizar esta base con:

- persistencia de worker heartbeats reales
- tabla de metricas por minuto
- alertas por email/Slack
- exportacion OpenTelemetry
- panel de jobs por tenant
- busqueda por correlation ID
