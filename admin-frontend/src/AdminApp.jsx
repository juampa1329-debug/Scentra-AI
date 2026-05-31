import React, { useEffect, useMemo, useRef, useState } from "react";
import { t } from "./i18n.js";

const API_BASE = (import.meta.env.VITE_API_BASE || "").replace(/\/$/, "");
const CLIENT_APP_BASE = (import.meta.env.VITE_CLIENT_APP_BASE || "http://localhost:5174").replace(/\/$/, "");
const TOKEN_KEY = "scentra_admin_access_token";
const TURNSTILE_SITE_KEY = String(import.meta.env.VITE_TURNSTILE_SITE_KEY || "").trim();
const CAPTCHA_ENABLED = ["1", "true", "yes", "on"].includes(String(import.meta.env.VITE_CAPTCHA_ENABLED || "").toLowerCase()) || Boolean(TURNSTILE_SITE_KEY);
const ADMIN_BOOTSTRAP_ENABLED = ["1", "true", "yes", "on"].includes(String(import.meta.env.VITE_ADMIN_BOOTSTRAP_ENABLED || "").toLowerCase())
  || ["localhost", "127.0.0.1"].includes(window.location.hostname);
const CAPTCHA_PROVIDER = "turnstile";
const SCENTRA_FAVICON_URL = "https://scentra-ai.online/favicon.png";
const SCENTRA_WHITE_LOGO_URL = "https://scentra-ai.online/logo-blanco.png";
const DEFAULT_TIME_ZONE = "America/Bogota";
const TIME_ZONE_KEY = "scentra_admin_timezone";
const TIME_ZONE_OPTIONS = [
  ["America/Bogota", "Colombia"],
  ["America/Lima", "Peru"],
  ["America/Mexico_City", "Mexico"],
  ["America/New_York", "Este USA"],
  ["America/Los_Angeles", "Pacifico USA"],
  ["America/Madrid", "Espana"],
  ["UTC", "UTC"],
];
const PAYMENT_LOGOS = [
  { label: "Wompi", src: "https://wompi.com/assets/downloadble/logos_wompi/Wompi_LogoPrincipal.png", wide: true },
  { label: "Mercado Pago", src: "https://upload.wikimedia.org/wikipedia/commons/9/98/Mercado_Pago.svg", wide: true },
  { label: "Visa", src: "https://cdn.simpleicons.org/visa/1434CB" },
  { label: "Mastercard", src: "https://cdn.simpleicons.org/mastercard/EB001B" },
];
let turnstileScriptPromise = null;

const VIEWS = [
  ["overview", t("view.overview")],
  ["tenants", t("view.tenants")],
  ["plans", t("view.plans")],
  ["subscriptions", t("view.subscriptions")],
  ["billing", t("view.billing")],
  ["users", "Usuarios"],
  ["notifications", "Notificaciones"],
  ["security", t("view.security")],
  ["intelligence", t("view.intelligence")],
  ["trust", t("view.trust")],
  ["performance", t("view.performance")],
  ["operations", t("view.operations")],
  ["observability", t("view.observability")],
  ["audit", t("view.audit")],
];
const TENANT_ROLE_LABELS = { owner: "Propietario", admin: "Administrador", supervisor: "Supervisor", agent: "Agente", viewer: "Lector" };
const PLATFORM_ROLE_LABELS = { superadmin: "Superadministrador", platform_admin: "Administrador plataforma", billing_admin: "Facturación", support: "Soporte", viewer: "Lector" };
const SEVERITY_LABELS = { info: "Información", success: "Confirmación", warning: "Alerta", critical: "Alerta crítica" };
const CATEGORY_LABELS = {
  system: "Sistema",
  account: "Cuenta",
  security: "Seguridad",
  billing: "Facturación",
  operations: "Operación",
  ai: "IA",
  maintenance: "Mantenimiento",
};

function roleLabel(role, platform = false) {
  const key = String(role || "").toLowerCase();
  const map = platform ? PLATFORM_ROLE_LABELS : TENANT_ROLE_LABELS;
  return map[key] || (key ? key.replaceAll("_", " ") : "Usuario");
}

function categoryLabel(category) {
  const key = String(category || "").toLowerCase();
  return CATEGORY_LABELS[key] || (key ? key.replaceAll("_", " ") : "Sistema");
}
const TENANT_STATUSES = ["active", "trial", "paused", "past_due", "suspended", "cancelled"];
const SUB_STATUSES = ["trial", "active", "past_due", "cancelled", "suspended"];
const INDUSTRY_OPTIONS = [
  ["general", "General"],
  ["retail", "Retail"],
  ["ecommerce", "Ecommerce"],
  ["restaurant", "Restaurantes"],
  ["hotel", "Hoteles"],
  ["health", "Clinicas y salud"],
  ["education", "Academias"],
  ["real_estate", "Inmobiliarias"],
  ["support", "Soporte tecnico"],
  ["automotive", "Automotriz"],
  ["financial_services", "Servicios financieros"],
  ["legal", "Legal"],
  ["insurance", "Seguros"],
  ["beauty", "Estetica y belleza"],
  ["services", "Servicios"],
];
const DEFAULT_FEATURES = {
  inbox: true,
  ai: true,
  ai_agents: true,
  advisor: true,
  broadcast: true,
  triggers: false,
  remarketing: false,
  ads: false,
  whatsapp_cloud: true,
  instagram_business: false,
  facebook_messenger: false,
  social_comments: false,
  knowledge_base: true,
  woocommerce: false,
  shopify: false,
  elevenlabs_voice: false,
  intelligence_demo: true,
  ai_premium: false,
  ml_predictions: false,
  lead_scoring_ml: false,
  churn_prediction: false,
  smart_remarketing: false,
  ai_operational_intelligence: false,
  predictive_recommendations: false,
  advanced_analytics: false,
  ai_advisors_premium: false,
  autonomous_operations: false,
  ai_self_healing: false,
  ai_control_center: false,
  multi_agent_os: false,
  event_driven_agents: false,
  agent_tool_tracing: false,
  ai_marketplace: false,
  ai_plugin_center: false,
  ai_developer_console: false,
  ai_tool_registry: false,
  ai_app_framework: false,
  enterprise_ai_network: false,
  vertical_ai_intelligence: false,
  industry_ai_models: false,
  benchmark_intelligence: false,
  cross_tenant_intelligence: false,
  vertical_ai_advisors: false,
  ai_playbook_library: false,
  federated_learning: false,
  federated_model_updates: false,
  privacy_safe_model_aggregation: false,
  global_intelligence: false,
  federated_benchmarking: false,
  ai_workflow_composer: false,
  workflow_composer_templates: false,
  ai_trust_center: false,
  ai_governance_policies: false,
  ai_risk_assessments: false,
  ai_model_cards: false,
  ai_compliance_reports: false,
  ai_audit_exports: false,
  realtime_intelligence_layer: false,
  realtime_event_stream: false,
  realtime_ai_alerts: false,
  realtime_intelligence_dashboard: false,
  voice_intelligence: false,
  voice_transcription: false,
  voice_sentiment_intent: false,
  vision_intelligence: false,
  image_understanding: false,
  document_ocr: false,
  web_search_intelligence: false,
  image_search_intelligence: false,
  external_source_assist: false,
  agent_multimodal_tools: false,
  agent_voice_tools: false,
  agent_vision_tools: false,
  agent_external_search_tools: false,
  multimodal_memory_events: false,
  multimodal_training_events: false,
  multimodal_rag_materialization: false,
  multimodal_agent_memory: false,
  multimodal_observability: false,
  multimodal_cost_observability: false,
  multimodal_quality_monitoring: false,
  multimodal_safe_rollout: false,
  multimodal_canary: false,
  autonomous_revenue_engine: false,
  revenue_opportunity_detection: false,
  revenue_forecasting: false,
  revenue_playbooks: false,
  revenue_experiments: false,
  enterprise_memory_network: false,
  memory_graph: false,
  memory_governance: false,
  cross_agent_memory_routing: false,
  memory_quality_scoring: false,
};
const PHASE24_FEATURE_KEYS = [
  "voice_intelligence",
  "voice_transcription",
  "voice_sentiment_intent",
  "vision_intelligence",
  "image_understanding",
  "document_ocr",
  "web_search_intelligence",
  "image_search_intelligence",
  "external_source_assist",
  "agent_multimodal_tools",
  "agent_voice_tools",
  "agent_vision_tools",
  "agent_external_search_tools",
  "multimodal_memory_events",
  "multimodal_training_events",
  "multimodal_rag_materialization",
  "multimodal_agent_memory",
  "multimodal_observability",
  "multimodal_cost_observability",
  "multimodal_quality_monitoring",
  "multimodal_safe_rollout",
  "multimodal_canary",
];
const PROVIDER_POLICY_DEFAULT = {
  scope_type: "global",
  scope_id: "",
  provider_category: "ai",
  provider_code: "google",
  model_id: "",
  enabled: true,
  input_cost_cents_per_1k: 0,
  output_cost_cents_per_1k: 0,
  request_cost_cents: 0,
  monthly_request_quota: 0,
  monthly_cost_limit_cents: 0,
  currency: "USD",
  notes: "",
};
const PAYMENT_PROVIDER_META = {
  wompi: {
    name: "Wompi",
    description: "Checkout Web de Wompi para pagos con tarjetas, PSE y medios locales.",
    fields: [
      ["public_key", "Llave publica"],
      ["private_key", "Llave privada"],
      ["event_key", "Llave privada de eventos"],
      ["integrity_key", "Llave de integridad"],
    ],
  },
  mercadopago: {
    name: "Mercado Pago",
    description: "Checkout de Mercado Pago para pagos con tarjetas y metodos disponibles por pais.",
    fields: [
      ["access_token", "Token de acceso"],
      ["webhook_secret", "Secreto de webhook"],
    ],
  },
};
const PAYMENT_PROVIDER_DEFAULT_FORM = {
  display_name: "",
  title: "",
  is_enabled: false,
  is_default: false,
  test_mode: true,
  debug_logging: false,
  test_public_key: "",
  test_private_key: "",
  test_event_key: "",
  test_integrity_key: "",
  live_public_key: "",
  live_private_key: "",
  live_event_key: "",
  live_integrity_key: "",
  test_access_token: "",
  test_webhook_secret: "",
  live_access_token: "",
  live_webhook_secret: "",
};
const DEFAULT_AGENT_TYPES = [
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
  "teacher",
];

const number = (value) => Number(value || 0).toLocaleString("es-CO");
const money = (cents, currency = "USD") => `${currency} ${(Number(cents || 0) / 100).toLocaleString("es-CO", { minimumFractionDigits: 0, maximumFractionDigits: 2 })}`;
const pct = (used, limit) => (!Number(limit || 0) ? 0 : Math.min(100, Math.round((Number(used || 0) / Number(limit || 0)) * 100)));

function normalizeTimeZone(value) {
  const candidate = String(value || "").trim() || DEFAULT_TIME_ZONE;
  try {
    new Intl.DateTimeFormat("es-CO", { timeZone: candidate }).format(new Date());
    return candidate;
  } catch {
    return DEFAULT_TIME_ZONE;
  }
}

function currentUiTimeZone() {
  try {
    return normalizeTimeZone(localStorage.getItem(TIME_ZONE_KEY) || DEFAULT_TIME_ZONE);
  } catch {
    return DEFAULT_TIME_ZONE;
  }
}

function rememberUiTimeZone(value) {
  const timezone = normalizeTimeZone(value);
  try { localStorage.setItem(TIME_ZONE_KEY, timezone); } catch { /* localStorage unavailable */ }
  return timezone;
}

const compactDateTimeLabel = (value) => {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString("es-CO", { timeZone: currentUiTimeZone(), dateStyle: "medium", timeStyle: "short" });
};

function emptyLogin() {
  return { email: "", password: "" };
}

function emptyPasswordRecovery() {
  return { email: "" };
}

function emptyPasswordReset() {
  return { token: "", new_password: "", confirm_password: "" };
}

function loadTurnstileScript() {
  if (window.turnstile) return Promise.resolve(window.turnstile);
  if (turnstileScriptPromise) return turnstileScriptPromise;
  turnstileScriptPromise = new Promise((resolve, reject) => {
    const existing = document.querySelector("script[data-scentra-turnstile]");
    if (existing) {
      existing.addEventListener("load", () => resolve(window.turnstile));
      existing.addEventListener("error", reject);
      return;
    }
    const script = document.createElement("script");
    script.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
    script.async = true;
    script.defer = true;
    script.dataset.scentraTurnstile = "true";
    script.onload = () => resolve(window.turnstile);
    script.onerror = reject;
    document.head.appendChild(script);
  });
  return turnstileScriptPromise;
}

function TurnstileChallenge({ onToken, resetKey = 0 }) {
  const containerRef = useRef(null);
  const widgetIdRef = useRef(null);

  useEffect(() => {
    let cancelled = false;
    if (!CAPTCHA_ENABLED || !TURNSTILE_SITE_KEY) {
      onToken("");
      return undefined;
    }
    onToken("");
    loadTurnstileScript()
      .then((turnstile) => {
        if (cancelled || !containerRef.current || !turnstile) return;
        if (widgetIdRef.current !== null && turnstile.remove) {
          try { turnstile.remove(widgetIdRef.current); } catch { /* widget already cleared */ }
        }
        containerRef.current.innerHTML = "";
        widgetIdRef.current = turnstile.render(containerRef.current, {
          sitekey: TURNSTILE_SITE_KEY,
          theme: "dark",
          callback: (token) => onToken(token || ""),
          "expired-callback": () => onToken(""),
          "error-callback": () => onToken(""),
        });
      })
      .catch(() => onToken(""));
    return () => {
      cancelled = true;
      if (window.turnstile?.remove && widgetIdRef.current !== null) {
        try { window.turnstile.remove(widgetIdRef.current); } catch { /* ignore cleanup race */ }
      }
      widgetIdRef.current = null;
    };
  }, [onToken, resetKey]);

  if (!CAPTCHA_ENABLED || !TURNSTILE_SITE_KEY) return null;
  return (
    <div className="captcha-box">
      <div ref={containerRef} />
      <small>Proteccion anti-bots activa.</small>
    </div>
  );
}

function BrandGlyph() {
  return <span className="brand-glyph"><img src={SCENTRA_FAVICON_URL} alt="" loading="lazy" /></span>;
}

function PaymentLogoChip({ logo }) {
  const [failed, setFailed] = useState(false);
  return (
    <span className={`payment-logo-chip ${logo.wide ? "wide" : ""}`}>
      {logo.src && !failed ? <img src={logo.src} alt={logo.label} loading="lazy" onError={() => setFailed(true)} /> : <strong>{logo.label}</strong>}
    </span>
  );
}

function PaymentLogoStrip() {
  return <div className="payment-logo-strip" aria-label="Pasarelas y tarjetas">{PAYMENT_LOGOS.map((logo) => <PaymentLogoChip key={logo.label} logo={logo} />)}</div>;
}

function ErrorDialog({ notice, onClose }) {
  if (!notice) return null;
  return (
    <div className="modal-backdrop error-modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section className="modal-window glass-card error-modal" role="dialog" aria-modal="true" aria-label="Error de Scentra Admin" onMouseDown={(event) => event.stopPropagation()}>
        <div className="panel-head"><div><span className="section-chip">Scentra Admin</span><h2>{notice.title || "Necesita revision"}</h2></div><button type="button" onClick={onClose}>Cerrar</button></div>
        <p>{notice.message}</p>
        {notice.suggestion ? <div className="notification-help"><strong>Que puedes hacer</strong><span>{notice.suggestion}</span></div> : null}
        {notice.technical && notice.technical !== notice.message ? <details><summary>Detalle tecnico</summary><code>{notice.technical}</code></details> : null}
      </section>
    </div>
  );
}

function emptyPlan() {
  return {
    plan_code: "",
    display_name: "",
    max_agents: 3,
    max_monthly_messages: 5000,
    max_integrations: 3,
    max_storage_gb: 5,
    max_campaigns: 10,
    max_broadcasts: 10,
    max_ai_tokens: 1000000,
    price_monthly_cents: 0,
    currency: "USD",
    is_public: true,
    is_active: true,
    sort_order: 100,
    feature_flags_json: { ...DEFAULT_FEATURES },
    ai_agent_limits: {
      max_ai_agents: 1,
      max_active_ai_agents: 1,
      max_memory_archives: 1,
      allowed_agent_types_json: [...DEFAULT_AGENT_TYPES],
      builder_enabled: true,
      notes: "",
    },
  };
}

function emptyPaymentProviderForms() {
  return {
    wompi: { ...PAYMENT_PROVIDER_DEFAULT_FORM, display_name: "Wompi", title: "Paga con Wompi" },
    mercadopago: { ...PAYMENT_PROVIDER_DEFAULT_FORM, display_name: "Mercado Pago", title: "Paga con Mercado Pago" },
  };
}

function paymentProviderFormFromApi(provider) {
  const key = String(provider?.provider || "").toLowerCase();
  const base = emptyPaymentProviderForms()[key] || { ...PAYMENT_PROVIDER_DEFAULT_FORM };
  return {
    ...base,
    display_name: provider?.display_name || base.display_name,
    title: provider?.title || base.title,
    is_enabled: Boolean(provider?.is_enabled),
    is_default: Boolean(provider?.is_default),
    test_mode: provider?.test_mode !== false,
    debug_logging: Boolean(provider?.debug_logging),
    test_public_key: provider?.test?.public_key || "",
    live_public_key: provider?.live?.public_key || "",
  };
}

function formatApiError(data, fallback) {
  const detail = data?.detail || data?.error;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((item) => item.msg || "dato invalido").join(" | ");
  if (detail && typeof detail === "object") return detail.message || detail.code || fallback;
  return fallback;
}

function readableErrorNotice(text) {
  const raw = String(text || "").trim();
  const lower = raw.toLowerCase();
  let message = raw || "Ocurrio un error inesperado.";
  let suggestion = "Intenta de nuevo. Si se repite, revisa el panel de observabilidad y comparte el detalle con soporte.";
  if (lower.includes("403") || lower.includes("forbidden") || lower.includes("permission")) {
    message = "La accion fue rechazada por permisos.";
    suggestion = "Verifica tu rol de Admin, permisos del tenant o credenciales del proveedor antes de repetir.";
  } else if (lower.includes("rate_limit") || lower.includes("429")) {
    message = "Se activaron limites de seguridad por demasiadas solicitudes.";
    suggestion = "Espera unos minutos antes de volver a intentar.";
  } else if (lower.includes("500") || lower.includes("internal_server_error")) {
    message = "El servidor no pudo completar la accion.";
    suggestion = "Revisa Observabilidad, el correlation_id del backend y vuelve a intentar cuando el servicio este estable.";
  } else if (lower.includes("session") || lower.includes("401")) {
    message = "Tu sesion Admin necesita renovarse.";
    suggestion = "Inicia sesion otra vez y repite la accion.";
  } else if (lower.includes("invalid_current_password")) {
    message = "La clave actual no coincide.";
    suggestion = "Revisa la clave antes de cambiar correo o password.";
  }
  return { title: "Necesita revision", message, suggestion, technical: raw };
}

function statusClass(status) {
  const value = String(status || "").toLowerCase();
  if (["active", "trial", "sent", "ok"].includes(value)) return "ok";
  if (["past_due", "paused", "queued", "degraded", "unknown", "retry", "watch", "needs_feedback", "insufficient_data", "warning", "dry_run"].includes(value)) return "warn";
  if (["suspended", "cancelled", "failed", "error", "critical", "down"].includes(value)) return "danger";
  return "neutral";
}

function taskTypeLabel(task) {
  return ({
    lead_scoring: "Puntaje comercial",
    churn_prediction: "Riesgo de abandono",
    smart_remarketing: "Remarketing inteligente",
    operational_anomaly: "Anomalia operacional",
  }[String(task || "").toLowerCase()] || String(task || "Tarea"));
}

function queueTotal(rows, status) {
  return (rows || []).find((item) => item.status === status)?.total || 0;
}

