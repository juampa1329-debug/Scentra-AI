# Informe de estado - Scentra SaaS

Fecha: 2026-05-21  
Proyecto: Scentra +AI / Scentra SaaS  
Ruta local: `C:\verane-whatsapp-ai\saas-version`

## 1. Resumen ejecutivo

Scentra ya paso de ser una adaptacion inicial del software original a una base SaaS multi-tenant mucho mas cercana a producto vendible. Actualmente existen tres piezas principales:

- Portal cliente: `app.scentra-ai.online`.
- API SaaS: `api.scentra-ai.online`.
- Portal admin interno: `admin.scentra-ai.online`.

La plataforma ya incluye autenticacion multi-tenant, trial de 30 dias, planes, limites, portal admin, integraciones Meta, Inbox CRM, webhooks, diagnosticos, observabilidad, AI Agents, Advisor Agent, comentarios sociales, seguridad base, captcha/rate-limit, billing inicial y una integracion inicial de Wompi/Bancolombia.

Estado general: base funcional avanzada, pero aun necesita validaciones reales de produccion con Meta, Wompi, flujos de pago, webhooks, permisos y pruebas end-to-end antes de venderla masivamente.

## 2. Arquitectura actual

### 2.1 Componentes

- `frontend/`: portal del cliente SaaS.
- `admin-frontend/`: panel interno de administracion de Scentra.
- `backend/app_saas/`: API FastAPI compartida.
- `migrations/`: migraciones SQL del SaaS.
- `docs/`: documentacion tecnica, roadmap e informes.
- `docker-compose.saas.yml`: despliegue multi-servicio para API, worker y base de datos.

### 2.2 Servicios logicos

- API SaaS multi-tenant.
- Worker embebido o worker separado.
- Base PostgreSQL centralizada multi-tenant.
- Frontend cliente.
- Frontend admin.
- Webhooks Meta/WhatsApp/Instagram/Facebook.
- Billing provider webhooks.
- AI Gateway y Agents runtime inicial.

## 3. Fases implementadas

## Fase base - SaaS inicial

Estado: implementado y en evolucion.

Se hizo:

- Carpeta SaaS separada en `saas-version`.
- Backend FastAPI SaaS independiente del codigo original.
- Autenticacion JWT con access/refresh token.
- Registro de empresas/tenants.
- Trial demo de 30 dias.
- Modelo multi-tenant con aislamiento por `tenant_id`.
- Plan inicial tipo `starter`/demo.
- CORS para dominios de produccion.
- Docker/Coolify preparado para deploy.
- Variables `.env.example` y compose ajustados.

Pendiente:

- Endurecer sesiones con refresh rotation completa.
- 2FA real para cliente y admin.
- Politicas mas estrictas de contrasenas y recuperacion.

## Fase UI/Rebranding - Scentra +AI

Estado: implementado.

Se hizo:

- Rebranding visual de WhatChimp/Verane a Scentra +AI.
- Portal con estetica glossy moderna.
- Layout oscuro/glassmorphism.
- Sidebar compacto.
- Dashboard operativo inicial.
- Ajustes separados por secciones: IA, Canales, APIs, Usuarios, Perfil, Seguridad, Plan.
- Mejora responsive parcial.

Pendiente:

- Pulir responsive mobile profundo para Inbox y CRM.
- Mejorar accesibilidad visual/contrastes.
- Code-splitting del frontend, porque Vite advierte bundle grande.

## Fase Integraciones Meta/WhatsApp

Estado: implementado parcialmente, requiere validacion por cliente.

Se hizo:

- Integracion manual de WhatsApp Cloud API por tenant.
- Campos para Phone Number ID, WABA ID, Meta App ID, Graph API version y token permanente.
- Token permanente cifrado/oculto en backend.
- Modal de actualizacion de secretos.
- Boton para editar integracion.
- Eliminacion de integraciones.
- Webhook endpoint por tenant/canal.
- Verify token generado por Scentra.
- Firma HMAC opcional.
- Callback URL completa para copiar/pegar.
- Diagnostico de WABA subscribed apps.
- Auto-suscripcion a `/{WABA_ID}/subscribed_apps` cuando falta.
- Verificacion/sincronizacion de numeros WhatsApp.
- Recepcion de inbound text/audio/image/video basica.
- Estados outbound: queued, sent, delivered, read, failed.

Pendiente:

- Revisar casos de Meta Graph 401/502 por token vencido, token incorrecto o IDs invertidos.
- Confirmar que cada tenant quede suscrito correctamente al WABA.
- Mejorar errores visibles para que expliquen si falla token, permisos, WABA o Phone ID.
- Validar en produccion que inbound messages lleguen en todos los tenants.

