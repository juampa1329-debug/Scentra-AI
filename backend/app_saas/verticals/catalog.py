from __future__ import annotations

from copy import deepcopy
from typing import Any

PACK_VERSION = 1

INDUSTRY_ALIASES = {
    "clinic": "health",
    "clinica": "health",
    "salud": "health",
    "retail": "retail",
    "tienda": "retail",
    "ecommerce": "ecommerce",
    "e_commerce": "ecommerce",
    "commerce": "ecommerce",
    "academy": "education",
    "academia": "education",
    "school": "education",
    "inmobiliaria": "real_estate",
    "realestate": "real_estate",
    "soporte": "support",
    "support": "support",
    "automotriz": "automotive",
    "automotive": "automotive",
    "financiero": "financial_services",
    "financial": "financial_services",
    "financial_services": "financial_services",
    "restaurant": "restaurant",
    "restaurante": "restaurant",
    "hotel": "hotel",
    "legal": "legal",
    "seguros": "insurance",
    "seguro": "insurance",
    "estetica": "beauty",
    "beauty": "beauty",
    "servicios": "services",
    "service": "services",
}


PIPELINES: dict[str, list[tuple[str, str, int, bool, bool]]] = {
    "general": [
        ("contactado", "Contactado", 10, False, False),
        ("interes", "Interes", 30, False, False),
        ("intencion_compra", "Intencion de compra", 55, False, False),
        ("pago_pendiente", "Pago pendiente", 75, False, False),
        ("pago_confirmado", "Pago confirmado", 100, True, False),
    ],
    "retail": [
        ("lead_nuevo", "Lead nuevo", 10, False, False),
        ("producto_identificado", "Producto identificado", 35, False, False),
        ("oferta_enviada", "Oferta enviada", 60, False, False),
        ("pago_pendiente", "Pago pendiente", 80, False, False),
        ("compra_confirmada", "Compra confirmada", 100, True, False),
    ],
    "ecommerce": [
        ("lead_nuevo", "Lead nuevo", 10, False, False),
        ("producto_interes", "Producto de interes", 30, False, False),
        ("carrito_pendiente", "Carrito pendiente", 55, False, False),
        ("pago_pendiente", "Pago pendiente", 80, False, False),
        ("compra_confirmada", "Compra confirmada", 100, True, False),
    ],
    "restaurant": [
        ("nuevo_lead", "Nuevo lead", 10, False, False),
        ("consulta_menu", "Consulta menu", 25, False, False),
        ("reserva_solicitada", "Reserva solicitada", 55, False, False),
        ("confirmacion_pendiente", "Confirmacion pendiente", 75, False, False),
        ("reserva_confirmada", "Reserva confirmada", 100, True, False),
    ],
    "hotel": [
        ("consulta_estadia", "Consulta estadia", 10, False, False),
        ("fechas_calificadas", "Fechas calificadas", 35, False, False),
        ("cotizacion_enviada", "Cotizacion enviada", 60, False, False),
        ("pago_pendiente", "Pago pendiente", 80, False, False),
        ("reserva_confirmada", "Reserva confirmada", 100, True, False),
    ],
    "real_estate": [
        ("lead_nuevo", "Lead nuevo", 10, False, False),
        ("requisitos_calificados", "Requisitos calificados", 35, False, False),
        ("propiedades_enviadas", "Propiedades enviadas", 55, False, False),
        ("visita_agendada", "Visita agendada", 75, False, False),
        ("negocio_cerrado", "Negocio cerrado", 100, True, False),
    ],
    "support": [
        ("ticket_nuevo", "Ticket nuevo", 10, False, False),
        ("prioridad_detectada", "Prioridad detectada", 35, False, False),
        ("en_revision", "En revision", 60, False, False),
        ("escalado", "Escalado", 80, False, False),
        ("resuelto", "Resuelto", 100, True, False),
    ],
    "automotive": [
        ("lead_nuevo", "Lead nuevo", 10, False, False),
        ("vehiculo_identificado", "Vehiculo identificado", 35, False, False),
        ("cotizacion_enviada", "Cotizacion enviada", 60, False, False),
        ("test_drive_agendado", "Test drive agendado", 80, False, False),
        ("venta_confirmada", "Venta confirmada", 100, True, False),
    ],
    "financial_services": [
        ("lead_nuevo", "Lead nuevo", 10, False, False),
        ("perfil_calificado", "Perfil calificado", 35, False, False),
        ("propuesta_enviada", "Propuesta enviada", 60, False, False),
        ("revision_humana", "Revision humana", 80, False, False),
        ("cliente_activado", "Cliente activado", 100, True, False),
    ],
    "health": [
        ("consulta_inicial", "Consulta inicial", 10, False, False),
        ("datos_recolectados", "Datos recolectados", 35, False, False),
        ("cita_sugerida", "Cita sugerida", 60, False, False),
        ("confirmacion_pendiente", "Confirmacion pendiente", 80, False, False),
        ("cita_confirmada", "Cita confirmada", 100, True, False),
    ],
    "education": [
        ("aspirante", "Aspirante", 10, False, False),
        ("programa_identificado", "Programa identificado", 35, False, False),
        ("requisitos_enviados", "Requisitos enviados", 60, False, False),
        ("asesoria_agendada", "Asesoria agendada", 80, False, False),
        ("matricula_confirmada", "Matricula confirmada", 100, True, False),
    ],
    "beauty": [
        ("consulta_servicio", "Consulta servicio", 10, False, False),
        ("preferencias_capturadas", "Preferencias capturadas", 35, False, False),
        ("cita_propuesta", "Cita propuesta", 60, False, False),
        ("recordatorio_pendiente", "Recordatorio pendiente", 80, False, False),
        ("cita_confirmada", "Cita confirmada", 100, True, False),
    ],
    "legal": [
        ("intake_inicial", "Intake inicial", 10, False, False),
        ("hechos_recolectados", "Hechos recolectados", 35, False, False),
        ("documentos_pendientes", "Documentos pendientes", 55, False, False),
        ("revision_humana", "Revision humana", 80, False, False),
        ("caso_aceptado", "Caso aceptado", 100, True, False),
    ],
    "insurance": [
        ("siniestro_nuevo", "Siniestro nuevo", 10, False, False),
        ("poliza_identificada", "Poliza identificada", 35, False, False),
        ("documentos_pendientes", "Documentos pendientes", 55, False, False),
        ("revision_humana", "Revision humana", 80, False, False),
        ("caso_radicado", "Caso radicado", 100, True, False),
    ],
    "services": [
        ("solicitud_nueva", "Solicitud nueva", 10, False, False),
        ("necesidad_calificada", "Necesidad calificada", 35, False, False),
        ("cotizacion_enviada", "Cotizacion enviada", 60, False, False),
        ("agenda_pendiente", "Agenda pendiente", 80, False, False),
        ("servicio_confirmado", "Servicio confirmado", 100, True, False),
    ],
}


