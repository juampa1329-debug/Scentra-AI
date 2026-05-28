# Fase 6 - Gobierno AI, Memoria Colectiva y Orquestador Multiagente

Fecha: 2026-05-22
Producto: Scentra AI
Alcance: SaaS multi-tenant con AI Agents, CRM conversacional, Meta channels, workflows, remarketing y observabilidad.

## Objetivo de la fase

La Fase 6 convierte el modulo AI Agents en una capa mas enterprise. El objetivo no es solo crear agentes aislados, sino permitir que trabajen bajo gobierno, trazabilidad, presupuestos, aprobaciones, versionado de prompts y una memoria colectiva por tenant.

## Implementado en esta fase

1. Memoria colectiva entre agentes

Se agrego una tabla para registrar aprendizajes compartidos entre agentes del mismo tenant:

- hechos
- decisiones
- restricciones
- insights
- handoffs
- riesgos
- preferencias

Cada registro guarda:

- tenant_id
- agente fuente
- tipo de memoria
- alcance
- titulo
- contenido
- nivel de confianza
- visibilidad
- etiquetas
- auditoria
- expiracion opcional

Esto permite que un Sales Agent, Support Agent, Advisor Agent o Profesor Agent no trabajen como islas.

2. Gobierno de prompts

Se agrego base para versionar prompts por agente:

- versiones draft
- etiqueta de version
- prompt preview
- variables JSON
- estado
- version activa
- auditoria de creador

Esto prepara a Scentra para:

- historial de prompts
- rollback
- aprobacion antes de activar cambios
- A/B testing de prompts
- comparacion de resultados por version

3. Aprobaciones de tool calling

Se agrego base para registrar aprobaciones de herramientas sensibles:

- tool_code
- action_type
- modulo objetivo
- payload solicitado
- riesgo
- estado
- usuario que decide
- nota de decision

Esto sera clave para que los agentes puedan sugerir acciones sin ejecutar cambios delicados automaticamente.

4. Politicas de presupuesto por agente

Se agrego base para presupuestos enterprise:

- limite mensual de tokens
- limite mensual de costo
- hard stop
- alerta de consumo
- auditoria de cambios

Esto complementa lo que ya existia en el builder de agente.

5. Eventos de coordinacion

Se agrego base para un futuro orquestador:

- agente fuente
- agente destino
- tipo de evento
- resumen
- payload
- estado

Esto permitira construir un Agent Orchestrator real en fases siguientes.

6. Endpoint de gobierno

Nuevo endpoint:

```http
GET /saas/v1/agents/governance
```

Devuelve:

- conteos de memoria colectiva
- aprobaciones pendientes
- versiones de prompt
- eventos de coordinacion
- resumen del orquestador propuesto
- ultimas memorias colectivas
- aprobaciones recientes
- versiones de prompt recientes

7. Endpoints de memoria colectiva

```http
GET /saas/v1/agents/collective-memory
POST /saas/v1/agents/collective-memory
DELETE /saas/v1/agents/collective-memory/{memory_id}
```

8. Endpoint de versiones de prompt

```http
POST /saas/v1/agents/{agent_id}/prompt-versions
```

9. Frontend AI Agents - pestaña Gobierno fase 6

Se agrego una pestaña nueva dentro de AI Agents:

- Gobierno fase 6
- metricas de memoria colectiva
- aprobaciones pendientes
- versiones de prompt
- eventos de coordinacion
- mapa conceptual del orquestador
- formulario para crear memorias colectivas
- listado de memorias colectivas
- borrado de memorias colectivas

10. Agente Profesor

Se agrego al catalogo el nuevo agente:

- codigo: teacher
- nombre: Profesor Tutor Agent
- categoria: vertical_education
- canales: WhatsApp, Instagram, Facebook, Web
- herramientas: education.tutor, knowledge.search, conversation.reply, crm.update
- memoria: corta, semantica, knowledge grounded, contexto vertical, memoria colectiva
- uso: resolver dudas de estudiantes fuera de clase, explicar paso a paso, detectar bloqueos y escalar al profesor humano

## Diseno en papel - Memoria Colectiva y Orquestador

### Problema que resuelve

Sin memoria colectiva, cada agente toma decisiones con su propio contexto. Esto puede provocar:

- respuestas inconsistentes
- duplicidad de acciones
- un agente contradiciendo a otro
- mala coordinacion entre ventas, soporte, operaciones y advisor
- perdida de aprendizajes importantes

### Propuesta

Crear un Agent Orchestrator con patron Blackboard.

El Blackboard es una memoria compartida por tenant donde los agentes publican informacion relevante y leen contexto antes de actuar.

### Componentes

1. Collective Memory Store

Guarda aprendizajes compartidos con:

- fuente
- confianza
- vigencia
- visibilidad
- etiquetas
- alcance
- auditoria

2. Orchestrator Runtime

Servicio que:

- observa eventos
- decide que agente debe actuar
- detecta conflictos
- crea handoffs
- bloquea acciones riesgosas
- evita duplicados
- solicita aprobacion humana cuando corresponde

3. Conflict Resolver

Detecta casos como:

- Sales Agent quiere enviar descuento, pero Operations Agent registro restriccion
- Campaign Agent propone remarketing, pero Support Agent detecto queja abierta
- Profesor Agent responde sobre un tema no autorizado por Knowledge Agent

4. Agent Handoff Protocol

Formato estandar para traspasar trabajo:

```json
{
  "from_agent": "support",
  "to_agent": "sales",
  "reason": "cliente resolvio duda tecnica y esta listo para cotizacion",
  "context": "pregunto por plan pro, presupuesto alto, urgencia esta semana",
  "risk": "medium",
  "recommended_action": "preparar propuesta"
}
```

5. Human Approval Layer

Cualquier accion sensible debe pasar por aprobacion:

- enviar mensajes masivos
- cambiar CRM critico
- crear campanas
- activar workflows
- modificar datos de integraciones
- tocar pagos o cobros
- responder temas legales, medicos o financieros

### Flujo recomendado

1. Entra evento: mensaje, comentario, webhook, error, cambio CRM o resultado de campana.
2. Event bus publica evento.
3. Orchestrator consulta memoria colectiva.
4. Selecciona agente responsable.
5. Agente arma contexto.
6. Si necesita tool calling, genera accion.
7. Si es segura, ejecuta o prepara draft.
8. Si es sensible, solicita aprobacion humana.
9. Resultado vuelve a memoria colectiva.
10. Advisor resume impacto y sugiere siguientes pasos.

### Reglas de seguridad

- Nunca compartir memoria entre tenants.
- Toda memoria debe tener fuente y timestamp.
- Datos sensibles deben tener visibilidad restringida.
- Las memorias deben poder expirar.
- Las acciones destructivas requieren aprobacion.
- Los prompts deben versionarse.
- Los conflictos entre agentes deben quedar auditados.

## Roadmap sugerido para completar esta fase

### Fase 6.1 - Completar UI de gobierno

- activar/versionar prompts desde frontend
- listar aprobaciones de tools con acciones aprobar/rechazar
- mostrar presupuesto real por agente
- mostrar conflictos detectados

### Fase 6.2 - Orquestador real

- worker o scheduler que observe eventos
- reglas de seleccion de agente
- generacion de handoffs
- prevencion de acciones duplicadas

### Fase 6.3 - Memoria colectiva en runtime

- inyectar memoria colectiva en Sales, Support, Advisor y Profesor
- ranking por relevancia
- TTL
- confianza
- tags

### Fase 6.4 - Conflictos y locks

- detectar conflictos entre agentes
- bloquear ejecuciones duplicadas
- ownership temporal de conversaciones o tareas

### Fase 6.5 - Governance enterprise

- aprobacion de prompts
- rollback de prompts
- politicas por industria
- budgets estrictos
- auditoria avanzada

## Riesgos a tener en cuenta

- Demasiada memoria puede contaminar el contexto si no hay ranking.
- Agentes sin orquestador pueden ejecutar acciones duplicadas.
- Sin TTL, reglas antiguas pueden seguir afectando decisiones.
- Sin versionado activo, es dificil saber que prompt genero una accion.
- Sin aprobacion humana, los agentes pueden hacer cambios delicados demasiado rapido.

## Recomendacion tecnica

El siguiente paso mas importante es Fase 6.2: crear el Orchestrator Runtime como worker independiente o tarea recurrente. Mi recomendacion es implementarlo como worker separado porque a futuro tendra colas, retries, locks y observabilidad propia.

