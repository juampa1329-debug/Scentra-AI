from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app_saas.ai_gateway.service import ensure_ai_gateway_tables
from app_saas.billing.limits import ensure_feature_enabled, ensure_tenant_operational

ALL_AGENT_TYPES = [
    "advisor",
    "sales",
    "support",
    "crm_intelligence",
    "campaign_strategist",
    "retention",
    "operations",
    "executive_summary",
    "knowledge",
    "workflow_architect",
    "restaurant_reservations",
    "restaurant_menu",
    "hotel_concierge",
    "hotel_booking",
    "appointment_scheduler",
    "real_estate_leads",
    "education_admissions",
    "automotive_service",
    "beauty_booking",
    "logistics_tracking",
    "collections_agent",
    "reputation_manager",
    "medical_appointment",
    "tourism_itinerary",
    "hr_recruiting",
    "multi_location_ops",
]

CORE_AGENT_TYPES = ALL_AGENT_TYPES[:10]

EDITABLE_STATUSES = {"draft", "active", "paused", "archived"}

CHANNEL_CATALOG: list[dict[str, str]] = [
    {"code": "global", "label": "Global", "description": "Analisis y acciones internas sin canal conversacional directo."},
    {"code": "whatsapp", "label": "WhatsApp", "description": "Conversaciones, plantillas, remarketing y mensajes Cloud API."},
    {"code": "instagram", "label": "Instagram", "description": "DMs, comentarios, menciones y activos Instagram Business."},
    {"code": "facebook", "label": "Facebook", "description": "Messenger, comentarios y paginas Meta conectadas."},
    {"code": "web", "label": "Web", "description": "Widget, formularios, sitio web y landing pages."},
]

TOOL_CATALOG: list[dict[str, str]] = [
    {"code": "advisor.actions", "group": "Advisor", "label": "Acciones Advisor", "description": "Crear acciones con aprobacion humana."},
    {"code": "advisor.summarize", "group": "Advisor", "label": "Resumenes", "description": "Crear balances ejecutivos y resumenes operativos."},
    {"code": "analytics.read", "group": "Analytics", "label": "Leer analytics", "description": "Consultar KPIs, conversion y actividad."},
    {"code": "campaigns.create_draft", "group": "Campanas", "label": "Crear borradores", "description": "Proponer campanas antes de publicarlas."},
    {"code": "campaigns.suggest", "group": "Campanas", "label": "Sugerir campanas", "description": "Recomendar campanas segun comportamiento."},
    {"code": "catalog.search", "group": "Commerce", "label": "Buscar catalogo", "description": "Consultar productos WooCommerce o Shopify."},
    {"code": "conversation.reply", "group": "Inbox", "label": "Responder conversaciones", "description": "Preparar o enviar respuestas conversacionales."},
    {"code": "crm.read", "group": "CRM", "label": "Leer CRM", "description": "Consultar clientes, etapas, etiquetas e historial."},
    {"code": "crm.update", "group": "CRM", "label": "Actualizar CRM", "description": "Actualizar datos del cliente con reglas de seguridad."},
    {"code": "diagnostics.read", "group": "Operaciones", "label": "Leer diagnosticos", "description": "Consultar health checks y errores recientes."},
    {"code": "knowledge.audit", "group": "Knowledge", "label": "Auditar knowledge", "description": "Detectar huecos o fuentes desactualizadas."},
    {"code": "knowledge.search", "group": "Knowledge", "label": "Buscar knowledge", "description": "Usar RAG y fuentes internas."},
    {"code": "logs.read", "group": "Operaciones", "label": "Leer logs", "description": "Revisar eventos operacionales."},
    {"code": "meta.checks", "group": "Meta", "label": "Checks Meta", "description": "Validar tokens, suscripciones y webhooks Meta."},
    {"code": "rag.evaluate", "group": "Knowledge", "label": "Evaluar RAG", "description": "Medir calidad de recuperacion de contexto."},
    {"code": "remarketing.suggest", "group": "Remarketing", "label": "Sugerir remarketing", "description": "Proponer recuperaciones y flujos por etapa."},
    {"code": "reports.create", "group": "Analytics", "label": "Crear reportes", "description": "Preparar reportes ejecutivos."},
    {"code": "segments.create", "group": "CRM", "label": "Crear segmentos", "description": "Proponer segmentos para campanas y seguimiento."},
    {"code": "templates.read", "group": "Plantillas", "label": "Leer plantillas", "description": "Consultar plantillas aprobadas, pendientes y rechazadas."},
    {"code": "tickets.create", "group": "Soporte", "label": "Crear tickets", "description": "Escalar casos de soporte."},
    {"code": "triggers.suggest", "group": "Triggers", "label": "Sugerir triggers", "description": "Proponer reglas por palabra clave, tiempo o estado."},
    {"code": "webhooks.repair", "group": "Operaciones", "label": "Reparar webhooks", "description": "Preparar reparaciones seguras para webhooks."},
    {"code": "workflows.create_draft", "group": "Workflows", "label": "Crear workflow draft", "description": "Disenar flujos sin publicarlos automaticamente."},
    {"code": "reservations.manage", "group": "Verticales", "label": "Reservas y mesas", "description": "Gestionar solicitudes de reserva, horarios y disponibilidad."},
    {"code": "menu.lookup", "group": "Verticales", "label": "Menu y alergenos", "description": "Consultar menu, precios, restricciones y recomendaciones."},
    {"code": "booking.manage", "group": "Verticales", "label": "Reservas hoteleras", "description": "Preparar reservas, disponibilidad, upgrades y solicitudes de huespedes."},
    {"code": "appointments.schedule", "group": "Verticales", "label": "Agenda y citas", "description": "Calificar, agendar, confirmar o reprogramar citas."},
    {"code": "property.search", "group": "Verticales", "label": "Busqueda inmobiliaria", "description": "Filtrar inmuebles, presupuestos y visitas."},
    {"code": "admissions.qualify", "group": "Verticales", "label": "Admisiones educativas", "description": "Calificar aspirantes, programas y requisitos."},
    {"code": "service.intake", "group": "Verticales", "label": "Intake de servicio", "description": "Recolectar datos para taller, soporte tecnico, salud o servicios locales."},
    {"code": "order.track", "group": "Verticales", "label": "Seguimiento logistico", "description": "Consultar estados de pedido, entrega, guia o incidencia."},
    {"code": "payments.followup", "group": "Verticales", "label": "Seguimiento de pagos", "description": "Crear recordatorios, acuerdos y alertas de cartera."},
    {"code": "reviews.manage", "group": "Verticales", "label": "Resenas y reputacion", "description": "Clasificar comentarios, sugerir respuestas y detectar crisis."},
    {"code": "recruiting.qualify", "group": "Verticales", "label": "Reclutamiento", "description": "Precalificar candidatos y coordinar entrevistas."},
    {"code": "locations.compare", "group": "Verticales", "label": "Multi-sede", "description": "Comparar sedes, sucursales y desempeno operacional."},
    {"code": "itinerary.plan", "group": "Verticales", "label": "Itinerarios", "description": "Crear planes de viaje, tours y recomendaciones."},
]

ACTION_DRAFT_PRESETS: list[dict[str, str]] = [
    {
        "tool_code": "advisor.actions",
        "action_type": "advisor_action",
        "target_module": "advisor",
        "label": "Accion libre del agente",
        "description": "Prepara una recomendacion accionable para aprobacion humana.",
    },
    {
        "tool_code": "crm.update",
        "action_type": "review_crm",
        "target_module": "customers",
        "label": "Revisar o actualizar CRM",
        "description": "Abre el CRM con una propuesta de cambios, sin modificar datos automaticamente.",
    },
    {
        "tool_code": "campaigns.create_draft",
        "action_type": "create_campaign_draft",
        "target_module": "campaigns",
        "label": "Crear borrador de campana",
        "description": "Crea una campana en borrador despues de aprobacion.",
    },
    {
        "tool_code": "triggers.suggest",
        "action_type": "create_trigger_draft",
        "target_module": "campaigns",
        "label": "Crear borrador de trigger",
        "description": "Propone un trigger desactivado para revision manual.",
    },
    {
        "tool_code": "remarketing.suggest",
        "action_type": "create_remarketing_flow_draft",
        "target_module": "campaigns",
        "label": "Crear flow de remarketing",
        "description": "Prepara un flujo de remarketing en borrador.",
    },
    {
        "tool_code": "webhooks.repair",
        "action_type": "open_debug",
        "target_module": "settings",
        "label": "Revisar diagnostico Meta",
        "description": "Dirige al debug antes de reparar integraciones o webhooks.",
    },
    {
        "tool_code": "reports.create",
        "action_type": "reports.create",
        "target_module": "analytics",
        "label": "Preparar reporte ejecutivo",
        "description": "Deja un borrador de reporte para revisar antes de compartir.",
    },
]

PROVIDER_ROUTE_CATALOG: list[dict[str, str]] = [
    {"code": "advisor", "label": "Advisor", "description": "Analisis estrategico y recomendaciones."},
    {"code": "sales", "label": "Ventas", "description": "Conversaciones comerciales y cierre."},
    {"code": "support", "label": "Soporte", "description": "FAQs, politicas y escalacion."},
    {"code": "classification", "label": "Clasificacion", "description": "Scoring, etiquetas y segmentacion."},
    {"code": "campaigns", "label": "Campanas", "description": "Estrategia, copies y automatizaciones."},
    {"code": "analysis", "label": "Analisis", "description": "Patrones, riesgo y oportunidades."},
    {"code": "ops", "label": "Operaciones", "description": "Diagnostico tecnico y self-healing."},
    {"code": "summaries", "label": "Resumenes", "description": "Reportes y balances ejecutivos."},
    {"code": "rag", "label": "RAG", "description": "Knowledge base y respuestas fundamentadas."},
    {"code": "workflow_reasoning", "label": "Workflows", "description": "Diseno de flujos y reasoning operacional."},
    {"code": "vertical_ops", "label": "Verticales", "description": "Flujos especializados por industria."},
]

AI_PROVIDER_CATALOG: list[dict[str, str]] = [
    {"code": "google", "label": "Google Gemini", "description": "Buen balance para resumenes, RAG y respuestas comerciales."},
    {"code": "mistral", "label": "Mistral", "description": "Clasificacion, scoring y tareas de bajo costo."},
    {"code": "openrouter", "label": "OpenRouter", "description": "Fallback flexible y acceso a catalogo amplio."},
    {"code": "kimi", "label": "Kimi", "description": "Reasoning, contexto largo y analisis complejo."},
]

MEMORY_FLAG_CATALOG: list[dict[str, str]] = [
    {"code": "short_term", "label": "Memoria corta", "description": "Usa el contexto reciente del modulo o conversacion."},
    {"code": "semantic", "label": "Memoria semantica", "description": "Recupera conocimiento relevante por similitud."},
    {"code": "business_summary", "label": "Resumen de negocio", "description": "Mantiene una vision ejecutiva del tenant."},
    {"code": "customer_profile", "label": "Perfil de cliente", "description": "Usa datos CRM e historial del contacto."},
    {"code": "knowledge_grounded", "label": "Basado en knowledge", "description": "Prioriza respuestas soportadas por fuentes."},
    {"code": "campaign_history", "label": "Historial de campanas", "description": "Considera campanas y resultados previos."},
    {"code": "incident_history", "label": "Historial de incidentes", "description": "Considera errores y reparaciones anteriores."},
    {"code": "workflow_history", "label": "Historial de workflows", "description": "Aprende de automatizaciones existentes."},
    {"code": "vertical_context", "label": "Contexto vertical", "description": "Usa reglas, catalogos, horarios y politicas de la industria."},
]