def _field(key: str, label: str, field_type: str = "text", options: list[str] | None = None, order: int = 100) -> dict[str, Any]:
    return {
        "field_key": key,
        "label": label,
        "field_type": field_type,
        "options_json": options or [],
        "is_required": False,
        "display_order": order,
    }


def _template(name: str, body: str, category: str = "vertical_pack") -> dict[str, Any]:
    return {
        "name": name,
        "channel": "whatsapp",
        "category": category,
        "status": "draft",
        "body": body,
        "variables_json": ["customer_first_name"],
        "blocks_json": [],
        "params_json": {"source": "vertical_pack", "phase": "10"},
        "render_mode": "chat",
        "template_scope": "crm",
        "source": "vertical_pack",
    }


def _segment(name: str, description: str, filters: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "description": description, "filters_json": filters}


def _trigger(name: str, words: list[str], stage: str, tag: str, priority: int = 100) -> dict[str, Any]:
    return {
        "name": name,
        "channel": "whatsapp",
        "event_type": "message_in",
        "trigger_type": "message_flow",
        "flow_event": "received",
        "conditions_json": {"match": "any", "conditions": [{"type": "check_words", "words": words}]},
        "actions_json": {
            "actions": [
                {"type": "change_tag", "mode": "add", "tags": [tag]},
                {"type": "configure_conversation", "field": "crm_stage", "status": stage},
                {
                    "type": "notify_admins",
                    "message": "Lead vertical {{trigger_name}}: {{customer_name}} escribio {{incoming_text}}",
                },
            ]
        },
        "priority": priority,
        "cooldown_minutes": 180,
        "is_active": False,
        "assistant_enabled": False,
        "assistant_message_type": "auto",
        "block_ai": True,
        "stop_on_match": True,
        "only_when_no_takeover": True,
        "quiet_hours_json": {},
        "ab_test_json": {},
        "revision_note": "vertical_pack_phase10_inactive_draft",
    }


