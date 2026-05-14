import React, { useEffect, useMemo, useRef, useState } from "react";
import CrmPanel from "./CrmPanel.jsx";
import LabelsPanel from "./LabelsPanel.jsx";
import CampaignsPanel from "./CampaignsPanel.jsx";
import BroadcastPanel from "./BroadcastPanel.jsx";
import AdsPanel from "./AdsPanel.jsx";

const API_BASE = (import.meta.env.VITE_API_BASE || "").replace(/\/$/, "");
const TOKEN_KEY = "scentra_ai_access_token";
const REFRESH_KEY = "scentra_ai_refresh_token";

const AI_API_PROVIDERS = [
  { name: "Google / Gemini", env: "GOOGLE_AI_API_KEY", alt: "GEMINI_API_KEY", models: "gemini-2.5-flash, gemini-2.5-pro, gemma-3-*" },
  { name: "Groq", env: "GROQ_API_KEY", alt: "", models: "llama-3.1-8b-instant, llama-3.1-70b-versatile" },
  { name: "Mistral", env: "MISTRAL_API_KEY", alt: "", models: "mistral-small-latest, mistral-medium-latest" },
  { name: "OpenRouter", env: "OPENROUTER_API_KEY", alt: "OPENROUTER_SITE / OPENROUTER_APP_NAME", models: "google/gemma-2-9b-it y catalogo live" },
];

const TTS_API_PROVIDERS = [
  { name: "ElevenLabs", env: "ELEVENLABS_API_KEY", fields: "ELEVENLABS_VOICE_ID, ELEVENLABS_MODEL_ID" },
  { name: "Google Cloud TTS", env: "GOOGLE_CLOUD_TTS_API_KEY", fields: "GOOGLE_TTS_LANGUAGE_CODE, GOOGLE_TTS_VOICE_NAME" },
  { name: "Piper local", env: "PIPER_BIN", fields: "PIPER_MODEL_PATH" },
];

const CHANNEL_API_PROVIDERS = [
  { name: "WhatsApp Cloud API", env: "WHATSAPP_PERMANENT_TOKEN", fields: ["WHATSAPP_TOKEN", "META_ACCESS_TOKEN", "WHATSAPP_PHONE_NUMBER_ID", "WHATSAPP_WABA_ID", "META_APP_ID", "WHATSAPP_GRAPH_VERSION"] },
  { name: "WooCommerce", env: "WC_BASE_URL", fields: ["WC_CONSUMER_KEY", "WC_CONSUMER_SECRET"] },
];

const FEATURE_LABELS = {
  inbox: "Inbox",
  ai: "IA comercial",
  broadcast: "Mensajeria masiva",
  triggers: "Triggers CRM",
  remarketing: "Remarketing",
  ads: "Ads Manager",
  whatsapp_cloud: "WhatsApp Cloud",
  elevenlabs_voice: "Voz ElevenLabs",
};

const NAV_ITEMS = [
  { key: "dashboard", label: "Dashboard" },
  { key: "inbox", label: "Inbox" },
  { key: "customers", label: "Clientes" },
  { key: "labels", label: "Etiquetas" },
  { key: "campaigns", label: "Campanas" },
  { key: "broadcast", label: "Mensajeria" },
  { key: "ads", label: "Ads Manager" },
  { key: "settings", label: "Ajustes" },
];

const defaultRegister = () => ({ email: "", password: "", full_name: "", tenant_name: "", tenant_slug: "" });
const defaultAiConfig = () => ({
  enabled: true,
  provider: "google",
  model: "Gemini 2.5 Flash",
  systemPrompt: "IDENTIDAD Y ROL: Scentra +AI\n\nEres una asesora comercial experta. Responde con tono humano, claro y orientado a convertir conversaciones en ventas.",
  maxTokens: "2000",
  temperature: "0.5",
  fallbackProvider: "groq",
  fallbackModel: "llama-3.1-8b-instant",
  chunks: "480",
  delayBetween: "4000",
  typingDelay: "4000",
  cooldown: "6",
  voiceEnabled: true,
  preferVoice: false,
  ttsProvider: "elevenlabs",
  voiceName: "Linda Gomez - Energetic and Upbeat",
  voiceId: "TsKSGPuG26FpNj0JzQBq",
  voiceModel: "eleven_v3",
  voicePrompt: "Voz de mujer colombiana joven, acento colombiano natural, tono alegre, espontaneo y cercano.",
});

function formatApiError(data, fallback) {
  const detail = data?.detail || data?.error;
  if (Array.isArray(detail)) {
    return detail.map((item) => {
      const path = Array.isArray(item.loc) ? item.loc.filter((part) => part !== "body").join(".") : "";
      return `${path ? `${path}: ` : ""}${item.msg || "dato invalido"}`;
    }).join(" | ");
  }
  if (detail && typeof detail === "object") {
    if (detail.code === "plan_limit_reached") return `Limite de plan alcanzado: ${detail.metric} (${detail.used}/${detail.limit}).`;
    if (detail.code === "feature_not_enabled") return `Modulo no incluido o desactivado: ${FEATURE_LABELS[detail.feature] || detail.feature}.`;
    if (detail.code === "tenant_not_operational") return `Empresa no habilitada para operar. Estado: ${detail.status || "desconocido"}.`;
    return detail.message || detail.code || fallback;
  }
  return typeof detail === "string" ? detail : fallback;
}

