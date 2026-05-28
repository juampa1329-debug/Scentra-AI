const DEFAULT_LOCALE = "es-CO";

const catalogs = {
  "es-CO": {
    "view.overview": "Resumen",
    "view.tenants": "Empresas",
    "view.plans": "Planes",
    "view.subscriptions": "Suscripciones",
    "view.billing": "Facturacion",
    "view.security": "Seguridad",
    "view.intelligence": "IA Predictiva",
    "view.trust": "Trust AI",
    "view.performance": "Rendimiento",
    "view.operations": "Operacion",
    "view.observability": "Salud",
    "view.audit": "Auditoria",
    "metric.reliability": "Confiabilidad",
    "metric.backlog": "Pendientes",
    "panel.performance": "Control de rendimiento",
    "panel.backup_readiness": "Preparacion de respaldo",
    "panel.slo_metrics": "Metricas SLO",
    "button.backup_readiness": "Preparacion de respaldo",
    "button.retention_dry_run": "Dry-run de retencion",
    "button.process_reliability": "Procesar confiabilidad",
  },
};

const activeLocale = catalogs[String(import.meta.env.VITE_ADMIN_LOCALE || "").trim()] ? String(import.meta.env.VITE_ADMIN_LOCALE).trim() : DEFAULT_LOCALE;

export function t(key, fallback = "") {
  return catalogs[activeLocale]?.[key] || catalogs[DEFAULT_LOCALE]?.[key] || fallback || key;
}

export function adminLocale() {
  return activeLocale;
}