def _flow(name: str, description: str, entry_stage: str, steps: list[str]) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "channel": "whatsapp",
        "status": "draft",
        "entry_rules_json": {"crm_stage": entry_stage},
        "exit_rules_json": {"won_stage": True, "takeover": True},
        "steps_json": [
            {"delay_hours": 24 * (index + 1), "type": "manual_review", "message": message}
            for index, message in enumerate(steps)
        ],
        "quiet_hours_json": {},
        "ab_test_json": {},
    }


def _pack(
    code: str,
    label: str,
    category: str,
    description: str,
    agent_types: list[str],
    fields: list[dict[str, Any]],
    templates: list[dict[str, Any]],
    segments: list[dict[str, Any]],
    triggers: list[dict[str, Any]],
    flows: list[dict[str, Any]],
    kpis: list[str],
) -> dict[str, Any]:
    return {
        "code": code,
        "label": label,
        "category": category,
        "description": description,
        "pack_version": PACK_VERSION,
        "pipeline": [
            {
                "stage_key": stage_key,
                "label": stage_label,
                "probability": probability,
                "is_won": is_won,
                "is_lost": is_lost,
                "display_order": (index + 1) * 10,
            }
            for index, (stage_key, stage_label, probability, is_won, is_lost) in enumerate(PIPELINES.get(code, PIPELINES["general"]))
        ],
        "agent_types": agent_types,
        "custom_fields": fields,
        "labels": [
            {"name": label, "color": "#5eead4", "description": f"Pack vertical {label}", "category": "vertical"},
            {"name": "Seguimiento vertical", "color": "#60a5fa", "description": "Seguimiento generado por pack vertical", "category": "vertical"},
        ],
        "templates": templates,
        "segments": segments,
        "triggers": triggers,
        "flows": flows,
        "quiet_hours": {"channel": "all", "entity_type": "all", "enabled": False, "timezone": "America/Bogota", "start_time": "21:00", "end_time": "08:00", "days_json": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]},
        "kpis": kpis,
    }


