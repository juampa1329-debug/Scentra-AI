# Scentra AI Agent Operating System

## Objetivo

Scentra debe operar como un sistema de agentes para SaaS multi-tenant, no como un chatbot aislado.
El nucleo AI se compone de:

- AI Gateway
- Provider adapters
- Agent runtime
- Context engine
- Memory/RAG
- Recommendation engine
- Human approval layer
- Observability y audit logs

## AI Gateway

El Gateway centraliza llamadas a proveedores LLM y evita que cada modulo llame modelos directamente.

Proveedores soportados:

- Google / Gemini
- Groq
- Mistral
- OpenRouter
- Kimi / Moonshot AI

Kimi queda registrado oficialmente con:

- `provider_code`: `kimi`
- `credential_key`: `KIMI_API_KEY`
- alias operativo: `MOONSHOT_API_KEY`
- base URL compatible OpenAI: `https://api.moonshot.ai/v1`
- uso recomendado: razonamiento, long-context e insights del Advisor Agent

## Provider Adapters

Cada adapter debe implementar progresivamente:

- `generate()`
- `stream()`
- `embeddings()`
- `tool_call()`
- `reasoning()`
- `moderation()`

En esta fase se implementa `generate()` para Gemini y proveedores OpenAI-compatible.

## Routing Inicial

Rutas globales sugeridas:

- `conversation.sales`: respuestas comerciales del inbox
- `advisor.insights`: Advisor Agent e insights estrategicos
- `crm.classification`: clasificacion y enriquecimiento CRM
- `summaries.executive`: balances ejecutivos

## Observability

Cada ejecucion registra:

- tenant
- agente
- task type
- route
- proveedor
- modelo
- tokens entrada/salida
- latencia
- fallback
- estado
- error

Tabla principal:

- `saas_ai_runs`

Tablas de crecimiento:

- `saas_ai_tool_calls`
- `saas_ai_recommendations`
- `saas_ai_routes`
- `saas_ai_providers`
- `saas_ai_models`

## Flujo Actual

```text
Inbound message
  -> schedule AI pending reply
  -> context assembly en ai_agent.service
  -> AI Gateway
  -> provider adapter
  -> saas_ai_runs
  -> parse JSON
  -> CRM update
  -> memory update
  -> outbound queue
```

## Siguiente Fase

1. Crear Advisor Agent flotante en frontend.
2. Crear endpoints de recomendaciones.
3. Conectar tool runtime con approvals.
4. Añadir RAG vectorial tenant-isolated.
5. Separar worker AI para produccion de alto volumen.

## Referencias oficiales

- Kimi / Moonshot AI API: https://platform.moonshot.ai/docs/overview
- Google Gemini API: https://ai.google.dev/gemini-api/docs
- Mistral API: https://docs.mistral.ai
- OpenRouter API: https://openrouter.ai/docs

