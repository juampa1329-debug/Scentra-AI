# Informe Roadmap Scentra SaaS - Estado al 2026-05-22

## Resumen ejecutivo

Scentra ya avanzo desde una adaptacion SaaS inicial hacia una plataforma multi-tenant con portal cliente, admin, integraciones Meta, inbox omnicanal, AI Gateway, AI Agents, Advisor, seguridad, observabilidad, billing y monetizacion.

Este informe resume lo construido, lo pendiente y el nuevo bloque estrategico de memoria colectiva entre agentes.

## Hecho hasta ahora

### Base SaaS multi-tenant

- Carpeta SaaS separada del software original.
- Backend FastAPI para SaaS.
- Frontend cliente.
- Admin frontend separado.
- Login, registro y demo 30 dias.
- Tenants, usuarios, roles y planes.
- CORS y dominios de produccion.
- Deploy preparado para Coolify.
- Variables de entorno separadas por app.

### Portal cliente

- Dashboard operativo.
- Inbox omnicanal.
- CRM lateral en conversacion.
- Ajustes por secciones: IA, canales, APIs, usuarios, perfil, seguridad y plan.
- UI glossy moderna.
- Responsive parcialmente trabajado.
- Integraciones manuales para Meta/WhatsApp/Instagram/Facebook.
- Debug y diagnostics para Meta.

### WhatsApp Cloud API

- Integracion de token permanente cifrado/oculto.
- Phone Number ID, WABA ID, Meta App ID, App Secret.
- Webhook callback por endpoint.
- Verify token generado por Scentra.
- Auto-subscribe de WABA a subscribed_apps.
- Diagnostics de WABA, telefonos y webhooks.
- Inbox con mensajes entrantes, outbound y estados.
- Media proxy para audio, imagenes y videos.
- Mejoras de UI tipo WhatsApp.

### Instagram y Facebook

- Integraciones manuales tipo WhatsApp.
- Diagnostics para permisos, subscribed_apps, webhooks y eventos.
- Separacion de DMs y comentarios.
- Comentarios dentro del inbox con pestaña propia.
- Estructura para publicaciones, comentarios y respuesta manual/IA.
- Preparacion para Facebook Messenger en flujo conversacional.
- Renovacion automatica de tokens long-lived cuando existe token OAuth renovable.

### CRM, triggers y remarketing

- Se replicaron bases del original hacia SaaS.
- Campanas CRM, triggers, plantillas y remarketing fueron analizados y trasladados progresivamente.
- CRM lateral dentro del inbox.
- Fichas comerciales con etapa, pago, intereses, etiquetas y notas.
- Base para remarketing y acciones asistidas.

### Knowledge Base

- Se preparo seccion de knowledge base y fuentes web.
- Se detecto que hace falta completar carga real, indexacion, crawl y uso RAG en runtime.

### AI Gateway

- Proveedores: Gemini, Mistral, OpenRouter, Kimi.
- Kimi agregado como proveedor oficial.
- Rutas de modelo por tipo de tarea.
- Fallbacks.
- Runs AI con tokens, latencia, modelo, proveedor y estado.
- Observabilidad base de AI.

### AI Advisor

- Floating advisor widget.
- Recomendaciones e insights.
- Acciones con aprobacion humana.
- Memoria activa.
- Se corrigio el problema de mostrar JSON crudo en varias respuestas, pero todavia requiere afinamiento UX continuo.

### AI Agents

- Modulo Scentra AI Agents.
- Catalogo de agentes.
- Builder visual.
- Configuracion de canales, tools, memoria, permisos, proveedor, fallback y presupuesto.
- Test antes de activar.
- Score de salud.
- A/B testing inicial.
- Boveda de memorias por plan.
- Eliminar agente con opcion de conservar memoria.
- Limite de memorias por plan.
- Importar/exportar memoria.
- Nuevos agentes por vertical: restaurantes, hoteleria, inmobiliaria, salud, legal, seguros, turismo, RRHH, SaaS, etc.

### Fase 6 implementada

- Memoria colectiva entre agentes.
- Gobierno de prompts.
- Aprobaciones de tool calling.
- Presupuestos por agente.
- Eventos de coordinacion.
- Endpoint `/saas/v1/agents/governance`.
- Pestaña Gobierno fase 6 en AI Agents.
- Agente Profesor para educacion.
- Documento tecnico de la fase.

### Seguridad

- Rate limiting y protecciones iniciales.
- Cloudflare Turnstile como opcion de captcha gratuita/alta cuota.
- Base de auditoria admin.
- Proteccion de secretos: tokens visibles solo como pista, no completos.
- Separacion de portal cliente y admin.