INDUSTRY_PACKS: dict[str, dict[str, Any]] = {
    "general": _pack(
        "general",
        "General",
        "general",
        "Pack base para empresas sin vertical definida.",
        ["sales", "support", "crm_intelligence", "custom"],
        [_field("producto_interes", "Producto/servicio de interes", order=10), _field("proximo_paso", "Proximo paso", order=20)],
        [_template("Seguimiento general", "Hola {{customer_first_name}}, sigo pendiente para ayudarte con el siguiente paso.")],
        [_segment("Leads calientes", "Contactos con alta intencion comercial.", {"crm_stage": "intencion_compra"})],
        [_trigger("Detectar interes comercial", ["precio", "cotizacion", "comprar", "informacion"], "intencion_compra", "Interes compra", 100)],
        [_flow("Seguimiento comercial base", "Recordatorio operativo para oportunidades abiertas.", "intencion_compra", ["Revisar si el lead necesita cotizacion.", "Validar si el cliente ya decidio."])],
        ["leads_abiertos", "conversion_pipeline", "tareas_vencidas", "mensajes_30d"],
    ),
    "retail": _pack(
        "retail",
        "Retail",
        "commerce",
        "Ventas de tienda, recompra, promociones y atencion postventa.",
        ["sales", "retention", "campaign_strategist", "custom"],
        [_field("producto_interes", "Producto de interes", order=10), _field("ticket_estimado", "Ticket estimado", "number", order=20), _field("preferencia_canal", "Canal preferido", order=30)],
        [_template("Oferta retail", "Hola {{customer_first_name}}, te comparto disponibilidad y opciones para el producto que te interesa."), _template("Recompra retail", "Hola {{customer_first_name}}, tenemos novedades relacionadas con tu ultima compra.")],
        [_segment("Leads retail calientes", "Clientes con producto identificado.", {"crm_stage": "producto_identificado"}), _segment("Recompra potencial", "Clientes listos para seguimiento de recompra.", {"crm_stage": "oferta_enviada"})],
        [_trigger("Interes retail", ["precio", "disponible", "producto", "comprar", "tienda"], "producto_identificado", "Seguimiento vertical", 80)],
        [_flow("Recompra retail", "Secuencia draft para recompra o seguimiento comercial.", "oferta_enviada", ["Validar disponibilidad y margen.", "Revisar incentivo antes de enviar."])],
        ["conversion_rate", "ticket_promedio", "recompra", "tiempo_respuesta"],
    ),
    "ecommerce": _pack(
        "ecommerce",
        "Ecommerce",
        "commerce",
        "Carritos, conversion online, recompra y remarketing.",
        ["sales", "retention", "campaign_strategist", "custom"],
        [_field("producto_interes", "Producto de interes", order=10), _field("carrito_url", "URL o referencia de carrito", order=20), _field("objecion_compra", "Objecion de compra", order=30)],
        [_template("Recuperacion ecommerce", "Hola {{customer_first_name}}, puedo ayudarte a completar tu compra o resolver dudas del producto."), _template("Seguimiento carrito", "Hola {{customer_first_name}}, tu seleccion quedo pendiente. Te ayudo a finalizarla?")],
        [_segment("Carritos pendientes", "Leads con carrito o compra pendiente.", {"crm_stage": "carrito_pendiente"}), _segment("Compradores recurrentes", "Clientes con potencial de recompra.", {"crm_stage": "compra_confirmada"})],
        [_trigger("Carrito o compra", ["carrito", "checkout", "envio", "comprar", "pago"], "producto_interes", "Seguimiento vertical", 80)],
        [_flow("Recuperar carrito", "Secuencia draft para carritos pendientes.", "carrito_pendiente", ["Verificar producto y stock.", "Sugerir alternativa o incentivo aprobado."])],
        ["conversion_rate", "cart_recovery", "campaign_positive_rate", "repeat_purchase"],
    ),
    "restaurant": _pack(
        "restaurant",
        "Restaurantes",
        "hospitality",
        "Reservas, menu, pedidos y no-shows.",
        ["restaurant_reservations", "restaurant_menu", "reputation_manager", "custom"],
        [_field("fecha_reserva", "Fecha de reserva", "date", order=10), _field("personas", "Numero de personas", "number", order=20), _field("preferencia_mesa", "Preferencia de mesa", order=30)],
        [_template("Confirmacion de reserva", "Hola {{customer_first_name}}, tenemos tu solicitud de reserva. Confirmanos fecha, hora y numero de personas."), _template("Consulta menu", "Hola {{customer_first_name}}, puedo ayudarte con menu, horarios, reservas y recomendaciones.")],
        [_segment("Reservas pendientes", "Reservas que requieren confirmacion.", {"crm_stage": "confirmacion_pendiente"}), _segment("Consultas de menu", "Clientes interesados en menu o pedidos.", {"crm_stage": "consulta_menu"})],
        [_trigger("Reserva por palabra clave", ["reserva", "mesa", "reservar"], "reserva_solicitada", "Seguimiento vertical", 80), _trigger("Consulta de menu", ["menu", "carta", "plato", "domicilio"], "consulta_menu", "Seguimiento vertical", 90)],
        [_flow("No-show y confirmacion", "Secuencia draft para confirmar reservas antes de la visita.", "reserva_solicitada", ["Confirmar disponibilidad de mesa.", "Enviar recordatorio manual antes de la reserva."])],
        ["reservas_pendientes", "reservas_confirmadas", "consultas_menu", "no_show_risk"],
    ),
    "hotel": _pack(
        "hotel",
        "Hoteles",
        "hospitality",
        "Reservas, cotizaciones, concierge y upsell.",
        ["hotel_booking", "hotel_concierge", "tourism_itinerary", "custom"],
        [_field("fecha_checkin", "Fecha check-in", "date", order=10), _field("fecha_checkout", "Fecha check-out", "date", order=20), _field("huespedes", "Huespedes", "number", order=30)],
        [_template("Cotizacion hotel", "Hola {{customer_first_name}}, para cotizar tu estadia necesito fechas, numero de huespedes y tipo de habitacion."), _template("Concierge", "Hola {{customer_first_name}}, cuentame que necesitas durante tu estadia y lo coordinamos.")],
        [_segment("Cotizaciones abiertas", "Estadias con cotizacion pendiente.", {"crm_stage": "cotizacion_enviada"}), _segment("Pagos pendientes hotel", "Reservas con pago pendiente.", {"crm_stage": "pago_pendiente"})],
        [_trigger("Solicitud de estadia", ["habitacion", "reserva", "estadia", "hotel"], "consulta_estadia", "Seguimiento vertical", 80)],
        [_flow("Recuperar cotizacion hotel", "Seguimiento draft para estadias cotizadas.", "cotizacion_enviada", ["Validar fechas y tarifa vigente.", "Revisar si requiere upgrade o pago."])],
        ["cotizaciones_abiertas", "reservas_confirmadas", "ocupacion_leads", "upsell_pendiente"],
    ),
    "health": _pack(
        "health",
        "Clinicas y salud",
        "regulated",
        "Citas, intake administrativo y escalacion segura.",
        ["medical_appointment", "dental_booking", "appointment_scheduler", "custom"],
        [_field("motivo_cita", "Motivo administrativo de cita", order=10), _field("especialidad", "Especialidad", order=20), _field("fecha_preferida", "Fecha preferida", "date", order=30)],
        [_template("Solicitud de cita", "Hola {{customer_first_name}}, puedo ayudarte a coordinar una cita. Indica especialidad, fecha preferida y datos de contacto."), _template("Escalacion salud", "Hola {{customer_first_name}}, por seguridad un asesor humano revisara tu caso antes de continuar.")],
        [_segment("Citas por confirmar", "Pacientes con confirmacion pendiente.", {"crm_stage": "confirmacion_pendiente"}), _segment("Revision humana salud", "Casos que requieren revision humana.", {"crm_stage": "cita_sugerida"})],
        [_trigger("Cita medica", ["cita", "consulta", "doctor", "dolor", "valoracion"], "consulta_inicial", "Seguimiento vertical", 70)],
        [_flow("Confirmacion de cita", "Secuencia draft para confirmar citas sin diagnostico.", "cita_sugerida", ["Validar disponibilidad de agenda.", "Confirmar que no se entrega diagnostico automatico."])],
        ["citas_solicitadas", "citas_confirmadas", "casos_escalados", "tiempo_respuesta"],
    ),
    "education": _pack(
        "education",
        "Academias",
        "education",
        "Admisiones, programas, clases y seguimiento academico.",
        ["education_admissions", "teacher", "appointment_scheduler", "custom"],
        [_field("programa_interes", "Programa de interes", order=10), _field("nivel_educativo", "Nivel educativo", order=20), _field("fecha_inicio", "Fecha tentativa de inicio", "date", order=30)],
        [_template("Admisiones", "Hola {{customer_first_name}}, dime que programa te interesa y te comparto requisitos y siguiente paso."), _template("Clase de prueba", "Hola {{customer_first_name}}, puedo ayudarte a coordinar una clase de prueba o asesoria academica.")],
        [_segment("Aspirantes activos", "Leads con programa identificado.", {"crm_stage": "programa_identificado"}), _segment("Matricula pendiente", "Aspirantes cerca de matricula.", {"crm_stage": "asesoria_agendada"})],
        [_trigger("Interes en programa", ["curso", "clase", "programa", "matricula", "inscripcion"], "aspirante", "Seguimiento vertical", 80)],
        [_flow("Matricula y admision", "Secuencia draft para aspirantes activos.", "programa_identificado", ["Confirmar requisitos enviados.", "Agendar asesoria o clase de prueba."])],
        ["aspirantes", "asesorias_agendadas", "matriculas", "dudas_academicas"],
    ),
    "real_estate": _pack(
        "real_estate",
        "Inmobiliarias",
        "real_estate",
        "Calificacion inmobiliaria, propiedades y visitas.",
        ["real_estate_leads", "sales", "appointment_scheduler", "custom"],
        [_field("presupuesto", "Presupuesto", "number", order=10), _field("zona_interes", "Zona de interes", order=20), _field("tipo_inmueble", "Tipo de inmueble", "select", ["Casa", "Apartamento", "Local", "Oficina", "Lote"], 30)],
        [_template("Calificacion inmueble", "Hola {{customer_first_name}}, para ayudarte necesito zona, presupuesto, tipo de inmueble y fecha estimada de compra o arriendo."), _template("Agenda visita", "Hola {{customer_first_name}}, podemos coordinar una visita. Indicanos disponibilidad y propiedad de interes.")],
        [_segment("Visitas por agendar", "Leads con propiedades enviadas.", {"crm_stage": "propiedades_enviadas"}), _segment("Negocios calientes", "Leads con visita agendada.", {"crm_stage": "visita_agendada"})],
        [_trigger("Lead inmobiliario", ["casa", "apartamento", "arriendo", "comprar", "inmueble"], "lead_nuevo", "Seguimiento vertical", 80)],
        [_flow("Agenda de visitas", "Secuencia draft para leads inmobiliarios calificados.", "propiedades_enviadas", ["Validar disponibilidad de visita.", "Confirmar requisitos y asesor asignado."])],
        ["leads_calificados", "visitas_agendadas", "negocios_cerrados", "presupuesto_promedio"],
    ),
    "support": _pack(
        "support",
        "Soporte tecnico",
        "support",
        "Tickets, SLA, escalaciones y resolucion operativa.",
        ["support", "operations", "knowledge", "custom"],
        [_field("tipo_ticket", "Tipo de ticket", order=10), _field("prioridad", "Prioridad", "select", ["Baja", "Media", "Alta", "Critica"], 20), _field("producto_afectado", "Producto afectado", order=30)],
        [_template("Soporte inicial", "Hola {{customer_first_name}}, registramos tu caso. Comparte detalles, impacto y evidencia disponible."), _template("Escalacion soporte", "Hola {{customer_first_name}}, escalaremos tu caso para revision especializada.")],
        [_segment("Tickets escalados", "Casos con prioridad alta o critica.", {"crm_stage": "escalado"}), _segment("Tickets en revision", "Casos pendientes de diagnostico.", {"crm_stage": "en_revision"})],
        [_trigger("Ticket soporte", ["error", "falla", "soporte", "ayuda", "problema"], "ticket_nuevo", "Seguimiento vertical", 70)],
        [_flow("SLA soporte", "Secuencia draft para tickets abiertos.", "prioridad_detectada", ["Validar prioridad y evidencia.", "Escalar si se acerca SLA."])],
        ["sla_response", "ticket_resolution", "escalation_rate", "customer_effort"],
    ),
    "automotive": _pack(
        "automotive",
        "Automotriz",
        "services",
        "Leads vehiculares, cotizaciones, test drive y posventa.",
        ["sales", "appointment_scheduler", "retention", "custom"],
        [_field("vehiculo_interes", "Vehiculo de interes", order=10), _field("presupuesto", "Presupuesto", "number", order=20), _field("fecha_test_drive", "Fecha test drive", "date", order=30)],
        [_template("Cotizacion automotriz", "Hola {{customer_first_name}}, para cotizar necesito modelo, presupuesto y ciudad."), _template("Agenda test drive", "Hola {{customer_first_name}}, coordinemos horario para test drive o asesoria comercial.")],
        [_segment("Test drive pendiente", "Leads con interes validado.", {"crm_stage": "cotizacion_enviada"}), _segment("Leads automotrices calientes", "Leads con test drive agendado.", {"crm_stage": "test_drive_agendado"})],
        [_trigger("Interes vehiculo", ["carro", "vehiculo", "auto", "test drive", "cotizar"], "lead_nuevo", "Seguimiento vertical", 80)],
        [_flow("Test drive y cierre", "Secuencia draft para leads automotrices.", "cotizacion_enviada", ["Validar modelo y presupuesto.", "Agendar test drive con asesor."])],
        ["test_drives", "conversion_rate", "cotizaciones", "posventa"],
    ),
    "financial_services": _pack(
        "financial_services",
        "Servicios financieros",
        "regulated",
        "Leads financieros, revision humana, consentimiento y retencion.",
        ["financial_services", "sales", "retention", "custom"],
        [_field("producto_financiero", "Producto financiero", order=10), _field("perfil_riesgo", "Perfil de riesgo", "select", ["Bajo", "Medio", "Alto"], 20), _field("consentimiento", "Consentimiento registrado", "select", ["Pendiente", "Registrado"], 30)],
        [_template("Intake financiero", "Hola {{customer_first_name}}, puedo registrar tu interes y datos iniciales para revision humana."), _template("Seguimiento financiero", "Hola {{customer_first_name}}, revisaremos tu solicitud con un asesor antes de avanzar.")],
        [_segment("Revision financiera", "Leads que requieren revision humana.", {"crm_stage": "revision_humana"}), _segment("Clientes financieros activos", "Clientes activados o por seguimiento.", {"crm_stage": "cliente_activado"})],
        [_trigger("Producto financiero", ["credito", "prestamo", "inversion", "tarjeta", "financiero"], "lead_nuevo", "Seguimiento vertical", 70)],
        [_flow("Revision financiera", "Secuencia draft para casos regulados.", "perfil_calificado", ["Validar consentimiento y datos minimos.", "Escalar a revision humana antes de recomendar."])],
        ["conversion_rate", "risk_review", "retention_risk", "response_time"],
    ),
    "legal": _pack(
        "legal",
        "Legal",
        "regulated",
        "Intake legal, documentos y escalacion sin asesoria automatica.",
        ["legal_intake", "support", "knowledge", "custom"],
        [_field("area_legal", "Area legal", order=10), _field("jurisdiccion", "Jurisdiccion", order=20), _field("urgencia", "Urgencia", "select", ["Baja", "Media", "Alta"], 30)],
        [_template("Intake legal", "Hola {{customer_first_name}}, puedo registrar datos iniciales del caso para que un abogado lo revise."), _template("Documentos legales", "Hola {{customer_first_name}}, por favor comparte los documentos disponibles para revision humana.")],
        [_segment("Casos en revision", "Casos que requieren humano.", {"crm_stage": "revision_humana"}), _segment("Documentos pendientes legal", "Casos con documentos por recibir.", {"crm_stage": "documentos_pendientes"})],
        [_trigger("Consulta legal", ["abogado", "demanda", "contrato", "legal", "caso"], "intake_inicial", "Seguimiento vertical", 70)],
        [_flow("Documentos legales", "Secuencia draft para completar intake legal.", "documentos_pendientes", ["Solicitar documentos faltantes.", "Validar revision humana antes de respuesta."])],
        ["casos_nuevos", "revision_humana", "documentos_pendientes", "tiempo_intake"],
    ),
    "insurance": _pack(
        "insurance",
        "Seguros",
        "regulated",
        "Siniestros, polizas, documentos y seguimiento.",
        ["insurance_claims", "financial_services", "support", "custom"],
        [_field("numero_poliza", "Numero de poliza", order=10), _field("tipo_siniestro", "Tipo de siniestro", order=20), _field("fecha_siniestro", "Fecha del siniestro", "date", order=30)],
        [_template("Registro de siniestro", "Hola {{customer_first_name}}, puedo ayudarte a registrar datos del siniestro y documentos para revision."), _template("Documentos seguro", "Hola {{customer_first_name}}, necesitamos poliza, fecha del evento y soportes disponibles.")],
        [_segment("Siniestros nuevos", "Reclamos nuevos por clasificar.", {"crm_stage": "siniestro_nuevo"}), _segment("Documentos pendientes seguro", "Siniestros con soportes faltantes.", {"crm_stage": "documentos_pendientes"})],
        [_trigger("Siniestro seguro", ["siniestro", "poliza", "reclamo", "seguro", "accidente"], "siniestro_nuevo", "Seguimiento vertical", 70)],
        [_flow("Seguimiento de siniestro", "Secuencia draft para documentos y estado.", "documentos_pendientes", ["Revisar documentos requeridos.", "Escalar a analista si hay caso sensible."])],
        ["siniestros_nuevos", "documentos_pendientes", "casos_radicados", "tiempo_respuesta"],
    ),
    "beauty": _pack(
        "beauty",
        "Estetica y belleza",
        "services",
        "Agenda, preferencias, paquetes y recordatorios.",
        ["beauty_booking", "appointment_scheduler", "reputation_manager", "custom"],
        [_field("servicio_interes", "Servicio de interes", order=10), _field("fecha_preferida", "Fecha preferida", "date", order=20), _field("preferencias", "Preferencias", order=30)],
        [_template("Agenda belleza", "Hola {{customer_first_name}}, dime que servicio quieres y tu fecha preferida para coordinar agenda."), _template("Recordatorio cita", "Hola {{customer_first_name}}, dejamos pendiente confirmar tu cita o paquete.")],
        [_segment("Citas por confirmar belleza", "Servicios con cita propuesta.", {"crm_stage": "cita_propuesta"}), _segment("Preferencias capturadas", "Clientes con preferencias registradas.", {"crm_stage": "preferencias_capturadas"})],
        [_trigger("Agenda belleza", ["cita", "unas", "pestanas", "cabello", "tratamiento"], "consulta_servicio", "Seguimiento vertical", 80)],
        [_flow("Recordatorios belleza", "Secuencia draft para citas y paquetes.", "cita_propuesta", ["Confirmar agenda y politica de cancelacion.", "Enviar recordatorio manual antes de la cita."])],
        ["citas_propuestas", "citas_confirmadas", "clientes_recurrentes", "paquetes_interes"],
    ),
    "services": _pack(
        "services",
        "Servicios",
        "services",
        "Solicitudes, cotizaciones, agenda y despacho.",
        ["field_service_dispatch", "appointment_scheduler", "sales", "custom"],
        [_field("tipo_servicio", "Tipo de servicio", order=10), _field("direccion", "Direccion", order=20), _field("prioridad_servicio", "Prioridad", "select", ["Baja", "Media", "Alta", "Urgente"], 30)],
        [_template("Solicitud de servicio", "Hola {{customer_first_name}}, cuentame que servicio necesitas, direccion y disponibilidad."), _template("Cotizacion servicio", "Hola {{customer_first_name}}, revisamos tu solicitud para preparar cotizacion o agenda.")],
        [_segment("Servicios por cotizar", "Solicitudes con necesidad calificada.", {"crm_stage": "necesidad_calificada"}), _segment("Agenda pendiente servicios", "Servicios con agenda pendiente.", {"crm_stage": "agenda_pendiente"})],
        [_trigger("Solicitud de servicio", ["servicio", "reparacion", "instalacion", "cotizacion", "visita"], "solicitud_nueva", "Seguimiento vertical", 80)],
        [_flow("Despacho y cotizacion", "Secuencia draft para servicios operativos.", "necesidad_calificada", ["Validar direccion y prioridad.", "Coordinar visita o cotizacion."])],
        ["solicitudes_nuevas", "cotizaciones_enviadas", "servicios_confirmados", "sla_operativo"],
    ),
}