## Fase Inbox CRM y Mensajeria

Estado: implementado en base avanzada.

Se hizo:

- Inbox omnicanal base.
- Conversaciones por canal.
- Filtros por canal segun integraciones activas.
- Mensajes entrantes/salientes.
- Adjuntos de audio, imagen y video.
- Vista de audio con waveform.
- Botones de adjuntar y emojis.
- Sonido ON/OFF para mensajes.
- CRM lateral desplegable/ocultable.
- Campos CRM: nombre, apellido, ciudad, tipo, etapa, pago, intereses, etiquetas, notas.
- Contexto IA por conversacion.
- Scroll interno de conversacion.
- Auto-scroll al ultimo mensaje.
- Estado leido/no leido.
- Double-check/status visual estilo WhatsApp.

Pendiente:

- Mejorar preview real de imagenes/videos/documentos.
- Envio robusto de notas de voz con transcoding ffmpeg en produccion.
- Adjuntos de catalogo con tarjetas enriquecidas.
- Realtime real por WebSocket o SSE para evitar refrescos manuales.
- Optimizar tiempos de llegada de mensajes y worker.

## Fase Campanas CRM, Triggers, Remarketing y Broadcast

Estado: replicado en estructura inicial desde el software original.

Se hizo:

- Seccion Campanas CRM.
- Plantillas por canal.
- Motor de triggers inicial.
- Motor de remarketing inicial.
- Mensajeria masiva/broadcast con estructura base.
- Diferenciacion conceptual entre plantillas de 24h/triggers y plantillas aprobadas para broadcast.
- Vista previa de mensajes estilo chat.
- Estados de plantillas: aprobada, rechazada, pendiente.

Pendiente:

- Integracion completa de aprobacion real con Meta Templates.
- Sincronizacion completa con plantillas de Meta.
- Validar restricciones de ventana 24h.
- Jobs de remarketing robustos con retry, auditoria y limites por plan.
- Editor de plantillas mas cercano al original con media, botones, quick replies y emojis completos.

## Fase Instagram/Facebook Social

Estado: implementado parcialmente, permisos Meta aun deben validarse.

Se hizo:

- Arquitectura para Instagram Business y Facebook Messenger.
- OAuth/manual integration paths.
- Diagnosticos Instagram/Facebook.
- Subscribed apps check.
- Separacion de DMs vs comentarios.
- Comentarios sociales dentro del Inbox en pestana separada.
- Tablas/estructura para posts, comments y settings de IA de comentarios.
- UI inicial de comentarios con publicacion asociada.
- Respuesta manual y generacion de respuesta con IA.
- Entrenamiento/configuracion IA para comentarios.
- Enriquecimiento de perfil/nombre/foto previsto en procesamiento.
- Token refresh job para tokens Meta de Facebook/Instagram.

Pendiente:

- Confirmar permisos Meta en App Review: `pages_manage_metadata`, `pages_messaging`, `pages_read_engagement`, `pages_read_user_content`, `pages_manage_engagement`, `instagram_manage_messages`, `instagram_manage_comments`.
- Probar DMs de Instagram y Messenger en produccion.
- Mejorar UI de comentarios tipo Meta Business Suite: post preview + comentario resaltado + reacciones.
- Reacciones con emojis completos.
- Confirmar si cada cliente usara su propia app Meta o una app Scentra verificada.
- Mejorar perfiles: mostrar nombre/foto en vez de solo ID cuando Meta lo permita.

## Fase AI Gateway y AI Agents

Estado: implementado en base funcional, pendiente hardening enterprise.

Se hizo:

- Diseno e implementacion inicial de AI Gateway.
- Proveedores: Gemini, Mistral, OpenRouter y Kimi como proveedor oficial.
- Catalogo de AI Agents.
- Builder de agentes.
- Dashboard de AI Agents.
- Agentes base: Advisor, Sales, Support, CRM Intelligence, Campaign Strategist, Retention, Operations, Executive Summary, Knowledge, Workflow Architect y otros sugeridos.
- Limites de agentes por plan.
- AI Agents disponible en demo con limites.
- Catalogo separado por pestana.
- Filtros por industria/funcion.
- Eliminar agente.
- Boveda de memoria para agentes eliminados.
- Limite de memorias por plan.
- Borrar memoria de agente.
- Advertencia si la boveda esta llena al borrar agente.
- Presets por industria: restaurante, hotel, inmobiliaria, clinica, academia, estetica, legal, seguros, entre otros.
- Presupuesto por agente.
- Test antes de activar.
- Score de salud del agente.
- A/B testing conceptual/estructura inicial.
- Politicas por industria.
- Exportar/importar memoria.