APPROVAL_FLAG_CATALOG: list[dict[str, str]] = [
    {"code": "requires_human_approval", "label": "Requiere aprobacion humana", "description": "Las acciones sensibles quedan como borrador."},
    {"code": "can_execute_safe_actions", "label": "Puede ejecutar acciones seguras", "description": "Permite acciones no destructivas aprobadas por politica."},
    {"code": "can_send_messages", "label": "Puede enviar mensajes", "description": "Habilita respuestas conversacionales cuando el runtime lo soporte."},
    {"code": "can_update_crm", "label": "Puede actualizar CRM", "description": "Permite modificar fichas de cliente con auditoria."},
]

AGENT_TEMPLATES: dict[str, dict[str, Any]] = {
    "advisor": {
        "agent_type": "advisor",
        "name": "Advisor Agent",
        "category": "strategy",
        "headline": "Copiloto empresarial y estratega operativo.",
        "description": "Analiza CRM, conversaciones, campanas, triggers y operacion para sugerir acciones.",
        "channels": ["global"],
        "tools": ["crm.read", "analytics.read", "advisor.actions", "campaigns.suggest", "diagnostics.read"],
        "goals": [
            "Detectar oportunidades comerciales",
            "Priorizar clientes y cuellos de botella",
            "Sugerir campanas, triggers y automatizaciones",
        ],
        "personality": {"tone": "estrategico, claro y accionable", "risk_posture": "conservador"},
        "provider_policy": {"route": "advisor", "preferred": "kimi", "fallback": "openrouter"},
        "memory_policy": {"short_term": True, "semantic": True, "business_summary": True},
        "approval_policy": {"requires_human_approval": True, "can_execute_safe_actions": True},
        "risk_level": "medium",
    },
    "sales": {
        "agent_type": "sales",
        "name": "Sales Agent",
        "category": "revenue",
        "headline": "Calificacion, seguimiento y cierre de leads.",
        "description": "Acompana conversaciones comerciales, detecta intencion y propone proximos pasos.",
        "channels": ["whatsapp", "instagram"],
        "tools": ["crm.update", "conversation.reply", "catalog.search", "campaigns.suggest"],
        "goals": ["Calificar leads", "Recuperar conversaciones abiertas", "Aumentar conversion"],
        "personality": {"tone": "humano, vendedor consultivo y breve", "risk_posture": "moderado"},
        "provider_policy": {"route": "sales", "preferred": "google", "fallback": "openrouter"},
        "memory_policy": {"short_term": True, "semantic": True, "customer_profile": True},
        "approval_policy": {"requires_human_approval": True, "can_execute_safe_actions": False},
        "risk_level": "high",
    },
    "support": {
        "agent_type": "support",
        "name": "Support Agent",
        "category": "service",
        "headline": "FAQs, soporte y escalacion humana.",
        "description": "Responde preguntas frecuentes usando knowledge base y escala casos sensibles.",
        "channels": ["whatsapp", "instagram"],
        "tools": ["knowledge.search", "conversation.reply", "crm.update", "tickets.create"],
        "goals": ["Resolver dudas repetidas", "Reducir tiempos de respuesta", "Escalar casos criticos"],
        "personality": {"tone": "calido, preciso y resolutivo", "risk_posture": "conservador"},
        "provider_policy": {"route": "support", "preferred": "google", "fallback": "mistral"},
        "memory_policy": {"short_term": True, "semantic": True, "knowledge_grounded": True},
        "approval_policy": {"requires_human_approval": True, "can_execute_safe_actions": False},
        "risk_level": "medium",
    },
    "crm_intelligence": {
        "agent_type": "crm_intelligence",
        "name": "CRM Intelligence Agent",
        "category": "crm",
        "headline": "Scoring, segmentacion y salud del pipeline.",
        "description": "Analiza clientes, etapas, tags, pagos e intereses para priorizar oportunidades.",
        "channels": ["global"],
        "tools": ["crm.read", "crm.update", "analytics.read", "segments.create"],
        "goals": ["Puntuar leads", "Segmentar clientes", "Detectar etapas estancadas"],
        "personality": {"tone": "analitico, concreto y orientado a pipeline"},
        "provider_policy": {"route": "classification", "preferred": "mistral", "fallback": "openrouter"},
        "memory_policy": {"short_term": False, "semantic": True, "pipeline_snapshots": True},
        "approval_policy": {"requires_human_approval": True, "can_execute_safe_actions": True},
        "risk_level": "medium",
    },
    "campaign_strategist": {
        "agent_type": "campaign_strategist",
        "name": "Campaign Strategist Agent",
        "category": "marketing",
        "headline": "Ideas de campanas, triggers y remarketing.",
        "description": "Propone campanas, secuencias y reglas basadas en comportamiento real.",
        "channels": ["whatsapp", "instagram"],
        "tools": ["campaigns.create_draft", "triggers.suggest", "remarketing.suggest", "templates.read"],
        "goals": ["Crear campanas accionables", "Optimizar remarketing", "Mejorar plantillas"],
        "personality": {"tone": "creativo, comercial y medible"},
        "provider_policy": {"route": "campaigns", "preferred": "kimi", "fallback": "openrouter"},
        "memory_policy": {"short_term": False, "semantic": True, "campaign_history": True},
        "approval_policy": {"requires_human_approval": True, "can_execute_safe_actions": True},
        "risk_level": "medium",
    },
    "retention": {
        "agent_type": "retention",
        "name": "Retention Agent",
        "category": "growth",
        "headline": "Churn, clientes dormidos y recuperacion.",
        "description": "Detecta riesgo de abandono y sugiere acciones de recuperacion.",
        "channels": ["whatsapp", "instagram"],
        "tools": ["crm.read", "analytics.read", "remarketing.suggest", "segments.create"],
        "goals": ["Reducir abandono", "Reactivar clientes dormidos", "Priorizar retencion"],
        "personality": {"tone": "preventivo, empatico y orientado a retencion"},
        "provider_policy": {"route": "analysis", "preferred": "mistral", "fallback": "openrouter"},
        "memory_policy": {"short_term": False, "semantic": True, "behavioral_memory": True},
        "approval_policy": {"requires_human_approval": True, "can_execute_safe_actions": True},
        "risk_level": "medium",
    },
    "operations": {
        "agent_type": "operations",
        "name": "Operations Agent",
        "category": "ops",
        "headline": "Monitoreo tecnico, Meta health y auto-reparacion.",
        "description": "Observa webhooks, errores, workers, tokens, Meta y recomienda reparaciones.",
        "channels": ["global"],
        "tools": ["diagnostics.read", "meta.checks", "webhooks.repair", "logs.read"],
        "goals": ["Detectar fallas operativas", "Sugerir reparaciones", "Priorizar incidentes"],
        "personality": {"tone": "tecnico, claro y preventivo", "risk_posture": "conservador"},
        "provider_policy": {"route": "ops", "preferred": "kimi", "fallback": "openrouter"},
        "memory_policy": {"short_term": True, "semantic": True, "incident_history": True},
        "approval_policy": {"requires_human_approval": True, "can_execute_safe_actions": False},
        "risk_level": "high",
    },
    "executive_summary": {
        "agent_type": "executive_summary",
        "name": "Executive Summary Agent",
        "category": "executive",
        "headline": "Balances, reportes y resumenes ejecutivos.",
        "description": "Convierte operacion, ventas y soporte en informes ejecutivos faciles de leer.",
        "channels": ["global"],
        "tools": ["analytics.read", "crm.read", "advisor.summarize", "reports.create"],
        "goals": ["Crear balances ejecutivos", "Explicar KPIs", "Resumir prioridades"],
        "personality": {"tone": "ejecutivo, sobrio y accionable"},
        "provider_policy": {"route": "summaries", "preferred": "google", "fallback": "openrouter"},
        "memory_policy": {"short_term": False, "semantic": True, "report_history": True},
        "approval_policy": {"requires_human_approval": False, "can_execute_safe_actions": True},
        "risk_level": "low",
    },
    "knowledge": {
        "agent_type": "knowledge",
        "name": "Knowledge Agent",
        "category": "knowledge",
        "headline": "RAG, politicas, documentos y FAQs.",
        "description": "Administra fuentes de conocimiento y valida respuestas contra documentos.",
        "channels": ["global"],
        "tools": ["knowledge.search", "knowledge.audit", "rag.evaluate"],
        "goals": ["Mejorar base de conocimiento", "Reducir alucinaciones", "Detectar huecos de informacion"],
        "personality": {"tone": "preciso, verificable y didactico"},
        "provider_policy": {"route": "rag", "preferred": "google", "fallback": "mistral"},
        "memory_policy": {"short_term": False, "semantic": True, "rag": True},
        "approval_policy": {"requires_human_approval": False, "can_execute_safe_actions": True},
        "risk_level": "low",
    },
    "workflow_architect": {
        "agent_type": "workflow_architect",
        "name": "Workflow Architect Agent",
        "category": "automation",
        "headline": "Diseno de automatizaciones y optimizacion de triggers.",
        "description": "Encuentra patrones operativos y propone flujos automatizados con aprobacion humana.",
        "channels": ["global"],
        "tools": ["workflows.create_draft", "triggers.suggest", "remarketing.suggest", "analytics.read"],
        "goals": ["Disenar workflows", "Optimizar triggers", "Reducir trabajo manual"],
        "personality": {"tone": "arquitecto, practico y medible"},
        "provider_policy": {"route": "workflow_reasoning", "preferred": "kimi", "fallback": "openrouter"},
        "memory_policy": {"short_term": True, "semantic": True, "workflow_history": True},
        "approval_policy": {"requires_human_approval": True, "can_execute_safe_actions": True},
        "risk_level": "medium",
    },
    "restaurant_reservations": {
        "agent_type": "restaurant_reservations",
        "name": "Restaurant Reservations Agent",
        "category": "vertical_restaurant",
        "headline": "Reservas, mesas, horarios y confirmaciones.",
        "description": "Gestiona solicitudes de reserva, confirma disponibilidad y prepara handoff humano para cambios sensibles.",
        "channels": ["whatsapp", "instagram", "facebook", "web"],
        "tools": ["reservations.manage", "conversation.reply", "crm.update", "knowledge.search"],
        "goals": ["Capturar fecha, hora y numero de personas", "Confirmar o dejar pendiente segun disponibilidad", "Reducir no-shows con recordatorios"],
        "personality": {"tone": "hospitalario, rapido y preciso", "risk_posture": "conservador"},
        "provider_policy": {"route": "vertical_ops", "preferred": "google", "fallback": "openrouter"},
        "memory_policy": {"short_term": True, "semantic": True, "customer_profile": True, "vertical_context": True},
        "approval_policy": {"requires_human_approval": True, "can_send_messages": True, "can_update_crm": True},
        "risk_level": "medium",
    },
    "restaurant_menu": {
        "agent_type": "restaurant_menu",
        "name": "Menu & Allergens Agent",
        "category": "vertical_restaurant",
        "headline": "Menu, alergenos, recomendaciones y pedidos.",
        "description": "Responde sobre platos, restricciones, precios y recomendaciones usando knowledge base o catalogo.",
        "channels": ["whatsapp", "instagram", "facebook", "web"],
        "tools": ["menu.lookup", "catalog.search", "knowledge.search", "conversation.reply"],
        "goals": ["Responder dudas de menu", "Recomendar opciones segun gustos o restricciones", "Derivar a pedido o reserva"],
        "personality": {"tone": "cercano, apetitoso y claro", "risk_posture": "conservador"},
        "provider_policy": {"route": "rag", "preferred": "google", "fallback": "mistral"},
        "memory_policy": {"short_term": True, "semantic": True, "knowledge_grounded": True, "vertical_context": True},
        "approval_policy": {"requires_human_approval": False, "can_send_messages": True},
        "risk_level": "low",
    },
    "hotel_concierge": {
        "agent_type": "hotel_concierge",
        "name": "Hotel Concierge Agent",
        "category": "vertical_hospitality",
        "headline": "Concierge, servicios, solicitudes y upsell.",
        "description": "Atiende solicitudes de huespedes, recomienda servicios y escala casos de operacion hotelera.",
        "channels": ["whatsapp", "instagram", "facebook", "web"],
        "tools": ["booking.manage", "conversation.reply", "knowledge.search", "crm.update"],
        "goals": ["Resolver solicitudes frecuentes", "Sugerir servicios y upgrades", "Escalar incidentes de hospedaje"],
        "personality": {"tone": "premium, atento y resolutivo", "risk_posture": "conservador"},
        "provider_policy": {"route": "vertical_ops", "preferred": "kimi", "fallback": "openrouter"},
        "memory_policy": {"short_term": True, "semantic": True, "customer_profile": True, "vertical_context": True},
        "approval_policy": {"requires_human_approval": True, "can_send_messages": True, "can_update_crm": True},
        "risk_level": "medium",
    },
    "hotel_booking": {
        "agent_type": "hotel_booking",
        "name": "Hotel Booking Agent",
        "category": "vertical_hospitality",
        "headline": "Disponibilidad, cotizacion y seguimiento de reservas.",
        "description": "Califica estadias, recopila fechas y preferencias, y prepara cotizaciones o handoff comercial.",
        "channels": ["whatsapp", "instagram", "facebook", "web"],
        "tools": ["booking.manage", "crm.update", "conversation.reply", "campaigns.suggest"],
        "goals": ["Capturar fechas y cantidad de huespedes", "Calificar presupuesto y motivo del viaje", "Preparar proximo paso comercial"],
        "personality": {"tone": "consultivo, claro y orientado a reserva", "risk_posture": "moderado"},
        "provider_policy": {"route": "sales", "preferred": "google", "fallback": "openrouter"},
        "memory_policy": {"short_term": True, "semantic": True, "customer_profile": True, "vertical_context": True},
        "approval_policy": {"requires_human_approval": True, "can_send_messages": True, "can_update_crm": True},
        "risk_level": "medium",
    },
    "appointment_scheduler": {
        "agent_type": "appointment_scheduler",
        "name": "Appointment Scheduler Agent",
        "category": "vertical_services",
        "headline": "Agenda, confirmaciones y reprogramaciones.",
        "description": "Gestiona solicitudes de cita para servicios profesionales, salud no diagnostica, belleza o consultorias.",
        "channels": ["whatsapp", "instagram", "facebook", "web"],
        "tools": ["appointments.schedule", "conversation.reply", "crm.update", "knowledge.search"],
        "goals": ["Capturar motivo de cita", "Recolectar datos minimos", "Confirmar, reprogramar o escalar"],
        "personality": {"tone": "ordenado, amable y breve", "risk_posture": "conservador"},
        "provider_policy": {"route": "vertical_ops", "preferred": "google", "fallback": "mistral"},
        "memory_policy": {"short_term": True, "semantic": True, "customer_profile": True, "vertical_context": True},
        "approval_policy": {"requires_human_approval": True, "can_send_messages": True, "can_update_crm": True},
        "risk_level": "medium",
    },
    "real_estate_leads": {
        "agent_type": "real_estate_leads",
        "name": "Real Estate Lead Agent",
        "category": "vertical_real_estate",
        "headline": "Calificacion inmobiliaria y agenda de visitas.",
        "description": "Califica compradores, arrendatarios o inversionistas segun ubicacion, presupuesto, tiempos y necesidades.",
        "channels": ["whatsapp", "instagram", "facebook", "web"],
        "tools": ["property.search", "crm.update", "conversation.reply", "segments.create"],
        "goals": ["Calificar presupuesto y zona", "Detectar urgencia y tipo de inmueble", "Preparar visita o asesor humano"],
        "personality": {"tone": "consultivo, confiable y directo", "risk_posture": "moderado"},
        "provider_policy": {"route": "sales", "preferred": "kimi", "fallback": "openrouter"},
        "memory_policy": {"short_term": True, "semantic": True, "customer_profile": True, "vertical_context": True},
        "approval_policy": {"requires_human_approval": True, "can_send_messages": True, "can_update_crm": True},
        "risk_level": "medium",
    },
    "education_admissions": {
        "agent_type": "education_admissions",
        "name": "Education Admissions Agent",
        "category": "vertical_education",
        "headline": "Admisiones, programas y seguimiento de aspirantes.",
        "description": "Orienta aspirantes, califica interes y prepara seguimiento para matrículas o admisiones.",
        "channels": ["whatsapp", "instagram", "facebook", "web"],
        "tools": ["admissions.qualify", "knowledge.search", "crm.update", "conversation.reply"],
        "goals": ["Identificar programa de interes", "Resolver requisitos frecuentes", "Agendar asesor o enviar siguiente paso"],
        "personality": {"tone": "orientador, claro y motivador", "risk_posture": "conservador"},
        "provider_policy": {"route": "support", "preferred": "google", "fallback": "mistral"},
        "memory_policy": {"short_term": True, "semantic": True, "knowledge_grounded": True, "vertical_context": True},
        "approval_policy": {"requires_human_approval": True, "can_send_messages": True, "can_update_crm": True},
        "risk_level": "medium",
    },
    "automotive_service": {
        "agent_type": "automotive_service",
        "name": "Automotive Service Agent",
        "category": "vertical_automotive",
        "headline": "Taller, repuestos, mantenimientos y cotizaciones.",
        "description": "Recolecta datos de vehiculo, problema y urgencia para preparar servicio o cotizacion.",
        "channels": ["whatsapp", "instagram", "facebook", "web"],
        "tools": ["service.intake", "appointments.schedule", "catalog.search", "crm.update"],
        "goals": ["Capturar placa/modelo/servicio requerido", "Priorizar urgencias", "Preparar cita o cotizacion"],
        "personality": {"tone": "practico, tecnico y tranquilizador", "risk_posture": "conservador"},
        "provider_policy": {"route": "vertical_ops", "preferred": "google", "fallback": "openrouter"},
        "memory_policy": {"short_term": True, "semantic": True, "customer_profile": True, "vertical_context": True},
        "approval_policy": {"requires_human_approval": True, "can_send_messages": True, "can_update_crm": True},
        "risk_level": "medium",
    },
    "beauty_booking": {
        "agent_type": "beauty_booking",
        "name": "Salon & Beauty Booking Agent",
        "category": "vertical_beauty",
        "headline": "Servicios, agenda, paquetes y recordatorios.",
        "description": "Agenda servicios de belleza, recomienda paquetes y captura preferencias del cliente.",
        "channels": ["whatsapp", "instagram", "facebook", "web"],
        "tools": ["appointments.schedule", "catalog.search", "crm.update", "conversation.reply"],
        "goals": ["Agendar servicios", "Recomendar paquetes segun necesidad", "Reducir ausencias con recordatorios"],
        "personality": {"tone": "cercano, estetico y consultivo", "risk_posture": "moderado"},
        "provider_policy": {"route": "sales", "preferred": "google", "fallback": "openrouter"},
        "memory_policy": {"short_term": True, "semantic": True, "customer_profile": True, "vertical_context": True},
        "approval_policy": {"requires_human_approval": True, "can_send_messages": True, "can_update_crm": True},
        "risk_level": "medium",
    },
    "logistics_tracking": {
        "agent_type": "logistics_tracking",
        "name": "Logistics Tracking Agent",
        "category": "vertical_logistics",
        "headline": "Estados de pedido, entregas e incidencias.",
        "description": "Atiende consultas de envio, actualiza CRM y escala incidencias de entrega.",
        "channels": ["whatsapp", "instagram", "facebook", "web"],
        "tools": ["order.track", "conversation.reply", "crm.update", "tickets.create"],
        "goals": ["Consultar estado de pedido", "Detectar incidencias", "Escalar retrasos o reclamos"],
        "personality": {"tone": "claro, calmado y operativo", "risk_posture": "conservador"},
        "provider_policy": {"route": "support", "preferred": "mistral", "fallback": "openrouter"},
        "memory_policy": {"short_term": True, "semantic": True, "customer_profile": True, "vertical_context": True},
        "approval_policy": {"requires_human_approval": True, "can_send_messages": True, "can_update_crm": True},
        "risk_level": "medium",
    },
    "collections_agent": {
        "agent_type": "collections_agent",
        "name": "Collections Follow-up Agent",
        "category": "vertical_finance",
        "headline": "Pagos pendientes, acuerdos y recordatorios.",
        "description": "Prioriza seguimiento de cartera con tono respetuoso, trazabilidad y aprobacion humana.",
        "channels": ["whatsapp", "facebook", "web"],
        "tools": ["payments.followup", "crm.read", "crm.update", "conversation.reply"],
        "goals": ["Detectar pagos pendientes", "Sugerir recordatorios seguros", "Preparar acuerdos para revision humana"],
        "personality": {"tone": "respetuoso, firme y cuidadoso", "risk_posture": "conservador"},
        "provider_policy": {"route": "analysis", "preferred": "mistral", "fallback": "openrouter"},
        "memory_policy": {"short_term": True, "semantic": True, "customer_profile": True, "vertical_context": True},
        "approval_policy": {"requires_human_approval": True, "can_send_messages": False, "can_update_crm": True},
        "risk_level": "high",
    },
    "reputation_manager": {
        "agent_type": "reputation_manager",
        "name": "Reviews & Reputation Agent",
        "category": "vertical_reputation",
        "headline": "Resenas, comentarios publicos y riesgo reputacional.",
        "description": "Clasifica comentarios, sugiere respuestas publicas y alerta temas sensibles o recurrentes.",
        "channels": ["instagram", "facebook", "web"],
        "tools": ["reviews.manage", "conversation.reply", "analytics.read", "advisor.actions"],
        "goals": ["Responder comentarios con criterio", "Detectar crisis o quejas repetidas", "Convertir feedback en acciones"],
        "personality": {"tone": "diplomatico, empatico y protector de marca", "risk_posture": "conservador"},
        "provider_policy": {"route": "classification", "preferred": "mistral", "fallback": "openrouter"},
        "memory_policy": {"short_term": True, "semantic": True, "business_summary": True, "vertical_context": True},
        "approval_policy": {"requires_human_approval": True, "can_send_messages": False, "can_execute_safe_actions": True},
        "risk_level": "high",
    },
    "medical_appointment": {
        "agent_type": "medical_appointment",
        "name": "Medical Appointment Agent",
        "category": "vertical_health",
        "headline": "Citas, intake basico y escalacion segura.",
        "description": "Agenda o prepara citas sin diagnosticar, sin dar consejo medico y escalando sintomas sensibles.",
        "channels": ["whatsapp", "facebook", "web"],
        "tools": ["appointments.schedule", "service.intake", "knowledge.search", "crm.update"],
        "goals": ["Capturar motivo administrativo de cita", "Evitar diagnostico o consejo medico", "Escalar urgencias o sintomas sensibles"],
        "personality": {"tone": "cuidadoso, humano y regulado", "risk_posture": "conservador"},
        "provider_policy": {"route": "support", "preferred": "google", "fallback": "mistral"},
        "memory_policy": {"short_term": True, "semantic": True, "knowledge_grounded": True, "vertical_context": True},
        "approval_policy": {"requires_human_approval": True, "can_send_messages": False, "can_update_crm": True},
        "risk_level": "high",
    },
    "tourism_itinerary": {
        "agent_type": "tourism_itinerary",
        "name": "Tourism Itinerary Agent",
        "category": "vertical_travel",
        "headline": "Itinerarios, tours, recomendaciones y upsell.",
        "description": "Ayuda a planear experiencias, recolecta preferencias y prepara propuestas turisticas.",
        "channels": ["whatsapp", "instagram", "facebook", "web"],
        "tools": ["itinerary.plan", "catalog.search", "crm.update", "conversation.reply"],
        "goals": ["Capturar fechas e intereses", "Recomendar planes", "Preparar cotizacion o asesor humano"],
        "personality": {"tone": "inspirador, organizado y comercial", "risk_posture": "moderado"},
        "provider_policy": {"route": "vertical_ops", "preferred": "kimi", "fallback": "openrouter"},
        "memory_policy": {"short_term": True, "semantic": True, "customer_profile": True, "vertical_context": True},
        "approval_policy": {"requires_human_approval": True, "can_send_messages": True, "can_update_crm": True},
        "risk_level": "medium",
    },
    "hr_recruiting": {
        "agent_type": "hr_recruiting",
        "name": "Recruiting Agent",
        "category": "vertical_hr",
        "headline": "Precalificacion de candidatos y coordinacion.",
        "description": "Recolecta informacion de candidatos, coordina pasos y evita decisiones automaticas de contratacion.",
        "channels": ["whatsapp", "facebook", "web"],
        "tools": ["recruiting.qualify", "conversation.reply", "crm.update", "reports.create"],
        "goals": ["Precalificar perfil", "Coordinar entrevista", "Mantener trazabilidad y evitar sesgos"],
        "personality": {"tone": "profesional, claro y justo", "risk_posture": "conservador"},
        "provider_policy": {"route": "classification", "preferred": "mistral", "fallback": "openrouter"},
        "memory_policy": {"short_term": True, "semantic": True, "vertical_context": True},
        "approval_policy": {"requires_human_approval": True, "can_send_messages": False, "can_update_crm": True},
        "risk_level": "high",
    },
    "multi_location_ops": {
        "agent_type": "multi_location_ops",
        "name": "Multi-location Operations Agent",
        "category": "vertical_operations",
        "headline": "Comparacion de sedes, sucursales y equipos.",
        "description": "Analiza rendimiento por sede, canal o equipo y recomienda mejoras operacionales.",
        "channels": ["global"],
        "tools": ["locations.compare", "analytics.read", "reports.create", "advisor.actions"],
        "goals": ["Detectar sedes con bajo rendimiento", "Comparar conversion por ubicacion", "Priorizar mejoras operativas"],
        "personality": {"tone": "ejecutivo, analitico y accionable", "risk_posture": "moderado"},
        "provider_policy": {"route": "analysis", "preferred": "kimi", "fallback": "openrouter"},
        "memory_policy": {"short_term": False, "semantic": True, "business_summary": True, "vertical_context": True},
        "approval_policy": {"requires_human_approval": True, "can_execute_safe_actions": True},
        "risk_level": "medium",
    },
}