function todayLabel() {
  return new Intl.DateTimeFormat("es-CO", { weekday: "short", day: "2-digit", month: "short", year: "numeric" }).format(new Date());
}
const pct = (used, limit) => (!Number(limit || 0) ? 0 : Math.min(100, Math.round((Number(used || 0) / Number(limit || 0)) * 100)));
const number = (value) => Number(value || 0).toLocaleString("es-CO");
const fullWebhookUrl = (path) => {
  const cleanPath = String(path || "").trim();
  if (!cleanPath) return "";
  if (/^https?:\/\//i.test(cleanPath)) return cleanPath;
  return `${API_BASE}${cleanPath.startsWith("/") ? cleanPath : `/${cleanPath}`}`;
};
const dateLabel = (value) => {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat("es-CO", { day: "2-digit", month: "short", year: "numeric" }).format(date);
};
const lifecycleLabel = (status) => ({
  trial: "Demo",
  active: "Activo",
  past_due: "Pago pendiente",
  suspended: "Suspendido",
  cancelled: "Cancelado",
  paused: "Pausado",
  none: "Sin suscripcion",
}[String(status || "").toLowerCase()] || String(status || "Activo"));

function App() {
  const metaAccessTokenRef = useRef(null);
  const [accessToken, setAccessToken] = useState(() => localStorage.getItem(TOKEN_KEY) || "");
  const [refreshToken, setRefreshToken] = useState(() => localStorage.getItem(REFRESH_KEY) || "");
  const [mode, setMode] = useState("login");
  const [login, setLogin] = useState({ email: "", password: "" });
  const [register, setRegister] = useState(defaultRegister);
  const [me, setMe] = useState(null);
  const [tenants, setTenants] = useState([]);
  const [activeView, setActiveView] = useState("dashboard");
  const [settingsTab, setSettingsTab] = useState("ia");
  const [webhookProvider, setWebhookProvider] = useState("whatsapp");
  const [webhookSignatureRequired, setWebhookSignatureRequired] = useState(false);
  const [webhooks, setWebhooks] = useState([]);
  const [webhookEvents, setWebhookEvents] = useState([]);
  const [lastWebhookSecret, setLastWebhookSecret] = useState(null);
  const [integrations, setIntegrations] = useState([]);
  const [billingOverview, setBillingOverview] = useState(null);
  const [billingPlans, setBillingPlans] = useState([]);
  const [dashboardOverview, setDashboardOverview] = useState(null);
  const [integrationForm, setIntegrationForm] = useState({ provider: "meta", channel: "whatsapp", status: "connected", dispatch_mode: "stub", phone_number_id: "", business_account_id: "", graph_api_version: "v24.0", access_token_env: "SCENTRA_META_ACCESS_TOKEN" });
  const [aiConfig, setAiConfig] = useState(defaultAiConfig);
  const [aiTesterOpen, setAiTesterOpen] = useState(false);
  const [aiTest, setAiTest] = useState({ phone: "", message: "" });
  const [profileForm, setProfileForm] = useState({ fullName: "", email: "", phone: "", role: "", avatarUrl: "" });
  const [securityForm, setSecurityForm] = useState({ currentPassword: "", newPassword: "", confirmPassword: "", twoFactorEnabled: false });
  const [apiSecrets, setApiSecrets] = useState({});
  const [conversations, setConversations] = useState([]);
  const [selectedConversation, setSelectedConversation] = useState(null);
  const [messages, setMessages] = useState([]);
  const [replyText, setReplyText] = useState("");
  const [status, setStatus] = useState("");
  const [statusTone, setStatusTone] = useState("neutral");

  const headers = useMemo(() => {
    const base = { "Content-Type": "application/json" };
    if (accessToken) base.Authorization = `Bearer ${accessToken}`;
    return base;
  }, [accessToken]);

  const activeCompany = tenants.find((company) => company.tenant_id === me?.tenant_id);
  const billingPlan = billingOverview?.plan || {};
  const billingLimits = billingPlan?.limits || {};
  const billingUsage = billingOverview?.usage || {};
  const billingRemaining = billingOverview?.remaining || {};
  const subscription = billingOverview?.subscription || {};
  const subscriptionStatus = subscription.status || activeCompany?.subscription_status || "none";
  const lifecycleStatus = subscriptionStatus !== "none" ? subscriptionStatus : (billingPlan.tenant_status || activeCompany?.tenant_status || "active");
  const trialEndsAt = subscriptionStatus === "trial" ? subscription.current_period_end : activeCompany?.trial_ends_at;
  const trialEndLabel = dateLabel(trialEndsAt);
  const featureFlags = billingOverview?.features || {};
  const featureLoaded = Boolean(billingOverview?.features);
  const hasFeature = (key) => !featureLoaded || featureFlags[key] !== false;
  const moduleAccess = {
    dashboard: true,
    inbox: hasFeature("inbox"),
    customers: true,
    labels: true,
    campaigns: hasFeature("triggers") || hasFeature("remarketing"),
    broadcast: hasFeature("broadcast"),
    ads: hasFeature("ads"),
    settings: true,
  };
  const activeViewAllowed = moduleAccess[activeView] !== false;
  const navItems = NAV_ITEMS.filter((item) => moduleAccess[item.key] !== false);
  const unreadTotal = conversations.reduce((sum, item) => sum + Number(item.unread_count || 0), 0);
  const connectedIntegrations = integrations.filter((item) => item.status !== "disconnected").length;
  const activeWebhooks = webhooks.filter((item) => item.is_active).length;
  const dashboardTotals = dashboardOverview?.totals || {};
  const dashboardFunnel = dashboardOverview?.funnel || [];
  const dashboardActivity = dashboardOverview?.activity || [];
  const dashboardRecent = dashboardOverview?.recent || [];
  const dashboardChannels = dashboardOverview?.channels || [];
  const dashboardActivityMax = Math.max(1, ...dashboardActivity.map((item) => Number(item.total || 0)));
  const dashboardConversations = Number(dashboardTotals.conversations ?? conversations.length);
  const dashboardUnread = Number(dashboardTotals.unread ?? unreadTotal);
  const viewTitles = {
    dashboard: ["Dashboard", "Vista ejecutiva de la empresa y operacion comercial."],
    inbox: ["Inbox", "Conversaciones entrantes y respuestas asistidas."],
    customers: ["Clientes", "CRM comercial, perfil del cliente y seguimiento."],
    labels: ["Etiquetas", "Segmentacion visual para ventas, soporte y automatizaciones."],
    campaigns: ["Campanas CRM", "Plantillas, triggers, remarketing y recorridos comerciales."],
    broadcast: ["Mensajeria masiva", "Difusiones por audiencia con control de limites y canales."],
    ads: ["Ads Manager", "Leads, comentarios y eventos de Meta conectados al inbox."],
    settings: ["Ajustes", "IA, canales, webhooks, APIs, usuarios y seguridad."],
  };

  const showStatus = (text, tone = "neutral") => { setStatus(text); setStatusTone(tone); };
  const apiCall = async (path, options = {}) => {
    if (!API_BASE) throw new Error("VITE_API_BASE requerido");
    const requestHeaders = { ...headers, ...(options.headers || {}) };
    if (options.body instanceof FormData) delete requestHeaders["Content-Type"];
    const res = await fetch(`${API_BASE}${path}`, { ...options, headers: requestHeaders });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(formatApiError(data, `HTTP ${res.status}`));
    return data;
  };

  const setTokens = (data) => {
    const nextAccess = data?.access_token || "";
    const nextRefresh = data?.refresh_token || refreshToken || "";
    setAccessToken(nextAccess);
    setRefreshToken(nextRefresh);
    if (nextAccess) localStorage.setItem(TOKEN_KEY, nextAccess);
    if (nextRefresh) localStorage.setItem(REFRESH_KEY, nextRefresh);
  };

  const clearWorkspaceState = () => {
    setConversations([]); setSelectedConversation(null); setMessages([]); setReplyText("");
    setIntegrations([]); setWebhooks([]); setWebhookEvents([]); setBillingOverview(null); setBillingPlans([]); setLastWebhookSecret(null);
  };

  const clearTokens = () => {
    setAccessToken(""); setRefreshToken(""); setMe(null); setTenants([]); clearWorkspaceState();
    localStorage.removeItem(TOKEN_KEY); localStorage.removeItem(REFRESH_KEY);
  };

  const loadSession = async () => {
    if (!accessToken) return;
    try {
      const data = await apiCall("/saas/v1/auth/me");
      setMe(data); setTenants(data?.tenants || []);
    } catch (err) { showStatus(String(err.message || err), "error"); }
  };

  const loadWebhooks = async () => {
    if (!accessToken) return;
    try {
      const [endpointData, eventData] = await Promise.all([apiCall("/saas/v1/webhooks/endpoints"), apiCall("/saas/v1/webhooks/events?limit=50")]);
      setWebhooks(endpointData || []); setWebhookEvents(eventData || []);
    } catch (err) { showStatus(String(err.message || err), "error"); }
  };

  const loadIntegrations = async () => {
    if (!accessToken) return;
    try { setIntegrations((await apiCall("/saas/v1/integrations")) || []); }
    catch (err) { showStatus(String(err.message || err), "error"); }
  };

  const loadBilling = async () => {
    if (!accessToken) return;
    try {
      const [overviewData, plansData] = await Promise.all([apiCall("/saas/v1/billing/overview"), apiCall("/saas/v1/billing/plans")]);
      setBillingOverview(overviewData); setBillingPlans(plansData?.plans || []);
    } catch (err) { showStatus(String(err.message || err), "error"); }
  };

  const loadDashboard = async (silent = false) => {
    if (!accessToken) return;
    try {
      const [overviewData, dashboardData, inboxData, integrationData, endpointData, eventData, plansData] = await Promise.all([
        apiCall("/saas/v1/billing/overview"), apiCall("/saas/v1/dashboard/overview"), apiCall("/saas/v1/conversations?limit=100"), apiCall("/saas/v1/integrations"),
        apiCall("/saas/v1/webhooks/endpoints"), apiCall("/saas/v1/webhooks/events?limit=20"), apiCall("/saas/v1/billing/plans"),
      ]);
      setBillingOverview(overviewData); setDashboardOverview(dashboardData); setConversations(inboxData?.conversations || []); setIntegrations(integrationData || []);
      setWebhooks(endpointData || []); setWebhookEvents(eventData || []); setBillingPlans(plansData?.plans || []);
      if (!silent) showStatus("Dashboard actualizado", "ok");
    } catch (err) { showStatus(String(err.message || err), "error"); }
  };

  const loadMessages = async (conversation) => {
    if (!conversation?.id) return;
    try {
      const data = await apiCall(`/saas/v1/conversations/${encodeURIComponent(conversation.id)}/messages`);
      setSelectedConversation(conversation); setMessages(data?.messages || []); setReplyText("");
    } catch (err) { showStatus(String(err.message || err), "error"); }
  };

  const loadInbox = async () => {
    if (!accessToken) return;
    try {
      const data = await apiCall("/saas/v1/conversations?limit=100");
      const items = data?.conversations || [];
      setConversations(items);
      if (items.length && !selectedConversation) await loadMessages(items[0]);
      if (!items.length) { setSelectedConversation(null); setMessages([]); setReplyText(""); }
    } catch (err) { showStatus(String(err.message || err), "error"); }
  };

  useEffect(() => {
    const rawHash = String(window.location.hash || "").replace(/^#/, "");
    if (!rawHash) return;
    const params = new URLSearchParams(rawHash);
    const supportToken = params.get("support_token") || "";
    if (!supportToken) return;
    localStorage.setItem(TOKEN_KEY, supportToken);
    setAccessToken(supportToken);
    window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}`);
    showStatus("Acceso de soporte activado", "ok");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => { loadSession(); }, [accessToken]);
  useEffect(() => {
    if (accessToken && ["dashboard", "customers", "labels", "campaigns", "broadcast", "ads"].includes(activeView)) loadDashboard(true);
    if (accessToken && activeView === "settings") Promise.all([loadIntegrations(), loadWebhooks(), loadBilling()]);
    if (accessToken && activeView === "inbox") loadInbox();
  }, [accessToken, activeView]);

  useEffect(() => {
    if (!featureLoaded || activeViewAllowed) return;
    const label = NAV_ITEMS.find((item) => item.key === activeView)?.label || "modulo";
    setActiveView("dashboard");
    showStatus(`${label} no esta activo para este plan o empresa.`, "neutral");
  }, [featureLoaded, activeViewAllowed, activeView]);

  const submitLogin = async (event) => {
    event.preventDefault();
    try {
      const data = await apiCall("/saas/v1/auth/login", { method: "POST", body: JSON.stringify(login) });
      setTokens(data); setTenants(data?.tenants || []); setActiveView("dashboard"); showStatus("Ingreso correcto", "ok");
    } catch (err) { showStatus(String(err.message || err), "error"); }
  };

  const submitRegister = async (event) => {
    event.preventDefault();
    if (register.password.length < 8) return showStatus("La clave debe tener al menos 8 caracteres.", "error");
    if (register.tenant_name.trim().length < 2) return showStatus("El nombre de la empresa debe tener al menos 2 caracteres.", "error");
    try {
      const data = await apiCall("/saas/v1/auth/register", { method: "POST", body: JSON.stringify(register) });
      setTokens(data); setTenants(data?.tenants || []); setRegister(defaultRegister()); setActiveView("dashboard"); showStatus("Empresa creada", "ok");
    } catch (err) { showStatus(String(err.message || err), "error"); }
  };

  const switchCompany = async (companyId) => {
    try {
      const data = await apiCall("/saas/v1/auth/switch-tenant", { method: "POST", body: JSON.stringify({ tenant_id: companyId }) });
      setTokens(data); setMe((prev) => ({ ...(prev || {}), tenant_id: data.tenant_id, role: data.role })); clearWorkspaceState(); showStatus("Empresa actualizada", "ok");
    } catch (err) { showStatus(String(err.message || err), "error"); }
  };

  const createWebhook = async () => {
    try {
      const data = await apiCall("/saas/v1/webhooks/endpoints", { method: "POST", body: JSON.stringify({ provider: webhookProvider, signature_required: webhookSignatureRequired }) });
      setLastWebhookSecret(data); showStatus("Endpoint webhook creado", "ok"); await loadWebhooks();
    } catch (err) { showStatus(String(err.message || err), "error"); }
  };

  const saveIntegration = async (event) => {
    event.preventDefault();
    const accessTokenEnv = (integrationForm.access_token_env || "SCENTRA_META_ACCESS_TOKEN").trim();
    const accessToken = (metaAccessTokenRef.current?.value || "").trim();
    const phoneNumberId = (integrationForm.phone_number_id || "").trim();
    const dispatchMode = (integrationForm.dispatch_mode || "stub").trim();
    if (dispatchMode !== "stub" && !phoneNumberId) return showStatus("Phone Number ID requerido para Meta Cloud real.", "error");
    try {
      const configJson = { dispatch_mode: dispatchMode, phone_number_id: phoneNumberId, business_account_id: (integrationForm.business_account_id || "").trim(), graph_api_version: (integrationForm.graph_api_version || "v24.0").trim(), access_token_env: accessTokenEnv };
      if (accessToken) configJson.access_token = accessToken;
      await apiCall("/saas/v1/integrations", { method: "POST", body: JSON.stringify({ provider: integrationForm.provider, channel: integrationForm.channel, status: integrationForm.status, secret_ref: accessToken ? "tenant:meta:whatsapp" : dispatchMode === "stub" ? "" : `env:${accessTokenEnv}`, config_json: configJson }) });
      if (metaAccessTokenRef.current) metaAccessTokenRef.current.value = "";
      showStatus("Integracion guardada", "ok"); await loadIntegrations(); await loadBilling();
    } catch (err) { showStatus(String(err.message || err), "error"); }
  };

  const copyText = async (value, label = "Texto") => {
    const text = String(value || "").trim();
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      showStatus(`${label} copiado`, "ok");
    } catch (err) {
      showStatus("No se pudo copiar automaticamente. Selecciona el texto y copialo manualmente.", "error");
    }
  };
  const updateWebhookEndpoint = async (endpoint, patch) => { try { await apiCall(`/saas/v1/webhooks/endpoints/${encodeURIComponent(endpoint.id)}`, { method: "PATCH", body: JSON.stringify(patch) }); showStatus("Endpoint actualizado", "ok"); await loadWebhooks(); } catch (err) { showStatus(String(err.message || err), "error"); } };
  const rotateWebhookToken = async (endpoint) => { try { const data = await apiCall(`/saas/v1/webhooks/endpoints/${encodeURIComponent(endpoint.id)}/rotate-token`, { method: "POST" }); setLastWebhookSecret(data); showStatus("Verify token rotado", "ok"); await loadWebhooks(); } catch (err) { showStatus(String(err.message || err), "error"); } };
  const rotateWebhookSignature = async (endpoint) => { try { const data = await apiCall(`/saas/v1/webhooks/endpoints/${encodeURIComponent(endpoint.id)}/rotate-signature`, { method: "POST" }); setLastWebhookSecret(data); showStatus("Firma HMAC rotada", "ok"); await loadWebhooks(); } catch (err) { showStatus(String(err.message || err), "error"); } };
  const processWebhookEvents = async () => { try { const data = await apiCall("/saas/v1/webhooks/events/process", { method: "POST" }); showStatus(`Procesados: ${data?.result?.processed || 0}`, "ok"); await loadWebhooks(); } catch (err) { showStatus(String(err.message || err), "error"); } };
  const markSelectedConversationRead = async () => { if (!selectedConversation?.id) return; try { await apiCall(`/saas/v1/conversations/${selectedConversation.id}/read`, { method: "POST" }); showStatus("Conversacion marcada como leida", "ok"); await loadInbox(); } catch (err) { showStatus(String(err.message || err), "error"); } };
  const sendSelectedMessage = async (event) => { event.preventDefault(); if (!selectedConversation?.id || !replyText.trim()) return; try { await apiCall(`/saas/v1/conversations/${encodeURIComponent(selectedConversation.id)}/messages`, { method: "POST", body: JSON.stringify({ text: replyText }) }); showStatus("Mensaje encolado para envio", "ok"); setReplyText(""); await loadMessages(selectedConversation); await loadInbox(); } catch (err) { showStatus(String(err.message || err), "error"); } };
  const changePlanDev = async (planCode) => { try { const data = await apiCall("/saas/v1/billing/dev/change-plan", { method: "POST", body: JSON.stringify({ plan_code: planCode }) }); setBillingOverview(data); showStatus(`Plan actualizado a ${planCode}`, "ok"); await loadSession(); } catch (err) { showStatus(String(err.message || err), "error"); } };
  const saveAiLocal = () => showStatus("Ajustes IA guardados localmente. Falta conectar endpoint persistente.", "ok");
  const saveProfileLocal = () => showStatus("Perfil preparado. Falta conectar persistencia de usuario y foto.", "ok");
  const saveSecurityLocal = () => showStatus("Seguridad preparada. Cambio de clave y 2FA requieren endpoints backend.", "neutral");
  const saveApiSecretsLocal = () => showStatus("Credenciales preparadas. En produccion deben guardarse cifradas o en secret manager.", "neutral");
  const submitAiTest = (event) => { event.preventDefault(); showStatus("Prueba IA preparada. El endpoint se conectara en la siguiente fase.", "neutral"); setAiTesterOpen(false); };

  const isLogged = Boolean(accessToken && me);

  if (!isLogged) {
    return (
      <main className="auth-page">
        <section className="auth-card glass-card">
          <div className="auth-brand"><span className="auth-logo">S</span><h1>Scentra +AI</h1><p>{mode === "login" ? "Control de conversaciones, IA y ventas." : "Crea tu empresa y empieza a configurar."}</p></div>
          {status ? <div className={`status ${statusTone}`}>{status}</div> : null}
          {mode === "login" ? (
            <form className="auth-form" onSubmit={submitLogin}>
              <label>Email</label><div className="input-wrap"><span>@</span><input autoComplete="email" inputMode="email" value={login.email} onChange={(event) => setLogin((prev) => ({ ...prev, email: event.target.value }))} /></div>
              <label>Password</label><div className="input-wrap"><span>key</span><input autoComplete="current-password" type="password" value={login.password} onChange={(event) => setLogin((prev) => ({ ...prev, password: event.target.value }))} /></div>
              <button className="primary auth-submit" type="submit">Entrar</button>
              <div className="auth-links"><button type="button">Recuperar clave</button><button type="button" onClick={() => setMode("register")}>Crear cuenta</button></div>
            </form>
          ) : (
            <form className="auth-form" onSubmit={submitRegister}>
              <label>Email owner</label><div className="input-wrap"><span>@</span><input autoComplete="email" inputMode="email" value={register.email} onChange={(event) => setRegister((prev) => ({ ...prev, email: event.target.value }))} /></div>
              <label>Password</label><div className="input-wrap"><span>key</span><input autoComplete="new-password" type="password" minLength={8} value={register.password} onChange={(event) => setRegister((prev) => ({ ...prev, password: event.target.value }))} /></div><small className="field-hint">Minimo 8 caracteres.</small>
              <label>Nombre</label><div className="input-wrap"><span>id</span><input autoComplete="name" value={register.full_name} onChange={(event) => setRegister((prev) => ({ ...prev, full_name: event.target.value }))} /></div>
              <label>Empresa</label><div className="input-wrap"><span>co</span><input autoComplete="organization" value={register.tenant_name} onChange={(event) => setRegister((prev) => ({ ...prev, tenant_name: event.target.value }))} /></div>
              <label>Slug publico</label><div className="input-wrap"><span>#</span><input autoComplete="off" value={register.tenant_slug} onChange={(event) => setRegister((prev) => ({ ...prev, tenant_slug: event.target.value }))} /></div>
              <small className="field-hint">Tu cuenta inicia con demo de 30 dias en el plan basico. Luego el admin puede activar el plan final.</small>
              <button className="primary auth-submit" type="submit">Crear demo 30 dias</button>
              <div className="auth-links"><button type="button" onClick={() => setMode("login")}>Volver al login</button></div>
            </form>
          )}
        </section>
      </main>
    );
  }

  return (
    <div className="app-shell">
      <aside className="sidebar glass-panel">
        <div className="brand"><span className="brand-mark">S</span><div><strong>Scentra +AI</strong><small>Sales intelligence cockpit</small></div></div>
        <nav>
          {navItems.map(({ key, label }) => <button key={key} className={"nav-item " + (activeView === key ? "active" : "")} onClick={() => setActiveView(key)}>{label}</button>)}
        </nav>
        <div className="company-card"><span>Empresa activa</span><strong>{activeCompany?.tenant_name || activeCompany?.name || me.tenant_id}</strong><small>{me.role} / plan {billingPlan.display_name || billingPlan.plan_code || activeCompany?.plan_code || "starter"}</small><span className={`mini-badge ${String(lifecycleStatus).toLowerCase()}`}>{lifecycleLabel(lifecycleStatus)}{trialEndLabel ? ` hasta ${trialEndLabel}` : ""}</span></div>
      </aside>

      <main className="content">
        <header className="topbar glass-panel">
          <div><p className="eyebrow">{todayLabel()}</p><h1>{viewTitles[activeView]?.[0]}</h1><p>{viewTitles[activeView]?.[1]}</p></div>
          <div className="top-actions"><select value={me.tenant_id || ""} onChange={(event) => switchCompany(event.target.value)} aria-label="Empresa activa">{tenants.map((company) => <option key={company.tenant_id} value={company.tenant_id}>{company.tenant_name || company.name} / {company.role}</option>)}</select><button type="button" onClick={clearTokens}>Salir</button></div>
        </header>
        {status ? <div className={`status floating-status ${statusTone}`}>{status}</div> : null}

        {activeView === "dashboard" ? (
          <section className="dashboard-page">
            <div className="hero-card glass-card"><div><p className="eyebrow">Resumen operativo</p><h2>Bienvenido, {me.email}</h2><p>Datos reales de la empresa activa: CRM, inbox, mensajes, webhooks y consumo del plan.</p>{lifecycleStatus === "trial" ? <p className="trial-note">Demo de 30 dias activa{trialEndLabel ? ` hasta ${trialEndLabel}` : ""}. Puedes configurar Meta, IA y plantillas antes de pasar a pago.</p> : null}</div><button type="button" className="icon-button" onClick={() => loadDashboard(false)}>Actualizar</button></div>
            <div className="metric-grid">
              <article className="metric-card mint"><span>Estado cuenta</span><strong>{lifecycleLabel(lifecycleStatus)}</strong><small>{trialEndLabel ? `Termina ${trialEndLabel}` : "Operativa"}</small></article>
              <article className="metric-card mint"><span>Clientes CRM</span><strong>{number(dashboardConversations)}</strong><small>Registros por empresa</small></article>
              <article className="metric-card blue"><span>No leidos</span><strong>{number(dashboardUnread)}</strong><small>Pendientes en inbox</small></article>
              <article className="metric-card amber"><span>Mensajes 30d</span><strong>{number(dashboardTotals.messages_30d || 0)}</strong><small>{number(dashboardTotals.inbound_30d || 0)} IN / {number(dashboardTotals.outbound_30d || 0)} OUT</small></article>
              <article className="metric-card rose"><span>Clientes nuevos</span><strong>{number(dashboardTotals.new_customers_30d || 0)}</strong><small>Ultimos 30 dias</small></article>
              <article className="metric-card violet"><span>Integraciones</span><strong>{number(connectedIntegrations)} / {number(billingLimits.max_integrations)}</strong><small>{number(activeWebhooks)} webhooks activos</small></article>
            </div>
            <section className="dashboard-layout">
              <article className="panel glass-card wide-panel"><div className="panel-head"><h2>Funnel comercial</h2><span>CRM real por etapa</span></div>{dashboardFunnel.length ? dashboardFunnel.map((item) => <div className="funnel-line" key={item.stage}><div><span>{item.label}</span><small>{number(item.count)} / {number(item.pct)}%</small></div><div className="meter"><span style={{ width: `${Math.max(2, Number(item.pct || 0))}%` }} /></div></div>) : <div className="empty">Aun no hay clientes para calcular funnel.</div>}</article>
              <article className="panel glass-card"><div className="panel-head"><h2>Uso del plan</h2><span>{billingOverview?.period_yyyymm || "periodo"}</span></div><div className="usage-bars"><div className="usage-line"><div><strong>Mensajes</strong><span>{number(billingRemaining.monthly_messages)} disponibles</span></div><div className="meter"><span style={{ width: `${pct(billingUsage.used_monthly_messages, billingLimits.max_monthly_messages)}%` }} /></div></div><div className="usage-line"><div><strong>Integraciones</strong><span>{number(billingRemaining.integrations)} disponibles</span></div><div className="meter"><span style={{ width: `${pct(billingUsage.used_integrations, billingLimits.max_integrations)}%` }} /></div></div><div className="usage-line"><div><strong>Usuarios</strong><span>{number(billingRemaining.agents)} disponibles</span></div><div className="meter"><span style={{ width: `${pct(billingUsage.used_agents, billingLimits.max_agents)}%` }} /></div></div></div></article>
              <article className="panel glass-card chart-panel"><div className="panel-head"><h2>Actividad reciente</h2><span>mensajes por dia</span></div><div className="activity-bars" role="img" aria-label="Mensajes por dia en los ultimos 14 dias">{dashboardActivity.map((item) => <div className="activity-day" key={item.date} title={`${item.date}: ${item.total} mensajes`}><span style={{ height: `${Math.max(4, (Number(item.total || 0) / dashboardActivityMax) * 100)}%` }} /><small>{String(item.date || "").slice(5)}</small></div>)}</div>{dashboardActivity.every((item) => Number(item.total || 0) === 0) ? <div className="empty">Sin mensajes recientes todavia.</div> : null}</article>
              <article className="panel glass-card"><div className="panel-head"><h2>Canales y pagos</h2><span>operacion</span></div><div className="channel-list dashboard-list">{dashboardChannels.length ? dashboardChannels.map((item) => <div key={item.channel}><strong>{number(item.count)}</strong><span>{item.channel}</span></div>) : <div><strong>0</strong><span>Sin canales</span></div>}<div><strong>{number(dashboardTotals.pending_payments || 0)}</strong><span>Pagos pendientes</span></div><div><strong>{number(dashboardTotals.paid_customers || 0)}</strong><span>Pagos confirmados</span></div></div></article>
              <article className="panel glass-card wide-panel"><div className="panel-head"><h2>Ultimos movimientos</h2><span>mensajes reales</span></div><div className="recent-list">{dashboardRecent.map((item, idx) => <div key={`${item.created_at}-${idx}`}><strong>{item.display_name || item.phone || item.external_contact_id || "Cliente"}</strong><span>{item.direction} / {item.channel} / {item.created_at}</span><p>{item.text}</p></div>)}{dashboardRecent.length === 0 ? <div className="empty">Todavia no hay movimientos registrados.</div> : null}</div></article>
            </section>
          </section>
        ) : activeView === "inbox" ? (
          <section className="inbox-grid"><div className="panel glass-card inbox-list"><div className="panel-head"><h2>Conversaciones</h2><button type="button" onClick={loadInbox}>Refrescar</button></div><div className="conversation-list">{conversations.map((conversation) => <button type="button" className={`conversation-item ${selectedConversation?.id === conversation.id ? "active" : ""}`} key={conversation.id} onClick={() => loadMessages(conversation)}><strong>{conversation.display_name || conversation.phone || conversation.external_contact_id}</strong><span>{conversation.channel} / {conversation.unread_count || 0} sin leer</span><small>{conversation.last_message_text || "-"}</small></button>)}{conversations.length === 0 ? <div className="empty">Sin conversaciones todavia.</div> : null}</div></div><div className="panel glass-card inbox-thread"><div className="panel-head"><h2>{selectedConversation ? selectedConversation.display_name || selectedConversation.external_contact_id : "Mensajes"}</h2>{selectedConversation ? <button type="button" onClick={markSelectedConversationRead}>Marcar leido</button> : null}</div><div className="messages">{messages.map((message) => <div className={`message ${message.direction === "out" ? "out" : "in"}`} key={message.id}><span>{message.msg_type}</span><p>{message.text || `[${message.msg_type}]`}</p><small>{message.created_at}</small></div>)}{messages.length === 0 ? <div className="empty">Selecciona una conversacion.</div> : null}</div>{selectedConversation ? <form className="composer" onSubmit={sendSelectedMessage}><input value={replyText} onChange={(event) => setReplyText(event.target.value)} placeholder="Escribe una respuesta..." /><button type="submit" className="primary">Enviar</button></form> : null}</div></section>
        ) : activeView === "customers" ? (
          <CrmPanel apiCall={apiCall} showStatus={showStatus} onOpenInbox={(customer) => { setActiveView("inbox"); loadMessages(customer); }} />
        ) : activeView === "labels" ? (
          <LabelsPanel apiCall={apiCall} showStatus={showStatus} onGoCampaigns={() => setActiveView("campaigns")} />
        ) : activeView === "campaigns" ? (
          <CampaignsPanel apiCall={apiCall} showStatus={showStatus} apiBase={API_BASE} accessToken={accessToken} features={featureFlags} />
        ) : activeView === "broadcast" ? (
          <BroadcastPanel apiCall={apiCall} showStatus={showStatus} onGoCampaigns={() => setActiveView("campaigns")} />
        ) : activeView === "ads" ? (
          <AdsPanel apiCall={apiCall} showStatus={showStatus} onConnectMeta={() => { setActiveView("settings"); setSettingsTab("channels"); }} onOpenInbox={(conversation) => { setActiveView("inbox"); loadMessages(conversation); }} />
        ) : (
          <section className="settings-page">
            <div className="settings-tabs glass-card">{[["ia","IA"],["channels","Canales"],["apis","APIs"],["users","Usuarios"],["profile","Perfil"],["security","Seguridad"],["plan","Plan"]].map(([key,label]) => <button key={key} type="button" className={settingsTab === key ? "active" : ""} onClick={() => setSettingsTab(key)}>{label}</button>)}</div>
            {settingsTab === "ia" ? <div className="settings-grid"><article className="panel glass-card"><div className="panel-head"><h2>Ajustes IA</h2><span>modelo y comportamiento</span></div><label className="check-row"><input type="checkbox" checked={aiConfig.enabled} onChange={(event) => setAiConfig((prev) => ({ ...prev, enabled: event.target.checked }))} /> IA habilitada</label><div className="form-grid two"><label>Provider<select value={aiConfig.provider} onChange={(event) => setAiConfig((prev) => ({ ...prev, provider: event.target.value }))}><option value="google">Google / Gemini</option><option value="groq">Groq</option><option value="mistral">Mistral</option><option value="openrouter">OpenRouter</option></select></label><label>Modelo<input value={aiConfig.model} onChange={(event) => setAiConfig((prev) => ({ ...prev, model: event.target.value }))} /></label></div><label>System prompt<textarea rows={7} value={aiConfig.systemPrompt} onChange={(event) => setAiConfig((prev) => ({ ...prev, systemPrompt: event.target.value }))} /></label><div className="form-grid two"><label>Max tokens<input value={aiConfig.maxTokens} onChange={(event) => setAiConfig((prev) => ({ ...prev, maxTokens: event.target.value }))} /></label><label>Temperatura<input value={aiConfig.temperature} onChange={(event) => setAiConfig((prev) => ({ ...prev, temperature: event.target.value }))} /></label><label>Fallback provider<input value={aiConfig.fallbackProvider} onChange={(event) => setAiConfig((prev) => ({ ...prev, fallbackProvider: event.target.value }))} /></label><label>Fallback model<input value={aiConfig.fallbackModel} onChange={(event) => setAiConfig((prev) => ({ ...prev, fallbackModel: event.target.value }))} /></label></div><div className="panel-actions"><button type="button" className="primary" onClick={saveAiLocal}>Guardar ajustes</button><button type="button" onClick={() => setAiTesterOpen(true)}>Probar IA</button></div></article><article className="panel glass-card"><div className="panel-head"><h2>Voz / TTS WhatsApp</h2><span>humanizacion</span></div><label className="check-row"><input type="checkbox" checked={aiConfig.voiceEnabled} onChange={(event) => setAiConfig((prev) => ({ ...prev, voiceEnabled: event.target.checked }))} /> Voz habilitada</label><label className="check-row"><input type="checkbox" checked={aiConfig.preferVoice} onChange={(event) => setAiConfig((prev) => ({ ...prev, preferVoice: event.target.checked }))} /> Preferir nota de voz</label><div className="form-grid two"><label>Proveedor TTS<select value={aiConfig.ttsProvider} onChange={(event) => setAiConfig((prev) => ({ ...prev, ttsProvider: event.target.value }))}><option value="google">Google Cloud TTS</option><option value="elevenlabs">ElevenLabs</option><option value="piper">Piper local</option></select></label><label>Voice ID<input value={aiConfig.voiceId} onChange={(event) => setAiConfig((prev) => ({ ...prev, voiceId: event.target.value }))} /></label><label>Voz<input value={aiConfig.voiceName} onChange={(event) => setAiConfig((prev) => ({ ...prev, voiceName: event.target.value }))} /></label><label>Modelo<input value={aiConfig.voiceModel} onChange={(event) => setAiConfig((prev) => ({ ...prev, voiceModel: event.target.value }))} /></label></div><label>Prompt de voz<textarea rows={4} value={aiConfig.voicePrompt} onChange={(event) => setAiConfig((prev) => ({ ...prev, voicePrompt: event.target.value }))} /></label></article><article className="panel glass-card"><div className="panel-head"><h2>Knowledge Base</h2><span>fuentes</span></div><div className="inline-form compact"><select><option>Mostrar: Todos</option></select><button type="button">Refrescar</button></div><label>Notas<input placeholder="ej: catalogo 2026, politicas de envio..." /></label><div className="upload-zone">Arrastra PDF/TXT aqui o elige archivo</div><h3>Fuentes Web</h3><label>URL<input placeholder="https://tutienda.com/pagina-o-blog" /></label><button type="button">Anadir fuente web</button></article></div> : null}
            {settingsTab === "channels" ? <div className="settings-stack"><article className="panel glass-card"><div className="panel-head"><h2>Integraciones</h2><button type="button" onClick={loadIntegrations}>Refrescar</button></div><form className="inline-form integrations-form" onSubmit={saveIntegration}><select value={integrationForm.provider} onChange={(event) => setIntegrationForm((prev) => ({ ...prev, provider: event.target.value }))}><option value="meta">Meta</option><option value="whatsapp">WhatsApp</option><option value="instagram">Instagram</option><option value="facebook">Facebook</option><option value="stripe">Stripe</option></select><select value={integrationForm.channel} onChange={(event) => setIntegrationForm((prev) => ({ ...prev, channel: event.target.value }))}><option value="whatsapp">WhatsApp</option><option value="instagram">Instagram</option><option value="facebook">Facebook</option><option value="billing">Billing</option></select><select value={integrationForm.status} onChange={(event) => setIntegrationForm((prev) => ({ ...prev, status: event.target.value }))}><option value="connected">Connected</option><option value="disconnected">Disconnected</option><option value="paused">Paused</option></select><select value={integrationForm.dispatch_mode} onChange={(event) => setIntegrationForm((prev) => ({ ...prev, dispatch_mode: event.target.value }))}><option value="stub">Stub local</option><option value="meta_cloud">Meta Cloud real</option></select><input placeholder="Phone Number ID" value={integrationForm.phone_number_id} onChange={(event) => setIntegrationForm((prev) => ({ ...prev, phone_number_id: event.target.value }))} /><input placeholder="WhatsApp Business Account ID / WABA ID" value={integrationForm.business_account_id} onChange={(event) => setIntegrationForm((prev) => ({ ...prev, business_account_id: event.target.value }))} /><input placeholder="Graph API version ej: v24.0" value={integrationForm.graph_api_version} onChange={(event) => setIntegrationForm((prev) => ({ ...prev, graph_api_version: event.target.value }))} /><input ref={metaAccessTokenRef} type="password" placeholder="Access token permanente de Meta" autoComplete="off" spellCheck={false} /><input placeholder="Token env var (solo admin)" value={integrationForm.access_token_env} onChange={(event) => setIntegrationForm((prev) => ({ ...prev, access_token_env: event.target.value }))} /><button type="submit" className="primary">Guardar</button></form><p className="soft-copy">El cliente puede pegar aqui su token permanente de Meta. Scentra lo cifra en backend y luego lo muestra como guardado, nunca como texto completo.</p><div className="table">{integrations.map((integration) => { const config = integration.config_json || {}; return <div className="row integration-row" key={integration.id}><span>{integration.provider}</span><span>{integration.channel}</span><span>{integration.status}</span><span>{config.dispatch_mode || "stub"}</span><span>{config.phone_number_id || "-"}</span><span>{config.has_access_token ? `token ${config.access_token_hint || "guardado"}` : config.access_token_env || "-"}</span></div>; })}{integrations.length === 0 ? <div className="empty">Sin integraciones configuradas.</div> : null}</div></article><article className="panel glass-card"><div className="panel-head"><h2>Webhooks</h2><button type="button" onClick={loadWebhooks}>Refrescar</button></div><div className="inline-form"><select value={webhookProvider} onChange={(event) => setWebhookProvider(event.target.value)}><option value="whatsapp">WhatsApp</option><option value="meta">Meta</option><option value="instagram">Instagram</option><option value="facebook">Facebook</option><option value="stripe">Stripe</option></select><label className="check-row"><input type="checkbox" checked={webhookSignatureRequired} onChange={(event) => setWebhookSignatureRequired(event.target.checked)} /> Requerir firma HMAC</label><button type="button" className="primary" onClick={createWebhook}>Crear endpoint</button></div>{lastWebhookSecret ? <div className="secret-box"><strong>Valores para Meta (visibles una sola vez)</strong><span>Callback URL para Meta</span><div className="copy-line"><code>{fullWebhookUrl(lastWebhookSecret.url_path)}</code><button type="button" onClick={() => copyText(fullWebhookUrl(lastWebhookSecret.url_path), "Callback URL")}>Copiar</button></div>{lastWebhookSecret.verify_token_once ? <><span>Verify token para Meta</span><div className="copy-line"><code>{lastWebhookSecret.verify_token_once}</code><button type="button" onClick={() => copyText(lastWebhookSecret.verify_token_once, "Verify token")}>Copiar</button></div></> : null}{lastWebhookSecret.signature_secret_once ? <><span>Firma HMAC opcional</span><div className="copy-line"><code>{lastWebhookSecret.signature_secret_once}</code><button type="button" onClick={() => copyText(lastWebhookSecret.signature_secret_once, "Firma HMAC")}>Copiar</button></div></> : null}<small>Meta pide el Verify token al verificar el webhook. Este valor no es el token permanente de WhatsApp Cloud API.</small></div> : <div className="secret-box muted-secret"><strong>Verify token de Meta</strong><span>Si no guardaste el token visible una sola vez, pulsa Rotar token en el endpoint y copia el nuevo valor en Meta Developers.</span></div>}<div className="table">{webhooks.map((endpoint) => <div className="row six" key={endpoint.id}><span>{endpoint.provider}</span><span className="copy-line compact"><code>{fullWebhookUrl(endpoint.url_path)}</code><button type="button" onClick={() => copyText(fullWebhookUrl(endpoint.url_path), "Callback URL")}>Copiar</button></span><span>{endpoint.signature_required ? "firma requerida" : "token o firma"}</span><span>{endpoint.is_active ? "activo" : "pausado"}</span><span>{endpoint.last_seen_at || "-"}</span><span className="row-actions"><button type="button" onClick={() => updateWebhookEndpoint(endpoint, { signature_required: !endpoint.signature_required })}>{endpoint.signature_required ? "Permitir token" : "Exigir firma"}</button><button type="button" onClick={() => rotateWebhookToken(endpoint)}>Rotar token</button><button type="button" onClick={() => rotateWebhookSignature(endpoint)}>Rotar firma</button></span></div>)}{webhooks.length === 0 ? <div className="empty">Sin endpoints webhook.</div> : null}</div><div className="panel-actions"><button type="button" onClick={processWebhookEvents}>Procesar eventos pendientes</button></div></article></div> : null}
            {settingsTab === "apis" ? <div className="settings-stack">
              <article className="panel glass-card api-console">
                <div className="panel-head"><h2>Proveedores IA</h2><span>LLM / modelos</span></div>
                <p className="soft-copy">Estos son los proveedores detectados en el proyecto original. Escribe las llaves aqui solo cuando conectemos persistencia cifrada en backend.</p>
                <div className="api-card-grid">{AI_API_PROVIDERS.map((provider) => <div className="api-card" key={provider.env}><div><strong>{provider.name}</strong><span>{provider.models}</span></div><label>{provider.env}<input type="password" placeholder="Pegar API key" value={apiSecrets[provider.env] || ""} onChange={(event) => setApiSecrets((prev) => ({ ...prev, [provider.env]: event.target.value }))} /></label>{provider.alt ? <small>Alias / extra: {provider.alt}</small> : null}</div>)}</div>
              </article>
              <article className="panel glass-card api-console">
                <div className="panel-head"><h2>Voz y TTS</h2><span>ElevenLabs / Google / Piper</span></div>
                <div className="api-card-grid">{TTS_API_PROVIDERS.map((provider) => <div className="api-card" key={provider.env}><div><strong>{provider.name}</strong><span>{provider.fields}</span></div><label>{provider.env}<input type="password" placeholder="Pegar valor" value={apiSecrets[provider.env] || ""} onChange={(event) => setApiSecrets((prev) => ({ ...prev, [provider.env]: event.target.value }))} /></label></div>)}</div>
              </article>
              <article className="panel glass-card api-console">
                <div className="panel-head"><h2>Canales y comercio</h2><span>WhatsApp / WooCommerce</span></div>
                <div className="api-card-grid channel-api-grid">{CHANNEL_API_PROVIDERS.map((provider) => <div className="api-card wide-api-card" key={provider.name}><div><strong>{provider.name}</strong><span>Principal: {provider.env}</span></div><label>{provider.env}<input type="password" placeholder="Pegar valor principal" value={apiSecrets[provider.env] || ""} onChange={(event) => setApiSecrets((prev) => ({ ...prev, [provider.env]: event.target.value }))} /></label><div className="api-field-list">{provider.fields.map((field) => <label key={field}>{field}<input type={field.includes("TOKEN") || field.includes("SECRET") || field.includes("KEY") ? "password" : "text"} placeholder={field.includes("GRAPH_VERSION") ? "v20.0 / v22.0" : "Valor requerido"} value={apiSecrets[field] || ""} onChange={(event) => setApiSecrets((prev) => ({ ...prev, [field]: event.target.value }))} /></label>)}</div></div>)}</div>
              </article>
              <article className="panel glass-card"><div className="panel-head"><h2>API SaaS interna</h2><span>base URL</span></div><code className="code-block">{API_BASE || "sin configurar"}/saas/v1</code><p className="soft-copy">Usa Bearer JWT para endpoints privados. Los webhooks resuelven empresa por endpoint key.</p><div className="panel-actions"><button type="button" className="primary" onClick={saveApiSecretsLocal}>Guardar credenciales</button><button type="button" onClick={() => setApiSecrets({})}>Limpiar campos</button></div></article>
            </div> : null}
            {settingsTab === "users" ? <div className="settings-grid"><article className="panel glass-card"><div className="panel-head"><h2>Usuarios</h2><span>equipo</span></div><div className="table"><div className="row"><span>{me.email}</span><span>{me.role}</span><span>activo</span></div></div></article><article className="panel glass-card"><div className="panel-head"><h2>Invitar usuario</h2><span>proximo</span></div><label>Email<input placeholder="correo@empresa.com" /></label><label>Rol<select><option>agent</option><option>supervisor</option><option>admin</option></select></label><button type="button" className="primary" onClick={() => showStatus("Invitaciones de usuarios pendientes de backend.", "neutral")}>Enviar invitacion</button></article></div> : null}
            {settingsTab === "profile" ? <div className="settings-grid profile-grid">
              <article className="panel glass-card profile-card"><div className="panel-head"><h2>Perfil</h2><span>datos personales</span></div><div className="avatar-editor"><div className="avatar-preview">{(profileForm.fullName || me.email || "S").slice(0,1).toUpperCase()}</div><div><strong>{profileForm.fullName || me.email}</strong><p className="soft-copy">Foto de perfil, nombre visible y datos de contacto.</p></div></div><label>URL foto de perfil<input placeholder="https://..." value={profileForm.avatarUrl} onChange={(event) => setProfileForm((prev) => ({ ...prev, avatarUrl: event.target.value }))} /></label><div className="form-grid two"><label>Nombre completo<input value={profileForm.fullName} placeholder={me.email} onChange={(event) => setProfileForm((prev) => ({ ...prev, fullName: event.target.value }))} /></label><label>Email<input value={profileForm.email} placeholder={me.email} onChange={(event) => setProfileForm((prev) => ({ ...prev, email: event.target.value }))} /></label><label>Telefono<input value={profileForm.phone} placeholder="+57..." onChange={(event) => setProfileForm((prev) => ({ ...prev, phone: event.target.value }))} /></label><label>Cargo / rol visible<input value={profileForm.role} placeholder={me.role} onChange={(event) => setProfileForm((prev) => ({ ...prev, role: event.target.value }))} /></label></div><div className="panel-actions"><button type="button" className="primary" onClick={saveProfileLocal}>Guardar perfil</button></div></article>
              <article className="panel glass-card"><div className="panel-head"><h2>Empresa</h2><span>workspace activo</span></div><div className="company-profile"><span>Empresa</span><strong>{activeCompany?.tenant_name || activeCompany?.name || "Scentra"}</strong><span>Rol</span><strong>{me.role}</strong><span>Plan</span><strong>{billingPlan.plan_code || activeCompany?.plan_code || "starter"}</strong></div></article>
            </div> : null}
            {settingsTab === "security" ? <div className="settings-grid security-grid">
              <article className="panel glass-card"><div className="panel-head"><h2>Cambiar clave</h2><span>acceso</span></div><label>Clave actual<input type="password" value={securityForm.currentPassword} onChange={(event) => setSecurityForm((prev) => ({ ...prev, currentPassword: event.target.value }))} /></label><label>Nueva clave<input type="password" value={securityForm.newPassword} onChange={(event) => setSecurityForm((prev) => ({ ...prev, newPassword: event.target.value }))} /></label><label>Confirmar nueva clave<input type="password" value={securityForm.confirmPassword} onChange={(event) => setSecurityForm((prev) => ({ ...prev, confirmPassword: event.target.value }))} /></label><div className="panel-actions"><button type="button" className="primary" onClick={saveSecurityLocal}>Actualizar clave</button></div></article>
              <article className="panel glass-card"><div className="panel-head"><h2>Autenticacion 2FA</h2><span>seguridad adicional</span></div><label className="switch-row"><input type="checkbox" checked={securityForm.twoFactorEnabled} onChange={(event) => setSecurityForm((prev) => ({ ...prev, twoFactorEnabled: event.target.checked }))} /><span><strong>Activar 2FA</strong><small>Preparado para TOTP o email OTP cuando exista endpoint backend.</small></span></label><div className="twofa-box"><strong>{securityForm.twoFactorEnabled ? "2FA solicitado" : "2FA apagado"}</strong><p>La siguiente fase debe generar QR, secreto TOTP y codigos de recuperacion.</p></div></article>
              <article className="panel glass-card"><div className="panel-head"><h2>Politicas</h2><span>estado</span></div><label className="check-row"><input type="checkbox" checked readOnly /> JWT requerido</label><label className="check-row"><input type="checkbox" checked readOnly /> RBAC por rol</label><label className="check-row"><input type="checkbox" checked={webhookSignatureRequired} onChange={(event) => setWebhookSignatureRequired(event.target.checked)} /> Firma HMAC por defecto en nuevos webhooks</label><p className="soft-copy">Auditoria de acciones criticas quedara en saas_audit_events.</p></article>
            </div> : null}
            {settingsTab === "plan" ? (
              <div className="settings-stack">
                <article className="panel glass-card">
                  <div className="panel-head"><h2>Plan y consumo</h2><button type="button" onClick={loadBilling}>Refrescar</button></div>
                  <div className="plan-summary">
                    <div><span>Estado</span><strong>{lifecycleLabel(lifecycleStatus)}</strong></div>
                    <div><span>Plan</span><strong>{billingPlan.display_name || billingPlan.plan_code || "starter"}</strong></div>
                    <div><span>Periodo</span><strong>{trialEndLabel || dateLabel(subscription.current_period_end) || billingOverview?.period_yyyymm || "-"}</strong></div>
                  </div>
                  <div className="usage-bars">
                    <div className="usage-line"><div><strong>Mensajes mensuales</strong><span>{number(billingRemaining.monthly_messages)} disponibles</span></div><div className="meter"><span style={{ width: `${pct(billingUsage.used_monthly_messages, billingLimits.max_monthly_messages)}%` }} /></div></div>
                    <div className="usage-line"><div><strong>Integraciones activas</strong><span>{number(billingRemaining.integrations)} disponibles</span></div><div className="meter"><span style={{ width: `${pct(billingUsage.used_integrations, billingLimits.max_integrations)}%` }} /></div></div>
                    <div className="usage-line"><div><strong>Usuarios</strong><span>{number(billingRemaining.agents)} disponibles</span></div><div className="meter"><span style={{ width: `${pct(billingUsage.used_agents, billingLimits.max_agents)}%` }} /></div></div>
                    <div className="usage-line"><div><strong>Campanas CRM</strong><span>{number(billingRemaining.campaigns)} disponibles</span></div><div className="meter"><span style={{ width: `${pct(billingUsage.used_campaigns, billingLimits.max_campaigns)}%` }} /></div></div>
                    <div className="usage-line"><div><strong>Broadcasts</strong><span>{number(billingRemaining.broadcasts)} disponibles</span></div><div className="meter"><span style={{ width: `${pct(billingUsage.used_broadcasts, billingLimits.max_broadcasts)}%` }} /></div></div>
                    <div className="usage-line"><div><strong>Tokens IA</strong><span>{number(billingRemaining.ai_tokens)} disponibles</span></div><div className="meter"><span style={{ width: `${pct(billingUsage.ai_tokens, billingLimits.max_ai_tokens)}%` }} /></div></div>
                  </div>
                </article>
                <article className="panel glass-card">
                  <div className="panel-head"><h2>Modulos activos</h2><span>controlados desde Scentra Admin</span></div>
                  <div className="feature-grid">{Object.entries(FEATURE_LABELS).map(([key, label]) => <span className={`feature-pill ${hasFeature(key) ? "on" : "off"}`} key={key}><strong>{label}</strong><small>{hasFeature(key) ? "Activo" : "Inactivo"}</small></span>)}</div>
                </article>
                <article className="panel glass-card">
                  <div className="panel-head"><h2>Planes disponibles</h2><span>Cambio local para pruebas</span></div>
                  <div className="plan-cards">{billingPlans.map((plan) => <article className={`plan-card ${billingPlan.plan_code === plan.plan_code ? "active" : ""}`} key={plan.plan_code}><strong>{plan.display_name || plan.plan_code}</strong><span>{number(plan.max_monthly_messages)} mensajes/mes</span><span>{number(plan.max_campaigns)} campanas CRM</span><span>{number(plan.max_broadcasts)} broadcasts</span><span>{number(plan.max_ai_tokens)} tokens IA</span><span>{number(plan.max_integrations)} integraciones / {number(plan.max_agents)} usuarios</span><button type="button" className="primary" disabled={!plan.is_active} onClick={() => changePlanDev(plan.plan_code)}>Usar plan</button></article>)}</div>
                  <p className="soft-copy">En produccion este cambio lo debe ejecutar Stripe por checkout/webhook.</p>
                </article>
              </div>
            ) : null}
          </section>
        )}
      </main>
      {aiTesterOpen ? <div className="modal-backdrop" role="presentation" onMouseDown={() => setAiTesterOpen(false)}><section className="modal-window glass-card" role="dialog" aria-modal="true" aria-label="Probar IA" onMouseDown={(event) => event.stopPropagation()}><div className="panel-head"><h2>Probar IA</h2><button type="button" onClick={() => setAiTesterOpen(false)}>Cerrar</button></div><form onSubmit={submitAiTest} className="modal-form"><label>Phone<input placeholder="57300..." value={aiTest.phone} onChange={(event) => setAiTest((prev) => ({ ...prev, phone: event.target.value }))} /></label><label>Mensaje<textarea rows={5} placeholder="Escribe un mensaje de prueba..." value={aiTest.message} onChange={(event) => setAiTest((prev) => ({ ...prev, message: event.target.value }))} /></label><div className="panel-actions"><button type="submit" className="primary">Procesar</button><button type="button" onClick={() => setAiTest({ phone: "", message: "" })}>Limpiar</button></div></form></section></div> : null}
    </div>
  );
}

export default App;