def normalize_industry_code(value: str | None) -> str:
    clean = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    clean = INDUSTRY_ALIASES.get(clean, clean)
    return clean if clean in INDUSTRY_PACKS else "general"


def get_industry_pack(value: str | None) -> dict[str, Any]:
    return deepcopy(INDUSTRY_PACKS[normalize_industry_code(value)])


def list_industry_packs() -> list[dict[str, Any]]:
    return [deepcopy(INDUSTRY_PACKS[key]) for key in sorted(INDUSTRY_PACKS.keys(), key=lambda item: (item != "general", item))]


def pack_summary(pack: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": pack["code"],
        "label": pack["label"],
        "category": pack["category"],
        "description": pack["description"],
        "pack_version": pack["pack_version"],
        "counts": {
            "pipeline_stages": len(pack.get("pipeline") or []),
            "custom_fields": len(pack.get("custom_fields") or []),
            "templates": len(pack.get("templates") or []),
            "segments": len(pack.get("segments") or []),
            "triggers": len(pack.get("triggers") or []),
            "flows": len(pack.get("flows") or []),
            "agents": len(pack.get("agent_types") or []),
            "kpis": len(pack.get("kpis") or []),
        },
        "agent_types": list(pack.get("agent_types") or []),
        "kpis": list(pack.get("kpis") or []),
    }