Pendiente:

- Evaluaciones automaticas de calidad de respuesta.
- Versionado de prompts.
- Tool approval layer completo.
- Cost tracking real por proveedor/modelo/agente.
- RAG/vector search robusto.
- Observabilidad avanzada de AI: latencia, fallback, tokens, errores, accuracy.
- Governance: aprobaciones humanas para acciones sensibles.
- Mejorar Advisor para que nunca muestre JSON crudo al usuario.

## Fase Advisor Agent

Estado: implementado en base, pendiente UX final.

Se hizo:

- Floating Advisor persistente.
- Insights proactivos.
- Recomendaciones.
- Acciones con aprobar/descartar.
- Memoria activa.
- Metricas del Advisor.
- Actividad reciente.
- Integracion con CRM, Inbox, eventos y diagnosticos.

Pendiente:

- Convertir todas las respuestas estructuradas a lenguaje natural.
- Evitar desbordes visuales en la ventana flotante.
- Hacer que `Preparar` siempre genere una accion clara.
- Mejorar streaming y estado de pensamiento.
- Resumen ejecutivo descargable.

## Fase Admin - Scentra Admin

Estado: implementado en base operativa.

Se hizo:

- App separada `admin-frontend`.
- Roles platform admin: `superadmin`, `platform_admin`, `billing_admin`, `support`.
- Login admin.
- Bootstrap del primer admin.
- Gestion de empresas/tenants.
- Ver clientes con nombre real, no solo codigos.
- Activar, pausar, suspender, cancelar tenants.
- Cambiar plan manualmente.
- Feature flags por tenant.
- Impersonacion soporte con auditoria.
- Gestion de planes.
- Gestion de suscripciones.
- Operaciones: colas, webhooks, outbound, triggers.
- Observabilidad: health global y dead-letter.
- Auditoria.
- Vista de facturacion inicial.

Pendiente:

- Mejorar seguridad admin con 2FA real.
- Registro completo de acciones criticas.
- Panel de soporte con timeline por tenant.
- Vista de pagos y facturas mas completa.
- Control granular de permisos por rol.

## Fase 1 Robustez - Seguridad, Captcha y Rate Limiting

Estado: implementado base.

Se hizo:

- Soporte para Cloudflare Turnstile.
- Captcha en login/registro cliente.
- Captcha en login/bootstrap admin.
- Rate limiting base.
- Registro de eventos de seguridad.
- Variables de configuracion para Coolify.

Pendiente:

- 2FA real.
- Politica de bloqueo por intentos fallidos.
- Recuperacion de cuenta segura.
- Headers de seguridad via Nginx/Traefik.
- Alertas admin ante ataques o abuso.

## Fase 2 Robustez - Admin Produccion

Estado: implementado base.

Se hizo:

- Admin build/Dockerfile/nginx.
- Variables para admin frontend.
- Admin seed tool.
- Roles admin.
- Planes y feature flags.
- Suscripciones.
- Auditoria.

Pendiente:

- Configurar definitivamente Coolify para `admin.scentra-ai.online`.
- Validar CORS final en produccion.
- Crear superadmin real con herramienta seed.
- Rotacion de secretos admin.

## Fase 3 Robustez - Observabilidad Operativa

Estado: implementado base.

Se hizo:

- Health global admin.
- Diagnostico por canal.
- Queue snapshots.
- Dead-letter events.
- Sync de dead-letter.
- Resolver dead-letter.
- Correlation/request meta base.
- Observabilidad para errores de webhooks, outbound y workers.

Pendiente:

- Dashboard historico por tenant.
- Alertas proactivas por email/Slack/WhatsApp.
- Integracion con Sentry/Prometheus/Grafana si se escala.
- Retention policy de logs.

## Fase 4 Robustez - Inbox/CRM Runtime

Estado: implementado y validado con compilacion/build.

Se hizo:

- Migracion `032_saas_inbox_crm_runtime.sql`.
- Campos de SLA, prioridad, asignacion y lead scoring en conversaciones.
- Tareas CRM por conversacion.
- Eventos de estado de mensajes.
- Actualizacion de inbound/outbound con timestamps.
- Recalculo de score.
- Filtros inteligentes de Inbox: unread, mine, unassigned, SLA, hot, human, AI.
- Badges de lead score, asignacion y SLA.
- CRM sidebar con tareas y timeline de estados.
- Dashboard con SLA vencido, tareas y leads calientes.

