const DEFAULT_LOCALE = "es-CO";

const catalogs = {
  "es-CO": {
    "brand.subtitle": "Centro comercial IA",
    "nav.dashboard": "Panel",
    "nav.inbox": "Inbox",
    "nav.customers": "Clientes",
    "nav.labels": "Etiquetas",
    "nav.campaigns": "CRM",
    "nav.broadcast": "Masiva",
    "nav.ads": "Anuncios",
    "nav.agents": "Agentes IA",
    "nav.intelligence": "Inteligencia",
    "nav.ecosystem": "Ecosistema IA",
    "nav.composer": "Composer",
    "nav.trust": "Trust AI",
    "nav.settings": "Ajustes",
    "page.dashboard.title": "Panel",
    "page.dashboard.description": "Vista ejecutiva de la empresa y operacion comercial.",
    "page.inbox.title": "Inbox",
    "page.inbox.description": "Conversaciones, comentarios y seguimiento operativo.",
    "page.customers.title": "Clientes",
    "page.customers.description": "CRM comercial, fichas, pipeline y timeline.",
    "page.labels.title": "Etiquetas",
    "page.labels.description": "Segmentacion visual y estados comerciales.",
    "page.campaigns.title": "CRM",
    "page.campaigns.description": "Campanas, triggers, flows y remarketing.",
    "page.broadcast.title": "Masiva",
    "page.broadcast.description": "Envios, plantillas Meta y reportes.",
    "page.ads.title": "Anuncios",
    "page.ads.description": "Leads, comentarios e integraciones sociales.",
    "page.agents.title": "Agentes IA",
    "page.agents.description": "Agentes empresariales para estrategia, ventas, soporte y operaciones.",
    "page.intelligence.title": "Inteligencia",
    "page.intelligence.description": "Predicciones, Advisor, operaciones autonomas y benchmarks verticales.",
    "page.ecosystem.title": "Ecosistema IA",
    "page.ecosystem.description": "Marketplace, plugins, SDK, herramientas e integraciones IA.",
    "page.composer.title": "Workflow Composer",
    "page.composer.description": "Diseno, simulacion, aprobacion, versionado y activacion controlada de workflows IA.",
    "page.trust.title": "Trust AI",
    "page.trust.description": "Gobierno, compliance, riesgos, model cards, incidentes y auditoria AI.",
    "page.settings.title": "Ajustes",
    "page.settings.description": "Canales, APIs, industria, plan, seguridad y diagnostico.",
    "settings.tab.ia": "IA",
    "settings.tab.vertical": "Industria",
    "settings.tab.channels": "Canales",
    "settings.tab.apis": "APIs",
    "settings.tab.debug": "Diagnostico",
    "settings.tab.users": "Usuarios",
    "settings.tab.profile": "Perfil",
    "settings.tab.security": "Seguridad",
    "settings.tab.plan": "Plan",
    "status.dashboard.updated": "Panel actualizado",
    "status.ecosystem.updated": "Ecosistema IA actualizado",
    "status.agents.updated": "Agentes IA actualizados",
    "meta.facebook.opened": "Conexion de Facebook abierta con la app Meta del cliente. Al finalizar, vuelve y pulsa Cargar cuentas.",
    "meta.facebook.start_first": "Primero inicia la conexion de Facebook.",
    "meta.facebook.missing_state": "Estado OAuth faltante. Inicia la conexion de Facebook de nuevo.",
    "meta.facebook.discovery_label": "Conexion de Facebook, descubrimiento automatico y webhooks",
    "meta.facebook.auto_refresh_hint": "Para auto-renovar necesitas conectar por OAuth de Facebook o guardar un user token OAuth junto al App ID/App Secret.",
    "meta.facebook.connect_button": "Conectar con Facebook",
    "meta.facebook.finish_empty": "Cuando termines la conexion de Facebook, pulsa Cargar cuentas detectadas.",
  },
};

const activeLocale = catalogs[String(import.meta.env.VITE_APP_LOCALE || "").trim()] ? String(import.meta.env.VITE_APP_LOCALE).trim() : DEFAULT_LOCALE;

export function t(key, fallback = "") {
  return catalogs[activeLocale]?.[key] || catalogs[DEFAULT_LOCALE]?.[key] || fallback || key;
}

export function appLocale() {
  return activeLocale;
}
