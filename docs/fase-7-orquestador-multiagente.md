# Fase 7 - Orquestador Multiagente Real

Fecha: 2026-05-23

## Objetivo

Convertir AI Agents en un sistema coordinado. Hasta fase 6 los agentes tenian catalogo, memoria, gobierno y memoria colectiva. Fase 7 agrega runtime de orquestacion para que los agentes puedan:

- recibir eventos de inbox, comentarios, diagnosticos y workflows
- elegir el agente mas adecuado
- evitar respuestas o acciones duplicadas con locks
- crear handoffs entre agentes
- registrar conflictos
- dejar auditoria operativa

## Que se implemento

### Backend

Nuevo modulo:

- `backend/app_saas/agents/orchestrator.py`

Funciones principales:

- `enqueue_orchestration_event()`
- `enqueue_conversation_orchestration()`
- `enqueue_social_comment_orchestration()`
- `select_agent_for_job()`
- `process_due_agent_orchestration()`
- `orchestration_overview()`

### Tablas nuevas

Migracion:

- `migrations/035_saas_ai_agent_orchestrator_phase7.sql`

Tablas:

- `saas_ai_agent_orchestration_jobs`
- `saas_ai_agent_locks`
- `saas_ai_agent_handoffs`
- `saas_ai_agent_conflicts`

### Endpoints

Nuevos endpoints en:

- `GET /saas/v1/agents/orchestrator`
- `POST /saas/v1/agents/orchestrator/events`
- `POST /saas/v1/agents/orchestrator/tick`

### Worker

El orquestador se conecta al worker existente:

- worker separado: `backend/app_saas/workers/runner.py`
- worker embebido en API: `backend/app_saas/main.py`

Esto evita exigir una cuarta app en Coolify. Si `SAAS_EMBEDDED_WORKER_ENABLED=true`, el API puede procesar ticks de orquestacion.

### Ingesta

Se conectaron eventos reales:

- mensajes entrantes desde inbox
- comentarios sociales de Instagram/Facebook

Ambos generan jobs de orquestacion sin bloquear la ingesta. Si el orquestador falla, el webhook sigue procesando.

### Frontend

Nueva pestana:

- AI Agents > Orquestador fase 7

Incluye:

- metricas de cola
- jobs recientes
- locks activos
- handoffs
- conflictos
- creacion de evento de prueba
- boton para procesar tick manual

## Como decide el agente

El selector actual usa reglas deterministicas:

- conversaciones: prioriza Sales, Support, Retention, CRM Intelligence o Advisor
- comentarios: prioriza Reputation Manager, Support o Sales
- diagnosticos: prioriza Operations
- workflows/campanas: prioriza Workflow Architect o Campaign Strategist
- educacion: prioriza Profesor o Education Admissions

Esta fase no ejecuta acciones sensibles directamente. Solo asigna ownership y deja trazabilidad.

## Locks

Los locks evitan duplicados por:

- conversacion
- comentario
- post
- cliente

TTL configurable:

- `SAAS_AGENT_ORCHESTRATOR_LOCK_TTL_MINUTES`

Valor por defecto: 15 minutos.

## Variables opcionales

- `SAAS_AGENT_ORCHESTRATOR_ENABLED=true`
- `SAAS_AGENT_ORCHESTRATOR_BATCH_SIZE=20`
- `SAAS_AGENT_ORCHESTRATOR_LOCK_TTL_MINUTES=15`
- `SAAS_AGENT_ORCHESTRATOR_RETRY_MINUTES=5`

## Limitaciones actuales

- El selector todavia es deterministico, no LLM-based.
- Los handoffs quedan propuestos, no aceptados por una UI dedicada.
- Los conflictos se registran, pero todavia no tienen boton de resolver.
- El agente seleccionado no ejecuta una tool call real desde este runtime; eso queda para fase 7.2.

## Siguiente fase sugerida

### Fase 7.2 - Runtime de ejecucion controlada

- conectar jobs completados con tool approvals
- aceptar/rechazar handoffs
- resolver conflictos desde UI
- ranking de memoria colectiva por relevancia
- inyectar memoria colectiva en Sales, Support, Advisor y Profesor
- crear run AI explicable por cada decision importante

### Fase 8 - RAG operativo

- subir archivos reales
- crawl de URL
- embeddings
- recuperacion semantica
- citas internas
- score de confianza

## Verificacion requerida en deploy

Despues de redeploy:

1. Confirmar que migracion 035 corrio.
2. Abrir AI Agents > Orquestador fase 7.
3. Crear evento de prueba.
4. Pulsar Procesar tick.
5. Verificar que el job cambia a completado o conflicto.
6. Enviar mensaje real al inbox y confirmar que aparece un job nuevo.
7. Hacer comentario en Instagram/Facebook y confirmar que aparece job social.