Pendiente:

- Asignacion a agentes humanos reales desde equipo.
- SLA configurable por tenant/plan.
- Realtime WebSocket/SSE.
- Reportes de productividad por agente.

## Fase 5 - Monetizacion, Billing y Wompi

Estado: implementacion agregada, pendiente prueba real end-to-end y redeploy.

Se hizo:

- Migracion `033_saas_billing_monetization.sql`.
- Tablas de checkout sessions, invoices, payments, credits y provider events.
- Servicio provider-agnostic de billing.
- Stripe checkout base.
- MercadoPago checkout base.
- Wompi Bancolombia como proveedor agregado.
- Checkout Wompi firmado desde backend con `signature:integrity`.
- Webhook Wompi en `/saas/v1/billing/webhooks/wompi`.
- Validacion de evento Wompi con `WOMPI_EVENTS_KEY`.
- Activacion de tenant/plan al recibir transaccion `APPROVED`.
- Creacion de invoice y payment al pagar.
- Creditos manuales que aumentan limites efectivos de mensajes.
- Vista de checkout en portal cliente.
- Vista Facturacion en Admin.
- Variables para Coolify en `.env.example` y `docker-compose.saas.yml`.
- Documento tecnico `docs/fase-5-monetizacion-wompi.md`.

Pendiente:

- Confirmar precios de planes en COP si se usara Wompi.
- Configurar webhook real en Wompi.
- Probar pago sandbox y produccion.
- Facturacion electronica/PDF real.
- Impuestos, retenciones y conciliacion contable.
- Job recurrente para lifecycle de billing.
- Reintentos y reconciliacion de pagos fallidos.

## 4. Validaciones ejecutadas

Validado localmente:

- `python -m compileall backend\app_saas\billing backend\app_saas\admin backend\app_saas\config.py`
- `npm run build` en `frontend`.
- `npm run build` en `admin-frontend`.

Resultado:

- Backend compila correctamente.
- Frontend cliente construye correctamente.
- Admin frontend construye correctamente.
- Vite advierte que el bundle del frontend cliente supera 500 kB; no rompe build, pero se recomienda code-splitting.

## 5. Documentacion creada o actualizada

- `docs/scentra-roadmap-robustez-admin-seguridad.md`
- `docs/scentra-roadmap-robustez-admin-seguridad.pdf`
- `docs/fase-1-seguridad-captcha-rate-limit.md`
- `docs/fase-2-scentra-admin-produccion.md`
- `docs/fase-3-observabilidad-operativa.md`
- `docs/fase-5-monetizacion-wompi.md`
- `docs/instagram-business-integration.md`
- `docs/whatsapp-webhook-subscription.md`
- `docs/ai-agent-operating-system.md`

## 6. Variables importantes de produccion

### Core SaaS

```env
DATABASE_URL=
SAAS_ENV=production
SAAS_JWT_SECRET=
SAAS_SECRET_KEY=
SAAS_CORS_ORIGINS=https://app.scentra-ai.online,https://admin.scentra-ai.online,https://api.scentra-ai.online,https://scentra-ai.online,https://www.scentra-ai.online
SCENTRA_API_PUBLIC_URL=https://api.scentra-ai.online
SCENTRA_APP_PUBLIC_URL=https://app.scentra-ai.online
```

### Seguridad

```env
SAAS_CAPTCHA_ENABLED=true
SAAS_CAPTCHA_PROVIDER=turnstile
TURNSTILE_SECRET_KEY=
SAAS_RATE_LIMIT_ENABLED=true
```

### Meta

```env
SCENTRA_META_APP_ID=
SCENTRA_META_APP_SECRET=
SCENTRA_META_GRAPH_VERSION=v24.0
SCENTRA_INSTAGRAM_WEBHOOK_VERIFY_TOKEN=
```

### Billing / Wompi

```env
BILLING_DEFAULT_PROVIDER=wompi
BILLING_SUCCESS_URL=https://app.scentra-ai.online/?billing=success
BILLING_CANCEL_URL=https://app.scentra-ai.online/?billing=cancelled
WOMPI_ENVIRONMENT=production
WOMPI_PUBLIC_KEY=
WOMPI_PRIVATE_KEY=
WOMPI_INTEGRITY_KEY=
WOMPI_EVENTS_KEY=
```

Webhook Wompi:

```txt
https://api.scentra-ai.online/saas/v1/billing/webhooks/wompi
```

## 7. Riesgos actuales