export default function AdminApp() {
  const [token, setToken] = useState(() => localStorage.getItem(TOKEN_KEY) || "");
  const [me, setMe] = useState(null);
  const [authMode, setAuthMode] = useState("login");
  const [activeView, setActiveView] = useState("overview");
  const [login, setLogin] = useState(emptyLogin);
  const [passwordRecovery, setPasswordRecovery] = useState(emptyPasswordRecovery);
  const [passwordReset, setPasswordReset] = useState(emptyPasswordReset);
  const [bootstrap, setBootstrap] = useState({ email: "", password: "", full_name: "Scentra Admin", platform_role: "superadmin" });
  const [adminProfileForm, setAdminProfileForm] = useState({ full_name: "", email: "", phone: "", role_label: "", avatar_url: "", timezone: currentUiTimeZone(), current_password: "" });
  const [adminPasswordForm, setAdminPasswordForm] = useState({ current_password: "", new_password: "", confirm_password: "" });
  const [loginCaptchaToken, setLoginCaptchaToken] = useState("");
  const [mfaChallenge, setMfaChallenge] = useState(null);
  const [mfaCode, setMfaCode] = useState("");
  const [recoveryCaptchaToken, setRecoveryCaptchaToken] = useState("");
  const [resetCaptchaToken, setResetCaptchaToken] = useState("");
  const [bootstrapCaptchaToken, setBootstrapCaptchaToken] = useState("");
  const [loginCaptchaReset, setLoginCaptchaReset] = useState(0);
  const [recoveryCaptchaReset, setRecoveryCaptchaReset] = useState(0);
  const [resetCaptchaReset, setResetCaptchaReset] = useState(0);
  const [bootstrapCaptchaReset, setBootstrapCaptchaReset] = useState(0);
  const [status, setStatus] = useState("");
  const [statusTone, setStatusTone] = useState("neutral");
  const [errorDialog, setErrorDialog] = useState(null);
  const [loading, setLoading] = useState(false);
  const [overview, setOverview] = useState(null);
  const [tenants, setTenants] = useState([]);
  const [tenantSearch, setTenantSearch] = useState("");
  const [tenantStatus, setTenantStatus] = useState("all");
  const [tenantPlan, setTenantPlan] = useState("all");
  const [selectedTenantId, setSelectedTenantId] = useState("");
  const [tenantDetail, setTenantDetail] = useState(null);
  const [plans, setPlans] = useState([]);
  const [planForm, setPlanForm] = useState(emptyPlan);
  const [subscriptions, setSubscriptions] = useState([]);
  const [billingInvoices, setBillingInvoices] = useState([]);
  const [billingCredits, setBillingCredits] = useState([]);
  const [billingForm, setBillingForm] = useState({ tenant_id: "", metric_code: "monthly_messages", amount: 1000, reason: "Credito manual", expires_at: "" });
  const [billingProviders, setBillingProviders] = useState([]);
  const [billingProviderForms, setBillingProviderForms] = useState(emptyPaymentProviderForms);
  const [billingProviderBusy, setBillingProviderBusy] = useState("");
  const [audit, setAudit] = useState([]);
  const [adminSecurity, setAdminSecurity] = useState(null);
  const [securityCompliance, setSecurityCompliance] = useState(null);
  const [platformAdmins, setPlatformAdmins] = useState([]);
  const [platformAdminRoles, setPlatformAdminRoles] = useState(Object.keys(PLATFORM_ROLE_LABELS));
  const [platformAdminForm, setPlatformAdminForm] = useState({ email: "", full_name: "", password: "", platform_role: "support", status: "active", notes: "", send_email: true });
  const [tenantUsers, setTenantUsers] = useState([]);
  const [tenantUserRoles, setTenantUserRoles] = useState(Object.keys(TENANT_ROLE_LABELS));
  const [tenantUserForm, setTenantUserForm] = useState({ tenant_id: "", email: "", full_name: "", password: "", role: "agent", send_email: true });
  const [userBusy, setUserBusy] = useState("");
  const [usersAdminTab, setUsersAdminTab] = useState("profile");
  const [tenantUserSearch, setTenantUserSearch] = useState("");
  const [notificationTargets, setNotificationTargets] = useState({ tenants: [], users: [], roles: [], smtp_configured: false });
  const [adminNotifications, setAdminNotifications] = useState([]);
  const [notificationForm, setNotificationForm] = useState({ title: "", body: "", severity: "info", category: "system", audience_type: "selected", tenant_ids: [], user_ids: [], roles: [], email_copy: true, ai_assisted: false });
  const [notificationDraftForm, setNotificationDraftForm] = useState({ topic: "", audience: "", tone: "claro", urgency: "normal", body_hint: "" });
  const [notificationBusy, setNotificationBusy] = useState("");
  const [notificationTargetSearch, setNotificationTargetSearch] = useState("");
  const [queues, setQueues] = useState(null);
  const [health, setHealth] = useState(null);
  const [deadLetters, setDeadLetters] = useState([]);
  const [metaErrors, setMetaErrors] = useState([]);
  const [features, setFeatures] = useState([]);
  const [intelligenceTenants, setIntelligenceTenants] = useState([]);
  const [intelligenceCatalog, setIntelligenceCatalog] = useState([]);
  const [intelligenceMetrics, setIntelligenceMetrics] = useState([]);
  const [intelligenceModels, setIntelligenceModels] = useState([]);
  const [intelligenceTraining, setIntelligenceTraining] = useState({ readiness: {}, summaries: [], samples: [] });
  const [intelligenceMlops, setIntelligenceMlops] = useState({ config: {}, jobs: [], artifacts: [], inference_runs: [], drift_snapshots: [], counts: {} });
  const [intelligenceRealtime, setIntelligenceRealtime] = useState({ totals: {}, tenants: [], feature_keys: [] });
  const [intelligenceGating, setIntelligenceGating] = useState({ features: [], tenants: [], plans: [], plan_feature_limits: [], provider_policies: [], provider_credentials: [], provider_costs: { totals: {}, ai: [], search: [] } });
  const [providerPolicyForm, setProviderPolicyForm] = useState({ ...PROVIDER_POLICY_DEFAULT });
  const [trustOverview, setTrustOverview] = useState(null);
  const [reliability, setReliability] = useState(null);
  const [intelligenceDataForm, setIntelligenceDataForm] = useState({ tenant_id: "", prediction_type: "lead_scoring", window_key: "90d", limit: 1000 });
  const [intelligenceTrainForm, setIntelligenceTrainForm] = useState({
    tenant_id: "",
    task_type: "lead_scoring",
    model_key: "",
    framework: "lightgbm",
    version: "",
    dataset_key: "",
    window_key: "90d",
    min_samples: 50,
    include_global: false,
    include_internal_demo: false,
    sample_size: 1000,
    seed: 42,
    register_model_registry: true,
  });
  const [intelligenceModelForm, setIntelligenceModelForm] = useState({
    model_key: "",
    task_type: "lead_scoring",
    model_type: "external",
    framework: "pending",
    version: "v1",
    artifact_uri: "",
    rollout_mode: "shadow",
    traffic_percent: 0,
    promotion_status: "pending_review",
  });

  const showStatus = (text, tone = "neutral") => {
    const notice = tone === "error" ? readableErrorNotice(text) : null;
    setStatus(notice?.message || text);
    setStatusTone(tone);
    if (notice) setErrorDialog(notice);
  };
  const headers = useMemo(() => {
    const next = { "Content-Type": "application/json" };
    if (token) next.Authorization = `Bearer ${token}`;
    return next;
  }, [token]);

  const apiCall = async (path, options = {}) => {
    if (!API_BASE) throw new Error("VITE_API_BASE requerido");
    const res = await fetch(`${API_BASE}${path}`, { ...options, headers: { ...headers, ...(options.headers || {}) } });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(formatApiError(data, `HTTP ${res.status}`));
    return data;
  };
  const downloadApiFile = async (path, filename = "scentra.pdf") => {
    if (!API_BASE) throw new Error("VITE_API_BASE requerido");
    const res = await fetch(`${API_BASE}${path}`, { headers: { Authorization: headers.Authorization || "" } });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(formatApiError(data, `HTTP ${res.status}`));
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 60000);
  };

  const setSession = (data) => {
    const nextToken = data?.access_token || "";
    setToken(nextToken);
    if (nextToken) localStorage.setItem(TOKEN_KEY, nextToken);
    setMe({ user_id: data?.user_id, email: data?.email, platform_role: data?.platform_role });
    setMfaChallenge(null);
    setMfaCode("");
  };

  const clearSession = () => {
    setToken("");
    setMe(null);
    setMfaChallenge(null);
    setMfaCode("");
    setAuthMode("login");
    localStorage.removeItem(TOKEN_KEY);
  };

  const loadMe = async () => {
    if (!token) return;
    const data = await apiCall("/saas/v1/admin/auth/me");
    setMe(data);
    const profile = data?.profile_json || {};
    const timezone = rememberUiTimeZone(profile.timezone || currentUiTimeZone());
    setAdminProfileForm((prev) => ({
      ...prev,
      full_name: prev.full_name || data?.full_name || "",
      email: prev.email || data?.email || "",
      phone: prev.phone || profile.phone || "",
      role_label: prev.role_label || profile.role_label || "",
      avatar_url: prev.avatar_url || profile.avatar_url || "",
      timezone,
    }));
  };

  const loadOverview = async () => {
    const data = await apiCall("/saas/v1/admin/overview");
    setOverview(data);
    setQueues(data?.queues || null);
  };

  const loadPlans = async () => {
    const data = await apiCall("/saas/v1/admin/plans");
    setPlans(data?.plans || []);
  };

  const loadFeatures = async () => {
    const data = await apiCall("/saas/v1/admin/feature-flags/catalog");
    setFeatures(data?.features || []);
  };

  const loadTenants = async () => {
    const params = new URLSearchParams({ search: tenantSearch, status: tenantStatus, plan_code: tenantPlan, limit: "100", offset: "0" });
    const data = await apiCall(`/saas/v1/admin/tenants?${params.toString()}`);
    setTenants(data?.tenants || []);
    if (!selectedTenantId && data?.tenants?.[0]?.id) setSelectedTenantId(data.tenants[0].id);
  };

  const loadTenantDetail = async (tenantId = selectedTenantId) => {
    if (!tenantId) return;
    const data = await apiCall(`/saas/v1/admin/tenants/${encodeURIComponent(tenantId)}`);
    setSelectedTenantId(tenantId);
    setTenantDetail(data);
  };

  const loadSubscriptions = async () => {
    const data = await apiCall("/saas/v1/admin/subscriptions?limit=200");
    setSubscriptions(data?.subscriptions || []);
  };

  const loadBillingAdmin = async () => {
    const [invoiceData, creditData, providerData] = await Promise.all([
      apiCall("/saas/v1/admin/billing/invoices?limit=120"),
      apiCall("/saas/v1/admin/billing/credits?limit=120"),
      apiCall("/saas/v1/admin/billing/providers/settings"),
    ]);
    setBillingInvoices(invoiceData?.invoices || []);
    setBillingCredits(creditData?.credits || []);
    const providers = providerData?.providers || [];
    setBillingProviders(providers);
    setBillingProviderForms((prev) => {
      const next = { ...prev };
      providers.forEach((provider) => {
        const key = String(provider?.provider || "").toLowerCase();
        if (key) next[key] = paymentProviderFormFromApi(provider);
      });
      return next;
    });
  };

  const loadIntelligence = async () => {
    const [catalogData, tenantsData, metricsData, modelsData, trainingData, mlopsData, realtimeData, gatingData] = await Promise.all([
      apiCall("/saas/v1/admin/intelligence/catalog"),
      apiCall("/saas/v1/admin/intelligence/tenants?limit=120"),
      apiCall("/saas/v1/admin/intelligence/model-metrics?limit=120"),
      apiCall("/saas/v1/admin/intelligence/models?limit=120"),
      apiCall("/saas/v1/admin/intelligence/training-dataset?limit=80"),
      apiCall("/saas/v1/admin/intelligence/mlops?limit=80"),
      apiCall("/saas/v1/admin/intelligence/realtime?limit=120"),
      apiCall("/saas/v1/admin/intelligence/premium-gating?limit=120"),
    ]);
    setIntelligenceCatalog(catalogData?.features || []);
    setIntelligenceTenants(tenantsData?.tenants || []);
    setIntelligenceMetrics(metricsData?.metrics || []);
    setIntelligenceModels(modelsData?.models || []);
    setIntelligenceTraining(trainingData || { readiness: {}, summaries: [], samples: [] });
    setIntelligenceMlops(mlopsData || { config: {}, jobs: [], artifacts: [], inference_runs: [], drift_snapshots: [], counts: {} });
    setIntelligenceRealtime(realtimeData?.realtime || { totals: {}, tenants: [], feature_keys: [] });
    setIntelligenceGating(gatingData?.gating || { features: [], tenants: [], plans: [], plan_feature_limits: [], provider_policies: [], provider_credentials: [], provider_costs: { totals: {}, ai: [], search: [] } });
  };

  const loadReliability = async () => {
    const data = await apiCall("/saas/v1/admin/reliability/overview");
    setReliability(data || null);
  };

  const loadTrust = async () => {
    const data = await apiCall("/saas/v1/admin/trust-center/overview");
    setTrustOverview(data || null);
  };

  const loadAudit = async () => {
    const data = await apiCall("/saas/v1/admin/audit?limit=120");
    setAudit(data?.audit || []);
  };

  const loadSecurity = async () => {
    const [securityData, complianceData] = await Promise.all([
      apiCall("/saas/v1/admin/auth/security"),
      apiCall("/saas/v1/admin/security/compliance"),
    ]);
    setAdminSecurity(securityData || null);
    setSecurityCompliance(complianceData || null);
  };

  const loadAdminUsers = async () => {
    const [platformData, tenantData] = await Promise.all([
      apiCall("/saas/v1/admin/users/platform"),
      apiCall("/saas/v1/admin/users/tenants?limit=300"),
    ]);
    setPlatformAdmins(platformData?.admins || []);
    setPlatformAdminRoles(platformData?.roles || Object.keys(PLATFORM_ROLE_LABELS));
    setTenantUsers(tenantData?.members || []);
    setTenantUserRoles(tenantData?.roles || Object.keys(TENANT_ROLE_LABELS));
  };

  const loadAdminNotifications = async () => {
    const [targetData, notificationData] = await Promise.all([
      apiCall("/saas/v1/admin/notifications/targets"),
      apiCall("/saas/v1/admin/notifications?limit=80"),
    ]);
    setNotificationTargets(targetData || { tenants: [], users: [], roles: [], smtp_configured: false });
    setAdminNotifications(notificationData?.notifications || []);
  };

  const loadQueues = async () => {
    const data = await apiCall("/saas/v1/admin/operations/queues");
    setQueues(data?.queues || null);
  };

  const loadHealth = async () => {
    const data = await apiCall("/saas/v1/admin/observability/health");
    setHealth(data || null);
    setQueues(data?.health?.queues || null);
    setDeadLetters(data?.dead_letters || []);
    setMetaErrors(data?.meta_error_history || []);
  };

  const loadDeadLetters = async () => {
    const data = await apiCall("/saas/v1/admin/observability/dead-letter?limit=120");
    setDeadLetters(data?.dead_letters || []);
  };

  const refreshActive = async (silent = false) => {
    if (!token) return;
    setLoading(true);
    try {
      if (activeView === "overview") await loadOverview();
      if (activeView === "tenants") { await Promise.all([loadTenants(), loadPlans(), loadFeatures()]); }
      if (activeView === "plans") { await Promise.all([loadPlans(), loadFeatures()]); }
      if (activeView === "subscriptions") await Promise.all([loadSubscriptions(), loadPlans()]);
      if (activeView === "billing") await Promise.all([loadBillingAdmin(), loadTenants()]);
      if (activeView === "users") await Promise.all([loadMe(), loadAdminUsers(), loadTenants()]);
      if (activeView === "notifications") await Promise.all([loadAdminNotifications(), loadTenants()]);
      if (activeView === "security") await loadSecurity();
      if (activeView === "intelligence") await loadIntelligence();
      if (activeView === "trust") await loadTrust();
      if (activeView === "performance") await loadReliability();
      if (activeView === "operations") await loadQueues();
      if (activeView === "observability") await loadHealth();
      if (activeView === "audit") await loadAudit();
      if (!silent) showStatus("Admin actualizado", "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const resetToken = new URLSearchParams(window.location.search).get("reset_token") || "";
    if (!resetToken) return;
    setAuthMode("reset");
    setPasswordReset((prev) => ({ ...prev, token: resetToken }));
  }, []);

  useEffect(() => {
    if (!token) return;
    loadMe().catch(() => clearSession());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  useEffect(() => {
    refreshActive(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, activeView]);

  useEffect(() => {
    if (activeView === "tenants" && selectedTenantId) loadTenantDetail(selectedTenantId).catch((err) => showStatus(String(err.message || err), "error"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedTenantId]);

  const submitLogin = async (event) => {
    event.preventDefault();
    try {
      const data = await apiCall("/saas/v1/admin/auth/login", { method: "POST", body: JSON.stringify({ ...login, captcha_token: loginCaptchaToken, captcha_provider: CAPTCHA_PROVIDER }) });
      if (data?.mfa_required) {
        setMfaChallenge(data);
        setMfaCode(data?.dev_otp || "");
        setAuthMode("mfa");
        showStatus(data?.email_sent ? "Codigo 2FA enviado al correo admin." : "Codigo 2FA requerido para Admin.", data?.email_sent || data?.dev_otp ? "ok" : "warn");
        return;
      }
      setSession(data);
      setLogin(emptyLogin());
      showStatus("Admin autenticado", "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      if (CAPTCHA_ENABLED) {
        setLoginCaptchaToken("");
        setLoginCaptchaReset((value) => value + 1);
      }
    }
  };

  const submitMfa = async (event) => {
    event.preventDefault();
    if (!mfaChallenge?.challenge_token) return showStatus("Desafio 2FA no disponible. Ingresa nuevamente.", "error");
    if (!mfaCode.trim()) return showStatus("Ingresa el codigo de seguridad.", "error");
    try {
      const data = await apiCall("/saas/v1/admin/auth/login/verify-otp", {
        method: "POST",
        body: JSON.stringify({ challenge_token: mfaChallenge.challenge_token, code: mfaCode }),
      });
      setSession(data);
      setLogin(emptyLogin());
      setAuthMode("login");
      showStatus("Admin autenticado con 2FA", "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    }
  };

  const submitPasswordRecovery = async (event) => {
    event.preventDefault();
    if (!passwordRecovery.email.trim()) return showStatus("Ingresa el correo admin", "error");
    try {
      const data = await apiCall("/saas/v1/auth/password/forgot", {
        method: "POST",
        body: JSON.stringify({ ...passwordRecovery, captcha_token: recoveryCaptchaToken, captcha_provider: CAPTCHA_PROVIDER }),
      });
      if (data?.dev_reset_token) {
        setPasswordReset((prev) => ({ ...prev, token: data.dev_reset_token }));
        setAuthMode("reset");
        showStatus("Token local generado. Define nueva clave.", "ok");
      } else {
        showStatus("Si la cuenta existe, enviaremos instrucciones de recuperacion.", "ok");
      }
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      if (CAPTCHA_ENABLED) {
        setRecoveryCaptchaToken("");
        setRecoveryCaptchaReset((value) => value + 1);
      }
    }
  };

  const submitPasswordReset = async (event) => {
    event.preventDefault();
    if (!passwordReset.token.trim()) return showStatus("Token requerido", "error");
    if (passwordReset.new_password.length < 8) return showStatus("La clave debe tener al menos 8 caracteres.", "error");
    if (passwordReset.new_password !== passwordReset.confirm_password) return showStatus("Las claves no coinciden.", "error");
    try {
      await apiCall("/saas/v1/auth/password/reset", {
        method: "POST",
        body: JSON.stringify({ token: passwordReset.token, new_password: passwordReset.new_password, captcha_token: resetCaptchaToken, captcha_provider: CAPTCHA_PROVIDER }),
      });
      setPasswordReset(emptyPasswordReset());
      setAuthMode("login");
      if (window.location.search.includes("reset_token=")) window.history.replaceState(null, "", window.location.pathname);
      showStatus("Clave actualizada. Ingresa al Admin.", "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      if (CAPTCHA_ENABLED) {
        setResetCaptchaToken("");
        setResetCaptchaReset((value) => value + 1);
      }
    }
  };

  const submitBootstrap = async (event) => {
    event.preventDefault();
    try {
      const data = await apiCall("/saas/v1/admin/auth/bootstrap", { method: "POST", body: JSON.stringify({ ...bootstrap, captcha_token: bootstrapCaptchaToken, captcha_provider: CAPTCHA_PROVIDER }) });
      setSession(data);
      showStatus("Admin local creado", "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      if (CAPTCHA_ENABLED) {
        setBootstrapCaptchaToken("");
        setBootstrapCaptchaReset((value) => value + 1);
      }
    }
  };

  const updateTenant = async (tenantId, patch) => {
    try {
      await apiCall(`/saas/v1/admin/tenants/${encodeURIComponent(tenantId)}`, { method: "PATCH", body: JSON.stringify(patch) });
      showStatus("Empresa actualizada", "ok");
      await loadTenants();
      await loadTenantDetail(tenantId);
    } catch (err) {
      showStatus(String(err.message || err), "error");
    }
  };

  const setTenantFeature = async (tenantId, featureKey, enabled) => {
    try {
      await apiCall(`/saas/v1/admin/tenants/${encodeURIComponent(tenantId)}/feature-flags`, {
        method: "POST",
        body: JSON.stringify({ feature_key: featureKey, is_enabled: enabled, source: "admin", notes: "Cambio desde Scentra Admin" }),
      });
      showStatus("Feature flag actualizada", "ok");
      await loadTenantDetail(tenantId);
    } catch (err) {
      showStatus(String(err.message || err), "error");
    }
  };

  const impersonateTenant = async (tenantId) => {
    try {
      const data = await apiCall(`/saas/v1/admin/tenants/${encodeURIComponent(tenantId)}/impersonate`, {
        method: "POST",
        body: JSON.stringify({ role: "admin", reason: "Soporte desde Scentra Admin" }),
      });
      const url = `${CLIENT_APP_BASE}/#support_token=${encodeURIComponent(data.access_token)}`;
      window.open(url, "_blank", "noopener,noreferrer");
      showStatus(`Acceso de soporte generado para ${data.tenant_name}`, "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    }
  };

  const savePlan = async (event) => {
    event.preventDefault();
    try {
      const payload = { ...planForm, price_monthly_cents: Number(planForm.price_monthly_cents || 0) };
      await apiCall("/saas/v1/admin/plans", { method: "POST", body: JSON.stringify(payload) });
      showStatus("Plan guardado", "ok");
      setPlanForm(emptyPlan());
      await loadPlans();
    } catch (err) {
      showStatus(String(err.message || err), "error");
    }
  };

  const editPlan = (plan) => setPlanForm({
    ...emptyPlan(),
    ...plan,
    feature_flags_json: { ...DEFAULT_FEATURES, ...(plan.feature_flags_json || {}) },
    ai_agent_limits: { ...emptyPlan().ai_agent_limits, ...(plan.ai_agent_limits || {}) },
  });

  const patchSubscription = async (tenantId, patch) => {
    try {
      await apiCall(`/saas/v1/admin/subscriptions/${encodeURIComponent(tenantId)}`, { method: "PATCH", body: JSON.stringify(patch) });
      showStatus("Suscripcion actualizada", "ok");
      await loadSubscriptions();
    } catch (err) {
      showStatus(String(err.message || err), "error");
    }
  };

  const applyBillingCredit = async (event) => {
    event.preventDefault();
    try {
      await apiCall("/saas/v1/admin/billing/credits", { method: "POST", body: JSON.stringify({ ...billingForm, amount: Number(billingForm.amount || 0) }) });
      showStatus("Credito aplicado", "ok");
      await loadBillingAdmin();
    } catch (err) {
      showStatus(String(err.message || err), "error");
    }
  };

  const syncBillingLifecycle = async () => {
    try {
      const data = await apiCall("/saas/v1/admin/billing/lifecycle/sync", { method: "POST" });
      showStatus(`Billing sync: ${JSON.stringify(data.result || {})}`, "ok");
      await Promise.all([loadBillingAdmin(), loadSubscriptions(), loadTenants()]);
    } catch (err) {
      showStatus(String(err.message || err), "error");
    }
  };

  const updateBillingProviderForm = (provider, patch) => {
    setBillingProviderForms((prev) => ({
      ...prev,
      [provider]: { ...(prev[provider] || PAYMENT_PROVIDER_DEFAULT_FORM), ...patch },
    }));
  };

  const saveBillingProvider = async (provider) => {
    try {
      setBillingProviderBusy(provider);
      const payload = billingProviderForms[provider] || {};
      await apiCall(`/saas/v1/admin/billing/providers/${encodeURIComponent(provider)}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
      showStatus(`${PAYMENT_PROVIDER_META[provider]?.name || provider} actualizado`, "ok");
      await loadBillingAdmin();
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setBillingProviderBusy("");
    }
  };

  const setIntelligenceFeature = async (tenantId, featureKey, patch) => {
    try {
      await apiCall(`/saas/v1/admin/intelligence/tenants/${encodeURIComponent(tenantId)}/features`, {
        method: "PATCH",
        body: JSON.stringify({ feature_key: featureKey, ...patch }),
      });
      showStatus("Feature AI actualizada", "ok");
      await loadIntelligence();
    } catch (err) {
      showStatus(String(err.message || err), "error");
    }
  };

  const setIntelligencePlanFeature = async (planCode, featureKey, patch) => {
    try {
      await apiCall(`/saas/v1/admin/intelligence/plans/${encodeURIComponent(planCode)}/features`, {
        method: "PATCH",
        body: JSON.stringify({ feature_key: featureKey, ...patch }),
      });
      showStatus("Cuota de plan AI actualizada", "ok");
      await Promise.all([loadIntelligence(), loadPlans()]);
    } catch (err) {
      showStatus(String(err.message || err), "error");
    }
  };

  const saveProviderPolicy = async (event) => {
    event.preventDefault();
    try {
      await apiCall("/saas/v1/admin/intelligence/provider-policies", {
        method: "PATCH",
        body: JSON.stringify({
          ...providerPolicyForm,
          input_cost_cents_per_1k: Number(providerPolicyForm.input_cost_cents_per_1k || 0),
          output_cost_cents_per_1k: Number(providerPolicyForm.output_cost_cents_per_1k || 0),
          request_cost_cents: Number(providerPolicyForm.request_cost_cents || 0),
          monthly_request_quota: Number(providerPolicyForm.monthly_request_quota || 0),
          monthly_cost_limit_cents: Number(providerPolicyForm.monthly_cost_limit_cents || 0),
        }),
      });
      showStatus("Politica de proveedor AI actualizada", "ok");
      setProviderPolicyForm((prev) => ({ ...PROVIDER_POLICY_DEFAULT, provider_category: prev.provider_category, provider_code: prev.provider_code }));
      await loadIntelligence();
    } catch (err) {
      showStatus(String(err.message || err), "error");
    }
  };

  const recomputeIntelligenceMetrics = async () => {
    try {
      const data = await apiCall("/saas/v1/admin/intelligence/model-metrics/recompute", {
        method: "POST",
        body: JSON.stringify({ window_key: "90d" }),
      });
      showStatus(`Metricas recalculadas: ${number((data?.metrics || []).length)}`, "ok");
      await loadIntelligence();
    } catch (err) {
      showStatus(String(err.message || err), "error");
    }
  };

  const refreshRealtimeMetrics = async () => {
    try {
      const data = await apiCall("/saas/v1/admin/intelligence/realtime/metrics/refresh", { method: "POST" });
      showStatus(`Realtime snapshots: ${number(data?.snapshots_written || 0)}`, "ok");
      await loadIntelligence();
    } catch (err) {
      showStatus(String(err.message || err), "error");
    }
  };

  const updateIntelligenceModel = async (model, patch) => {
    try {
      await apiCall(`/saas/v1/admin/intelligence/models/${encodeURIComponent(model.model_key)}`, {
        method: "PATCH",
        body: JSON.stringify({
          status: model.status || "active",
          stage: model.stage || "production",
          shadow_mode: Boolean(model.shadow_mode),
          rollout_mode: model.rollout_mode || "production",
          traffic_percent: Number(model.traffic_percent ?? 100),
          min_labeled_count: Number(model.min_labeled_count ?? 10),
          min_accuracy: Number(model.min_accuracy ?? 70),
          max_drift_score: Number(model.max_drift_score ?? 25),
          promotion_status: model.promotion_status || "approved",
          reason: "Cambio desde Scentra Admin",
          ...patch,
        }),
      });
      showStatus("Modelo predictivo actualizado", "ok");
      await loadIntelligence();
    } catch (err) {
      showStatus(String(err.message || err), "error");
    }
  };

  const registerIntelligenceModel = async (event) => {
    event.preventDefault();
    try {
      await apiCall("/saas/v1/admin/intelligence/models", {
        method: "POST",
        body: JSON.stringify({
          ...intelligenceModelForm,
          traffic_percent: Number(intelligenceModelForm.traffic_percent || 0),
          min_labeled_count: 10,
          min_accuracy: 70,
          max_drift_score: 25,
          reason: "Registro desde Scentra Admin",
        }),
      });
      showStatus("Modelo predictivo registrado", "ok");
      setIntelligenceModelForm((prev) => ({ ...prev, model_key: "", artifact_uri: "", rollout_mode: "shadow", traffic_percent: 0, promotion_status: "pending_review" }));
      await loadIntelligence();
    } catch (err) {
      showStatus(String(err.message || err), "error");
    }
  };

  const runSyntheticMlTraining = async (event) => {
    event.preventDefault();
    try {
      await apiCall("/saas/v1/admin/intelligence/ml-training/synthetic", {
        method: "POST",
        body: JSON.stringify({
          ...intelligenceTrainForm,
          sample_size: Number(intelligenceTrainForm.sample_size || 1000),
          seed: Number(intelligenceTrainForm.seed || 42),
        }),
      });
      showStatus("Entrenamiento ML solicitado. Artifact registrado en shadow si el servicio ML esta habilitado.", "ok");
      setIntelligenceTrainForm((prev) => ({ ...prev, model_key: "" }));
      await loadIntelligence();
    } catch (err) {
      showStatus(String(err.message || err), "error");
    }
  };

  const generateAutoLabels = async () => {
    try {
      const data = await apiCall("/saas/v1/admin/intelligence/auto-labels/generate", {
        method: "POST",
        body: JSON.stringify({
          ...intelligenceDataForm,
          limit: Number(intelligenceDataForm.limit || 1000),
        }),
      });
      showStatus(`Auto-labels generados: ${number(data?.total || 0)}`, "ok");
      await loadIntelligence();
    } catch (err) {
      showStatus(String(err.message || err), "error");
    }
  };

  const recomputeFeaturePipelines = async () => {
    try {
      const data = await apiCall("/saas/v1/admin/intelligence/feature-pipelines/recompute", {
        method: "POST",
        body: JSON.stringify({
          ...intelligenceDataForm,
          limit: Number(intelligenceDataForm.limit || 1000),
        }),
      });
      showStatus(`Feature pipelines: ${number((data?.runs || []).length)} runs`, "ok");
      await loadIntelligence();
    } catch (err) {
      showStatus(String(err.message || err), "error");
    }
  };

  const buildMlDataset = async () => {
    try {
      const data = await apiCall("/saas/v1/admin/intelligence/ml-datasets/build", {
        method: "POST",
        body: JSON.stringify({
          tenant_id: intelligenceTrainForm.tenant_id,
          task_type: intelligenceTrainForm.task_type,
          dataset_key: intelligenceTrainForm.dataset_key,
          version: intelligenceTrainForm.version,
          window_key: intelligenceTrainForm.window_key,
          min_samples: Number(intelligenceTrainForm.min_samples || 50),
          include_global: Boolean(intelligenceTrainForm.include_global),
          include_internal_demo: Boolean(intelligenceTrainForm.include_internal_demo),
        }),
      });
      showStatus(`Dataset ML listo: ${number(data?.dataset?.sample_count || 0)} muestras`, "ok");
      await loadIntelligence();
    } catch (err) {
      showStatus(String(err.message || err), "error");
    }
  };

  const runAutoLabelMlTraining = async () => {
    try {
      await apiCall("/saas/v1/admin/intelligence/ml-training/autolabel", {
        method: "POST",
        body: JSON.stringify({
          ...intelligenceTrainForm,
          min_samples: Number(intelligenceTrainForm.min_samples || 50),
          seed: Number(intelligenceTrainForm.seed || 42),
          include_global: Boolean(intelligenceTrainForm.include_global),
          include_internal_demo: Boolean(intelligenceTrainForm.include_internal_demo),
        }),
      });
      showStatus("Entrenamiento autolabel solicitado. El modelo queda en shadow/pending_review.", "ok");
      setIntelligenceTrainForm((prev) => ({ ...prev, model_key: "" }));
      await loadIntelligence();
    } catch (err) {
      showStatus(String(err.message || err), "error");
    }
  };
  const downloadAdminInvoice = async (invoice) => {
    try {
      const invoiceId = invoice?.id || "";
      if (!invoiceId) return;
      const name = invoice.invoice_number || invoice.provider_invoice_id || invoiceId;
      await downloadApiFile(`/saas/v1/admin/billing/invoices/${encodeURIComponent(invoiceId)}/pdf`, `${name}.pdf`);
      showStatus("Factura PDF generada", "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    }
  };

  const processQueue = async (kind) => {
    const endpointMap = {
      webhooks: "webhooks",
      triggers: "triggers",
      outbound: "outbound",
      ai: "ai",
      remarketing: "remarketing",
      agents: "agents",
      intelligence: "intelligence",
      reliability: "reliability",
      metaTokens: "meta-tokens",
    };
    const endpoint = endpointMap[kind] || "outbound";
    try {
      const data = await apiCall(`/saas/v1/admin/operations/${endpoint}/process?limit=50`, { method: "POST" });
      showStatus(`Procesado: ${JSON.stringify(data.result)}`, "ok");
      await loadQueues();
      if (activeView === "observability") await loadHealth();
      if (activeView === "intelligence") await loadIntelligence();
      if (activeView === "trust") await loadTrust();
      if (activeView === "performance") await loadReliability();
    } catch (err) {
      showStatus(String(err.message || err), "error");
    }
  };

  const recordReliabilitySnapshot = async () => {
    try {
      const data = await apiCall("/saas/v1/admin/reliability/snapshot", { method: "POST" });
      showStatus(`Snapshot reliability: ${data?.snapshot?.status || "ok"}`, "ok");
      await loadReliability();
    } catch (err) {
      showStatus(String(err.message || err), "error");
    }
  };

  const runReliabilityDrill = async (drillType) => {
    try {
      const data = await apiCall(`/saas/v1/admin/reliability/drills/${encodeURIComponent(drillType)}`, { method: "POST" });
      showStatus(`Drill ${drillType}: ${data?.drill?.status || "ok"}`, "ok");
      await loadReliability();
    } catch (err) {
      showStatus(String(err.message || err), "error");
    }
  };

  const runRetentionDryRun = async () => {
    try {
      const data = await apiCall("/saas/v1/admin/reliability/retention/run?dry_run=true&include_disabled=true", { method: "POST" });
      showStatus(`Retention dry-run: ${number(data?.result?.total_matched || 0)} candidatos`, "ok");
      await loadReliability();
    } catch (err) {
      showStatus(String(err.message || err), "error");
    }
  };

  const syncDeadLetters = async () => {
    try {
      const data = await apiCall("/saas/v1/admin/observability/dead-letter/sync?limit=250", { method: "POST" });
      showStatus(`Dead-letter sincronizado: ${data?.result?.synced || 0}`, "ok");
      await Promise.all([loadHealth(), loadDeadLetters()]);
    } catch (err) {
      showStatus(String(err.message || err), "error");
    }
  };

  const updateAdminTwoFactor = async (enabled) => {
    try {
      const data = await apiCall("/saas/v1/admin/auth/security/2fa", {
        method: "PATCH",
        body: JSON.stringify({ enabled, method: "email_otp" }),
      });
      setAdminSecurity(data || null);
      showStatus(enabled ? "2FA admin activado." : "2FA admin desactivado.", "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    }
  };

  const saveAdminProfile = async () => {
    try {
      const data = await apiCall("/saas/v1/admin/auth/profile", {
        method: "PATCH",
        body: JSON.stringify(adminProfileForm),
      });
      setAdminProfileForm((prev) => ({ ...prev, current_password: "" }));
      rememberUiTimeZone(data?.user?.profile_json?.timezone || adminProfileForm.timezone);
      setMe((prev) => ({ ...(prev || {}), email: data?.user?.email || prev?.email, full_name: data?.user?.full_name || prev?.full_name, profile_json: data?.user?.profile_json || prev?.profile_json || {} }));
      showStatus("Perfil admin actualizado", "ok");
      await loadMe();
    } catch (err) { showStatus(String(err.message || err), "error"); }
  };

  const changeAdminPassword = async () => {
    if (adminPasswordForm.new_password !== adminPasswordForm.confirm_password) return showStatus("La confirmacion de clave no coincide.", "error");
    try {
      await apiCall("/saas/v1/admin/auth/password/change", {
        method: "POST",
        body: JSON.stringify({ current_password: adminPasswordForm.current_password, new_password: adminPasswordForm.new_password }),
      });
      setAdminPasswordForm({ current_password: "", new_password: "", confirm_password: "" });
      showStatus("Clave admin actualizada", "ok");
    } catch (err) { showStatus(String(err.message || err), "error"); }
  };

  const createPlatformAdmin = async () => {
    setUserBusy("platform-create");
    try {
      await apiCall("/saas/v1/admin/users/platform", { method: "POST", body: JSON.stringify(platformAdminForm) });
      setPlatformAdminForm({ email: "", full_name: "", password: "", platform_role: "support", status: "active", notes: "", send_email: true });
      showStatus("Administrador creado o actualizado", "ok");
      await loadAdminUsers();
    } catch (err) { showStatus(String(err.message || err), "error"); }
    finally { setUserBusy(""); }
  };

  const patchPlatformAdmin = async (userId, patch) => {
    setUserBusy(userId);
    try {
      await apiCall(`/saas/v1/admin/users/platform/${encodeURIComponent(userId)}`, { method: "PATCH", body: JSON.stringify(patch) });
      showStatus("Administrador actualizado", "ok");
      await loadAdminUsers();
    } catch (err) { showStatus(String(err.message || err), "error"); }
    finally { setUserBusy(""); }
  };

  const createTenantUser = async () => {
    setUserBusy("tenant-create");
    try {
      await apiCall("/saas/v1/admin/users/tenants", { method: "POST", body: JSON.stringify(tenantUserForm) });
      setTenantUserForm((prev) => ({ ...prev, email: "", full_name: "", password: "", role: "agent" }));
      showStatus("Usuario de empresa creado o actualizado", "ok");
      await loadAdminUsers();
    } catch (err) { showStatus(String(err.message || err), "error"); }
    finally { setUserBusy(""); }
  };

  const patchTenantUser = async (membershipId, patch) => {
    setUserBusy(membershipId);
    try {
      await apiCall(`/saas/v1/admin/users/tenants/${encodeURIComponent(membershipId)}`, { method: "PATCH", body: JSON.stringify(patch) });
      showStatus("Usuario de empresa actualizado", "ok");
      await loadAdminUsers();
    } catch (err) { showStatus(String(err.message || err), "error"); }
    finally { setUserBusy(""); }
  };

  const draftNotification = async () => {
    setNotificationBusy("draft");
    try {
      const data = await apiCall("/saas/v1/admin/notifications/draft-ai", { method: "POST", body: JSON.stringify(notificationDraftForm) });
      setNotificationForm((prev) => ({ ...prev, title: data?.title || prev.title, body: data?.body || prev.body, ai_assisted: Boolean(data?.ai_assisted) }));
      showStatus("Borrador preparado", "ok");
    } catch (err) { showStatus(String(err.message || err), "error"); }
    finally { setNotificationBusy(""); }
  };

  const sendAdminNotification = async () => {
    setNotificationBusy("send");
    try {
      await apiCall("/saas/v1/admin/notifications", { method: "POST", body: JSON.stringify(notificationForm) });
      setNotificationForm({ title: "", body: "", severity: "info", category: "system", audience_type: "selected", tenant_ids: [], user_ids: [], roles: [], email_copy: true, ai_assisted: false });
      showStatus("Notificación enviada", "ok");
      await loadAdminNotifications();
    } catch (err) { showStatus(String(err.message || err), "error"); }
    finally { setNotificationBusy(""); }
  };

  const downloadAuditCsv = async () => {
    try {
      await downloadApiFile("/saas/v1/admin/audit/export.csv?limit=2000", "scentra-admin-audit.csv");
      showStatus("Auditoria exportada.", "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    }
  };

  const resolveDeadLetter = async (eventId) => {
    try {
      await apiCall(`/saas/v1/admin/observability/dead-letter/${encodeURIComponent(eventId)}/resolve`, { method: "POST" });
      showStatus("Evento marcado como resuelto", "ok");
      await Promise.all([loadHealth(), loadDeadLetters()]);
    } catch (err) {
      showStatus(String(err.message || err), "error");
    }
  };

  const retryDeadLetter = async (eventId) => {
    try {
      const data = await apiCall(`/saas/v1/admin/observability/dead-letter/${encodeURIComponent(eventId)}/retry?process_now=true`, { method: "POST" });
      showStatus(`Reintento enviado: ${JSON.stringify(data.process_result || data.result || {})}`, "ok");
      await Promise.all([loadHealth(), loadDeadLetters()]);
    } catch (err) {
      showStatus(String(err.message || err), "error");
    }
  };

  if (!token || !me) {
    return (
      <main className="admin-auth">
        <section className="auth-card glass-card">
          <div className="brand-block">
            <BrandGlyph />
            <div><img className="admin-wordmark" src={SCENTRA_WHITE_LOGO_URL} alt="Scentra" /><h1>Scentra Admin</h1><p>Centro de control interno para planes, clientes y operacion.</p></div>
          </div>
          {status ? <div className={`status ${statusTone}`}>{status}</div> : null}
          {authMode === "login" ? (
            <form className="auth-grid" onSubmit={submitLogin}>
              <label>Correo<input value={login.email} autoComplete="email" onChange={(event) => setLogin((prev) => ({ ...prev, email: event.target.value }))} /></label>
              <label>Clave<input type="password" value={login.password} autoComplete="current-password" onChange={(event) => setLogin((prev) => ({ ...prev, password: event.target.value }))} /></label>
              <TurnstileChallenge onToken={setLoginCaptchaToken} resetKey={loginCaptchaReset} />
              <button type="submit" className="primary">Entrar al Admin</button>
              <button type="button" onClick={() => setAuthMode("forgot")}>Recuperar clave admin</button>
            </form>
          ) : authMode === "mfa" ? (
            <form className="auth-grid" onSubmit={submitMfa}>
              <label>Codigo 2FA<input value={mfaCode} autoComplete="one-time-code" inputMode="numeric" onChange={(event) => setMfaCode(event.target.value)} /></label>
              <small>Enviado a {mfaChallenge?.email_hint || "tu correo admin"}. {mfaChallenge?.dev_otp ? `OTP local: ${mfaChallenge.dev_otp}` : ""}</small>
              <button type="submit" className="primary">Verificar codigo</button>
              <button type="button" onClick={() => { setMfaChallenge(null); setMfaCode(""); setAuthMode("login"); }}>Volver al login</button>
            </form>
          ) : authMode === "forgot" ? (
            <form className="auth-grid" onSubmit={submitPasswordRecovery}>
              <label>Correo admin<input value={passwordRecovery.email} autoComplete="email" onChange={(event) => setPasswordRecovery((prev) => ({ ...prev, email: event.target.value }))} /></label>
              <TurnstileChallenge onToken={setRecoveryCaptchaToken} resetKey={recoveryCaptchaReset} />
              <button type="submit" className="primary">Enviar recuperacion</button>
              <button type="button" onClick={() => setAuthMode("login")}>Volver al login</button>
              <button type="button" onClick={() => setAuthMode("reset")}>Ya tengo token</button>
            </form>
          ) : (
            <form className="auth-grid" onSubmit={submitPasswordReset}>
              <label>Token de recuperacion<input value={passwordReset.token} autoComplete="one-time-code" onChange={(event) => setPasswordReset((prev) => ({ ...prev, token: event.target.value }))} /></label>
              <label>Nueva clave<input type="password" value={passwordReset.new_password} autoComplete="new-password" onChange={(event) => setPasswordReset((prev) => ({ ...prev, new_password: event.target.value }))} /></label>
              <label>Confirmar clave<input type="password" value={passwordReset.confirm_password} autoComplete="new-password" onChange={(event) => setPasswordReset((prev) => ({ ...prev, confirm_password: event.target.value }))} /></label>
              <TurnstileChallenge onToken={setResetCaptchaToken} resetKey={resetCaptchaReset} />
              <button type="submit" className="primary">Actualizar clave</button>
              <button type="button" onClick={() => setAuthMode("login")}>Volver al login</button>
            </form>
          )}
          {ADMIN_BOOTSTRAP_ENABLED ? (
            <details className="bootstrap-box">
              <summary>Crear primer admin local</summary>
              <form className="auth-grid" onSubmit={submitBootstrap}>
                <label>Correo<input value={bootstrap.email} onChange={(event) => setBootstrap((prev) => ({ ...prev, email: event.target.value }))} /></label>
                <label>Clave<input type="password" value={bootstrap.password} onChange={(event) => setBootstrap((prev) => ({ ...prev, password: event.target.value }))} /></label>
                <label>Nombre<input value={bootstrap.full_name} onChange={(event) => setBootstrap((prev) => ({ ...prev, full_name: event.target.value }))} /></label>
                <label>Rol<select value={bootstrap.platform_role} onChange={(event) => setBootstrap((prev) => ({ ...prev, platform_role: event.target.value }))}><option value="superadmin">superadmin</option><option value="platform_admin">platform_admin</option><option value="billing_admin">billing_admin</option><option value="support">support</option></select></label>
                <TurnstileChallenge onToken={setBootstrapCaptchaToken} resetKey={bootstrapCaptchaReset} />
                <button type="submit">Bootstrap local</button>
              </form>
            </details>
          ) : null}
        </section>
        <ErrorDialog notice={errorDialog} onClose={() => setErrorDialog(null)} />
      </main>
    );
  }

  return (
    <div className="admin-shell">
      <aside className="admin-sidebar glass-card">
        <div className="brand-block compact"><BrandGlyph /><div><strong>Scentra Admin</strong><small>{me.platform_role}</small></div></div>
        <nav>{VIEWS.map(([id, label]) => <button key={id} type="button" className={activeView === id ? "active" : ""} onClick={() => setActiveView(id)}>{label}</button>)}</nav>
        <div className="operator-card"><small>Operador</small><strong>{me.email}</strong><button type="button" onClick={clearSession}>Salir</button></div>
      </aside>

      <main className="admin-content">
        <header className="topbar glass-card">
          <div><p className="eyebrow">Control interno</p><h1>{VIEWS.find(([id]) => id === activeView)?.[1]}</h1></div>
          <div className="top-actions"><button type="button" onClick={() => refreshActive(false)}>{loading ? "Actualizando..." : "Recargar"}</button></div>
        </header>
        {status ? <div className={`status floating ${statusTone}`}>{status}</div> : null}
        <ErrorDialog notice={errorDialog} onClose={() => setErrorDialog(null)} />

        {activeView === "overview" ? <Overview overview={overview} /> : null}
        {activeView === "tenants" ? (
          <TenantsView
            tenants={tenants}
            plans={plans}
            features={features}
            tenantSearch={tenantSearch}
            tenantStatus={tenantStatus}
            tenantPlan={tenantPlan}
            selectedTenantId={selectedTenantId}
            tenantDetail={tenantDetail}
            setTenantSearch={setTenantSearch}
            setTenantStatus={setTenantStatus}
            setTenantPlan={setTenantPlan}
            loadTenants={loadTenants}
            selectTenant={setSelectedTenantId}
            updateTenant={updateTenant}
            setTenantFeature={setTenantFeature}
            impersonateTenant={impersonateTenant}
          />
        ) : null}
        {activeView === "plans" ? <PlansView plans={plans} features={features} planForm={planForm} setPlanForm={setPlanForm} savePlan={savePlan} editPlan={editPlan} /> : null}
        {activeView === "subscriptions" ? <SubscriptionsView subscriptions={subscriptions} plans={plans} patchSubscription={patchSubscription} /> : null}
        {activeView === "billing" ? <BillingView tenants={tenants} invoices={billingInvoices} credits={billingCredits} billingForm={billingForm} setBillingForm={setBillingForm} applyBillingCredit={applyBillingCredit} syncBillingLifecycle={syncBillingLifecycle} downloadInvoice={downloadAdminInvoice} providers={billingProviders} providerForms={billingProviderForms} updateProviderForm={updateBillingProviderForm} saveProvider={saveBillingProvider} providerBusy={billingProviderBusy} /> : null}
        {activeView === "users" ? <UsersAdminView me={me} activeTab={usersAdminTab} setActiveTab={setUsersAdminTab} tenantUserSearch={tenantUserSearch} setTenantUserSearch={setTenantUserSearch} profileForm={adminProfileForm} setProfileForm={setAdminProfileForm} passwordForm={adminPasswordForm} setPasswordForm={setAdminPasswordForm} saveProfile={saveAdminProfile} changePassword={changeAdminPassword} platformAdmins={platformAdmins} platformRoles={platformAdminRoles} platformForm={platformAdminForm} setPlatformForm={setPlatformAdminForm} createPlatformAdmin={createPlatformAdmin} patchPlatformAdmin={patchPlatformAdmin} tenantUsers={tenantUsers} tenantRoles={tenantUserRoles} tenantForm={tenantUserForm} setTenantForm={setTenantUserForm} tenants={tenants} createTenantUser={createTenantUser} patchTenantUser={patchTenantUser} busy={userBusy} /> : null}
        {activeView === "notifications" ? <NotificationsAdminView targets={notificationTargets} notifications={adminNotifications} form={notificationForm} setForm={setNotificationForm} draftForm={notificationDraftForm} setDraftForm={setNotificationDraftForm} targetSearch={notificationTargetSearch} setTargetSearch={setNotificationTargetSearch} draftNotification={draftNotification} sendNotification={sendAdminNotification} busy={notificationBusy} /> : null}
        {activeView === "security" ? <SecurityView security={adminSecurity} compliance={securityCompliance} updateAdminTwoFactor={updateAdminTwoFactor} downloadAuditCsv={downloadAuditCsv} /> : null}
        {activeView === "intelligence" ? <IntelligenceView tenants={intelligenceTenants} catalog={intelligenceCatalog} metrics={intelligenceMetrics} models={intelligenceModels} training={intelligenceTraining} mlops={intelligenceMlops} realtime={intelligenceRealtime} gating={intelligenceGating} providerPolicyForm={providerPolicyForm} setProviderPolicyForm={setProviderPolicyForm} saveProviderPolicy={saveProviderPolicy} setIntelligencePlanFeature={setIntelligencePlanFeature} dataForm={intelligenceDataForm} setDataForm={setIntelligenceDataForm} generateAutoLabels={generateAutoLabels} recomputeFeaturePipelines={recomputeFeaturePipelines} buildMlDataset={buildMlDataset} trainForm={intelligenceTrainForm} setTrainForm={setIntelligenceTrainForm} runTraining={runSyntheticMlTraining} runAutoLabelTraining={runAutoLabelMlTraining} modelForm={intelligenceModelForm} setModelForm={setIntelligenceModelForm} registerModel={registerIntelligenceModel} setIntelligenceFeature={setIntelligenceFeature} processQueue={processQueue} recomputeMetrics={recomputeIntelligenceMetrics} refreshRealtimeMetrics={refreshRealtimeMetrics} updateModel={updateIntelligenceModel} /> : null}
        {activeView === "trust" ? <TrustAdminView overview={trustOverview} /> : null}
        {activeView === "performance" ? <PerformanceView reliability={reliability} processQueue={processQueue} recordSnapshot={recordReliabilitySnapshot} runDrill={runReliabilityDrill} runRetentionDryRun={runRetentionDryRun} /> : null}
        {activeView === "operations" ? <OperationsView queues={queues} processQueue={processQueue} /> : null}
        {activeView === "observability" ? <ObservabilityView health={health} deadLetters={deadLetters} metaErrors={metaErrors} processQueue={processQueue} syncDeadLetters={syncDeadLetters} resolveDeadLetter={resolveDeadLetter} retryDeadLetter={retryDeadLetter} /> : null}
        {activeView === "audit" ? <AuditView audit={audit} /> : null}
      </main>
    </div>
  );
}

function Overview({ overview }) {
  const tenants = overview?.tenants || {};
  const usage = Object.fromEntries((overview?.usage || []).map((item) => [item.metric_code, item.total]));
  return (
    <section className="stack">
      <div className="metric-grid">
        <Metric title="Empresas" value={tenants.total} hint={`${number(tenants.active)} activas`} tone="mint" />
        <Metric title="Trial" value={tenants.trial} hint="En evaluacion" tone="blue" />
        <Metric title="Past due" value={tenants.past_due} hint="Revisar pagos" tone="amber" />
        <Metric title="Suspendidas" value={tenants.suspended} hint="Bloqueadas" tone="rose" />
        <Metric title="Mensajes mes" value={usage.messages_in || 0} hint={`${number(usage.outbound_messages_queued || 0)} outbound`} tone="violet" />
      </div>
      <div className="dashboard-grid">
        <article className="panel glass-card"><div className="panel-head"><h2>Planes activos</h2><span>{overview?.period_yyyymm}</span></div><div className="list">{(overview?.plans || []).map((item) => <div key={item.plan_code}><strong>{item.plan_code}</strong><span>{number(item.tenants)} empresas</span></div>)}</div></article>
        <article className="panel glass-card"><div className="panel-head"><h2>Colas</h2><span>runtime</span></div><QueueSummary queues={overview?.queues} /></article>
      </div>
    </section>
  );
}

function TrustAdminView({ overview }) {
  const aggregate = overview?.aggregate || {};
  const tenants = overview?.tenants || [];
  const recentAudits = overview?.recent_audits || [];
  const riskyTenants = tenants.filter((item) => Number(item.counts?.open_risks || 0) || Number(item.counts?.open_incidents || 0));
  return (
    <section className="stack">
      <div className="metric-grid">
        <Metric title="Tenants revisados" value={aggregate.tenants || tenants.length} hint="scope admin" tone="blue" />
        <Metric title="Riesgos abiertos" value={aggregate.open_risks || 0} hint={`${number(aggregate.high_risks || 0)} altos`} tone={Number(aggregate.high_risks || 0) ? "rose" : "amber"} />
        <Metric title="Incidentes abiertos" value={aggregate.open_incidents || 0} hint="governance AI" tone={Number(aggregate.open_incidents || 0) ? "rose" : "mint"} />
        <Metric title="Politicas" value={aggregate.policies || 0} hint={`${number(aggregate.model_cards || 0)} model cards`} tone="violet" />
      </div>
      <div className="dashboard-grid">
        <article className="panel glass-card">
          <div className="panel-head"><h2>Empresas con atencion</h2><span>{number(riskyTenants.length)}</span></div>
          <div className="table compact">
            {riskyTenants.slice(0, 24).map((item) => (
              <div className="row" key={item.tenant.id}>
                <span><strong>{item.tenant.name}</strong><small>{item.tenant.plan_code || "plan"} / {item.tenant.industry_code || "general"}</small></span>
                <span><mark className={statusClass(item.tenant.status)}>{item.tenant.status}</mark></span>
                <span>{number(item.counts?.open_risks || 0)} riesgos</span>
                <span>{number(item.counts?.open_incidents || 0)} incidentes</span>
              </div>
            ))}
            {!riskyTenants.length ? <p className="empty">Sin riesgos o incidentes abiertos en el snapshot actual.</p> : null}
          </div>
        </article>
        <article className="panel glass-card">
          <div className="panel-head"><h2>Senales auditadas</h2><span>control-plane</span></div>
          <div className="table compact">
            {tenants.slice(0, 24).map((item) => (
              <div className="row" key={item.tenant.id}>
                <span><strong>{item.tenant.name}</strong></span>
                <span>{number(item.source_signals?.agents || 0)} agentes</span>
                <span>{number(item.source_signals?.workflows || 0)} workflows</span>
                <span>{number(item.source_signals?.models || 0)} modelos</span>
                <span>{number(item.source_signals?.tools || 0)} tools</span>
              </div>
            ))}
            {!tenants.length ? <p className="empty">Sin tenants para mostrar.</p> : null}
          </div>
        </article>
      </div>
      <article className="panel glass-card">
        <div className="panel-head"><h2>Auditoria reciente AI Governance</h2><span>{number(recentAudits.length)}</span></div>
        <div className="table compact">
          {recentAudits.slice(0, 40).map((item) => (
            <div className="row" key={item.id}>
              <span><strong>{item.event_type}</strong><small>{item.tenant_name || item.tenant_id}</small></span>
              <span>{item.entity_type}</span>
              <span><mark className={statusClass(item.severity)}>{item.severity}</mark></span>
              <span>{item.summary || "-"}</span>
              <span>{compactDateTimeLabel(item.created_at)}</span>
            </div>
          ))}
          {!recentAudits.length ? <p className="empty">Aun no hay auditoria de Trust AI.</p> : null}
        </div>
      </article>
    </section>
  );
}

function Metric({ title, value, hint, tone }) {
  const renderedValue = typeof value === "number" || /^\d+(\.\d+)?$/.test(String(value || "")) ? number(value) : value;
  return <article className={`metric-card ${tone}`}><span>{title}</span><strong>{renderedValue}</strong><small>{hint}</small></article>;
}

function TenantsView(props) {
  const {
    tenants, plans, features, tenantSearch, tenantStatus, tenantPlan, selectedTenantId, tenantDetail,
    setTenantSearch, setTenantStatus, setTenantPlan, loadTenants, selectTenant, updateTenant, setTenantFeature,
    impersonateTenant,
  } = props;
  const detail = tenantDetail || {};
  const selected = detail.tenant || {};
  const owner = detail.owner || {};
  const limits = detail.billing?.effective_limits || detail.billing?.plan?.limits || {};
  const usage = detail.billing?.usage || {};
  const effectiveFeatures = detail.billing?.features || {};
  const featureSources = detail.billing?.feature_sources || {};
  const featureMap = Object.fromEntries((detail.feature_flags || []).map((item) => [item.feature_key, item]));
  const planName = (code) => plans.find((plan) => plan.plan_code === code)?.display_name || code || "Sin plan";
  const industryName = (code) => INDUSTRY_OPTIONS.find((item) => item[0] === code)?.[1] || code || "General";
  return (
    <section className="tenant-layout">
      <article className="panel glass-card">
        <div className="panel-head"><h2>Empresas</h2><span>{number(tenants.length)}</span></div>
        <div className="filter-bar">
          <input value={tenantSearch} onChange={(event) => setTenantSearch(event.target.value)} placeholder="Buscar empresa..." />
          <select value={tenantStatus} onChange={(event) => setTenantStatus(event.target.value)}><option value="all">Todos</option>{TENANT_STATUSES.map((item) => <option key={item} value={item}>{item}</option>)}</select>
          <select value={tenantPlan} onChange={(event) => setTenantPlan(event.target.value)}><option value="all">Todos los planes</option>{plans.map((plan) => <option key={plan.plan_code} value={plan.plan_code}>{plan.plan_code}</option>)}</select>
          <button type="button" onClick={loadTenants}>Filtrar</button>
        </div>
        <div className="tenant-list">{tenants.map((tenant) => <button key={tenant.id} type="button" className={tenant.id === selectedTenantId ? "active" : ""} onClick={() => selectTenant(tenant.id)}><strong>{tenant.name}</strong><span>{tenant.owner_name || tenant.owner_email || "Owner sin nombre"}</span><mark className={statusClass(tenant.status)}>{tenant.status}</mark><small>{planName(tenant.plan_code)} / {industryName(tenant.industry_code)} / {number(tenant.used_monthly_messages)} msgs</small></button>)}</div>
      </article>
      <article className="panel glass-card tenant-detail">
        <div className="panel-head"><h2>{selected.name || "Selecciona empresa"}</h2><span>{owner.full_name || owner.email || "Cliente"}</span></div>
        {selected.id ? (
          <>
            <div className="admin-actions">
              {TENANT_STATUSES.map((item) => <button key={item} type="button" className={selected.status === item ? "primary" : ""} onClick={() => updateTenant(selected.id, { status: item, subscription_status: item === "past_due" ? "past_due" : item === "suspended" ? "suspended" : item === "cancelled" ? "cancelled" : "active" })}>{item}</button>)}
              <button type="button" onClick={() => impersonateTenant(selected.id)}>Abrir como soporte</button>
            </div>
            <div className="owner-card">
              <span>Cliente principal</span>
              <strong>{owner.full_name || owner.email || "Sin owner visible"}</strong>
              <small>{owner.email || "Sin email"}</small>
            </div>
            <div className="form-grid two">
              <label>Plan<select value={selected.plan_code || ""} onChange={(event) => updateTenant(selected.id, { plan_code: event.target.value, subscription_status: "active" })}>{plans.map((plan) => <option key={plan.plan_code} value={plan.plan_code}>{plan.display_name || plan.plan_code}</option>)}</select></label>
              <label>Nombre<input defaultValue={selected.name || ""} onBlur={(event) => event.target.value !== selected.name && updateTenant(selected.id, { name: event.target.value })} /></label>
              <label>Industria<select value={selected.industry_code || "general"} onChange={(event) => updateTenant(selected.id, { industry_code: event.target.value })}>{INDUSTRY_OPTIONS.map(([code, label]) => <option key={code} value={code}>{label}</option>)}</select></label>
              <label>Pack aplicado<input readOnly value={selected.vertical_pack_applied_at ? compactDateTimeLabel(selected.vertical_pack_applied_at) : "Sin aplicar"} /></label>
            </div>
            <div className="usage-box">
              <div><strong>{number(usage.used_monthly_messages)}</strong><span>mensajes / {number(limits.max_monthly_messages)}</span><div className="meter"><span style={{ width: `${pct(usage.used_monthly_messages, limits.max_monthly_messages)}%` }} /></div></div>
              <div><strong>{number(usage.used_agents)}</strong><span>usuarios / {number(limits.max_agents)}</span></div>
              <div><strong>{number(usage.used_integrations)}</strong><span>integraciones / {number(limits.max_integrations)}</span></div>
            </div>
            <h3>Feature flags</h3>
            <div className="flag-grid">{features.map((feature) => <label key={feature.key} className="switch"><input type="checkbox" checked={Boolean(effectiveFeatures[feature.key])} onChange={(event) => setTenantFeature(selected.id, feature.key, event.target.checked)} /><span><strong>{feature.label}</strong><small>{featureMap[feature.key]?.source || featureSources[feature.key] || "plan/default"}</small></span></label>)}</div>
            <h3>Usuarios</h3>
            <div className="table compact">{(detail.members || []).map((member) => <div className="row" key={member.id}><span>{member.email}</span><span>{member.role}</span><span>{member.is_active ? "activo" : "inactivo"}</span></div>)}</div>
          </>
        ) : <p className="empty">Sin empresa seleccionada.</p>}
      </article>
    </section>
  );
}

function PlansView({ plans, features, planForm, setPlanForm, savePlan, editPlan }) {
  const updateFeature = (key, value) => setPlanForm((prev) => ({ ...prev, feature_flags_json: { ...(prev.feature_flags_json || {}), [key]: value } }));
  const updateAgentLimit = (key, value) => setPlanForm((prev) => ({ ...prev, ai_agent_limits: { ...(prev.ai_agent_limits || emptyPlan().ai_agent_limits), [key]: value } }));
  const agentTypesText = (planForm.ai_agent_limits?.allowed_agent_types_json || []).join(", ");
  return (
    <section className="plans-layout">
      <article className="panel glass-card">
        <div className="panel-head"><h2>Planes</h2><span>{number(plans.length)}</span></div>
        <div className="plan-grid">{plans.map((plan) => <button key={plan.plan_code} type="button" className="plan-card" onClick={() => editPlan(plan)}><strong>{plan.display_name || plan.plan_code}</strong><span>{money(plan.price_monthly_cents, plan.currency)} / mes</span><small>{number(plan.max_monthly_messages)} mensajes / {number(plan.tenants_count)} empresas</small><mark className={plan.is_active ? "ok" : "danger"}>{plan.is_active ? "activo" : "inactivo"}</mark></button>)}</div>
      </article>
      <article className="panel glass-card">
        <div className="panel-head"><h2>Crear / editar plan</h2><button type="button" onClick={() => setPlanForm(emptyPlan())}>Nuevo</button></div>
        <form className="plan-form" onSubmit={savePlan}>
          <div className="form-grid two"><label>Codigo<input value={planForm.plan_code} onChange={(event) => setPlanForm((prev) => ({ ...prev, plan_code: event.target.value }))} /></label><label>Nombre<input value={planForm.display_name} onChange={(event) => setPlanForm((prev) => ({ ...prev, display_name: event.target.value }))} /></label></div>
          <div className="form-grid four">
            {["max_agents", "max_monthly_messages", "max_integrations", "max_storage_gb", "max_campaigns", "max_broadcasts", "max_ai_tokens", "price_monthly_cents"].map((key) => <label key={key}>{key}<input type="number" value={planForm[key]} onChange={(event) => setPlanForm((prev) => ({ ...prev, [key]: Number(event.target.value || 0) }))} /></label>)}
          </div>
          <div className="form-grid two"><label>Moneda<input value={planForm.currency} onChange={(event) => setPlanForm((prev) => ({ ...prev, currency: event.target.value }))} /></label><label>Orden<input type="number" value={planForm.sort_order} onChange={(event) => setPlanForm((prev) => ({ ...prev, sort_order: Number(event.target.value || 0) }))} /></label></div>
          <div className="section-chip">Agentes IA por plan</div>
          <div className="form-grid four">
            {["max_ai_agents", "max_active_ai_agents", "max_memory_archives"].map((key) => <label key={key}>{key}<input type="number" value={planForm.ai_agent_limits?.[key] ?? 0} onChange={(event) => updateAgentLimit(key, Number(event.target.value || 0))} /></label>)}
            <label>Builder<select value={planForm.ai_agent_limits?.builder_enabled ? "true" : "false"} onChange={(event) => updateAgentLimit("builder_enabled", event.target.value === "true")}><option value="true">Activo</option><option value="false">Inactivo</option></select></label>
          </div>
          <label>Tipos de agente permitidos<textarea rows={3} value={agentTypesText} onChange={(event) => updateAgentLimit("allowed_agent_types_json", event.target.value.split(",").map((item) => item.trim()).filter(Boolean))} /></label>
          <label>Notas de agentes IA<textarea rows={2} value={planForm.ai_agent_limits?.notes || ""} onChange={(event) => updateAgentLimit("notes", event.target.value)} /></label>
          <div className="section-chip">Modulos incluidos</div>
          <div className="flag-grid">{features.map((feature) => <label className="switch" key={feature.key}><input type="checkbox" checked={Boolean(planForm.feature_flags_json?.[feature.key])} onChange={(event) => updateFeature(feature.key, event.target.checked)} /><span><strong>{feature.label}</strong><small>{feature.key}</small></span></label>)}</div>
          <label className="check"><input type="checkbox" checked={planForm.is_public} onChange={(event) => setPlanForm((prev) => ({ ...prev, is_public: event.target.checked }))} /> Publico</label>
          <label className="check"><input type="checkbox" checked={planForm.is_active} onChange={(event) => setPlanForm((prev) => ({ ...prev, is_active: event.target.checked }))} /> Activo</label>
          <button type="submit" className="primary">Guardar plan</button>
        </form>
      </article>
    </section>
  );
}

function SubscriptionsView({ subscriptions, plans, patchSubscription }) {
  return (
    <section className="panel glass-card">
      <div className="panel-head"><h2>Suscripciones</h2><span>{number(subscriptions.length)}</span></div>
      <div className="table">{subscriptions.map((sub) => <div className="row six" key={sub.id}><span><strong>{sub.tenant_name}</strong><small>{sub.owner_name || sub.owner_email || "Owner sin nombre"}</small></span><span>{sub.provider}</span><span><mark className={statusClass(sub.status)}>{sub.status}</mark></span><span>{plans.find((plan) => plan.plan_code === sub.plan_code)?.display_name || sub.plan_code}</span><span>{sub.current_period_end || "-"}</span><span className="row-actions"><select defaultValue={sub.plan_code} onChange={(event) => patchSubscription(sub.tenant_id, { status: "active", plan_code: event.target.value })}>{plans.map((plan) => <option key={plan.plan_code} value={plan.plan_code}>{plan.display_name || plan.plan_code}</option>)}</select>{SUB_STATUSES.map((status) => <button key={status} type="button" onClick={() => patchSubscription(sub.tenant_id, { status, plan_code: sub.plan_code })}>{status}</button>)}</span></div>)}</div>
    </section>
  );
}

function BillingProviderSettings({ providers, providerForms, updateProviderForm, saveProvider, providerBusy }) {
  const providerMap = Object.fromEntries((providers || []).map((item) => [item.provider, item]));
  const renderField = (providerKey, mode, field, label) => {
    const formKey = `${mode}_${field}`;
    const form = providerForms?.[providerKey] || PAYMENT_PROVIDER_DEFAULT_FORM;
    const provider = providerMap[providerKey] || {};
    const storedValue = provider?.[mode]?.[field] || "";
    const isPublic = field === "public_key";
    return (
      <label key={formKey}>{label}
        <input
          type={isPublic ? "text" : "password"}
          value={form[formKey] || ""}
          placeholder={storedValue ? `${storedValue} guardado` : `Pega ${label.toLowerCase()}`}
          onChange={(event) => updateProviderForm(providerKey, { [formKey]: event.target.value })}
        />
      </label>
    );
  };
  return (
    <article className="panel glass-card billing-provider-panel">
      <div className="panel-head">
        <div>
          <h2>Pasarelas de pago</h2>
          <span>Configura prueba/produccion sin entrar a Coolify</span>
        </div>
      </div>
      <PaymentLogoStrip />
      <div className="provider-settings-grid">
        {Object.entries(PAYMENT_PROVIDER_META).map(([providerKey, meta]) => {
          const provider = providerMap[providerKey] || {};
          const form = providerForms?.[providerKey] || PAYMENT_PROVIDER_DEFAULT_FORM;
          return (
            <form className="payment-provider-card" key={providerKey} onSubmit={(event) => { event.preventDefault(); saveProvider(providerKey); }}>
              <div className="payment-provider-head">
                <div>
                  <strong>{meta.name}</strong>
                  <small>{meta.description}</small>
                </div>
                <mark className={provider.checkout_ready ? "ok" : provider.is_enabled ? "warn" : "neutral"}>{provider.checkout_ready ? "listo" : provider.is_enabled ? "incompleto" : "apagado"}</mark>
              </div>
              <div className="payment-provider-webhook">
                <span>Webhook para copiar en {meta.name}</span>
                <code>{provider.webhook_url || "-"}</code>
              </div>
              <label>Titulo visible en checkout
                <input value={form.title || ""} onChange={(event) => updateProviderForm(providerKey, { title: event.target.value })} />
              </label>
              <div className="payment-switch-grid">
                <label className="check-row"><input type="checkbox" checked={Boolean(form.is_enabled)} onChange={(event) => updateProviderForm(providerKey, { is_enabled: event.target.checked })} /><span><strong>Habilitar {meta.name}</strong><small>Permite crear checkouts con esta pasarela.</small></span></label>
                <label className="check-row"><input type="checkbox" checked={Boolean(form.test_mode)} onChange={(event) => updateProviderForm(providerKey, { test_mode: event.target.checked })} /><span><strong>Modo prueba</strong><small>Usa credenciales sandbox/test para ensayos.</small></span></label>
                <label className="check-row"><input type="checkbox" checked={Boolean(form.is_default)} onChange={(event) => updateProviderForm(providerKey, { is_default: event.target.checked })} /><span><strong>Predeterminado</strong><small>Se usa cuando el cliente deja proveedor automatico.</small></span></label>
                <label className="check-row"><input type="checkbox" checked={Boolean(form.debug_logging)} onChange={(event) => updateProviderForm(providerKey, { debug_logging: event.target.checked })} /><span><strong>Registro debug</strong><small>Solo para diagnostico temporal.</small></span></label>
              </div>
              <div className="payment-credential-grid">
                <div className="payment-credential-box">
                  <span className="section-chip">Prueba</span>
                  {meta.fields.map(([field, label]) => renderField(providerKey, "test", field, label))}
                </div>
                <div className="payment-credential-box">
                  <span className="section-chip">Produccion</span>
                  {meta.fields.map(([field, label]) => renderField(providerKey, "live", field, label))}
                </div>
              </div>
              <div className="payment-provider-foot">
                <small>{provider.source === "environment" ? "Usando respaldo de variables del servidor hasta guardar aqui." : "Guardado cifrado en la base de datos."}</small>
                <button type="submit" className="primary" disabled={providerBusy === providerKey}>{providerBusy === providerKey ? "Guardando..." : `Guardar ${meta.name}`}</button>
              </div>
            </form>
          );
        })}
      </div>
    </article>
  );
}

function BillingView({ tenants, invoices, credits, billingForm, setBillingForm, applyBillingCredit, syncBillingLifecycle, downloadInvoice, providers, providerForms, updateProviderForm, saveProvider, providerBusy }) {
  const selectedTenant = tenants.find((tenant) => tenant.id === billingForm.tenant_id);
  return (
    <section className="stack">
      <BillingProviderSettings providers={providers} providerForms={providerForms} updateProviderForm={updateProviderForm} saveProvider={saveProvider} providerBusy={providerBusy} />
      <div className="dashboard-grid wide-left">
      <article className="panel glass-card">
        <div className="panel-head"><h2>Facturacion</h2><button type="button" onClick={syncBillingLifecycle}>Sincronizar lifecycle</button></div>
        <div className="table observability-table">
          {invoices.length ? invoices.map((item) => (
            <div className="row channel-row" key={item.id}>
              <span><strong>{item.tenant_name}</strong><small>{item.invoice_number || item.provider_invoice_id || item.id}</small></span>
              <span><mark className={statusClass(item.status)}>{item.status}</mark></span>
              <span>{item.provider}</span>
              <span>{item.plan_code}</span>
              <span>{money(item.total_cents, item.currency)}</span>
              <span className="row-actions"><small>{item.paid_at || item.due_at || item.created_at}</small><button type="button" onClick={() => downloadInvoice(item)}>PDF</button></span>
            </div>
          )) : <p className="empty">Sin facturas registradas todavia.</p>}
        </div>
      </article>
      <article className="panel glass-card">
        <div className="panel-head"><h2>Creditos manuales</h2><span>{selectedTenant?.name || "elige empresa"}</span></div>
        <form className="auth-grid" onSubmit={applyBillingCredit}>
          <label>Empresa<select value={billingForm.tenant_id} onChange={(event) => setBillingForm((prev) => ({ ...prev, tenant_id: event.target.value }))}><option value="">Seleccionar...</option>{tenants.map((tenant) => <option key={tenant.id} value={tenant.id}>{tenant.name}</option>)}</select></label>
          <label>Metrica<select value={billingForm.metric_code} onChange={(event) => setBillingForm((prev) => ({ ...prev, metric_code: event.target.value }))}><option value="monthly_messages">Mensajes mensuales</option><option value="messages">Bolsa mensajes</option><option value="ai_tokens">Tokens IA</option></select></label>
          <label>Cantidad<input type="number" value={billingForm.amount} onChange={(event) => setBillingForm((prev) => ({ ...prev, amount: Number(event.target.value || 0) }))} /></label>
          <label>Expira<input type="datetime-local" value={billingForm.expires_at} onChange={(event) => setBillingForm((prev) => ({ ...prev, expires_at: event.target.value }))} /></label>
          <label>Motivo<textarea rows={2} value={billingForm.reason} onChange={(event) => setBillingForm((prev) => ({ ...prev, reason: event.target.value }))} /></label>
          <button type="submit" className="primary" disabled={!billingForm.tenant_id}>Aplicar credito</button>
        </form>
        <div className="table compact">
          {credits.slice(0, 8).map((item) => <div className="row" key={item.id}><span>{item.tenant_name}</span><span>{item.metric_code}</span><span>{number(item.remaining_amount)} / {number(item.amount)}</span></div>)}
        </div>
      </article>
      </div>
    </section>
  );
}

function IntelligenceView({ tenants, catalog, metrics, models, training, mlops, realtime, gating, providerPolicyForm, setProviderPolicyForm, saveProviderPolicy, setIntelligencePlanFeature, dataForm, setDataForm, generateAutoLabels, recomputeFeaturePipelines, buildMlDataset, trainForm, setTrainForm, runTraining, runAutoLabelTraining, modelForm, setModelForm, registerModel, setIntelligenceFeature, processQueue, recomputeMetrics, refreshRealtimeMetrics, updateModel }) {
  const fullFeatures = (catalog || []).filter((item) => item.key !== "intelligence_demo");
  const phase24Features = (gating?.features || []).length ? gating.features : (catalog || []).filter((item) => PHASE24_FEATURE_KEYS.includes(item.key));
  const featureLabel = (key) => (catalog || []).find((item) => item.key === key)?.label || key;
  const percentLabel = (value) => (value === null || value === undefined ? "-" : `${Number(value || 0).toFixed(1)}%`);
  const readiness = training?.readiness || {};
  const mlConfig = mlops?.config || {};
  const realtimeTotals = realtime?.totals || {};
  const realtimeTenants = realtime?.tenants || [];
  const gatingCosts = gating?.provider_costs || {};
  const gatingTotals = gatingCosts?.totals || {};
  const planLimitMap = Object.fromEntries((gating?.plan_feature_limits || []).map((item) => [`${item.plan_code}:${item.feature_key}`, item]));
  const providerOptions = Array.from(new Set([...(gating?.provider_policies || []).map((item) => item.provider_code), "google", "mistral", "openrouter", "kimi", "groq", "tavily", "brave_search", "serpapi"].filter(Boolean)));
  const phase24CostUsd = Number(gatingTotals.ai_estimated_cost_usd || 0) + Number(gatingTotals.search_estimated_cost_usd || 0);
  const phase24TenantRows = gating?.tenants || [];
  const phase24PlanRows = gating?.plans || [];
  const providerPolicies = gating?.provider_policies || [];
  const providerCredentials = gating?.provider_credentials || [];
  const providerScopeChoices = providerPolicyForm.scope_type === "tenant" ? phase24TenantRows : providerPolicyForm.scope_type === "plan" ? phase24PlanRows : [];
  const providerScopeValue = providerPolicyForm.scope_type === "global" ? "" : providerPolicyForm.scope_id;
  return (
    <section className="stack">
      <div className="metric-grid">
        <Metric title="Tenants" value={tenants.length} hint="gestion AI premium" tone="violet" />
        <Metric title="Predicciones 30d" value={tenants.reduce((sum, item) => sum + Number(item.predictions_30d || 0), 0)} hint="todas las empresas" tone="blue" />
        <Metric title="Recomendaciones" value={tenants.reduce((sum, item) => sum + Number(item.open_recommendations || 0), 0)} hint="abiertas" tone="amber" />
        <Metric title="Uso mes" value={tenants.reduce((sum, item) => sum + Number(item.intelligence_usage_month || 0), 0)} hint="requests predictivos" tone="mint" />
        <Metric title="Modelos" value={(models || []).length} hint="registry y rollout" tone="blue" />
        <Metric title="Labels ML" value={readiness.auto_label_count || readiness.labeled_count || 0} hint={`${number(readiness.auto_label_ready_groups || readiness.ready_groups || 0)} grupos ready`} tone="mint" />
      </div>
      <article className="panel glass-card">
        <div className="panel-head"><h2>AI Real-Time Intelligence Layer</h2><button type="button" onClick={refreshRealtimeMetrics}>Snapshot realtime</button><span>{compactDateTimeLabel(realtime?.generated_at)}</span></div>
        <div className="metric-grid realtime-admin-grid">
          <Metric title="Eventos 15m" value={realtimeTotals.events_15m || 0} hint="eventos Intelligence" tone="blue" />
          <Metric title="Predicciones 1h" value={realtimeTotals.predictions_1h || 0} hint="live scoring" tone="violet" />
          <Metric title="Recomendaciones" value={realtimeTotals.open_recommendations || 0} hint="abiertas" tone="amber" />
          <Metric title="Sesiones live" value={realtimeTotals.active_sessions || 0} hint="usuarios conectados" tone="mint" />
        </div>
        <div className="table observability-table">
          {realtimeTenants.slice(0, 12).map((tenant) => (
            <div className="row intelligence-row realtime-admin-row" key={tenant.tenant_id}>
              <span><strong>{tenant.tenant_name}</strong><small>{tenant.tenant_slug} / {tenant.plan_code}</small></span>
              <span><mark className={statusClass(tenant.status)}>{tenant.status}</mark></span>
              <span>{number(tenant.events_15m)}<small>eventos 15m</small></span>
              <span>{number(tenant.predictions_1h)}<small>predicciones 1h</small></span>
              <span>{number(tenant.open_recommendations)}<small>recomendaciones</small></span>
              <span>{number(tenant.active_sessions)}<small>sesiones</small></span>
              <span className="feature-stack">
                {(realtime?.feature_keys || []).map((key) => {
                  const item = tenant.realtime_features?.[key] || {};
                  return <small key={key}>{featureLabel(key)}: {item.mode || "off"}</small>;
                })}
              </span>
            </div>
          ))}
          {!realtimeTenants.length ? <p className="empty">Sin datos realtime todavia. Activa demo/full o genera eventos Intelligence.</p> : null}
        </div>
      </article>
      <article className="panel glass-card">
        <div className="panel-head"><h2>Phase 24.8-24.10 Admin & Premium Gating</h2><span>tenants, planes, proveedores, costos, observabilidad y rollout</span></div>
        <div className="metric-grid realtime-admin-grid">
          <Metric title="Tenants Phase 24" value={phase24TenantRows.filter((item) => Number(item.phase24_summary?.enabled || 0) > 0).length} hint={`${number(phase24TenantRows.length)} inspeccionados`} tone="violet" />
          <Metric title="AI requests mes" value={gatingTotals.ai_requests || 0} hint="AI Gateway" tone="blue" />
          <Metric title="Search requests mes" value={gatingTotals.search_requests || 0} hint="web/image search" tone="mint" />
          <Metric title="Costo estimado" value={`USD ${phase24CostUsd.toFixed(4)}`} hint="segun politicas Admin" tone="amber" />
        </div>
        <div className="section-chip">Gating Phase 24 por tenant</div>
        <div className="table observability-table">
          {phase24TenantRows.length ? phase24TenantRows.slice(0, 12).map((tenant) => {
            const featureMap = Object.fromEntries((tenant.phase24_features || []).map((item) => [item.key, item]));
            const summary = tenant.phase24_summary || {};
            return (
              <div className="row intelligence-row phase24-row" key={`phase24-${tenant.id}`}>
                <span><strong>{tenant.name}</strong><small>{tenant.slug} / {tenant.plan_code}</small></span>
                <span><mark className={statusClass(tenant.status)}>{tenant.status}</mark></span>
                <span>{number(summary.enabled)}<small>features on</small></span>
                <span>{number(summary.full)} / {number(summary.demo)}<small>full / demo</small></span>
                <span>{number(summary.quota_used)} / {number(summary.quota_monthly)}<small>cuota mes</small></span>
                <span>{number(tenant.intelligence_usage_month)}<small>uso AI mes</small></span>
                <span className="feature-stack">
                  {phase24Features.map((feature) => {
                    const item = featureMap[feature.key] || {};
                    const mode = item.mode || "disabled";
                    return (
                      <label key={`${tenant.id}-${feature.key}-${item.quota_monthly || feature.default_quota_monthly || 0}`} className="mini-control">
                        <small>{featureLabel(feature.key)}</small>
                        <select
                          value={mode}
                          onChange={(event) => setIntelligenceFeature(tenant.id, feature.key, { mode: event.target.value, enabled: event.target.value !== "disabled", quota_monthly: item.quota_monthly || feature.default_quota_monthly || 0, source: "admin", notes: "Phase 24 tenant gating" })}
                        >
                          <option value="disabled">off</option>
                          {feature.demo_allowed || item.mode === "demo" ? <option value="demo" disabled={!feature.demo_allowed}>demo</option> : null}
                          <option value="full">full</option>
                        </select>
                        <input
                          type="number"
                          min="0"
                          defaultValue={item.quota_monthly || feature.default_quota_monthly || 0}
                          onBlur={(event) => setIntelligenceFeature(tenant.id, feature.key, { mode, enabled: mode !== "disabled", quota_monthly: Number(event.target.value || 0), source: "admin", notes: "Phase 24 tenant quota" })}
                        />
                      </label>
                    );
                  })}
                </span>
              </div>
            );
          }) : <p className="empty">Sin tenants cargados para Phase 24.</p>}
        </div>
        <div className="section-chip">Cuotas Phase 24 por plan</div>
        <div className="table observability-table">
          {phase24PlanRows.length ? phase24PlanRows.map((plan) => (
            <div className="row intelligence-row phase24-row" key={`plan-${plan.plan_code}`}>
              <span><strong>{plan.display_name || plan.plan_code}</strong><small>{plan.plan_code}</small></span>
              <span><mark className={plan.is_active ? "ok" : "neutral"}>{plan.is_active ? "active" : "inactive"}</mark></span>
              <span>{money(plan.price_monthly_cents, plan.currency)}<small>precio base</small></span>
              <span>{number((gating?.plan_feature_limits || []).filter((item) => item.plan_code === plan.plan_code && item.enabled).length)}<small>limites on</small></span>
              <span>{number(plan.sort_order)}<small>orden</small></span>
              <span>{plan.currency || "USD"}<small>moneda</small></span>
              <span className="feature-stack">
                {phase24Features.map((feature) => {
                  const item = planLimitMap[`${plan.plan_code}:${feature.key}`] || {};
                  const mode = item.mode || "disabled";
                  return (
                    <label key={`${plan.plan_code}-${feature.key}-${item.quota_monthly || feature.default_quota_monthly || 0}`} className="mini-control">
                      <small>{featureLabel(feature.key)}</small>
                      <select
                        value={mode}
                        onChange={(event) => setIntelligencePlanFeature(plan.plan_code, feature.key, { mode: event.target.value, enabled: event.target.value !== "disabled", quota_monthly: item.quota_monthly || feature.default_quota_monthly || 0, notes: "Phase 24 plan gating" })}
                      >
                        <option value="disabled">off</option>
                        <option value="demo">demo</option>
                        <option value="full">full</option>
                      </select>
                      <input
                        type="number"
                        min="0"
                        defaultValue={item.quota_monthly || feature.default_quota_monthly || 0}
                        onBlur={(event) => setIntelligencePlanFeature(plan.plan_code, feature.key, { mode, enabled: mode !== "disabled", quota_monthly: Number(event.target.value || 0), notes: "Phase 24 plan quota" })}
                      />
                    </label>
                  );
                })}
              </span>
            </div>
          )) : <p className="empty">Sin planes cargados para Phase 24.</p>}
        </div>
      </article>
      <article className="panel glass-card">
        <div className="panel-head"><h2>Provider Policies & Cost Controls</h2><span>AI, busqueda y TTS</span></div>
        <form className="form-grid four" onSubmit={saveProviderPolicy}>
          <label>Scope<select value={providerPolicyForm.scope_type} onChange={(event) => setProviderPolicyForm((prev) => ({ ...prev, scope_type: event.target.value, scope_id: "" }))}><option value="global">global</option><option value="plan">plan</option><option value="tenant">tenant</option></select></label>
          <label>Scope ID<select value={providerScopeValue} disabled={providerPolicyForm.scope_type === "global"} onChange={(event) => setProviderPolicyForm((prev) => ({ ...prev, scope_id: event.target.value }))}><option value="">{providerPolicyForm.scope_type === "global" ? "global" : "Seleccionar..."}</option>{providerScopeChoices.map((item) => <option key={item.id || item.plan_code} value={item.id || item.plan_code}>{item.name || item.display_name || item.plan_code}</option>)}</select></label>
          <label>Categoria<select value={providerPolicyForm.provider_category} onChange={(event) => setProviderPolicyForm((prev) => ({ ...prev, provider_category: event.target.value }))}><option value="ai">ai</option><option value="search">search</option><option value="tts">tts</option></select></label>
          <label>Proveedor<select value={providerPolicyForm.provider_code} onChange={(event) => setProviderPolicyForm((prev) => ({ ...prev, provider_code: event.target.value }))}>{providerOptions.map((code) => <option key={code} value={code}>{code}</option>)}</select></label>
          <label>Modelo<input value={providerPolicyForm.model_id} placeholder="opcional" onChange={(event) => setProviderPolicyForm((prev) => ({ ...prev, model_id: event.target.value }))} /></label>
          <label>Estado<select value={providerPolicyForm.enabled ? "true" : "false"} onChange={(event) => setProviderPolicyForm((prev) => ({ ...prev, enabled: event.target.value === "true" }))}><option value="true">enabled</option><option value="false">disabled</option></select></label>
          <label>Input cents/1k<input type="number" min="0" step="0.000001" value={providerPolicyForm.input_cost_cents_per_1k} onChange={(event) => setProviderPolicyForm((prev) => ({ ...prev, input_cost_cents_per_1k: event.target.value }))} /></label>
          <label>Output cents/1k<input type="number" min="0" step="0.000001" value={providerPolicyForm.output_cost_cents_per_1k} onChange={(event) => setProviderPolicyForm((prev) => ({ ...prev, output_cost_cents_per_1k: event.target.value }))} /></label>
          <label>Request cents<input type="number" min="0" step="0.000001" value={providerPolicyForm.request_cost_cents} onChange={(event) => setProviderPolicyForm((prev) => ({ ...prev, request_cost_cents: event.target.value }))} /></label>
          <label>Quota requests<input type="number" min="0" value={providerPolicyForm.monthly_request_quota} onChange={(event) => setProviderPolicyForm((prev) => ({ ...prev, monthly_request_quota: event.target.value }))} /></label>
          <label>Cost limit cents<input type="number" min="0" value={providerPolicyForm.monthly_cost_limit_cents} onChange={(event) => setProviderPolicyForm((prev) => ({ ...prev, monthly_cost_limit_cents: event.target.value }))} /></label>
          <label>Moneda<input value={providerPolicyForm.currency} onChange={(event) => setProviderPolicyForm((prev) => ({ ...prev, currency: event.target.value.toUpperCase() }))} /></label>
          <label>Notas<textarea rows={2} value={providerPolicyForm.notes} onChange={(event) => setProviderPolicyForm((prev) => ({ ...prev, notes: event.target.value }))} /></label>
          <button type="submit" className="primary" disabled={!providerPolicyForm.provider_code}>Guardar policy</button>
        </form>
        <div className="section-chip">Politicas activas</div>
        <div className="table observability-table">
          {providerPolicies.length ? providerPolicies.slice(0, 18).map((policy) => (
            <div className="row provider-policy-row" key={policy.id || `${policy.scope_type}-${policy.scope_id}-${policy.provider_category}-${policy.provider_code}-${policy.model_id}`}>
              <span><strong>{policy.provider_code}</strong><small>{policy.provider_category} / {policy.model_id || "*"}</small></span>
              <span>{policy.scope_type}:{policy.scope_id || "*"}</span>
              <span><mark className={policy.enabled ? "ok" : "warn"}>{policy.enabled ? "enabled" : "disabled"}</mark></span>
              <span>{number(policy.monthly_request_quota)}<small>quota req</small></span>
              <span>{number(policy.monthly_cost_limit_cents)}<small>cost cents</small></span>
              <span>{number(policy.input_cost_cents_per_1k)} / {number(policy.output_cost_cents_per_1k)} / {number(policy.request_cost_cents)}<small>in/out/req</small></span>
              <span className="row-actions"><button type="button" onClick={() => setProviderPolicyForm({ ...PROVIDER_POLICY_DEFAULT, ...policy, metadata_json: policy.metadata_json || {} })}>Editar</button></span>
            </div>
          )) : <p className="empty">Sin politicas de proveedor configuradas.</p>}
        </div>
        <div className="section-chip">Credenciales y costos estimados del mes</div>
        <section className="dashboard-grid">
          <div className="table compact">
            {providerCredentials.length ? providerCredentials.slice(0, 10).map((item) => (
              <div className="row" key={`${item.tenant_id}-${item.category}-${item.provider_code}`}>
                <span><strong>{item.tenant_name}</strong><small>{item.plan_code}</small></span>
                <span>{item.category}/{item.provider_code}</span>
                <span>{number(item.secrets_ready)} / {number(item.credentials)}<small>secrets</small></span>
              </div>
            )) : <p className="empty">Sin credenciales AI/search/TTS registradas.</p>}
          </div>
          <div className="table compact">
            {[...(gatingCosts.ai || []), ...(gatingCosts.search || [])].slice(0, 10).map((item, index) => (
              <div className="row" key={`${item.tenant_id}-${item.provider_code}-${item.model || item.search_type}-${index}`}>
                <span><strong>{item.tenant_name}</strong><small>{item.model || item.search_type || "*"}</small></span>
                <span>{item.provider_code}</span>
                <span>USD {Number(item.estimated_cost_usd || 0).toFixed(4)}<small>{number(item.requests)} req</small></span>
              </div>
            ))}
            {!((gatingCosts.ai || []).length || (gatingCosts.search || []).length) ? <p className="empty">Sin uso AI/search del mes para costeo.</p> : null}
          </div>
        </section>
      </article>
      <article className="panel glass-card">
        <div className="panel-head"><h2>AI & Predictive Features Management</h2><button type="button" onClick={() => processQueue("intelligence")}>Procesar Intelligence</button><span>{number(fullFeatures.length)} features premium</span></div>
        <div className="table observability-table">
          {tenants.length ? tenants.map((tenant) => {
            const features = tenant.intelligence?.features || [];
            const featureMap = Object.fromEntries(features.map((item) => [item.key, item]));
            return (
              <div className="row intelligence-row" key={tenant.id}>
                <span><strong>{tenant.name}</strong><small>{tenant.slug} / {tenant.plan_code}</small></span>
                <span><mark className={statusClass(tenant.status)}>{tenant.status}</mark></span>
                <span>{number(tenant.predictions_30d)}<small>predicciones 30d</small></span>
                <span>{number(tenant.open_recommendations)}<small>recomendaciones</small></span>
                <span>{number(tenant.intelligence_usage_month)}<small>uso mes</small></span>
                <span className="row-actions">
                  <select
                    value={featureMap.intelligence_demo?.mode || "disabled"}
                    onChange={(event) => setIntelligenceFeature(tenant.id, "intelligence_demo", { mode: event.target.value, enabled: event.target.value !== "disabled", source: "admin", notes: "Modo demo administrado desde Scentra Admin" })}
                  >
                    <option value="disabled">demo off</option>
                    <option value="demo">demo on</option>
                  </select>
                </span>
                <span className="feature-stack">
                  {fullFeatures.map((feature) => {
                    const item = featureMap[feature.key] || {};
                    return (
                      <label key={feature.key} className="mini-control">
                        <small>{featureLabel(feature.key)}</small>
                        <select
                          value={item.mode || "disabled"}
                          onChange={(event) => setIntelligenceFeature(tenant.id, feature.key, { mode: event.target.value, enabled: event.target.value !== "disabled", quota_monthly: item.quota_monthly || feature.default_quota_monthly || 0, source: "admin" })}
                        >
                          <option value="disabled">off</option>
                          {feature.demo_allowed || item.mode === "demo" ? <option value="demo" disabled={!feature.demo_allowed}>demo</option> : null}
                          <option value="full">full</option>
                        </select>
                      </label>
                    );
                  })}
                </span>
              </div>
            );
          }) : <p className="empty">Sin tenants para gestionar inteligencia predictiva.</p>}
        </div>
      </article>
      <article className="panel glass-card">
        <div className="panel-head"><h2>ModelOps predictivo</h2><button type="button" onClick={recomputeMetrics}>Recalcular metricas</button><span>feedback y calidad</span></div>
        <div className="table observability-table">
          {(metrics || []).length ? metrics.map((metric) => (
            <div className="row intelligence-row" key={metric.id || `${metric.tenant_id}-${metric.model_key}-${metric.prediction_type}`}>
              <span><strong>{metric.model_key}</strong><small>{metric.prediction_type} / {metric.window_key}</small></span>
              <span>{metric.tenant_name || metric.tenant_slug || metric.tenant_id}</span>
              <span><mark className={statusClass(metric.status)}>{metric.status}</mark><small>{compactDateTimeLabel(metric.computed_at)}</small></span>
              <span>{number(metric.sample_size)}<small>muestras</small></span>
              <span>{number(metric.labeled_count)}<small>feedback</small></span>
              <span>{percentLabel(metric.accuracy)}<small>accuracy</small></span>
              <span>{percentLabel(metric.drift_score)}<small>drift</small></span>
            </div>
          )) : <p className="empty">Aun no hay metricas. Registra feedback de predicciones o recalcula cuando existan predicciones.</p>}
        </div>
      </article>
      <article className="panel glass-card">
        <div className="panel-head"><h2>ML Infrastructure</h2><span>{mlConfig.enabled ? "habilitado" : "apagado por defecto"}</span></div>
        <div className="notice-card">
          <strong>Politica de aprendizaje</strong>
          <span>Las cuentas demo/trial no alimentan entrenamiento por defecto. Para permitir pruebas internas activa en esa empresa <b>Aporte a entrenamiento ML</b> y <b>Demo autorizado para aprendizaje interno</b>. Los datos demo autorizados quedan marcados como internos y se excluyen de datasets productivos salvo que marques la casilla de prueba.</span>
        </div>
        <div className="section-chip">Data intelligence</div>
        <div className="form-grid four">
          <label>Empresa<select value={dataForm.tenant_id} onChange={(event) => setDataForm((prev) => ({ ...prev, tenant_id: event.target.value }))}><option value="">Todas operativas</option>{tenants.map((tenant) => <option key={tenant.id} value={tenant.id}>{tenant.name}</option>)}</select></label>
          <label>Tarea<select value={dataForm.prediction_type} onChange={(event) => setDataForm((prev) => ({ ...prev, prediction_type: event.target.value }))}><option value="">Todas</option>{["lead_scoring", "churn_prediction", "smart_remarketing", "operational_anomaly"].map((task) => <option key={task} value={task}>{taskTypeLabel(task)}</option>)}</select></label>
          <label>Ventana<input value={dataForm.window_key} onChange={(event) => setDataForm((prev) => ({ ...prev, window_key: event.target.value }))} /></label>
          <label>Limite<input type="number" min="1" max="25000" value={dataForm.limit} onChange={(event) => setDataForm((prev) => ({ ...prev, limit: Number(event.target.value || 1000) }))} /></label>
          <button type="button" onClick={generateAutoLabels}>Generar labels</button>
          <button type="button" onClick={recomputeFeaturePipelines}>Recalcular features</button>
        </div>
        <div className="metric-grid">
          <Metric title="Event contracts" value={mlops?.counts?.event_contracts || 0} hint="schemas activos" tone="blue" />
          <Metric title="Feature sets" value={mlops?.counts?.feature_sets || 0} hint="versionados" tone="violet" />
          <Metric title="Auto-labels" value={mlops?.counts?.auto_labels || 0} hint="ultimos registros" tone="mint" />
          <Metric title="Datasets" value={mlops?.counts?.training_datasets || 0} hint="Postgres feature store" tone="amber" />
        </div>
        <div className="section-chip">Entrenamiento real con auto-labels</div>
        <div className="form-grid four">
          <label>Empresa<select value={trainForm.tenant_id || ""} onChange={(event) => setTrainForm((prev) => ({ ...prev, tenant_id: event.target.value }))}><option value="">Global anonimo</option>{tenants.map((tenant) => <option key={tenant.id} value={tenant.id}>{tenant.name}</option>)}</select></label>
          <label>Dataset key<input value={trainForm.dataset_key || ""} onChange={(event) => setTrainForm((prev) => ({ ...prev, dataset_key: event.target.value }))} /></label>
          <label>Version<input value={trainForm.version || ""} onChange={(event) => setTrainForm((prev) => ({ ...prev, version: event.target.value }))} /></label>
          <label>Ventana<input value={trainForm.window_key || "90d"} onChange={(event) => setTrainForm((prev) => ({ ...prev, window_key: event.target.value }))} /></label>
          <label>Min samples<input type="number" min="5" value={trainForm.min_samples || 50} onChange={(event) => setTrainForm((prev) => ({ ...prev, min_samples: Number(event.target.value || 50) }))} /></label>
          <label className="check"><input type="checkbox" checked={Boolean(trainForm.include_global)} onChange={(event) => setTrainForm((prev) => ({ ...prev, include_global: event.target.checked }))} /> incluir global anonimo</label>
          <label className="check"><input type="checkbox" checked={Boolean(trainForm.include_internal_demo)} onChange={(event) => setTrainForm((prev) => ({ ...prev, include_internal_demo: event.target.checked }))} /> incluir demos autorizados solo para prueba</label>
          <button type="button" onClick={buildMlDataset} disabled={!mlConfig.enabled}>Construir dataset</button>
          <button type="button" className="primary" onClick={runAutoLabelTraining} disabled={!mlConfig.enabled}>Entrenar autolabel</button>
        </div>
        <div className="section-chip">Entrenamiento sintetico bootstrap</div>
        <form className="form-grid four" onSubmit={runTraining}>
          <label>Tarea<select value={trainForm.task_type} onChange={(event) => setTrainForm((prev) => ({ ...prev, task_type: event.target.value }))}>{["lead_scoring", "churn_prediction", "smart_remarketing", "operational_anomaly"].map((task) => <option key={task} value={task}>{taskTypeLabel(task)}</option>)}</select></label>
          <label>Modelo<input value={trainForm.model_key} placeholder="ml_lead_scoring_v2" onChange={(event) => setTrainForm((prev) => ({ ...prev, model_key: event.target.value }))} /></label>
          <label>Framework<select value={trainForm.framework} onChange={(event) => setTrainForm((prev) => ({ ...prev, framework: event.target.value }))}><option value="lightgbm">LightGBM</option><option value="xgboost">XGBoost</option><option value="sklearn">scikit-learn fallback</option></select></label>
          <label>Muestras<input type="number" min="50" max="100000" value={trainForm.sample_size} onChange={(event) => setTrainForm((prev) => ({ ...prev, sample_size: Number(event.target.value || 0) }))} /></label>
          <label>Seed<input type="number" value={trainForm.seed} onChange={(event) => setTrainForm((prev) => ({ ...prev, seed: Number(event.target.value || 42) }))} /></label>
          <label className="check"><input type="checkbox" checked={Boolean(trainForm.register_model_registry)} onChange={(event) => setTrainForm((prev) => ({ ...prev, register_model_registry: event.target.checked }))} /> Registrar en shadow</label>
          <button type="submit" className="primary" disabled={!mlConfig.enabled}>Entrenar sintetico</button>
        </form>
        <div className="metric-grid">
          <Metric title="Training jobs" value={mlops?.counts?.jobs || 0} hint="ultimos registros" tone="blue" />
          <Metric title="Artifacts" value={mlops?.counts?.artifacts || 0} hint="MLflow/BentoML/local" tone="violet" />
          <Metric title="Inferencias ML" value={mlops?.counts?.inference_runs || 0} hint="shadow/canary/prod" tone="mint" />
          <Metric title="Drift" value={mlops?.counts?.drift_snapshots || 0} hint="snapshots" tone="amber" />
        </div>
        <div className="table observability-table">
          <div className="row intelligence-row">
            <span><strong>Runtime</strong><small>{mlConfig.service_url || "sin servicio"}</small></span>
            <span><mark className={mlConfig.enabled ? "ok" : "neutral"}>{mlConfig.enabled ? "enabled" : "disabled"}</mark></span>
            <span>{mlConfig.shadow_inference_enabled ? "shadow on" : "shadow off"}<small>shadow inference</small></span>
            <span>{mlConfig.auto_train_enabled ? "auto train on" : "auto train off"}<small>entrenamiento automatico</small></span>
            <span>{mlConfig.mlflow_tracking_uri || "-"}<small>MLflow</small></span>
            <span>{mlConfig.qdrant_url || "-"}<small>vector infra</small></span>
          </div>
          {(mlops?.artifacts || []).slice(0, 8).map((artifact) => (
            <div className="row intelligence-row" key={artifact.id || `${artifact.model_key}-${artifact.version}`}>
              <span><strong>{artifact.model_key}</strong><small>{artifact.prediction_type} / {artifact.framework}</small></span>
              <span><mark className={statusClass(artifact.status)}>{artifact.status}</mark><small>{artifact.version}</small></span>
              <span>{percentLabel(artifact.metrics_json?.accuracy)}<small>accuracy</small></span>
              <span>{artifact.mlflow_run_id || "-"}<small>MLflow run</small></span>
              <span>{artifact.bentoml_tag || "-"}<small>BentoML tag</small></span>
              <span>{compactDateTimeLabel(artifact.updated_at)}<small>actualizado</small></span>
            </div>
          ))}
        </div>
      </article>
      <article className="panel glass-card">
        <div className="panel-head"><h2>Training readiness</h2><span>{number(readiness.sample_size || 0)} muestras / {number(readiness.labeled_count || 0)} labels</span></div>
        <div className="section-chip">Auto-label datasets</div>
        <div className="table observability-table">
          {(training?.auto_label_summaries || []).length ? training.auto_label_summaries.map((item) => (
            <div className="row intelligence-row" key={`${item.tenant_id}-${item.prediction_type}-${item.window_key}`}>
              <span><strong>{item.prediction_type}</strong><small>{item.window_key}</small></span>
              <span>{item.tenant_name || item.tenant_slug || item.tenant_id}</span>
              <span><mark className={item.ready_for_training ? "ok" : "warn"}>{item.ready_for_training ? "ready" : "blocked"}</mark><small>auto_label_v1</small></span>
              <span>{number(item.labeled_count)}<small>labels</small></span>
              <span>{number(item.positive_count)} / {number(item.negative_count)}<small>pos / neg</small></span>
              <span>{number(item.subjects)}<small>sujetos</small></span>
              <span>{compactDateTimeLabel(item.last_generated_at)}<small>generado</small></span>
            </div>
          )) : <p className="empty">Genera labels automaticos para crear datasets supervisados sin labeling manual inicial.</p>}
        </div>
        <div className="section-chip">Feedback datasets</div>
        <div className="table observability-table">
          {(training?.summaries || []).length ? training.summaries.map((item) => (
            <div className="row intelligence-row" key={`${item.tenant_id}-${item.model_key}-${item.prediction_type}`}>
              <span><strong>{item.model_key}</strong><small>{item.prediction_type}</small></span>
              <span>{item.tenant_name || item.tenant_slug || item.tenant_id}</span>
              <span><mark className={item.ready_for_training ? "ok" : "warn"}>{item.ready_for_training ? "ready" : "blocked"}</mark><small>{(item.readiness_reasons || []).join(", ")}</small></span>
              <span>{number(item.sample_size)}<small>muestras</small></span>
              <span>{number(item.labeled_count)} / {number(item.min_labeled_count)}<small>labels</small></span>
              <span>{number(item.label_diversity)}<small>diversidad</small></span>
              <span>{compactDateTimeLabel(item.last_feedback_at || item.last_prediction_at)}<small>ultimo dato</small></span>
            </div>
          )) : <p className="empty">Aun no hay datasets listos. Se necesita feedback/outcome para entrenamiento supervisado real por tenant/modelo.</p>}
        </div>
      </article>
      <article className="panel glass-card">
        <div className="panel-head"><h2>Model Registry & Rollout</h2><span>shadow, canary y produccion</span></div>
        <form className="form-grid four" onSubmit={registerModel}>
          <label>Modelo<input value={modelForm.model_key} placeholder="lead_scoring_candidate_v2" onChange={(event) => setModelForm((prev) => ({ ...prev, model_key: event.target.value }))} /></label>
          <label>Tarea<select value={modelForm.task_type} onChange={(event) => setModelForm((prev) => ({ ...prev, task_type: event.target.value }))}>{["lead_scoring", "churn_prediction", "smart_remarketing", "operational_anomaly"].map((task) => <option key={task} value={task}>{taskTypeLabel(task)}</option>)}</select></label>
          <label>Framework<input value={modelForm.framework} placeholder="lightgbm / catboost / pending" onChange={(event) => setModelForm((prev) => ({ ...prev, framework: event.target.value }))} /></label>
          <label>Version<input value={modelForm.version} onChange={(event) => setModelForm((prev) => ({ ...prev, version: event.target.value }))} /></label>
          <label>Artifact URI<input value={modelForm.artifact_uri} placeholder="s3://... / mlflow:/..." onChange={(event) => setModelForm((prev) => ({ ...prev, artifact_uri: event.target.value }))} /></label>
          <label>Rollout<select value={modelForm.rollout_mode} onChange={(event) => setModelForm((prev) => ({ ...prev, rollout_mode: event.target.value }))}><option value="shadow">shadow</option><option value="canary">canary</option><option value="production">production</option><option value="disabled">disabled</option></select></label>
          <label>Trafico %<input type="number" min="0" max="100" value={modelForm.traffic_percent} onChange={(event) => setModelForm((prev) => ({ ...prev, traffic_percent: Number(event.target.value || 0) }))} /></label>
          <label>Promocion<select value={modelForm.promotion_status} onChange={(event) => setModelForm((prev) => ({ ...prev, promotion_status: event.target.value }))}><option value="pending_review">pending_review</option><option value="approved">approved</option><option value="rejected">rejected</option><option value="blocked">blocked</option></select></label>
          <button type="submit" className="primary" disabled={!modelForm.model_key}>Registrar modelo</button>
        </form>
        <div className="table observability-table">
          {(models || []).length ? models.map((model) => {
            const assessment = model.assessment || {};
            const metricsSummary = model.metrics_summary || {};
            return (
              <div className="row intelligence-row" key={model.model_key}>
                <span><strong>{model.model_key}</strong><small>{model.task_type} / {model.framework}</small></span>
                <span><mark className={statusClass(model.status)}>{model.status}</mark><small>{model.stage}</small></span>
                <span>
                  <select
                    value={model.rollout_mode || "production"}
                    onChange={(event) => updateModel(model, { rollout_mode: event.target.value })}
                  >
                    <option value="disabled">disabled</option>
                    <option value="shadow">shadow</option>
                    <option value="canary">canary</option>
                    <option value="production">production</option>
                  </select>
                  <small>{number(model.traffic_percent)}% trafico</small>
                </span>
                <span>
                  <select
                    value={model.status || "active"}
                    onChange={(event) => updateModel(model, { status: event.target.value })}
                  >
                    <option value="active">active</option>
                    <option value="paused">paused</option>
                    <option value="candidate">candidate</option>
                    <option value="deprecated">deprecated</option>
                  </select>
                  <small>{model.promotion_status || "approved"}</small>
                </span>
                <span>{number(metricsSummary.labeled_count)}<small>feedback total</small></span>
                <span>{percentLabel(metricsSummary.avg_accuracy)}<small>accuracy global</small></span>
                <span>{percentLabel(metricsSummary.max_drift_score)}<small>drift max</small></span>
                <span><mark className={assessment.ready_for_production ? "ok" : "warn"}>{assessment.ready_for_production ? "ready" : "blocked"}</mark><small>{(assessment.reasons || []).join(", ")}</small></span>
              </div>
            );
          }) : <p className="empty">Sin modelos registrados para governance.</p>}
        </div>
      </article>
      <article className="panel glass-card">
        <div className="panel-head"><h2>Catalogo AI premium</h2><span>gating por plan, tenant y grant</span></div>
        <div className="flag-grid">
          {(catalog || []).map((feature) => (
            <div key={feature.key} className="switch read-only">
              <span><strong>{feature.label}</strong><small>{feature.key} / {feature.category}</small></span>
            </div>
          ))}
        </div>
      </article>
    </section>
  );
}

function PerformanceView({ reliability, processQueue, recordSnapshot, runDrill, runRetentionDryRun }) {
  const sloMetrics = reliability?.slo?.metrics || [];
  const queues = reliability?.backpressure?.queues || [];
  const indexes = reliability?.index_audit?.indexes || [];
  const policies = reliability?.retention_policies || [];
  const cleanupRuns = reliability?.cleanup_runs || [];
  const drills = reliability?.drills || [];
  const snapshots = reliability?.snapshots || [];
  const backup = reliability?.backup_readiness || {};
  const health = reliability?.health_summary || {};
  const status = reliability?.status || "unknown";
  return (
    <section className="stack">
      <div className="metric-grid">
        <Metric title={t("metric.reliability")} value={status.toUpperCase()} hint={reliability?.checked_at || "sin chequeo"} tone={status === "ok" ? "mint" : status === "critical" ? "rose" : "amber"} />
        <Metric title="SLO" value={(reliability?.slo?.status || "unknown").toUpperCase()} hint={`${number(sloMetrics.length)} metricas`} tone={reliability?.slo?.status === "ok" ? "mint" : "amber"} />
        <Metric title={t("metric.backlog")} value={health.backlog || 0} hint="jobs pendientes" tone={Number(health.backlog || 0) ? "amber" : "mint"} />
        <Metric title="Errores" value={health.error_total || 0} hint="colas y dead-letter" tone={Number(health.error_total || 0) ? "rose" : "mint"} />
        <Metric title="Indices" value={`${number(reliability?.index_audit?.present || 0)}/${number(reliability?.index_audit?.expected || 0)}`} hint={`${number(reliability?.index_audit?.missing || 0)} faltantes`} tone={reliability?.index_audit?.status === "ok" ? "mint" : "amber"} />
      </div>
      <section className="dashboard-grid wide-left">
        <article className="panel glass-card">
          <div className="panel-head"><h2>{t("panel.performance")}</h2><span>SLOs, colas y drills</span></div>
          <p className="soft">Las acciones de esta vista registran snapshots, dry-runs y readiness checks. No reparan Meta, no pausan campanas y no borran datos sin ejecucion destructiva explicita.</p>
          <div className="admin-actions">
            <button type="button" className="primary" onClick={recordSnapshot}>Snapshot SLO</button>
            <button type="button" onClick={() => runDrill("load_smoke")}>Drill carga smoke</button>
            <button type="button" onClick={() => runDrill("backup_readiness")}>{t("button.backup_readiness")}</button>
            <button type="button" onClick={runRetentionDryRun}>{t("button.retention_dry_run")}</button>
            <button type="button" onClick={() => processQueue("reliability")}>{t("button.process_reliability")}</button>
          </div>
        </article>
        <article className="panel glass-card">
          <div className="panel-head"><h2>{t("panel.backup_readiness")}</h2><span>{backup.status || "unknown"}</span></div>
          <div className="list">
            <div><strong>{backup.latest_migration?.file_name || "-"}</strong><span>Ultima migracion aplicada</span></div>
            <div><strong>{number(backup.database?.public_tables || 0)}</strong><span>Tablas publicas</span></div>
            <div><strong>{number(backup.database?.database_bytes || 0)}</strong><span>Bytes DB</span></div>
          </div>
        </article>
      </section>
      <article className="panel glass-card">
        <div className="panel-head"><h2>{t("panel.slo_metrics")}</h2><span>{reliability?.slo?.status || "unknown"}</span></div>
        <div className="table observability-table">
          {sloMetrics.length ? sloMetrics.map((item) => (
            <div className="row performance-row" key={item.metric_key}>
              <span><strong>{item.label || item.metric_key}</strong><small>{item.metric_key}</small></span>
              <span><mark className={statusClass(item.status)}>{item.status}</mark></span>
              <span>{number(item.value)}<small>valor</small></span>
              <span>{item.comparison} {number(item.target_value)}<small>objetivo</small></span>
              <span>{number(item.warn_threshold)} / {number(item.critical_threshold)}<small>warn / critical</small></span>
            </div>
          )) : <p className="empty">Sin metricas SLO disponibles.</p>}
        </div>
      </article>
      <article className="panel glass-card">
        <div className="panel-head"><h2>Backpressure de colas</h2><span>{reliability?.backpressure?.status || "unknown"}</span></div>
        <div className="table observability-table">
          {queues.length ? queues.map((item) => (
            <div className="row performance-row" key={item.queue_key}>
              <span><strong>{item.queue_key}</strong><small>{(item.recommended_actions || []).join(", ") || "sin acciones"}</small></span>
              <span><mark className={statusClass(item.status)}>{item.status}</mark></span>
              <span>{number(item.pending)}<small>pendientes</small></span>
              <span>{number(item.errors)}<small>errores</small></span>
              <span>{number(item.warn_backlog)} / {number(item.critical_backlog)}<small>warn / critical</small></span>
            </div>
          )) : <p className="empty">Sin colas detectadas.</p>}
        </div>
      </article>
      <article className="panel glass-card">
        <div className="panel-head"><h2>Auditoria de indices</h2><span>{reliability?.index_audit?.status || "unknown"}</span></div>
        <div className="table observability-table">
          {indexes.length ? indexes.map((item) => (
            <div className="row index-row" key={item.index_name}>
              <span><strong>{item.index_name}</strong><small>{item.table_name}</small></span>
              <span><mark className={item.present ? "ok" : "warn"}>{item.present ? "present" : "missing"}</mark></span>
              <span>{number(item.live_rows)}<small>live rows</small></span>
              <span>{number(item.seq_scan)} / {number(item.idx_scan)}<small>seq / idx scans</small></span>
              <span>{item.purpose}</span>
            </div>
          )) : <p className="empty">Sin auditoria de indices.</p>}
        </div>
      </article>
      <section className="dashboard-grid">
        <article className="panel glass-card">
          <div className="panel-head"><h2>Retention policies</h2><span>dry-run first</span></div>
          <div className="table observability-table">
            {policies.length ? policies.map((item) => (
              <div className="row retention-row" key={item.policy_key}>
                <span><strong>{item.policy_key}</strong><small>{item.table_name}.{item.timestamp_column}</small></span>
                <span><mark className={item.enabled ? "ok" : "warn"}>{item.enabled ? "enabled" : "disabled"}</mark></span>
                <span>{number(item.retention_days)} dias<small>retencion</small></span>
                <span>{number(item.batch_limit)}<small>batch</small></span>
                <span>{compactDateTimeLabel(item.last_run_at)}<small>ultimo run</small></span>
              </div>
            )) : <p className="empty">Sin politicas de retencion.</p>}
          </div>
        </article>
        <article className="panel glass-card">
          <div className="panel-head"><h2>Cleanup runs</h2><span>{number(cleanupRuns.length)}</span></div>
          <div className="table compact">
            {cleanupRuns.length ? cleanupRuns.slice(0, 8).map((item) => (
              <div className="row" key={item.id}><span><strong>{item.policy_key}</strong><small>{compactDateTimeLabel(item.started_at)}</small></span><span><mark className={statusClass(item.status)}>{item.status}</mark></span><span>{number(item.matched_count)} / {number(item.deleted_count)}<small>match / delete</small></span></div>
            )) : <p className="empty">Sin ejecuciones registradas.</p>}
          </div>
        </article>
      </section>
      <section className="dashboard-grid">
        <article className="panel glass-card">
          <div className="panel-head"><h2>Drills recientes</h2><span>{number(drills.length)}</span></div>
          <div className="table compact">
            {drills.length ? drills.slice(0, 8).map((item) => (
              <div className="row" key={item.id}><span><strong>{item.drill_type}</strong><small>{compactDateTimeLabel(item.started_at)}</small></span><span><mark className={statusClass(item.status)}>{item.status}</mark></span><span>{item.initiated_by || "system"}</span></div>
            )) : <p className="empty">Sin drills registrados.</p>}
          </div>
        </article>
        <article className="panel glass-card">
          <div className="panel-head"><h2>Snapshots</h2><span>{number(snapshots.length)}</span></div>
          <div className="table compact">
            {snapshots.length ? snapshots.slice(0, 8).map((item) => (
              <div className="row" key={item.id}><span><strong>{item.snapshot_key}</strong><small>{compactDateTimeLabel(item.created_at)}</small></span><span><mark className={statusClass(item.status)}>{item.status}</mark></span><span>{(item.signals_json || []).slice(0, 2).join(", ") || "sin senales"}</span></div>
            )) : <p className="empty">Sin snapshots registrados.</p>}
          </div>
        </article>
      </section>
    </section>
  );
}

function OperationsView({ queues, processQueue }) {
  return (
    <section className="dashboard-grid">
      <article className="panel glass-card"><div className="panel-head"><h2>Colas</h2><span>workers</span></div><QueueSummary queues={queues} /><div className="admin-actions"><button type="button" className="primary" onClick={() => processQueue("webhooks")}>Procesar webhooks</button><button type="button" className="primary" onClick={() => processQueue("outbound")}>Procesar outbound</button><button type="button" onClick={() => processQueue("triggers")}>Procesar triggers</button><button type="button" onClick={() => processQueue("ai")}>Procesar IA</button><button type="button" onClick={() => processQueue("remarketing")}>Procesar remarketing</button><button type="button" onClick={() => processQueue("agents")}>Procesar agentes</button><button type="button" onClick={() => processQueue("intelligence")}>Procesar Intelligence</button><button type="button" onClick={() => processQueue("reliability")}>Procesar reliability</button><button type="button" onClick={() => processQueue("metaTokens")}>Refrescar Meta</button></div></article>
      <article className="panel glass-card"><div className="panel-head"><h2>Salud operativa</h2><span>runtime</span></div><p className="soft">Desde aqui se reintentan jobs criticos, workers, IA, outbound, webhooks, triggers, remarketing y token refresh de Meta.</p></article>
    </section>
  );
}

function ObservabilityView({ health, deadLetters, metaErrors, processQueue, syncDeadLetters, resolveDeadLetter, retryDeadLetter }) {
  const state = health?.health || {};
  const summary = state?.summary || {};
  const platform = state?.platform || {};
  const channels = health?.channels || [];
  const workers = state?.workers || {};
  const meta = state?.meta || {};
  const aiGateway = state?.ai_gateway || {};
  const status = state?.status || "unknown";
  return (
    <section className="stack">
      <div className="metric-grid">
        <Metric title="Estado API" value={status.toUpperCase()} hint={state?.checked_at || "sin chequeo"} tone={status === "ok" ? "mint" : status === "down" ? "rose" : "amber"} />
        <Metric title="DB" value={state?.database?.ok ? "OK" : "ERROR"} hint={state?.database?.server_time || "-"} tone={state?.database?.ok ? "mint" : "rose"} />
        <Metric title="Worker" value={(workers.status || "unknown").toUpperCase()} hint={`${number(workers.fresh || 0)} activos / ${number(workers.total || 0)} vistos`} tone={workers.status === "ok" ? "mint" : "amber"} />
        <Metric title="Meta" value={(meta.status || "unknown").toUpperCase()} hint={`${number(meta.error_total || 0)} errores`} tone={meta.status === "ok" ? "mint" : "rose"} />
        <Metric title="AI Gateway" value={(aiGateway.status || "unknown").toUpperCase()} hint={`${number(aiGateway?.runs?.failed_24h || 0)} fallos 24h`} tone={aiGateway.status === "ok" ? "mint" : "amber"} />
        <Metric title="Backlog" value={summary.backlog || 0} hint="jobs pendientes" tone="blue" />
        <Metric title="Errores" value={summary.error_total || 0} hint="candidatos dead-letter" tone={Number(summary.error_total || 0) ? "rose" : "mint"} />
        <Metric title="Integraciones" value={platform.connected_integrations || 0} hint={`${number(platform.active_webhooks || 0)} webhooks activos`} tone="violet" />
      </div>
      <section className="dashboard-grid wide-left">
        <article className="panel glass-card">
          <div className="panel-head"><h2>Colas operativas</h2><span>runtime</span></div>
          <QueueSummary queues={state?.queues} />
          <div className="admin-actions">
            <button type="button" className="primary" onClick={() => processQueue("webhooks")}>Procesar webhooks</button>
            <button type="button" className="primary" onClick={() => processQueue("outbound")}>Procesar outbound</button>
            <button type="button" onClick={() => processQueue("triggers")}>Procesar triggers</button>
            <button type="button" onClick={() => processQueue("ai")}>Procesar IA</button>
            <button type="button" onClick={() => processQueue("agents")}>Procesar agentes</button>
            <button type="button" onClick={() => processQueue("intelligence")}>Procesar Intelligence</button>
            <button type="button" onClick={() => processQueue("reliability")}>Procesar reliability</button>
            <button type="button" onClick={() => processQueue("metaTokens")}>Refrescar Meta</button>
            <button type="button" onClick={syncDeadLetters}>Sincronizar dead-letter</button>
          </div>
          {(state?.signals || []).length ? <div className="insight-list">{state.signals.map((signal) => <mark key={signal} className="warn">{signal}</mark>)}</div> : <p className="soft">Sin senales criticas en este chequeo.</p>}
        </article>
        <article className="panel glass-card">
          <div className="panel-head"><h2>Base de datos</h2><span>{state?.database?.ok ? "ok" : "error"}</span></div>
          <div className="list">
            <div><strong>{state?.database?.server_time || "-"}</strong><span>Hora servidor</span></div>
            <div><strong>{platform.active_tenants || 0} / {platform.tenants || 0}</strong><span>Empresas activas / totales</span></div>
            <div><strong>{health?.dead_letter_sync?.synced || 0}</strong><span>Eventos normalizados en ultimo chequeo</span></div>
            <div><strong>{number(aiGateway?.runs?.runs_24h || 0)}</strong><span>AI Gateway runs 24h</span></div>
          </div>
        </article>
      </section>
      <section className="dashboard-grid">
        <article className="panel glass-card">
          <div className="panel-head"><h2>Workers</h2><span>{workers.status || "unknown"}</span></div>
          <div className="table compact">
            {(workers.workers || []).length ? workers.workers.map((item) => (
              <div className="row" key={item.worker_name}><span><strong>{item.worker_name}</strong><small>{item.worker_type}</small></span><span>{item.status}</span><span>{number(item.age_seconds || 0)}s</span><span>{item.last_error || item.last_seen_at || "-"}</span></div>
            )) : <p className="empty">Sin heartbeat de worker registrado.</p>}
          </div>
        </article>
        <article className="panel glass-card">
          <div className="panel-head"><h2>Meta y AI Gateway</h2><span>24h / 7d</span></div>
          <div className="list">
            <div><strong>{number(meta?.webhooks?.events_24h || 0)} / {number(meta?.webhooks?.errors_24h || 0)}</strong><span>Webhooks Meta / errores 24h</span></div>
            <div><strong>{number(meta?.outbound?.failed_24h || 0)}</strong><span>Outbound Meta fallido 24h</span></div>
            <div><strong>{number(aiGateway?.runs?.success_24h || 0)} / {number(aiGateway?.runs?.failed_24h || 0)}</strong><span>AI success / fallos 24h</span></div>
            <div><strong>{number(aiGateway?.runs?.avg_latency_ms || 0)} ms</strong><span>Latencia promedio AI</span></div>
          </div>
        </article>
      </section>
      <article className="panel glass-card">
        <div className="panel-head"><h2>Diagnostico por canal</h2><span>{number(channels.length)}</span></div>
        <div className="table observability-table">
          {channels.length ? channels.map((item) => (
            <div className="row channel-row" key={`${item.provider}-${item.channel}`}>
              <span><strong>{item.provider} / {item.channel}</strong><small>{(item.signals || []).join(", ") || "sin alertas"}</small></span>
              <span><mark className={statusClass(item.status)}>{item.status}</mark></span>
              <span>{number(item.connected)} / {number(item.integrations)}<small>integraciones</small></span>
              <span>{number(item.events_7d)}<small>webhooks 7d</small></span>
              <span>{number(item.errors_7d + item.outbound_failed)}<small>errores</small></span>
              <span>{item.last_event_at || item.last_message_at || "-"}</span>
            </div>
          )) : <p className="empty">Sin integraciones o canales detectados.</p>}
        </div>
      </article>
      <article className="panel glass-card">
        <div className="panel-head"><h2>Dead-letter</h2><span>{number(deadLetters.length)} abiertos</span></div>
        <div className="table observability-table">
          {deadLetters.length ? deadLetters.map((item) => (
            <div className="row dead-row" key={item.id}>
              <span><strong>{item.tenant_name || item.tenant_slug || "Tenant"}</strong><small>{item.source_type} / {item.source_id}</small></span>
              <span><mark className={item.severity === "high" ? "danger" : "warn"}>{item.severity}</mark></span>
              <span>{item.provider || "-"} / {item.channel || "-"}</span>
              <span><strong>{item.reason || item.status}</strong><small>{item.diagnosis?.stage || "-"} · {item.correlation_id || "sin correlation_id"}</small></span>
              <span>{number(item.retry_info?.attempts || 0)} / {number(item.retry_info?.max_attempts || 0)}<small>intentos</small></span>
              <span className="row-actions">{item.retry_info?.retryable ? <button type="button" className="primary" onClick={() => retryDeadLetter(item.id)}>Reintentar</button> : null}<button type="button" onClick={() => resolveDeadLetter(item.id)}>Resolver</button></span>
            </div>
          )) : <p className="empty">Sin dead-letters abiertos.</p>}
        </div>
      </article>
      <article className="panel glass-card">
        <div className="panel-head"><h2>Errores Meta por tenant</h2><span>{number((metaErrors || []).length)}</span></div>
        <div className="table observability-table">
          {(metaErrors || []).length ? metaErrors.map((item) => (
            <div className="row dead-row" key={`${item.source_type}-${item.source_id}`}>
              <span><strong>{item.tenant_name || item.tenant_slug || "Tenant"}</strong><small>{item.source_type}</small></span>
              <span>{item.provider || "meta"} / {item.channel || "-"}</span>
              <span>{item.status || "-"}</span>
              <span><strong>{item.error_message || "-"}</strong><small>{item.occurred_at || "-"}</small></span>
              <span>{number(item.attempts || 0)}<small>intentos</small></span>
            </div>
          )) : <p className="empty">Sin errores Meta recientes.</p>}
        </div>
      </article>
    </section>
  );
}

function QueueSummary({ queues }) {
  const outbound = queues?.outbound || [];
  const webhooks = queues?.webhooks || [];
  const scheduled = queues?.scheduled_triggers || [];
  const aiPending = queues?.ai_pending || [];
  const remarketing = queues?.remarketing || [];
  const agentOrchestrator = queues?.agent_orchestrator || [];
  return (
    <div className="queue-grid">
      <div><span>Outbound queued</span><strong>{number(queueTotal(outbound, "queued"))}</strong></div>
      <div><span>Outbound retry</span><strong>{number(queueTotal(outbound, "retry"))}</strong></div>
      <div><span>Outbound failed</span><strong>{number(queueTotal(outbound, "failed"))}</strong></div>
      <div><span>Webhooks received</span><strong>{number(queueTotal(webhooks, "received"))}</strong></div>
      <div><span>Webhooks error</span><strong>{number(queueTotal(webhooks, "error"))}</strong></div>
      <div><span>Triggers pending</span><strong>{number(queueTotal(scheduled, "pending"))}</strong></div>
      <div><span>AI pending</span><strong>{number(queueTotal(aiPending, "pending"))}</strong></div>
      <div><span>Remarketing active</span><strong>{number(queueTotal(remarketing, "active"))}</strong></div>
      <div><span>Agent queued</span><strong>{number(queueTotal(agentOrchestrator, "queued"))}</strong></div>
    </div>
  );
}

function LegacyUsersAdminView({ me, profileForm, setProfileForm, passwordForm, setPasswordForm, saveProfile, changePassword, platformAdmins, platformRoles, platformForm, setPlatformForm, createPlatformAdmin, patchPlatformAdmin, tenantUsers, tenantRoles, tenantForm, setTenantForm, tenants, createTenantUser, patchTenantUser, busy }) {
  return (
    <section className="stack">
      <div className="grid">
        <article className="panel glass-card">
          <div className="panel-head"><h2>Mi perfil Admin</h2><span>{roleLabel(me?.platform_role, true)}</span></div>
          <div className="form-grid two">
            <label>Nombre<input value={profileForm.full_name} onChange={(event) => setProfileForm((prev) => ({ ...prev, full_name: event.target.value }))} /></label>
            <label>Correo<input value={profileForm.email} onChange={(event) => setProfileForm((prev) => ({ ...prev, email: event.target.value }))} /></label>
            <label>Telefono<input value={profileForm.phone} onChange={(event) => setProfileForm((prev) => ({ ...prev, phone: event.target.value }))} /></label>
            <label>Cargo visible<input value={profileForm.role_label} onChange={(event) => setProfileForm((prev) => ({ ...prev, role_label: event.target.value }))} /></label>
            <label className="wide">URL avatar<input value={profileForm.avatar_url} onChange={(event) => setProfileForm((prev) => ({ ...prev, avatar_url: event.target.value }))} /></label>
            <label className="wide">Clave actual para cambiar correo<input type="password" value={profileForm.current_password} onChange={(event) => setProfileForm((prev) => ({ ...prev, current_password: event.target.value }))} /></label>
          </div>
          <button type="button" className="primary" onClick={saveProfile}>Guardar perfil</button>
        </article>
        <article className="panel glass-card">
          <div className="panel-head"><h2>Cambiar clave</h2><span>seguridad</span></div>
          <label>Clave actual<input type="password" value={passwordForm.current_password} onChange={(event) => setPasswordForm((prev) => ({ ...prev, current_password: event.target.value }))} /></label>
          <label>Nueva clave<input type="password" value={passwordForm.new_password} onChange={(event) => setPasswordForm((prev) => ({ ...prev, new_password: event.target.value }))} /></label>
          <label>Confirmar clave<input type="password" value={passwordForm.confirm_password} onChange={(event) => setPasswordForm((prev) => ({ ...prev, confirm_password: event.target.value }))} /></label>
          <button type="button" className="primary" onClick={changePassword}>Actualizar clave</button>
        </article>
      </div>
      <div className="grid">
        <article className="panel glass-card">
          <div className="panel-head"><h2>Crear Admin</h2><span>plataforma</span></div>
          <label>Nombre<input value={platformForm.full_name} onChange={(event) => setPlatformForm((prev) => ({ ...prev, full_name: event.target.value }))} /></label>
          <label>Email<input value={platformForm.email} onChange={(event) => setPlatformForm((prev) => ({ ...prev, email: event.target.value }))} /></label>
          <label>Clave temporal<input type="password" value={platformForm.password} onChange={(event) => setPlatformForm((prev) => ({ ...prev, password: event.target.value }))} /></label>
          <label>Rol<select value={platformForm.platform_role} onChange={(event) => setPlatformForm((prev) => ({ ...prev, platform_role: event.target.value }))}>{platformRoles.map((role) => <option key={role} value={role}>{roleLabel(role, true)}</option>)}</select></label>
          <label>Estado<select value={platformForm.status} onChange={(event) => setPlatformForm((prev) => ({ ...prev, status: event.target.value }))}><option value="active">Activo</option><option value="paused">Pausado</option><option value="disabled">Deshabilitado</option></select></label>
          <label>Notas<input value={platformForm.notes} onChange={(event) => setPlatformForm((prev) => ({ ...prev, notes: event.target.value }))} /></label>
          <label className="check-row"><input type="checkbox" checked={platformForm.send_email} onChange={(event) => setPlatformForm((prev) => ({ ...prev, send_email: event.target.checked }))} /> Enviar bienvenida</label>
          <button type="button" className="primary" disabled={busy === "platform-create"} onClick={createPlatformAdmin}>{busy === "platform-create" ? "Guardando..." : "Crear admin"}</button>
        </article>
        <article className="panel glass-card">
          <div className="panel-head"><h2>Crear usuario tenant</h2><span>empresa</span></div>
          <label>Empresa<select value={tenantForm.tenant_id} onChange={(event) => setTenantForm((prev) => ({ ...prev, tenant_id: event.target.value }))}><option value="">Seleccionar empresa</option>{tenants.map((tenant) => <option key={tenant.id} value={tenant.id}>{tenant.name}</option>)}</select></label>
          <label>Nombre<input value={tenantForm.full_name} onChange={(event) => setTenantForm((prev) => ({ ...prev, full_name: event.target.value }))} /></label>
          <label>Email<input value={tenantForm.email} onChange={(event) => setTenantForm((prev) => ({ ...prev, email: event.target.value }))} /></label>
          <label>Clave temporal<input type="password" value={tenantForm.password} onChange={(event) => setTenantForm((prev) => ({ ...prev, password: event.target.value }))} /></label>
          <label>Rol<select value={tenantForm.role} onChange={(event) => setTenantForm((prev) => ({ ...prev, role: event.target.value }))}>{tenantRoles.map((role) => <option key={role} value={role}>{roleLabel(role)}</option>)}</select></label>
          <label className="check-row"><input type="checkbox" checked={tenantForm.send_email} onChange={(event) => setTenantForm((prev) => ({ ...prev, send_email: event.target.checked }))} /> Enviar bienvenida</label>
          <button type="button" className="primary" disabled={busy === "tenant-create" || !tenantForm.tenant_id} onClick={createTenantUser}>{busy === "tenant-create" ? "Guardando..." : "Crear usuario"}</button>
        </article>
      </div>
      <article className="panel glass-card">
        <div className="panel-head"><h2>Administradores plataforma</h2><span>{number(platformAdmins.length)}</span></div>
        <div className="table">{platformAdmins.map((admin) => <div className="row" key={admin.user_id}><span><strong>{admin.full_name || admin.email}</strong><small>{admin.email}</small></span><span><select value={admin.platform_role} disabled={busy === admin.user_id} onChange={(event) => patchPlatformAdmin(admin.user_id, { platform_role: event.target.value })}>{platformRoles.map((role) => <option key={role} value={role}>{roleLabel(role, true)}</option>)}</select></span><span><select value={admin.platform_status} disabled={busy === admin.user_id || admin.user_id === me?.user_id} onChange={(event) => patchPlatformAdmin(admin.user_id, { status: event.target.value })}><option value="active">Activo</option><option value="paused">Pausado</option><option value="disabled">Deshabilitado</option></select></span></div>)}</div>
      </article>
      <article className="panel glass-card">
        <div className="panel-head"><h2>Usuarios de empresas</h2><span>{number(tenantUsers.length)}</span></div>
        <div className="table">{tenantUsers.map((member) => <div className="row user-row" key={member.id}><span><strong>{member.full_name || member.email}</strong><small>{member.email} / {member.tenant_name}</small></span><span><select value={member.role} disabled={busy === member.id} onChange={(event) => patchTenantUser(member.id, { role: event.target.value })}>{tenantRoles.map((role) => <option key={role} value={role}>{roleLabel(role)}</option>)}</select></span><span>{member.is_active ? "Activo" : "Inactivo"}</span><span><button type="button" disabled={busy === member.id} onClick={() => patchTenantUser(member.id, { is_active: !member.is_active })}>{member.is_active ? "Desactivar" : "Activar"}</button></span></div>)}</div>
      </article>
    </section>
  );
}

function LegacyNotificationsAdminView({ targets, notifications, form, setForm, draftForm, setDraftForm, draftNotification, sendNotification, busy }) {
  const toggleListValue = (key, value) => {
    setForm((prev) => {
      const current = new Set(prev[key] || []);
      if (current.has(value)) current.delete(value);
      else current.add(value);
      return { ...prev, [key]: Array.from(current), audience_type: "selected" };
    });
  };
  return (
    <section className="stack">
      <div className="grid">
        <article className="panel glass-card">
          <div className="panel-head"><h2>Borrador asistido</h2><span>humano revisa y envía</span></div>
          <label>Tema<input value={draftForm.topic} onChange={(event) => setDraftForm((prev) => ({ ...prev, topic: event.target.value }))} placeholder="Mantenimiento, cambio de rol, aviso comercial..." /></label>
          <label>Audiencia<input value={draftForm.audience} onChange={(event) => setDraftForm((prev) => ({ ...prev, audience: event.target.value }))} placeholder="administradores de empresas, agentes..." /></label>
          <label>Tono<input value={draftForm.tone} onChange={(event) => setDraftForm((prev) => ({ ...prev, tone: event.target.value }))} /></label>
          <label>Contexto<textarea rows={4} value={draftForm.body_hint} onChange={(event) => setDraftForm((prev) => ({ ...prev, body_hint: event.target.value }))} /></label>
          <button type="button" onClick={draftNotification} disabled={busy === "draft"}>{busy === "draft" ? "Generando..." : "Preparar borrador"}</button>
        </article>
        <article className="panel glass-card">
          <div className="panel-head"><h2>Enviar notificación</h2><span>{targets.smtp_configured ? "correo activo" : "solo app"}</span></div>
          <label>Titulo<input value={form.title} onChange={(event) => setForm((prev) => ({ ...prev, title: event.target.value }))} /></label>
          <label>Mensaje<textarea rows={6} value={form.body} onChange={(event) => setForm((prev) => ({ ...prev, body: event.target.value }))} /></label>
          <div className="form-grid two">
            <label>Severidad<select value={form.severity} onChange={(event) => setForm((prev) => ({ ...prev, severity: event.target.value }))}>{Object.entries(SEVERITY_LABELS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
            <label>Categoría<select value={form.category} onChange={(event) => setForm((prev) => ({ ...prev, category: event.target.value }))}>{Object.entries(CATEGORY_LABELS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
          </div>
          <label className="check-row"><input type="checkbox" checked={form.email_copy} onChange={(event) => setForm((prev) => ({ ...prev, email_copy: event.target.checked }))} /> Enviar copia por correo</label>
          <button type="button" className="primary" onClick={sendNotification} disabled={busy === "send"}>{busy === "send" ? "Enviando..." : "Enviar"}</button>
        </article>
      </div>
      <article className="panel glass-card">
        <div className="panel-head"><h2>Destinatarios</h2><span>sin mensajes de cliente</span></div>
        <div className="notification-targets">
          <div><strong>Empresas</strong>{(targets.tenants || []).slice(0, 80).map((tenant) => <label className="check-row" key={tenant.id}><input type="checkbox" checked={(form.tenant_ids || []).includes(tenant.id)} onChange={() => toggleListValue("tenant_ids", tenant.id)} /> {tenant.name}</label>)}</div>
          <div><strong>Roles</strong>{(targets.roles || Object.keys(TENANT_ROLE_LABELS)).map((role) => <label className="check-row" key={role}><input type="checkbox" checked={(form.roles || []).includes(role)} onChange={() => toggleListValue("roles", role)} /> {roleLabel(role)}</label>)}</div>
          <div><strong>Usuarios</strong>{(targets.users || []).slice(0, 120).map((user) => <label className="check-row" key={`${user.tenant_id}-${user.user_id}`}><input type="checkbox" checked={(form.user_ids || []).includes(user.user_id)} onChange={() => toggleListValue("user_ids", user.user_id)} /> {user.full_name || user.email} <small>{user.tenant_name}</small></label>)}</div>
        </div>
      </article>
      <article className="panel glass-card">
        <div className="panel-head"><h2>Historial</h2><span>{number(notifications.length)}</span></div>
        <div className="table">{notifications.map((item) => <div className="row notification-row" key={item.id}><span><strong>{item.title}</strong><small>{SEVERITY_LABELS[item.severity] || item.severity} / {categoryLabel(item.category)}</small></span><span>{number(item.recipients)} destinatarios</span><span>{number(item.read_count)} leídas</span><span>{number(item.email_sent_count)} correos</span></div>)}</div>
      </article>
    </section>
  );
}

function UsersAdminView({ me, activeTab, setActiveTab, tenantUserSearch, setTenantUserSearch, profileForm, setProfileForm, passwordForm, setPasswordForm, saveProfile, changePassword, platformAdmins, platformRoles, platformForm, setPlatformForm, createPlatformAdmin, patchPlatformAdmin, tenantUsers, tenantRoles, tenantForm, setTenantForm, tenants, createTenantUser, patchTenantUser, busy }) {
  const normalizedTenantSearch = tenantUserSearch.trim().toLowerCase();
  const filteredTenantUsers = tenantUsers.filter((member) => {
    if (!normalizedTenantSearch) return true;
    return [
      member.full_name,
      member.email,
      member.tenant_name,
      member.role,
      member.is_active ? "activo" : "inactivo",
    ].some((value) => String(value || "").toLowerCase().includes(normalizedTenantSearch));
  });
  const tabs = [
    ["profile", "Mi perfil", "datos y clave"],
    ["platform", "Admins plataforma", `${number(platformAdmins.length)} admins`],
    ["tenant", "Usuarios empresa", `${number(tenantUsers.length)} usuarios`],
  ];
  return (
    <section className="stack admin-section">
      <div className="admin-tabs" role="tablist" aria-label="Gestion de usuarios">
        {tabs.map(([key, label, hint]) => (
          <button type="button" key={key} className={activeTab === key ? "active" : ""} onClick={() => setActiveTab(key)}>
            <strong>{label}</strong>
            <small>{hint}</small>
          </button>
        ))}
      </div>

      {activeTab === "profile" ? (
        <div className="admin-split">
          <article className="panel glass-card">
            <div className="panel-head"><h2>Mi perfil Admin</h2><span>{roleLabel(me?.platform_role, true)}</span></div>
            <p className="panel-hint">Actualiza tus datos visibles dentro del Admin. Si cambias el correo, confirma con tu clave actual.</p>
            <div className="form-grid two">
              <label>Nombre<input value={profileForm.full_name} onChange={(event) => setProfileForm((prev) => ({ ...prev, full_name: event.target.value }))} /></label>
              <label>Correo<input value={profileForm.email} onChange={(event) => setProfileForm((prev) => ({ ...prev, email: event.target.value }))} /></label>
              <label>Telefono<input value={profileForm.phone} onChange={(event) => setProfileForm((prev) => ({ ...prev, phone: event.target.value }))} /></label>
              <label>Cargo visible<input value={profileForm.role_label} onChange={(event) => setProfileForm((prev) => ({ ...prev, role_label: event.target.value }))} /></label>
              <label>Zona horaria<select value={profileForm.timezone} onChange={(event) => setProfileForm((prev) => ({ ...prev, timezone: event.target.value }))}>{TIME_ZONE_OPTIONS.map(([value, label]) => <option key={value} value={value}>{label} ({value})</option>)}</select></label>
              <label className="wide">URL avatar<input value={profileForm.avatar_url} onChange={(event) => setProfileForm((prev) => ({ ...prev, avatar_url: event.target.value }))} /></label>
              <label className="wide">Clave actual para cambiar correo<input type="password" value={profileForm.current_password} onChange={(event) => setProfileForm((prev) => ({ ...prev, current_password: event.target.value }))} /></label>
            </div>
            <p className="panel-hint">Los horarios de auditoria, errores y registros se muestran con esta zona. Por defecto usamos Colombia.</p>
            <button type="button" className="primary" onClick={saveProfile}>Guardar perfil</button>
          </article>
          <article className="panel glass-card">
            <div className="panel-head"><h2>Cambiar clave</h2><span>seguridad</span></div>
            <p className="panel-hint">Usa una clave nueva fuerte. Este cambio afecta solo tu acceso al panel Admin.</p>
            <label>Clave actual<input type="password" value={passwordForm.current_password} onChange={(event) => setPasswordForm((prev) => ({ ...prev, current_password: event.target.value }))} /></label>
            <label>Nueva clave<input type="password" value={passwordForm.new_password} onChange={(event) => setPasswordForm((prev) => ({ ...prev, new_password: event.target.value }))} /></label>
            <label>Confirmar clave<input type="password" value={passwordForm.confirm_password} onChange={(event) => setPasswordForm((prev) => ({ ...prev, confirm_password: event.target.value }))} /></label>
            <button type="button" className="primary" onClick={changePassword}>Actualizar clave</button>
          </article>
        </div>
      ) : null}

      {activeTab === "platform" ? (
        <div className="admin-split wide-left">
          <article className="panel glass-card">
            <div className="panel-head"><h2>Crear admin</h2><span>plataforma</span></div>
            <p className="panel-hint">Crea usuarios para operar Scentra Admin. Estos usuarios no entran al Inbox de las empresas.</p>
            <div className="form-grid two">
              <label>Nombre<input value={platformForm.full_name} onChange={(event) => setPlatformForm((prev) => ({ ...prev, full_name: event.target.value }))} /></label>
              <label>Email<input value={platformForm.email} onChange={(event) => setPlatformForm((prev) => ({ ...prev, email: event.target.value }))} /></label>
              <label>Clave temporal<input type="password" value={platformForm.password} onChange={(event) => setPlatformForm((prev) => ({ ...prev, password: event.target.value }))} /></label>
              <label>Rol<select value={platformForm.platform_role} onChange={(event) => setPlatformForm((prev) => ({ ...prev, platform_role: event.target.value }))}>{platformRoles.map((role) => <option key={role} value={role}>{roleLabel(role, true)}</option>)}</select></label>
              <label>Estado<select value={platformForm.status} onChange={(event) => setPlatformForm((prev) => ({ ...prev, status: event.target.value }))}><option value="active">Activo</option><option value="paused">Pausado</option><option value="disabled">Deshabilitado</option></select></label>
              <label>Notas<input value={platformForm.notes} onChange={(event) => setPlatformForm((prev) => ({ ...prev, notes: event.target.value }))} /></label>
            </div>
            <label className="check-row compact-check"><input type="checkbox" checked={platformForm.send_email} onChange={(event) => setPlatformForm((prev) => ({ ...prev, send_email: event.target.checked }))} /><span>Enviar bienvenida por correo</span></label>
            <button type="button" className="primary" disabled={busy === "platform-create"} onClick={createPlatformAdmin}>{busy === "platform-create" ? "Guardando..." : "Crear admin"}</button>
          </article>
          <article className="panel glass-card">
            <div className="panel-head"><h2>Administradores plataforma</h2><span>{number(platformAdmins.length)}</span></div>
            <div className="table">{platformAdmins.map((admin) => <div className="row platform-user-row" key={admin.user_id}><span><strong>{admin.full_name || admin.email}</strong><small>{admin.email}</small></span><span><select value={admin.platform_role} disabled={busy === admin.user_id} onChange={(event) => patchPlatformAdmin(admin.user_id, { platform_role: event.target.value })}>{platformRoles.map((role) => <option key={role} value={role}>{roleLabel(role, true)}</option>)}</select></span><span><select value={admin.platform_status} disabled={busy === admin.user_id || admin.user_id === me?.user_id} onChange={(event) => patchPlatformAdmin(admin.user_id, { status: event.target.value })}><option value="active">Activo</option><option value="paused">Pausado</option><option value="disabled">Deshabilitado</option></select></span></div>)}</div>
          </article>
        </div>
      ) : null}

      {activeTab === "tenant" ? (
        <div className="admin-split wide-left">
          <article className="panel glass-card">
            <div className="panel-head"><h2>Crear usuario tenant</h2><span>empresa</span></div>
            <p className="panel-hint">Crea usuarios para una empresa especifica. Su rol define que puede ver y operar dentro del SaaS.</p>
            <div className="form-grid two">
              <label className="wide">Empresa<select value={tenantForm.tenant_id} onChange={(event) => setTenantForm((prev) => ({ ...prev, tenant_id: event.target.value }))}><option value="">Seleccionar empresa</option>{tenants.map((tenant) => <option key={tenant.id} value={tenant.id}>{tenant.name}</option>)}</select></label>
              <label>Nombre<input value={tenantForm.full_name} onChange={(event) => setTenantForm((prev) => ({ ...prev, full_name: event.target.value }))} /></label>
              <label>Email<input value={tenantForm.email} onChange={(event) => setTenantForm((prev) => ({ ...prev, email: event.target.value }))} /></label>
              <label>Clave temporal<input type="password" value={tenantForm.password} onChange={(event) => setTenantForm((prev) => ({ ...prev, password: event.target.value }))} /></label>
              <label>Rol<select value={tenantForm.role} onChange={(event) => setTenantForm((prev) => ({ ...prev, role: event.target.value }))}>{tenantRoles.map((role) => <option key={role} value={role}>{roleLabel(role)}</option>)}</select></label>
            </div>
            <label className="check-row compact-check"><input type="checkbox" checked={tenantForm.send_email} onChange={(event) => setTenantForm((prev) => ({ ...prev, send_email: event.target.checked }))} /><span>Enviar bienvenida por correo</span></label>
            <button type="button" className="primary" disabled={busy === "tenant-create" || !tenantForm.tenant_id} onClick={createTenantUser}>{busy === "tenant-create" ? "Guardando..." : "Crear usuario"}</button>
          </article>
          <article className="panel glass-card">
            <div className="panel-head"><h2>Usuarios por empresa</h2><span>{number(filteredTenantUsers.length)} / {number(tenantUsers.length)}</span></div>
            <div className="table-tools">
              <input value={tenantUserSearch} onChange={(event) => setTenantUserSearch(event.target.value)} placeholder="Buscar por nombre, correo, empresa, rol o estado..." />
              <button type="button" onClick={() => setTenantUserSearch("")}>Limpiar</button>
            </div>
            <div className="table">{filteredTenantUsers.map((member) => <div className="row user-row" key={member.id}><span><strong>{member.full_name || member.email}</strong><small>{member.email} / {member.tenant_name}</small></span><span><select value={member.role} disabled={busy === member.id} onChange={(event) => patchTenantUser(member.id, { role: event.target.value })}>{tenantRoles.map((role) => <option key={role} value={role}>{roleLabel(role)}</option>)}</select></span><span><mark className={member.is_active ? "ok" : "warn"}>{member.is_active ? "Activo" : "Inactivo"}</mark></span><span><button type="button" disabled={busy === member.id} onClick={() => patchTenantUser(member.id, { is_active: !member.is_active })}>{member.is_active ? "Desactivar" : "Activar"}</button></span></div>)}</div>
            {filteredTenantUsers.length === 0 ? <div className="empty">No hay usuarios que coincidan con la busqueda.</div> : null}
          </article>
        </div>
      ) : null}
    </section>
  );
}

function NotificationsAdminView({ targets, notifications, form, setForm, draftForm, setDraftForm, targetSearch, setTargetSearch, draftNotification, sendNotification, busy }) {
  const targetNeedle = targetSearch.trim().toLowerCase();
  const targetMatches = (values) => !targetNeedle || values.some((value) => String(value || "").toLowerCase().includes(targetNeedle));
  const filteredTenants = (targets.tenants || []).filter((tenant) => targetMatches([tenant.name, tenant.status, tenant.plan_code]));
  const filteredRoles = (targets.roles || Object.keys(TENANT_ROLE_LABELS)).filter((role) => targetMatches([role, roleLabel(role)]));
  const filteredUsers = (targets.users || []).filter((user) => targetMatches([user.full_name, user.email, user.tenant_name, user.role]));
  const selectedCount = form.audience_type === "all"
    ? number((targets.users || []).length)
    : number(new Set([...(form.user_ids || []), ...(form.tenant_ids || []), ...(form.roles || [])]).size);
  const toggleListValue = (key, value) => {
    setForm((prev) => {
      const current = new Set(prev[key] || []);
      if (current.has(value)) current.delete(value);
      else current.add(value);
      return { ...prev, [key]: Array.from(current), audience_type: "selected" };
    });
  };
  const setAudienceAll = () => setForm((prev) => ({ ...prev, audience_type: "all", tenant_ids: [], user_ids: [], roles: [] }));
  const setAudienceSelected = () => setForm((prev) => ({ ...prev, audience_type: "selected" }));
  return (
    <section className="stack admin-section">
      <div className="notification-compose-grid">
        <article className="panel glass-card">
          <div className="panel-head"><h2>Borrador asistido</h2><span>humano revisa y envia</span></div>
          <p className="panel-hint">La IA solo prepara un texto base segun el contexto. No se envia nada hasta que revises el mensaje y pulses Enviar.</p>
          <div className="form-grid two">
            <label>Tema<input value={draftForm.topic} onChange={(event) => setDraftForm((prev) => ({ ...prev, topic: event.target.value }))} placeholder="Mantenimiento, cambio de rol, aviso comercial..." /></label>
            <label>Audiencia<input value={draftForm.audience} onChange={(event) => setDraftForm((prev) => ({ ...prev, audience: event.target.value }))} placeholder="administradores, agentes, empresas..." /></label>
            <label>Tono<input value={draftForm.tone} onChange={(event) => setDraftForm((prev) => ({ ...prev, tone: event.target.value }))} /></label>
            <label>Urgencia<input value={draftForm.urgency} onChange={(event) => setDraftForm((prev) => ({ ...prev, urgency: event.target.value }))} /></label>
            <label className="wide">Contexto<textarea rows={4} value={draftForm.body_hint} onChange={(event) => setDraftForm((prev) => ({ ...prev, body_hint: event.target.value }))} /></label>
          </div>
          <button type="button" onClick={draftNotification} disabled={busy === "draft"}>{busy === "draft" ? "Generando..." : "Preparar borrador"}</button>
        </article>
        <article className="panel glass-card">
          <div className="panel-head"><h2>Enviar notificacion</h2><span>{targets.smtp_configured ? "correo disponible" : "solo app"}</span></div>
          <p className="panel-hint">Siempre se crea una notificacion interna en el Inbox del usuario. Si activas correo, tambien se envia una copia por email cuando SMTP este configurado.</p>
          <label>Titulo<input value={form.title} onChange={(event) => setForm((prev) => ({ ...prev, title: event.target.value }))} /></label>
          <label>Mensaje<textarea rows={6} value={form.body} onChange={(event) => setForm((prev) => ({ ...prev, body: event.target.value }))} /></label>
          <div className="form-grid two">
            <label>Severidad<select value={form.severity} onChange={(event) => setForm((prev) => ({ ...prev, severity: event.target.value }))}>{Object.entries(SEVERITY_LABELS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
            <label>Categoria<select value={form.category} onChange={(event) => setForm((prev) => ({ ...prev, category: event.target.value }))}>{Object.entries(CATEGORY_LABELS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
          </div>
          <label className="check-row compact-check"><input type="checkbox" checked={form.email_copy} onChange={(event) => setForm((prev) => ({ ...prev, email_copy: event.target.checked }))} /><span>Enviar copia por correo</span></label>
          <button type="button" className="primary" onClick={sendNotification} disabled={busy === "send"}>{busy === "send" ? "Enviando..." : "Enviar"}</button>
        </article>
      </div>
      <article className="panel glass-card">
        <div className="panel-head"><h2>Destinatarios</h2><span>{form.audience_type === "all" ? `Todos (${selectedCount})` : `${selectedCount} reglas`}</span></div>
        <div className="notification-help">
          <strong>Destino interno seguro</strong>
          <span>Estos avisos aparecen en el Inbox de Scentra, no son chats de clientes, no admiten respuesta y no activan IA, triggers ni remarketing.</span>
        </div>
        <div className="audience-toolbar">
          <button type="button" className={form.audience_type === "all" ? "active" : ""} onClick={setAudienceAll}>Para todos</button>
          <button type="button" className={form.audience_type !== "all" ? "active" : ""} onClick={setAudienceSelected}>Seleccionar</button>
          <input value={targetSearch} onChange={(event) => setTargetSearch(event.target.value)} placeholder="Buscar empresa, usuario, correo o rol..." />
          <button type="button" onClick={() => setTargetSearch("")}>Limpiar</button>
        </div>
        <div className="notification-targets">
          <div><strong>Empresas</strong>{filteredTenants.slice(0, 100).map((tenant) => <label className="check-row" key={tenant.id}><input type="checkbox" checked={(form.tenant_ids || []).includes(tenant.id)} onChange={() => toggleListValue("tenant_ids", tenant.id)} /><span>{tenant.name}<small>{tenant.plan_code || "plan"} / {tenant.status || "estado"}</small></span></label>)}{filteredTenants.length === 0 ? <small>Sin coincidencias.</small> : null}</div>
          <div><strong>Roles</strong>{filteredRoles.map((role) => <label className="check-row" key={role}><input type="checkbox" checked={(form.roles || []).includes(role)} onChange={() => toggleListValue("roles", role)} /><span>{roleLabel(role)}<small>{role}</small></span></label>)}{filteredRoles.length === 0 ? <small>Sin coincidencias.</small> : null}</div>
          <div><strong>Usuarios</strong>{filteredUsers.slice(0, 180).map((user) => <label className="check-row" key={`${user.tenant_id}-${user.user_id}`}><input type="checkbox" checked={(form.user_ids || []).includes(user.user_id)} onChange={() => toggleListValue("user_ids", user.user_id)} /><span>{user.full_name || user.email}<small>{user.email} / {user.tenant_name}</small></span></label>)}{filteredUsers.length === 0 ? <small>Sin coincidencias.</small> : null}</div>
        </div>
      </article>
      <article className="panel glass-card">
        <div className="panel-head"><h2>Historial</h2><span>{number(notifications.length)}</span></div>
        <div className="table">{notifications.map((item) => <div className="row notification-row" key={item.id}><span><strong>{item.title}</strong><small>{SEVERITY_LABELS[item.severity] || item.severity} / {categoryLabel(item.category)}</small></span><span>{number(item.recipients)} destinatarios</span><span>{number(item.read_count)} leidas</span><span>{number(item.email_sent_count)} correos</span></div>)}</div>
      </article>
    </section>
  );
}

function SecurityView({ security, compliance, updateAdminTwoFactor, downloadAuditCsv }) {
  const eventCounts = Object.fromEntries((compliance?.security_events_24h || []).map((item) => [item.status, item.total]));
  const privacyCounts = Object.fromEntries((compliance?.privacy_requests || []).map((item) => [item.status, item.total]));
  return (
    <section className="grid">
      <Metric title="Usuarios 2FA" value={`${number(compliance?.users?.two_factor_enabled || 0)}/${number(compliance?.users?.total || 0)}`} hint={`${number(compliance?.users?.locked || 0)} bloqueados`} />
      <Metric title="Admins sin 2FA" value={number(compliance?.platform_admins?.without_two_factor || 0)} hint={`${number(compliance?.platform_admins?.total || 0)} admins activos`} tone={(compliance?.platform_admins?.without_two_factor || 0) ? "amber" : "mint"} />
      <Metric title="Webhooks firmados" value={`${number(compliance?.webhooks?.signature_required || 0)}/${number(compliance?.webhooks?.total || 0)}`} hint="HMAC requerido" />
      <Metric title="Eventos fallidos 24h" value={number(eventCounts.failed || 0)} hint={`${number(eventCounts.blocked || 0)} bloqueados`} tone={(eventCounts.failed || eventCounts.blocked) ? "amber" : "mint"} />
      <article className="panel glass-card">
        <div className="panel-head"><h2>Seguridad Admin</h2><span>{security?.two_factor_enabled ? "2FA activo" : "2FA inactivo"}</span></div>
        <p>Metodo: {security?.two_factor_method || "none"} / SMTP: {security?.smtp_configured ? "configurado" : "no configurado"}</p>
        {security?.password_changed_at ? <p>Clave cambiada: {security.password_changed_at}</p> : null}
        <div className="panel-actions">
          <button type="button" className="primary" onClick={() => updateAdminTwoFactor(!security?.two_factor_enabled)}>{security?.two_factor_enabled ? "Desactivar 2FA" : "Activar 2FA email"}</button>
          <button type="button" onClick={downloadAuditCsv}>Exportar auditoria CSV</button>
        </div>
      </article>
      <article className="panel glass-card">
        <div className="panel-head"><h2>Compliance</h2><span>controles</span></div>
        <div className="table">
          <div className="row"><span>CAPTCHA</span><span>{compliance?.environment?.captcha_enabled ? "activo" : "inactivo"}</span></div>
          <div className="row"><span>Rate limiting</span><span>{compliance?.environment?.rate_limit_enabled ? "activo" : "inactivo"}</span></div>
          <div className="row"><span>JWT secret default</span><span className={compliance?.environment?.jwt_secret_default ? "danger" : "ok"}>{compliance?.environment?.jwt_secret_default ? "riesgo" : "ok"}</span></div>
          <div className="row"><span>Privacy requests</span><span>{number(privacyCounts.pending || 0)} pendientes</span></div>
        </div>
      </article>
    </section>
  );
}


function AuditView({ audit }) {
  return (
    <section className="panel glass-card">
      <div className="panel-head"><h2>Auditoria</h2><span>{number(audit.length)}</span></div>
      <div className="table">{audit.map((item) => <div className="row audit-row" key={item.id}><span>{item.created_at}</span><span><strong>{item.action}</strong><small>{item.actor_email || "system"}</small></span><span>{item.tenant_name || "-"}</span><span>{item.resource_type}</span><span>{item.resource_id}</span></div>)}</div>
    </section>
  );
}