### Admin

- Admin frontend separado.
- Gestion base de empresas, planes, suscripciones, billing, operaciones, observabilidad y auditoria.
- Feature flags.
- Plan limits.
- Base para controlar agentes por plan.

### Billing y pagos

- Planes, suscripciones y lifecycle.
- Trial/demo 30 dias.
- Base de billing.
- Integracion Wompi preparada como fase de monetizacion.
- Webhooks y eventos de pago base.

## Pendiente principal

### Produccion y estabilidad

- Verificar migraciones en Coolify.
- Ejecutar smoke tests por app: backend, frontend, admin, workers.
- Revisar variables finales de produccion.
- Verificar CORS, dominios, TLS, DNS y callbacks Meta.
- Separar worker real si el volumen sube.

### WhatsApp

- Mejorar mensajes de error Meta para usuarios no expertos.
- Completar diagnostico guiado paso a paso.
- Confirmar envio real de audios, imagenes y video con conversion correcta.
- Revisar estados sent, delivered, read en todos los outbound.

### Instagram/Facebook

- Completar OAuth automatizado si la app Meta logra permisos aprobados.
- Mejorar UI de comentarios al estilo Meta Business Suite.
- Responder comentarios con IA y emojis completos.
- Enriquecer nombres/fotos de perfiles cuando Meta lo permita.
- Confirmar permisos pages_messaging, pages_manage_metadata, pages_read_engagement, pages_manage_engagement, pages_read_user_content.

### Knowledge Base y RAG

- Subida real de archivos.
- Crawl real de URLs.
- Indexacion vectorial.
- Uso real en Advisor, Sales, Support y Profesor.
- Panel de calidad de fuentes.

### AI Agents

- Activar orquestador real.
- Inyectar memoria colectiva en runtime.
- UI para versiones de prompt.
- UI para aprobar/rechazar tool calls.
- Score de precision y satisfaccion.
- Comparador A/B real.
- Politicas por industria mas profundas.

### Admin

- Completar acciones operativas de soporte.
- Impersonation con auditoria.
- Gestion de pagos real desde admin.
- Dashboard financiero.
- Alertas de impago.
- Control granular de modulos por tenant.

### Billing/Wompi

- Validar llaves de sandbox y produccion.
- Confirmar firma de eventos.
- Mapear estados Wompi a suscripciones Scentra.
- Facturas, recibos e historial de pagos.
- Bloqueo automatico por past_due.

## Nueva fase sugerida: Fase 7 - Orquestador Multiagente real

Objetivo: que los agentes no solo compartan memoria, sino que coordinen acciones.

Componentes:

- worker de orquestacion
- event bus
- conflict resolver
- ownership de tareas
- handoff protocol
- locks por conversacion/campana/cliente
- aprobaciones humanas
- auditoria de decisiones

Prioridad: alta, porque permite que Scentra sea realmente un sistema operativo de agentes, no solo un conjunto de bots.

## Nueva fase sugerida: Fase 8 - RAG operativo y Knowledge Agent

Objetivo: que la IA responda con base en documentos, URLs, politicas y catalogos.

Componentes:

- upload real
- crawler
- embeddings
- busqueda semantica
- ranking
- citas internas
- score de confianza
- expiracion de fuentes

Prioridad: alta para reducir alucinaciones y soportar Profesor Agent.

## Nueva fase sugerida: Fase 9 - Produccion comercial

Objetivo: dejar el SaaS listo para vender con operaciones reales.

Componentes:

- onboarding guiado
- checklist por canal
- pagos reales
- admin completo
- soporte/impersonation
- backups
- logs centralizados
- alertas
- monitoreo uptime

## Recomendacion de orden

1. Validar deploy actual con migraciones y apps.
2. Probar AI Agents y Profesor en demo.
3. Completar UI de Fase 6 para prompts y tool approvals.
4. Construir Orchestrator Runtime.
5. Completar Knowledge Base/RAG real.
6. Cerrar Instagram/Facebook OAuth y comentarios.
7. Robustecer Admin y Billing Wompi.
8. Preparar salida comercial con checklist y soporte.

## Conclusiones

Scentra ya tiene una base SaaS fuerte. Lo mas importante ahora es consolidar confiabilidad operacional, cerrar integraciones Meta con diagnostico claro y convertir AI Agents en un sistema coordinado con memoria colectiva y orquestador. El nuevo Profesor Agent abre la puerta a vertical educacion y ayuda a que Scentra no quede limitado a ecommerce.