def _clean(value: Any, limit: int = 500) -> str:
    return str(value or "").strip()[:limit]


def _json(value: Any) -> str:
    return json.dumps(_jsonable(value if value is not None else {}), ensure_ascii=False, default=str)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return value


def _uuid() -> str:
    return str(uuid.uuid4())


def _json_value(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback
    return value


def _normalize_agent_type(value: str) -> str:
    clean = _clean(value, 80).lower().replace("-", "_").replace(" ", "_")
    if clean not in AGENT_TEMPLATES:
        raise HTTPException(status_code=400, detail={"code": "unknown_agent_type", "agent_type": clean})
    return clean


def _normalize_status(value: str) -> str:
    clean = _clean(value, 40).lower()
    if clean not in EDITABLE_STATUSES:
        raise HTTPException(status_code=400, detail={"code": "invalid_agent_status", "status": clean})
    return clean


def _ensure_tables(conn: Connection) -> None:
    try:
        with conn.begin_nested():
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
    except Exception:
        # Some managed/shared Postgres roles cannot create extensions. The
        # service supplies UUIDs explicitly on inserts, so existing installs can
        # still operate even when pgcrypto cannot be enabled by this DB user.
        pass
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ai_agent_plan_limits (
                plan_code TEXT PRIMARY KEY,
                max_ai_agents INTEGER NOT NULL DEFAULT 1,
                max_active_ai_agents INTEGER NOT NULL DEFAULT 1,
                allowed_agent_types_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                builder_enabled BOOLEAN NOT NULL DEFAULT TRUE,
                notes TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(
        text(
            """
            ALTER TABLE saas_ai_agent_plan_limits
              ADD COLUMN IF NOT EXISTS max_ai_agents INTEGER NOT NULL DEFAULT 1,
              ADD COLUMN IF NOT EXISTS max_active_ai_agents INTEGER NOT NULL DEFAULT 1,
              ADD COLUMN IF NOT EXISTS allowed_agent_types_json JSONB NOT NULL DEFAULT '[]'::jsonb,
              ADD COLUMN IF NOT EXISTS builder_enabled BOOLEAN NOT NULL DEFAULT TRUE,
              ADD COLUMN IF NOT EXISTS notes TEXT NOT NULL DEFAULT '',
              ADD COLUMN IF NOT EXISTS created_at TIMESTAMP NOT NULL DEFAULT NOW(),
              ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ai_agents (
                id UUID PRIMARY KEY,
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                agent_type TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'draft',
                provider_policy_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                personality_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                goals_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                rules_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                channels_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                tools_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                memory_policy_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                approval_policy_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                metrics_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(
        text(
            """
            ALTER TABLE saas_ai_agents
              ADD COLUMN IF NOT EXISTS tenant_id UUID NULL,
              ADD COLUMN IF NOT EXISTS agent_type TEXT NOT NULL DEFAULT 'advisor',
              ADD COLUMN IF NOT EXISTS name TEXT NOT NULL DEFAULT '',
              ADD COLUMN IF NOT EXISTS description TEXT NOT NULL DEFAULT '',
              ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'draft',
              ADD COLUMN IF NOT EXISTS provider_policy_json JSONB NOT NULL DEFAULT '{}'::jsonb,
              ADD COLUMN IF NOT EXISTS personality_json JSONB NOT NULL DEFAULT '{}'::jsonb,
              ADD COLUMN IF NOT EXISTS goals_json JSONB NOT NULL DEFAULT '[]'::jsonb,
              ADD COLUMN IF NOT EXISTS rules_json JSONB NOT NULL DEFAULT '[]'::jsonb,
              ADD COLUMN IF NOT EXISTS channels_json JSONB NOT NULL DEFAULT '[]'::jsonb,
              ADD COLUMN IF NOT EXISTS tools_json JSONB NOT NULL DEFAULT '[]'::jsonb,
              ADD COLUMN IF NOT EXISTS memory_policy_json JSONB NOT NULL DEFAULT '{}'::jsonb,
              ADD COLUMN IF NOT EXISTS approval_policy_json JSONB NOT NULL DEFAULT '{}'::jsonb,
              ADD COLUMN IF NOT EXISTS metrics_json JSONB NOT NULL DEFAULT '{}'::jsonb,
              ADD COLUMN IF NOT EXISTS created_by_user_id UUID NULL,
              ADD COLUMN IF NOT EXISTS created_at TIMESTAMP NOT NULL DEFAULT NOW(),
              ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            """
        )
    )
    try:
        with conn.begin_nested():
            conn.execute(
                text(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS ux_saas_ai_agents_tenant_type_lower_name
                    ON saas_ai_agents (tenant_id, agent_type, lower(name))
                    WHERE status <> 'archived'
                    """
                )
            )
    except Exception:
        # Duplicate legacy rows should not block the agent registry from loading.
        pass
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_saas_ai_agents_tenant_status
            ON saas_ai_agents (tenant_id, status, updated_at DESC)
            """
        )
    )
    conn.execute(
        text(
            """
            ALTER TABLE saas_ai_agent_events
              ADD COLUMN IF NOT EXISTS tenant_id UUID NULL,
              ADD COLUMN IF NOT EXISTS agent_id UUID NULL,
              ADD COLUMN IF NOT EXISTS actor_user_id UUID NULL,
              ADD COLUMN IF NOT EXISTS event_type TEXT NOT NULL DEFAULT 'agent.event',
              ADD COLUMN IF NOT EXISTS summary TEXT NOT NULL DEFAULT '',
              ADD COLUMN IF NOT EXISTS details_json JSONB NOT NULL DEFAULT '{}'::jsonb,
              ADD COLUMN IF NOT EXISTS created_at TIMESTAMP NOT NULL DEFAULT NOW()
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ai_agent_events (
                id UUID PRIMARY KEY,
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                agent_id UUID NULL REFERENCES saas_ai_agents(id) ON DELETE CASCADE,
                actor_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
                event_type TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                details_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_saas_ai_agent_events_tenant_created
            ON saas_ai_agent_events (tenant_id, created_at DESC)
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ai_agent_memory_archives (
                id UUID PRIMARY KEY,
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                source_agent_id UUID NULL,
                source_agent_type TEXT NOT NULL DEFAULT '',
                source_agent_name TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '',
                snapshot_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                reusable_payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_saas_ai_agent_memory_archives_tenant_created
            ON saas_ai_agent_memory_archives (tenant_id, created_at DESC)
            """
        )
    )
    _seed_plan_limits(conn)


def _seed_plan_limits(conn: Connection) -> None:
    all_types = ALL_AGENT_TYPES
    rows = [
        ("demo", 2, 1, all_types, True, "Demo de 30 dias: explora AI Agents con ejecucion controlada."),
        ("starter", 1, 1, all_types, True, "Plan starter: un agente AI activo."),
        ("basic", 1, 1, all_types, True, "Plan basico: un agente AI activo."),
        ("growth", 3, 3, all_types, True, "Growth: equipo pequeno con varios agentes AI."),
        ("pro", 6, 6, all_types, True, "Pro: suite de agentes AI para operacion comercial."),
        ("enterprise", 50, 50, all_types, True, "Enterprise: limites negociables y gobierno avanzado."),
    ]
    for plan_code, max_agents, max_active, allowed, builder_enabled, notes in rows:
        conn.execute(
            text(
                """
                INSERT INTO saas_ai_agent_plan_limits (
                    plan_code, max_ai_agents, max_active_ai_agents, allowed_agent_types_json,
                    builder_enabled, notes, updated_at
                )
                VALUES (
                    :plan_code, :max_agents, :max_active, CAST(:allowed AS jsonb),
                    :builder_enabled, :notes, NOW()
                )
                ON CONFLICT (plan_code) DO NOTHING
                """
            ),
            {
                "plan_code": plan_code,
                "max_agents": max_agents,
                "max_active": max_active,
                "allowed": _json(allowed),
                "builder_enabled": builder_enabled,
                "notes": notes,
            },
        )


def _tenant_plan_code(conn: Connection, tenant_id: str) -> tuple[str, str]:
    row = conn.execute(
        text(
            """
            SELECT plan_code, status
            FROM saas_tenants
            WHERE id = CAST(:tenant_id AS uuid)
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="tenant_not_found")
    plan_code = _clean(row.get("plan_code"), 40).lower() or "starter"
    tenant_status = _clean(row.get("status"), 40).lower()
    if tenant_status == "trial":
        return "demo", tenant_status
    return plan_code, tenant_status


def plan_limits(conn: Connection, tenant_id: str) -> dict[str, Any]:
    _ensure_tables(conn)
    effective_plan_code, tenant_status = _tenant_plan_code(conn, tenant_id)
    row = conn.execute(
        text(
            """
            SELECT plan_code, max_ai_agents, max_active_ai_agents, allowed_agent_types_json,
                   builder_enabled, notes, updated_at::text
            FROM saas_ai_agent_plan_limits
            WHERE plan_code = :plan_code
            LIMIT 1
            """
        ),
        {"plan_code": effective_plan_code},
    ).mappings().first()
    if not row:
        row = conn.execute(
            text(
                """
                SELECT plan_code, max_ai_agents, max_active_ai_agents, allowed_agent_types_json,
                       builder_enabled, notes, updated_at::text
                FROM saas_ai_agent_plan_limits
                WHERE plan_code = 'starter'
                LIMIT 1
                """
            )
        ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="ai_agent_plan_limits_not_found")
    data = dict(row)
    allowed = _json_value(data.get("allowed_agent_types_json"), ALL_AGENT_TYPES)
    allowed_set = {str(item) for item in allowed}
    # Existing installations may still have the original 10-agent catalog in DB.
    # If a plan was allowed to use the full core catalog, keep it full after adding vertical agents.
    if allowed_set and set(CORE_AGENT_TYPES).issubset(allowed_set):
        allowed = ALL_AGENT_TYPES
    counts = agent_counts(conn, tenant_id)
    return {
        "tenant_id": tenant_id,
        "tenant_status": tenant_status,
        "plan_code": data.get("plan_code") or effective_plan_code,
        "max_ai_agents": int(data.get("max_ai_agents") or 0),
        "max_active_ai_agents": int(data.get("max_active_ai_agents") or 0),
        "allowed_agent_types": [str(item) for item in allowed if str(item) in AGENT_TEMPLATES],
        "builder_enabled": bool(data.get("builder_enabled")),
        "notes": data.get("notes") or "",
        "usage": counts,
        "remaining": {
            "total": max(0, int(data.get("max_ai_agents") or 0) - counts["total"]),
            "active": max(0, int(data.get("max_active_ai_agents") or 0) - counts["active"]),
        },
        "updated_at": str(data.get("updated_at") or ""),
    }


def agent_counts(conn: Connection, tenant_id: str) -> dict[str, int]:
    _ensure_tables(conn)
    row = conn.execute(
        text(
            """
            SELECT
                COUNT(*) FILTER (WHERE status <> 'archived')::int AS total,
                COUNT(*) FILTER (WHERE status = 'active')::int AS active,
                COUNT(*) FILTER (WHERE status = 'paused')::int AS paused,
                COUNT(*) FILTER (WHERE status = 'draft')::int AS draft
            FROM saas_ai_agents
            WHERE tenant_id = CAST(:tenant_id AS uuid)
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().first()
    data = dict(row or {})
    return {key: int(data.get(key) or 0) for key in ("total", "active", "paused", "draft")}


def list_templates() -> list[dict[str, Any]]:
    return [dict(template) for template in AGENT_TEMPLATES.values()]


def builder_catalog() -> dict[str, Any]:
    return {
        "channels": CHANNEL_CATALOG,
        "tools": TOOL_CATALOG,
        "provider_routes": PROVIDER_ROUTE_CATALOG,
        "providers": AI_PROVIDER_CATALOG,
        "memory_flags": MEMORY_FLAG_CATALOG,
        "approval_flags": APPROVAL_FLAG_CATALOG,
        "action_draft_presets": ACTION_DRAFT_PRESETS,
    }


def runtime_agent_for_conversation(conn: Connection, tenant_id: str, channel: str) -> dict[str, Any] | None:
    _ensure_tables(conn)
    clean_channel = _clean(channel, 40).lower() or "whatsapp"
    rows = conn.execute(
        text(
            """
            SELECT id::text, tenant_id::text, agent_type, name, description, status,
                   provider_policy_json, personality_json, goals_json, rules_json, channels_json,
                   tools_json, memory_policy_json, approval_policy_json, metrics_json,
                   created_by_user_id::text, created_at::text, updated_at::text
            FROM saas_ai_agents
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND status = 'active'
              AND agent_type IN ('sales', 'support')
            ORDER BY
              CASE agent_type WHEN 'sales' THEN 1 WHEN 'support' THEN 2 ELSE 9 END,
              updated_at DESC
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().all()
    for row in rows:
        item = _agent_row_to_dict(dict(row))
        channels = {str(value or "").strip().lower() for value in _json_value(item.get("channels_json"), [])}
        if clean_channel in channels or "global" in channels:
            return item
    return None


def record_agent_runtime_event(
    conn: Connection,
    *,
    tenant_id: str,
    agent_id: str,
    event_type: str,
    summary: str,
    details: dict[str, Any] | None = None,
) -> None:
    _audit(
        conn,
        tenant_id=tenant_id,
        agent_id=agent_id,
        actor_user_id=None,
        event_type=event_type,
        summary=summary,
        details=details or {},
    )


def _runtime_events(conn: Connection, tenant_id: str, agent_id: str, limit: int = 12) -> list[dict[str, Any]]:
    _ensure_tables(conn)
    rows = conn.execute(
        text(
            """
            SELECT id::text, tenant_id::text, agent_id::text, actor_user_id::text,
                   event_type, summary, details_json, created_at::text
            FROM saas_ai_agent_events
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND agent_id = CAST(:agent_id AS uuid)
              AND event_type LIKE 'agent.runtime_%'
            ORDER BY created_at DESC
            LIMIT :limit
            """
        ),
        {"tenant_id": tenant_id, "agent_id": agent_id, "limit": max(1, min(int(limit or 12), 100))},
    ).mappings().all()
    return [
        {
            **dict(row),
            "details_json": _json_value(row.get("details_json"), {}),
        }
        for row in rows
    ]


def _runtime_runs(conn: Connection, tenant_id: str, agent_id: str, limit: int = 12) -> list[dict[str, Any]]:
    ensure_ai_gateway_tables(conn)
    rows = conn.execute(
        text(
            """
            SELECT id::text, COALESCE(conversation_id::text, '') AS conversation_id,
                   agent_type, task_type, route_code, provider_code, model, status,
                   input_tokens, output_tokens, total_tokens, latency_ms, fallback_used,
                   error_code, error_message, metadata_json, created_at::text
            FROM saas_ai_runs
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND metadata_json->>'runtime_agent_id' = :agent_id
            ORDER BY created_at DESC
            LIMIT :limit
            """
        ),
        {"tenant_id": tenant_id, "agent_id": agent_id, "limit": max(1, min(int(limit or 12), 100))},
    ).mappings().all()
    return [
        {
            **dict(row),
            "metadata_json": _json_value(row.get("metadata_json"), {}),
        }
        for row in rows
    ]


def ensure_agent_action_tables(conn: Connection) -> None:
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_advisor_actions (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                created_by UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
                recommendation_id UUID NULL,
                insight_id UUID NULL,
                action_type TEXT NOT NULL DEFAULT 'advisor_action',
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                impact TEXT NOT NULL DEFAULT 'medium',
                risk_level TEXT NOT NULL DEFAULT 'medium',
                approval_required BOOLEAN NOT NULL DEFAULT TRUE,
                status TEXT NOT NULL DEFAULT 'draft',
                approved_by UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
                approved_at TIMESTAMP NULL,
                executed_at TIMESTAMP NULL,
                execution_result_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_saas_advisor_actions_tenant_status
            ON saas_advisor_actions (tenant_id, status, updated_at DESC)
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_saas_advisor_actions_agent
            ON saas_advisor_actions (tenant_id, ((payload_json->>'agent_id')), updated_at DESC)
            """
        )
    )


def _agent_action_out(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row.get("id") or ""),
        "action_type": str(row.get("action_type") or "advisor_action"),
        "title": str(row.get("title") or ""),
        "description": str(row.get("description") or ""),
        "payload_json": _json_value(row.get("payload_json"), {}),
        "impact": str(row.get("impact") or "medium"),
        "risk_level": str(row.get("risk_level") or "medium"),
        "approval_required": bool(row.get("approval_required", True)),
        "status": str(row.get("status") or "draft"),
        "approved_by": str(row.get("approved_by") or ""),
        "approved_at": str(row.get("approved_at") or ""),
        "executed_at": str(row.get("executed_at") or ""),
        "execution_result_json": _json_value(row.get("execution_result_json"), {}),
        "created_at": str(row.get("created_at") or ""),
        "updated_at": str(row.get("updated_at") or ""),
    }


def _action_preset_for(tool_code: str, action_type: str = "") -> dict[str, str]:
    clean_tool = _clean(tool_code, 120).lower()
    clean_action = _clean(action_type, 120).lower()
    for preset in ACTION_DRAFT_PRESETS:
        if clean_tool and preset["tool_code"] == clean_tool:
            return preset
        if clean_action and preset["action_type"] == clean_action:
            return preset
    return ACTION_DRAFT_PRESETS[0]


def _agent_action_metrics(conn: Connection, tenant_id: str, agent_id: str) -> dict[str, int]:
    ensure_agent_action_tables(conn)
    row = conn.execute(
        text(
            """
            SELECT
                COUNT(*) FILTER (WHERE status IN ('draft', 'pending_approval'))::int AS pending_action_drafts,
                COUNT(*) FILTER (WHERE status = 'approved')::int AS approved_action_drafts,
                COUNT(*) FILTER (WHERE status = 'executed')::int AS executed_action_drafts,
                COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '7 days')::int AS action_drafts_7d
            FROM saas_advisor_actions
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND payload_json->>'source' = 'ai_agent'
              AND payload_json->>'agent_id' = :agent_id
            """
        ),
        {"tenant_id": tenant_id, "agent_id": agent_id},
    ).mappings().first()
    return {key: int(value or 0) for key, value in dict(row or {}).items()}


def list_agent_action_drafts(conn: Connection, tenant_id: str, agent_id: str, limit: int = 20) -> list[dict[str, Any]]:
    ensure_agent_action_tables(conn)
    get_agent(conn, tenant_id, agent_id)
    rows = conn.execute(
        text(
            """
            SELECT id::text, action_type, title, description, payload_json, impact, risk_level,
                   approval_required, status, approved_by::text, approved_at::text, executed_at::text,
                   execution_result_json, created_at::text, updated_at::text
            FROM saas_advisor_actions
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND payload_json->>'source' = 'ai_agent'
              AND payload_json->>'agent_id' = :agent_id
            ORDER BY updated_at DESC
            LIMIT :limit
            """
        ),
        {"tenant_id": tenant_id, "agent_id": agent_id, "limit": max(1, min(int(limit or 20), 100))},
    ).mappings().all()
    return [_agent_action_out(dict(row)) for row in rows]


def create_agent_action_draft(
    conn: Connection,
    tenant_id: str,
    user_id: str,
    agent_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    ensure_agent_action_tables(conn)
    item = get_agent(conn, tenant_id, agent_id)
    preset = _action_preset_for(str(payload.get("tool_code") or ""), str(payload.get("action_type") or ""))
    tool_code = _clean(payload.get("tool_code") or preset["tool_code"], 120).lower()
    action_type = _clean(payload.get("action_type") or preset["action_type"], 120).lower()
    target_module = _clean(payload.get("target_module") or preset["target_module"], 120).lower()
    allowed_tools = {str(value or "").strip().lower() for value in _json_value(item.get("tools_json"), [])}
    if tool_code and allowed_tools and tool_code not in allowed_tools:
        raise HTTPException(
            status_code=403,
            detail={"code": "agent_tool_not_allowed", "tool_code": tool_code, "agent_id": agent_id},
        )
    impact = _clean(payload.get("impact"), 40).lower() or "medium"
    risk_level = _clean(payload.get("risk_level"), 40).lower() or "medium"
    if impact not in {"low", "medium", "high", "critical"}:
        impact = "medium"
    if risk_level not in {"low", "medium", "high", "critical"}:
        risk_level = "medium"
    title = _clean(payload.get("title"), 180) or preset["label"]
    description = _clean(payload.get("description"), 1200) or preset["description"]
    extra_payload = payload.get("payload_json") if isinstance(payload.get("payload_json"), dict) else {}
    action_payload = {
        **extra_payload,
        "source": "ai_agent",
        "agent_id": item["id"],
        "agent_type": item["agent_type"],
        "agent_name": item["name"],
        "tool_code": tool_code,
        "target_module": target_module,
        "requires_human_approval": True,
        "action": {
            "type": action_type,
            "module": target_module,
            "tool_code": tool_code,
            "title": title,
            "description": description,
            "created_by_agent": item["name"],
        },
    }
    row = conn.execute(
        text(
            """
            INSERT INTO saas_advisor_actions (
                tenant_id, created_by, action_type, title, description, payload_json,
                impact, risk_level, approval_required, status, execution_result_json, updated_at
            )
            VALUES (
                CAST(:tenant_id AS uuid),
                CASE WHEN :user_id = '' THEN NULL ELSE CAST(:user_id AS uuid) END,
                :action_type,
                :title,
                :description,
                CAST(:payload_json AS jsonb),
                :impact,
                :risk_level,
                TRUE,
                'pending_approval',
                CAST(:execution_result_json AS jsonb),
                NOW()
            )
            RETURNING id::text, action_type, title, description, payload_json, impact, risk_level,
                      approval_required, status, approved_by::text, approved_at::text, executed_at::text,
                      execution_result_json, created_at::text, updated_at::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "user_id": user_id or "",
            "action_type": action_type,
            "title": title,
            "description": description,
            "payload_json": _json(action_payload),
            "impact": impact,
            "risk_level": risk_level,
            "execution_result_json": _json(
                {
                    "state": "awaiting_human_approval",
                    "source": "ai_agent",
                    "agent_id": item["id"],
                    "tool_code": tool_code,
                    "approval_layer": "human_required",
                }
            ),
        },
    ).mappings().first()
    action = _agent_action_out(dict(row))
    _audit(
        conn,
        tenant_id=tenant_id,
        agent_id=item["id"],
        actor_user_id=user_id,
        event_type="agent.action_draft_created",
        summary=f"Borrador de accion preparado: {action['title']}",
        details={
            "action_id": action["id"],
            "action_type": action["action_type"],
            "tool_code": tool_code,
            "target_module": target_module,
            "impact": impact,
            "risk_level": risk_level,
        },
    )
    return action


def _runtime_health(item: dict[str, Any], metrics: dict[str, Any]) -> dict[str, Any]:
    issues: list[str] = []
    status = "healthy"
    agent_type = str(item.get("agent_type") or "")
    channels = {str(value or "").strip().lower() for value in _json_value(item.get("channels_json"), [])}
    tools = {str(value or "").strip().lower() for value in _json_value(item.get("tools_json"), [])}
    approval = _json_value(item.get("approval_policy_json"), {})
    if item.get("status") != "active":
        issues.append("agent_not_active")
    if agent_type in {"sales", "support"}:
        if not (channels & {"whatsapp", "instagram", "facebook", "web"}):
            issues.append("no_conversational_channel")
        if tools and "conversation.reply" not in tools:
            issues.append("conversation_reply_tool_missing")
        if isinstance(approval, dict) and approval.get("can_send_messages") is False:
            issues.append("send_permission_disabled")
    runs_7d = int(metrics.get("runs_7d") or 0)
    failed_7d = int(metrics.get("failed_runs_7d") or 0) + int(metrics.get("skipped_runs_7d") or 0)
    success_7d = int(metrics.get("success_runs_7d") or 0)
    if runs_7d and failed_7d and not success_7d:
        issues.append("runtime_failing")
        status = "critical"
    elif failed_7d:
        issues.append("runtime_has_errors")
        status = "warning"
    if issues and status == "healthy":
        status = "warning"
    if item.get("status") == "active" and agent_type in {"sales", "support"} and not runs_7d and not int(metrics.get("runtime_events_7d") or 0):
        status = "idle"
        issues.append("no_recent_runtime_activity")
    labels = {
        "healthy": "Operativo",
        "warning": "Revisar",
        "critical": "Critico",
        "idle": "Sin actividad",
    }
    return {"status": status, "label": labels.get(status, status), "issues": issues}


def _runtime_metrics(conn: Connection, item: dict[str, Any]) -> dict[str, Any]:
    tenant_id = str(item.get("tenant_id") or "")
    agent_id = str(item.get("id") or "")
    if not tenant_id or not agent_id:
        return {}
    ensure_ai_gateway_tables(conn)
    event_row = conn.execute(
        text(
            """
            SELECT
                COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '7 days')::int AS runtime_events_7d,
                COUNT(*) FILTER (WHERE event_type = 'agent.runtime_generated' AND created_at >= NOW() - INTERVAL '7 days')::int AS generated_7d,
                COUNT(*) FILTER (WHERE event_type = 'agent.runtime_completed' AND created_at >= NOW() - INTERVAL '7 days')::int AS completed_7d,
                COUNT(*) FILTER (WHERE event_type = 'agent.runtime_failed' AND created_at >= NOW() - INTERVAL '7 days')::int AS failed_events_7d,
                COUNT(*) FILTER (WHERE event_type = 'agent.runtime_skipped' AND created_at >= NOW() - INTERVAL '7 days')::int AS skipped_events_7d,
                COUNT(*) FILTER (WHERE event_type = 'agent.runtime_tested' AND created_at >= NOW() - INTERVAL '7 days')::int AS tests_7d,
                COALESCE(MAX(created_at)::text, '') AS last_runtime_event_at
            FROM saas_ai_agent_events
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND agent_id = CAST(:agent_id AS uuid)
              AND event_type LIKE 'agent.runtime_%'
            """
        ),
        {"tenant_id": tenant_id, "agent_id": agent_id},
    ).mappings().first()
    run_row = conn.execute(
        text(
            """
            SELECT
                COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '7 days')::int AS runs_7d,
                COUNT(*) FILTER (WHERE status = 'success' AND created_at >= NOW() - INTERVAL '7 days')::int AS success_runs_7d,
                COUNT(*) FILTER (WHERE status = 'failed' AND created_at >= NOW() - INTERVAL '7 days')::int AS failed_runs_7d,
                COUNT(*) FILTER (WHERE status = 'skipped' AND created_at >= NOW() - INTERVAL '7 days')::int AS skipped_runs_7d,
                COUNT(*) FILTER (WHERE fallback_used AND created_at >= NOW() - INTERVAL '7 days')::int AS fallback_runs_7d,
                COALESCE(SUM(total_tokens) FILTER (WHERE created_at >= NOW() - INTERVAL '7 days'), 0)::int AS tokens_7d,
                COALESCE(ROUND(AVG(latency_ms) FILTER (WHERE created_at >= NOW() - INTERVAL '7 days')), 0)::int AS avg_latency_ms_7d,
                COALESCE(MAX(created_at)::text, '') AS last_ai_run_at
            FROM saas_ai_runs
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND metadata_json->>'runtime_agent_id' = :agent_id
            """
        ),
        {"tenant_id": tenant_id, "agent_id": agent_id},
    ).mappings().first()
    last_run = conn.execute(
        text(
            """
            SELECT provider_code, model, status, error_code, error_message, created_at::text
            FROM saas_ai_runs
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND metadata_json->>'runtime_agent_id' = :agent_id
            ORDER BY created_at DESC
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id, "agent_id": agent_id},
    ).mappings().first()
    metrics = {key: (int(value or 0) if str(key).endswith("_7d") or key in {"tokens_7d", "avg_latency_ms_7d"} else value) for key, value in dict(event_row or {}).items()}
    for key, value in dict(run_row or {}).items():
        metrics[key] = int(value or 0) if str(key).endswith("_7d") or key in {"tokens_7d", "avg_latency_ms_7d"} else value
    metrics.update(_agent_action_metrics(conn, tenant_id, agent_id))
    if last_run:
        metrics.update(
            {
                "last_provider": str(last_run.get("provider_code") or ""),
                "last_model": str(last_run.get("model") or ""),
                "last_run_status": str(last_run.get("status") or ""),
                "last_error_code": str(last_run.get("error_code") or ""),
                "last_error_message": str(last_run.get("error_message") or ""),
            }
        )
    metrics["runtime_health"] = _runtime_health(item, metrics)
    return metrics


def agent_runtime_summary(conn: Connection, tenant_id: str, agent_id: str) -> dict[str, Any]:
    item = get_agent(conn, tenant_id, agent_id)
    metrics = _runtime_metrics(conn, item)
    return {
        "agent": {**item, "metrics_json": {**(item.get("metrics_json") or {}), **metrics}},
        "metrics": metrics,
        "runs": _runtime_runs(conn, tenant_id, agent_id, limit=12),
        "events": _runtime_events(conn, tenant_id, agent_id, limit=12),
        "actions": list_agent_action_drafts(conn, tenant_id, agent_id, limit=12),
        "health": metrics.get("runtime_health") or _runtime_health(item, metrics),
    }


def _template_payload(agent_type: str) -> dict[str, Any]:
    template = dict(AGENT_TEMPLATES[_normalize_agent_type(agent_type)])
    return {
        "agent_type": template["agent_type"],
        "name": template["name"],
        "description": template["description"],
        "status": "draft",
        "provider_policy_json": template.get("provider_policy", {}),
        "personality_json": template.get("personality", {}),
        "goals_json": template.get("goals", []),
        "rules_json": [],
        "channels_json": template.get("channels", []),
        "tools_json": template.get("tools", []),
        "memory_policy_json": template.get("memory_policy", {}),
        "approval_policy_json": template.get("approval_policy", {}),
        "metrics_json": {"risk_level": template.get("risk_level", "medium"), "category": template.get("category", "")},
    }


def _agent_row_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    template = AGENT_TEMPLATES.get(str(row.get("agent_type") or ""), {})
    return {
        "id": str(row.get("id") or ""),
        "tenant_id": str(row.get("tenant_id") or ""),
        "agent_type": str(row.get("agent_type") or ""),
        "name": str(row.get("name") or ""),
        "description": str(row.get("description") or ""),
        "status": str(row.get("status") or "draft"),
        "category": str(template.get("category") or _json_value(row.get("metrics_json"), {}).get("category") or ""),
        "headline": str(template.get("headline") or ""),
        "provider_policy_json": _json_value(row.get("provider_policy_json"), {}),
        "personality_json": _json_value(row.get("personality_json"), {}),
        "goals_json": _json_value(row.get("goals_json"), []),
        "rules_json": _json_value(row.get("rules_json"), []),
        "channels_json": _json_value(row.get("channels_json"), []),
        "tools_json": _json_value(row.get("tools_json"), []),
        "memory_policy_json": _json_value(row.get("memory_policy_json"), {}),
        "approval_policy_json": _json_value(row.get("approval_policy_json"), {}),
        "metrics_json": _json_value(row.get("metrics_json"), {}),
        "created_by_user_id": str(row.get("created_by_user_id") or ""),
        "created_at": str(row.get("created_at") or ""),
        "updated_at": str(row.get("updated_at") or ""),
    }


def _audit(
    conn: Connection,
    *,
    tenant_id: str,
    agent_id: str | None,
    actor_user_id: str | None,
    event_type: str,
    summary: str,
    details: dict[str, Any] | None = None,
) -> None:
    _ensure_tables(conn)
    conn.execute(
        text(
            """
            INSERT INTO saas_ai_agent_events (
                id, tenant_id, agent_id, actor_user_id, event_type, summary, details_json
            )
            VALUES (
                CAST(:id AS uuid),
                CAST(:tenant_id AS uuid),
                CASE WHEN :agent_id = '' THEN NULL ELSE CAST(:agent_id AS uuid) END,
                CASE WHEN :actor_user_id = '' THEN NULL ELSE CAST(:actor_user_id AS uuid) END,
                :event_type,
                :summary,
                CAST(:details AS jsonb)
            )
            """
        ),
        {
            "id": _uuid(),
            "tenant_id": tenant_id,
            "agent_id": agent_id or "",
            "actor_user_id": actor_user_id or "",
            "event_type": _clean(event_type, 80) or "agent.event",
            "summary": _clean(summary, 500),
            "details": _json(details or {}),
        },
    )


def ensure_default_advisor_agent(conn: Connection, tenant_id: str, user_id: str | None = None) -> dict[str, Any] | None:
    _ensure_tables(conn)
    row = conn.execute(
        text(
            """
            SELECT id::text, tenant_id::text, agent_type, name, description, status,
                   provider_policy_json, personality_json, goals_json, rules_json, channels_json,
                   tools_json, memory_policy_json, approval_policy_json, metrics_json,
                   created_by_user_id::text, created_at::text, updated_at::text
            FROM saas_ai_agents
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND agent_type = 'advisor'
              AND status <> 'archived'
            ORDER BY created_at ASC
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().first()
    if row:
        return _agent_row_to_dict(dict(row))

    limits = plan_limits(conn, tenant_id)
    if limits["usage"]["total"] >= int(limits["max_ai_agents"] or 0):
        return None
    payload = _template_payload("advisor")
    payload["status"] = "active" if limits["usage"]["active"] < int(limits["max_active_ai_agents"] or 0) else "draft"
    item = _insert_agent(conn, tenant_id=tenant_id, user_id=user_id or "", payload=payload, skip_quota=True)
    _audit(
        conn,
        tenant_id=tenant_id,
        agent_id=item["id"],
        actor_user_id=user_id,
        event_type="agent.seeded",
        summary="Advisor Agent creado automaticamente como agente base del tenant.",
        details={"agent_type": "advisor", "status": item["status"]},
    )
    return item


def _assert_create_allowed(conn: Connection, tenant_id: str, agent_type: str) -> dict[str, Any]:
    ensure_tenant_operational(conn, tenant_id)
    ensure_feature_enabled(conn, tenant_id, "ai")
    limits = plan_limits(conn, tenant_id)
    if not bool(limits.get("builder_enabled")):
        raise HTTPException(status_code=403, detail={"code": "ai_agent_builder_disabled"})
    if agent_type not in set(limits.get("allowed_agent_types") or []):
        raise HTTPException(status_code=403, detail={"code": "agent_type_not_allowed", "agent_type": agent_type})
    if limits["usage"]["total"] >= int(limits["max_ai_agents"] or 0):
        raise HTTPException(
            status_code=402,
            detail={
                "code": "ai_agent_limit_reached",
                "metric": "ai_agents",
                "limit": limits["max_ai_agents"],
                "used": limits["usage"]["total"],
            },
        )
    return limits


def _insert_agent(
    conn: Connection,
    *,
    tenant_id: str,
    user_id: str,
    payload: dict[str, Any],
    skip_quota: bool = False,
) -> dict[str, Any]:
    _ensure_tables(conn)
    agent_type = _normalize_agent_type(str(payload.get("agent_type") or ""))
    if not skip_quota:
        _assert_create_allowed(conn, tenant_id, agent_type)
    template = _template_payload(agent_type)
    merged = {**template, **payload}
    name = _clean(merged.get("name"), 160) or template["name"]
    description = _clean(merged.get("description"), 1200) or template["description"]
    status = _normalize_status(str(merged.get("status") or "draft"))
    if status == "active":
        _assert_activation_allowed(conn, tenant_id, "")
    try:
        row = conn.execute(
            text(
                """
                INSERT INTO saas_ai_agents (
                    id, tenant_id, agent_type, name, description, status, provider_policy_json,
                    personality_json, goals_json, rules_json, channels_json, tools_json,
                    memory_policy_json, approval_policy_json, metrics_json, created_by_user_id, updated_at
                )
                VALUES (
                    CAST(:id AS uuid), CAST(:tenant_id AS uuid), :agent_type, :name, :description, :status,
                    CAST(:provider_policy_json AS jsonb),
                    CAST(:personality_json AS jsonb),
                    CAST(:goals_json AS jsonb),
                    CAST(:rules_json AS jsonb),
                    CAST(:channels_json AS jsonb),
                    CAST(:tools_json AS jsonb),
                    CAST(:memory_policy_json AS jsonb),
                    CAST(:approval_policy_json AS jsonb),
                    CAST(:metrics_json AS jsonb),
                    CASE WHEN :user_id = '' THEN NULL ELSE CAST(:user_id AS uuid) END,
                    NOW()
                )
                RETURNING id::text, tenant_id::text, agent_type, name, description, status,
                          provider_policy_json, personality_json, goals_json, rules_json, channels_json,
                          tools_json, memory_policy_json, approval_policy_json, metrics_json,
                          created_by_user_id::text, created_at::text, updated_at::text
                """
            ),
            {
                "id": _uuid(),
                "tenant_id": tenant_id,
                "agent_type": agent_type,
                "name": name,
                "description": description,
                "status": status,
                "provider_policy_json": _json(merged.get("provider_policy_json") or merged.get("provider_policy") or {}),
                "personality_json": _json(merged.get("personality_json") or merged.get("personality") or {}),
                "goals_json": _json(merged.get("goals_json") or merged.get("goals") or []),
                "rules_json": _json(merged.get("rules_json") or []),
                "channels_json": _json(merged.get("channels_json") or merged.get("channels") or []),
                "tools_json": _json(merged.get("tools_json") or merged.get("tools") or []),
                "memory_policy_json": _json(merged.get("memory_policy_json") or merged.get("memory_policy") or {}),
                "approval_policy_json": _json(merged.get("approval_policy_json") or merged.get("approval_policy") or {}),
                "metrics_json": _json(merged.get("metrics_json") or {}),
                "user_id": user_id or "",
            },
        ).mappings().first()
    except Exception as exc:
        if "ux_saas_ai_agents_tenant_type_lower_name" in str(exc) or "duplicate key" in str(exc).lower():
            raise HTTPException(status_code=409, detail={"code": "agent_already_exists", "agent_type": agent_type, "name": name})
        raise
    item = _agent_row_to_dict(dict(row))
    _audit(
        conn,
        tenant_id=tenant_id,
        agent_id=item["id"],
        actor_user_id=user_id,
        event_type="agent.created",
        summary=f"{item['name']} creado desde el registry AI Agents.",
        details={"agent_type": agent_type, "status": status},
    )
    return item


def create_agent(conn: Connection, tenant_id: str, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return _insert_agent(conn, tenant_id=tenant_id, user_id=user_id, payload=payload)


def create_from_template(conn: Connection, tenant_id: str, user_id: str, agent_type: str) -> dict[str, Any]:
    clean_type = _normalize_agent_type(agent_type)
    payload = _template_payload(clean_type)
    return _insert_agent(conn, tenant_id=tenant_id, user_id=user_id, payload=payload)


def list_agents(conn: Connection, tenant_id: str, *, include_archived: bool = False, seed_advisor: bool = True) -> list[dict[str, Any]]:
    _ensure_tables(conn)
    if seed_advisor:
        try:
            with conn.begin_nested():
                ensure_default_advisor_agent(conn, tenant_id)
        except Exception:
            # Listing the registry must remain available in demo/trial even if
            # an older database state blocks automatic Advisor seeding.
            pass
    where_archived = "" if include_archived else "AND status <> 'archived'"
    rows = conn.execute(
        text(
            f"""
            SELECT id::text, tenant_id::text, agent_type, name, description, status,
                   provider_policy_json, personality_json, goals_json, rules_json, channels_json,
                   tools_json, memory_policy_json, approval_policy_json, metrics_json,
                   created_by_user_id::text, created_at::text, updated_at::text
            FROM saas_ai_agents
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              {where_archived}
            ORDER BY
              CASE status WHEN 'active' THEN 1 WHEN 'paused' THEN 2 WHEN 'draft' THEN 3 ELSE 4 END,
              updated_at DESC
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().all()
    return [_hydrate_metrics(conn, _agent_row_to_dict(dict(row))) for row in rows]


def get_agent(conn: Connection, tenant_id: str, agent_id: str) -> dict[str, Any]:
    _ensure_tables(conn)
    row = conn.execute(
        text(
            """
            SELECT id::text, tenant_id::text, agent_type, name, description, status,
                   provider_policy_json, personality_json, goals_json, rules_json, channels_json,
                   tools_json, memory_policy_json, approval_policy_json, metrics_json,
                   created_by_user_id::text, created_at::text, updated_at::text
            FROM saas_ai_agents
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND id = CAST(:agent_id AS uuid)
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id, "agent_id": agent_id},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="agent_not_found")
    return _hydrate_metrics(conn, _agent_row_to_dict(dict(row)))


def _hydrate_metrics(conn: Connection, item: dict[str, Any]) -> dict[str, Any]:
    metrics = dict(item.get("metrics_json") or {})
    if item.get("agent_type") == "advisor":
        # /agents can be the first AI screen a demo tenant opens. Ensure the
        # Advisor metric tables exist so the registry never fails with 500.
        try:
            from app_saas.advisor.service import ensure_advisor_tables

            with conn.begin_nested():
                ensure_advisor_tables(conn)
        except Exception:
            metrics.update({"metrics_warning": "advisor_tables_unavailable"})
            item["metrics_json"] = metrics
            return item
        try:
            with conn.begin_nested():
                row = conn.execute(
                    text(
                        """
                        SELECT
                            (SELECT COUNT(*)::int FROM saas_advisor_actions WHERE tenant_id = CAST(:tenant_id AS uuid) AND status IN ('draft','pending_approval','approved')) AS pending_actions,
                            (SELECT COUNT(*)::int FROM saas_advisor_messages WHERE tenant_id = CAST(:tenant_id AS uuid) AND role = 'assistant' AND created_at >= NOW() - INTERVAL '7 days') AS assistant_messages_7d,
                            (SELECT COUNT(*)::int FROM saas_ai_insights WHERE tenant_id = CAST(:tenant_id AS uuid) AND status = 'open') AS open_insights
                        """
                    ),
                    {"tenant_id": item["tenant_id"]},
                ).mappings().first()
            if row:
                metrics.update({key: int(row[key] or 0) for key in row.keys()})
        except Exception:
            metrics.update({"metrics_warning": "advisor_metrics_unavailable"})
    item["metrics_json"] = metrics
    return item


def _assert_activation_allowed(conn: Connection, tenant_id: str, agent_id: str) -> dict[str, Any]:
    limits = plan_limits(conn, tenant_id)
    exclude_clause = "AND id <> CAST(:agent_id AS uuid)" if agent_id else ""
    active_count = int(
        conn.execute(
            text(
                f"""
                SELECT COUNT(*)::int
                FROM saas_ai_agents
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND status = 'active'
                  {exclude_clause}
                """
            ),
            {"tenant_id": tenant_id, "agent_id": agent_id or ""},
        ).scalar()
        or 0
    )
    if active_count >= int(limits["max_active_ai_agents"] or 0):
        raise HTTPException(
            status_code=402,
            detail={
                "code": "active_ai_agent_limit_reached",
                "metric": "active_ai_agents",
                "limit": limits["max_active_ai_agents"],
                "used": active_count,
            },
        )
    return limits


def update_agent(conn: Connection, tenant_id: str, user_id: str, agent_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    _ensure_tables(conn)
    current = get_agent(conn, tenant_id, agent_id)
    assignments: list[str] = []
    params: dict[str, Any] = {"tenant_id": tenant_id, "agent_id": agent_id}
    scalar_fields = {"name": 160, "description": 1200}
    for field, limit in scalar_fields.items():
        if field in payload and payload[field] is not None:
            params[field] = _clean(payload[field], limit)
            assignments.append(f"{field} = :{field}")
    if "status" in payload and payload["status"] is not None:
        status = _normalize_status(str(payload["status"]))
        if status == "active" and current["status"] != "active":
            _assert_activation_allowed(conn, tenant_id, agent_id)
        params["status"] = status
        assignments.append("status = :status")
    json_fields = [
        "provider_policy_json",
        "personality_json",
        "goals_json",
        "rules_json",
        "channels_json",
        "tools_json",
        "memory_policy_json",
        "approval_policy_json",
    ]
    for field in json_fields:
        if field in payload and payload[field] is not None:
            params[field] = _json(payload[field])
            assignments.append(f"{field} = CAST(:{field} AS jsonb)")
    if not assignments:
        return current
    sql = f"""
        UPDATE saas_ai_agents
        SET {", ".join(assignments)}, updated_at = NOW()
        WHERE tenant_id = CAST(:tenant_id AS uuid)
          AND id = CAST(:agent_id AS uuid)
        RETURNING id::text, tenant_id::text, agent_type, name, description, status,
                  provider_policy_json, personality_json, goals_json, rules_json, channels_json,
                  tools_json, memory_policy_json, approval_policy_json, metrics_json,
                  created_by_user_id::text, created_at::text, updated_at::text
    """
    row = conn.execute(text(sql), params).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="agent_not_found")
    item = _hydrate_metrics(conn, _agent_row_to_dict(dict(row)))
    _audit(
        conn,
        tenant_id=tenant_id,
        agent_id=agent_id,
        actor_user_id=user_id,
        event_type="agent.updated",
        summary=f"{item['name']} actualizado.",
        details={"fields": list(payload.keys())},
    )
    return item


def set_agent_status(conn: Connection, tenant_id: str, user_id: str, agent_id: str, status: str) -> dict[str, Any]:
    clean_status = _normalize_status(status)
    if clean_status == "active":
        _assert_activation_allowed(conn, tenant_id, agent_id)
    return update_agent(conn, tenant_id, user_id, agent_id, {"status": clean_status})


def _agent_archive_payload(agent: dict[str, Any]) -> dict[str, Any]:
    return {
        "agent_type": agent.get("agent_type") or "advisor",
        "name": f"{agent.get('name') or 'Agente'} restaurado"[:160],
        "description": agent.get("description") or "",
        "status": "draft",
        "provider_policy_json": agent.get("provider_policy_json") or {},
        "personality_json": agent.get("personality_json") or {},
        "goals_json": agent.get("goals_json") or [],
        "rules_json": agent.get("rules_json") or [],
        "channels_json": agent.get("channels_json") or [],
        "tools_json": agent.get("tools_json") or [],
        "memory_policy_json": agent.get("memory_policy_json") or {},
        "approval_policy_json": agent.get("approval_policy_json") or {},
        "metrics_json": {
            "restored_from_memory": True,
            "source_agent_type": agent.get("agent_type") or "",
            "category": agent.get("category") or "",
        },
    }


def create_agent_memory_archive(
    conn: Connection,
    tenant_id: str,
    user_id: str,
    agent_id: str,
    *,
    title: str = "",
    notes: str = "",
) -> dict[str, Any]:
    _ensure_tables(conn)
    agent = get_agent(conn, tenant_id, agent_id)
    if agent.get("agent_type") == "advisor":
        raise HTTPException(status_code=400, detail={"code": "advisor_memory_archive_blocked"})
    recent_events = list_agent_events(conn, tenant_id, agent_id, limit=20)
    archive_title = _clean(title, 180) or f"Memoria de {agent['name']}"
    snapshot = {
        "agent": agent,
        "recent_events": recent_events,
        "memory_policy": agent.get("memory_policy_json") or {},
        "goals": agent.get("goals_json") or [],
        "rules": agent.get("rules_json") or [],
    }
    reusable_payload = _agent_archive_payload(agent)
    row = conn.execute(
        text(
            """
            INSERT INTO saas_ai_agent_memory_archives (
                id, tenant_id, source_agent_id, source_agent_type, source_agent_name,
                title, notes, snapshot_json, reusable_payload_json, created_by_user_id
            )
            VALUES (
                CAST(:id AS uuid), CAST(:tenant_id AS uuid), CAST(:agent_id AS uuid),
                :agent_type, :agent_name, :title, :notes,
                CAST(:snapshot AS jsonb), CAST(:reusable_payload AS jsonb),
                CASE WHEN :user_id = '' THEN NULL ELSE CAST(:user_id AS uuid) END
            )
            RETURNING id::text, tenant_id::text, source_agent_id::text, source_agent_type,
                      source_agent_name, title, notes, snapshot_json, reusable_payload_json,
                      created_by_user_id::text, created_at::text
            """
        ),
        {
            "id": _uuid(),
            "tenant_id": tenant_id,
            "agent_id": agent_id,
            "agent_type": agent["agent_type"],
            "agent_name": agent["name"],
            "title": archive_title,
            "notes": _clean(notes, 1200),
            "snapshot": _json(snapshot),
            "reusable_payload": _json(reusable_payload),
            "user_id": user_id or "",
        },
    ).mappings().first()
    memory = _memory_archive_row_to_dict(dict(row))
    _audit(
        conn,
        tenant_id=tenant_id,
        agent_id=agent_id,
        actor_user_id=user_id,
        event_type="agent.memory_archived",
        summary=f"Memoria guardada antes de eliminar {agent['name']}.",
        details={"memory_archive_id": memory["id"], "agent_type": agent["agent_type"]},
    )
    return memory


def archive_agent_with_memory(
    conn: Connection,
    tenant_id: str,
    user_id: str,
    agent_id: str,
    *,
    preserve_memory: bool = False,
    memory_title: str = "",
    notes: str = "",
) -> dict[str, Any]:
    current = get_agent(conn, tenant_id, agent_id)
    if current.get("agent_type") == "advisor":
        raise HTTPException(status_code=400, detail={"code": "advisor_archive_blocked"})
    memory = None
    if preserve_memory:
        memory = create_agent_memory_archive(conn, tenant_id, user_id, agent_id, title=memory_title, notes=notes)
    agent = set_agent_status(conn, tenant_id, user_id, agent_id, "archived")
    return {"agent": agent, "memory": memory}


def _memory_archive_row_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    snapshot = _json_value(row.get("snapshot_json"), {})
    reusable_payload = _json_value(row.get("reusable_payload_json"), {})
    return {
        "id": str(row.get("id") or ""),
        "tenant_id": str(row.get("tenant_id") or ""),
        "source_agent_id": str(row.get("source_agent_id") or ""),
        "source_agent_type": str(row.get("source_agent_type") or ""),
        "source_agent_name": str(row.get("source_agent_name") or ""),
        "title": str(row.get("title") or ""),
        "notes": str(row.get("notes") or ""),
        "snapshot_json": snapshot,
        "reusable_payload_json": reusable_payload,
        "created_by_user_id": str(row.get("created_by_user_id") or ""),
        "created_at": str(row.get("created_at") or ""),
        "summary": {
            "goals": _json_value(snapshot.get("goals"), [])[:5] if isinstance(snapshot, dict) else [],
            "tools": _json_value(reusable_payload.get("tools_json"), [])[:8] if isinstance(reusable_payload, dict) else [],
            "channels": _json_value(reusable_payload.get("channels_json"), [])[:5] if isinstance(reusable_payload, dict) else [],
        },
    }


def list_agent_memory_archives(conn: Connection, tenant_id: str, limit: int = 100) -> list[dict[str, Any]]:
    _ensure_tables(conn)
    rows = conn.execute(
        text(
            """
            SELECT id::text, tenant_id::text, source_agent_id::text, source_agent_type,
                   source_agent_name, title, notes, snapshot_json, reusable_payload_json,
                   created_by_user_id::text, created_at::text
            FROM saas_ai_agent_memory_archives
            WHERE tenant_id = CAST(:tenant_id AS uuid)
            ORDER BY created_at DESC
            LIMIT :limit
            """
        ),
        {"tenant_id": tenant_id, "limit": max(1, min(int(limit or 100), 200))},
    ).mappings().all()
    return [_memory_archive_row_to_dict(dict(row)) for row in rows]


def create_agent_from_memory_archive(
    conn: Connection,
    tenant_id: str,
    user_id: str,
    memory_id: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _ensure_tables(conn)
    row = conn.execute(
        text(
            """
            SELECT id::text, tenant_id::text, source_agent_type, source_agent_name,
                   title, notes, reusable_payload_json
            FROM saas_ai_agent_memory_archives
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND id = CAST(:memory_id AS uuid)
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id, "memory_id": memory_id},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="agent_memory_not_found")
    archive = dict(row)
    reusable_payload = _json_value(archive.get("reusable_payload_json"), {})
    if not isinstance(reusable_payload, dict):
        raise HTTPException(status_code=400, detail={"code": "agent_memory_payload_invalid"})
    data = dict(reusable_payload)
    overrides = payload or {}
    if _clean(overrides.get("name"), 160):
        data["name"] = _clean(overrides.get("name"), 160)
    if _clean(overrides.get("status"), 40):
        data["status"] = _normalize_status(str(overrides.get("status")))
    data["status"] = "draft" if data.get("status") == "archived" else data.get("status", "draft")
    item = _insert_agent(conn, tenant_id=tenant_id, user_id=user_id, payload=data)
    _audit(
        conn,
        tenant_id=tenant_id,
        agent_id=item["id"],
        actor_user_id=user_id,
        event_type="agent.memory_restored",
        summary=f"{item['name']} creado desde memoria guardada.",
        details={"memory_archive_id": memory_id, "source_agent_name": archive.get("source_agent_name") or ""},
    )
    return item


def list_agent_events(conn: Connection, tenant_id: str, agent_id: str | None = None, limit: int = 60) -> list[dict[str, Any]]:
    _ensure_tables(conn)
    where_agent = "AND agent_id = CAST(:agent_id AS uuid)" if agent_id else ""
    rows = conn.execute(
        text(
            f"""
            SELECT id::text, tenant_id::text, agent_id::text, actor_user_id::text,
                   event_type, summary, details_json, created_at::text
            FROM saas_ai_agent_events
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              {where_agent}
            ORDER BY created_at DESC
            LIMIT :limit
            """
        ),
        {"tenant_id": tenant_id, "agent_id": agent_id or "", "limit": max(1, min(int(limit or 60), 200))},
    ).mappings().all()
    return [
        {
            **dict(row),
            "details_json": _json_value(row.get("details_json"), {}),
        }
        for row in rows
    ]


def add_agent_event(
    conn: Connection,
    tenant_id: str,
    user_id: str,
    agent_id: str,
    *,
    event_type: str,
    summary: str,
    details: dict[str, Any] | None = None,
) -> None:
    get_agent(conn, tenant_id, agent_id)
    _audit(
        conn,
        tenant_id=tenant_id,
        agent_id=agent_id,
        actor_user_id=user_id,
        event_type=event_type,
        summary=summary,
        details=details or {},
    )