- Meta puede bloquear inbound messages si falta `subscribed_apps` o permisos correctos.
- Instagram/Facebook dependen de App Review y permisos aprobados.
- Tokens Facebook/Instagram no son permanentes como WhatsApp; el refresh job ayuda, pero requiere app id/secret correctos.
- Wompi requiere planes en COP para funcionar correctamente en Colombia.
- La facturacion legal colombiana todavia no esta completa.
- Falta E2E automatizado para onboarding, mensajes, pagos, webhooks y agentes.
- El bundle frontend crecio; conviene dividir por modulos.
- El sistema aun requiere monitoreo externo si se vende a clientes reales.

## 8. Siguientes fases recomendadas

### Fase 6 - AI Enterprise

Objetivo: convertir AI Agents en sistema confiable para produccion.

Acciones:

- Versionado de prompts.
- Evaluaciones automaticas.
- Observabilidad AI profunda.
- Cost analytics por tenant/agente/modelo.
- Tool approval layer.
- Memory governance.
- RAG/vector search real.
- Human-in-the-loop para acciones sensibles.

### Fase 7 - Verticalizacion comercial

Objetivo: que Scentra sirva para ecommerce, restaurantes, hoteles, clinicas, inmobiliarias, academias, esteticas, legal y seguros.

Acciones:

- Presets por industria.
- Pipelines por industria.
- Prompts por industria.
- Agentes por industria.
- Plantillas de campanas por industria.
- Workflows listos para activar.
- Onboarding guiado segun tipo de negocio.

### Fase 8 - Realtime y colaboracion multiagente humana

Acciones:

- WebSocket/SSE.
- Asignacion en vivo.
- Presencia de agentes.
- Typing indicators reales.
- Notificaciones push/browser.
- Bandejas compartidas.
- SLA por equipo.

### Fase 9 - Billing avanzado y facturacion local

Acciones:

- Wompi sandbox/produccion probado.
- Reconciliacion de pagos.
- Facturas PDF.
- Facturacion electronica si aplica.
- Cobros recurrentes reales.
- Dunning emails/WhatsApp por impago.
- Reporte financiero admin.

### Fase 10 - Hardening produccion

Acciones:

- Tests unitarios e integracion.
- E2E Playwright.
- Backups automáticos.
- Disaster recovery.
- Sentry/Prometheus/Grafana.
- Politicas de retencion de logs.
- Auditoria completa de secretos.
- Security headers y CSP.

## 9. Implementaciones pendientes por modulo

### Portal cliente

- Mejor responsive mobile.
- Mejor onboarding guiado.
- Tour de producto por actualizaciones.
- Centro de ayuda dentro de Scentra.
- Estado de plan/pago mas claro.

### Inbox

- WebSocket/SSE.
- Adjuntos completos.
- Audio con ffmpeg listo en contenedor.
- Catalog cards enriquecidas.
- Busqueda avanzada.
- Etiquetado masivo.
- Atajos de teclado.

### CRM

- Segmentacion avanzada.
- Campos personalizados por tenant.
- Pipelines personalizables.
- Historial completo por contacto.
- Importacion/exportacion CSV.

### Meta

- Debug guiado paso a paso.
- Auto-repair mas profundo.
- Validacion de permisos por canal.
- Re-suscripcion automatico programada.
- Enriquecimiento de perfiles.

### AI

- RAG real.
- Eval sets.
- Testing sandbox de agentes.
- Observabilidad y costos.
- Versionado de memoria/prompts.
- Guardrails por industria.

### Admin

- Dashboard financiero.
- Gestion avanzada de soporte.
- Eventos de seguridad.
- Auditoria exportable.
- Roles/permisos granulares.

### Billing

- Prueba Wompi real.
- Stripe/MercadoPago webhooks completos.
- Reconciliacion.
- Facturacion legal.
- Renovaciones y cancelaciones automaticas.

## 10. Conclusion

Scentra ya tiene una base SaaS seria: multi-tenant, admin, planes, integraciones Meta, Inbox CRM, AI Agents, Advisor, observabilidad, seguridad base y billing inicial con Wompi. El siguiente salto debe enfocarse en tres frentes:

1. Validacion real de produccion: Meta, Wompi, dominios, webhooks, permisos y pagos.
2. Robustez operativa: realtime, observabilidad, retries, alertas, E2E tests y hardening.
3. Producto comercial: verticales, agentes por industria, onboarding guiado y facturacion completa.

Recomendacion inmediata: hacer redeploy, correr migraciones, configurar variables de Wompi en Coolify, probar un pago sandbox/produccion y luego validar que el tenant cambie automaticamente a `active` tras webhook `APPROVED`.
