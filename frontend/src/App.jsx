import React, { useEffect, useMemo, useRef, useState } from "react";
import CrmPanel from "./CrmPanel.jsx";
import LabelsPanel from "./LabelsPanel.jsx";
import CampaignsPanel from "./CampaignsPanel.jsx";
import BroadcastPanel from "./BroadcastPanel.jsx";
import AdsPanel from "./AdsPanel.jsx";
import AiAgentsPanel from "./AiAgentsPanel.jsx";
import IntelligencePanel from "./IntelligencePanel.jsx";
import AiEcosystemPanel from "./AiEcosystemPanel.jsx";
import WorkflowComposerPanel from "./WorkflowComposerPanel.jsx";
import TrustCenterPanel from "./TrustCenterPanel.jsx";
import { t } from "./i18n.js";

const API_BASE = (import.meta.env.VITE_API_BASE || "").replace(/\/$/, "");
const TOKEN_KEY = "scentra_ai_access_token";
const REFRESH_KEY = "scentra_ai_refresh_token";
const SEEN_MILESTONES_KEY = "scentra_seen_milestones_v1";
const TURNSTILE_SITE_KEY = String(import.meta.env.VITE_TURNSTILE_SITE_KEY || "").trim();
const CAPTCHA_ENABLED = ["1", "true", "yes", "on"].includes(String(import.meta.env.VITE_CAPTCHA_ENABLED || "").toLowerCase()) || Boolean(TURNSTILE_SITE_KEY);
const CAPTCHA_PROVIDER = "turnstile";
let turnstileScriptPromise = null;

const AI_API_PROVIDERS = [
  { code: "google", category: "ai", name: "Google / Gemini", env: "GOOGLE_AI_API_KEY", alt: "GEMINI_API_KEY", models: "gemini-2.5-flash, gemini-2.5-flash-lite, gemini-2.5-pro, gemini-2.0-flash", summary: "Multimodal, voz, imagen y bajo costo con Flash Lite.", supportsModels: true },
  { code: "groq", category: "ai", name: "Groq", env: "GROQ_API_KEY", alt: "", models: "llama-3.1-8b-instant, llama-3.3-70b-versatile, openai/gpt-oss-20b, openai/gpt-oss-120b", summary: "Clasificacion rapida y baja latencia.", supportsModels: true },
  { code: "mistral", category: "ai", name: "Mistral", env: "MISTRAL_API_KEY", alt: "", models: "mistral-small-latest, mistral-medium-latest, mistral-large-latest", summary: "Tareas cortas, clasificacion y costo controlado.", supportsModels: true },
  { code: "openrouter", category: "ai", name: "OpenRouter", env: "OPENROUTER_API_KEY", alt: "OPENROUTER_SITE / OPENROUTER_APP_NAME", models: "google/gemini-2.5-flash, google/gemini-2.5-flash-lite, google/gemini-2.5-pro, openai/gpt-4o-mini", summary: "Fallback multi-modelo y pruebas por proveedor.", supportsModels: true },
  { code: "kimi", category: "ai", name: "Kimi / Moonshot AI", env: "KIMI_API_KEY", alt: "MOONSHOT_API_KEY", models: "kimi-k2.6, kimi-k2, moonshot-v1-8k-vision-preview", summary: "Razonamiento largo, agentes y vision cuando el modelo lo soporte.", supportsModels: true },
];
const VISION_API_PROVIDERS = AI_API_PROVIDERS.filter((provider) => ["google", "openrouter", "kimi"].includes(provider.code));

const TTS_API_PROVIDERS = [
  { code: "elevenlabs", category: "tts", name: "ElevenLabs", env: "ELEVENLABS_API_KEY", fields: "ELEVENLABS_VOICE_ID, ELEVENLABS_MODEL_ID", summary: "Voces premium para agentes y mensajes de voz.", supportsModels: true },
  { code: "google_tts", category: "tts", name: "Google Cloud TTS", env: "GOOGLE_CLOUD_TTS_API_KEY", fields: "GOOGLE_TTS_LANGUAGE_CODE, GOOGLE_TTS_VOICE_NAME", summary: "Voces cloud estables y catalogo por idioma.", supportsModels: true },
  { code: "piper", category: "tts", name: "Piper local", env: "PIPER_BIN", fields: "PIPER_MODEL_PATH", summary: "Voz local futura; requiere binario/modelo.", supportsModels: false },
];

const SEARCH_API_PROVIDERS = [
  { code: "tavily", category: "search", name: "Tavily Search", env: "TAVILY_API_KEY", summary: "Busqueda web optimizada para IA con imagenes de apoyo.", supportsModels: false },
  { code: "brave_search", category: "search", name: "Brave Search API", env: "BRAVE_SEARCH_API_KEY", summary: "Busqueda web e imagenes con indice independiente y Safe Search.", supportsModels: false },
  { code: "serpapi", category: "search", name: "SerpAPI", env: "SERPAPI_API_KEY", summary: "Resultados estructurados de Google web e imagenes.", supportsModels: false },
];

const CHANNEL_API_PROVIDERS = [
  { code: "whatsapp_cloud", category: "channel", name: "WhatsApp Cloud API", env: "WHATSAPP_PERMANENT_TOKEN", summary: "Runtime de WhatsApp y envio de media.", fields: ["WHATSAPP_TOKEN", "META_ACCESS_TOKEN", "WHATSAPP_PHONE_NUMBER_ID", "WHATSAPP_WABA_ID", "META_APP_ID", "WHATSAPP_GRAPH_VERSION"] },
  { code: "instagram_business", category: "channel", name: "Instagram Business", env: "INSTAGRAM_PAGE_ACCESS_TOKEN", summary: "DMs, comentarios y activos Meta.", fields: ["INSTAGRAM_PAGE_ID", "INSTAGRAM_BUSINESS_ACCOUNT_ID", "META_APP_ID", "META_APP_SECRET"] },
  { code: "woocommerce", category: "commerce", name: "WooCommerce", env: "WC_BASE_URL", summary: "Catalogo/productos para ventas asistidas.", fields: ["WC_CONSUMER_KEY", "WC_CONSUMER_SECRET"] },
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

const FALLBACK_VERTICAL_PACKS = [
  { code: "general", label: "General", description: "Pack base para empresas sin vertical definida.", counts: {} },
  { code: "restaurant", label: "Restaurantes", description: "Reservas, menu, pedidos y no-shows.", counts: {} },
  { code: "hotel", label: "Hoteles", description: "Reservas, cotizaciones, concierge y upsell.", counts: {} },
  { code: "health", label: "Clinicas y salud", description: "Citas, intake administrativo y escalacion segura.", counts: {} },
  { code: "education", label: "Academias", description: "Admisiones, programas, clases y seguimiento.", counts: {} },
  { code: "real_estate", label: "Inmobiliarias", description: "Calificacion inmobiliaria, propiedades y visitas.", counts: {} },
  { code: "legal", label: "Legal", description: "Intake legal, documentos y escalacion.", counts: {} },
  { code: "insurance", label: "Seguros", description: "Siniestros, polizas, documentos y seguimiento.", counts: {} },
  { code: "beauty", label: "Estetica y belleza", description: "Agenda, preferencias, paquetes y recordatorios.", counts: {} },
  { code: "services", label: "Servicios", description: "Solicitudes, cotizaciones, agenda y despacho.", counts: {} },
];

const NAV_ITEMS = [
  { key: "dashboard", label: t("nav.dashboard"), icon: "▥" },
  { key: "inbox", label: t("nav.inbox"), icon: "□" },
  { key: "customers", label: t("nav.customers"), icon: "◎" },
  { key: "labels", label: t("nav.labels"), icon: "◇" },
  { key: "campaigns", label: t("nav.campaigns"), icon: "↯" },
  { key: "broadcast", label: t("nav.broadcast"), icon: "◁" },
  { key: "ads", label: t("nav.ads"), icon: "▤" },
  { key: "agents", label: t("nav.agents"), icon: "✦" },
  { key: "intelligence", label: t("nav.intelligence"), icon: "AI" },
  { key: "ecosystem", label: t("nav.ecosystem"), icon: "SDK" },
  { key: "composer", label: t("nav.composer"), icon: "WF" },
  { key: "trust", label: t("nav.trust"), icon: "AI" },
  { key: "settings", label: t("nav.settings"), icon: "⚙" },
];

const SETTINGS_TABS = [
  ["ia", t("settings.tab.ia")],
  ["vertical", t("settings.tab.vertical")],
  ["channels", t("settings.tab.channels")],
  ["apis", t("settings.tab.apis")],
  ["debug", t("settings.tab.debug")],
  ["users", t("settings.tab.users")],
  ["profile", t("settings.tab.profile")],
  ["security", t("settings.tab.security")],
  ["plan", t("settings.tab.plan")],
];

const defaultRegister = () => ({ email: "", password: "", full_name: "", tenant_name: "", tenant_slug: "", industry_code: "general" });
const defaultPasswordRecovery = () => ({ email: "" });
const defaultPasswordReset = () => ({ token: "", new_password: "", confirm_password: "" });
const defaultAiConfig = () => ({
  enabled: true,
  provider: "google",
  model: "Gemini 2.5 Flash",
  systemPrompt: "IDENTIDAD Y ROL: Scentra +AI\n\nEres una asesora comercial experta. Responde con tono humano, claro, breve y orientado a convertir conversaciones en ventas sin perder contexto.",
  maxTokens: "700",
  temperature: "0.5",
  fallbackProvider: "groq",
  fallbackModel: "llama-3.1-8b-instant",
  humanReplyStyle: true,
  humanReplySplitting: true,
  replyMaxOutputTokens: "700",
  chunks: "220",
  delayBetween: "4200",
  typingDelay: "3200",
  cooldown: "6",
  recentMessageLimit: "16",
  messageContextChars: "1200",
  typingIndicator: true,
  voiceEnabled: true,
  preferVoice: false,
  ttsProvider: "elevenlabs",
  voiceAnalysisProvider: "google",
  visionAnalysisProvider: "google",
  webImageSearchProvider: "tavily",
  voiceName: "Linda Gomez - Energetic and Upbeat",
  voiceId: "TsKSGPuG26FpNj0JzQBq",
  voiceModel: "eleven_v3",
  voicePrompt: "Voz de mujer colombiana joven, acento colombiano natural, tono alegre, espontaneo y cercano.",
});
const defaultInstagramForm = () => ({
  provider: "meta",
  channel: "instagram",
  status: "connected",
  dispatch_mode: "instagram_graph",
  page_id: "",
  page_name: "",
  business_id: "",
  business_name: "",
  instagram_business_account_id: "",
  instagram_username: "",
  app_id: "",
  graph_api_version: "v24.0",
});
const defaultFacebookForm = () => ({
  provider: "meta",
  channel: "facebook",
  status: "connected",
  dispatch_mode: "facebook_graph",
  page_id: "",
  page_name: "",
  business_id: "",
  business_name: "",
  app_id: "",
  graph_api_version: "v24.0",
});

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
          try { turnstile.remove(widgetIdRef.current); } catch { /* widget may already be gone */ }
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
    if (detail.code === "ai_agent_limit_reached") return `Limite de agentes AI alcanzado: ${detail.used}/${detail.limit}.`;
    if (detail.code === "active_ai_agent_limit_reached") return `Limite de agentes AI activos alcanzado: ${detail.used}/${detail.limit}. Pausa otro agente antes de activar este.`;
    if (detail.code === "agent_preflight_not_ready") return `Preflight del agente no aprobado (${detail.score || 0}/100). Revisa los checks antes de activar.`;
    if (detail.code === "ai_agent_budget_exceeded") return "Presupuesto del agente excedido. Ajusta limite o pausa hard stop.";
    if (detail.code === "ai_agent_not_active") return "Solo puedes asignar conversaciones a agentes activos.";
    if (detail.code === "feature_not_enabled") return `Modulo no incluido o desactivado: ${FEATURE_LABELS[detail.feature] || detail.feature}.`;
    if (detail.code === "tenant_not_operational") return `Empresa no habilitada para operar. Estado: ${detail.status || "desconocido"}.`;
    return detail.message || detail.code || fallback;
  }
  return typeof detail === "string" ? detail : fallback;
}

function advisorDisplayContent(value) {
  const raw = String(value || "").trim();
  if (!raw) return "";
  const unfenced = raw.startsWith("```")
    ? raw.replace(/^```(?:json)?\s*/i, "").replace(/```$/i, "").trim()
    : raw;
  const parseCandidate = (text) => {
    const starts = [];
    for (let index = 0; index < text.length; index += 1) {
      if (text[index] === "{" || text[index] === "[") starts.push(index);
    }
    for (const start of starts) {
      const closers = text[start] === "{" ? ["}", "]"] : ["]", "}"];
      for (const closer of closers) {
        const end = text.lastIndexOf(closer);
        if (end <= start) continue;
        try {
          return { parsed: JSON.parse(text.slice(start, end + 1)), prefix: text.slice(0, start).trim() };
        } catch {
          // Try the next possible JSON-looking segment.
        }
      }
    }
    return null;
  };
  try {
    let candidate = null;
    if (["{", "["].includes(unfenced.charAt(0))) {
      try {
        candidate = { parsed: JSON.parse(unfenced), prefix: "" };
      } catch {
        candidate = parseCandidate(unfenced);
      }
    } else {
      candidate = parseCandidate(unfenced);
    }
    if (!candidate) return raw;
    const parsed = candidate.parsed;
    const labelFor = (key) => ({
      insights: "Insights",
      hallazgos: "Hallazgos",
      recomendaciones: "Recomendaciones",
      recommendations: "Recomendaciones",
      acciones: "Acciones sugeridas",
      actions: "Acciones sugeridas",
      siguientes_pasos: "Siguientes pasos",
      next_steps: "Siguientes pasos",
      propuestas: "Propuestas",
      oportunidades: "Oportunidades",
      opportunities: "Oportunidades",
      riesgos: "Riesgos",
      risks: "Riesgos",
      prioridades: "Prioridades",
      priorities: "Prioridades",
    }[String(key || "").toLowerCase()] || String(key || "").replace(/_/g, " ").replace(/^\w/, (letter) => letter.toUpperCase()));
    const shortItem = (item) => {
      if (!item || typeof item !== "object" || Array.isArray(item)) return String(item || "");
      const keys = ["titulo", "title", "name", "nombre", "resumen", "summary", "descripcion", "description", "mensaje", "message", "texto", "text"];
      for (const key of keys) {
        if (item[key]) return String(item[key]);
      }
      return Object.entries(item)
        .filter(([, entry]) => entry && typeof entry !== "object")
        .slice(0, 2)
        .map(([key, entry]) => `${labelFor(key)}: ${entry}`)
        .join(" - ");
    };
    const toHumanLines = (item, topLevel = false) => {
      if (Array.isArray(item)) {
        const lines = topLevel ? ["Esto es lo mas importante que encontre:"] : [];
        item.slice(0, 6).forEach((entry) => {
          const summary = shortItem(entry) || (typeof entry === "object" ? toHumanLines(entry).slice(0, 2).join(" - ") : "");
          if (summary) lines.push(`- ${summary}`);
        });
        return lines;
      }
      if (!item || typeof item !== "object") return [String(item || "")].filter(Boolean);
      const title = item.titulo || item.title || item.name || item.nombre || "";
      const description = item.respuesta || item.answer || item.mensaje || item.message || item.content || item.texto || item.text || item.descripcion || item.description || item.resumen || item.summary || "";
      const lines = [];
      const used = new Set(["titulo", "title", "name", "nombre", "respuesta", "answer", "mensaje", "message", "content", "texto", "text", "descripcion", "description", "resumen", "summary"]);
      const meta = [["prioridad", "Prioridad"], ["priority", "Prioridad"], ["impacto", "Impacto"], ["impact", "Impacto"], ["riesgo", "Riesgo"], ["risk", "Riesgo"], ["risk_level", "Riesgo"], ["confianza", "Confianza"], ["confidence", "Confianza"]];
      const sections = ["insights", "hallazgos", "recomendaciones", "recommendations", "acciones", "actions", "siguientes_pasos", "next_steps", "propuestas", "oportunidades", "opportunities", "riesgos", "risks", "prioridades", "priorities"];
      if (title) lines.push(String(title));
      if (description && description !== title) lines.push(String(description));
      meta.forEach(([key, label]) => {
        used.add(key);
        if (item[key]) lines.push(`${label}: ${item[key]}`);
      });
      sections.forEach((key) => {
        used.add(key);
        if (!item[key]) return;
        const sectionLines = toHumanLines(item[key]);
        if (sectionLines.length) {
          lines.push(`${labelFor(key)}:`);
          lines.push(...sectionLines.slice(0, 7));
        }
      });
      Object.entries(item).forEach(([key, entry]) => {
        if (used.has(key) || ["id", "type", "tipo", "status", "estado", "raw", "schema"].includes(key) || lines.length >= 14) return;
        if (entry && typeof entry === "object") {
          const nested = toHumanLines(entry);
          if (nested.length) lines.push(`${labelFor(key)}:`, ...nested.slice(0, 5));
        } else if (entry) {
          lines.push(`${labelFor(key)}: ${entry}`);
        }
      });
      return lines;
    };
    const lines = [
      ...(candidate.prefix ? [candidate.prefix] : []),
      ...toHumanLines(parsed, true),
    ];
    const human = lines.filter(Boolean).join("\n").trim();
    return human || raw;
  } catch {
    return raw;
  }
}

function todayLabel() {
  return new Intl.DateTimeFormat("es-CO", { weekday: "short", day: "2-digit", month: "short", year: "numeric" }).format(new Date());
}
const pct = (used, limit) => (!Number(limit || 0) ? 0 : Math.min(100, Math.round((Number(used || 0) / Number(limit || 0)) * 100)));
const number = (value) => Number(value || 0).toLocaleString("es-CO");
const money = (cents, currency = "USD") => `${currency} ${(Number(cents || 0) / 100).toLocaleString("es-CO", { minimumFractionDigits: 0, maximumFractionDigits: 2 })}`;
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
const chatTimeLabel = (value) => {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat("es-CO", { hour: "numeric", minute: "2-digit", hour12: true }).format(date).toLowerCase().replace(/\s+/g, " ");
};
const compactDateTimeLabel = (value) => {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  const now = new Date();
  const sameDay = date.toDateString() === now.toDateString();
  if (sameDay) return chatTimeLabel(value);
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (date.toDateString() === yesterday.toDateString()) return `ayer ${chatTimeLabel(value)}`;
  return `${new Intl.DateTimeFormat("es-CO", { day: "2-digit", month: "short" }).format(date)} ${chatTimeLabel(value)}`;
};
const datetimeLocalValue = (value) => {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value).slice(0, 16);
  const offsetMs = date.getTimezoneOffset() * 60000;
  return new Date(date.getTime() - offsetMs).toISOString().slice(0, 16);
};
const isPastDate = (value) => {
  if (!value) return false;
  const date = new Date(value);
  return !Number.isNaN(date.getTime()) && date.getTime() < Date.now();
};
const leadTemperatureLabel = (value, score = 0) => {
  const key = String(value || "").toLowerCase() || (Number(score || 0) >= 75 ? "hot" : Number(score || 0) >= 40 ? "warm" : "cold");
  return { hot: "Caliente", warm: "Tibio", cold: "Frio" }[key] || key;
};
const predictionTypeLabel = (value) => ({
  lead_scoring: "Lead scoring",
  churn_prediction: "Churn",
  smart_remarketing: "Remarketing",
  operational_anomaly: "Operacion",
}[String(value || "").toLowerCase()] || "Prediccion");
const priorityLabel = (value) => ({
  urgent: "Urgente",
  high: "Alta",
  normal: "Normal",
  low: "Baja",
}[String(value || "normal").toLowerCase()] || "Normal");
const customFieldOptions = (field) => {
  const raw = field?.options_json;
  if (Array.isArray(raw)) return raw.map((item) => String(item || "").trim()).filter(Boolean);
  if (raw && typeof raw === "object" && Array.isArray(raw.options)) return raw.options.map((item) => String(item || "").trim()).filter(Boolean);
  return [];
};
const customFieldInputType = (fieldType) => ({
  number: "number",
  date: "date",
  url: "url",
  email: "email",
  phone: "tel",
}[String(fieldType || "text").toLowerCase()] || "text");
const lifecycleLabel = (status) => ({
  trial: "Demo",
  active: "Activo",
  past_due: "Pago pendiente",
  suspended: "Suspendido",
  cancelled: "Cancelado",
  paused: "Pausado",
  none: "Sin suscripcion",
}[String(status || "").toLowerCase()] || String(status || "Activo"));
const CHAT_EMOJIS = [
  "😀", "😃", "😄", "😁", "😅", "😂", "🙂", "😉", "😊", "😍", "😘", "😎",
  "🤔", "😮", "😢", "😭", "😡", "🙏", "👏", "🙌", "👍", "👎", "💪", "🔥",
  "✨", "💎", "🎁", "🚚", "✅", "❌", "⏰", "📌", "📦", "💳", "💰", "🛍️",
  "🌸", "💐", "💬", "📲", "🤝", "🥰", "😇", "🤣", "😋", "👌", "🫶", "🎉",
];
const EMOJI_GROUPS = [
  { label: "Frecuentes", icon: "↺", items: CHAT_EMOJIS },
  { label: "Caras y emociones", icon: "☺", keywords: "caras sonrisa feliz triste enojo amor risa sorpresa", items: ["😀", "😃", "😄", "😁", "😆", "😅", "😂", "🤣", "🥲", "🙂", "🙃", "😉", "😊", "😇", "🥰", "😍", "🤩", "😘", "😗", "😚", "😙", "😋", "😛", "😜", "🤪", "😝", "🤑", "🤗", "🤭", "🫢", "🫣", "🤫", "🤔", "🫡", "🤐", "🤨", "😐", "😑", "😶", "😏", "😒", "🙄", "😬", "😮‍💨", "🤥", "😌", "😔", "😪", "🤤", "😴", "😷", "🤒", "🤕", "🤢", "🤮", "🤧", "🥵", "🥶", "🥴", "😵", "🤯", "🤠", "🥳", "🥸", "😎", "🤓", "🧐", "😕", "🫤", "😟", "🙁", "☹️", "😮", "😯", "😲", "😳", "🥺", "🥹", "😦", "😧", "😨", "😰", "😥", "😢", "😭", "😱", "😖", "😣", "😞", "😓", "😩", "😫", "🥱", "😤", "😡", "😠", "🤬", "😈", "👿", "💀", "☠️", "💩", "🤡", "👻", "👽", "🤖"] },
  { label: "Gestos y personas", icon: "☝", keywords: "manos gestos persona saludo ok gracias aplauso", items: ["👋", "🤚", "🖐️", "✋", "🖖", "🫱", "🫲", "👌", "🤌", "🤏", "✌️", "🤞", "🫰", "🤟", "🤘", "🤙", "👈", "👉", "👆", "👇", "☝️", "👍", "👎", "✊", "👊", "🤛", "🤜", "👏", "🙌", "🫶", "👐", "🤲", "🙏", "✍️", "💅", "🤳", "💪", "🦾", "🦵", "🦶", "👀", "👁️", "👄", "🧠", "🫂", "👤", "👥", "🗣️", "👶", "🧒", "👦", "👧", "🧑", "👩", "👨", "🧔", "👱", "👵", "👴", "🙍", "🙎", "🙅", "🙆", "💁", "🙋", "🧏", "🙇", "🤦", "🤷", "💃", "🕺", "🏃", "🚶", "🧘"] },
  { label: "Corazones y simbolos", icon: "♡", keywords: "corazon amor check alerta estrella simbolos", items: ["❤️", "🧡", "💛", "💚", "💙", "💜", "🖤", "🤍", "🤎", "💔", "❣️", "💕", "💞", "💓", "💗", "💖", "💘", "💝", "💟", "☮️", "✝️", "☪️", "🕉️", "☸️", "✡️", "🔯", "🕎", "☯️", "☦️", "🛐", "⛎", "♈", "♉", "♊", "♋", "♌", "♍", "♎", "♏", "♐", "♑", "♒", "♓", "✅", "☑️", "✔️", "❌", "❎", "⚠️", "🚫", "⛔", "📛", "💯", "🔰", "♻️", "⭐", "🌟", "✨", "⚡", "🔥", "💥", "💫", "💦", "💨"] },
  { label: "Ventas y negocio", icon: "$", keywords: "ventas ecommerce pago dinero envio compra tienda producto", items: ["💬", "📲", "📞", "☎️", "📩", "📧", "📨", "📮", "✅", "❌", "⏰", "⌛", "📌", "📍", "🗓️", "📅", "📦", "📫", "🚚", "🚛", "🛵", "✈️", "🚢", "💳", "💵", "💴", "💶", "💷", "💰", "🪙", "🏦", "🧾", "🧮", "🛍️", "🛒", "🏷️", "🎁", "🎟️", "📊", "📈", "📉", "📋", "📝", "📁", "🔐", "🔑", "🔗", "🌐", "🤝", "🙋", "💡", "🎯", "🚀", "🏆"] },
  { label: "Comida y lugares", icon: "☕", keywords: "comida restaurante cafe hotel viaje lugar", items: ["☕", "🍵", "🧉", "🥤", "🧃", "🧋", "🍺", "🍻", "🥂", "🍷", "🍸", "🍹", "🍾", "🍽️", "🍴", "🥄", "🔪", "🥐", "🥖", "🥨", "🧀", "🥚", "🍳", "🥞", "🧇", "🥓", "🥩", "🍗", "🍖", "🌭", "🍔", "🍟", "🍕", "🥪", "🌮", "🌯", "🥙", "🧆", "🍝", "🍜", "🍲", "🍛", "🍣", "🍤", "🍙", "🍚", "🍦", "🍰", "🧁", "🍫", "🍪", "🍩", "🍎", "🍓", "🥭", "🏠", "🏢", "🏬", "🏨", "🏥", "🏫", "🏪", "🏖️", "🏝️", "⛰️", "🚗", "🚌", "🚕", "🚆", "✈️", "🛎️", "🛏️"] },
  { label: "Objetos y naturaleza", icon: "□", keywords: "objetos flores perfume musica camara regalo", items: ["🌸", "🌺", "🌷", "🌹", "🥀", "🌻", "🌼", "💐", "🌿", "🍃", "🌱", "🌵", "🌴", "🌳", "☀️", "🌤️", "⛅", "🌧️", "🌈", "🌙", "💎", "🪞", "🧴", "🧼", "🛁", "🧽", "🧸", "🎈", "🎉", "🎊", "🎵", "🎶", "🎧", "🎤", "📷", "🎥", "💻", "📱", "⌚", "🖥️", "🖨️", "💡", "🔦", "🕯️", "🧲", "🧰", "🛠️", "⚙️", "🧪", "💊", "🩺", "📚", "📖", "✏️", "🖊️", "📎", "✂️"] },
];
const EMOJI_SEARCH_TERMS = {
  "😀": "sonrisa feliz happy cara", "😂": "risa carcajada lol", "🤣": "risa suelo", "😍": "amor ojos corazon", "🥰": "amor tierno gracias", "😘": "beso",
  "😢": "triste llorar", "😭": "llanto llorar", "😡": "enojo bravo", "🙏": "gracias por favor oracion", "👏": "aplauso felicitaciones", "🙌": "celebrar manos",
  "👍": "like ok bien aprobar", "👎": "no dislike", "🫶": "amor manos corazon", "🔥": "fuego hot promocion", "✨": "brillo magia", "✅": "check correcto listo",
  "❌": "x error cancelar", "⏰": "hora tiempo", "📦": "paquete envio", "🚚": "envio domicilio transporte", "💳": "tarjeta pago", "💰": "dinero pago precio",
  "🛍️": "compra tienda bolsa", "🎁": "regalo promo", "📲": "celular whatsapp mensaje", "💬": "chat mensaje", "📍": "ubicacion direccion",
};
const RECENT_EMOJIS_KEY = "scentra_recent_emojis";
const BROWSER_NOTIFICATIONS_KEY = "scentra_browser_notifications";
const EMPTY_WAVEFORM = Array.from({ length: 32 }, (_, idx) => 8 + ((idx * 7) % 18));
const formatDuration = (seconds) => {
  const safe = Math.max(0, Number(seconds || 0));
  const min = Math.floor(safe / 60).toString().padStart(2, "0");
  const sec = Math.floor(safe % 60).toString().padStart(2, "0");
  return `${min}:${sec}`;
};
const mediaKindFromMime = (type) => {
  const mime = String(type || "").toLowerCase();
  if (mime.startsWith("image/")) return "image";
  if (mime.startsWith("video/")) return "video";
  if (mime.startsWith("audio/")) return "audio";
  return "document";
};
const channelLabel = (channel) => ({
  whatsapp: "WhatsApp",
  facebook: "Facebook",
  instagram: "Instagram",
  tiktok: "TikTok",
  meta: "Meta",
}[String(channel || "").toLowerCase()] || String(channel || "Canal"));

const agentTypeLabel = (type) => ({
  advisor: "Advisor",
  sales: "Ventas",
  support: "Soporte",
  custom: "Custom Agent",
  teacher: "Profesor",
  restaurant_reservations: "Restaurante Reservas",
  hotel_booking: "Reservas Hotel",
  real_estate_leads: "Inmobiliaria",
  appointment_scheduler: "Agenda / Citas",
}[String(type || "").toLowerCase()] || String(type || "Agente"));

const fallbackProviderModels = (provider) => String(provider?.models || "")
  .split(",")
  .map((item) => item.trim())
  .filter(Boolean)
  .map((item) => ({ id: item, label: item }));

const providerModelsNotice = (data, provider) => {
  if (data?.ok !== false) return "Modelos cargados desde el proveedor";
  const detail = data?.detail;
  const code = typeof detail === "object" ? detail.code : detail;
  if (code === "credential_required") return `Modelos de referencia cargados. Agrega primero la API key de ${provider?.name || "este proveedor"} para consultar modelos reales.`;
  if (code === "provider_models_error") return `No se pudo validar la API de ${provider?.name || "este proveedor"}. Dejé modelos de referencia para que puedas continuar.`;
  return `Modelos de referencia cargados para ${provider?.name || "este proveedor"}.`;
};

const emojiMatchesNeedle = (emoji, needle, group) => {
  if (!needle) return true;
  const haystack = `${emoji} ${group?.label || ""} ${group?.keywords || ""} ${EMOJI_SEARCH_TERMS[emoji] || ""}`.toLowerCase();
  return haystack.includes(needle);
};

const asObject = (value) => {
  if (value && typeof value === "object" && !Array.isArray(value)) return value;
  if (typeof value === "string" && value.trim()) {
    try {
      const parsed = JSON.parse(value);
      return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
    } catch {
      return {};
    }
  }
  return {};
};

const cleanProductText = (value, limit = 500) => String(value || "").trim().slice(0, limit);

const normalizeProductCard = (product) => {
  const raw = asObject(product);
  const attributes = Array.isArray(raw.attributes)
    ? raw.attributes
        .map((item) => ({ name: cleanProductText(item?.name, 80), value: cleanProductText(item?.value || item?.option, 220) }))
        .filter((item) => item.name && item.value)
        .slice(0, 8)
    : [];
  const categories = Array.isArray(raw.categories) ? raw.categories.map((item) => cleanProductText(item, 80)).filter(Boolean).slice(0, 8) : [];
  return {
    id: cleanProductText(raw.id, 80),
    name: cleanProductText(raw.name, 180) || "Producto",
    sku: cleanProductText(raw.sku, 120),
    price: cleanProductText(raw.price, 80),
    regular_price: cleanProductText(raw.regular_price, 80),
    sale_price: cleanProductText(raw.sale_price, 80),
    currency: cleanProductText(raw.currency, 20),
    permalink: cleanProductText(raw.permalink, 900),
    image_url: cleanProductText(raw.image_url || raw.featured_image, 900),
    stock_status: cleanProductText(raw.stock_status, 80),
    short_description: cleanProductText(raw.short_description, 280),
    categories,
    attributes,
  };
};

const productCardFromMessage = (message) => {
  const payload = asObject(message?.payload_json);
  const product = normalizeProductCard(payload.product_card || payload.product || payload.catalog_product || {});
  return product.name !== "Producto" || product.permalink || product.image_url || product.price ? product : null;
};

const productPriceLabel = (product) => {
  const price = product.sale_price || product.price || product.regular_price || "";
  if (!price) return "Precio no visible";
  const numeric = Number(String(price).replace(/[^\d.,-]/g, "").replace(/\./g, "").replace(",", "."));
  if (Number.isFinite(numeric) && numeric > 0) return new Intl.NumberFormat("es-CO", { style: "currency", currency: "COP", maximumFractionDigits: 0 }).format(numeric);
  return product.currency ? `${product.currency} ${price}` : `$ ${price}`;
};

const buildProductOutboundText = (product, note = "") => {
  const lines = [];
  const cleanNote = cleanProductText(note, 900);
  if (cleanNote) lines.push(cleanNote, "");
  lines.push(product.name || "Producto");
  const price = productPriceLabel(product);
  if (price && price !== "Precio no visible") lines.push(`Precio: ${price}`);
  if (product.sku) lines.push(`SKU: ${product.sku}`);
  product.attributes.forEach((attribute) => lines.push(`${attribute.name}: ${attribute.value}`));
  if (product.short_description) lines.push(product.short_description);
  if (product.permalink) lines.push(`Ver producto: ${product.permalink}`);
  return lines.join("\n").trim();
};

function ProductMessageCard({ product, compact = false }) {
  if (!product) return null;
  const detailChips = [
    ...(product.categories || []).slice(0, 2),
    product.stock_status ? (product.stock_status === "instock" ? "Disponible" : product.stock_status) : "",
    product.sku ? `SKU ${product.sku}` : "",
  ].filter(Boolean).slice(0, 4);
  return (
    <article className={`product-message-card ${compact ? "compact" : ""}`}>
      <div className="product-card-media">
        {product.image_url ? <img src={product.image_url} alt={product.name} loading="lazy" /> : <span>Sin imagen</span>}
      </div>
      <div className="product-card-body">
        <strong>{product.name}</strong>
        <b>{productPriceLabel(product)}</b>
        {detailChips.length ? <div className="product-card-chips">{detailChips.map((chip) => <span key={chip}>{chip}</span>)}</div> : null}
        {product.attributes?.length ? (
          <dl className="product-card-attrs">
            {product.attributes.slice(0, 4).map((attribute) => (
              <React.Fragment key={`${attribute.name}-${attribute.value}`}>
                <dt>{attribute.name}</dt>
                <dd>{attribute.value}</dd>
              </React.Fragment>
            ))}
          </dl>
        ) : null}
        {product.short_description ? <p>{product.short_description}</p> : null}
        {product.permalink ? <a href={product.permalink} target="_blank" rel="noreferrer">Ver producto</a> : null}
      </div>
    </article>
  );
}

const messageDeliveryState = (message) => {
  if (String(message?.direction || "").toLowerCase() !== "out") return null;
  const payload = asObject(message?.payload_json);
  const raw = String(payload.delivery_status || payload.dispatch_status || "queued").toLowerCase();
  if (raw === "read") return { key: "read", label: "Leido", mark: "✓✓" };
  if (raw === "delivered") return { key: "delivered", label: "Entregado", mark: "✓✓" };
  if (raw === "sent") return { key: "sent", label: "Enviado", mark: "✓" };
  if (["failed", "blocked"].includes(raw)) return { key: "failed", label: payload.delivery_error || payload.error || "No enviado", mark: "!" };
  return { key: "queued", label: "En cola", mark: "•" };
};

const userDisplayName = (user) => {
  const fullName = String(user?.full_name || "").trim();
  if (fullName) return fullName;
  const email = String(user?.email || "").trim();
  const local = email.split("@")[0] || "";
  return local || email || "Scentra";
};

const waveformFromSeed = (seed = "", count = 32) => {
  const text = String(seed || "scentra");
  let hash = 0;
  for (let idx = 0; idx < text.length; idx += 1) hash = (hash * 31 + text.charCodeAt(idx)) >>> 0;
  return Array.from({ length: count }, (_, idx) => {
    hash = (hash * 1664525 + 1013904223) >>> 0;
    const pulse = Math.abs(Math.sin((idx + 1) * 0.72 + text.length));
    return 8 + Math.round(((hash % 100) / 100) * 22 + pulse * 12);
  });
};

const waveformFromAudioBuffer = (audioBuffer, count = 32) => {
  if (!audioBuffer?.length) return EMPTY_WAVEFORM.slice(0, count);
  const data = audioBuffer.getChannelData(0);
  const blockSize = Math.max(1, Math.floor(data.length / count));
  const raw = Array.from({ length: count }, (_, idx) => {
    const start = idx * blockSize;
    const end = Math.min(data.length, start + blockSize);
    let total = 0;
    for (let pos = start; pos < end; pos += 1) total += data[pos] * data[pos];
    return Math.sqrt(total / Math.max(1, end - start));
  });
  const max = Math.max(...raw, 0.001);
  return raw.map((value) => Math.max(7, Math.min(46, Math.round(7 + (value / max) * 39))));
};

const analyzeAudioBlobWaveform = async (blob, count = 32) => {
  const AudioContextCtor = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextCtor || !blob?.size) return EMPTY_WAVEFORM.slice(0, count);
  const audioContext = new AudioContextCtor();
  try {
    const buffer = await blob.arrayBuffer();
    const audioBuffer = await audioContext.decodeAudioData(buffer.slice(0));
    return waveformFromAudioBuffer(audioBuffer, count);
  } finally {
    audioContext.close?.().catch(() => {});
  }
};

function AudioWaveform({ src, seed = "", levels = null }) {
  const fallback = useMemo(() => (Array.isArray(levels) && levels.length ? levels : waveformFromSeed(seed)), [levels, seed]);
  const [bars, setBars] = useState(fallback);

  useEffect(() => { setBars(fallback); }, [fallback]);
  useEffect(() => {
    if (!src) return undefined;
    let cancelled = false;
    fetch(src)
      .then((res) => (res.ok ? res.blob() : Promise.reject(new Error("audio_fetch_failed"))))
      .then((blob) => analyzeAudioBlobWaveform(blob))
      .then((nextBars) => { if (!cancelled && nextBars?.length) setBars(nextBars); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [src]);

  return <div className="audio-wave" aria-hidden="true">{bars.map((height, idx) => <span key={idx} style={{ height: `${height}px` }} />)}</div>;
}

function App() {
  const metaAccessTokenRef = useRef(null);
  const metaAppSecretRef = useRef(null);
  const instagramPageTokenRef = useRef(null);
  const instagramAppSecretRef = useRef(null);
  const facebookPageTokenRef = useRef(null);
  const facebookAppSecretRef = useRef(null);
  const composerFileRef = useRef(null);
  const knowledgeFileRef = useRef(null);
  const messagesPanelRef = useRef(null);
  const messagesEndRef = useRef(null);
  const advisorChatRef = useRef(null);
  const mediaRecorderRef = useRef(null);
  const mediaStreamRef = useRef(null);
  const recordingChunksRef = useRef([]);
  const recordingLevelsRef = useRef(EMPTY_WAVEFORM);
  const recordingCancelledRef = useRef(false);
  const recordingTimerRef = useRef(null);
  const recordingAnimationRef = useRef(null);
  const audioContextRef = useRef(null);
  const attachmentSignatureRef = useRef("");
  const lastUnreadTotalRef = useRef(0);
  const lastOpenCommentsRef = useRef(0);
  const lastNotifiedInboxKeyRef = useRef("");
  const inboxRequestRef = useRef(null);
  const inboxRequestSeqRef = useRef(0);
  const refreshPromiseRef = useRef(null);
  const [accessToken, setAccessToken] = useState(() => localStorage.getItem(TOKEN_KEY) || "");
  const [refreshToken, setRefreshToken] = useState(() => localStorage.getItem(REFRESH_KEY) || "");
  const [mode, setMode] = useState("login");
  const [login, setLogin] = useState({ email: "", password: "" });
  const [register, setRegister] = useState(defaultRegister);
  const [passwordRecovery, setPasswordRecovery] = useState(defaultPasswordRecovery);
  const [passwordReset, setPasswordReset] = useState(defaultPasswordReset);
  const [loginCaptchaToken, setLoginCaptchaToken] = useState("");
  const [registerCaptchaToken, setRegisterCaptchaToken] = useState("");
  const [recoveryCaptchaToken, setRecoveryCaptchaToken] = useState("");
  const [resetCaptchaToken, setResetCaptchaToken] = useState("");
  const [mfaChallenge, setMfaChallenge] = useState(null);
  const [mfaCode, setMfaCode] = useState("");
  const [loginCaptchaReset, setLoginCaptchaReset] = useState(0);
  const [registerCaptchaReset, setRegisterCaptchaReset] = useState(0);
  const [recoveryCaptchaReset, setRecoveryCaptchaReset] = useState(0);
  const [resetCaptchaReset, setResetCaptchaReset] = useState(0);
  const [me, setMe] = useState(null);
  const [tenants, setTenants] = useState([]);
  const [activeView, setActiveView] = useState("dashboard");
  const [settingsTab, setSettingsTab] = useState("ia");
  const [webhookProvider, setWebhookProvider] = useState("whatsapp");
  const [webhookSignatureRequired, setWebhookSignatureRequired] = useState(false);
  const [webhooks, setWebhooks] = useState([]);
  const [webhookEvents, setWebhookEvents] = useState([]);
  const [lastWebhookSecret, setLastWebhookSecret] = useState(null);
  const [webhookCheck, setWebhookCheck] = useState(null);
  const [integrations, setIntegrations] = useState([]);
  const [billingOverview, setBillingOverview] = useState(null);
  const [billingPlans, setBillingPlans] = useState([]);
  const [billingCheckoutSessions, setBillingCheckoutSessions] = useState([]);
  const [billingInvoices, setBillingInvoices] = useState([]);
  const [billingCheckoutProvider, setBillingCheckoutProvider] = useState("wompi");
  const [billingCheckoutBusy, setBillingCheckoutBusy] = useState("");
  const [dashboardOverview, setDashboardOverview] = useState(null);
  const [whatsappPhones, setWhatsappPhones] = useState([]);
  const [phoneRegisterForm, setPhoneRegisterForm] = useState({ phone_number_id: "", pin: "" });
  const [phoneSyncing, setPhoneSyncing] = useState(false);
  const [integrationForm, setIntegrationForm] = useState({ provider: "meta", channel: "whatsapp", status: "connected", dispatch_mode: "stub", phone_number_id: "", business_account_id: "", app_id: "", graph_api_version: "v24.0", access_token_env: "SCENTRA_META_ACCESS_TOKEN" });
  const [instagramForm, setInstagramForm] = useState(defaultInstagramForm);
  const [facebookForm, setFacebookForm] = useState(defaultFacebookForm);
  const [integrationSecretModal, setIntegrationSecretModal] = useState(null);
  const [aiConfig, setAiConfig] = useState(defaultAiConfig);
  const [aiTesterOpen, setAiTesterOpen] = useState(false);
  const [aiTest, setAiTest] = useState({ phone: "", message: "" });
  const [aiTestResult, setAiTestResult] = useState("");
  const [profileForm, setProfileForm] = useState({ fullName: "", email: "", phone: "", role: "", avatarUrl: "" });
  const [securityForm, setSecurityForm] = useState({ currentPassword: "", newPassword: "", confirmPassword: "", twoFactorEnabled: false, twoFactorMethod: "email_otp", passwordChangedAt: "" });
  const [apiCredentials, setApiCredentials] = useState([]);
  const [knowledgeSources, setKnowledgeSources] = useState([]);
  const [knowledgeHealth, setKnowledgeHealth] = useState(null);
  const [knowledgeSearch, setKnowledgeSearch] = useState({ query: "", results: [], citations: [], confidence: 0, retrievalMode: "", searched: false });
  const [knowledgeSearching, setKnowledgeSearching] = useState(false);
  const [knowledgeUrlForm, setKnowledgeUrlForm] = useState({ url: "", title: "", notes: "" });
  const [knowledgeUploading, setKnowledgeUploading] = useState(false);
  const [knowledgeEvaluations, setKnowledgeEvaluations] = useState([]);
  const [knowledgeEvalForm, setKnowledgeEvalForm] = useState({ query: "", expectedAnswer: "", expectedSources: "" });
  const [knowledgeEvaluating, setKnowledgeEvaluating] = useState(false);
  const [diagnostics, setDiagnostics] = useState(null);
  const [diagnosticsRunning, setDiagnosticsRunning] = useState(false);
  const [aiGatewayProviders, setAiGatewayProviders] = useState([]);
  const [aiGatewayRuns, setAiGatewayRuns] = useState([]);
  const [advisorOpen, setAdvisorOpen] = useState(false);
  const [advisorThreadId, setAdvisorThreadId] = useState("");
  const [advisorMessages, setAdvisorMessages] = useState([]);
  const [advisorInput, setAdvisorInput] = useState("");
  const [advisorInsights, setAdvisorInsights] = useState([]);
  const [advisorRecommendations, setAdvisorRecommendations] = useState([]);
  const [advisorActions, setAdvisorActions] = useState([]);
  const [advisorBriefing, setAdvisorBriefing] = useState([]);
  const [advisorMetrics, setAdvisorMetrics] = useState(null);
  const [advisorActivity, setAdvisorActivity] = useState([]);
  const [advisorMemory, setAdvisorMemory] = useState(null);
  const [advisorStreamStatus, setAdvisorStreamStatus] = useState("");
  const [advisorLastSync, setAdvisorLastSync] = useState("");
  const [advisorLoading, setAdvisorLoading] = useState(false);
  const [advisorBusyActionId, setAdvisorBusyActionId] = useState("");
  const [instagramOAuth, setInstagramOAuth] = useState({ state: "", assets: [], status: "", callbackUrl: "" });
  const [instagramDiagnostics, setInstagramDiagnostics] = useState(null);
  const [facebookDiagnostics, setFacebookDiagnostics] = useState(null);
  const [metaTokenHealth, setMetaTokenHealth] = useState({ instagram: null, facebook: null });
  const [instagramBusy, setInstagramBusy] = useState(false);
  const [facebookBusy, setFacebookBusy] = useState(false);
  const [debugInboundForm, setDebugInboundForm] = useState({ from_phone: "573001112233", message: "Hola, prueba de webhook entrante", contact_name: "Cliente Diagnostico" });
  const [debugInboundResult, setDebugInboundResult] = useState(null);
  const [subscriptionCheck, setSubscriptionCheck] = useState(null);
  const [credentialModal, setCredentialModal] = useState(null);
  const [credentialSaving, setCredentialSaving] = useState(false);
  const [credentialModels, setCredentialModels] = useState({});
  const [expandedCredentialCards, setExpandedCredentialCards] = useState({});
  const [conversations, setConversations] = useState([]);
  const [inboxAiAgents, setInboxAiAgents] = useState([]);
  const [selectedConversation, setSelectedConversation] = useState(null);
  const [conversationMemory, setConversationMemory] = useState(null);
  const [messages, setMessages] = useState([]);
  const [voiceAnalysisBusy, setVoiceAnalysisBusy] = useState("");
  const [visionAnalysisBusy, setVisionAnalysisBusy] = useState("");
  const [webSearchRuns, setWebSearchRuns] = useState([]);
  const [webSearchForm, setWebSearchForm] = useState({ query: "", searchType: "mixed", providerCode: "tavily" });
  const [webSearchBusy, setWebSearchBusy] = useState("");
  const [multimodalMemoryEvents, setMultimodalMemoryEvents] = useState([]);
  const [inboxMode, setInboxMode] = useState("dms");
  const [socialComments, setSocialComments] = useState([]);
  const [selectedComment, setSelectedComment] = useState(null);
  const [commentReplyText, setCommentReplyText] = useState("");
  const [commentAiSettings, setCommentAiSettings] = useState(null);
  const [commentBusy, setCommentBusy] = useState("");
  const [commentEmojiOpen, setCommentEmojiOpen] = useState(false);
  const [commentReactionOpen, setCommentReactionOpen] = useState(false);
  const [replyText, setReplyText] = useState("");
  const [attachmentFile, setAttachmentFile] = useState(null);
  const [attachmentKind, setAttachmentKind] = useState("");
  const [attachmentPreview, setAttachmentPreview] = useState("");
  const [attachmentWaveform, setAttachmentWaveform] = useState(EMPTY_WAVEFORM);
  const [catalogOpen, setCatalogOpen] = useState(false);
  const [catalogSearch, setCatalogSearch] = useState("");
  const [catalogProducts, setCatalogProducts] = useState([]);
  const [catalogLoading, setCatalogLoading] = useState(false);
  const [catalogError, setCatalogError] = useState("");
  const [catalogDraft, setCatalogDraft] = useState(null);
  const [emojiOpen, setEmojiOpen] = useState(false);
  const [emojiSearch, setEmojiSearch] = useState("");
  const [recentEmojis, setRecentEmojis] = useState(() => {
    try { return JSON.parse(localStorage.getItem(RECENT_EMOJIS_KEY) || "[]"); }
    catch { return []; }
  });
  const [attachMenuOpen, setAttachMenuOpen] = useState(false);
  const [inboxChannelFilter, setInboxChannelFilter] = useState("all");
  const [inboxQueueFilter, setInboxQueueFilter] = useState("all");
  const [inboxAgentFilter, setInboxAgentFilter] = useState("all");
  const [inboxSearch, setInboxSearch] = useState("");
  const [crmPanelOpen, setCrmPanelOpen] = useState(true);
  const [crmConfig, setCrmConfig] = useState({ custom_fields: [], pipeline: { stages: [] }, industry_presets: [] });
  const [publicVerticalPacks, setPublicVerticalPacks] = useState(FALLBACK_VERTICAL_PACKS);
  const [verticalPacks, setVerticalPacks] = useState(FALLBACK_VERTICAL_PACKS);
  const [verticalState, setVerticalState] = useState(null);
  const [verticalApply, setVerticalApply] = useState({ industry_code: "general", create_agents: false });
  const [verticalBusy, setVerticalBusy] = useState(false);
  const [crmDraft, setCrmDraft] = useState({});
  const [conversationTasks, setConversationTasks] = useState([]);
  const [messageStatusEvents, setMessageStatusEvents] = useState([]);
  const [conversationTimeline, setConversationTimeline] = useState([]);
  const [dedupeCandidates, setDedupeCandidates] = useState([]);
  const [mergingCustomerId, setMergingCustomerId] = useState("");
  const [taskDraft, setTaskDraft] = useState({ title: "", due_at: "", priority: "normal" });
  const [savingCrm, setSavingCrm] = useState(false);
  const [predictiveBusy, setPredictiveBusy] = useState("");
  const [notificationSoundEnabled, setNotificationSoundEnabled] = useState(true);
  const [browserNotificationsEnabled, setBrowserNotificationsEnabled] = useState(() => localStorage.getItem(BROWSER_NOTIFICATIONS_KEY) === "true");
  const [notificationPermission, setNotificationPermission] = useState(() => (typeof window !== "undefined" && "Notification" in window ? window.Notification.permission : "unsupported"));
  const [inboxRefreshing, setInboxRefreshing] = useState(false);
  const [inboxLastSyncAt, setInboxLastSyncAt] = useState("");
  const [inboxSyncError, setInboxSyncError] = useState("");
  const [isRecording, setIsRecording] = useState(false);
  const [recordingSeconds, setRecordingSeconds] = useState(0);
  const [recordingLevels, setRecordingLevels] = useState(EMPTY_WAVEFORM);
  const [composerSending, setComposerSending] = useState(false);
  const [status, setStatus] = useState("");
  const [statusTone, setStatusTone] = useState("neutral");
  const [milestoneNotice, setMilestoneNotice] = useState(null);

  const activeCompany = tenants.find((company) => company.tenant_id === me?.tenant_id);
  const currentUserName = userDisplayName(me);
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
    agents: hasFeature("ai"),
    intelligence: true,
    ecosystem: hasFeature("ai"),
    composer: true,
    trust: true,
    settings: true,
  };
  const activeViewAllowed = moduleAccess[activeView] !== false;
  const navItems = NAV_ITEMS.filter((item) => moduleAccess[item.key] !== false);
  const activeCrmCustomFields = useMemo(() => (crmConfig.custom_fields || []).filter((field) => field.is_active !== false), [crmConfig.custom_fields]);
  const activePipelineStages = useMemo(() => ((crmConfig.pipeline || {}).stages || []).filter((stage) => stage.is_active !== false), [crmConfig.pipeline]);
  const currentIndustryCode = verticalState?.tenant?.industry_code || activeCompany?.industry_code || register.industry_code || "general";
  const selectedVerticalPack = verticalPacks.find((pack) => pack.code === verticalApply.industry_code) || verticalPacks.find((pack) => pack.code === currentIndustryCode) || FALLBACK_VERTICAL_PACKS[0];
  const unreadTotal = conversations.reduce((sum, item) => sum + Number(item.unread_count || 0), 0);
  const connectedIntegrations = integrations.filter((item) => item.status !== "disconnected").length;
  const activeWebhooks = webhooks.filter((item) => item.is_active).length;
  const activeWhatsappIntegration = integrations.find((item) => item.channel === "whatsapp" && item.status === "connected");
  const whatsappDispatchMode = String(activeWhatsappIntegration?.config_json?.dispatch_mode || "stub").toLowerCase();
  const credentialByKey = useMemo(() => Object.fromEntries(apiCredentials.map((item) => [item.credential_key, item])), [apiCredentials]);
  const commerceCredentialsReady = ["WC_BASE_URL", "WC_CONSUMER_KEY", "WC_CONSUMER_SECRET"].every((key) => credentialByKey[key]?.has_secret);
  const selectedAiProvider = AI_API_PROVIDERS.find((provider) => provider.code === aiConfig.provider) || AI_API_PROVIDERS[0];
  const selectedAiCredential = credentialByKey[selectedAiProvider?.env] || {};
  const selectedFallbackProvider = AI_API_PROVIDERS.find((provider) => provider.code === aiConfig.fallbackProvider) || null;
  const selectedFallbackCredential = selectedFallbackProvider ? credentialByKey[selectedFallbackProvider.env] || {} : {};
  const selectedTtsProvider = TTS_API_PROVIDERS.find((provider) => provider.code === aiConfig.ttsProvider) || TTS_API_PROVIDERS[0];
  const selectedTtsCredential = credentialByKey[selectedTtsProvider?.env] || {};
  const selectedVoiceAnalysisProvider = AI_API_PROVIDERS.find((provider) => provider.code === aiConfig.voiceAnalysisProvider) || AI_API_PROVIDERS[0];
  const selectedVoiceAnalysisCredential = credentialByKey[selectedVoiceAnalysisProvider?.env] || {};
  const selectedVisionAnalysisProvider = VISION_API_PROVIDERS.find((provider) => provider.code === aiConfig.visionAnalysisProvider) || VISION_API_PROVIDERS[0];
  const selectedVisionAnalysisCredential = credentialByKey[selectedVisionAnalysisProvider?.env] || {};
  const selectedWebSearchProvider = SEARCH_API_PROVIDERS.find((provider) => provider.code === (webSearchForm.providerCode || aiConfig.webImageSearchProvider)) || SEARCH_API_PROVIDERS[0];
  const selectedWebSearchCredential = credentialByKey[selectedWebSearchProvider?.env] || {};
  const activeAiModel = selectedAiCredential.selected_model || "";
  const activeFallbackModel = selectedFallbackCredential.selected_model || "";
  const activeTtsModel = selectedTtsCredential.selected_model || "";
  const activeVoiceAnalysisModel = selectedVoiceAnalysisCredential.selected_model || "";
  const activeVisionAnalysisModel = selectedVisionAnalysisCredential.selected_model || "";
  const availableInboxChannels = Array.from(new Set([
    ...integrations.filter((item) => item.status === "connected").map((item) => String(item.channel || "").toLowerCase()),
    ...conversations.map((item) => String(item.channel || "").toLowerCase()),
    ...socialComments.map((item) => String(item.channel || "").toLowerCase()),
  ].filter(Boolean))).filter((channel) => !["billing"].includes(channel)).sort();
  const activeInboxAiAgents = inboxAiAgents.filter((agent) => String(agent.status || "").toLowerCase() === "active");
  const webSearchItems = useMemo(() => webSearchRuns.flatMap((run) => (run.results || []).map((result) => ({ run, result }))), [webSearchRuns]);
  const approvedVisualReferences = useMemo(() => webSearchItems.filter(({ result }) => result.approval_status === "approved" && result.safety_status !== "blocked" && (result.thumbnail_url || result.image_url)).slice(0, 6), [webSearchItems]);
  const pendingVisualReferences = useMemo(() => webSearchItems.filter(({ result }) => result.approval_status !== "approved" && result.safety_status !== "blocked" && (result.thumbnail_url || result.image_url)).slice(0, 6), [webSearchItems]);
  const inboxVoiceInsights = useMemo(() => messages.slice().reverse().map((message) => {
    const voice = asObject(asObject(message.payload_json).voice_intelligence);
    if (!voice.transcript && !voice.summary && !voice.intent && !voice.sentiment) return null;
    return {
      message,
      summary: cleanProductText(voice.summary || voice.transcript, 220),
      intent: cleanProductText(voice.intent_label || voice.intent || "other", 80),
      sentiment: cleanProductText(voice.sentiment || "neutral", 60),
      urgency: cleanProductText(voice.urgency || "low", 40),
      confidence: Math.round(Number(voice.confidence || 0) * 100),
    };
  }).filter(Boolean).slice(0, 4), [messages]);
  const inboxVisionInsights = useMemo(() => messages.slice().reverse().map((message) => {
    const vision = asObject(asObject(message.payload_json).vision_intelligence);
    if (!vision.summary && !vision.visual_description && !vision.extracted_text && !vision.intent && !vision.document_type) return null;
    return {
      message,
      summary: cleanProductText(vision.summary || vision.visual_description || vision.extracted_text, 220),
      intent: cleanProductText(vision.intent_label || vision.intent || "other", 80),
      type: cleanProductText(vision.document_type || vision.media_kind || message.msg_type || "media", 80),
      urgency: cleanProductText(vision.urgency || "low", 40),
      confidence: Math.round(Number(vision.confidence || 0) * 100),
    };
  }).filter(Boolean).slice(0, 4), [messages]);
  const inboxMemoryHighlights = useMemo(() => multimodalMemoryEvents.slice(0, 5).map((event) => ({
    id: event.id,
    source: cleanProductText(event.source_kind || event.event_type || "multimodal", 80),
    text: cleanProductText(event.memory_text || event.rag_text, 240),
    training: Boolean(event.eligible_for_training),
    rag: Boolean(event.eligible_for_rag),
    status: cleanProductText(event.status || event.approval_status || "captured", 80),
  })).filter((event) => event.text), [multimodalMemoryEvents]);
  const inboxAnalysisCounts = {
    voice: inboxVoiceInsights.length,
    vision: inboxVisionInsights.length,
    memory: multimodalMemoryEvents.length,
    approvedReferences: webSearchItems.filter(({ result }) => result.approval_status === "approved").length,
    pendingReferences: webSearchItems.filter(({ result }) => result.approval_status === "pending").length,
  };
  const filteredConversations = conversations.filter((conversation) => {
    const channelOk = inboxChannelFilter === "all" || String(conversation.channel || "").toLowerCase() === inboxChannelFilter;
    const agentOk = inboxAgentFilter === "all" || String(conversation.assigned_ai_agent_id || "") === inboxAgentFilter;
    const queueOk = (() => {
      if (inboxQueueFilter === "all") return true;
      if (inboxQueueFilter === "unread") return Number(conversation.unread_count || 0) > 0;
      if (inboxQueueFilter === "mine") return String(conversation.assigned_user_id || "") === String(me?.user_id || "");
      if (inboxQueueFilter === "unassigned") return !conversation.assigned_user_id;
      if (inboxQueueFilter === "sla") return isPastDate(conversation.sla_due_at || conversation.first_response_due_at);
      if (inboxQueueFilter === "hot") return Number(conversation.lead_score || 0) >= 75 || String(conversation.lead_temperature || "").toLowerCase() === "hot";
      if (inboxQueueFilter === "churn") return Number(conversation.predictive_intelligence?.churn_risk || 0) >= 70;
      if (inboxQueueFilter === "human") return Boolean(conversation.takeover);
      if (inboxQueueFilter === "ai") return !conversation.takeover;
      return true;
    })();
    const needle = inboxSearch.trim().toLowerCase();
    if (!channelOk || !queueOk || !agentOk) return false;
    if (!needle) return true;
    return [
      conversation.display_name,
      conversation.phone,
      conversation.external_contact_id,
      conversation.last_message_text,
      conversation.tags,
    ].some((value) => String(value || "").toLowerCase().includes(needle));
  });
  const filteredSocialComments = socialComments.filter((comment) => {
    const channelOk = inboxChannelFilter === "all" || String(comment.channel || "").toLowerCase() === inboxChannelFilter;
    const needle = inboxSearch.trim().toLowerCase();
    if (!channelOk) return false;
    if (!needle) return true;
    return [
      comment.author_name,
      comment.author_username,
      comment.author_external_id,
      comment.message,
      comment.post_caption,
    ].some((value) => String(value || "").toLowerCase().includes(needle));
  });
  const emojiNeedle = emojiSearch.trim().toLowerCase();
  const visibleEmojiGroups = [
    { label: "Recientes", icon: "↺", items: recentEmojis },
    ...EMOJI_GROUPS,
  ].map((group) => ({
    ...group,
    items: group.items.filter((emoji) => emojiMatchesNeedle(emoji, emojiNeedle, group)),
  })).filter((group) => group.items.length);
  const dashboardTotals = dashboardOverview?.totals || {};
  const dashboardFunnel = dashboardOverview?.funnel || [];
  const dashboardActivity = dashboardOverview?.activity || [];
  const dashboardRecent = dashboardOverview?.recent || [];
  const dashboardChannels = dashboardOverview?.channels || [];
  const dashboardPredictive = dashboardOverview?.predictive || {};
  const dashboardActivityMax = Math.max(1, ...dashboardActivity.map((item) => Number(item.total || 0)));
  const dashboardConversations = Number(dashboardTotals.conversations ?? conversations.length);
  const dashboardUnread = Number(dashboardTotals.unread ?? unreadTotal);
  const selectedPredictive = selectedConversation?.predictive_intelligence || {};
  const viewTitles = {
    dashboard: [t("page.dashboard.title"), t("page.dashboard.description")],
    inbox: [t("page.inbox.title"), t("page.inbox.description")],
    customers: [t("page.customers.title"), t("page.customers.description")],
    labels: [t("page.labels.title"), t("page.labels.description")],
    campaigns: [t("page.campaigns.title"), t("page.campaigns.description")],
    broadcast: [t("page.broadcast.title"), t("page.broadcast.description")],
    ads: [t("page.ads.title"), t("page.ads.description")],
    agents: [t("page.agents.title"), t("page.agents.description")],
    intelligence: [t("page.intelligence.title"), t("page.intelligence.description")],
    ecosystem: [t("page.ecosystem.title"), t("page.ecosystem.description")],
    composer: [t("page.composer.title"), t("page.composer.description")],
    trust: [t("page.trust.title"), t("page.trust.description")],
    settings: [t("page.settings.title"), t("page.settings.description")],
  };
  const advisorPendingActionCount = advisorActions.filter((item) => ["draft", "pending_approval", "approved"].includes(item.status)).length;
  const advisorSignalCount = advisorBriefing.length + advisorInsights.length + advisorRecommendations.length + advisorPendingActionCount;
  const advisorQuickPrompts = [
    "Dame un resumen ejecutivo de la empresa hoy.",
    "Que oportunidades comerciales ves ahora?",
    "Que automatizacion o trigger recomendarias primero?",
  ];
  const selectedIntegrationForForm = integrations.find((item) => (
    String(item.provider || "").toLowerCase() === String(integrationForm.provider || "").toLowerCase()
    && String(item.channel || "").toLowerCase() === String(integrationForm.channel || "").toLowerCase()
  ));
  const selectedIntegrationConfig = selectedIntegrationForForm?.config_json || {};
  const selectedInstagramIntegration = integrations.find((item) => (
    String(item.provider || "").toLowerCase() === "meta"
    && String(item.channel || "").toLowerCase() === "instagram"
  ));
  const selectedInstagramConfig = selectedInstagramIntegration?.config_json || {};
  const selectedFacebookIntegration = integrations.find((item) => (
    String(item.provider || "").toLowerCase() === "meta"
    && String(item.channel || "").toLowerCase() === "facebook"
  ));
  const selectedFacebookConfig = selectedFacebookIntegration?.config_json || {};
  const facebookGrantedPermissions = facebookDiagnostics?.granted_permissions || [];
  const facebookMissingPermissions = facebookDiagnostics?.missing_permissions || [];
  const facebookMetaRequiredPermissions = facebookDiagnostics?.meta_required_permissions || [];
  const integrationToForm = (integration) => {
    const config = integration?.config_json || {};
    return {
      provider: integration?.provider || "meta",
      channel: integration?.channel || "whatsapp",
      status: integration?.status || "connected",
      dispatch_mode: config.dispatch_mode || "stub",
      phone_number_id: config.phone_number_id || "",
      business_account_id: config.business_account_id || config.waba_id || "",
      app_id: config.app_id || "",
      graph_api_version: config.graph_api_version || "v24.0",
      access_token_env: config.access_token_env || "SCENTRA_META_ACCESS_TOKEN",
    };
  };
  const instagramIntegrationToForm = (integration) => {
    const config = integration?.config_json || {};
    return {
      ...defaultInstagramForm(),
      provider: integration?.provider || "meta",
      channel: integration?.channel || "instagram",
      status: integration?.status || "connected",
      dispatch_mode: config.dispatch_mode || "instagram_graph",
      page_id: config.page_id || config.facebook_page_id || "",
      page_name: config.page_name || "",
      business_id: config.business_id || "",
      business_name: config.business_name || "",
      instagram_business_account_id: config.instagram_business_account_id || config.ig_business_id || "",
      instagram_username: config.instagram_username || "",
      app_id: config.app_id || "",
      graph_api_version: config.graph_api_version || "v24.0",
    };
  };
  const facebookIntegrationToForm = (integration) => {
    const config = integration?.config_json || {};
    return {
      ...defaultFacebookForm(),
      provider: integration?.provider || "meta",
      channel: integration?.channel || "facebook",
      status: integration?.status || "connected",
      dispatch_mode: config.dispatch_mode || "facebook_graph",
      page_id: config.page_id || config.facebook_page_id || "",
      page_name: config.page_name || "",
      business_id: config.business_id || "",
      business_name: config.business_name || "",
      app_id: config.app_id || "",
      graph_api_version: config.graph_api_version || "v24.0",
    };
  };

  const showStatus = (text, tone = "neutral") => { setStatus(text); setStatusTone(tone); };

  useEffect(() => {
    const token = new URLSearchParams(window.location.search).get("reset_token") || "";
    if (!token) return;
    setMode("reset");
    setPasswordReset((prev) => ({ ...prev, token }));
  }, []);

  useEffect(() => { loadPublicVerticalPacks(); }, []);

  const showMilestoneOnce = (key, notice = {}) => {
    const cleanKey = String(key || "").trim();
    if (!cleanKey) return;
    try {
      const seen = JSON.parse(localStorage.getItem(SEEN_MILESTONES_KEY) || "{}") || {};
      if (seen[cleanKey]) return;
      seen[cleanKey] = new Date().toISOString();
      localStorage.setItem(SEEN_MILESTONES_KEY, JSON.stringify(seen));
      setMilestoneNotice({ key: cleanKey, ...notice });
    } catch {
      setMilestoneNotice({ key: cleanKey, ...notice });
    }
  };

  const closeMilestoneNotice = (runAction = false) => {
    const actionType = milestoneNotice?.actionType || "";
    setMilestoneNotice(null);
    if (!runAction) return;
    if (actionType === "advisor") setAdvisorOpen(true);
    if (actionType === "settings-apis") {
      setActiveView("settings");
      setSettingsTab("apis");
    }
    if (actionType === "settings-debug") {
      setActiveView("settings");
      setSettingsTab("debug");
      loadDiagnostics(true);
    }
    if (actionType === "settings-channels") {
      setActiveView("settings");
      setSettingsTab("channels");
    }
  };

  const refreshAccessToken = async () => {
    if (!API_BASE) throw new Error("VITE_API_BASE requerido");
    const storedRefreshToken = refreshToken || localStorage.getItem(REFRESH_KEY) || "";
    if (!storedRefreshToken) throw new Error("session_refresh_missing");
    if (!refreshPromiseRef.current) {
      refreshPromiseRef.current = fetch(`${API_BASE}/saas/v1/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: storedRefreshToken, tenant_id: me?.tenant_id || "" }),
      })
        .then(async (res) => {
          const data = await res.json().catch(() => ({}));
          if (!res.ok) throw new Error(formatApiError(data, `HTTP ${res.status}`));
          setTokens(data);
          return data?.access_token || "";
        })
        .finally(() => { refreshPromiseRef.current = null; });
    }
    return refreshPromiseRef.current;
  };

  const apiCall = async (path, options = {}) => {
    if (!API_BASE) throw new Error("VITE_API_BASE requerido");
    const skipAuthRefreshPath = ["/saas/v1/auth/login", "/saas/v1/auth/register", "/saas/v1/auth/refresh", "/saas/v1/auth/password/forgot", "/saas/v1/auth/password/reset"].some((prefix) => String(path || "").startsWith(prefix));
    const runFetch = async (tokenOverride = null) => {
      const requestHeaders = { "Content-Type": "application/json", ...(options.headers || {}) };
      const bearer = tokenOverride ?? accessToken;
      if (bearer) requestHeaders.Authorization = `Bearer ${bearer}`;
      if (options.body instanceof FormData) delete requestHeaders["Content-Type"];
      const response = await fetch(`${API_BASE}${path}`, { ...options, headers: requestHeaders });
      const payload = await response.json().catch(() => ({}));
      return { response, payload };
    };

    let { response: res, payload: data } = await runFetch();
    if (res.status === 401 && !skipAuthRefreshPath && !options.skipAuthRefresh) {
      try {
        const nextAccessToken = await refreshAccessToken();
        if (nextAccessToken) ({ response: res, payload: data } = await runFetch(nextAccessToken));
      } catch {
        clearTokens();
        throw new Error("Sesion vencida. Ingresa nuevamente para continuar.");
      }
    }
    if (res.status === 401 && !skipAuthRefreshPath) clearTokens();
    if (!res.ok) throw new Error(formatApiError(data, `HTTP ${res.status}`));
    return data;
  };
  const streamApiCall = async (path, options = {}) => {
    if (!API_BASE) throw new Error("VITE_API_BASE requerido");
    const runFetch = async (tokenOverride = null) => {
      const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
      const bearer = tokenOverride ?? accessToken;
      if (bearer) headers.Authorization = `Bearer ${bearer}`;
      return fetch(`${API_BASE}${path}`, { ...options, headers });
    };
    let response = await runFetch();
    if (response.status === 401 && !options.skipAuthRefresh) {
      try {
        const nextAccessToken = await refreshAccessToken();
        if (nextAccessToken) response = await runFetch(nextAccessToken);
      } catch {
        clearTokens();
        throw new Error("Sesion vencida. Ingresa nuevamente para continuar.");
      }
    }
    if (response.status === 401) clearTokens();
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(formatApiError(data, `HTTP ${response.status}`));
    }
    return response;
  };
  const downloadApiFile = async (path, filename = "scentra.pdf") => {
    if (!API_BASE) throw new Error("VITE_API_BASE requerido");
    const runFetch = async (tokenOverride = null) => {
      const requestHeaders = {};
      const bearer = tokenOverride ?? accessToken;
      if (bearer) requestHeaders.Authorization = `Bearer ${bearer}`;
      return fetch(`${API_BASE}${path}`, { headers: requestHeaders });
    };
    let response = await runFetch();
    if (response.status === 401) {
      try {
        const nextAccessToken = await refreshAccessToken();
        if (nextAccessToken) response = await runFetch(nextAccessToken);
      } catch {
        clearTokens();
        throw new Error("Sesion vencida. Ingresa nuevamente para continuar.");
      }
    }
    if (response.status === 401) clearTokens();
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(formatApiError(data, `HTTP ${response.status}`));
    }
    const blob = await response.blob();
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
  const setTokens = (data) => {
    const nextAccess = data?.access_token || "";
    const nextRefresh = data?.refresh_token || refreshToken || "";
    setAccessToken(nextAccess);
    setRefreshToken(nextRefresh);
    if (nextAccess) localStorage.setItem(TOKEN_KEY, nextAccess);
    if (nextRefresh) localStorage.setItem(REFRESH_KEY, nextRefresh);
  };

  const clearComposerAttachment = () => {
    if (attachmentPreview) URL.revokeObjectURL(attachmentPreview);
    setAttachmentFile(null);
    setAttachmentKind("");
    setAttachmentPreview("");
    setAttachmentWaveform(EMPTY_WAVEFORM);
    attachmentSignatureRef.current = "";
    if (composerFileRef.current) composerFileRef.current.value = "";
  };

  const setComposerAttachment = (file, forcedKind = "", knownWaveform = null) => {
    if (!file) return;
    clearComposerAttachment();
    setCatalogDraft(null);
    const kind = forcedKind || mediaKindFromMime(file.type);
    const signature = `${file.name || "archivo"}:${file.size || 0}:${file.lastModified || Date.now()}`;
    attachmentSignatureRef.current = signature;
    setAttachmentFile(file);
    setAttachmentKind(kind);
    setAttachmentPreview(URL.createObjectURL(file));
    setAttachmentWaveform(Array.isArray(knownWaveform) && knownWaveform.length ? knownWaveform : waveformFromSeed(signature));
    if (kind === "audio") {
      analyzeAudioBlobWaveform(file)
        .then((bars) => {
          if (attachmentSignatureRef.current === signature && bars?.length) setAttachmentWaveform(bars);
        })
        .catch(() => {});
    }
  };

  const clearWorkspaceState = () => {
    setConversations([]); setSelectedConversation(null); setConversationMemory(null); setMessages([]); setMultimodalMemoryEvents([]); setReplyText("");
    clearComposerAttachment(); setCatalogDraft(null); setEmojiOpen(false); setAttachMenuOpen(false); setInboxChannelFilter("all"); setInboxSearch(""); setIsRecording(false); setRecordingSeconds(0); setRecordingLevels(EMPTY_WAVEFORM);
    recordingLevelsRef.current = EMPTY_WAVEFORM;
    setIntegrations([]); setWebhooks([]); setWebhookEvents([]); setWebhookCheck(null); setBillingOverview(null); setBillingPlans([]); setBillingCheckoutSessions([]); setBillingInvoices([]); setLastWebhookSecret(null);
    setApiCredentials([]); setCredentialModal(null); setCredentialModels({}); setKnowledgeSources([]); setKnowledgeHealth(null); setKnowledgeSearch({ query: "", results: [], citations: [], confidence: 0, retrievalMode: "", searched: false }); setKnowledgeEvaluations([]); setKnowledgeEvalForm({ query: "", expectedAnswer: "", expectedSources: "" }); setDiagnostics(null); setAiGatewayProviders([]); setAiGatewayRuns([]);
    setAdvisorOpen(false); setAdvisorThreadId(""); setAdvisorMessages([]); setAdvisorInput(""); setAdvisorInsights([]); setAdvisorRecommendations([]); setAdvisorActions([]); setAdvisorMetrics(null); setAdvisorActivity([]); setAdvisorMemory(null); setAdvisorStreamStatus(""); setAdvisorLastSync(""); setAdvisorLoading(false);
    setInstagramDiagnostics(null); setFacebookDiagnostics(null); setInstagramOAuth({ state: "", assets: [], status: "", callbackUrl: "" });
    setInstagramForm(defaultInstagramForm());
    setDebugInboundResult(null); setSubscriptionCheck(null);
    setIntegrationSecretModal(null);
    setMilestoneNotice(null);
    setWhatsappPhones([]); setPhoneRegisterForm({ phone_number_id: "", pin: "" });
  };

  const clearTokens = () => {
    setAccessToken(""); setRefreshToken(""); setMe(null); setTenants([]); clearWorkspaceState();
    setMfaChallenge(null); setMfaCode(""); setMode("login");
    localStorage.removeItem(TOKEN_KEY); localStorage.removeItem(REFRESH_KEY);
  };

  const loadSession = async () => {
    if (!accessToken) return;
    try {
      const data = await apiCall("/saas/v1/auth/me");
      setMe(data); setTenants(data?.tenants || []);
      setProfileForm((prev) => ({ ...prev, fullName: prev.fullName || data?.full_name || "", email: prev.email || data?.email || "" }));
    } catch (err) { showStatus(String(err.message || err), "error"); }
  };

  const loadSecurityStatus = async () => {
    if (!accessToken) return;
    try {
      const data = await apiCall("/saas/v1/auth/security");
      setSecurityForm((prev) => ({
        ...prev,
        twoFactorEnabled: Boolean(data?.two_factor_enabled),
        twoFactorMethod: data?.two_factor_method && data.two_factor_method !== "none" ? data.two_factor_method : "email_otp",
        passwordChangedAt: data?.password_changed_at || "",
      }));
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

  const loadApiCredentials = async () => {
    if (!accessToken) return;
    try { setApiCredentials((await apiCall("/saas/v1/api-credentials")) || []); }
    catch (err) { showStatus(String(err.message || err), "error"); }
  };

  const loadKnowledgeSources = async () => {
    if (!accessToken) return;
    try {
      const [sourcesData, healthData, evalData] = await Promise.all([
        apiCall("/saas/v1/knowledge/sources"),
        apiCall("/saas/v1/knowledge/health"),
        apiCall("/saas/v1/knowledge/evaluations?limit=8"),
      ]);
      setKnowledgeSources(sourcesData || []);
      setKnowledgeHealth(healthData || null);
      setKnowledgeEvaluations(evalData || []);
    }
    catch (err) { showStatus(String(err.message || err), "error"); }
  };

  const loadDiagnostics = async (silent = false) => {
    if (!accessToken) return;
    try {
      const data = await apiCall("/saas/v1/diagnostics/overview");
      setDiagnostics(data);
      if (!silent) showStatus("Diagnostico actualizado", "ok");
    } catch (err) { showStatus(String(err.message || err), "error"); }
  };

  const loadAiGateway = async (silent = false) => {
    if (!accessToken) return;
    try {
      const [providersData, runsData] = await Promise.all([
        apiCall("/saas/v1/ai-gateway/providers"),
        apiCall("/saas/v1/ai-gateway/runs?limit=12"),
      ]);
      setAiGatewayProviders(providersData?.providers || []);
      setAiGatewayRuns(runsData?.runs || []);
      if (!silent) showStatus("AI Gateway actualizado", "ok");
    } catch (err) { if (!silent) showStatus(String(err.message || err), "error"); }
  };

  const loadAdvisorSignals = async (silent = false) => {
    if (!accessToken) return;
    try {
      const data = await apiCall("/saas/v1/advisor/briefing");
      setAdvisorBriefing(data?.briefing || []);
      setAdvisorInsights(data?.insights || []);
      setAdvisorRecommendations(data?.recommendations || []);
      setAdvisorActions(data?.actions || []);
      setAdvisorMetrics(data?.metrics || null);
      setAdvisorActivity(data?.activity || []);
      setAdvisorMemory(data?.memory || null);
      setAdvisorLastSync(new Date().toISOString());
      if (!silent) showStatus("Advisor actualizado", "ok");
    } catch (err) { if (!silent) showStatus(String(err.message || err), "error"); }
  };

  const loadAdvisorHistory = async () => {
    if (!accessToken || advisorMessages.length) return;
    try {
      const data = await apiCall("/saas/v1/advisor/threads?limit=1");
      const thread = (data?.threads || [])[0];
      if (!thread?.id) return;
      setAdvisorThreadId(thread.id);
      const messagesData = await apiCall(`/saas/v1/advisor/threads/${encodeURIComponent(thread.id)}`);
      setAdvisorMessages(messagesData?.messages || []);
    } catch {
      // El historial no bloquea el uso del Advisor.
    }
  };

  const loadAiSettings = async () => {
    if (!accessToken) return;
    try {
      const data = await apiCall("/saas/v1/ai/settings");
      const meta = asObject(data?.metadata_json);
      setAiConfig((prev) => ({
        ...prev,
        enabled: Boolean(data?.enabled),
        provider: data?.provider_code || prev.provider,
        fallbackProvider: data?.fallback_provider_code || prev.fallbackProvider,
        systemPrompt: data?.system_prompt || prev.systemPrompt,
        maxTokens: String(data?.max_tokens || prev.maxTokens),
        temperature: String(data?.temperature ?? prev.temperature),
        humanReplyStyle: meta.human_reply_style_enabled !== false,
        humanReplySplitting: meta.human_reply_splitting_enabled !== false,
        replyMaxOutputTokens: String(meta.reply_max_output_tokens ?? data?.max_tokens ?? prev.replyMaxOutputTokens),
        chunks: String(meta.reply_chunk_chars ?? prev.chunks),
        delayBetween: String(meta.reply_chunk_delay_ms ?? prev.delayBetween),
        typingDelay: String(meta.reply_initial_delay_ms ?? prev.typingDelay),
        cooldown: String(meta.inbound_cooldown_seconds ?? prev.cooldown),
        recentMessageLimit: String(meta.recent_message_limit ?? prev.recentMessageLimit),
        messageContextChars: String(meta.message_context_chars ?? prev.messageContextChars),
        typingIndicator: meta.typing_indicator_enabled !== false,
        voiceEnabled: meta.voice_enabled ?? prev.voiceEnabled,
        preferVoice: meta.prefer_voice ?? prev.preferVoice,
        ttsProvider: meta.tts_provider || prev.ttsProvider,
        voiceAnalysisProvider: meta.voice_analysis_provider || prev.voiceAnalysisProvider,
        visionAnalysisProvider: meta.vision_analysis_provider || prev.visionAnalysisProvider,
        webImageSearchProvider: meta.web_image_search_provider || prev.webImageSearchProvider,
        voiceId: meta.voice_id || prev.voiceId,
        voiceName: meta.voice_name || prev.voiceName,
        voicePrompt: meta.voice_prompt || prev.voicePrompt,
      }));
      if (meta.web_image_search_provider) {
        setWebSearchForm((prev) => ({ ...prev, providerCode: meta.web_image_search_provider }));
      }
    } catch (err) { showStatus(String(err.message || err), "error"); }
  };

  const loadConversationMemory = async (conversationId) => {
    if (!accessToken || !conversationId) return;
    try {
      const data = await apiCall(`/saas/v1/ai/conversations/${encodeURIComponent(conversationId)}/memory`);
      setConversationMemory(data || null);
    } catch {
      setConversationMemory(null);
    }
  };

  const loadBilling = async () => {
    if (!accessToken) return;
    try {
      const [overviewData, plansData, checkoutData, invoiceData] = await Promise.all([
        apiCall("/saas/v1/billing/overview"),
        apiCall("/saas/v1/billing/plans"),
        apiCall("/saas/v1/billing/checkout-sessions?limit=8").catch(() => ({ checkout_sessions: [] })),
        apiCall("/saas/v1/billing/invoices?limit=8").catch(() => ({ invoices: [] })),
      ]);
      setBillingOverview(overviewData); setBillingPlans(plansData?.plans || []); setBillingCheckoutSessions(checkoutData?.checkout_sessions || []); setBillingInvoices(invoiceData?.invoices || []);
    } catch (err) { showStatus(String(err.message || err), "error"); }
  };

  const loadDashboard = async (silent = false) => {
    if (!accessToken) return;
    try {
      const [overviewData, dashboardData, inboxData, integrationData, endpointData, eventData, plansData, checkoutData, invoiceData] = await Promise.all([
        apiCall("/saas/v1/billing/overview"), apiCall("/saas/v1/dashboard/overview"), apiCall("/saas/v1/conversations?limit=100"), apiCall("/saas/v1/integrations"),
        apiCall("/saas/v1/webhooks/endpoints"), apiCall("/saas/v1/webhooks/events?limit=20"), apiCall("/saas/v1/billing/plans"),
        apiCall("/saas/v1/billing/checkout-sessions?limit=8").catch(() => ({ checkout_sessions: [] })),
        apiCall("/saas/v1/billing/invoices?limit=8").catch(() => ({ invoices: [] })),
      ]);
      setBillingOverview(overviewData); setDashboardOverview(dashboardData); setConversations(inboxData?.conversations || []); setIntegrations(integrationData || []);
      setWebhooks(endpointData || []); setWebhookEvents(eventData || []); setBillingPlans(plansData?.plans || []); setBillingCheckoutSessions(checkoutData?.checkout_sessions || []); setBillingInvoices(invoiceData?.invoices || []);
      if (!silent) showStatus(t("status.dashboard.updated"), "ok");
    } catch (err) { showStatus(String(err.message || err), "error"); }
  };

  const loadCrmConfig = async (silent = true) => {
    if (!accessToken) return null;
    try {
      const data = await apiCall("/saas/v1/crm/config");
      setCrmConfig({
        custom_fields: data?.custom_fields || [],
        pipeline: data?.pipeline || { stages: [] },
        industry_presets: data?.industry_presets || [],
      });
      if (!silent) showStatus("Configuracion CRM actualizada", "ok");
      return data;
    } catch (err) {
      if (!silent) showStatus(String(err.message || err), "error");
      return null;
    }
  };

  const loadPublicVerticalPacks = async () => {
    try {
      const data = await apiCall("/saas/v1/verticals/public-packs", { skipAuthRefresh: true });
      const packs = data?.packs?.length ? data.packs : FALLBACK_VERTICAL_PACKS;
      setPublicVerticalPacks(packs);
      if (!accessToken) setVerticalPacks(packs);
      setRegister((prev) => ({ ...prev, industry_code: prev.industry_code || packs[0]?.code || "general" }));
    } catch {
      setPublicVerticalPacks(FALLBACK_VERTICAL_PACKS);
    }
  };

  const loadVerticalState = async (silent = true) => {
    if (!accessToken) return null;
    try {
      const [packsData, stateData] = await Promise.all([
        apiCall("/saas/v1/verticals/packs"),
        apiCall("/saas/v1/verticals/state"),
      ]);
      const packs = packsData?.packs?.length ? packsData.packs : FALLBACK_VERTICAL_PACKS;
      setVerticalPacks(packs);
      setVerticalState(stateData || null);
      const activeCode = stateData?.tenant?.industry_code || packs[0]?.code || "general";
      setVerticalApply((prev) => ({ ...prev, industry_code: activeCode }));
      if (!silent) showStatus("Verticalizacion actualizada", "ok");
      return stateData;
    } catch (err) {
      if (!silent) showStatus(String(err.message || err), "error");
      return null;
    }
  };

  const applyVerticalPack = async () => {
    if (!verticalApply.industry_code) return showStatus("Elige una industria.", "error");
    setVerticalBusy(true);
    try {
      const data = await apiCall("/saas/v1/verticals/apply", {
        method: "POST",
        body: JSON.stringify(verticalApply),
      });
      setVerticalState(data || null);
      await Promise.all([loadCrmConfig(true), loadSession(), loadDashboard(true).catch(() => null)]);
      showStatus(`Pack ${data?.pack?.label || verticalApply.industry_code} aplicado`, "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setVerticalBusy(false);
    }
  };

  const loadMessages = async (conversation, options = {}) => {
    if (!conversation?.id) return;
    try {
      const [data, memoryData, tasksData, statusData, timelineData, dedupeData, searchData, multimodalData] = await Promise.all([
        apiCall(`/saas/v1/conversations/${encodeURIComponent(conversation.id)}/messages`),
        apiCall(`/saas/v1/ai/conversations/${encodeURIComponent(conversation.id)}/memory`).catch(() => null),
        apiCall(`/saas/v1/conversations/${encodeURIComponent(conversation.id)}/tasks`).catch(() => ({ tasks: [] })),
        apiCall(`/saas/v1/conversations/${encodeURIComponent(conversation.id)}/status-events?limit=40`).catch(() => ({ events: [] })),
        apiCall(`/saas/v1/conversations/${encodeURIComponent(conversation.id)}/timeline?limit=80`).catch(() => ({ events: [] })),
        apiCall(`/saas/v1/customers/${encodeURIComponent(conversation.id)}/dedupe-candidates?limit=6`).catch(() => ({ candidates: [] })),
        apiCall(`/saas/v1/media/search/runs?conversation_id=${encodeURIComponent(conversation.id)}&limit=8`).catch(() => ({ runs: [] })),
        apiCall(`/saas/v1/agents/multimodal-memory/events?conversation_id=${encodeURIComponent(conversation.id)}&limit=24`).catch(() => ({ events: [] })),
      ]);
      const selected = { ...conversation, unread_count: 0 };
      setSelectedConversation(selected); setMessages(data?.messages || []);
      setConversationMemory(memoryData || null);
      setConversationTasks(tasksData?.tasks || []);
      setMessageStatusEvents(statusData?.events || []);
      setConversationTimeline(timelineData?.events || []);
      setDedupeCandidates(dedupeData?.candidates || []);
      setWebSearchRuns(searchData?.runs || []);
      setMultimodalMemoryEvents(multimodalData?.events || []);
      if (!options.preserveComposer) { setReplyText(""); clearComposerAttachment(); setCatalogDraft(null); setEmojiOpen(false); setAttachMenuOpen(false); }
      if (Number(conversation.unread_count || 0) > 0) markConversationRead(conversation.id, { silent: true });
    } catch (err) { showStatus(String(err.message || err), "error"); }
  };

  const loadSocialComments = async (options = {}) => {
    if (!accessToken) return;
    try {
      const params = new URLSearchParams({ limit: "100" });
      if (inboxChannelFilter !== "all") params.set("channel", inboxChannelFilter);
      const [commentsData, settingsData] = await Promise.all([
        apiCall(`/saas/v1/social/comments?${params.toString()}`),
        apiCall("/saas/v1/social/comments/settings").catch(() => null),
      ]);
      const items = commentsData?.comments || [];
      setSocialComments(items);
      setCommentAiSettings(settingsData?.settings || null);
      if (!options.keepSelection) setSelectedComment((prev) => prev || items[0] || null);
      if (!items.length) setSelectedComment(null);
    } catch (err) { showStatus(String(err.message || err), "error"); }
  };

  const buildInboxConversationPath = () => {
    const params = new URLSearchParams({ limit: "200" });
    const cleanSearch = inboxSearch.trim();
    if (cleanSearch) params.set("search", cleanSearch);
    if (inboxChannelFilter !== "all") params.set("channel", inboxChannelFilter);
    if (inboxAgentFilter !== "all") params.set("agent_id", inboxAgentFilter);
    if (inboxMode === "dms" && inboxQueueFilter !== "all") params.set("queue", inboxQueueFilter);
    return `/saas/v1/conversations?${params.toString()}`;
  };

  const buildSocialCommentsPath = () => {
    const params = new URLSearchParams({ limit: "100" });
    if (inboxChannelFilter !== "all") params.set("channel", inboxChannelFilter);
    return `/saas/v1/social/comments?${params.toString()}`;
  };

  const notifyInboxItem = (kind, item) => {
    if (!browserNotificationsEnabled || notificationPermission !== "granted") return;
    if (typeof window === "undefined" || !("Notification" in window)) return;
    const key = kind === "comment"
      ? `comment:${item?.id || ""}:${item?.updated_at || item?.created_at || ""}`
      : `message:${item?.id || ""}:${item?.last_message_at || item?.updated_at || ""}:${item?.unread_count || 0}`;
    if (!key.trim() || lastNotifiedInboxKeyRef.current === key) return;
    lastNotifiedInboxKeyRef.current = key;
    const title = kind === "comment" ? "Nuevo comentario" : "Nuevo mensaje";
    const body = kind === "comment"
      ? `${item?.author_name || item?.author_username || "Comentario"}: ${item?.message || ""}`.slice(0, 140)
      : `${item?.display_name || item?.phone || item?.external_contact_id || "Cliente"}: ${item?.last_message_text || ""}`.slice(0, 140);
    try {
      const notification = new window.Notification(title, {
        body,
        tag: key,
        silent: true,
      });
      notification.onclick = () => {
        window.focus();
        setActiveView("inbox");
      };
    } catch {
      // Browser notification permissions can change outside the app.
    }
  };

  const loadInbox = async (options = {}) => {
    if (!accessToken) return;
    if (inboxRequestRef.current && !options.force) return inboxRequestRef.current;
    setInboxRefreshing(true);
    const requestSeq = inboxRequestSeqRef.current + 1;
    inboxRequestSeqRef.current = requestSeq;
    const run = (async () => {
      const [data, commentsData, agentsData] = await Promise.all([
        apiCall(buildInboxConversationPath()),
        apiCall(buildSocialCommentsPath()).catch(() => ({ comments: [] })),
        apiCall("/saas/v1/agents").catch(() => ({ agents: [] })),
      ]);
      if (requestSeq !== inboxRequestSeqRef.current) return;
      const items = data?.conversations || [];
      const comments = commentsData?.comments || [];
      setInboxAiAgents(agentsData?.agents || []);
      const previousUnread = Number(lastUnreadTotalRef.current || 0);
      const previousOpenComments = Number(lastOpenCommentsRef.current || 0);
      const nextUnread = items.reduce((sum, item) => sum + Number(item.unread_count || 0), 0);
      const nextOpenComments = comments.filter((item) => String(item.status || "open").toLowerCase() === "open").length;
      if (previousUnread && nextUnread > previousUnread) {
        if (notificationSoundEnabled) playIncomingSound();
        notifyInboxItem("message", items.find((item) => Number(item.unread_count || 0) > 0) || items[0]);
      }
      if (previousOpenComments && nextOpenComments > previousOpenComments) {
        if (notificationSoundEnabled) playIncomingSound();
        notifyInboxItem("comment", comments.find((item) => String(item.status || "open").toLowerCase() === "open") || comments[0]);
      }
      lastUnreadTotalRef.current = nextUnread;
      lastOpenCommentsRef.current = nextOpenComments;
      setConversations(items);
      setSocialComments(comments);
      if (items.length && !selectedConversation) await loadMessages(items[0]);
      if (items.length && selectedConversation?.id) {
        const updatedSelected = items.find((item) => item.id === selectedConversation.id);
        if (updatedSelected) await loadMessages({ ...selectedConversation, ...updatedSelected }, { preserveComposer: true });
      }
      if (!items.length) { setSelectedConversation(null); setConversationMemory(null); setConversationTasks([]); setMessageStatusEvents([]); setWebSearchRuns([]); setMultimodalMemoryEvents([]); setMessages([]); setReplyText(""); clearComposerAttachment(); setCatalogDraft(null); }
      setInboxLastSyncAt(new Date().toISOString());
      setInboxSyncError("");
    })()
      .catch((err) => {
        const message = String(err.message || err);
        setInboxSyncError(message);
        showStatus(message, "error");
      })
      .finally(() => {
        if (requestSeq === inboxRequestSeqRef.current) {
          inboxRequestRef.current = null;
          setInboxRefreshing(false);
        }
      });
    inboxRequestRef.current = run;
    return run;
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
    if (browserNotificationsEnabled && notificationPermission !== "granted") {
      localStorage.setItem(BROWSER_NOTIFICATIONS_KEY, "false");
      setBrowserNotificationsEnabled(false);
    }
  }, [browserNotificationsEnabled, notificationPermission]);
  useEffect(() => {
    if (accessToken) loadAdvisorSignals(true);
    if (accessToken && ["dashboard", "customers", "labels", "campaigns", "broadcast", "ads"].includes(activeView)) loadDashboard(true);
    if (accessToken && activeView === "settings") Promise.all([loadIntegrations(), loadWebhooks(), loadBilling(), loadApiCredentials(), loadAiSettings(), loadKnowledgeSources(), loadDiagnostics(true), loadAiGateway(true), loadVerticalState(true)]);
    if (accessToken && activeView === "inbox") loadInbox();
  }, [accessToken, activeView]);

  useEffect(() => {
    if (!accessToken) return undefined;
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") loadAdvisorSignals(true);
    }, advisorOpen ? 30000 : 60000);
    return () => window.clearInterval(timer);
  }, [accessToken, advisorOpen]);

  useEffect(() => {
    if (accessToken && activeView === "settings" && settingsTab === "security") loadSecurityStatus();
  }, [accessToken, activeView, settingsTab]);

  useEffect(() => {
    if (advisorOpen) {
      loadAdvisorHistory();
      loadAdvisorSignals(true);
    }
  }, [advisorOpen]);

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      if (advisorChatRef.current) advisorChatRef.current.scrollTop = advisorChatRef.current.scrollHeight;
    });
    return () => window.cancelAnimationFrame(frame);
  }, [advisorMessages, advisorLoading]);

  useEffect(() => {
    if (!accessToken || activeView !== "inbox") return undefined;
    let stopped = false;
    let timer = null;
    const schedule = (delay) => {
      timer = window.setTimeout(async () => {
        if (stopped) return;
        if (document.visibilityState === "visible") await loadInbox();
        const nextDelay = document.visibilityState === "visible"
          ? (selectedConversation?.id ? 5000 : 8000)
          : 20000;
        schedule(nextDelay);
      }, delay);
    };
    const handleVisibility = () => {
      if (document.visibilityState === "visible") loadInbox({ force: true });
    };
    document.addEventListener("visibilitychange", handleVisibility);
    schedule(5000);
    return () => {
      stopped = true;
      if (timer) window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, [accessToken, activeView, selectedConversation?.id, notificationSoundEnabled, browserNotificationsEnabled]);

  useEffect(() => {
    if (!accessToken || activeView !== "inbox") return undefined;
    const timer = window.setTimeout(() => loadInbox({ force: true }), 350);
    return () => window.clearTimeout(timer);
  }, [accessToken, activeView, inboxChannelFilter, inboxQueueFilter, inboxAgentFilter, inboxSearch, inboxMode]);

  useEffect(() => {
    const metaWhatsapp = integrations.find((item) => item.provider === "meta" && item.channel === "whatsapp");
    const formIsEmptyMeta = integrationForm.provider === "meta"
      && integrationForm.channel === "whatsapp"
      && !integrationForm.phone_number_id
      && !integrationForm.business_account_id
      && !integrationForm.app_id;
    if (metaWhatsapp && formIsEmptyMeta) setIntegrationForm(integrationToForm(metaWhatsapp));
  }, [integrations.length]);

  useEffect(() => {
    const metaInstagram = integrations.find((item) => item.provider === "meta" && item.channel === "instagram");
    const formIsEmptyInstagram = !instagramForm.page_id
      && !instagramForm.instagram_business_account_id
      && !instagramForm.app_id;
    if (metaInstagram && formIsEmptyInstagram) setInstagramForm(instagramIntegrationToForm(metaInstagram));
  }, [integrations.length]);

  useEffect(() => {
    const metaFacebook = integrations.find((item) => item.provider === "meta" && item.channel === "facebook");
    const formIsEmptyFacebook = !facebookForm.page_id && !facebookForm.app_id;
    if (metaFacebook && formIsEmptyFacebook) setFacebookForm(facebookIntegrationToForm(metaFacebook));
  }, [integrations.length]);

  useEffect(() => {
    if (activeView !== "inbox") return undefined;
    const frame = window.requestAnimationFrame(() => {
      if (messagesPanelRef.current) messagesPanelRef.current.scrollTop = messagesPanelRef.current.scrollHeight;
      messagesEndRef.current?.scrollIntoView({ block: "end" });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [activeView, selectedConversation?.id, messages.length]);

  useEffect(() => {
    if (!featureLoaded || activeViewAllowed) return;
    const label = NAV_ITEMS.find((item) => item.key === activeView)?.label || "modulo";
    setActiveView("dashboard");
    showStatus(`${label} no esta activo para este plan o empresa.`, "neutral");
  }, [featureLoaded, activeViewAllowed, activeView]);

  useEffect(() => {
    if (!accessToken || !["inbox", "customers"].includes(activeView)) return;
    loadCrmConfig(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accessToken, activeView]);

  useEffect(() => {
    if (!selectedConversation?.id) {
      setCrmDraft({});
      setConversationMemory(null);
      setConversationTasks([]);
      setMessageStatusEvents([]);
      setConversationTimeline([]);
      setDedupeCandidates([]);
      setWebSearchRuns([]);
      setMultimodalMemoryEvents([]);
      return;
    }
    const selectedProfile = selectedConversation.profile_json && typeof selectedConversation.profile_json === "object" ? selectedConversation.profile_json : {};
    setCrmDraft({
      display_name: selectedConversation.display_name || "",
      first_name: selectedConversation.first_name || "",
      last_name: selectedConversation.last_name || "",
      city: selectedConversation.city || "",
      customer_type: selectedConversation.customer_type || "",
      interests: selectedConversation.interests || "",
      tags: selectedConversation.tags || "",
      notes: selectedConversation.notes || "",
      payment_status: selectedConversation.payment_status || "",
      crm_stage: selectedConversation.crm_stage || "",
      intent: selectedConversation.intent || "",
      takeover: Boolean(selectedConversation.takeover),
      assigned_user_id: selectedConversation.assigned_user_id || "",
      priority: selectedConversation.priority || "normal",
      sla_due_at: datetimeLocalValue(selectedConversation.sla_due_at),
      first_response_due_at: datetimeLocalValue(selectedConversation.first_response_due_at),
      lead_score: Number(selectedConversation.lead_score || 0),
      lead_temperature: selectedConversation.lead_temperature || "cold",
      custom_fields: { ...(selectedProfile.custom_fields || selectedConversation.custom_fields || {}) },
    });
  }, [selectedConversation?.id]);

  const submitLogin = async (event) => {
    event.preventDefault();
    try {
      const data = await apiCall("/saas/v1/auth/login", { method: "POST", body: JSON.stringify({ ...login, captcha_token: loginCaptchaToken, captcha_provider: CAPTCHA_PROVIDER }) });
      if (data?.mfa_required) {
        setMfaChallenge(data);
        setMfaCode(data?.dev_otp || "");
        setMode("mfa");
        showStatus(data?.email_sent ? "Codigo 2FA enviado a tu correo." : "Codigo 2FA requerido. Revisa tu correo configurado.", data?.email_sent || data?.dev_otp ? "ok" : "warn");
        return;
      }
      setTokens(data); setTenants(data?.tenants || []); setActiveView("dashboard"); showStatus("Ingreso correcto", "ok");
    } catch (err) { showStatus(String(err.message || err), "error"); }
    finally {
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
      const data = await apiCall("/saas/v1/auth/login/verify-otp", {
        method: "POST",
        body: JSON.stringify({ challenge_token: mfaChallenge.challenge_token, code: mfaCode }),
      });
      setTokens(data);
      setTenants(data?.tenants || []);
      setMfaChallenge(null);
      setMfaCode("");
      setMode("login");
      setActiveView("dashboard");
      showStatus("Ingreso protegido correcto", "ok");
    } catch (err) { showStatus(String(err.message || err), "error"); }
  };

  const submitRegister = async (event) => {
    event.preventDefault();
    if (register.password.length < 8) return showStatus("La clave debe tener al menos 8 caracteres.", "error");
    if (register.tenant_name.trim().length < 2) return showStatus("El nombre de la empresa debe tener al menos 2 caracteres.", "error");
    try {
      const data = await apiCall("/saas/v1/auth/register", { method: "POST", body: JSON.stringify({ ...register, captcha_token: registerCaptchaToken, captcha_provider: CAPTCHA_PROVIDER }) });
      setTokens(data); setTenants(data?.tenants || []); setRegister(defaultRegister()); setActiveView("dashboard"); showStatus("Empresa creada", "ok");
    } catch (err) { showStatus(String(err.message || err), "error"); }
    finally {
      if (CAPTCHA_ENABLED) {
        setRegisterCaptchaToken("");
        setRegisterCaptchaReset((value) => value + 1);
      }
    }
  };

  const submitPasswordRecovery = async (event) => {
    event.preventDefault();
    if (!passwordRecovery.email.trim()) return showStatus("Ingresa tu correo.", "error");
    try {
      const data = await apiCall("/saas/v1/auth/password/forgot", {
        method: "POST",
        body: JSON.stringify({ ...passwordRecovery, captcha_token: recoveryCaptchaToken, captcha_provider: CAPTCHA_PROVIDER }),
      });
      if (data?.dev_reset_token) {
        setPasswordReset((prev) => ({ ...prev, token: data.dev_reset_token }));
        setMode("reset");
        showStatus("Token local generado. Define tu nueva clave.", "ok");
      } else {
        showStatus("Si el correo existe, enviaremos instrucciones para recuperar la cuenta.", "ok");
      }
    } catch (err) { showStatus(String(err.message || err), "error"); }
    finally {
      if (CAPTCHA_ENABLED) {
        setRecoveryCaptchaToken("");
        setRecoveryCaptchaReset((value) => value + 1);
      }
    }
  };

  const submitPasswordReset = async (event) => {
    event.preventDefault();
    if (!passwordReset.token.trim()) return showStatus("Token requerido.", "error");
    if (passwordReset.new_password.length < 8) return showStatus("La clave debe tener al menos 8 caracteres.", "error");
    if (passwordReset.new_password !== passwordReset.confirm_password) return showStatus("Las claves no coinciden.", "error");
    try {
      await apiCall("/saas/v1/auth/password/reset", {
        method: "POST",
        body: JSON.stringify({ token: passwordReset.token, new_password: passwordReset.new_password, captcha_token: resetCaptchaToken, captcha_provider: CAPTCHA_PROVIDER }),
      });
      setPasswordReset(defaultPasswordReset());
      setMode("login");
      if (window.location.search.includes("reset_token=")) window.history.replaceState(null, "", window.location.pathname);
      showStatus("Clave actualizada. Ingresa con tu nueva clave.", "ok");
    } catch (err) { showStatus(String(err.message || err), "error"); }
    finally {
      if (CAPTCHA_ENABLED) {
        setResetCaptchaToken("");
        setResetCaptchaReset((value) => value + 1);
      }
    }
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
      showMilestoneOnce(`webhook:${data?.provider || webhookProvider}:${data?.endpoint_key || "nuevo"}`, {
        eyebrow: "Webhook listo",
        title: "Endpoint preparado para Meta",
        body: "Copia la Callback URL y el Verify token en Meta Developers. Luego usa Verificar para confirmar si ya entran eventos.",
        cta: "Ver debug",
        actionType: "settings-debug",
      });
    } catch (err) { showStatus(String(err.message || err), "error"); }
  };

  const saveIntegration = async (event) => {
    event.preventDefault();
    const accessTokenEnv = (integrationForm.access_token_env || "SCENTRA_META_ACCESS_TOKEN").trim();
    const isUpdatingExisting = Boolean(selectedIntegrationForForm);
    const accessToken = isUpdatingExisting ? "" : (metaAccessTokenRef.current?.value || "").trim();
    const appSecret = isUpdatingExisting ? "" : (metaAppSecretRef.current?.value || "").trim();
    const phoneNumberId = (integrationForm.phone_number_id || "").trim();
    const dispatchMode = (integrationForm.dispatch_mode || "stub").trim();
    if (dispatchMode !== "stub" && !phoneNumberId) return showStatus("Phone Number ID requerido para Meta Cloud real.", "error");
    try {
      const configJson = { dispatch_mode: dispatchMode, phone_number_id: phoneNumberId, business_account_id: (integrationForm.business_account_id || "").trim(), app_id: (integrationForm.app_id || "").trim(), graph_api_version: (integrationForm.graph_api_version || "v24.0").trim(), access_token_env: accessTokenEnv };
      if (accessToken) configJson.access_token = accessToken;
      if (appSecret) configJson.app_secret = appSecret;
      const savedIntegration = await apiCall("/saas/v1/integrations", { method: "POST", body: JSON.stringify({ provider: integrationForm.provider, channel: integrationForm.channel, status: integrationForm.status, secret_ref: accessToken ? "tenant:meta:whatsapp" : dispatchMode === "stub" ? "" : `env:${accessTokenEnv}`, config_json: configJson }) });
      if (metaAccessTokenRef.current) metaAccessTokenRef.current.value = "";
      if (metaAppSecretRef.current) metaAppSecretRef.current.value = "";
      showStatus("Integracion guardada", "ok"); await loadIntegrations(); await loadBilling();
      showMilestoneOnce(`integration:whatsapp:${savedIntegration?.id || phoneNumberId || "meta"}`, {
        eyebrow: "Canal conectado",
        title: dispatchMode === "stub" ? "WhatsApp quedó en modo prueba" : "WhatsApp Cloud quedó configurado",
        body: "El siguiente paso recomendado es verificar webhook, token y eventos entrantes desde Diagnostico antes de usar campanas reales.",
        cta: "Verificar canal",
        actionType: "settings-debug",
      });
    } catch (err) { showStatus(String(err.message || err), "error"); }
  };

  const editIntegration = (integration) => {
    setIntegrationForm(integrationToForm(integration));
    if (metaAccessTokenRef.current) metaAccessTokenRef.current.value = "";
    if (metaAppSecretRef.current) metaAppSecretRef.current.value = "";
    showStatus("Integracion cargada para editar. Guarda para actualizar datos generales.", "ok");
  };

  const editInstagramIntegration = (integration = selectedInstagramIntegration) => {
    if (!integration) return;
    setInstagramForm(instagramIntegrationToForm(integration));
    if (instagramPageTokenRef.current) instagramPageTokenRef.current.value = "";
    if (instagramAppSecretRef.current) instagramAppSecretRef.current.value = "";
    showStatus("Instagram cargado para editar. Los secretos siguen ocultos y cifrados.", "ok");
  };

  const editFacebookIntegration = (integration = selectedFacebookIntegration) => {
    if (!integration) return;
    setFacebookForm(facebookIntegrationToForm(integration));
    if (facebookPageTokenRef.current) facebookPageTokenRef.current.value = "";
    if (facebookAppSecretRef.current) facebookAppSecretRef.current.value = "";
    showStatus("Facebook cargado para editar. Los secretos siguen ocultos y cifrados.", "ok");
  };

  const saveInstagramManual = async (event) => {
    event.preventDefault();
    const isUpdatingExisting = Boolean(selectedInstagramIntegration);
    const pageAccessToken = isUpdatingExisting ? "" : (instagramPageTokenRef.current?.value || "").trim();
    const appSecret = isUpdatingExisting ? "" : (instagramAppSecretRef.current?.value || "").trim();
    const pageId = String(instagramForm.page_id || "").trim();
    const instagramId = String(instagramForm.instagram_business_account_id || "").trim();
    const dispatchMode = String(instagramForm.dispatch_mode || "instagram_graph").trim();
    if (dispatchMode !== "stub" && (!pageId || !instagramId)) return showStatus("Page ID e Instagram Business Account ID son requeridos para Instagram Graph real.", "error");
    if (dispatchMode !== "stub" && !isUpdatingExisting && !pageAccessToken) return showStatus("Page Access Token requerido para conectar Instagram por modo manual.", "error");
    try {
      const configJson = {
        dispatch_mode: dispatchMode,
        page_id: pageId,
        page_name: String(instagramForm.page_name || "").trim(),
        business_id: String(instagramForm.business_id || "").trim(),
        business_name: String(instagramForm.business_name || "").trim(),
        instagram_business_account_id: instagramId,
        instagram_username: String(instagramForm.instagram_username || "").trim(),
        app_id: String(instagramForm.app_id || "").trim(),
        graph_api_version: String(instagramForm.graph_api_version || "v24.0").trim(),
        webhook_callback_url: `${API_BASE}/saas/v1/webhooks/instagram/{endpoint_key}`,
        subscribed_fields: ["messages", "messaging_postbacks", "feed", "mention"],
      };
      if (pageAccessToken) configJson.page_access_token = pageAccessToken;
      if (appSecret) configJson.app_secret = appSecret;
      const savedIntegration = await apiCall("/saas/v1/integrations", {
        method: "POST",
        body: JSON.stringify({
          provider: "meta",
          channel: "instagram",
          status: instagramForm.status || "connected",
          secret_ref: pageAccessToken ? "tenant:meta:instagram" : (selectedInstagramIntegration?.secret_ref || "tenant:meta:instagram"),
          config_json: configJson,
        }),
      });
      if (instagramPageTokenRef.current) instagramPageTokenRef.current.value = "";
      if (instagramAppSecretRef.current) instagramAppSecretRef.current.value = "";
      showStatus("Instagram guardado. Si usas app propia, crea o copia el endpoint Instagram para Meta Developers.", "ok");
      await loadIntegrations();
      await loadBilling();
      await loadInstagramDiagnostics();
      showMilestoneOnce(`integration:instagram:${savedIntegration?.id || instagramId || "meta"}`, {
        eyebrow: "Instagram conectado",
        title: "Instagram Business quedó listo para validar",
        body: "Confirma permisos, subscribed_apps y último webhook desde Diagnóstico antes de automatizar DMs o comentarios.",
        cta: "Ver debug",
        actionType: "settings-debug",
      });
    } catch (err) { showStatus(String(err.message || err), "error"); }
  };

  const saveFacebookManual = async (event) => {
    event.preventDefault();
    const isUpdatingExisting = Boolean(selectedFacebookIntegration);
    const pageAccessToken = isUpdatingExisting ? "" : (facebookPageTokenRef.current?.value || "").trim();
    const appSecret = isUpdatingExisting ? "" : (facebookAppSecretRef.current?.value || "").trim();
    const pageId = String(facebookForm.page_id || "").trim();
    const dispatchMode = String(facebookForm.dispatch_mode || "facebook_graph").trim();
    if (dispatchMode !== "stub" && !pageId) return showStatus("Page ID requerido para Facebook Messenger real.", "error");
    if (dispatchMode !== "stub" && !isUpdatingExisting && !pageAccessToken) return showStatus("Page Access Token requerido para conectar Facebook Messenger.", "error");
    try {
      const configJson = {
        dispatch_mode: dispatchMode,
        page_id: pageId,
        page_name: String(facebookForm.page_name || "").trim(),
        business_id: String(facebookForm.business_id || "").trim(),
        business_name: String(facebookForm.business_name || "").trim(),
        app_id: String(facebookForm.app_id || "").trim(),
        graph_api_version: String(facebookForm.graph_api_version || "v24.0").trim(),
        webhook_callback_url: `${API_BASE}/saas/v1/webhooks/facebook/{endpoint_key}`,
        subscribed_fields: ["messages", "messaging_postbacks", "feed"],
      };
      if (pageAccessToken) configJson.page_access_token = pageAccessToken;
      if (appSecret) configJson.app_secret = appSecret;
      const savedIntegration = await apiCall("/saas/v1/integrations", {
        method: "POST",
        body: JSON.stringify({
          provider: "meta",
          channel: "facebook",
          status: facebookForm.status || "connected",
          secret_ref: pageAccessToken ? "tenant:meta:facebook" : (selectedFacebookIntegration?.secret_ref || "tenant:meta:facebook"),
          config_json: configJson,
        }),
      });
      if (facebookPageTokenRef.current) facebookPageTokenRef.current.value = "";
      if (facebookAppSecretRef.current) facebookAppSecretRef.current.value = "";
      showStatus("Facebook Messenger guardado. Crea el endpoint Facebook y suscribe messages/feed en Meta Developers.", "ok");
      await loadIntegrations();
      await loadBilling();
      await loadDiagnostics(true);
      await loadFacebookDiagnostics();
      showMilestoneOnce(`integration:facebook:${savedIntegration?.id || pageId || "meta"}`, {
        eyebrow: "Facebook conectado",
        title: "Facebook Messenger y comentarios quedan en revisión",
        body: "Revisa que pages_messaging, pages_manage_metadata y los webhooks de Page estén activos para recibir DMs y comentarios.",
        cta: "Ver debug",
        actionType: "settings-debug",
      });
    } catch (err) { showStatus(String(err.message || err), "error"); }
  };

  const createInstagramWebhookEndpoint = async () => {
    setWebhookProvider("instagram");
    try {
      const data = await apiCall("/saas/v1/webhooks/endpoints", { method: "POST", body: JSON.stringify({ provider: "instagram", signature_required: false }) });
      setLastWebhookSecret(data);
      showStatus("Endpoint Instagram creado. Copia Callback URL y Verify token en Meta Developers.", "ok");
      await loadWebhooks();
      showMilestoneOnce(`webhook:instagram:${data?.endpoint_key || "nuevo"}`, {
        eyebrow: "Webhook Instagram",
        title: "Endpoint de Instagram generado",
        body: "Usa esta URL en Meta Developers y vuelve a Diagnóstico para confirmar que lleguen DMs o comentarios.",
        cta: "Ver debug",
        actionType: "settings-debug",
      });
    } catch (err) { showStatus(String(err.message || err), "error"); }
  };

  const createFacebookWebhookEndpoint = async () => {
    setWebhookProvider("facebook");
    try {
      const data = await apiCall("/saas/v1/webhooks/endpoints", { method: "POST", body: JSON.stringify({ provider: "facebook", signature_required: false }) });
      setLastWebhookSecret(data);
      showStatus("Endpoint Facebook creado. Copia Callback URL y Verify token en Meta Developers.", "ok");
      await loadWebhooks();
      if (selectedFacebookIntegration) await loadFacebookDiagnostics();
      showMilestoneOnce(`webhook:facebook:${data?.endpoint_key || "nuevo"}`, {
        eyebrow: "Webhook Facebook",
        title: "Endpoint de Facebook generado",
        body: "Ahora suscribe messages, messaging_postbacks y feed en el Webhook de Page para recibir DMs y comentarios.",
        cta: "Ver debug",
        actionType: "settings-debug",
      });
    } catch (err) { showStatus(String(err.message || err), "error"); }
  };

  const openIntegrationSecretModal = (integration = selectedIntegrationForForm) => {
    if (!integration) return showStatus("Primero guarda la integracion general.", "error");
    const config = integration.config_json || {};
    const channel = String(integration.channel || "").toLowerCase();
    const isSocialMeta = ["instagram", "facebook"].includes(channel);
    setIntegrationSecretModal({
      provider: integration.provider,
      channel: integration.channel,
      status: integration.status,
      secret_ref: integration.secret_ref || "",
      dispatch_mode: config.dispatch_mode || "stub",
      phone_number_id: config.phone_number_id || "",
      business_account_id: config.business_account_id || config.waba_id || "",
      page_id: config.page_id || "",
      page_name: config.page_name || "",
      business_id: config.business_id || "",
      business_name: config.business_name || "",
      instagram_business_account_id: config.instagram_business_account_id || "",
      instagram_username: config.instagram_username || "",
      app_id: config.app_id || "",
      graph_api_version: config.graph_api_version || "v24.0",
      access_token_env: config.access_token_env || "SCENTRA_META_ACCESS_TOKEN",
      token_hint: isSocialMeta ? (config.page_access_token_hint || config.access_token_hint || "") : (config.access_token_hint || ""),
      app_secret_hint: config.app_secret_hint || "",
      has_access_token: isSocialMeta ? Boolean(config.has_page_access_token || config.has_access_token) : Boolean(config.has_access_token),
      has_app_secret: Boolean(config.has_app_secret),
      access_token: "",
      app_secret: "",
      current_password: "",
    });
  };

  const saveIntegrationSecrets = async (event) => {
    event.preventDefault();
    if (!integrationSecretModal) return;
    const accessToken = String(integrationSecretModal.access_token || "").trim();
    const appSecret = String(integrationSecretModal.app_secret || "").trim();
    const currentPassword = String(integrationSecretModal.current_password || "").trim();
    if (!accessToken && !appSecret) return showStatus("Pega al menos un token o app secret para actualizar.", "error");
    if (!currentPassword) return showStatus("Confirma tu contrasena para actualizar secretos.", "error");
    const secretChannel = String(integrationSecretModal.channel || "").toLowerCase();
    const isSocialMeta = ["instagram", "facebook"].includes(secretChannel);
    const configJson = isSocialMeta ? {
      dispatch_mode: integrationSecretModal.dispatch_mode || (secretChannel === "facebook" ? "facebook_graph" : "instagram_graph"),
      page_id: integrationSecretModal.page_id || "",
      page_name: integrationSecretModal.page_name || "",
      business_id: integrationSecretModal.business_id || "",
      business_name: integrationSecretModal.business_name || "",
      instagram_business_account_id: secretChannel === "instagram" ? (integrationSecretModal.instagram_business_account_id || "") : "",
      instagram_username: secretChannel === "instagram" ? (integrationSecretModal.instagram_username || "") : "",
      app_id: integrationSecretModal.app_id || "",
      graph_api_version: integrationSecretModal.graph_api_version || "v24.0",
      webhook_callback_url: `${API_BASE}/saas/v1/webhooks/${secretChannel}/{endpoint_key}`,
      subscribed_fields: secretChannel === "facebook" ? ["messages", "messaging_postbacks", "feed"] : ["messages", "messaging_postbacks", "feed", "mention"],
    } : {
      dispatch_mode: integrationSecretModal.dispatch_mode || "stub",
      phone_number_id: integrationSecretModal.phone_number_id || "",
      business_account_id: integrationSecretModal.business_account_id || "",
      app_id: integrationSecretModal.app_id || "",
      graph_api_version: integrationSecretModal.graph_api_version || "v24.0",
      access_token_env: integrationSecretModal.access_token_env || "SCENTRA_META_ACCESS_TOKEN",
    };
    if (accessToken) {
      if (isSocialMeta) configJson.page_access_token = accessToken;
      else configJson.access_token = accessToken;
    }
    if (appSecret) configJson.app_secret = appSecret;
    try {
      await apiCall("/saas/v1/integrations", {
        method: "POST",
        body: JSON.stringify({
          provider: integrationSecretModal.provider,
          channel: integrationSecretModal.channel,
          status: integrationSecretModal.status || "connected",
          secret_ref: accessToken ? (isSocialMeta ? `tenant:meta:${secretChannel}` : "tenant:meta:whatsapp") : integrationSecretModal.secret_ref,
          config_json: configJson,
          current_password: currentPassword,
        }),
      });
      setIntegrationSecretModal(null);
      showStatus("Secretos actualizados y cifrados", "ok");
      await loadIntegrations();
      if (secretChannel === "facebook") await loadFacebookDiagnostics();
      if (secretChannel === "instagram") await loadInstagramDiagnostics();
      showMilestoneOnce(`integration-secret:${secretChannel}:${new Date().toISOString().slice(0, 19)}`, {
        eyebrow: "Secreto actualizado",
        title: "Credenciales cifradas correctamente",
        body: "Scentra no vuelve a mostrar el token completo. Si el canal falla, usa Diagnóstico para revisar permisos y webhooks.",
        cta: "Ver debug",
        actionType: "settings-debug",
      });
    } catch (err) { showStatus(String(err.message || err), "error"); }
  };

  const deleteIntegration = async (integration) => {
    if (!integration?.id) return;
    const channel = String(integration.channel || "canal").toUpperCase();
    const ok = window.confirm(`Eliminar la integracion ${channel}? Scentra dejara de usar este canal y desactivara su endpoint webhook local.`);
    if (!ok) return;
    try {
      await apiCall(`/saas/v1/integrations/${encodeURIComponent(integration.id)}`, { method: "DELETE" });
      const cleanChannel = String(integration.channel || "").toLowerCase();
      if (cleanChannel === "whatsapp") {
        setIntegrationForm({ provider: "meta", channel: "whatsapp", status: "connected", dispatch_mode: "stub", phone_number_id: "", business_account_id: "", app_id: "", graph_api_version: "v24.0", access_token_env: "SCENTRA_META_ACCESS_TOKEN" });
        setWhatsappPhones([]);
      }
      if (cleanChannel === "instagram") {
        setInstagramForm(defaultInstagramForm());
        setInstagramDiagnostics(null);
      }
      if (cleanChannel === "facebook") {
        setFacebookForm(defaultFacebookForm());
        setFacebookDiagnostics(null);
      }
      setLastWebhookSecret(null);
      showStatus(`Integracion ${channel} eliminada`, "ok");
      await Promise.all([loadIntegrations(), loadBilling(), loadWebhooks(), loadInbox(), loadDiagnostics(true)]);
    } catch (err) {
      showStatus(String(err.message || err), "error");
    }
  };

  const syncWhatsappPhones = async () => {
    setPhoneSyncing(true);
    try {
      const data = await apiCall("/saas/v1/integrations/meta/whatsapp/phone-numbers");
      const phones = Array.isArray(data?.phone_numbers) ? data.phone_numbers : [];
      setWhatsappPhones(phones);
      showStatus(`Telefonos sincronizados: ${phones.length}`, "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setPhoneSyncing(false);
    }
  };

  const registerWhatsappPhone = async (event) => {
    event.preventDefault();
    const phoneNumberId = phoneRegisterForm.phone_number_id.trim();
    const pin = phoneRegisterForm.pin.trim();
    if (!phoneNumberId) return showStatus("Selecciona o escribe un Phone Number ID.", "error");
    if (!/^\d{6}$/.test(pin)) return showStatus("El PIN debe tener exactamente 6 digitos.", "error");
    setPhoneSyncing(true);
    try {
      await apiCall("/saas/v1/integrations/meta/whatsapp/register-phone", {
        method: "POST",
        body: JSON.stringify({ phone_number_id: phoneNumberId, pin }),
      });
      setIntegrationForm((prev) => ({ ...prev, phone_number_id: phoneNumberId, dispatch_mode: "meta_cloud" }));
      setPhoneRegisterForm({ phone_number_id: "", pin: "" });
      showStatus("Numero registrado/verificado en Meta", "ok");
      await loadIntegrations();
      await syncWhatsappPhones();
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setPhoneSyncing(false);
    }
  };

  const startInstagramOAuth = async () => {
    const tenantAppId = String(instagramForm.app_id || facebookForm.app_id || selectedInstagramConfig.app_id || selectedFacebookConfig.app_id || "").trim();
    const tenantAppSecret = String(instagramAppSecretRef.current?.value || facebookAppSecretRef.current?.value || "").trim();
    const graphApiVersion = String(instagramForm.graph_api_version || facebookForm.graph_api_version || selectedInstagramConfig.graph_api_version || selectedFacebookConfig.graph_api_version || "v24.0").trim();
    if (!tenantAppId && !selectedInstagramConfig.has_app_secret && !selectedFacebookConfig.has_app_secret) {
      return showStatus("Para OAuth por cliente, escribe Meta App ID y Meta App Secret o guarda primero la integracion.", "error");
    }
    setInstagramBusy(true);
    try {
      const data = await apiCall("/saas/v1/integrations/instagram/oauth/start", {
        method: "POST",
        body: JSON.stringify({
          app_id: tenantAppId,
          app_secret: tenantAppSecret,
          graph_api_version: graphApiVersion,
          preferred_channel: instagramForm.app_id || instagramForm.instagram_business_account_id ? "instagram" : "facebook",
        }),
      });
      setInstagramOAuth((prev) => ({ ...prev, state: data.state || "", assets: [], status: "oauth_started", callbackUrl: data.callback_url || "" }));
      if (data.auth_url) window.open(data.auth_url, "_blank", "noopener,noreferrer");
      showStatus(t("meta.facebook.opened"), "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setInstagramBusy(false);
    }
  };

  const loadInstagramAssets = async () => {
    if (!instagramOAuth.state) return showStatus(t("meta.facebook.start_first"), "error");
    setInstagramBusy(true);
    try {
      const data = await apiCall(`/saas/v1/integrations/instagram/oauth/assets?state=${encodeURIComponent(instagramOAuth.state)}`);
      setInstagramOAuth((prev) => ({ ...prev, assets: data.assets || [], status: data.status || "" }));
      showStatus(`Cuentas detectadas: ${(data.assets || []).filter((item) => item.connected).length}`, "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setInstagramBusy(false);
    }
  };

  const connectInstagramAsset = async (asset) => {
    if (!instagramOAuth.state) return showStatus(t("meta.facebook.missing_state"), "error");
    setInstagramBusy(true);
    try {
      const data = await apiCall("/saas/v1/integrations/instagram/connect", {
        method: "POST",
        body: JSON.stringify({
          state: instagramOAuth.state,
          page_id: asset.page_id,
          instagram_business_account_id: asset.instagram_business_account_id,
        }),
      });
      showStatus(data?.subscription?.final_subscribed ? "Instagram conectado y suscrito a webhooks." : "Instagram conectado, revisa diagnostics para confirmar webhooks.", data?.subscription?.final_subscribed ? "ok" : "neutral");
      if (data?.webhook?.verify_token_once) setLastWebhookSecret({ provider: "instagram", url_path: data.webhook.url_path, verify_token_once: data.webhook.verify_token_once });
      setInstagramForm((prev) => ({
        ...prev,
        page_id: asset.page_id || prev.page_id,
        page_name: asset.page_name || prev.page_name,
        business_id: asset.business_id || prev.business_id,
        business_name: asset.business_name || prev.business_name,
        instagram_business_account_id: asset.instagram_business_account_id || prev.instagram_business_account_id,
        instagram_username: asset.instagram_username || prev.instagram_username,
        dispatch_mode: "instagram_graph",
      }));
      await loadIntegrations();
      await loadInstagramDiagnostics();
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setInstagramBusy(false);
    }
  };

  const connectFacebookAsset = async (asset) => {
    if (!instagramOAuth.state) return showStatus(t("meta.facebook.missing_state"), "error");
    setFacebookBusy(true);
    try {
      const data = await apiCall("/saas/v1/integrations/instagram/connect-facebook", {
        method: "POST",
        body: JSON.stringify({
          state: instagramOAuth.state,
          page_id: asset.page_id,
        }),
      });
      showStatus(data?.subscription?.final_subscribed ? "Facebook conectado y suscrito a webhooks." : "Facebook conectado, revisa diagnostics para confirmar webhooks.", data?.subscription?.final_subscribed ? "ok" : "neutral");
      if (data?.webhook?.verify_token_once) setLastWebhookSecret({ provider: "facebook", url_path: data.webhook.url_path, verify_token_once: data.webhook.verify_token_once });
      setFacebookForm((prev) => ({
        ...prev,
        page_id: asset.page_id || prev.page_id,
        page_name: asset.page_name || prev.page_name,
        business_id: asset.business_id || prev.business_id,
        business_name: asset.business_name || prev.business_name,
        dispatch_mode: "facebook_graph",
      }));
      await loadIntegrations();
      await loadFacebookDiagnostics();
      await loadMetaTokenHealth("facebook");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setFacebookBusy(false);
    }
  };

  const loadInstagramDiagnostics = async () => {
    setInstagramBusy(true);
    try {
      const data = await apiCall("/saas/v1/integrations/instagram/diagnostics");
      setInstagramDiagnostics(data);
      showStatus(data?.ok ? "Instagram Diagnostics actualizado." : "Instagram aun no esta conectado.", data?.ok ? "ok" : "neutral");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setInstagramBusy(false);
    }
  };

  const loadFacebookDiagnostics = async () => {
    setFacebookBusy(true);
    try {
      const data = await apiCall("/saas/v1/integrations/meta/facebook/diagnostics");
      setFacebookDiagnostics(data);
      if (data?.token_health) setMetaTokenHealth((prev) => ({ ...prev, facebook: data.token_health }));
      showStatus(data?.ok ? "Facebook Diagnostics actualizado." : "Facebook aun no esta conectado.", data?.ok ? "ok" : "neutral");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setFacebookBusy(false);
    }
  };

  const loadMetaTokenHealth = async (channel) => {
    const cleanChannel = String(channel || "").toLowerCase();
    const setBusy = cleanChannel === "facebook" ? setFacebookBusy : setInstagramBusy;
    setBusy(true);
    try {
      const data = await apiCall(`/saas/v1/integrations/meta/${encodeURIComponent(cleanChannel)}/token-health`);
      setMetaTokenHealth((prev) => ({ ...prev, [cleanChannel]: data }));
      showStatus(data?.ok ? `Token ${cleanChannel} valido.` : `Token ${cleanChannel}: ${data?.recommendation || data?.status || "revisar"}`, data?.ok ? "ok" : "neutral");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setBusy(false);
    }
  };

  const refreshMetaToken = async (channel) => {
    const cleanChannel = String(channel || "").toLowerCase();
    const setBusy = cleanChannel === "facebook" ? setFacebookBusy : setInstagramBusy;
    setBusy(true);
    try {
      const data = await apiCall(`/saas/v1/integrations/meta/${encodeURIComponent(cleanChannel)}/token-refresh`, { method: "POST" });
      setMetaTokenHealth((prev) => ({ ...prev, [cleanChannel]: data?.health || data }));
      showStatus(data?.ok ? `Token ${cleanChannel} renovado y validado.` : (data?.message || `No se pudo renovar ${cleanChannel}.`), data?.ok ? "ok" : "neutral");
      await loadIntegrations();
      if (cleanChannel === "instagram") await loadInstagramDiagnostics();
      if (cleanChannel === "facebook") await loadFacebookDiagnostics();
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setBusy(false);
    }
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
  const updateWebhookEndpoint = async (endpoint, patch) => {
    try {
      await apiCall(`/saas/v1/webhooks/endpoints/${encodeURIComponent(endpoint.id)}`, { method: "PATCH", body: JSON.stringify(patch) });
      showStatus("Endpoint actualizado", "ok");
      await loadWebhooks();
      setWebhookCheck(null);
    } catch (err) { showStatus(String(err.message || err), "error"); }
  };
  const verifyWebhookEndpoint = async (endpoint) => {
    if (!endpoint?.id) return;
    try {
      const data = await apiCall(`/saas/v1/webhooks/endpoints/${encodeURIComponent(endpoint.id)}/verify`);
      setWebhookCheck(data);
      showStatus(data?.ok ? "Endpoint verificado" : "Endpoint requiere ajustes", data?.ok ? "ok" : "neutral");
    } catch (err) {
      setWebhookCheck({ ok: false, error: String(err.message || err), endpoint });
      showStatus(String(err.message || err), "error");
    }
  };
  const deleteWebhookEndpoint = async (endpoint) => {
    if (!endpoint?.id) return;
    const ok = window.confirm(`Eliminar endpoint ${String(endpoint.provider || "").toUpperCase()}? Meta dejara de poder llamar esta URL hasta que crees/copias un endpoint nuevo.`);
    if (!ok) return;
    try {
      await apiCall(`/saas/v1/webhooks/endpoints/${encodeURIComponent(endpoint.id)}`, { method: "DELETE" });
      setLastWebhookSecret(null);
      setWebhookCheck(null);
      showStatus("Endpoint eliminado/desactivado", "ok");
      await Promise.all([loadWebhooks(), loadDiagnostics(true)]);
    } catch (err) { showStatus(String(err.message || err), "error"); }
  };
  const rotateWebhookToken = async (endpoint) => { try { const data = await apiCall(`/saas/v1/webhooks/endpoints/${encodeURIComponent(endpoint.id)}/rotate-token`, { method: "POST" }); setLastWebhookSecret(data); setWebhookCheck(null); showStatus("Verify token rotado", "ok"); await loadWebhooks(); } catch (err) { showStatus(String(err.message || err), "error"); } };
  const rotateWebhookSignature = async (endpoint) => { try { const data = await apiCall(`/saas/v1/webhooks/endpoints/${encodeURIComponent(endpoint.id)}/rotate-signature`, { method: "POST" }); setLastWebhookSecret(data); setWebhookCheck(null); showStatus("Firma HMAC rotada", "ok"); await loadWebhooks(); } catch (err) { showStatus(String(err.message || err), "error"); } };
  const processWebhookEvents = async () => { try { const data = await apiCall("/saas/v1/webhooks/events/process", { method: "POST" }); showStatus(`Procesados: ${data?.result?.processed || 0}`, "ok"); await loadWebhooks(); } catch (err) { showStatus(String(err.message || err), "error"); } };
  const patchConversationLocal = (conversationId, patch) => {
    setConversations((prev) => prev.map((item) => item.id === conversationId ? { ...item, ...patch } : item));
    setSelectedConversation((prev) => (prev?.id === conversationId ? { ...prev, ...patch } : prev));
  };
  const markConversationRead = async (conversationId, { silent = false } = {}) => {
    if (!conversationId) return;
    patchConversationLocal(conversationId, { unread_count: 0 });
    try {
      await apiCall(`/saas/v1/conversations/${encodeURIComponent(conversationId)}/read`, { method: "POST" });
      if (!silent) showStatus("Conversacion marcada como leida", "ok");
    } catch (err) {
      if (!silent) showStatus(String(err.message || err), "error");
    }
  };
  const markSelectedConversationRead = () => markConversationRead(selectedConversation?.id);
  const toggleSelectedTakeover = async () => {
    if (!selectedConversation?.id) return;
    const nextTakeover = !Boolean(selectedConversation.takeover);
    patchConversationLocal(selectedConversation.id, { takeover: nextTakeover });
    setCrmDraft((prev) => ({ ...prev, takeover: nextTakeover }));
    try {
      await apiCall(`/saas/v1/conversations/${encodeURIComponent(selectedConversation.id)}/takeover?takeover=${nextTakeover ? "true" : "false"}`, { method: "POST" });
      showStatus(nextTakeover ? "Takeover humano activado. La IA queda en pausa para este chat." : "Takeover desactivado. La IA puede atender este chat.", "ok");
    } catch (err) {
      const rollback = !nextTakeover;
      patchConversationLocal(selectedConversation.id, { takeover: rollback });
      setCrmDraft((prev) => ({ ...prev, takeover: rollback }));
      showStatus(String(err.message || err), "error");
    }
  };
  const playIncomingSound = () => {
    try {
      const AudioContextCtor = window.AudioContext || window.webkitAudioContext;
      if (!AudioContextCtor) return;
      const audio = new AudioContextCtor();
      const gain = audio.createGain();
      const first = audio.createOscillator();
      const second = audio.createOscillator();
      gain.gain.setValueAtTime(0.0001, audio.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.06, audio.currentTime + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, audio.currentTime + 0.34);
      first.frequency.setValueAtTime(740, audio.currentTime);
      second.frequency.setValueAtTime(990, audio.currentTime + 0.11);
      first.connect(gain); second.connect(gain); gain.connect(audio.destination);
      first.start(audio.currentTime); first.stop(audio.currentTime + 0.16);
      second.start(audio.currentTime + 0.12); second.stop(audio.currentTime + 0.34);
      window.setTimeout(() => audio.close().catch(() => {}), 500);
    } catch {
      // Browsers may block audio until the first user interaction.
    }
  };
  const toggleBrowserNotifications = async () => {
    if (typeof window === "undefined" || !("Notification" in window)) {
      setNotificationPermission("unsupported");
      showStatus("Este navegador no soporta notificaciones.", "neutral");
      return;
    }
    if (browserNotificationsEnabled) {
      localStorage.setItem(BROWSER_NOTIFICATIONS_KEY, "false");
      setBrowserNotificationsEnabled(false);
      showStatus("Notificaciones del navegador desactivadas", "ok");
      return;
    }
    if (window.Notification.permission === "denied") {
      setNotificationPermission("denied");
      showStatus("El navegador tiene bloqueadas las notificaciones para este sitio.", "neutral");
      return;
    }
    const permission = window.Notification.permission === "granted"
      ? "granted"
      : await window.Notification.requestPermission();
    setNotificationPermission(permission);
    const enabled = permission === "granted";
    localStorage.setItem(BROWSER_NOTIFICATIONS_KEY, enabled ? "true" : "false");
    setBrowserNotificationsEnabled(enabled);
    showStatus(enabled ? "Notificaciones del navegador activadas" : "No se activaron las notificaciones", enabled ? "ok" : "neutral");
  };
  const appendEmoji = (emoji, target = "message") => {
    if (target === "comment") {
      setCommentReplyText((prev) => `${prev}${emoji}`);
    } else {
      setReplyText((prev) => `${prev}${emoji}`);
    }
    setRecentEmojis((prev) => {
      const next = [emoji, ...prev.filter((item) => item !== emoji)].slice(0, 24);
      localStorage.setItem(RECENT_EMOJIS_KEY, JSON.stringify(next));
      return next;
    });
  };
  const loadCatalogProducts = async (search = catalogSearch) => {
    setCatalogLoading(true);
    setCatalogError("");
    try {
      const params = new URLSearchParams({ limit: "24" });
      if (String(search || "").trim()) params.set("search", String(search).trim());
      const data = await apiCall(`/saas/v1/commerce/products?${params.toString()}`);
      setCatalogProducts(data?.products || []);
      setCatalogOpen(true);
      showStatus((data?.products || []).length ? "Catalogo WooCommerce cargado." : "WooCommerce respondió, pero no devolvió productos para esa búsqueda.", "ok");
    } catch (err) {
      const message = String(err.message || err);
      setCatalogError(message);
      setCatalogOpen(true);
      showStatus(message, "error");
    } finally {
      setCatalogLoading(false);
    }
  };
  const openCatalogPicker = () => {
    if (!commerceCredentialsReady) {
      showStatus("Conecta WC_BASE_URL, WC_CONSUMER_KEY y WC_CONSUMER_SECRET en Ajustes > APIs para usar el catalogo.", "neutral");
      setActiveView("settings");
      setSettingsTab("apis");
      return;
    }
    loadCatalogProducts("");
  };
  const insertCatalogProduct = (product) => {
    const normalized = normalizeProductCard(product);
    clearComposerAttachment();
    setCatalogDraft(normalized);
    setCatalogOpen(false);
    showStatus("Producto adjunto como ficha. Puedes agregar una nota y enviarlo.", "ok");
  };
  const openAttachmentPicker = (kind) => {
    setAttachMenuOpen(false);
    if (kind === "catalog") {
      openCatalogPicker();
      return;
    }
    const acceptMap = {
      image: "image/*",
      video: "video/*",
      audio: "audio/*",
      document: ".pdf,.doc,.docx,.xls,.xlsx,.txt,application/pdf,text/plain",
    };
    if (composerFileRef.current) {
      composerFileRef.current.dataset.kind = kind;
      composerFileRef.current.accept = acceptMap[kind] || "image/*,video/*,audio/*,.pdf,.doc,.docx,.xls,.xlsx,.txt";
      composerFileRef.current.click();
    }
  };
  const updateCrmDraft = (key, value) => setCrmDraft((prev) => ({ ...prev, [key]: value }));
  const updateCrmCustomField = (key, value) => setCrmDraft((prev) => ({
    ...prev,
    custom_fields: { ...(prev.custom_fields || {}), [key]: value },
  }));
  const saveSelectedCrm = async () => {
    if (!selectedConversation?.id || savingCrm) return;
    setSavingCrm(true);
    try {
      const data = await apiCall(`/saas/v1/customers/${encodeURIComponent(selectedConversation.id)}`, {
        method: "PATCH",
        body: JSON.stringify(crmDraft),
      });
      const customer = data?.customer || {};
      setSelectedConversation((prev) => ({ ...(prev || {}), ...customer }));
      setConversations((prev) => prev.map((item) => item.id === selectedConversation.id ? { ...item, ...customer } : item));
      setCrmDraft((prev) => ({ ...prev, ...customer, custom_fields: customer.custom_fields || prev.custom_fields || {}, sla_due_at: datetimeLocalValue(customer.sla_due_at), first_response_due_at: datetimeLocalValue(customer.first_response_due_at) }));
      showStatus("Ficha CRM guardada", "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setSavingCrm(false);
    }
  };
  const assignSelectedConversation = async (userId = "") => {
    if (!selectedConversation?.id) return;
    try {
      const data = await apiCall(`/saas/v1/customers/${encodeURIComponent(selectedConversation.id)}`, {
        method: "PATCH",
        body: JSON.stringify({ assigned_user_id: userId }),
      });
      const customer = data?.customer || {};
      setSelectedConversation((prev) => ({ ...(prev || {}), ...customer }));
      setConversations((prev) => prev.map((item) => item.id === selectedConversation.id ? { ...item, ...customer } : item));
      setCrmDraft((prev) => ({ ...prev, ...customer, assigned_user_id: customer.assigned_user_id || "" }));
      showStatus(userId ? "Conversacion asignada a ti" : "Conversacion sin asignacion", "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    }
  };
  const assignSelectedAiAgent = async (agentId = "") => {
    if (!selectedConversation?.id) return;
    try {
      const query = agentId ? `?agent_id=${encodeURIComponent(agentId)}` : "";
      const data = await apiCall(`/saas/v1/conversations/${encodeURIComponent(selectedConversation.id)}/ai-agent${query}`, {
        method: "PATCH",
      });
      const customer = data?.customer || {};
      setSelectedConversation((prev) => ({ ...(prev || {}), ...customer }));
      setConversations((prev) => prev.map((item) => item.id === selectedConversation.id ? { ...item, ...customer } : item));
      setCrmDraft((prev) => ({ ...prev, ...customer, assigned_ai_agent_id: customer.assigned_ai_agent_id || "" }));
      showStatus(agentId ? "Agente IA asignado. La IA general queda desconectada de este chat." : "Conversacion devuelta a IA general.", "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    }
  };
  const recomputeSelectedScore = async () => {
    if (!selectedConversation?.id) return;
    try {
      const data = await apiCall(`/saas/v1/conversations/${encodeURIComponent(selectedConversation.id)}/score`, { method: "POST" });
      const customer = data?.customer || {};
      setSelectedConversation((prev) => ({ ...(prev || {}), ...customer }));
      setConversations((prev) => prev.map((item) => item.id === selectedConversation.id ? { ...item, ...customer } : item));
      setCrmDraft((prev) => ({ ...prev, lead_score: Number(customer.lead_score || 0), lead_temperature: customer.lead_temperature || prev.lead_temperature }));
      showStatus("Score comercial recalculado", "ok");
    } catch (err) { showStatus(String(err.message || err), "error"); }
  };
  const runSelectedPredictiveInsight = async (predictionType) => {
    if (!selectedConversation?.id || predictiveBusy) return;
    setPredictiveBusy(predictionType);
    try {
      const data = await apiCall("/saas/v1/intelligence/predict", {
        method: "POST",
        body: JSON.stringify({
          prediction_type: predictionType,
          subject_type: "conversation",
          subject_id: selectedConversation.id,
          window_key: "latest",
          persist_recommendations: true,
        }),
      });
      const customerData = await apiCall(`/saas/v1/customers/${encodeURIComponent(selectedConversation.id)}`);
      const customer = customerData?.customer || {};
      if (customer.id) {
        setSelectedConversation((prev) => ({ ...(prev || {}), ...customer }));
        setConversations((prev) => prev.map((item) => item.id === selectedConversation.id ? { ...item, ...customer } : item));
        setCrmDraft((prev) => ({ ...prev, ...customer, custom_fields: customer.custom_fields || prev.custom_fields || {} }));
      }
      showStatus(`${predictionTypeLabel(predictionType)} generado: ${data?.prediction?.label || "ready"}`, "ok");
      await loadAdvisorSignals(true);
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setPredictiveBusy("");
    }
  };
  const createConversationTask = async (event) => {
    event.preventDefault();
    if (!selectedConversation?.id || !taskDraft.title.trim()) return;
    try {
      const data = await apiCall(`/saas/v1/conversations/${encodeURIComponent(selectedConversation.id)}/tasks`, {
        method: "POST",
        body: JSON.stringify(taskDraft),
      });
      if (data?.task) setConversationTasks((prev) => [data.task, ...prev]);
      setTaskDraft({ title: "", due_at: "", priority: "normal" });
      showStatus("Tarea creada para seguimiento", "ok");
    } catch (err) { showStatus(String(err.message || err), "error"); }
  };
  const patchConversationTask = async (taskId, patch) => {
    if (!taskId) return;
    try {
      const data = await apiCall(`/saas/v1/crm/tasks/${encodeURIComponent(taskId)}`, { method: "PATCH", body: JSON.stringify(patch) });
      const task = data?.task || {};
      setConversationTasks((prev) => prev.map((item) => item.id === taskId ? { ...item, ...task } : item));
      showStatus(patch.status === "done" ? "Tarea completada" : "Tarea actualizada", "ok");
    } catch (err) { showStatus(String(err.message || err), "error"); }
  };
  const mergeDedupeCandidate = async (sourceConversationId) => {
    if (!selectedConversation?.id || !sourceConversationId || mergingCustomerId) return;
    setMergingCustomerId(sourceConversationId);
    try {
      const data = await apiCall(`/saas/v1/customers/${encodeURIComponent(selectedConversation.id)}/merge`, {
        method: "POST",
        body: JSON.stringify({ source_conversation_id: sourceConversationId, reason: "Merge desde Inbox CRM" }),
      });
      const customer = data?.customer || {};
      setSelectedConversation((prev) => ({ ...(prev || {}), ...customer }));
      setConversations((prev) => prev
        .filter((item) => item.id !== sourceConversationId)
        .map((item) => item.id === selectedConversation.id ? { ...item, ...customer } : item));
      setCrmDraft((prev) => ({ ...prev, ...customer, custom_fields: customer.custom_fields || prev.custom_fields || {}, sla_due_at: datetimeLocalValue(customer.sla_due_at), first_response_due_at: datetimeLocalValue(customer.first_response_due_at) }));
      await loadMessages({ ...selectedConversation, ...customer }, { preserveComposer: true });
      showStatus("Clientes duplicados fusionados", "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setMergingCustomerId("");
    }
  };
  const localMediaUrl = (mediaId) => mediaId && accessToken ? `${API_BASE}/saas/v1/media/${encodeURIComponent(mediaId)}?token=${encodeURIComponent(accessToken)}` : "";
  const whatsappMediaUrl = (mediaId) => mediaId && accessToken ? `${API_BASE}/saas/v1/media/whatsapp/${encodeURIComponent(mediaId)}?token=${encodeURIComponent(accessToken)}` : "";
  const messageMediaUrl = (message) => {
    const id = String(message?.media_id || "").trim();
    if (!id) return "";
    return message.direction === "in" ? whatsappMediaUrl(id) : localMediaUrl(id);
  };
  const messageLabel = (message) => {
    const type = String(message?.msg_type || "text").toLowerCase();
    if (type === "image") return "imagen";
    if (type === "video") return "video";
    if (type === "audio") return "nota de voz";
    if (type === "document" || type === "file") return "documento";
    if (type === "product") return "producto";
    return type;
  };
  const messageSenderLabel = (message) => {
    if (String(message?.direction || "").toLowerCase() === "out") return "Tu";
    const fullName = [selectedConversation?.first_name, selectedConversation?.last_name].filter(Boolean).join(" ").trim();
    return fullName || selectedConversation?.display_name || "Cliente";
  };
  const analyzeVoiceMessage = async (message, force = false) => {
    const messageId = String(message?.id || "");
    if (!messageId || voiceAnalysisBusy) return;
    setVoiceAnalysisBusy(messageId);
    try {
      const query = new URLSearchParams();
      if (force) query.set("force", "true");
      if (aiConfig.voiceAnalysisProvider) query.set("provider_code", aiConfig.voiceAnalysisProvider);
      const suffix = query.toString() ? `?${query.toString()}` : "";
      const data = await apiCall(`/saas/v1/media/messages/${encodeURIComponent(messageId)}/voice/analyze${suffix}`, { method: "POST" });
      const voice = data?.analysis?.voice_intelligence || data?.analysis || {};
      setMessages((prev) => prev.map((item) => {
        if (item.id !== messageId) return item;
        const payload = asObject(item.payload_json);
        return { ...item, payload_json: { ...payload, voice_intelligence: voice } };
      }));
      showStatus(data?.cached ? "Analisis de voz cargado" : "Audio analizado con Voice Intelligence", "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setVoiceAnalysisBusy("");
    }
  };
  const analyzeVisionMessage = async (message, force = false) => {
    const messageId = String(message?.id || "");
    if (!messageId || visionAnalysisBusy) return;
    setVisionAnalysisBusy(messageId);
    try {
      const query = new URLSearchParams();
      if (force) query.set("force", "true");
      if (aiConfig.visionAnalysisProvider) query.set("provider_code", aiConfig.visionAnalysisProvider);
      const suffix = query.toString() ? `?${query.toString()}` : "";
      const data = await apiCall(`/saas/v1/media/messages/${encodeURIComponent(messageId)}/vision/analyze${suffix}`, { method: "POST" });
      const vision = data?.analysis?.vision_intelligence || data?.analysis || {};
      setMessages((prev) => prev.map((item) => {
        if (item.id !== messageId) return item;
        const payload = asObject(item.payload_json);
        return { ...item, payload_json: { ...payload, vision_intelligence: vision } };
      }));
      showStatus(data?.cached ? "Analisis visual cargado" : "Media analizada con Vision Intelligence", "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setVisionAnalysisBusy("");
    }
  };
  const loadWebSearchRunsForConversation = async (conversationId = selectedConversation?.id) => {
    if (!conversationId) return;
    try {
      const data = await apiCall(`/saas/v1/media/search/runs?conversation_id=${encodeURIComponent(conversationId)}&limit=8`);
      setWebSearchRuns(data?.runs || []);
    } catch (err) {
      showStatus(String(err.message || err), "error");
    }
  };
  const loadConversationMultimodalEvents = async (conversationId = selectedConversation?.id) => {
    if (!conversationId) return;
    try {
      const data = await apiCall(`/saas/v1/agents/multimodal-memory/events?conversation_id=${encodeURIComponent(conversationId)}&limit=24`);
      setMultimodalMemoryEvents(data?.events || []);
    } catch {
      setMultimodalMemoryEvents([]);
    }
  };
  const syncConversationMultimodalMemory = async () => {
    if (!selectedConversation?.id) return showStatus("Selecciona una conversacion para sincronizar memoria multimodal.", "error");
    setWebSearchBusy("memory-sync");
    try {
      const data = await apiCall("/saas/v1/agents/multimodal-memory/sync", {
        method: "POST",
        body: JSON.stringify({
          conversation_id: selectedConversation.id,
          include_voice: true,
          include_vision: true,
          include_search: true,
          include_agent_runs: true,
          limit: 40,
        }),
      });
      setMultimodalMemoryEvents(data?.events || []);
      showStatus(`Memoria multimodal sincronizada: ${number(data?.synced || 0)} eventos.`, "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setWebSearchBusy("");
    }
  };
  const submitWebImageSearch = async (event) => {
    event.preventDefault();
    const query = webSearchForm.query.trim();
    if (!query) return showStatus("Escribe una busqueda para consultar fuentes externas.", "error");
    if (!selectedConversation?.id) return showStatus("Selecciona una conversacion para asociar la busqueda.", "error");
    setWebSearchBusy("search");
    try {
      const data = await apiCall("/saas/v1/media/search", {
        method: "POST",
        body: JSON.stringify({
          query,
          search_type: webSearchForm.searchType || "mixed",
          provider_code: webSearchForm.providerCode || aiConfig.webImageSearchProvider || "tavily",
          conversation_id: selectedConversation.id,
          limit: 6,
        }),
      });
      const run = data?.run;
      if (run?.id) setWebSearchRuns((prev) => [run, ...prev.filter((item) => item.id !== run.id)].slice(0, 8));
      setWebSearchForm((prev) => ({ ...prev, query: "" }));
      showStatus("Busqueda externa registrada. Revisa y aprueba fuentes antes de usarlas.", "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setWebSearchBusy("");
    }
  };
  const reviewWebSearchResult = async (result, approvalStatus) => {
    const resultId = String(result?.id || "");
    if (!resultId) return;
    setWebSearchBusy(`${approvalStatus}-${resultId}`);
    try {
      await apiCall(`/saas/v1/media/search/results/${encodeURIComponent(resultId)}/approval`, {
        method: "POST",
        body: JSON.stringify({
          approval_status: approvalStatus,
          reason: approvalStatus === "rejected" ? "Rechazado desde Inbox por revision humana" : "",
        }),
      });
      await loadWebSearchRunsForConversation(selectedConversation?.id);
      showStatus(approvalStatus === "approved" ? "Fuente aprobada para referencia humana" : "Fuente rechazada", approvalStatus === "approved" ? "ok" : "neutral");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setWebSearchBusy("");
    }
  };
  const showOutboundDispatchStatus = (data, sentLabel = "Mensaje enviado por WhatsApp", queuedLabel = "Mensaje encolado para envio") => {
    const dispatch = data?.dispatch || {};
    const outboundError = dispatch.last_error || data?.outbound_status?.error || "";
    if (Number(dispatch.failed || 0) > 0 || Number(dispatch.blocked || 0) > 0) {
      showStatus(outboundError ? `Meta no envio el mensaje: ${outboundError}` : "Mensaje guardado, pero Meta no lo envio. Revisa integracion, plan o logs de outbound.", "error");
    } else if (Number(dispatch.sent || 0) > 0 && whatsappDispatchMode === "stub") {
      showStatus("Mensaje procesado en modo prueba. Cambia Canales a Meta Cloud para enviarlo al telefono.", "neutral");
    } else if (Number(dispatch.sent || 0) > 0) {
      showStatus(sentLabel, "ok");
    } else {
      showStatus(queuedLabel, "ok");
    }
  };
  const useWebSearchReference = async (result, action = "draft") => {
    const resultId = String(result?.id || "");
    if (!resultId || !selectedConversation?.id) return;
    if (result.safety_status === "blocked") return showStatus("Esta fuente esta bloqueada por seguridad.", "error");
    const busyKey = `${action}-reference-${resultId}`;
    setWebSearchBusy(busyKey);
    try {
      if (result.approval_status !== "approved") {
        await apiCall(`/saas/v1/media/search/results/${encodeURIComponent(resultId)}/approval`, {
          method: "POST",
          body: JSON.stringify({ approval_status: "approved", reason: "" }),
        });
      }
      const data = await apiCall(`/saas/v1/media/search/results/${encodeURIComponent(resultId)}/reference`, {
        method: "POST",
        body: JSON.stringify({ conversation_id: selectedConversation.id, include_source_url: true, include_image_url: true }),
      });
      const reference = data?.reference || {};
      const text = String(reference.message_text || "").trim();
      if (!text) return showStatus("No se pudo preparar la referencia aprobada.", "error");
      if (action === "send") {
        const ok = window.confirm("Enviar esta referencia aprobada al cliente?");
        if (!ok) return;
        setComposerSending(true);
        const sent = await apiCall(`/saas/v1/conversations/${encodeURIComponent(selectedConversation.id)}/messages`, {
          method: "POST",
          body: JSON.stringify({
            text,
            msg_type: "text",
            payload_json: {
              source: "inbox_multimodal_reference",
              search_result_id: resultId,
              reference_title: reference.title || result.title || "",
              reference_url: reference.source_url || result.url || "",
              visual_url: reference.visual_url || result.image_url || result.thumbnail_url || "",
            },
          }),
        });
        showOutboundDispatchStatus(sent, "Referencia aprobada enviada", "Referencia aprobada encolada para envio");
        await loadMessages(selectedConversation, { preserveComposer: true });
        await loadInbox();
      } else {
        setReplyText((prev) => (prev.trim() ? `${prev.trim()}\n\n${text}` : text));
        showStatus(result.approval_status === "approved" ? "Referencia agregada al composer" : "Fuente aprobada y agregada al composer", "ok");
      }
      await loadWebSearchRunsForConversation(selectedConversation.id);
      await loadConversationMultimodalEvents(selectedConversation.id);
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setComposerSending(false);
      setWebSearchBusy("");
    }
  };
  const renderMessageContent = (message) => {
    const type = String(message?.msg_type || "text").toLowerCase();
    const url = messageMediaUrl(message);
    const label = messageLabel(message);
    const product = productCardFromMessage(message);
    const payload = asObject(message?.payload_json);
    const note = cleanProductText(payload.message_note, 900);
    const voice = asObject(payload.voice_intelligence);
    const vision = asObject(payload.vision_intelligence);
    const hasVoiceAnalysis = Boolean(voice.transcript || voice.summary || voice.intent || voice.sentiment);
    const hasVisionAnalysis = Boolean(vision.summary || vision.visual_description || vision.extracted_text || vision.intent || vision.document_type);
    const canAnalyzeVision = ["image", "document", "file"].includes(type);
    return (
      <>
        {product ? <ProductMessageCard product={product} /> : null}
        {product && note ? <p className="product-message-note">{note}</p> : null}
        {type === "image" && url ? <img className="chat-media image" src={url} alt={message.text || "Imagen recibida"} loading="lazy" /> : null}
        {type === "video" && url ? <video className="chat-media video" src={url} controls playsInline /> : null}
        {type === "audio" && url ? (
          <div className="audio-message">
            <AudioWaveform src={url} seed={message.id || message.created_at || message.media_id} />
            <audio src={url} controls preload="metadata" />
          </div>
        ) : null}
        {type === "audio" ? (
          <div className={`voice-intel-card ${hasVoiceAnalysis ? "ready" : ""}`}>
            <div className="voice-intel-head">
              <strong>Voice Intelligence</strong>
              <button type="button" onClick={() => analyzeVoiceMessage(message, hasVoiceAnalysis)} disabled={voiceAnalysisBusy === message.id}>
                {voiceAnalysisBusy === message.id ? "Analizando..." : hasVoiceAnalysis ? "Reanalizar" : "Analizar voz"}
              </button>
            </div>
            {hasVoiceAnalysis ? (
              <>
                <p>{voice.summary || voice.transcript}</p>
                <div className="voice-intel-tags">
                  <span>{voice.sentiment || "neutral"} {Math.round(Number(voice.sentiment_score || 0) * 100) / 100}</span>
                  <span>{voice.intent_label || voice.intent || "other"}</span>
                  <span>Urgencia {voice.urgency || "low"}</span>
                  <span>{Math.round(Number(voice.confidence || 0) * 100)}% conf.</span>
                </div>
                {voice.transcript ? <details><summary>Transcripcion</summary><p>{voice.transcript}</p></details> : null}
                {voice.recommended_action ? <small>{voice.recommended_action}</small> : null}
              </>
            ) : (
              <small>Transcribe, resume y detecta sentimiento e intencion del audio.</small>
            )}
          </div>
        ) : null}
        {canAnalyzeVision ? (
          <div className={`vision-intel-card ${hasVisionAnalysis ? "ready" : ""}`}>
            <div className="voice-intel-head">
              <strong>Vision Intelligence</strong>
              <button type="button" onClick={() => analyzeVisionMessage(message, hasVisionAnalysis)} disabled={visionAnalysisBusy === message.id}>
                {visionAnalysisBusy === message.id ? "Analizando..." : hasVisionAnalysis ? "Reanalizar" : "Analizar media"}
              </button>
            </div>
            {hasVisionAnalysis ? (
              <>
                <p>{vision.summary || vision.visual_description || vision.extracted_text}</p>
                <div className="voice-intel-tags">
                  <span>{vision.document_type || vision.media_kind || "media"}</span>
                  <span>{vision.intent_label || vision.intent || "other"}</span>
                  <span>Urgencia {vision.urgency || "low"}</span>
                  <span>{Math.round(Number(vision.confidence || 0) * 100)}% conf.</span>
                </div>
                {vision.visual_description ? <details><summary>Descripcion visual</summary><p>{vision.visual_description}</p></details> : null}
                {vision.extracted_text ? <details><summary>Texto extraido</summary><p>{vision.extracted_text}</p></details> : null}
                {Array.isArray(vision.topics) && vision.topics.length ? <small>Temas: {vision.topics.slice(0, 6).join(", ")}</small> : null}
                {vision.recommended_action ? <small>{vision.recommended_action}</small> : null}
              </>
            ) : (
              <small>Describe imagenes, extrae texto de documentos y detecta intencion sin modificar CRM ni enviar mensajes.</small>
            )}
          </div>
        ) : null}
        {(type === "document" || type === "file") && url ? <a className="document-chip" href={url} target="_blank" rel="noreferrer">Abrir {label}</a> : null}
        {!product && message.text && !/^\[(image|video|audio|document|file|product)\]$/i.test(message.text) ? <p>{message.text}</p> : !product && !url ? <p>[{label}]</p> : null}
      </>
    );
  };
  const stopRecordingMeters = () => {
    if (recordingTimerRef.current) window.clearInterval(recordingTimerRef.current);
    if (recordingAnimationRef.current) window.cancelAnimationFrame(recordingAnimationRef.current);
    recordingTimerRef.current = null;
    recordingAnimationRef.current = null;
    if (audioContextRef.current) {
      audioContextRef.current.close().catch(() => {});
      audioContextRef.current = null;
    }
  };
  const stopRecordingStream = () => {
    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach((track) => track.stop());
      mediaStreamRef.current = null;
    }
  };
  const startVoiceRecording = async () => {
    try {
      if (!window.MediaRecorder || !navigator.mediaDevices?.getUserMedia) throw new Error("Este navegador no soporta grabacion de voz.");
      if (mediaRecorderRef.current && mediaRecorderRef.current.state !== "inactive") mediaRecorderRef.current.stop();
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mime = ["audio/ogg;codecs=opus", "audio/ogg", "audio/webm;codecs=opus", "audio/webm"].find((item) => window.MediaRecorder.isTypeSupported(item));
      const recorder = mime ? new window.MediaRecorder(stream, { mimeType: mime, audioBitsPerSecond: 32000 }) : new window.MediaRecorder(stream, { audioBitsPerSecond: 32000 });
      mediaStreamRef.current = stream;
      mediaRecorderRef.current = recorder;
      recordingChunksRef.current = [];
      recordingCancelledRef.current = false;
      recordingLevelsRef.current = EMPTY_WAVEFORM;
      setRecordingLevels(EMPTY_WAVEFORM);
      setRecordingSeconds(0);
      setIsRecording(true);
      recorder.ondataavailable = (event) => { if (event.data?.size) recordingChunksRef.current.push(event.data); };
      recorder.onstop = () => {
        const blobType = recorder.mimeType || mime || "audio/webm";
        const blob = new Blob(recordingChunksRef.current, { type: blobType });
        recordingChunksRef.current = [];
        stopRecordingMeters();
        stopRecordingStream();
        setIsRecording(false);
        if (!recordingCancelledRef.current && blob.size) {
          const extension = blobType.includes("ogg") ? "ogg" : "webm";
          setComposerAttachment(new File([blob], `nota-voz-${Date.now()}.${extension}`, { type: blobType }), "audio", recordingLevelsRef.current);
          showStatus("Nota de voz lista para enviar", "ok");
        }
        recordingCancelledRef.current = false;
      };
      recorder.start();
      recordingTimerRef.current = window.setInterval(() => setRecordingSeconds((prev) => prev + 1), 1000);
      const AudioContextCtor = window.AudioContext || window.webkitAudioContext;
      if (AudioContextCtor) {
        const audioContext = new AudioContextCtor();
        audioContextRef.current = audioContext;
        const source = audioContext.createMediaStreamSource(stream);
        const analyser = audioContext.createAnalyser();
        analyser.fftSize = 256;
        source.connect(analyser);
        const data = new Uint8Array(analyser.frequencyBinCount);
        const tick = () => {
          analyser.getByteTimeDomainData(data);
          let total = 0;
          data.forEach((value) => { const centered = value - 128; total += centered * centered; });
          const rms = Math.sqrt(total / data.length) / 128;
          const height = Math.max(7, Math.min(44, Math.round(rms * 110)));
          recordingLevelsRef.current = [...recordingLevelsRef.current.slice(1), height];
          setRecordingLevels(recordingLevelsRef.current);
          recordingAnimationRef.current = window.requestAnimationFrame(tick);
        };
        tick();
      }
    } catch (err) {
      stopRecordingMeters();
      stopRecordingStream();
      setIsRecording(false);
      showStatus(String(err.message || err), "error");
    }
  };
  const stopVoiceRecording = () => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== "inactive") mediaRecorderRef.current.stop();
  };
  const cancelVoiceRecording = () => {
    recordingCancelledRef.current = true;
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== "inactive") mediaRecorderRef.current.stop();
    else {
      stopRecordingMeters();
      stopRecordingStream();
      setIsRecording(false);
    }
  };
  const sendSelectedMessage = async (event) => {
    event.preventDefault();
    if (!selectedConversation?.id || composerSending) return;
    if (!replyText.trim() && !attachmentFile && !catalogDraft) return;
    setComposerSending(true);
    try {
      let mediaId = "";
      let msgType = "text";
      let mimeType = "";
      let filename = "";
      let outgoingText = replyText.trim();
      let payloadJson = {};
      if (attachmentFile) {
        msgType = attachmentKind || mediaKindFromMime(attachmentFile.type);
        mimeType = attachmentFile.type || "";
        filename = attachmentFile.name || "";
        const formData = new FormData();
        formData.append("kind", msgType);
        formData.append("file", attachmentFile);
        const upload = await apiCall("/saas/v1/media/upload", { method: "POST", body: formData });
        mediaId = upload?.media_id || upload?.media?.id || "";
      } else if (catalogDraft) {
        msgType = "product";
        outgoingText = buildProductOutboundText(catalogDraft, replyText.trim());
        payloadJson = {
          product_card: catalogDraft,
          message_note: replyText.trim(),
          cta_url: catalogDraft.permalink || "",
          cta_text: "Ver producto",
        };
      }
      const data = await apiCall(`/saas/v1/conversations/${encodeURIComponent(selectedConversation.id)}/messages`, {
        method: "POST",
        body: JSON.stringify({ text: outgoingText, msg_type: msgType, media_id: mediaId, mime_type: mimeType, filename, payload_json: payloadJson }),
      });
      showOutboundDispatchStatus(data);
      setReplyText("");
      clearComposerAttachment();
      setCatalogDraft(null);
      setEmojiOpen(false);
      await loadMessages(selectedConversation);
      await loadInbox();
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setComposerSending(false);
    }
  };
  const generateCommentAiReply = async (comment = selectedComment) => {
    if (!comment?.id) return;
    setCommentBusy(`ai-${comment.id}`);
    try {
      const data = await apiCall(`/saas/v1/social/comments/${encodeURIComponent(comment.id)}/generate-ai`, { method: "POST" });
      const suggestion = data?.suggestion || "";
      setCommentReplyText(suggestion);
      setSelectedComment((prev) => prev?.id === comment.id ? { ...prev, ai_suggestion: suggestion, ai_status: "suggested" } : prev);
      setSocialComments((prev) => prev.map((item) => item.id === comment.id ? { ...item, ai_suggestion: suggestion, ai_status: "suggested" } : item));
      showStatus("Respuesta sugerida por IA", "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setCommentBusy("");
    }
  };
  const sendCommentReply = async (event) => {
    event?.preventDefault?.();
    if (!selectedComment?.id || !commentReplyText.trim()) return;
    setCommentBusy(`reply-${selectedComment.id}`);
    try {
      await apiCall(`/saas/v1/social/comments/${encodeURIComponent(selectedComment.id)}/reply`, {
        method: "POST",
        body: JSON.stringify({ message: commentReplyText.trim() }),
      });
      showStatus("Comentario respondido", "ok");
      setCommentReplyText("");
      await loadSocialComments({ keepSelection: true });
      setSelectedComment((prev) => prev ? { ...prev, status: "replied", last_reply_text: commentReplyText.trim() } : prev);
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setCommentBusy("");
    }
  };
  const reactToComment = async (emoji = "👍") => {
    if (!selectedComment?.id) return;
    setCommentBusy(`react-${selectedComment.id}`);
    try {
      await apiCall(`/saas/v1/social/comments/${encodeURIComponent(selectedComment.id)}/react`, {
        method: "POST",
        body: JSON.stringify({ emoji }),
      });
      setSelectedComment((prev) => prev ? { ...prev, last_reaction_emoji: emoji, reacted_at: new Date().toISOString() } : prev);
      setSocialComments((prev) => prev.map((item) => item.id === selectedComment.id ? { ...item, last_reaction_emoji: emoji, reacted_at: new Date().toISOString() } : item));
      setCommentReactionOpen(false);
      showStatus(`Reaccionaste ${emoji} al comentario`, "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setCommentBusy("");
    }
  };
  const saveCommentAiSettings = async () => {
    setCommentBusy("settings");
    try {
      const data = await apiCall("/saas/v1/social/comments/settings", {
        method: "PATCH",
        body: JSON.stringify(commentAiSettings || {}),
      });
      setCommentAiSettings(data?.settings || null);
      showStatus("Entrenamiento de comentarios guardado", "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setCommentBusy("");
    }
  };
  const changePlanDev = async (planCode) => { try { const data = await apiCall("/saas/v1/billing/dev/change-plan", { method: "POST", body: JSON.stringify({ plan_code: planCode }) }); setBillingOverview(data); showStatus(`Plan actualizado a ${planCode}`, "ok"); await loadSession(); } catch (err) { showStatus(String(err.message || err), "error"); } };
  const startPlanCheckout = async (planCode) => {
    setBillingCheckoutBusy(planCode);
    try {
      const data = await apiCall("/saas/v1/billing/checkout", {
        method: "POST",
        body: JSON.stringify({ plan_code: planCode, provider: billingCheckoutProvider }),
      });
      const checkout = data?.checkout || {};
      setBillingCheckoutSessions((prev) => [checkout, ...prev.filter((item) => item.id !== checkout.id)].slice(0, 8));
      if (checkout.checkout_url) {
        window.open(checkout.checkout_url, "_blank", "noopener,noreferrer");
        showStatus(`Checkout ${checkout.provider || billingCheckoutProvider} abierto`, "ok");
      } else {
        showStatus(checkout.error || "Checkout creado sin URL. Revisa proveedor de pago.", "neutral");
      }
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setBillingCheckoutBusy("");
    }
  };
  const downloadBillingInvoice = async (invoice) => {
    try {
      const invoiceId = invoice?.id || "";
      if (!invoiceId) return;
      const name = invoice.invoice_number || invoice.provider_invoice_id || invoiceId;
      await downloadApiFile(`/saas/v1/billing/invoices/${encodeURIComponent(invoiceId)}/pdf`, `${name}.pdf`);
      showStatus("Factura PDF generada", "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    }
  };
  const saveAiLocal = async () => {
    try {
      const data = await apiCall("/saas/v1/ai/settings", {
        method: "PUT",
        body: JSON.stringify({
          enabled: Boolean(aiConfig.enabled),
          provider_code: aiConfig.provider,
          fallback_provider_code: aiConfig.fallbackProvider,
          system_prompt: aiConfig.systemPrompt,
          max_tokens: Number(aiConfig.maxTokens || 700),
          temperature: Number(aiConfig.temperature || 0.5),
          metadata_json: {
            voice_enabled: Boolean(aiConfig.voiceEnabled),
            prefer_voice: Boolean(aiConfig.preferVoice),
            tts_provider: aiConfig.ttsProvider,
            voice_analysis_provider: aiConfig.voiceAnalysisProvider,
            vision_analysis_provider: aiConfig.visionAnalysisProvider,
            web_image_search_provider: aiConfig.webImageSearchProvider,
            voice_id: aiConfig.voiceId,
            voice_name: aiConfig.voiceName,
            voice_prompt: aiConfig.voicePrompt,
            human_reply_style_enabled: Boolean(aiConfig.humanReplyStyle),
            human_reply_splitting_enabled: Boolean(aiConfig.humanReplySplitting),
            reply_max_output_tokens: Number(aiConfig.replyMaxOutputTokens || aiConfig.maxTokens || 700),
            typing_indicator_enabled: Boolean(aiConfig.typingIndicator),
            inbound_cooldown_seconds: Number(aiConfig.cooldown || 6),
            reply_initial_delay_ms: Number(aiConfig.typingDelay || 3200),
            reply_chunk_delay_ms: Number(aiConfig.delayBetween || 4200),
            reply_chunk_chars: Number(aiConfig.chunks || 220),
            recent_message_limit: Number(aiConfig.recentMessageLimit || 16),
            message_context_chars: Number(aiConfig.messageContextChars || 1200),
          },
        }),
      });
      setAiConfig((prev) => ({
        ...prev,
        enabled: Boolean(data?.enabled),
        provider: data?.provider_code || prev.provider,
        fallbackProvider: data?.fallback_provider_code || prev.fallbackProvider,
        systemPrompt: data?.system_prompt || prev.systemPrompt,
        maxTokens: String(data?.max_tokens || prev.maxTokens),
        temperature: String(data?.temperature ?? prev.temperature),
        humanReplyStyle: asObject(data?.metadata_json).human_reply_style_enabled !== false,
        humanReplySplitting: asObject(data?.metadata_json).human_reply_splitting_enabled !== false,
        replyMaxOutputTokens: String(asObject(data?.metadata_json).reply_max_output_tokens ?? data?.max_tokens ?? prev.replyMaxOutputTokens),
        chunks: String(asObject(data?.metadata_json).reply_chunk_chars ?? prev.chunks),
        delayBetween: String(asObject(data?.metadata_json).reply_chunk_delay_ms ?? prev.delayBetween),
        typingDelay: String(asObject(data?.metadata_json).reply_initial_delay_ms ?? prev.typingDelay),
        cooldown: String(asObject(data?.metadata_json).inbound_cooldown_seconds ?? prev.cooldown),
        recentMessageLimit: String(asObject(data?.metadata_json).recent_message_limit ?? prev.recentMessageLimit),
        messageContextChars: String(asObject(data?.metadata_json).message_context_chars ?? prev.messageContextChars),
        typingIndicator: asObject(data?.metadata_json).typing_indicator_enabled !== false,
        voiceEnabled: asObject(data?.metadata_json).voice_enabled ?? prev.voiceEnabled,
        preferVoice: asObject(data?.metadata_json).prefer_voice ?? prev.preferVoice,
        ttsProvider: asObject(data?.metadata_json).tts_provider || prev.ttsProvider,
        voiceAnalysisProvider: asObject(data?.metadata_json).voice_analysis_provider || prev.voiceAnalysisProvider,
        visionAnalysisProvider: asObject(data?.metadata_json).vision_analysis_provider || prev.visionAnalysisProvider,
        webImageSearchProvider: asObject(data?.metadata_json).web_image_search_provider || prev.webImageSearchProvider,
        voiceId: asObject(data?.metadata_json).voice_id || prev.voiceId,
        voiceName: asObject(data?.metadata_json).voice_name || prev.voiceName,
        voicePrompt: asObject(data?.metadata_json).voice_prompt || prev.voicePrompt,
      }));
      showStatus("Ajustes IA guardados. El agente usara el modelo seleccionado en APIs.", "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    }
  };
  const uploadKnowledgeFile = async (file) => {
    if (!file || knowledgeUploading) return;
    setKnowledgeUploading(true);
    try {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("title", file.name || "Archivo KB");
      await apiCall("/saas/v1/knowledge/upload", { method: "POST", body: formData });
      showStatus("Archivo agregado a Knowledge Base. La IA lo usara como contexto.", "ok");
      await loadKnowledgeSources();
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setKnowledgeUploading(false);
      if (knowledgeFileRef.current) knowledgeFileRef.current.value = "";
    }
  };
  const addKnowledgeUrl = async (event) => {
    event.preventDefault();
    if (!knowledgeUrlForm.url.trim()) return showStatus("Ingresa una URL primero.", "neutral");
    setKnowledgeUploading(true);
    try {
      await apiCall("/saas/v1/knowledge/url", { method: "POST", body: JSON.stringify(knowledgeUrlForm) });
      setKnowledgeUrlForm({ url: "", title: "", notes: "" });
      showStatus("Fuente web agregada a Knowledge Base.", "ok");
      await loadKnowledgeSources();
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setKnowledgeUploading(false);
    }
  };
  const deleteKnowledgeSource = async (sourceId) => {
    try {
      await apiCall(`/saas/v1/knowledge/sources/${encodeURIComponent(sourceId)}`, { method: "DELETE" });
      showStatus("Fuente eliminada.", "ok");
      await loadKnowledgeSources();
    } catch (err) {
      showStatus(String(err.message || err), "error");
    }
  };
  const reindexKnowledgeSource = async (sourceId) => {
    try {
      const data = await apiCall(`/saas/v1/knowledge/sources/${encodeURIComponent(sourceId)}/reindex`, { method: "POST" });
      showStatus(`Fuente reindexada: ${number(data?.chunk_count || 0)} fragmentos.`, "ok");
      await loadKnowledgeSources();
    } catch (err) {
      showStatus(String(err.message || err), "error");
    }
  };
  const reindexAllKnowledge = async () => {
    if (knowledgeUploading) return;
    setKnowledgeUploading(true);
    try {
      const data = await apiCall("/saas/v1/knowledge/reindex?limit=100", { method: "POST" });
      showStatus(`Knowledge Base reindexada: ${number(data?.indexed_sources || 0)} fuentes / ${number(data?.chunks || 0)} fragmentos.`, "ok");
      await loadKnowledgeSources();
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setKnowledgeUploading(false);
    }
  };
  const searchKnowledgeSources = async (event) => {
    event.preventDefault();
    const query = knowledgeSearch.query.trim();
    if (!query) return showStatus("Escribe una pregunta para probar el RAG.", "neutral");
    setKnowledgeSearching(true);
    try {
      const data = await apiCall("/saas/v1/knowledge/search", {
        method: "POST",
        body: JSON.stringify({ query, limit: 6, min_score: 1 }),
      });
      setKnowledgeSearch({
        query,
        results: data?.results || [],
        citations: data?.citations || [],
        confidence: data?.confidence || 0,
        retrievalMode: data?.retrieval_mode || "",
        searched: true,
      });
      showStatus(`RAG encontro ${number((data?.results || []).length)} fragmentos relevantes.`, "ok");
      await loadKnowledgeSources();
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setKnowledgeSearching(false);
    }
  };
  const runKnowledgeEvaluation = async (event) => {
    event.preventDefault();
    const query = (knowledgeEvalForm.query || knowledgeSearch.query).trim();
    if (!query) return showStatus("Escribe una pregunta para evaluar el RAG.", "neutral");
    const expectedSources = knowledgeEvalForm.expectedSources
      .split(/[\n,]+/)
      .map((item) => item.trim())
      .filter(Boolean)
      .slice(0, 12);
    setKnowledgeEvaluating(true);
    try {
      const data = await apiCall("/saas/v1/knowledge/evaluate", {
        method: "POST",
        body: JSON.stringify({
          query,
          expected_answer: knowledgeEvalForm.expectedAnswer,
          expected_sources: expectedSources,
          limit: 6,
          min_quality_score: 55,
        }),
      });
      const evaluation = data?.evaluation || {};
      setKnowledgeSearch({
        query,
        results: data?.search?.results || [],
        citations: data?.search?.citations || [],
        confidence: evaluation.confidence || 0,
        retrievalMode: data?.search?.retrieval_mode || "",
        searched: true,
      });
      setKnowledgeEvalForm((prev) => ({ ...prev, query }));
      showStatus(`Evaluacion RAG: ${number(evaluation.quality_score || 0)}% / ${evaluation.passed ? "aprobada" : "requiere ajuste"}.`, evaluation.passed ? "ok" : "neutral");
      await loadKnowledgeSources();
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setKnowledgeEvaluating(false);
    }
  };
  const runDiagnostics = async () => {
    setDiagnosticsRunning(true);
    try {
      const data = await apiCall("/saas/v1/diagnostics/run?limit=50", { method: "POST" });
      showStatus(`Procesado: webhooks ${data?.webhooks?.processed || 0}, IA ${data?.ai?.processed || 0}, outbound ${data?.outbound?.processed || 0}.`, "ok");
      await loadDiagnostics(true);
      await loadInbox();
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setDiagnosticsRunning(false);
    }
  };
  const simulateInboundWebhook = async (event) => {
    event.preventDefault();
    setDiagnosticsRunning(true);
    try {
      const data = await apiCall("/saas/v1/diagnostics/whatsapp/simulate-inbound", {
        method: "POST",
        body: JSON.stringify(debugInboundForm),
      });
      setDebugInboundResult(data);
      showStatus(data?.ok ? "Simulacion entrante OK: Scentra creo mensaje en Inbox." : "Simulacion ejecutada, pero no creo mensaje.", data?.ok ? "ok" : "error");
      await loadDiagnostics(true);
      await loadInbox();
    } catch (err) {
      setDebugInboundResult({ ok: false, error: String(err.message || err) });
      showStatus(String(err.message || err), "error");
    } finally {
      setDiagnosticsRunning(false);
    }
  };
  const checkWhatsappSubscription = async () => {
    setDiagnosticsRunning(true);
    try {
      const metaIntegration = (diagnostics?.integrations || integrations || []).find((item) => item.provider === "meta" && item.channel === "whatsapp") || {};
      const wabaId = metaIntegration.business_account_id || integrationForm.business_account_id || "";
      const query = wabaId ? `?wabaId=${encodeURIComponent(wabaId)}` : "";
      const data = await apiCall(`/saas/v1/internal/whatsapp/check-subscription${query}`);
      setSubscriptionCheck(data);
      showStatus(data?.is_subscribed ? "WABA suscrito a la app de Meta." : "WABA revisado: falta suscripcion o Meta no la confirmo.", data?.is_subscribed ? "ok" : "error");
      await loadDiagnostics(true);
      await loadIntegrations();
    } catch (err) {
      setSubscriptionCheck({ ok: false, error: String(err.message || err) });
      showStatus(String(err.message || err), "error");
    } finally {
      setDiagnosticsRunning(false);
    }
  };
  const saveProfileLocal = () => showStatus("Perfil preparado. Falta conectar persistencia de usuario y foto.", "ok");
  const savePasswordChange = async () => {
    if (!securityForm.currentPassword) return showStatus("Ingresa tu clave actual.", "error");
    if (securityForm.newPassword.length < 8) return showStatus("La nueva clave debe tener al menos 8 caracteres.", "error");
    if (securityForm.newPassword !== securityForm.confirmPassword) return showStatus("Las claves no coinciden.", "error");
    try {
      await apiCall("/saas/v1/auth/password/change", {
        method: "POST",
        body: JSON.stringify({ current_password: securityForm.currentPassword, new_password: securityForm.newPassword }),
      });
      setSecurityForm((prev) => ({ ...prev, currentPassword: "", newPassword: "", confirmPassword: "" }));
      await loadSecurityStatus();
      showStatus("Clave actualizada.", "ok");
    } catch (err) { showStatus(String(err.message || err), "error"); }
  };
  const saveTwoFactorPreference = async () => {
    try {
      const data = await apiCall("/saas/v1/auth/security/2fa", {
        method: "PATCH",
        body: JSON.stringify({ enabled: securityForm.twoFactorEnabled, method: securityForm.twoFactorMethod || "email_otp" }),
      });
      setSecurityForm((prev) => ({
        ...prev,
        twoFactorEnabled: Boolean(data?.two_factor_enabled),
        twoFactorMethod: data?.two_factor_method && data.two_factor_method !== "none" ? data.two_factor_method : "email_otp",
        passwordChangedAt: data?.password_changed_at || prev.passwordChangedAt,
      }));
      showStatus("Preferencia 2FA guardada.", "ok");
    } catch (err) { showStatus(String(err.message || err), "error"); }
  };
  const downloadComplianceJson = (payload, filename) => {
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 60000);
  };
  const exportMyAccountData = async () => {
    try {
      const data = await apiCall("/saas/v1/compliance/me/export");
      downloadComplianceJson(data, "scentra-account-export.json");
      showStatus("Export de cuenta generado.", "ok");
    } catch (err) { showStatus(String(err.message || err), "error"); }
  };
  const exportSelectedCustomerData = async () => {
    if (!selectedConversation?.id) return showStatus("Selecciona una conversacion en Inbox para exportar datos del cliente.", "error");
    try {
      const data = await apiCall(`/saas/v1/compliance/customers/${encodeURIComponent(selectedConversation.id)}/export`);
      downloadComplianceJson(data, `scentra-customer-${selectedConversation.id}.json`);
      showStatus("Export de cliente generado.", "ok");
    } catch (err) { showStatus(String(err.message || err), "error"); }
  };
  const requestSelectedCustomerDelete = async () => {
    if (!selectedConversation?.id) return showStatus("Selecciona una conversacion en Inbox para solicitar borrado.", "error");
    try {
      await apiCall(`/saas/v1/compliance/customers/${encodeURIComponent(selectedConversation.id)}/delete-request?reason=${encodeURIComponent("Solicitud creada desde configuracion de seguridad")}`, { method: "POST" });
      showStatus("Solicitud de borrado creada para revision.", "ok");
    } catch (err) { showStatus(String(err.message || err), "error"); }
  };
  const openCredentialModal = (provider, credentialKey = provider.env) => {
    setCredentialModal({
      ...provider,
      credential_key: credentialKey,
      value: "",
      selected_model: credentialByKey[credentialKey]?.selected_model || "",
    });
  };
  const saveCredentialModal = async (event) => {
    event.preventDefault();
    if (!credentialModal || credentialSaving) return;
    setCredentialSaving(true);
    try {
      const data = await apiCall("/saas/v1/api-credentials", {
        method: "POST",
        body: JSON.stringify({
          category: credentialModal.category || "ai",
          provider_code: credentialModal.code,
          credential_key: credentialModal.credential_key,
          display_name: credentialModal.name,
          value: credentialModal.value,
          selected_model: credentialModal.selected_model || "",
        }),
      });
      setApiCredentials((prev) => {
        const others = prev.filter((item) => item.credential_key !== data.credential_key);
        return [...others, data].sort((a, b) => String(a.credential_key).localeCompare(String(b.credential_key)));
      });
      setCredentialModal(null);
      showStatus("Credencial guardada cifrada en backend", "ok");
      showMilestoneOnce(`credential:${data?.credential_key || credentialModal.credential_key}:${data?.updated_at || data?.has_secret || "saved"}`, {
        eyebrow: credentialModal.category === "ai" ? "IA conectada" : "Credencial segura",
        title: credentialModal.category === "ai" ? `${credentialModal.name} quedó disponible` : `${credentialModal.name} quedó guardado`,
        body: credentialModal.category === "ai"
          ? "Carga los modelos disponibles y selecciona el modelo activo para que los agentes usen esta credencial."
          : "La credencial quedó cifrada por empresa y solo se mostrará como pista protegida.",
        cta: credentialModal.category === "ai" ? "Ver APIs" : "Entendido",
        actionType: credentialModal.category === "ai" ? "settings-apis" : "",
      });
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setCredentialSaving(false);
    }
  };
  const loadCredentialModels = async (provider) => {
    if (!provider?.supportsModels) return;
    const key = provider.env;
    setCredentialModels((prev) => ({ ...prev, [key]: { ...(prev[key] || {}), loading: true, error: "" } }));
    try {
      const data = await apiCall(`/saas/v1/api-credentials/${encodeURIComponent(provider.code)}/models?credential_key=${encodeURIComponent(key)}`);
      const models = data?.models || [];
      const current = credentialByKey[key]?.selected_model || models[0]?.id || "";
      const notice = providerModelsNotice(data, provider);
      setCredentialModels((prev) => ({ ...prev, [key]: { loading: false, models, selected: current, source: data?.source || "", warning: data?.ok === false ? notice : "" } }));
      showStatus(notice, data?.ok === false ? "neutral" : "ok");
    } catch (err) {
      const models = fallbackProviderModels(provider);
      const current = credentialByKey[key]?.selected_model || models[0]?.id || "";
      const warning = `No se pudo consultar ${provider?.name || "el proveedor"} ahora. Cargué modelos de referencia para que puedas continuar.`;
      setCredentialModels((prev) => ({ ...prev, [key]: { ...(prev[key] || {}), loading: false, models, selected: current, source: "static", warning, error: "" } }));
      showStatus(warning, "neutral");
    }
  };
  const saveCredentialModel = async (provider) => {
    const key = provider.env;
    const selected = credentialModels[key]?.selected || credentialByKey[key]?.selected_model || "";
    if (!selected) return showStatus("Selecciona un modelo primero.", "neutral");
    try {
      const data = await apiCall("/saas/v1/api-credentials", {
        method: "POST",
        body: JSON.stringify({
          category: provider.category,
          provider_code: provider.code,
          credential_key: key,
          display_name: provider.name,
          selected_model: selected,
        }),
      });
      setApiCredentials((prev) => {
        const others = prev.filter((item) => item.credential_key !== data.credential_key);
        return [...others, data].sort((a, b) => String(a.credential_key).localeCompare(String(b.credential_key)));
      });
      showStatus("Modelo preferido guardado", "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    }
  };
  const processSelectedWithAi = async () => {
    if (!selectedConversation?.id) return;
    try {
      const data = await apiCall(`/saas/v1/ai/conversations/${encodeURIComponent(selectedConversation.id)}/process`, { method: "POST" });
      const result = data?.result || {};
      if ((result.outbound || {}).ok) showStatus("IA procesó la conversación y encoló respuesta.", "ok");
      else showStatus(`IA procesada: ${result.skipped || "sin respuesta para enviar"}`, "neutral");
      await loadMessages(selectedConversation, { preserveComposer: true });
      await loadInbox();
    } catch (err) {
      showStatus(String(err.message || err), "error");
    }
  };
  const submitAiTest = async (event) => {
    event.preventDefault();
    setAiTestResult("");
    try {
      const data = await apiCall("/saas/v1/ai/test", { method: "POST", body: JSON.stringify(aiTest) });
      const reply = data?.result?.reply || "";
      setAiTestResult(reply || JSON.stringify(data?.result || {}, null, 2));
      showStatus("Prueba IA ejecutada con el proveedor activo.", "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    }
  };

  const credentialKeysForProvider = (provider) => [provider.env, ...((Array.isArray(provider.fields) ? provider.fields : []) || [])].filter(Boolean);
  const credentialIsConfigured = (credentialKey) => Boolean(credentialByKey[credentialKey]?.has_secret || credentialByKey[credentialKey]?.selected_model);
  const providerIsConfigured = (provider) => credentialKeysForProvider(provider).some((key) => credentialIsConfigured(key));
  const cardIsExpanded = (provider, credentialKey = provider.env) => Boolean(
    expandedCredentialCards[credentialKey] || credentialIsConfigured(credentialKey) || expandedCredentialCards[`provider:${provider.code}`]
  );
  const expandCredentialCard = (key) => setExpandedCredentialCards((prev) => ({ ...prev, [key]: true }));
  const collapseCredentialCard = (key) => setExpandedCredentialCards((prev) => ({ ...prev, [key]: false }));

  const renderProviderPicker = (providers, options = {}) => {
    const items = providers.filter((provider) => {
      const key = options.grouped ? `provider:${provider.code}` : provider.env;
      return !expandedCredentialCards[key] && !(options.grouped ? providerIsConfigured(provider) : credentialIsConfigured(provider.env));
    });
    if (!items.length) return null;
    return (
      <div className="api-provider-picker">
        {items.map((provider) => {
          const key = options.grouped ? `provider:${provider.code}` : provider.env;
          return (
            <button type="button" className="api-provider-tile" key={key} onClick={() => expandCredentialCard(key)}>
              <strong>{provider.name}</strong>
              <span>{provider.summary || provider.models || provider.fields || provider.env}</span>
              <small>Añadir</small>
            </button>
          );
        })}
      </div>
    );
  };

  const renderCredentialCard = (provider, credentialKey = provider.env, options = {}) => {
    if (!cardIsExpanded(provider, credentialKey) && !options.force) return null;
    const credential = credentialByKey[credentialKey] || {};
    const modelsState = credentialModels[credentialKey] || {};
    const modelOptions = modelsState.models || [];
    const selectedModel = modelsState.selected ?? credential.selected_model ?? "";
    const canCollapse = !credentialIsConfigured(credentialKey) && options.collapsible !== false;
    return (
      <div className="api-card" key={`${provider.code}-${credentialKey}`}>
        <div className="api-card-headline">
          <div><strong>{provider.name}</strong><span>{provider.summary || provider.models || provider.fields || `Principal: ${provider.env}`}</span></div>
          <span className={`secret-pill ${credential.has_secret ? "saved" : "missing"}`}>{credential.has_secret ? `Guardada ${credential.secret_hint || ""}` : "Sin guardar"}</span>
        </div>
        <div className="api-key-row">
          <span>{credentialKey}</span>
          <div className="api-key-actions">
            <button type="button" onClick={() => openCredentialModal(provider, credentialKey)}>{credential.has_secret ? "Actualizar" : "Agregar"}</button>
            {canCollapse ? <button type="button" className="ghost-button small" onClick={() => collapseCredentialCard(credentialKey)}>Ocultar</button> : null}
          </div>
        </div>
        {provider.alt ? <small>Alias / extra: {provider.alt}</small> : null}
        {provider.supportsModels ? (
          <div className="model-loader">
            <div className="row-actions">
              <button type="button" onClick={() => loadCredentialModels(provider)} disabled={modelsState.loading}>{modelsState.loading ? "Cargando..." : "Cargar modelos"}</button>
              <button type="button" className="primary" onClick={() => saveCredentialModel(provider)} disabled={!selectedModel}>Guardar modelo</button>
            </div>
            <select value={selectedModel} onChange={(event) => setCredentialModels((prev) => ({ ...prev, [credentialKey]: { ...(prev[credentialKey] || {}), selected: event.target.value } }))}>
              <option value="">{credential.selected_model ? `Actual: ${credential.selected_model}` : "Carga modelos disponibles..."}</option>
              {modelOptions.map((model) => <option key={model.id} value={model.id}>{model.label || model.id}</option>)}
            </select>
            {credential.selected_model ? <small>Modelo guardado: {credential.selected_model}</small> : null}
            {modelsState.warning ? <small className="soft-copy">{modelsState.warning}</small> : null}
            {modelsState.error ? <small className="danger-copy">{modelsState.error}</small> : null}
          </div>
        ) : null}
      </div>
    );
  };

  const renderCredentialSection = (providers) => (
    <>
      {renderProviderPicker(providers)}
      <div className="api-card-grid">
        {providers.map((provider) => renderCredentialCard(provider)).filter(Boolean)}
      </div>
    </>
  );

  const renderChannelCredentialGroup = (provider) => {
    const groupKey = `provider:${provider.code}`;
    const expanded = expandedCredentialCards[groupKey] || providerIsConfigured(provider);
    if (!expanded) return null;
    return (
      <div className="api-channel-group" key={provider.code}>
        <div className="api-card-headline">
          <div><strong>{provider.name}</strong><span>{provider.summary || `Principal: ${provider.env}`}</span></div>
          <button type="button" className="ghost-button small" onClick={() => collapseCredentialCard(groupKey)} disabled={providerIsConfigured(provider)}>Ocultar</button>
        </div>
        <div className="api-field-list">
          {renderCredentialCard(provider, provider.env, { force: true, collapsible: false })}
          {provider.fields.map((field) => renderCredentialCard({ ...provider, name: field, env: field, supportsModels: false }, field, { force: true, collapsible: false }))}
        </div>
      </div>
    );
  };

  const renderChannelCredentialSection = (providers) => (
    <>
      {renderProviderPicker(providers, { grouped: true })}
      <div className="api-card-grid channel-api-grid">
        {providers.map((provider) => renderChannelCredentialGroup(provider)).filter(Boolean)}
      </div>
    </>
  );

  const advisorContextPayload = () => ({
    context_type: activeView === "inbox" && selectedConversation?.id ? "conversation" : activeView,
    context_id: activeView === "inbox" && selectedConversation?.id ? selectedConversation.id : "",
    module: activeView,
  });

  const sendAdvisorMessage = async (messageOverride = "") => {
    const text = String(messageOverride || advisorInput || "").trim();
    if (!text || advisorLoading) return;
    const tempId = `local-${Date.now()}`;
    const assistantTempId = `assistant-${Date.now()}`;
    setAdvisorInput("");
    setAdvisorOpen(true);
    setAdvisorStreamStatus("Preparando contexto...");
    setAdvisorMessages((prev) => [
      ...prev,
      { id: tempId, role: "user", content: text, created_at: new Date().toISOString(), metadata_json: { local: true } },
      { id: assistantTempId, role: "assistant", content: "", created_at: new Date().toISOString(), metadata_json: { streaming: true } },
    ]);
    setAdvisorLoading(true);
    try {
      const response = await streamApiCall("/saas/v1/advisor/chat/stream", {
        method: "POST",
        body: JSON.stringify({ message: text, thread_id: advisorThreadId, ...advisorContextPayload() }),
      });
      if (!response.body) throw new Error("stream_unavailable");
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let finalOk = true;
      while (true) {
        const { done, value } = await reader.read();
        buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";
        for (const rawLine of lines) {
          const line = rawLine.trim();
          if (!line) continue;
          const event = JSON.parse(line);
          const data = event.data || {};
          if (event.type === "status") setAdvisorStreamStatus(data.message || "Analizando...");
          if (event.type === "thread" && data.id) setAdvisorThreadId(data.id);
          if (event.type === "user_message" && data.id) {
            setAdvisorMessages((prev) => prev.map((item) => item.id === tempId ? data : item));
          }
          if (event.type === "assistant_start") {
            setAdvisorMessages((prev) => prev.map((item) => item.id === assistantTempId ? { ...data, id: assistantTempId, content: "", metadata_json: { ...(data.metadata_json || {}), streaming: true } } : item));
          }
          if (event.type === "delta") {
            setAdvisorStreamStatus("Escribiendo respuesta...");
            setAdvisorMessages((prev) => prev.map((item) => item.id === assistantTempId ? { ...item, content: `${item.content || ""}${data.text || ""}` } : item));
          }
          if (event.type === "assistant_done" && data.id) {
            setAdvisorMessages((prev) => prev.map((item) => item.id === assistantTempId ? data : item));
          }
          if (event.type === "signals") {
            setAdvisorInsights(data.insights || []);
            setAdvisorRecommendations(data.recommendations || []);
            if (data.actions) setAdvisorActions(data.actions);
            if (data.memory) setAdvisorMemory(data.memory);
            setAdvisorLastSync(new Date().toISOString());
          }
          if (event.type === "done") finalOk = data.ok !== false;
          if (event.type === "error") throw new Error(data.message || "advisor_stream_error");
        }
        if (done) break;
      }
      if (!finalOk) showStatus("Advisor sin modelo AI activo. Revisa Ajustes > APIs.", "neutral");
    } catch (err) {
      setAdvisorMessages((prev) => [
        ...prev.filter((item) => ![tempId, assistantTempId].includes(item.id)),
        { id: `advisor-error-${Date.now()}`, role: "assistant", content: `No pude consultar el Advisor: ${String(err.message || err)}`, created_at: new Date().toISOString(), metadata_json: { error: true } },
      ]);
    } finally {
      setAdvisorLoading(false);
      setAdvisorStreamStatus("");
    }
  };

  const submitAdvisorChat = (event) => {
    event.preventDefault();
    sendAdvisorMessage();
  };

  const dismissAdvisorSignal = async (kind, id) => {
    if (!id) return;
    try {
      const path = kind === "recommendation" ? `/saas/v1/advisor/recommendations/${encodeURIComponent(id)}/dismiss` : `/saas/v1/advisor/insights/${encodeURIComponent(id)}/dismiss`;
      await apiCall(path, { method: "POST" });
      if (kind === "recommendation") setAdvisorRecommendations((prev) => prev.filter((item) => item.id !== id));
      else setAdvisorInsights((prev) => prev.filter((item) => item.id !== id));
    } catch (err) { showStatus(String(err.message || err), "error"); }
  };

  const applyAdvisorSignal = (item) => {
    const action = item?.recommended_action_json || item?.action_json || {};
    if (action.module) setActiveView(action.module);
    if (action.tab) setSettingsTab(action.tab);
    if (action.module || action.tab) setAdvisorOpen(false);
  };

  const prepareAdvisorAction = async (item) => {
    if (!item?.id) return;
    const kind = item._kind || (item.recommendation_type ? "recommendation" : "insight");
    setAdvisorBusyActionId(`prepare:${item.id}`);
    try {
      const path = kind === "recommendation"
        ? `/saas/v1/advisor/recommendations/${encodeURIComponent(item.id)}/action`
        : `/saas/v1/advisor/insights/${encodeURIComponent(item.id)}/action`;
      const data = await apiCall(path, { method: "POST" });
      if (data?.action?.id) {
        setAdvisorActions((prev) => [data.action, ...prev.filter((action) => action.id !== data.action.id)]);
        showStatus("Accion del Advisor preparada para aprobacion", "ok");
        await loadAdvisorSignals(true);
      } else {
        showStatus("No pude preparar esa accion. Revisa si la recomendacion sigue activa.", "error");
      }
    } catch (err) { showStatus(String(err.message || err), "error"); }
    finally { setAdvisorBusyActionId(""); }
  };

  const approveAdvisorAction = async (actionId) => {
    if (!actionId) return;
    setAdvisorBusyActionId(`approve:${actionId}`);
    try {
      const data = await apiCall(`/saas/v1/advisor/actions/${encodeURIComponent(actionId)}/approve`, { method: "POST" });
      if (data?.action?.id) {
        setAdvisorActions((prev) => prev.map((item) => item.id === actionId ? data.action : item));
        showStatus("Accion aprobada. Queda lista para ejecucion asistida.", "ok");
        await loadAdvisorSignals(true);
      }
    } catch (err) { showStatus(String(err.message || err), "error"); }
    finally { setAdvisorBusyActionId(""); }
  };

  const dismissAdvisorAction = async (actionId) => {
    if (!actionId) return;
    setAdvisorBusyActionId(`dismiss:${actionId}`);
    try {
      await apiCall(`/saas/v1/advisor/actions/${encodeURIComponent(actionId)}/dismiss`, { method: "POST" });
      setAdvisorActions((prev) => prev.filter((item) => item.id !== actionId));
      await loadAdvisorSignals(true);
    } catch (err) { showStatus(String(err.message || err), "error"); }
    finally { setAdvisorBusyActionId(""); }
  };

  const executeAdvisorAction = async (actionId) => {
    if (!actionId) return;
    setAdvisorBusyActionId(`execute:${actionId}`);
    try {
      const data = await apiCall(`/saas/v1/advisor/actions/${encodeURIComponent(actionId)}/execute`, { method: "POST" });
      if (data?.action?.id) {
        setAdvisorActions((prev) => prev.map((item) => item.id === actionId ? data.action : item));
        const navigation = data?.result?.navigation || data?.action?.execution_result_json?.navigation || {};
        if (navigation.module) setActiveView(navigation.module);
        if (navigation.tab) setSettingsTab(navigation.tab);
        if (data.ok) showStatus("Accion ejecutada de forma segura", "ok");
        else showStatus(data.error || "La accion requiere executor adicional", "error");
        await loadAdvisorSignals(true);
      }
    } catch (err) { showStatus(String(err.message || err), "error"); }
    finally { setAdvisorBusyActionId(""); }
  };

  const sendAdvisorFeedback = async (messageId, rating) => {
    if (!messageId) return;
    try {
      await apiCall(`/saas/v1/advisor/messages/${encodeURIComponent(messageId)}/feedback`, {
        method: "POST",
        body: JSON.stringify({ rating }),
      });
      setAdvisorMessages((prev) => prev.map((message) => message.id === messageId ? {
        ...message,
        metadata_json: { ...(message.metadata_json || {}), feedback_rating: rating },
      } : message));
      loadAdvisorSignals(true);
      showStatus(rating === "helpful" ? "Feedback guardado. El Advisor aprende de esto." : "Feedback guardado para revision del Advisor.", rating === "helpful" ? "ok" : "neutral");
    } catch (err) { showStatus(String(err.message || err), "error"); }
  };

  const isLogged = Boolean(accessToken && me);

  if (!isLogged) {
    return (
      <main className="auth-page">
        <section className="auth-card glass-card">
          <div className="auth-brand"><span className="auth-logo">S</span><h1>Scentra +AI</h1><p>{mode === "login" ? "Control de conversaciones, IA y ventas." : mode === "register" ? "Crea tu empresa y empieza a configurar." : mode === "forgot" ? "Recupera el acceso de forma segura." : mode === "mfa" ? "Confirma el segundo factor de seguridad." : "Define una nueva clave segura."}</p></div>
          {status ? <div className={`status ${statusTone}`}>{status}</div> : null}
          {mode === "login" ? (
            <form className="auth-form" onSubmit={submitLogin}>
              <label>Correo</label><div className="input-wrap"><span>@</span><input autoComplete="email" inputMode="email" value={login.email} onChange={(event) => setLogin((prev) => ({ ...prev, email: event.target.value }))} /></div>
              <label>Clave</label><div className="input-wrap"><span>key</span><input autoComplete="current-password" type="password" value={login.password} onChange={(event) => setLogin((prev) => ({ ...prev, password: event.target.value }))} /></div>
              <TurnstileChallenge onToken={setLoginCaptchaToken} resetKey={loginCaptchaReset} />
              <button className="primary auth-submit" type="submit">Entrar</button>
              <div className="auth-links"><button type="button" onClick={() => setMode("forgot")}>Recuperar clave</button><button type="button" onClick={() => setMode("register")}>Crear cuenta</button></div>
            </form>
          ) : mode === "mfa" ? (
            <form className="auth-form" onSubmit={submitMfa}>
              <label>Codigo 2FA</label><div className="input-wrap"><span>#</span><input autoComplete="one-time-code" inputMode="numeric" value={mfaCode} onChange={(event) => setMfaCode(event.target.value)} /></div>
              <small className="field-hint">Enviado a {mfaChallenge?.email_hint || "tu correo"}. {mfaChallenge?.expires_at ? `Vence: ${dateLabel(mfaChallenge.expires_at)}.` : ""}</small>
              {mfaChallenge?.dev_otp ? <small className="field-hint">Local dev OTP: {mfaChallenge.dev_otp}</small> : null}
              <button className="primary auth-submit" type="submit">Verificar codigo</button>
              <div className="auth-links"><button type="button" onClick={() => { setMfaChallenge(null); setMfaCode(""); setMode("login"); }}>Volver al login</button></div>
            </form>
          ) : mode === "register" ? (
            <form className="auth-form" onSubmit={submitRegister}>
              <label>Correo propietario</label><div className="input-wrap"><span>@</span><input autoComplete="email" inputMode="email" value={register.email} onChange={(event) => setRegister((prev) => ({ ...prev, email: event.target.value }))} /></div>
              <label>Clave</label><div className="input-wrap"><span>key</span><input autoComplete="new-password" type="password" minLength={8} value={register.password} onChange={(event) => setRegister((prev) => ({ ...prev, password: event.target.value }))} /></div><small className="field-hint">Minimo 8 caracteres.</small>
              <label>Nombre</label><div className="input-wrap"><span>id</span><input autoComplete="name" value={register.full_name} onChange={(event) => setRegister((prev) => ({ ...prev, full_name: event.target.value }))} /></div>
              <label>Empresa</label><div className="input-wrap"><span>co</span><input autoComplete="organization" value={register.tenant_name} onChange={(event) => setRegister((prev) => ({ ...prev, tenant_name: event.target.value }))} /></div>
              <label>Slug publico</label><div className="input-wrap"><span>#</span><input autoComplete="off" value={register.tenant_slug} onChange={(event) => setRegister((prev) => ({ ...prev, tenant_slug: event.target.value }))} /></div>
              <label>Industria</label><div className="input-wrap"><span>in</span><select value={register.industry_code} onChange={(event) => setRegister((prev) => ({ ...prev, industry_code: event.target.value }))}>{publicVerticalPacks.map((pack) => <option key={pack.code} value={pack.code}>{pack.label}</option>)}</select></div>
              <small className="field-hint">Tu cuenta inicia con demo de 30 dias en el plan basico. Luego el admin puede activar el plan final.</small>
              <TurnstileChallenge onToken={setRegisterCaptchaToken} resetKey={registerCaptchaReset} />
              <button className="primary auth-submit" type="submit">Crear demo 30 dias</button>
              <div className="auth-links"><button type="button" onClick={() => setMode("login")}>Volver al login</button></div>
            </form>
          ) : mode === "forgot" ? (
            <form className="auth-form" onSubmit={submitPasswordRecovery}>
              <label>Correo</label><div className="input-wrap"><span>@</span><input autoComplete="email" inputMode="email" value={passwordRecovery.email} onChange={(event) => setPasswordRecovery((prev) => ({ ...prev, email: event.target.value }))} /></div>
              <small className="field-hint">Si existe una cuenta activa, enviaremos un enlace de recuperacion.</small>
              <TurnstileChallenge onToken={setRecoveryCaptchaToken} resetKey={recoveryCaptchaReset} />
              <button className="primary auth-submit" type="submit">Enviar recuperacion</button>
              <div className="auth-links"><button type="button" onClick={() => setMode("login")}>Volver al login</button><button type="button" onClick={() => setMode("reset")}>Ya tengo token</button></div>
            </form>
          ) : (
            <form className="auth-form" onSubmit={submitPasswordReset}>
              <label>Token de recuperacion</label><div className="input-wrap"><span>#</span><input autoComplete="one-time-code" value={passwordReset.token} onChange={(event) => setPasswordReset((prev) => ({ ...prev, token: event.target.value }))} /></div>
              <label>Nueva clave</label><div className="input-wrap"><span>key</span><input autoComplete="new-password" type="password" minLength={8} value={passwordReset.new_password} onChange={(event) => setPasswordReset((prev) => ({ ...prev, new_password: event.target.value }))} /></div>
              <label>Confirmar clave</label><div className="input-wrap"><span>key</span><input autoComplete="new-password" type="password" minLength={8} value={passwordReset.confirm_password} onChange={(event) => setPasswordReset((prev) => ({ ...prev, confirm_password: event.target.value }))} /></div>
              <TurnstileChallenge onToken={setResetCaptchaToken} resetKey={resetCaptchaReset} />
              <button className="primary auth-submit" type="submit">Actualizar clave</button>
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
        <div className="brand"><span className="brand-mark">S</span><div><strong>Scentra +AI</strong><small>{t("brand.subtitle")}</small></div></div>
        <nav>
          {navItems.map(({ key, label, icon }) => <button key={key} className={"nav-item " + (activeView === key ? "active" : "")} onClick={() => setActiveView(key)}><span className="nav-icon">{icon}</span><span>{label}</span></button>)}
        </nav>
        <div className="company-card"><span>Empresa activa</span><strong>{activeCompany?.tenant_name || activeCompany?.name || me.tenant_id}</strong><small>{me.role} / plan {billingPlan.display_name || billingPlan.plan_code || activeCompany?.plan_code || "starter"} / {selectedVerticalPack?.label || currentIndustryCode}</small></div>
      </aside>

      <main className={`content ${activeView === "inbox" ? "content-inbox" : ""}`}>
        <header className="topbar glass-panel">
          <div><p className="eyebrow">{todayLabel()}</p><h1>{viewTitles[activeView]?.[0]}</h1><p>{viewTitles[activeView]?.[1]}</p></div>
          <div className="top-actions"><select value={me.tenant_id || ""} onChange={(event) => switchCompany(event.target.value)} aria-label="Empresa activa">{tenants.map((company) => <option key={company.tenant_id} value={company.tenant_id}>{company.tenant_name || company.name} / {company.role}</option>)}</select><button type="button" onClick={clearTokens}>Salir</button></div>
        </header>
        {status ? <div className={`status floating-status ${statusTone}`}>{status}</div> : null}
        {lifecycleStatus === "trial" && activeView !== "dashboard" ? <div className="trial-strip glass-card"><strong>Demo activa</strong><span>{trialEndLabel ? `Hasta ${trialEndLabel}` : "30 dias de prueba"}</span><small>Configura Meta, IA y plantillas antes de pasar a pago.</small></div> : null}

        {activeView === "dashboard" ? (
          <section className="dashboard-page">
            <div className="hero-card glass-card"><div><p className="eyebrow">Resumen operativo</p><h2>Bienvenido, {currentUserName}</h2><p>Datos reales de la empresa activa: CRM, inbox, mensajes, webhooks y consumo del plan.</p>{lifecycleStatus === "trial" ? <p className="trial-note">Demo de 30 dias activa{trialEndLabel ? ` hasta ${trialEndLabel}` : ""}. Puedes configurar Meta, IA y plantillas antes de pasar a pago.</p> : null}</div><button type="button" className="icon-button" onClick={() => loadDashboard(false)}>Actualizar</button></div>
            <div className="metric-grid">
              <article className="metric-card mint"><span>Estado cuenta</span><strong>{lifecycleLabel(lifecycleStatus)}</strong><small>{trialEndLabel ? `Termina ${trialEndLabel}` : "Operativa"}</small></article>
              <article className="metric-card mint"><span>Clientes CRM</span><strong>{number(dashboardConversations)}</strong><small>Registros por empresa</small></article>
              <article className="metric-card blue"><span>No leidos</span><strong>{number(dashboardUnread)}</strong><small>Pendientes en inbox</small></article>
              <article className="metric-card amber"><span>Mensajes 30d</span><strong>{number(dashboardTotals.messages_30d || 0)}</strong><small>{number(dashboardTotals.inbound_30d || 0)} IN / {number(dashboardTotals.outbound_30d || 0)} OUT</small></article>
              <article className="metric-card rose"><span>Clientes nuevos</span><strong>{number(dashboardTotals.new_customers_30d || 0)}</strong><small>Ultimos 30 dias</small></article>
              <article className="metric-card violet"><span>Integraciones</span><strong>{number(connectedIntegrations)} / {number(billingLimits.max_integrations)}</strong><small>{number(activeWebhooks)} webhooks activos</small></article>
              <article className="metric-card rose"><span>SLA vencido</span><strong>{number(dashboardTotals.sla_overdue || 0)}</strong><small>{number(dashboardTotals.open_tasks || 0)} tareas abiertas</small></article>
              <article className="metric-card amber"><span>Leads calientes</span><strong>{number(dashboardTotals.hot_leads || 0)}</strong><small>{number(dashboardTotals.tasks_due_today || 0)} follow-ups hoy</small></article>
            </div>
            {dashboardPredictive.latest?.length || Number(dashboardPredictive.open_recommendations || 0) ? (
              <section className="dashboard-predictive-strip glass-card">
                <div>
                  <span>Predictive Intelligence</span>
                  <strong>{number(dashboardPredictive.open_recommendations || 0)} recomendaciones abiertas</strong>
                </div>
                {(dashboardPredictive.latest || []).slice(0, 4).map((item) => (
                  <button type="button" key={`${item.prediction_type}-${item.created_at}`} onClick={() => setActiveView("intelligence")}>
                    <span>{predictionTypeLabel(item.prediction_type)}</span>
                    <strong>{number(item.score)}</strong>
                    <small>{item.label || item.status}</small>
                  </button>
                ))}
              </section>
            ) : null}
            <section className="dashboard-layout">
              <article className="panel glass-card wide-panel"><div className="panel-head"><h2>Funnel comercial</h2><span>CRM real por etapa</span></div>{dashboardFunnel.length ? dashboardFunnel.map((item) => <div className="funnel-line" key={item.stage}><div><span>{item.label}</span><small>{number(item.count)} / {number(item.pct)}%</small></div><div className="meter"><span style={{ width: `${Math.max(2, Number(item.pct || 0))}%` }} /></div></div>) : <div className="empty">Aun no hay clientes para calcular funnel.</div>}</article>
              <article className="panel glass-card"><div className="panel-head"><h2>Uso del plan</h2><span>{billingOverview?.period_yyyymm || "periodo"}</span></div><div className="usage-bars"><div className="usage-line"><div><strong>Mensajes</strong><span>{number(billingRemaining.monthly_messages)} disponibles</span></div><div className="meter"><span style={{ width: `${pct(billingUsage.used_monthly_messages, billingLimits.max_monthly_messages)}%` }} /></div></div><div className="usage-line"><div><strong>Integraciones</strong><span>{number(billingRemaining.integrations)} disponibles</span></div><div className="meter"><span style={{ width: `${pct(billingUsage.used_integrations, billingLimits.max_integrations)}%` }} /></div></div><div className="usage-line"><div><strong>Usuarios</strong><span>{number(billingRemaining.agents)} disponibles</span></div><div className="meter"><span style={{ width: `${pct(billingUsage.used_agents, billingLimits.max_agents)}%` }} /></div></div></div></article>
              <article className="panel glass-card chart-panel"><div className="panel-head"><h2>Actividad reciente</h2><span>mensajes por dia</span></div><div className="activity-bars" role="img" aria-label="Mensajes por dia en los ultimos 14 dias">{dashboardActivity.map((item) => <div className="activity-day" key={item.date} title={`${item.date}: ${item.total} mensajes`}><span style={{ height: `${Math.max(4, (Number(item.total || 0) / dashboardActivityMax) * 100)}%` }} /><small>{String(item.date || "").slice(5)}</small></div>)}</div>{dashboardActivity.every((item) => Number(item.total || 0) === 0) ? <div className="empty">Sin mensajes recientes todavia.</div> : null}</article>
              <article className="panel glass-card"><div className="panel-head"><h2>Canales y pagos</h2><span>operacion</span></div><div className="channel-list dashboard-list">{dashboardChannels.length ? dashboardChannels.map((item) => <div key={item.channel}><strong>{number(item.count)}</strong><span>{item.channel}</span></div>) : <div><strong>0</strong><span>Sin canales</span></div>}<div><strong>{number(dashboardTotals.pending_payments || 0)}</strong><span>Pagos pendientes</span></div><div><strong>{number(dashboardTotals.paid_customers || 0)}</strong><span>Pagos confirmados</span></div></div></article>
              <article className="panel glass-card wide-panel"><div className="panel-head"><h2>Ultimos movimientos</h2><span>mensajes reales</span></div><div className="recent-list">{dashboardRecent.map((item, idx) => <div key={`${item.created_at}-${idx}`}><strong>{item.display_name || item.phone || item.external_contact_id || "Cliente"}</strong><span>{item.direction} / {item.channel} / {compactDateTimeLabel(item.created_at)}</span><p>{item.text}</p></div>)}{dashboardRecent.length === 0 ? <div className="empty">Todavia no hay movimientos registrados.</div> : null}</div></article>
            </section>
          </section>
        ) : activeView === "inbox" ? (
          <section className={`inbox-grid ${crmPanelOpen ? "crm-open" : "crm-closed"}`}>
            <div className="panel glass-card inbox-list">
              <div className="panel-head inbox-list-head"><h2>Inbox</h2><span>{inboxMode === "comments" ? `${filteredSocialComments.length} comentarios` : unreadTotal ? `${number(unreadTotal)} sin leer` : `${filteredConversations.length} chats`}</span></div>
              <div className="inbox-mode-tabs">
                <button type="button" className={inboxMode === "dms" ? "active" : ""} onClick={() => setInboxMode("dms")}>Mensajes</button>
                <button type="button" className={inboxMode === "comments" ? "active" : ""} onClick={() => { setInboxMode("comments"); loadSocialComments({ keepSelection: true }); }}>Comentarios</button>
              </div>
              <div className={`inbox-sync ${inboxRefreshing ? "active" : ""} ${inboxSyncError ? "error" : ""}`}>
                <span>{inboxRefreshing ? "Sincronizando" : inboxLastSyncAt ? `Actualizado ${compactDateTimeLabel(inboxLastSyncAt)}` : "Sincronizacion pendiente"}</span>
                {inboxSyncError ? <small>{inboxSyncError}</small> : <small>Polling visible con pausa en segundo plano</small>}
              </div>
              <div className="inbox-filters">
                <button type="button" className={inboxChannelFilter === "all" ? "active" : ""} onClick={() => setInboxChannelFilter("all")}>Todos</button>
                {availableInboxChannels.map((channel) => <button type="button" key={channel} className={inboxChannelFilter === channel ? "active" : ""} onClick={() => setInboxChannelFilter(channel)}>{channelLabel(channel)}</button>)}
                <input value={inboxSearch} onChange={(event) => setInboxSearch(event.target.value)} placeholder="Buscar telefono, nombre o preview..." />
                <button type="button" onClick={() => { setInboxSearch(""); setInboxChannelFilter("all"); setInboxQueueFilter("all"); setInboxAgentFilter("all"); }}>Limpiar</button>
              </div>
              <div className="inbox-agent-filter">
                <label>Agente IA
                  <select value={inboxAgentFilter} onChange={(event) => setInboxAgentFilter(event.target.value)}>
                    <option value="all">Todos los agentes</option>
                    {activeInboxAiAgents.map((agent) => <option key={agent.id} value={agent.id}>{agent.name || agentTypeLabel(agent.agent_type)}</option>)}
                  </select>
                </label>
              </div>
              <div className="inbox-smart-filters">
                {[["all","Todos"],["unread","Sin leer"],["mine","Mios"],["unassigned","Sin asignar"],["sla","SLA"],["hot","Hot"],["churn","Churn"],["human","Humano"],["ai","IA"]].map(([key, label]) => (
                  <button key={key} type="button" className={inboxQueueFilter === key ? "active" : ""} onClick={() => setInboxQueueFilter(key)}>{label}</button>
                ))}
              </div>
              <div className="conversation-list">
                {inboxMode === "dms" ? filteredConversations.map((conversation) => (
                  <button type="button" className={`conversation-item ${selectedConversation?.id === conversation.id ? "active" : ""}`} key={conversation.id} onClick={() => loadMessages(conversation)}>
                    <span className="conversation-title"><strong>{conversation.display_name || conversation.phone || conversation.external_contact_id}</strong>{Number(conversation.unread_count || 0) > 0 ? <em>{number(conversation.unread_count)}</em> : null}</span>
                    <span className="conversation-meta"><b>{channelLabel(conversation.channel)}</b>{Number(conversation.unread_count || 0) > 0 ? <small>Sin leer</small> : <small>Leido</small>}</span>
                    <span className="conversation-badges">
                      {Number(conversation.lead_score || 0) > 0 ? <mark className={`lead-${conversation.lead_temperature || "cold"}`}>{leadTemperatureLabel(conversation.lead_temperature, conversation.lead_score)} {number(conversation.lead_score)}</mark> : null}
                      {conversation.predictive_intelligence?.source === "intelligence_prediction" ? <mark>ML {number(conversation.predictive_intelligence?.conversion_probability || 0)}%</mark> : null}
                      {Number(conversation.predictive_intelligence?.churn_risk || 0) >= 40 ? <mark className={Number(conversation.predictive_intelligence?.churn_risk || 0) >= 70 ? "danger" : ""}>Churn {number(conversation.predictive_intelligence?.churn_risk || 0)}</mark> : null}
                      {conversation.assigned_user_name ? <mark>{conversation.assigned_user_name}</mark> : <mark>Sin asignar</mark>}
                      {conversation.assigned_ai_agent_name ? <mark>IA: {conversation.assigned_ai_agent_name}</mark> : null}
                      {conversation.sla_due_at || conversation.first_response_due_at ? <mark className={isPastDate(conversation.sla_due_at || conversation.first_response_due_at) ? "danger" : ""}>SLA {compactDateTimeLabel(conversation.sla_due_at || conversation.first_response_due_at)}</mark> : null}
                    </span>
                    <small>{conversation.last_message_text || "-"}</small>
                  </button>
                )) : filteredSocialComments.map((comment) => (
                  <button type="button" className={`conversation-item comment-item ${selectedComment?.id === comment.id ? "active" : ""}`} key={comment.id} onClick={() => { setSelectedComment(comment); setCommentReplyText(comment.ai_suggestion || ""); setCommentEmojiOpen(false); setCommentReactionOpen(false); }}>
                    <span className="conversation-title"><strong>{comment.author_name || comment.author_username || comment.author_external_id || "Comentario"}</strong>{comment.status === "open" ? <em>1</em> : null}</span>
                    <span className="conversation-meta"><b>{channelLabel(comment.channel)}</b><small>{comment.status === "replied" ? "Respondido" : "Pendiente"}</small></span>
                    <small>{comment.message || "-"}</small>
                  </button>
                ))}
                {inboxMode === "dms" && filteredConversations.length === 0 ? <div className="empty">Sin conversaciones para este filtro.</div> : null}
                {inboxMode === "comments" && filteredSocialComments.length === 0 ? <div className="empty">Sin comentarios para este filtro.</div> : null}
              </div>
            </div>
            <div className="panel glass-card inbox-thread">
              {inboxMode === "comments" ? (
                <>
                  <div className="panel-head inbox-thread-head">
                    <div className="thread-title">
                      <span className="thread-avatar">{selectedComment ? String(selectedComment.author_name || selectedComment.author_username || "CM").slice(0, 2).toUpperCase() : "CM"}</span>
                      <div>
                        <h2>{selectedComment ? selectedComment.author_name || selectedComment.author_username || "Comentario" : "Comentarios"}</h2>
                        <span>{selectedComment ? `${channelLabel(selectedComment.channel)} / ${selectedComment.status || "open"}` : "Selecciona un comentario"}</span>
                      </div>
                    </div>
                    <div className="thread-actions"><button type="button" onClick={() => loadSocialComments({ keepSelection: true })}>Refrescar</button></div>
                  </div>
                  {selectedComment ? (
                    <div className="comment-detail business-suite-comments">
                      <article className="social-post-card meta-post-preview">
                        <div className="post-media-frame">
                          {selectedComment.media_url ? <img src={selectedComment.media_url} alt="Publicacion" /> : <span>Post</span>}
                        </div>
                        <div className="post-preview-body">
                          <span>Publicacion asociada</span>
                          <strong>{selectedComment.post_caption || "Sin caption disponible"}</strong>
                          <div className="post-preview-meta">
                            <small>{channelLabel(selectedComment.channel)}</small>
                            <small>{compactDateTimeLabel(selectedComment.external_created_time || selectedComment.created_at)}</small>
                          </div>
                          <div className="post-comment-focus">
                            <div className="comment-author-line">
                              <span className="mini-avatar">{String(selectedComment.author_name || selectedComment.author_username || "CM").slice(0, 2).toUpperCase()}</span>
                              <div><b>{selectedComment.author_name || selectedComment.author_username || selectedComment.author_external_id}</b><small>Comentario seleccionado</small></div>
                            </div>
                            <p>{selectedComment.message}</p>
                            <div className="comment-focus-actions">
                              {selectedComment.last_reaction_emoji ? <mark>{selectedComment.last_reaction_emoji} reaccionado</mark> : null}
                              {selectedComment.last_reply_text ? <mark>Respondido</mark> : null}
                            </div>
                          </div>
                          {selectedComment.permalink_url ? <a href={selectedComment.permalink_url} target="_blank" rel="noreferrer">Ver publicacion en Meta</a> : null}
                        </div>
                      </article>
                      {selectedComment.ai_suggestion ? <div className="ai-suggestion-card"><strong>Sugerencia IA</strong><p>{selectedComment.ai_suggestion}</p><button type="button" onClick={() => setCommentReplyText(selectedComment.ai_suggestion)}>Usar sugerencia</button></div> : null}
                      <form className="comment-reply-box meta-comment-composer" onSubmit={sendCommentReply}>
                        <div className="comment-composer-row">
                          <textarea rows={3} value={commentReplyText} onChange={(event) => setCommentReplyText(event.target.value)} placeholder="Responder comentario..." />
                          <button type="button" className="composer-icon" onClick={() => setCommentEmojiOpen((prev) => !prev)} title="Emojis">☺</button>
                        </div>
                        <div className="row-actions comment-actions">
                          <div className="comment-reaction-wrap">
                            <button type="button" onClick={() => setCommentReactionOpen((prev) => !prev)} disabled={Boolean(commentBusy)}>Reaccionar</button>
                            {commentReactionOpen ? (
                              <div className="emoji-panel comment-emoji-panel reaction-panel">
                                {["👍", "❤️", "👏", "🔥", "😍", "😂", "😮", "😢"].map((emoji) => (
                                  <button key={emoji} type="button" onClick={() => reactToComment(emoji)}>{emoji}</button>
                                ))}
                              </div>
                            ) : null}
                          </div>
                          <button type="button" onClick={() => generateCommentAiReply(selectedComment)} disabled={Boolean(commentBusy)}>{commentBusy === `ai-${selectedComment.id}` ? "Generando..." : "Generar con IA"}</button>
                          <button type="submit" className="primary" disabled={Boolean(commentBusy) || !commentReplyText.trim()}>{commentBusy === `reply-${selectedComment.id}` ? "Enviando..." : "Responder"}</button>
                        </div>
                        {commentEmojiOpen ? (
                          <div className="emoji-panel whatsapp-emoji-panel comment-emoji-panel">
                            <input value={emojiSearch} onChange={(event) => setEmojiSearch(event.target.value)} placeholder="Buscar emoji..." />
                            {visibleEmojiGroups.map((group) => (
                              <div className="emoji-group" key={`comment-${group.label}`}>
                                <strong>{group.icon} {group.label}</strong>
                                <div>{group.items.map((emoji, idx) => <button key={`comment-${group.label}-${emoji}-${idx}`} type="button" onClick={() => appendEmoji(emoji, "comment")}>{emoji}</button>)}</div>
                              </div>
                            ))}
                          </div>
                        ) : null}
                      </form>
                    </div>
                  ) : <div className="empty">Selecciona un comentario para responderlo.</div>}
                </>
              ) : (
              <>
              <div className="panel-head inbox-thread-head">
                <div className="thread-title">
                  <span className="thread-avatar">{selectedConversation ? String(selectedConversation.display_name || selectedConversation.phone || selectedConversation.external_contact_id || "?").slice(0, 2).toUpperCase() : "SC"}</span>
                  <div>
                    <h2>{selectedConversation ? selectedConversation.display_name || selectedConversation.external_contact_id : "Mensajes"}</h2>
                    {selectedConversation ? <span>Canal: {channelLabel(selectedConversation.channel)} / {selectedConversation.phone || selectedConversation.external_contact_id}</span> : null}
                  </div>
                </div>
                <div className="thread-actions">
                  {selectedConversation ? <button type="button" className={`takeover-toggle ${selectedConversation.takeover ? "active" : ""}`} onClick={toggleSelectedTakeover}>{selectedConversation.takeover ? "Takeover ON" : "Takeover OFF"}</button> : null}
                  {selectedConversation ? <button type="button" onClick={markSelectedConversationRead}>Leido</button> : null}
                  <button type="button" onClick={() => setNotificationSoundEnabled((prev) => !prev)}>{notificationSoundEnabled ? "Sonido ON" : "Sonido OFF"}</button>
                  <button type="button" onClick={toggleBrowserNotifications} disabled={notificationPermission === "unsupported"}>{browserNotificationsEnabled ? "Notifs ON" : "Notifs OFF"}</button>
                  <button type="button" onClick={() => setCrmPanelOpen((prev) => !prev)}>{crmPanelOpen ? "Ocultar CRM" : "CRM"}</button>
                </div>
              </div>
              <div className="messages" ref={messagesPanelRef}>
                {messages.map((message) => (
                  <div className={`message ${message.direction === "out" ? "out" : "in"} ${message.msg_type || "text"}`} key={message.id}>
                    <span className="message-type">{messageSenderLabel(message)}</span>
                    {renderMessageContent(message)}
                    <small className="message-foot">{chatTimeLabel(message.created_at)}{messageDeliveryState(message) ? <span className={`wa-checks ${messageDeliveryState(message).key}`} title={messageDeliveryState(message).label}>{messageDeliveryState(message).mark}</span> : null}</small>
                  </div>
                ))}
                {messages.length === 0 ? <div className="empty">Selecciona una conversacion.</div> : null}
                <div ref={messagesEndRef} aria-hidden="true" />
              </div>
              {selectedConversation ? (
                <form className="composer rich-composer" onSubmit={sendSelectedMessage}>
                  {attachmentFile ? (
                    <div className="attachment-preview">
                      <div>
                        <strong>{attachmentFile.name}</strong>
                        <span>{attachmentKind || mediaKindFromMime(attachmentFile.type)} / {Math.round((attachmentFile.size || 0) / 1024)} KB</span>
                      </div>
                      {attachmentFile.type.startsWith("image/") ? <img src={attachmentPreview} alt="Vista previa adjunto" /> : null}
                      {attachmentFile.type.startsWith("video/") ? <video src={attachmentPreview} controls playsInline /> : null}
                      {attachmentFile.type.startsWith("audio/") ? <div className="audio-message compact outgoing-preview"><AudioWaveform src={attachmentPreview} seed={attachmentFile.name} levels={attachmentWaveform} /><audio src={attachmentPreview} controls /></div> : null}
                      <button type="button" onClick={clearComposerAttachment}>Quitar</button>
                    </div>
                  ) : null}
                  {catalogDraft ? (
                    <div className="attachment-preview product-draft-preview">
                      <ProductMessageCard product={catalogDraft} compact />
                      <button type="button" onClick={() => setCatalogDraft(null)}>Quitar</button>
                    </div>
                  ) : null}
                  {isRecording ? (
                    <div className="recording-panel">
                      <strong>{formatDuration(recordingSeconds)}</strong>
                      <div className="recording-wave" aria-hidden="true">{recordingLevels.slice(-24).map((height, idx) => <span key={idx} style={{ height: `${height}px` }} />)}</div>
                      <button type="button" className="primary" onClick={stopVoiceRecording}>Listo</button>
                      <button type="button" onClick={cancelVoiceRecording}>Cancelar</button>
                    </div>
                  ) : null}
                  <input ref={composerFileRef} className="composer-file-input" type="file" accept="image/*,video/*,audio/*,.pdf,.doc,.docx,.xls,.xlsx,.txt" onChange={(event) => setComposerAttachment(event.target.files?.[0], event.currentTarget.dataset.kind || "")} />
                  <div className="attach-wrap">
                    <button type="button" className="composer-icon" onClick={() => setAttachMenuOpen((prev) => !prev)} title="Adjuntar">＋</button>
                    {attachMenuOpen ? (
                      <div className="attach-menu">
                        <button type="button" onClick={() => openAttachmentPicker("image")}>Imagen</button>
                        <button type="button" onClick={() => openAttachmentPicker("video")}>Video</button>
                        <button type="button" onClick={() => openAttachmentPicker("document")}>Documento</button>
                        <button type="button" onClick={() => openAttachmentPicker("audio")}>Audio</button>
                        <button type="button" onClick={() => openAttachmentPicker("catalog")}>Producto (Catalogo)</button>
                      </div>
                    ) : null}
                  </div>
                  <button type="button" className={`composer-icon mic-button ${isRecording ? "active" : ""}`} onClick={isRecording ? stopVoiceRecording : startVoiceRecording} title="Grabar nota de voz">♩</button>
                  <input value={replyText} onChange={(event) => setReplyText(event.target.value)} placeholder="Escribe un mensaje..." />
                  <button type="button" className="composer-icon" onClick={() => setEmojiOpen((prev) => !prev)} title="Emojis">☺</button>
                  <button type="submit" className="primary send-button" disabled={composerSending || (!replyText.trim() && !attachmentFile && !catalogDraft)}>{composerSending ? "..." : "➤"}</button>
                  {emojiOpen ? (
                    <div className="emoji-panel whatsapp-emoji-panel">
                      <input value={emojiSearch} onChange={(event) => setEmojiSearch(event.target.value)} placeholder="Buscar emoji..." />
                      {visibleEmojiGroups.map((group) => (
                        <div className="emoji-group" key={group.label}>
                          <strong>{group.icon} {group.label}</strong>
                          <div>{group.items.map((emoji, idx) => <button key={`${group.label}-${emoji}-${idx}`} type="button" onClick={() => appendEmoji(emoji)}>{emoji}</button>)}</div>
                        </div>
                      ))}
                    </div>
                  ) : null}
                </form>
              ) : null}
              </>
              )}
            </div>
            {inboxMode === "comments" ? (
              <aside className="panel glass-card inbox-crm comment-ai-settings">
                <div className="panel-head"><h2>IA Comentarios</h2><button type="button" onClick={() => loadSocialComments({ keepSelection: true })}>↻</button></div>
                <label className="check-row"><input type="checkbox" checked={Boolean(commentAiSettings?.enabled ?? true)} onChange={(event) => setCommentAiSettings((prev) => ({ ...(prev || {}), enabled: event.target.checked }))} /> Activar IA para comentarios</label>
                <label className="check-row"><input type="checkbox" checked={Boolean(commentAiSettings?.auto_generate)} onChange={(event) => setCommentAiSettings((prev) => ({ ...(prev || {}), auto_generate: event.target.checked }))} /> Generar sugerencias automaticas</label>
                <label>Tono<input value={commentAiSettings?.tone || ""} onChange={(event) => setCommentAiSettings((prev) => ({ ...(prev || {}), tone: event.target.value }))} placeholder="calido, breve y util" /></label>
                <label>Entrenamiento<textarea rows={8} value={commentAiSettings?.instructions || ""} onChange={(event) => setCommentAiSettings((prev) => ({ ...(prev || {}), instructions: event.target.value }))} placeholder="Como debe responder la IA ante comentarios publicos..." /></label>
                <button type="button" className="primary" onClick={saveCommentAiSettings} disabled={commentBusy === "settings"}>{commentBusy === "settings" ? "Guardando..." : "Guardar entrenamiento"}</button>
              </aside>
            ) : crmPanelOpen ? (
              <aside className="panel glass-card inbox-crm">
                <div className="panel-head"><h2>CRM - Cliente</h2><button type="button" onClick={() => setCrmPanelOpen(false)}>×</button></div>
                {selectedConversation ? (
                  <div className="crm-mini-form">
                    <div className="crm-snapshot"><span>Telefono</span><strong>{selectedConversation.phone || selectedConversation.external_contact_id}</strong><span>Canal</span><strong>{channelLabel(selectedConversation.channel)}</strong></div>
                    <div className="assignment-actions">
                      <span>Asignacion</span>
                      <strong>{selectedConversation.assigned_user_name || selectedConversation.assigned_user_email || "Sin asignar"}</strong>
                      <button type="button" onClick={() => assignSelectedConversation(me?.user_id || "")} disabled={!me?.user_id || selectedConversation.assigned_user_id === me?.user_id}>Asignarme</button>
                      <button type="button" onClick={() => assignSelectedConversation("")} disabled={!selectedConversation.assigned_user_id}>Liberar</button>
                    </div>
                    <div className="assignment-actions ai-owner-actions">
                      <span>Agente IA responsable</span>
                      <strong>{selectedConversation.assigned_ai_agent_name || "IA general"}</strong>
                      <select value={selectedConversation.assigned_ai_agent_id || ""} onChange={(event) => assignSelectedAiAgent(event.target.value)}>
                        <option value="">IA general</option>
                        {activeInboxAiAgents.map((agent) => <option key={agent.id} value={agent.id}>{agent.name || agentTypeLabel(agent.agent_type)}</option>)}
                      </select>
                      <button type="button" onClick={() => assignSelectedAiAgent("")} disabled={!selectedConversation.assigned_ai_agent_id}>Liberar IA</button>
                    </div>
                    <div className="crm-ops-card">
                      <div className="crm-ops-head">
                        <strong>Operacion</strong>
                        <span className={`lead-pill lead-${crmDraft.lead_temperature || "cold"}`}>{leadTemperatureLabel(crmDraft.lead_temperature, crmDraft.lead_score)} {number(crmDraft.lead_score)}</span>
                      </div>
                      <label>Prioridad<select value={crmDraft.priority || "normal"} onChange={(event) => updateCrmDraft("priority", event.target.value)}><option value="low">Baja</option><option value="normal">Normal</option><option value="high">Alta</option><option value="urgent">Urgente</option></select></label>
                      <label>Score<input type="number" min="0" max="100" value={crmDraft.lead_score ?? 0} onChange={(event) => updateCrmDraft("lead_score", Number(event.target.value || 0))} /></label>
                      <label>Temperatura<select value={crmDraft.lead_temperature || "cold"} onChange={(event) => updateCrmDraft("lead_temperature", event.target.value)}><option value="cold">Frio</option><option value="warm">Tibio</option><option value="hot">Caliente</option></select></label>
                      <label>SLA<input type="datetime-local" value={crmDraft.sla_due_at || ""} onChange={(event) => updateCrmDraft("sla_due_at", event.target.value)} /></label>
                      <button type="button" onClick={recomputeSelectedScore}>Recalcular score</button>
                    </div>
                    <div className="crm-predictive-card">
                      <div className="ai-context-head"><strong>Inteligencia predictiva</strong><small>{selectedPredictive.source || "crm_baseline"}</small></div>
                      <div className="predictive-mini-grid">
                        <span><b>{number(selectedPredictive.conversion_probability || selectedPredictive.lead_score || 0)}%</b>Conversion</span>
                        <span><b>{number(selectedPredictive.engagement_score || 0)}</b>Engagement</span>
                        <span className={Number(selectedPredictive.churn_risk || 0) >= 70 ? "danger" : ""}><b>{number(selectedPredictive.churn_risk || 0)}</b>Churn</span>
                      </div>
                      <p>{selectedPredictive.recommended_action || "Genera predicciones para obtener accion recomendada."}</p>
                      <small>{selectedPredictive.best_channel || selectedConversation.channel || "canal"} / {selectedPredictive.best_window || "09:00-11:00 local"} / {selectedPredictive.frequency || "frecuencia sugerida"}</small>
                      <div className="predictive-buttons">
                        {["lead_scoring", "churn_prediction", "smart_remarketing"].map((type) => (
                          <button type="button" key={type} onClick={() => runSelectedPredictiveInsight(type)} disabled={Boolean(predictiveBusy)}>
                            {predictiveBusy === type ? "..." : predictionTypeLabel(type)}
                          </button>
                        ))}
                      </div>
                    </div>
                    <div className="inbox-analysis-card">
                      <div className="ai-context-head">
                        <strong>Panel de analisis Inbox</strong>
                        <div className="mini-action-row">
                          <button type="button" onClick={() => loadConversationMultimodalEvents(selectedConversation.id)}>Refrescar</button>
                          <button type="button" onClick={syncConversationMultimodalMemory} disabled={webSearchBusy === "memory-sync"}>{webSearchBusy === "memory-sync" ? "..." : "Sincronizar"}</button>
                        </div>
                      </div>
                      <div className="inbox-analysis-metrics">
                        <span><b>{number(inboxAnalysisCounts.voice)}</b>Voz</span>
                        <span><b>{number(inboxAnalysisCounts.vision)}</b>Visual</span>
                        <span><b>{number(inboxAnalysisCounts.memory)}</b>Memoria</span>
                        <span><b>{number(inboxAnalysisCounts.approvedReferences)}</b>Aprobadas</span>
                      </div>
                      <div className="inbox-analysis-stream">
                        {inboxVoiceInsights.map((item) => (
                          <div className="analysis-signal voice" key={`voice-${item.message.id}`}>
                            <strong>Voz: {item.intent}</strong>
                            <span>{item.sentiment} / urgencia {item.urgency} / {item.confidence}% conf.</span>
                            <p>{item.summary}</p>
                          </div>
                        ))}
                        {inboxVisionInsights.map((item) => (
                          <div className="analysis-signal vision" key={`vision-${item.message.id}`}>
                            <strong>Visual: {item.type}</strong>
                            <span>{item.intent} / urgencia {item.urgency} / {item.confidence}% conf.</span>
                            <p>{item.summary}</p>
                          </div>
                        ))}
                        {inboxMemoryHighlights.map((event) => (
                          <div className="analysis-signal memory" key={event.id}>
                            <strong>{event.source}</strong>
                            <span>{event.status}{event.training ? " / training" : ""}{event.rag ? " / RAG" : ""}</span>
                            <p>{event.text}</p>
                          </div>
                        ))}
                        {!inboxVoiceInsights.length && !inboxVisionInsights.length && !inboxMemoryHighlights.length ? <p className="muted-note">Sin analisis multimodal aun. Analiza audios, imagenes o sincroniza memoria para activar señales.</p> : null}
                      </div>
                      <div className="visual-reference-strip">
                        <div className="ai-context-head"><strong>Referencias visuales aprobadas</strong><small>{approvedVisualReferences.length} listas / {pendingVisualReferences.length} pendientes</small></div>
                        {approvedVisualReferences.map(({ result }) => (
                          <div className="visual-reference-item" key={`approved-ref-${result.id}`}>
                            <img src={result.thumbnail_url || result.image_url} alt={result.title || "Referencia visual"} loading="lazy" />
                            <div>
                              <strong>{result.title || "Referencia visual"}</strong>
                              <span>{result.source_name || result.display_url || "fuente externa"}</span>
                              <div className="web-search-actions">
                                <button type="button" onClick={() => useWebSearchReference(result, "draft")} disabled={Boolean(webSearchBusy)}>Usar</button>
                                <button type="button" onClick={() => useWebSearchReference(result, "send")} disabled={Boolean(webSearchBusy) || composerSending}>Enviar</button>
                              </div>
                            </div>
                          </div>
                        ))}
                        {!approvedVisualReferences.length ? <p className="muted-note">Aprueba una imagen segura para poder usarla como referencia visual.</p> : null}
                      </div>
                    </div>
                    <div className="web-search-card">
                      <div className="ai-context-head">
                        <strong>Web/Image Search Intelligence</strong>
                        <button type="button" onClick={() => loadWebSearchRunsForConversation(selectedConversation.id)}>Refrescar</button>
                      </div>
                      <form className="web-search-form" onSubmit={submitWebImageSearch}>
                        <input value={webSearchForm.query} onChange={(event) => setWebSearchForm((prev) => ({ ...prev, query: event.target.value }))} placeholder="Buscar fuente o imagen de referencia..." />
                        <select value={webSearchForm.searchType} onChange={(event) => setWebSearchForm((prev) => ({ ...prev, searchType: event.target.value }))}>
                          <option value="mixed">Web + imagen</option>
                          <option value="web">Solo web</option>
                          <option value="image">Solo imagen</option>
                        </select>
                        <select value={webSearchForm.providerCode} onChange={(event) => setWebSearchForm((prev) => ({ ...prev, providerCode: event.target.value }))}>
                          {SEARCH_API_PROVIDERS.map((provider) => <option key={provider.code} value={provider.code}>{provider.name}</option>)}
                        </select>
                        <button type="submit" className="primary" disabled={webSearchBusy === "search"}>{webSearchBusy === "search" ? "Buscando..." : "Buscar"}</button>
                      </form>
                      <small>{selectedWebSearchCredential.has_secret ? `Proveedor listo: ${selectedWebSearchProvider.name} ${selectedWebSearchCredential.secret_hint || ""}` : `Agrega ${selectedWebSearchProvider.name} en Ajustes > APIs. No se envian resultados automaticamente.`}</small>
                      <div className="web-search-results">
                        {webSearchItems.slice(0, 20).map(({ run, result }) => (
                          <div className={`web-search-result ${result.approval_status || "pending"} ${result.safety_status || ""}`} key={result.id}>
                            {result.thumbnail_url || result.image_url ? <img src={result.thumbnail_url || result.image_url} alt={result.title || "Referencia"} loading="lazy" /> : null}
                            <div>
                              <strong>{result.title || "Fuente externa"}</strong>
                              <span>{result.source_name || result.display_url || run.provider_code} / {result.result_type}</span>
                              {result.snippet ? <p>{result.snippet}</p> : null}
                              {result.url ? <a href={result.url} target="_blank" rel="noreferrer">Abrir fuente</a> : <small>Fuente bloqueada por seguridad: {result.rejected_reason || result.safety_status}</small>}
                              {result.license_label ? <small>Licencia: {result.license_label}</small> : null}
                              <div className="web-search-actions">
                                <span>{result.approval_status === "approved" ? "Aprobada" : result.approval_status === "rejected" ? "Rechazada" : "Pendiente"}</span>
                                <button type="button" onClick={() => reviewWebSearchResult(result, "approved")} disabled={Boolean(webSearchBusy) || result.safety_status === "blocked" || result.approval_status === "approved"}>Aprobar</button>
                                <button type="button" onClick={() => reviewWebSearchResult(result, "rejected")} disabled={Boolean(webSearchBusy) || result.approval_status === "rejected"}>Rechazar</button>
                                <button type="button" onClick={() => useWebSearchReference(result, "draft")} disabled={Boolean(webSearchBusy) || result.safety_status === "blocked"}>{result.approval_status === "approved" ? "Usar" : "Aprobar y usar"}</button>
                                <button type="button" onClick={() => useWebSearchReference(result, "send")} disabled={Boolean(webSearchBusy) || composerSending || result.safety_status === "blocked"}>{result.approval_status === "approved" ? "Enviar" : "Aprobar y enviar"}</button>
                              </div>
                            </div>
                          </div>
                        ))}
                        {webSearchRuns.length === 0 ? <p className="muted-note">Sin busquedas externas para esta conversacion.</p> : null}
                      </div>
                    </div>
                    <label>Nombre<input value={crmDraft.first_name || ""} onChange={(event) => updateCrmDraft("first_name", event.target.value)} placeholder="Ej: Juan" /></label>
                    <label>Apellido<input value={crmDraft.last_name || ""} onChange={(event) => updateCrmDraft("last_name", event.target.value)} placeholder="Ej: Perez" /></label>
                    <label>Ciudad<input value={crmDraft.city || ""} onChange={(event) => updateCrmDraft("city", event.target.value)} /></label>
                    <label>Tipo<select value={crmDraft.customer_type || ""} onChange={(event) => updateCrmDraft("customer_type", event.target.value)}><option value="">Sin definir</option><option value="minorista">Minorista</option><option value="mayorista">Mayorista</option><option value="vip">VIP</option></select></label>
                    <label>Etapa<select value={crmDraft.crm_stage || ""} onChange={(event) => updateCrmDraft("crm_stage", event.target.value)}><option value="">Sin etapa</option>{activePipelineStages.length ? activePipelineStages.map((stage) => <option value={stage.stage_key} key={stage.id || stage.stage_key}>{stage.label}</option>) : <><option value="contactado">Contactado</option><option value="interes">Interes</option><option value="intencion_compra">Intencion compra</option><option value="pago_pendiente">Pago pendiente</option><option value="pago_confirmado">Pago confirmado</option></>}</select></label>
                    <label>Pago<select value={crmDraft.payment_status || ""} onChange={(event) => updateCrmDraft("payment_status", event.target.value)}><option value="">Sin estado</option><option value="pending">Pendiente</option><option value="paid">Pagado</option><option value="failed">Fallido</option></select></label>
                    <label>Intereses<input value={crmDraft.interests || ""} onChange={(event) => updateCrmDraft("interests", event.target.value)} placeholder="dulces, frescos..." /></label>
                    <label>Etiquetas<input value={crmDraft.tags || ""} onChange={(event) => updateCrmDraft("tags", event.target.value)} placeholder="vip, pago pendiente..." /></label>
                    <label>Notas<textarea rows={4} value={crmDraft.notes || ""} onChange={(event) => updateCrmDraft("notes", event.target.value)} /></label>
                    {activeCrmCustomFields.length ? (
                      <div className="crm-custom-card">
                        <div className="ai-context-head"><strong>Campos personalizados</strong><small>{activeCrmCustomFields.length}</small></div>
                        {activeCrmCustomFields.map((field) => {
                          const value = (crmDraft.custom_fields || {})[field.field_key] ?? "";
                          const options = customFieldOptions(field);
                          if (String(field.field_type).toLowerCase() === "boolean") {
                            return <label className="check-row" key={field.id || field.field_key}><input type="checkbox" checked={Boolean(value)} onChange={(event) => updateCrmCustomField(field.field_key, event.target.checked)} /> {field.label}</label>;
                          }
                          if (["select", "multiselect"].includes(String(field.field_type).toLowerCase())) {
                            return <label key={field.id || field.field_key}>{field.label}<select value={Array.isArray(value) ? value[0] || "" : value} onChange={(event) => updateCrmCustomField(field.field_key, event.target.value)}><option value="">Sin valor</option>{options.map((option) => <option value={option} key={option}>{option}</option>)}</select></label>;
                          }
                          return <label key={field.id || field.field_key}>{field.label}<input type={customFieldInputType(field.field_type)} value={value} onChange={(event) => updateCrmCustomField(field.field_key, event.target.value)} /></label>;
                        })}
                      </div>
                    ) : null}
                    <div className="crm-tasks-card">
                      <div className="ai-context-head"><strong>Tareas y follow-up</strong><small>{conversationTasks.filter((task) => ["open", "in_progress"].includes(String(task.status))).length} abiertas</small></div>
                      <form onSubmit={createConversationTask} className="task-mini-form">
                        <input value={taskDraft.title} onChange={(event) => setTaskDraft((prev) => ({ ...prev, title: event.target.value }))} placeholder="Ej: llamar mañana..." />
                        <input type="datetime-local" value={taskDraft.due_at} onChange={(event) => setTaskDraft((prev) => ({ ...prev, due_at: event.target.value }))} />
                        <select value={taskDraft.priority} onChange={(event) => setTaskDraft((prev) => ({ ...prev, priority: event.target.value }))}><option value="normal">Normal</option><option value="high">Alta</option><option value="urgent">Urgente</option><option value="low">Baja</option></select>
                        <button type="submit" disabled={!taskDraft.title.trim()}>Crear</button>
                      </form>
                      <div className="task-list-mini">
                        {conversationTasks.slice(0, 5).map((task) => (
                          <div key={task.id} className={`task-mini ${task.is_overdue ? "overdue" : ""}`}>
                            <div><strong>{task.title}</strong><span>{priorityLabel(task.priority)}{task.due_at ? ` / ${compactDateTimeLabel(task.due_at)}` : ""}</span></div>
                            {task.status !== "done" ? <button type="button" onClick={() => patchConversationTask(task.id, { status: "done" })}>✓</button> : <small>Lista</small>}
                          </div>
                        ))}
                        {conversationTasks.length === 0 ? <p className="muted-note">Sin tareas para esta conversacion.</p> : null}
                      </div>
                    </div>
                    <div className="crm-dedupe-card">
                      <div className="ai-context-head"><strong>Duplicados posibles</strong><small>{dedupeCandidates.length}</small></div>
                      {dedupeCandidates.slice(0, 4).map((candidate) => (
                        <div className="dedupe-row" key={candidate.id}>
                          <div><strong>{candidate.display_name || candidate.phone || candidate.external_contact_id}</strong><span>{candidate.channel} / score {number(candidate.match_score)} / {(candidate.reasons || []).join(", ")}</span></div>
                          <button type="button" onClick={() => mergeDedupeCandidate(candidate.id)} disabled={mergingCustomerId === candidate.id}>{mergingCustomerId === candidate.id ? "..." : "Fusionar"}</button>
                        </div>
                      ))}
                      {dedupeCandidates.length === 0 ? <p className="muted-note">Sin duplicados evidentes por telefono, nombre o email.</p> : null}
                    </div>
                    <div className="crm-timeline-card">
                      <div className="ai-context-head"><strong>Timeline completo</strong><small>{conversationTimeline.length}</small></div>
                      {conversationTimeline.slice(0, 8).map((event) => (
                        <div className={`timeline-event ${event.event_type || ""}`} key={`${event.event_type}-${event.id}-${event.occurred_at}`}>
                          <strong>{event.title || event.event_type}</strong>
                          <span>{compactDateTimeLabel(event.occurred_at || event.created_at)}</span>
                          {event.description ? <small>{event.description}</small> : null}
                        </div>
                      ))}
                      {conversationTimeline.length === 0 ? <p className="muted-note">Aun no hay actividad historica para esta conversacion.</p> : null}
                    </div>
                    <div className="ai-context-card">
                      <div className="ai-context-head"><strong>Contexto IA</strong><button type="button" onClick={() => loadConversationMemory(selectedConversation.id)}>Refrescar</button></div>
                      <p>{conversationMemory?.summary || "La IA aun no ha construido memoria para esta conversacion."}</p>
                      <div className="ai-facts">
                        {Object.entries(conversationMemory?.facts_json || {}).filter(([, value]) => String(value || "").trim()).slice(0, 8).map(([key, value]) => <span key={key}><b>{key}</b>{String(value)}</span>)}
                      </div>
                      <button type="button" onClick={processSelectedWithAi}>Procesar con IA ahora</button>
                    </div>
                    <div className="message-status-card">
                      <div className="ai-context-head"><strong>Estados Meta</strong><span>{messageStatusEvents.length}</span></div>
                      {messageStatusEvents.slice(0, 6).map((event) => (
                        <div className={`status-event ${event.status || ""}`} key={event.id}>
                          <strong>{event.status}</strong>
                          <span>{compactDateTimeLabel(event.occurred_at || event.created_at)}</span>
                          {event.error ? <small>{event.error}</small> : null}
                        </div>
                      ))}
                      {messageStatusEvents.length === 0 ? <p className="muted-note">Aun no hay eventos de estado para esta conversacion.</p> : null}
                    </div>
                    <label className="check-row"><input type="checkbox" checked={Boolean(crmDraft.takeover)} onChange={(event) => updateCrmDraft("takeover", event.target.checked)} /> Takeover humano</label>
                    <button type="button" className="primary" onClick={saveSelectedCrm} disabled={savingCrm}>{savingCrm ? "Guardando..." : "Guardar ficha"}</button>
                  </div>
                ) : <div className="empty">Selecciona una conversacion para ver la ficha CRM.</div>}
              </aside>
            ) : null}
          </section>
        ) : activeView === "customers" ? (
          <CrmPanel apiCall={apiCall} showStatus={showStatus} crmConfig={crmConfig} onConfigChange={() => loadCrmConfig(true)} onOpenInbox={(customer) => { setActiveView("inbox"); loadMessages(customer); }} />
        ) : activeView === "labels" ? (
          <LabelsPanel apiCall={apiCall} showStatus={showStatus} onGoCampaigns={() => setActiveView("campaigns")} />
        ) : activeView === "campaigns" ? (
          <CampaignsPanel apiCall={apiCall} showStatus={showStatus} apiBase={API_BASE} accessToken={accessToken} features={featureFlags} />
        ) : activeView === "broadcast" ? (
          <BroadcastPanel apiCall={apiCall} showStatus={showStatus} onGoCampaigns={() => setActiveView("campaigns")} />
        ) : activeView === "ads" ? (
          <AdsPanel apiCall={apiCall} showStatus={showStatus} onConnectMeta={() => { setActiveView("settings"); setSettingsTab("channels"); }} onOpenInbox={(conversation) => { setActiveView("inbox"); loadMessages(conversation); }} />
        ) : activeView === "agents" ? (
          <AiAgentsPanel
            apiCall={apiCall}
            showStatus={showStatus}
            onOpenAdvisor={() => setAdvisorOpen(true)}
            onOpenSettings={() => { setActiveView("settings"); setSettingsTab("apis"); }}
            onMilestone={showMilestoneOnce}
          />
        ) : activeView === "intelligence" ? (
          <IntelligencePanel apiCall={apiCall} showStatus={showStatus} tenantId={me.tenant_id || ""} />
        ) : activeView === "ecosystem" ? (
          <AiEcosystemPanel apiCall={apiCall} showStatus={showStatus} />
        ) : activeView === "composer" ? (
          <WorkflowComposerPanel apiCall={apiCall} showStatus={showStatus} />
        ) : activeView === "trust" ? (
          <TrustCenterPanel apiCall={apiCall} showStatus={showStatus} />
        ) : (
          <section className="settings-page">
            <div className="settings-tabs glass-card">{SETTINGS_TABS.map(([key,label]) => <button key={key} type="button" className={settingsTab === key ? "active" : ""} onClick={() => setSettingsTab(key)}>{label}</button>)}</div>
            {settingsTab === "ia" ? (
              <div className="settings-grid">
                <article className="panel glass-card">
                  <div className="panel-head"><h2>Ajustes IA</h2><span>modelo vinculado desde APIs</span></div>
                  <label className="check-row"><input type="checkbox" checked={aiConfig.enabled} onChange={(event) => setAiConfig((prev) => ({ ...prev, enabled: event.target.checked }))} /> IA habilitada</label>
                  <div className="form-grid two">
                    <label>Proveedor
                      <select value={aiConfig.provider} onChange={(event) => setAiConfig((prev) => ({ ...prev, provider: event.target.value }))}>
                        {AI_API_PROVIDERS.map((provider) => <option key={provider.code} value={provider.code}>{provider.name}</option>)}
                      </select>
                    </label>
                    <div className={`linked-model-card ${activeAiModel ? "ready" : "missing"}`}>
                      <span>Modelo activo</span>
                      <strong>{activeAiModel || "Sin modelo seleccionado"}</strong>
                      <small>{selectedAiCredential.has_secret ? `API guardada ${selectedAiCredential.secret_hint || "cifrada"}` : `Agrega la API key de ${selectedAiProvider?.name || "IA"} en Ajustes > APIs`}</small>
                    </div>
                  </div>
                  <label>System prompt<textarea rows={7} value={aiConfig.systemPrompt} onChange={(event) => setAiConfig((prev) => ({ ...prev, systemPrompt: event.target.value }))} /></label>
                  <div className="form-grid two">
                    <label>Max tokens<input value={aiConfig.maxTokens} onChange={(event) => setAiConfig((prev) => ({ ...prev, maxTokens: event.target.value }))} /></label>
                    <label>Temperatura<input value={aiConfig.temperature} onChange={(event) => setAiConfig((prev) => ({ ...prev, temperature: event.target.value }))} /></label>
                    <label>Fallback provider
                      <select value={aiConfig.fallbackProvider} onChange={(event) => setAiConfig((prev) => ({ ...prev, fallbackProvider: event.target.value }))}>
                        {AI_API_PROVIDERS.map((provider) => <option key={provider.code} value={provider.code}>{provider.name}</option>)}
                      </select>
                    </label>
                    <div className={`linked-model-card ${activeFallbackModel ? "ready" : "missing"}`}>
                      <span>Modelo fallback</span>
                      <strong>{activeFallbackModel || "Sin modelo fallback"}</strong>
                      <small>{selectedFallbackCredential.has_secret ? `API guardada ${selectedFallbackCredential.secret_hint || "cifrada"}` : "Configura el proveedor fallback en APIs si quieres respaldo automatico."}</small>
                    </div>
                  </div>
                  <p className="soft-copy">Los modelos se eligen en Ajustes &gt; APIs con Cargar modelos y Guardar modelo. Aqui solo se selecciona el proveedor y el comportamiento.</p>
                  <h3>Ritmo humano</h3>
                  <label className="check-row"><input type="checkbox" checked={Boolean(aiConfig.humanReplyStyle)} onChange={(event) => setAiConfig((prev) => ({ ...prev, humanReplyStyle: event.target.checked }))} /> Respuestas breves sin perder contexto</label>
                  <label className="check-row"><input type="checkbox" checked={Boolean(aiConfig.humanReplySplitting)} onChange={(event) => setAiConfig((prev) => ({ ...prev, humanReplySplitting: event.target.checked }))} /> Fragmentar respuestas largas en mensajes naturales</label>
                  <div className="form-grid four">
                    <label>Espera antes de responder (seg)<input type="number" min="0" value={aiConfig.cooldown} onChange={(event) => setAiConfig((prev) => ({ ...prev, cooldown: event.target.value }))} /></label>
                    <label>Typing antes del primer envio (ms)<input type="number" min="0" value={aiConfig.typingDelay} onChange={(event) => setAiConfig((prev) => ({ ...prev, typingDelay: event.target.value }))} /></label>
                    <label>Chars por mensaje<input type="number" min="0" value={aiConfig.chunks} onChange={(event) => setAiConfig((prev) => ({ ...prev, chunks: event.target.value }))} /></label>
                    <label>Delay entre fragmentos (ms)<input type="number" min="0" value={aiConfig.delayBetween} onChange={(event) => setAiConfig((prev) => ({ ...prev, delayBetween: event.target.value }))} /></label>
                    <label>Max tokens salida<input type="number" min="200" value={aiConfig.replyMaxOutputTokens} onChange={(event) => setAiConfig((prev) => ({ ...prev, replyMaxOutputTokens: event.target.value, maxTokens: event.target.value }))} /></label>
                    <label>Mensajes recientes<input type="number" min="4" max="24" value={aiConfig.recentMessageLimit} onChange={(event) => setAiConfig((prev) => ({ ...prev, recentMessageLimit: event.target.value }))} /></label>
                    <label>Chars por mensaje historico<input type="number" min="200" value={aiConfig.messageContextChars} onChange={(event) => setAiConfig((prev) => ({ ...prev, messageContextChars: event.target.value }))} /></label>
                  </div>
                  <label className="check-row"><input type="checkbox" checked={Boolean(aiConfig.typingIndicator)} onChange={(event) => setAiConfig((prev) => ({ ...prev, typingIndicator: event.target.checked }))} /> Mostrar “escribiendo...” en WhatsApp cuando Meta lo permita</label>
                  <div className="panel-actions"><button type="button" className="primary" onClick={saveAiLocal}>Guardar ajustes</button><button type="button" onClick={() => setAiTesterOpen(true)}>Probar IA</button></div>
                </article>
                <article className="panel glass-card">
                  <div className="panel-head"><h2>Voz / TTS WhatsApp</h2><span>humanizacion</span></div>
                  <label className="check-row"><input type="checkbox" checked={aiConfig.voiceEnabled} onChange={(event) => setAiConfig((prev) => ({ ...prev, voiceEnabled: event.target.checked }))} /> Voz habilitada</label>
                  <label className="check-row"><input type="checkbox" checked={aiConfig.preferVoice} onChange={(event) => setAiConfig((prev) => ({ ...prev, preferVoice: event.target.checked }))} /> Preferir nota de voz</label>
                  <div className="form-grid two">
                    <label>Proveedor TTS
                      <select value={aiConfig.ttsProvider} onChange={(event) => setAiConfig((prev) => ({ ...prev, ttsProvider: event.target.value }))}>
                        {TTS_API_PROVIDERS.map((provider) => <option key={provider.code} value={provider.code}>{provider.name}</option>)}
                      </select>
                    </label>
                    <div className={`linked-model-card ${activeTtsModel ? "ready" : "missing"}`}>
                      <span>Voz/modelo activo</span>
                      <strong>{activeTtsModel || "Sin voz seleccionada"}</strong>
                      <small>{selectedTtsCredential.has_secret ? `Credencial guardada ${selectedTtsCredential.secret_hint || "cifrada"}` : `Agrega ${selectedTtsProvider?.name || "TTS"} en Ajustes > APIs`}</small>
                    </div>
                    <label>Analisis de audios
                      <select value={aiConfig.voiceAnalysisProvider} onChange={(event) => setAiConfig((prev) => ({ ...prev, voiceAnalysisProvider: event.target.value }))}>
                        {AI_API_PROVIDERS.filter((provider) => provider.code === "google").map((provider) => <option key={provider.code} value={provider.code}>{provider.name}</option>)}
                      </select>
                    </label>
                    <div className={`linked-model-card ${activeVoiceAnalysisModel ? "ready" : "missing"}`}>
                      <span>Modelo Voice Intelligence</span>
                      <strong>{activeVoiceAnalysisModel || "Gemini recomendado"}</strong>
                      <small>{selectedVoiceAnalysisCredential.has_secret ? `API guardada ${selectedVoiceAnalysisCredential.secret_hint || "cifrada"}` : "Configura Google / Gemini en APIs para transcribir audio real."}</small>
                    </div>
                    <label>Vision Intelligence
                      <select value={aiConfig.visionAnalysisProvider} onChange={(event) => setAiConfig((prev) => ({ ...prev, visionAnalysisProvider: event.target.value }))}>
                        {VISION_API_PROVIDERS.map((provider) => <option key={provider.code} value={provider.code}>{provider.name}</option>)}
                      </select>
                    </label>
                    <div className={`linked-model-card ${activeVisionAnalysisModel ? "ready" : "missing"}`}>
                      <span>Modelo imagen/documento</span>
                      <strong>{activeVisionAnalysisModel || "Gemini recomendado"}</strong>
                      <small>{selectedVisionAnalysisCredential.has_secret ? `API guardada ${selectedVisionAnalysisCredential.secret_hint || "cifrada"}` : "Agrega Google, OpenRouter o Kimi en APIs. Los documentos usan Gemini como ruta segura."}</small>
                    </div>
                    <label>Busqueda web/imagen
                      <select value={aiConfig.webImageSearchProvider} onChange={(event) => { setAiConfig((prev) => ({ ...prev, webImageSearchProvider: event.target.value })); setWebSearchForm((prev) => ({ ...prev, providerCode: event.target.value })); }}>
                        {SEARCH_API_PROVIDERS.map((provider) => <option key={provider.code} value={provider.code}>{provider.name}</option>)}
                      </select>
                    </label>
                    <div className={`linked-model-card ${selectedWebSearchCredential.has_secret ? "ready" : "missing"}`}>
                      <span>Fuentes externas</span>
                      <strong>{selectedWebSearchProvider.name}</strong>
                      <small>{selectedWebSearchCredential.has_secret ? `API guardada ${selectedWebSearchCredential.secret_hint || "cifrada"}` : "Agrega la API key en Ajustes > APIs. Las fuentes requieren aprobacion humana."}</small>
                    </div>
                    <label>Voice ID manual opcional<input value={aiConfig.voiceId} onChange={(event) => setAiConfig((prev) => ({ ...prev, voiceId: event.target.value }))} /></label>
                    <label>Nombre visible de voz<input value={aiConfig.voiceName} onChange={(event) => setAiConfig((prev) => ({ ...prev, voiceName: event.target.value }))} /></label>
                  </div>
                  <label>Prompt de voz<textarea rows={4} value={aiConfig.voicePrompt} onChange={(event) => setAiConfig((prev) => ({ ...prev, voicePrompt: event.target.value }))} /></label>
                </article>
                <article className="panel glass-card">
                  <div className="panel-head"><h2>Knowledge Base</h2><span>fuentes</span></div>
                  <p className="soft-copy">Estas fuentes se inyectan como contexto para la IA. Sirven para politicas, catalogos, preguntas frecuentes, precios y procesos internos.</p>
                  <div className="kb-health-grid">
                    <div><span>Estado RAG</span><strong>{knowledgeHealth?.status || "sin datos"}</strong><small>{number(knowledgeHealth?.totals?.active_sources || 0)} fuentes activas</small></div>
                    <div><span>Fragmentos</span><strong>{number(knowledgeHealth?.totals?.chunks || 0)}</strong><small>chunks indexados</small></div>
                    <div><span>Vectorizados</span><strong>{number(knowledgeHealth?.totals?.vectorized_chunks || 0)}</strong><small>{knowledgeHealth?.retrieval_mode || "sparse_vector_lexical"}</small></div>
                    <div><span>Calidad RAG</span><strong>{number(knowledgeHealth?.quality?.avg_quality_score || 0)}%</strong><small>{number(knowledgeHealth?.quality?.passed_evaluations || 0)} evaluaciones aprobadas</small></div>
                    <div><span>Errores</span><strong>{number(knowledgeHealth?.totals?.error_sources || 0)}</strong><small>fuentes con problema</small></div>
                  </div>
                  <div className="inline-form compact"><select><option>Mostrar: Todos</option></select><button type="button" onClick={loadKnowledgeSources}>Refrescar</button><button type="button" onClick={reindexAllKnowledge} disabled={knowledgeUploading}>Reindexar todo</button></div>
                  <input ref={knowledgeFileRef} className="composer-file-input" type="file" accept=".txt,.md,.csv,.json,.pdf,text/plain,application/pdf" onChange={(event) => uploadKnowledgeFile(event.target.files?.[0])} />
                  <div
                    className="upload-zone actionable"
                    role="button"
                    tabIndex={0}
                    onClick={() => knowledgeFileRef.current?.click()}
                    onKeyDown={(event) => { if (event.key === "Enter") knowledgeFileRef.current?.click(); }}
                    onDragOver={(event) => event.preventDefault()}
                    onDrop={(event) => { event.preventDefault(); uploadKnowledgeFile(event.dataTransfer.files?.[0]); }}
                  >
                    {knowledgeUploading ? "Procesando fuente..." : "Arrastra PDF/TXT/CSV aqui o haz clic para subir"}
                  </div>
                  <form className="kb-search-form" onSubmit={searchKnowledgeSources}>
                    <label>Probar recuperacion RAG
                      <input
                        placeholder="Ej: politicas de envio, garantia, precio de producto..."
                        value={knowledgeSearch.query}
                        onChange={(event) => setKnowledgeSearch((prev) => ({ ...prev, query: event.target.value }))}
                      />
                    </label>
                    <button type="submit" className="primary" disabled={knowledgeSearching}>{knowledgeSearching ? "Buscando..." : "Buscar contexto"}</button>
                  </form>
                  {knowledgeSearch.searched ? (
                    <div className="kb-rag-results">
                      <div className="kb-rag-summary"><strong>{number(knowledgeSearch.results.length)} fragmentos encontrados</strong><span>Confianza {number(knowledgeSearch.confidence)}% / {knowledgeSearch.retrievalMode || "sparse_vector_lexical"}</span></div>
                      {knowledgeSearch.results.slice(0, 4).map((item) => (
                        <div className="kb-rag-result" key={item.chunk_id}>
                          <strong>{item.title}</strong>
                          <span>{item.source_label || item.filename || item.url || "Fuente interna"} / score {item.score} / vector {number(item.vector_score || 0)}</span>
                          {Array.isArray(item.matched_terms) && item.matched_terms.length ? <small>Coincidencias: {item.matched_terms.slice(0, 8).join(", ")}</small> : null}
                          <p>{item.content}</p>
                        </div>
                      ))}
                      {knowledgeSearch.citations.length ? <div className="kb-citations"><strong>Citas internas</strong>{knowledgeSearch.citations.slice(0, 5).map((citation, index) => <span key={`${citation.chunk_id || index}`}>Fuente {index + 1}: {citation.title} / score {citation.score}</span>)}</div> : null}
                      {knowledgeSearch.results.length === 0 ? <div className="empty">No se encontro contexto. Revisa que haya fuentes activas o reindexa.</div> : null}
                    </div>
                  ) : null}
                  <form className="kb-eval-form" onSubmit={runKnowledgeEvaluation}>
                    <h3>Evaluacion de calidad RAG</h3>
                    <label>Pregunta de prueba<input placeholder="Ej: que garantia tiene este producto" value={knowledgeEvalForm.query} onChange={(event) => setKnowledgeEvalForm((prev) => ({ ...prev, query: event.target.value }))} /></label>
                    <label>Respuesta esperada opcional<textarea rows={3} placeholder="Datos que deberian aparecer en el contexto recuperado" value={knowledgeEvalForm.expectedAnswer} onChange={(event) => setKnowledgeEvalForm((prev) => ({ ...prev, expectedAnswer: event.target.value }))} /></label>
                    <label>Fuentes esperadas opcionales<textarea rows={2} placeholder="Una fuente por linea o separadas por coma" value={knowledgeEvalForm.expectedSources} onChange={(event) => setKnowledgeEvalForm((prev) => ({ ...prev, expectedSources: event.target.value }))} /></label>
                    <button type="submit" className="primary" disabled={knowledgeEvaluating}>{knowledgeEvaluating ? "Evaluando..." : "Evaluar RAG"}</button>
                  </form>
                  {knowledgeEvaluations.length ? (
                    <div className="kb-eval-list">
                      {knowledgeEvaluations.map((item) => (
                        <div key={item.id} className={item.passed ? "kb-eval-row ok" : "kb-eval-row warn"}>
                          <strong>{item.query}</strong>
                          <span>{item.answerability} / calidad {number(item.quality_score)}% / confianza {number(item.confidence)}%</span>
                          <small>{compactDateTimeLabel(item.created_at)} / {item.passed ? "aprobada" : "requiere ajuste"}</small>
                        </div>
                      ))}
                    </div>
                  ) : null}
                  <h3>Fuentes Web</h3>
                  <form className="kb-url-form" onSubmit={addKnowledgeUrl}>
                    <label>URL<input placeholder="https://tutienda.com/pagina-o-blog" value={knowledgeUrlForm.url} onChange={(event) => setKnowledgeUrlForm((prev) => ({ ...prev, url: event.target.value }))} /></label>
                    <label>Titulo opcional<input placeholder="Politicas de envio" value={knowledgeUrlForm.title} onChange={(event) => setKnowledgeUrlForm((prev) => ({ ...prev, title: event.target.value }))} /></label>
                    <label>Notas opcionales<input placeholder="Prioridad, uso interno, version..." value={knowledgeUrlForm.notes} onChange={(event) => setKnowledgeUrlForm((prev) => ({ ...prev, notes: event.target.value }))} /></label>
                    <button type="submit" className="primary" disabled={knowledgeUploading}>{knowledgeUploading ? "Agregando..." : "Anadir fuente web"}</button>
                  </form>
                  <div className="kb-source-list">
                    {knowledgeSources.map((source) => (
                      <div className="kb-source" key={source.id}>
                        <div>
                          <strong>{source.title || source.filename || source.url}</strong>
                          <span>{source.source_type} / {number(source.content_chars)} chars / {number(source.chunk_count)} chunks / {source.status || "sin estado"} / {compactDateTimeLabel(source.updated_at)}</span>
                          {source.metadata_json?.parser ? <small>Parser: {source.metadata_json.parser}</small> : null}
                          {source.error ? <small className="danger-text">{source.error}</small> : <small>Indexado {source.last_indexed_at ? compactDateTimeLabel(source.last_indexed_at) : "pendiente"}</small>}
                          <p>{source.content_preview}</p>
                        </div>
                        <div className="row-actions">
                          <button type="button" onClick={() => reindexKnowledgeSource(source.id)}>Reindexar</button>
                          <button type="button" onClick={() => deleteKnowledgeSource(source.id)}>Eliminar</button>
                        </div>
                      </div>
                    ))}
                    {knowledgeSources.length === 0 ? <div className="empty">Aun no hay fuentes. Sube un TXT/PDF o agrega una URL para que la IA tenga contexto adicional.</div> : null}
                  </div>
                </article>
              </div>
            ) : null}
            {settingsTab === "vertical" ? (
              <div className="settings-stack vertical-settings">
                <article className="panel glass-card vertical-hero">
                  <div className="panel-head">
                    <div><h2>Verticalizacion</h2><span>{verticalState?.tenant?.industry_code || activeCompany?.industry_code || "general"}</span></div>
                    <button type="button" onClick={() => loadVerticalState(false)}>Refrescar</button>
                  </div>
                  <p className="soft-copy">El pack de industria ajusta pipeline CRM, campos comerciales, segmentos, plantillas, triggers inactivos, flows draft, KPIs y agentes recomendados para la empresa activa.</p>
                  <div className="vertical-current">
                    <div><span>Industria actual</span><strong>{verticalState?.current_pack?.label || selectedVerticalPack?.label || "General"}</strong><small>{verticalState?.current_pack?.description || selectedVerticalPack?.description}</small></div>
                    <div><span>Pack aplicado</span><strong>{verticalState?.tenant?.vertical_pack_applied_at ? compactDateTimeLabel(verticalState.tenant.vertical_pack_applied_at) : "pendiente"}</strong><small>Version {verticalState?.tenant?.vertical_pack_version || selectedVerticalPack?.pack_version || 1}</small></div>
                    <div><span>Automatizaciones</span><strong>{number(verticalState?.kpis?.active_triggers || 0)} activas</strong><small>{number(verticalState?.kpis?.triggers || 0)} triggers / {number(verticalState?.kpis?.flows || 0)} flows</small></div>
                  </div>
                </article>
                <div className="vertical-layout">
                  <article className="panel glass-card">
                    <div className="panel-head"><h2>Aplicar pack</h2><span>{selectedVerticalPack?.label}</span></div>
                    <label>Industria
                      <select value={verticalApply.industry_code} onChange={(event) => setVerticalApply((prev) => ({ ...prev, industry_code: event.target.value }))}>
                        {verticalPacks.map((pack) => <option key={pack.code} value={pack.code}>{pack.label}</option>)}
                      </select>
                    </label>
                    <p className="soft-copy">{selectedVerticalPack?.description}</p>
                    <div className="vertical-counts">
                      {Object.entries(selectedVerticalPack?.counts || {}).map(([key, value]) => <span key={key}><strong>{number(value)}</strong>{key.replaceAll("_", " ")}</span>)}
                    </div>
                    <label className="check-row"><input type="checkbox" checked={Boolean(verticalApply.create_agents)} onChange={(event) => setVerticalApply((prev) => ({ ...prev, create_agents: event.target.checked }))} /> Crear agentes recomendados como borradores si el plan lo permite</label>
                    <div className="panel-actions"><button type="button" className="primary" onClick={applyVerticalPack} disabled={verticalBusy}>{verticalBusy ? "Aplicando..." : "Aplicar vertical"}</button><button type="button" onClick={() => { setActiveView("agents"); setSettingsTab("ia"); }}>Ver agentes</button></div>
                    <div className="vertical-agents">
                      <strong>Agentes sugeridos</strong>
                      {(selectedVerticalPack?.agent_types || []).map((agentType) => <span key={agentType}>{agentType}</span>)}
                    </div>
                  </article>
                  <article className="panel glass-card">
                    <div className="panel-head"><h2>KPIs verticales</h2><span>tenant activo</span></div>
                    <div className="vertical-kpis">
                      {Object.entries(verticalState?.kpis || {}).map(([key, value]) => <div key={key}><strong>{number(value)}</strong><span>{key.replaceAll("_", " ")}</span></div>)}
                    </div>
                    <h3>KPIs esperados del pack</h3>
                    <div className="vertical-chip-list">{(selectedVerticalPack?.kpis || []).map((item) => <span key={item}>{item.replaceAll("_", " ")}</span>)}</div>
                  </article>
                  <article className="panel glass-card">
                    <div className="panel-head"><h2>Historial</h2><span>{number(verticalState?.last_applications?.length || 0)}</span></div>
                    <div className="vertical-history">
                      {(verticalState?.last_applications || []).map((item) => <div key={item.id}><strong>{item.industry_code}</strong><span>Version {item.pack_version} / agentes {item.created_agents ? "solicitados" : "no creados"}</span><small>{compactDateTimeLabel(item.created_at)}</small></div>)}
                      {!(verticalState?.last_applications || []).length ? <p className="empty">Aun no hay aplicaciones de pack registradas.</p> : null}
                    </div>
                  </article>
                </div>
              </div>
            ) : null}
            {settingsTab === "channels" ? (
              <div className="settings-stack channels-settings">
                <article className="panel glass-card integration-card">
                  <div className="panel-head">
                    <div>
                      <h2>Meta WhatsApp Cloud</h2>
                      <span>credenciales cifradas, WABA y numero activo</span>
                    </div>
                    <button type="button" onClick={loadIntegrations}>Refrescar</button>
                  </div>
                  <p className="soft-copy">Pega el token permanente una sola vez. Scentra lo cifra en backend y luego solo muestra una pista, nunca el token completo en el navegador.</p>
                  {selectedIntegrationForForm ? (
                    <div className="current-integration-strip">
                      <div>
                        <strong>Integracion actual: {selectedIntegrationForForm.provider} / {selectedIntegrationForForm.channel}</strong>
                        <span>{selectedIntegrationForForm.status} / {selectedIntegrationConfig.dispatch_mode || "stub"} - Phone {selectedIntegrationConfig.phone_number_id || "-"} - WABA {selectedIntegrationConfig.business_account_id || "-"}</span>
                      </div>
                      <div className="row-actions">
                        <button type="button" className="primary" onClick={() => editIntegration(selectedIntegrationForForm)}>Cargar datos para editar</button>
                        <button type="button" onClick={() => openIntegrationSecretModal(selectedIntegrationForForm)}>Actualizar token</button>
                        <button type="button" className="danger-button" onClick={() => deleteIntegration(selectedIntegrationForForm)}>Eliminar</button>
                      </div>
                    </div>
                  ) : null}
                  <form className="meta-grid" onSubmit={saveIntegration}>
                    <label>Proveedor
                      <select value={integrationForm.provider} disabled onChange={(event) => setIntegrationForm((prev) => ({ ...prev, provider: event.target.value }))}>
                        <option value="meta">Meta</option>
                      </select>
                    </label>
                    <label>Canal
                      <select value={integrationForm.channel} disabled onChange={(event) => setIntegrationForm((prev) => ({ ...prev, channel: event.target.value }))}>
                        <option value="whatsapp">WhatsApp</option>
                      </select>
                    </label>
                    <label>Estado
                      <select value={integrationForm.status} onChange={(event) => setIntegrationForm((prev) => ({ ...prev, status: event.target.value }))}>
                        <option value="connected">Connected</option>
                        <option value="disconnected">Disconnected</option>
                        <option value="paused">Paused</option>
                      </select>
                    </label>
                    <label>Modo envio
                      <select value={integrationForm.dispatch_mode} onChange={(event) => setIntegrationForm((prev) => ({ ...prev, dispatch_mode: event.target.value }))}>
                        <option value="stub">Stub local</option>
                        <option value="meta_cloud">Meta Cloud real</option>
                      </select>
                    </label>
                    <label>Phone Number ID
                      <input placeholder="Ej: 731040572984317" value={integrationForm.phone_number_id} onChange={(event) => setIntegrationForm((prev) => ({ ...prev, phone_number_id: event.target.value }))} />
                    </label>
                    <label>WABA ID
                      <input placeholder="WhatsApp Business Account ID" value={integrationForm.business_account_id} onChange={(event) => setIntegrationForm((prev) => ({ ...prev, business_account_id: event.target.value }))} />
                    </label>
                    <label>Meta App ID
                      <input placeholder="ID de la app en Meta" value={integrationForm.app_id} onChange={(event) => setIntegrationForm((prev) => ({ ...prev, app_id: event.target.value }))} />
                    </label>
                    <label>Graph API
                      <input placeholder="v24.0" value={integrationForm.graph_api_version} onChange={(event) => setIntegrationForm((prev) => ({ ...prev, graph_api_version: event.target.value }))} />
                    </label>
                    {!selectedIntegrationForForm ? (
                      <>
                        <label className="token-field">Meta App Secret
                          <input ref={metaAppSecretRef} type="password" placeholder="Opcional: valida x-hub-signature-256" autoComplete="off" spellCheck={false} />
                        </label>
                        <label className="token-field">Token permanente de Meta
                          <input ref={metaAccessTokenRef} type="password" placeholder="Pegar token permanente" autoComplete="off" spellCheck={false} />
                        </label>
                      </>
                    ) : (
                      <div className="secret-summary token-field">
                        <div>
                          <strong>Secretos protegidos</strong>
                          <span>Token: {selectedIntegrationConfig.has_access_token ? `******** ${selectedIntegrationConfig.access_token_hint || ""}` : "sin token"} / App secret: {selectedIntegrationConfig.has_app_secret ? `******** ${selectedIntegrationConfig.app_secret_hint || ""}` : "sin app secret"}</span>
                        </div>
                        <button type="button" onClick={() => openIntegrationSecretModal(selectedIntegrationForForm)}>Actualizar secretos</button>
                      </div>
                    )}
                    <button type="submit" className="primary">Guardar integracion</button>
                  </form>
                  <div className="integration-cards">
                    {integrations.filter((integration) => String(integration.channel || "").toLowerCase() === "whatsapp").map((integration) => {
                      const config = integration.config_json || {};
                      const tokenLabel = config.has_access_token ? `Token guardado ${config.access_token_hint || ""}` : (config.access_token_env ? `Env ${config.access_token_env}` : "Sin token");
                      const appSecretLabel = config.has_app_secret ? `App secret ${config.app_secret_hint || "guardado"}` : "Sin app secret";
                      return (
                        <div className="integration-card-row" key={integration.id}>
                          <div>
                            <strong>{integration.provider} / {integration.channel}</strong>
                            <span>{integration.status} / {config.dispatch_mode || "stub"}</span>
                          </div>
                          <div><span>Phone Number ID</span><strong>{config.phone_number_id || "-"}</strong></div>
                          <div><span>WABA ID</span><strong>{config.business_account_id || "-"}</strong></div>
                          <div><span>Meta App ID</span><strong>{config.app_id || "-"}</strong></div>
                          <div className="integration-marks"><mark>{tokenLabel}</mark><mark>{appSecretLabel}</mark></div>
                          <div className="row-actions">
                            <button type="button" onClick={() => editIntegration(integration)}>Editar</button>
                            <button type="button" onClick={() => openIntegrationSecretModal(integration)}>Actualizar token</button>
                            <button type="button" className="danger-button" onClick={() => deleteIntegration(integration)}>Eliminar</button>
                          </div>
                        </div>
                      );
                    })}
                    {integrations.filter((integration) => String(integration.channel || "").toLowerCase() === "whatsapp").length === 0 ? <div className="empty">Sin integracion WhatsApp configurada.</div> : null}
                  </div>
                </article>

                <article className="panel glass-card">
                  <div className="panel-head">
                    <div>
                      <h2>Verificar numero WhatsApp</h2>
                      <span>sincroniza WABA y registra el Phone Number ID</span>
                    </div>
                    <button type="button" disabled={phoneSyncing} onClick={syncWhatsappPhones}>{phoneSyncing ? "Sincronizando..." : "Sincronizar numeros"}</button>
                  </div>
                  <p className="soft-copy">Scentra consulta los numeros conectados a tu WABA y puede registrar el numero usando el PIN de verificacion en dos pasos configurado en Meta.</p>
                  <form className="inline-form phone-register-form" onSubmit={registerWhatsappPhone}>
                    <select value={phoneRegisterForm.phone_number_id} onChange={(event) => setPhoneRegisterForm((prev) => ({ ...prev, phone_number_id: event.target.value }))}>
                      <option value="">Selecciona un numero sincronizado...</option>
                      {whatsappPhones.map((phone) => <option key={phone.id} value={phone.id}>{phone.display_phone_number || phone.verified_name || phone.id} / {phone.id}</option>)}
                    </select>
                    <input type="password" placeholder="PIN de 6 digitos" inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={phoneRegisterForm.pin} onChange={(event) => setPhoneRegisterForm((prev) => ({ ...prev, pin: event.target.value.replace(/\D/g, "").slice(0, 6) }))} />
                    <button type="submit" className="primary" disabled={phoneSyncing}>Registrar/verificar</button>
                  </form>
                  <div className="phone-grid">
                    {whatsappPhones.map((phone) => (
                      <div className="phone-card" key={phone.id}>
                        <strong>{phone.display_phone_number || phone.verified_name || phone.id}</strong>
                        <span>ID: {phone.id}</span>
                        <span>Nombre verificado: {phone.verified_name || "-"}</span>
                        <span>Calidad: {phone.quality_rating || "-"}</span>
                        <mark>{phone.code_verification_status || phone.name_status || "sin estado"}</mark>
                      </div>
                    ))}
                    {whatsappPhones.length === 0 ? <div className="empty">Aun no hay numeros sincronizados. Guarda WABA ID y token permanente, luego pulsa Sincronizar numeros.</div> : null}
                  </div>
                </article>

                <article className="panel glass-card integration-card">
                  <div className="panel-head">
                    <div>
                      <h2>Instagram Business</h2>
                      <span>{t("meta.facebook.discovery_label")}</span>
                    </div>
                    <button type="button" disabled={instagramBusy} onClick={loadInstagramDiagnostics}>Diagnostics IG</button>
                  </div>
                  <p className="soft-copy">Instagram no usa Phone Number ID ni WABA. Para DMs necesitas una pagina de Facebook conectada a una cuenta Instagram profesional, el Instagram Business Account ID y un Page Access Token con permisos de mensajes. Si tu app Meta no tiene App Review/verificacion, usa el modo manual por cliente.</p>
                  {selectedInstagramIntegration ? (
                    <div className="current-integration-strip">
                      <div>
                        <strong>Instagram actual: {selectedInstagramConfig.instagram_username || selectedInstagramConfig.page_name || "cuenta conectada"}</strong>
                        <span>{selectedInstagramIntegration.status} / {selectedInstagramConfig.dispatch_mode || "instagram_graph"} - Page {selectedInstagramConfig.page_id || "-"} - IG Business {selectedInstagramConfig.instagram_business_account_id || "-"}</span>
                      </div>
                      <div className="row-actions">
                        <button type="button" className="primary" onClick={() => editInstagramIntegration(selectedInstagramIntegration)}>Cargar datos para editar</button>
                        <button type="button" onClick={() => openIntegrationSecretModal(selectedInstagramIntegration)}>Actualizar token</button>
                        <button type="button" onClick={() => loadMetaTokenHealth("instagram")} disabled={instagramBusy}>Salud token</button>
                        <button type="button" onClick={() => refreshMetaToken("instagram")} disabled={instagramBusy}>Renovar</button>
                        <button type="button" className="danger-button" onClick={() => deleteIntegration(selectedInstagramIntegration)}>Eliminar</button>
                      </div>
                    </div>
                  ) : null}
                  {metaTokenHealth.instagram ? (
                    <div className={`token-health-strip ${metaTokenHealth.instagram.ok ? "ok" : "warn"}`}>
                      <strong>{metaTokenHealth.instagram.ok ? "Token Instagram operativo" : `Token Instagram: ${metaTokenHealth.instagram.recommendation || metaTokenHealth.instagram.status || "revisar"}`}</strong>
                      <span>Fuente: {metaTokenHealth.instagram.refresh_source || "-"} / Auto-renovable: {metaTokenHealth.instagram.can_auto_refresh ? "si" : "no"}</span>
                      <small>Page token {metaTokenHealth.instagram.page_access_token?.hint || "-"} {metaTokenHealth.instagram.page_access_token?.expires_at ? `/ vence ${compactDateTimeLabel(metaTokenHealth.instagram.page_access_token.expires_at)}` : ""}</small>
                      {!metaTokenHealth.instagram.can_auto_refresh ? <small>{t("meta.facebook.auto_refresh_hint")}</small> : null}
                    </div>
                  ) : null}
                  <form className="meta-grid instagram-manual-grid" onSubmit={saveInstagramManual}>
                    <label>Estado
                      <select value={instagramForm.status} onChange={(event) => setInstagramForm((prev) => ({ ...prev, status: event.target.value }))}>
                        <option value="connected">Connected</option>
                        <option value="paused">Paused</option>
                        <option value="disconnected">Disconnected</option>
                      </select>
                    </label>
                    <label>Modo envio
                      <select value={instagramForm.dispatch_mode} onChange={(event) => setInstagramForm((prev) => ({ ...prev, dispatch_mode: event.target.value }))}>
                        <option value="instagram_graph">Instagram Graph real</option>
                        <option value="stub">Stub local</option>
                      </select>
                    </label>
                    <label>Page ID
                      <input placeholder="Facebook Page ID conectada a Instagram" value={instagramForm.page_id} onChange={(event) => setInstagramForm((prev) => ({ ...prev, page_id: event.target.value }))} />
                    </label>
                    <label>Instagram Business ID
                      <input placeholder="Instagram Business Account ID" value={instagramForm.instagram_business_account_id} onChange={(event) => setInstagramForm((prev) => ({ ...prev, instagram_business_account_id: event.target.value }))} />
                    </label>
                    <label>Nombre pagina
                      <input placeholder="Ej: Scentra Store" value={instagramForm.page_name} onChange={(event) => setInstagramForm((prev) => ({ ...prev, page_name: event.target.value }))} />
                    </label>
                    <label>Usuario Instagram
                      <input placeholder="@usuario o nombre visible" value={instagramForm.instagram_username} onChange={(event) => setInstagramForm((prev) => ({ ...prev, instagram_username: event.target.value }))} />
                    </label>
                    <label>Business Portfolio ID
                      <input placeholder="Opcional" value={instagramForm.business_id} onChange={(event) => setInstagramForm((prev) => ({ ...prev, business_id: event.target.value }))} />
                    </label>
                    <label>Meta App ID
                      <input placeholder="ID de la app del cliente" value={instagramForm.app_id} onChange={(event) => setInstagramForm((prev) => ({ ...prev, app_id: event.target.value }))} />
                    </label>
                    <label>Graph API
                      <input placeholder="v24.0" value={instagramForm.graph_api_version} onChange={(event) => setInstagramForm((prev) => ({ ...prev, graph_api_version: event.target.value }))} />
                    </label>
                    {!selectedInstagramIntegration ? (
                      <>
                        <label className="token-field">Page Access Token
                          <input ref={instagramPageTokenRef} type="password" placeholder="Token largo/permanente de la pagina" autoComplete="off" spellCheck={false} />
                        </label>
                        <label className="token-field">Meta App Secret
                          <input ref={instagramAppSecretRef} type="password" placeholder="Opcional: valida x-hub-signature-256" autoComplete="off" spellCheck={false} />
                        </label>
                      </>
                    ) : (
                      <div className="secret-summary token-field">
                        <div>
                          <strong>Secretos Instagram protegidos</strong>
                          <span>Page token: {selectedInstagramConfig.has_page_access_token ? `******** ${selectedInstagramConfig.page_access_token_hint || ""}` : "sin token"} / App secret: {selectedInstagramConfig.has_app_secret ? `******** ${selectedInstagramConfig.app_secret_hint || ""}` : "sin app secret"}</span>
                        </div>
                        <button type="button" onClick={() => openIntegrationSecretModal(selectedInstagramIntegration)}>Actualizar secretos</button>
                      </div>
                    )}
                    <button type="submit" className="primary">Guardar Instagram</button>
                  </form>
                  <div className="integration-cards">
                    {selectedInstagramIntegration ? (
                      <div className="integration-card-row instagram-row">
                        <div>
                          <strong>meta / instagram</strong>
                          <span>{selectedInstagramIntegration.status} / {selectedInstagramConfig.dispatch_mode || "instagram_graph"}</span>
                        </div>
                        <div><span>Page ID</span><strong>{selectedInstagramConfig.page_id || "-"}</strong></div>
                        <div><span>IG Business ID</span><strong>{selectedInstagramConfig.instagram_business_account_id || "-"}</strong></div>
                        <div><span>Meta App ID</span><strong>{selectedInstagramConfig.app_id || "-"}</strong></div>
                        <div className="integration-marks"><mark>{selectedInstagramConfig.has_page_access_token ? `Page token ${selectedInstagramConfig.page_access_token_hint || "guardado"}` : "Sin Page token"}</mark><mark>{selectedInstagramConfig.has_app_secret ? `App secret ${selectedInstagramConfig.app_secret_hint || "guardado"}` : "Sin app secret"}</mark></div>
                        <div className="row-actions">
                          <button type="button" onClick={() => editInstagramIntegration(selectedInstagramIntegration)}>Editar</button>
                          <button type="button" onClick={() => openIntegrationSecretModal(selectedInstagramIntegration)}>Actualizar token</button>
                          <button type="button" onClick={() => loadMetaTokenHealth("instagram")} disabled={instagramBusy}>Salud</button>
                          <button type="button" onClick={() => refreshMetaToken("instagram")} disabled={instagramBusy}>Renovar</button>
                          <button type="button" className="danger-button" onClick={() => deleteIntegration(selectedInstagramIntegration)}>Eliminar</button>
                        </div>
                      </div>
                    ) : <div className="empty">Sin integracion Instagram configurada.</div>}
                  </div>
                  <div className="manual-mode-box">
                    <div>
                      <strong>Webhook Instagram para app propia</strong>
                      <span>Crea un endpoint por tenant y copia Callback URL + Verify token en Meta Developers. En Page subscribed_apps se usan: messages, messaging_postbacks, feed y mention.</span>
                    </div>
                    <button type="button" onClick={createInstagramWebhookEndpoint}>Crear endpoint Instagram</button>
                  </div>
                  {lastWebhookSecret?.provider === "instagram" ? (
                    <div className="secret-box">
                      <strong>Valores Instagram visibles una sola vez</strong>
                      <span>Callback URL</span>
                      <div className="secret-value-row"><code>{fullWebhookUrl(lastWebhookSecret.url_path)}</code><button type="button" onClick={() => copyText(fullWebhookUrl(lastWebhookSecret.url_path), "Callback Instagram")}>Copiar URL</button></div>
                      {lastWebhookSecret.verify_token_once ? <><span>Verify token</span><div className="secret-value-row"><code>{lastWebhookSecret.verify_token_once}</code><button type="button" onClick={() => copyText(lastWebhookSecret.verify_token_once, "Verify token Instagram")}>Copiar token</button></div></> : null}
                    </div>
                  ) : null}
                  <div className="oauth-mode-box">
                    <div>
                      <strong>OAuth con la app Meta del cliente</strong>
                      <span>Usa el Meta App ID/App Secret de este tenant para generar user token largo y page token renovable. Descubre paginas, Facebook Messenger e Instagram Business automaticamente.</span>
                    </div>
                    <div className="panel-actions">
                      <button type="button" className="primary" disabled={instagramBusy} onClick={startInstagramOAuth}>{instagramBusy ? "Procesando..." : t("meta.facebook.connect_button")}</button>
                      <button type="button" disabled={instagramBusy || !instagramOAuth.state} onClick={loadInstagramAssets}>Cargar cuentas detectadas</button>
                    </div>
                  </div>
                  {instagramOAuth.callbackUrl ? <div className="callback-box"><code>{instagramOAuth.callbackUrl}</code><button type="button" onClick={() => copyText(instagramOAuth.callbackUrl, "OAuth callback")}>Copiar OAuth callback</button></div> : null}
                  <div className="phone-grid instagram-asset-grid">
                    {(instagramOAuth.assets || []).map((asset) => (
                      <div className={`phone-card ${asset.connected ? "" : "muted"}`} key={`${asset.page_id}-${asset.instagram_business_account_id || "none"}`}>
                        <strong>{asset.instagram_username || "Sin Instagram Business"}</strong>
                        <span>Pagina: {asset.page_name || "-"} / {asset.page_id}</span>
                        <span>Business: {asset.business_name || "-"} / {asset.business_id || "-"}</span>
                        <span>IG Business ID: {asset.instagram_business_account_id || "-"}</span>
                        <mark>{asset.connected ? "Instagram detectado" : "Pagina sin Instagram Business"}</mark>
                        <div className="panel-actions compact-actions">
                          <button type="button" className="primary" disabled={!asset.connected || instagramBusy} onClick={() => connectInstagramAsset(asset)}>Usar Instagram</button>
                          <button type="button" disabled={facebookBusy || !asset.page_id} onClick={() => connectFacebookAsset(asset)}>Usar Facebook</button>
                        </div>
                      </div>
                    ))}
                    {instagramOAuth.state && instagramOAuth.assets.length === 0 ? <div className="empty">{t("meta.facebook.finish_empty")}</div> : null}
                  </div>
                  {instagramDiagnostics ? (
                    <div className={`debug-result ${instagramDiagnostics.ok && instagramDiagnostics.subscription?.final_subscribed ? "ok" : "bad"}`}>
                      <strong>Instagram Diagnostics</strong>
                      <span>{instagramDiagnostics.ok ? `${instagramDiagnostics.instagram_username || "Instagram"} / Page ${instagramDiagnostics.page_id || "-"}` : (instagramDiagnostics.status || "sin conexion")}</span>
                      {instagramDiagnostics.ok ? <small>IG Business ID: {instagramDiagnostics.instagram_business_account_id || "-"} / subscribed_apps: {instagramDiagnostics.subscription?.status || "-"}</small> : null}
                      {instagramDiagnostics.ok ? <small>Webhook global: {instagramDiagnostics.webhook_callback_url || "-"} / Ultimo evento: {instagramDiagnostics.webhook_status?.last_seen_at || "sin eventos"}</small> : null}
                      {instagramDiagnostics.last_message?.id ? <small>Ultimo mensaje: {instagramDiagnostics.last_message.display_name || instagramDiagnostics.last_message.external_contact_id} - {instagramDiagnostics.last_message.last_message_text}</small> : null}
                      {(instagramDiagnostics.subscription_checks || []).slice(0, 3).map((item, idx) => <small key={`${item.created_at}-${idx}`}>{compactDateTimeLabel(item.created_at)} - {item.status} {item.error || item.meta_error_message || ""}</small>)}
                    </div>
                  ) : null}
                </article>

                <article className="panel glass-card integration-card">
                  <div className="panel-head">
                    <div>
                      <h2>Facebook Messenger</h2>
                      <span>DMs, comentarios feed y Page webhooks</span>
                    </div>
                    <button type="button" disabled={facebookBusy} onClick={loadFacebookDiagnostics}>{facebookBusy ? "Revisando..." : "Diagnostics FB"}</button>
                  </div>
                  <p className="soft-copy">Facebook Messenger usa Page ID y Page Access Token. Los DMs entran al Inbox como conversaciones y los comentarios de publicaciones entran a la pestaña Comentarios. Usa un callback Facebook separado del callback Instagram para que cada tenant pueda diagnosticar mejor sus eventos.</p>
                  {selectedFacebookIntegration ? (
                    <div className="current-integration-strip">
                      <div>
                        <strong>Facebook actual: {selectedFacebookConfig.page_name || "pagina conectada"}</strong>
                        <span>{selectedFacebookIntegration.status} / {selectedFacebookConfig.dispatch_mode || "facebook_graph"} - Page {selectedFacebookConfig.page_id || "-"}</span>
                      </div>
                      <div className="row-actions">
                        <button type="button" className="primary" onClick={() => editFacebookIntegration(selectedFacebookIntegration)}>Cargar datos para editar</button>
                        <button type="button" onClick={() => openIntegrationSecretModal(selectedFacebookIntegration)}>Actualizar token</button>
                        <button type="button" onClick={() => loadMetaTokenHealth("facebook")} disabled={facebookBusy}>Salud token</button>
                        <button type="button" onClick={() => refreshMetaToken("facebook")} disabled={facebookBusy}>Renovar</button>
                        <button type="button" className="danger-button" onClick={() => deleteIntegration(selectedFacebookIntegration)}>Eliminar</button>
                      </div>
                    </div>
                  ) : null}
                  {metaTokenHealth.facebook ? (
                    <div className={`token-health-strip ${metaTokenHealth.facebook.ok ? "ok" : "warn"}`}>
                      <strong>{metaTokenHealth.facebook.ok ? "Token Facebook operativo" : `Token Facebook: ${metaTokenHealth.facebook.recommendation || metaTokenHealth.facebook.status || "revisar"}`}</strong>
                      <span>Fuente: {metaTokenHealth.facebook.refresh_source || "-"} / Auto-renovable: {metaTokenHealth.facebook.can_auto_refresh ? "si" : "no"}</span>
                      <small>Page token {metaTokenHealth.facebook.page_access_token?.hint || "-"} {metaTokenHealth.facebook.page_access_token?.expires_at ? `/ vence ${compactDateTimeLabel(metaTokenHealth.facebook.page_access_token.expires_at)}` : ""}</small>
                      {!metaTokenHealth.facebook.can_auto_refresh ? <small>{t("meta.facebook.auto_refresh_hint")}</small> : null}
                    </div>
                  ) : null}
                  <form className="meta-grid instagram-manual-grid" onSubmit={saveFacebookManual}>
                    <label>Estado
                      <select value={facebookForm.status} onChange={(event) => setFacebookForm((prev) => ({ ...prev, status: event.target.value }))}>
                        <option value="connected">Connected</option>
                        <option value="paused">Paused</option>
                        <option value="disconnected">Disconnected</option>
                      </select>
                    </label>
                    <label>Modo envio
                      <select value={facebookForm.dispatch_mode} onChange={(event) => setFacebookForm((prev) => ({ ...prev, dispatch_mode: event.target.value }))}>
                        <option value="facebook_graph">Facebook Graph real</option>
                        <option value="stub">Stub local</option>
                      </select>
                    </label>
                    <label>Page ID
                      <input placeholder="Facebook Page ID" value={facebookForm.page_id} onChange={(event) => setFacebookForm((prev) => ({ ...prev, page_id: event.target.value }))} />
                    </label>
                    <label>Nombre pagina
                      <input placeholder="Ej: LuminArt Makeup" value={facebookForm.page_name} onChange={(event) => setFacebookForm((prev) => ({ ...prev, page_name: event.target.value }))} />
                    </label>
                    <label>Business Portfolio ID
                      <input placeholder="Opcional" value={facebookForm.business_id} onChange={(event) => setFacebookForm((prev) => ({ ...prev, business_id: event.target.value }))} />
                    </label>
                    <label>Meta App ID
                      <input placeholder="ID de la app del cliente" value={facebookForm.app_id} onChange={(event) => setFacebookForm((prev) => ({ ...prev, app_id: event.target.value }))} />
                    </label>
                    <label>Graph API
                      <input placeholder="v24.0" value={facebookForm.graph_api_version} onChange={(event) => setFacebookForm((prev) => ({ ...prev, graph_api_version: event.target.value }))} />
                    </label>
                    {!selectedFacebookIntegration ? (
                      <>
                        <label className="token-field">Page Access Token
                          <input ref={facebookPageTokenRef} type="password" placeholder="Token largo/permanente de la pagina" autoComplete="off" spellCheck={false} />
                        </label>
                        <label className="token-field">Meta App Secret
                          <input ref={facebookAppSecretRef} type="password" placeholder="Opcional: valida x-hub-signature-256" autoComplete="off" spellCheck={false} />
                        </label>
                      </>
                    ) : (
                      <div className="secret-summary token-field">
                        <div>
                          <strong>Secretos Facebook protegidos</strong>
                          <span>Page token: {selectedFacebookConfig.has_page_access_token ? `******** ${selectedFacebookConfig.page_access_token_hint || ""}` : "sin token"} / App secret: {selectedFacebookConfig.has_app_secret ? `******** ${selectedFacebookConfig.app_secret_hint || ""}` : "sin app secret"}</span>
                        </div>
                        <button type="button" onClick={() => openIntegrationSecretModal(selectedFacebookIntegration)}>Actualizar secretos</button>
                      </div>
                    )}
                    <button type="submit" className="primary">Guardar Facebook</button>
                  </form>
                  <div className="integration-cards">
                    {selectedFacebookIntegration ? (
                      <div className="integration-card-row instagram-row">
                        <div>
                          <strong>meta / facebook</strong>
                          <span>{selectedFacebookIntegration.status} / {selectedFacebookConfig.dispatch_mode || "facebook_graph"}</span>
                        </div>
                        <div><span>Page ID</span><strong>{selectedFacebookConfig.page_id || "-"}</strong></div>
                        <div><span>Meta App ID</span><strong>{selectedFacebookConfig.app_id || "-"}</strong></div>
                        <div className="integration-marks"><mark>{selectedFacebookConfig.has_page_access_token ? `Page token ${selectedFacebookConfig.page_access_token_hint || "guardado"}` : "Sin Page token"}</mark><mark>{selectedFacebookConfig.has_app_secret ? `App secret ${selectedFacebookConfig.app_secret_hint || "guardado"}` : "Sin app secret"}</mark></div>
                        <div className="row-actions">
                          <button type="button" onClick={() => editFacebookIntegration(selectedFacebookIntegration)}>Editar</button>
                          <button type="button" onClick={() => openIntegrationSecretModal(selectedFacebookIntegration)}>Actualizar token</button>
                          <button type="button" onClick={() => loadMetaTokenHealth("facebook")} disabled={facebookBusy}>Salud</button>
                          <button type="button" onClick={() => refreshMetaToken("facebook")} disabled={facebookBusy}>Renovar</button>
                          <button type="button" className="danger-button" onClick={() => deleteIntegration(selectedFacebookIntegration)}>Eliminar</button>
                        </div>
                      </div>
                    ) : <div className="empty">Sin integracion Facebook Messenger configurada.</div>}
                  </div>
                  <div className="manual-mode-box">
                    <div>
                      <strong>Webhook Facebook para app propia</strong>
                      <span>Crea un endpoint por tenant y copia Callback URL + Verify token en Meta Developers. Suscribe eventos: messages, messaging_postbacks y feed.</span>
                    </div>
                    <button type="button" onClick={createFacebookWebhookEndpoint}>Crear endpoint Facebook</button>
                  </div>
                  <div className="oauth-mode-box">
                    <div>
                      <strong>OAuth Facebook por tenant</strong>
                      <span>Usa la misma app Meta del cliente para generar tokens renovables. Luego pulsa Cargar cuentas y elige Usar Facebook en la pagina detectada.</span>
                    </div>
                    <div className="panel-actions">
                      <button type="button" className="primary" disabled={instagramBusy || facebookBusy} onClick={startInstagramOAuth}>{instagramBusy || facebookBusy ? "Procesando..." : t("meta.facebook.connect_button")}</button>
                      <button type="button" disabled={(instagramBusy || facebookBusy) || !instagramOAuth.state} onClick={loadInstagramAssets}>Cargar cuentas</button>
                    </div>
                  </div>
                  {lastWebhookSecret?.provider === "facebook" ? (
                    <div className="secret-box">
                      <strong>Valores Facebook visibles una sola vez</strong>
                      <span>Callback URL</span>
                      <div className="secret-value-row"><code>{fullWebhookUrl(lastWebhookSecret.url_path)}</code><button type="button" onClick={() => copyText(fullWebhookUrl(lastWebhookSecret.url_path), "Callback Facebook")}>Copiar URL</button></div>
                      {lastWebhookSecret.verify_token_once ? <><span>Verify token</span><div className="secret-value-row"><code>{lastWebhookSecret.verify_token_once}</code><button type="button" onClick={() => copyText(lastWebhookSecret.verify_token_once, "Verify token Facebook")}>Copiar token</button></div></> : null}
                    </div>
                  ) : null}
                  {facebookDiagnostics ? (
                    <div className={`debug-result ${facebookDiagnostics.ok && facebookDiagnostics.subscription?.final_subscribed ? "ok" : "bad"}`}>
                      <strong>Facebook Diagnostics</strong>
                      <span>{facebookDiagnostics.ok ? `${facebookDiagnostics.page_name || "Facebook Page"} / Page ${facebookDiagnostics.page_id || "-"}` : (facebookDiagnostics.status || "sin conexion")}</span>
                      {facebookDiagnostics.ok ? <small>subscribed_apps: {facebookDiagnostics.subscription?.status || "-"} / auto-subscribe: {facebookDiagnostics.subscription?.auto_subscribe_attempted ? "intentado" : "no necesario"}</small> : null}
                      {facebookDiagnostics.ok ? <small>Webhook Facebook: {facebookDiagnostics.webhook_callback_url || "-"} / Ultimo evento: {facebookDiagnostics.webhook_status?.last_seen_at || "sin eventos"}</small> : null}
                      {facebookDiagnostics.last_message?.id ? <small>Ultimo DM: {facebookDiagnostics.last_message.display_name || facebookDiagnostics.last_message.external_contact_id} - {facebookDiagnostics.last_message.last_message_text}</small> : null}
                      {facebookDiagnostics.last_comment?.id ? <small>Ultimo comentario: {facebookDiagnostics.last_comment.author_name || facebookDiagnostics.last_comment.author_username || "Usuario"} - {facebookDiagnostics.last_comment.message}</small> : null}
                      {facebookMetaRequiredPermissions.length ? <small>Meta esta reclamando: {facebookMetaRequiredPermissions.join(", ")}</small> : null}
                      {facebookMissingPermissions.length ? <small>Permisos faltantes segun el token: {facebookMissingPermissions.join(", ")}</small> : <small>Permisos Facebook requeridos: completos o no reportados por este token.</small>}
                      {facebookGrantedPermissions.length ? <small>Permisos concedidos detectados: {facebookGrantedPermissions.join(", ")}</small> : null}
                      {(facebookDiagnostics.subscription_checks || []).slice(0, 3).map((item, idx) => <small key={`${item.created_at}-${idx}`}>{compactDateTimeLabel(item.created_at)} - {item.status} {item.error || item.meta_error_message || ""}</small>)}
                      {(facebookDiagnostics.recent_errors || []).slice(0, 3).map((item, idx) => <small key={`${item.received_at}-${idx}`}>{compactDateTimeLabel(item.received_at)} - webhook {item.status}: {item.error}</small>)}
                    </div>
                  ) : null}
                </article>

                <article className="panel glass-card webhook-panel">
                  <div className="panel-head">
                    <div>
                      <h2>Webhooks</h2>
                      <span>callback URL y verify token para Meta Developers</span>
                    </div>
                    <button type="button" onClick={loadWebhooks}>Refrescar</button>
                  </div>
                  <div className="inline-form webhook-create-form">
                    <select value={webhookProvider} onChange={(event) => setWebhookProvider(event.target.value)}>
                      <option value="whatsapp">WhatsApp</option>
                      <option value="meta">Meta</option>
                      <option value="instagram">Instagram</option>
                      <option value="facebook">Facebook</option>
                      <option value="stripe">Stripe</option>
                    </select>
                    <label className="check-row"><input type="checkbox" checked={webhookSignatureRequired} onChange={(event) => setWebhookSignatureRequired(event.target.checked)} /> Requerir firma HMAC</label>
                    <button type="button" className="primary" onClick={createWebhook}>Crear / actualizar endpoint</button>
                  </div>
                  {lastWebhookSecret ? (
                    <div className="secret-box">
                      <strong>Valores para Meta (visibles una sola vez)</strong>
                      <span>Callback URL para Meta</span>
                      <div className="secret-value-row"><code>{fullWebhookUrl(lastWebhookSecret.url_path)}</code><button type="button" onClick={() => copyText(fullWebhookUrl(lastWebhookSecret.url_path), "Callback URL")}>Copiar URL</button></div>
                      {lastWebhookSecret.verify_token_once ? <><span>Verify token para Meta</span><div className="secret-value-row"><code>{lastWebhookSecret.verify_token_once}</code><button type="button" onClick={() => copyText(lastWebhookSecret.verify_token_once, "Verify token")}>Copiar token</button></div></> : null}
                      {lastWebhookSecret.signature_secret_once ? <><span>Firma HMAC opcional</span><div className="secret-value-row"><code>{lastWebhookSecret.signature_secret_once}</code><button type="button" onClick={() => copyText(lastWebhookSecret.signature_secret_once, "Firma HMAC")}>Copiar firma</button></div></> : null}
                      <small>El Verify token lo genera Scentra aleatoriamente. No es el token permanente de WhatsApp Cloud API.</small>
                    </div>
                  ) : (
                    <div className="secret-box muted-secret">
                      <strong>Verify token de Meta</strong>
                      <span>Scentra lo genera automaticamente al crear o rotar un endpoint. Si lo perdiste, pulsa Rotar token y copia el nuevo valor en Meta Developers.</span>
                    </div>
                  )}
                  <div className="webhook-cards">
                    {webhooks.map((endpoint) => (
                      <div className="webhook-card" key={endpoint.id}>
                        <div className="webhook-card-head">
                          <div><strong>{endpoint.provider}</strong><span>{endpoint.is_active ? "activo" : "pausado"} / {endpoint.signature_required ? "firma requerida" : "verify token"}</span></div>
                          <span>{endpoint.last_seen_at || "sin eventos"}</span>
                        </div>
                        <div className="callback-box"><code>{fullWebhookUrl(endpoint.url_path)}</code><button type="button" onClick={() => copyText(fullWebhookUrl(endpoint.url_path), "Callback URL")}>Copiar URL</button></div>
                        <div className="row-actions">
                          <button type="button" onClick={() => verifyWebhookEndpoint(endpoint)}>Verificar</button>
                          <button type="button" onClick={() => updateWebhookEndpoint(endpoint, { signature_required: !endpoint.signature_required })}>{endpoint.signature_required ? "Permitir token" : "Exigir firma"}</button>
                          <button type="button" onClick={() => rotateWebhookToken(endpoint)}>Rotar token</button>
                          <button type="button" onClick={() => rotateWebhookSignature(endpoint)}>Rotar firma</button>
                          <button type="button" className="danger-button" onClick={() => deleteWebhookEndpoint(endpoint)}>Eliminar</button>
                        </div>
                      </div>
                    ))}
                    {webhooks.length === 0 ? <div className="empty">Sin endpoints webhook.</div> : null}
                  </div>
                  {webhookCheck ? (
                    <div className={`debug-result ${webhookCheck.ok ? "ok" : "bad"}`}>
                      <strong>{webhookCheck.ok ? "Endpoint operativo" : "Endpoint con ajustes pendientes"}</strong>
                      {webhookCheck.error ? <span>{webhookCheck.error}</span> : null}
                      {webhookCheck.callback_url ? <div className="secret-value-row"><code>{webhookCheck.callback_url}</code><button type="button" onClick={() => copyText(webhookCheck.callback_url, "Callback URL")}>Copiar URL</button></div> : null}
                      <div className="debug-checks">
                        {(webhookCheck.checks || []).map((check) => <span className={check.ok ? "ok" : "warn"} key={check.code}>{check.label}</span>)}
                      </div>
                      {webhookCheck.integration?.id ? <small>Integracion vinculada: {webhookCheck.integration.status || "sin estado"} / actualizada {compactDateTimeLabel(webhookCheck.integration.updated_at)}</small> : <small>No hay integracion activa para este provider. Si eliminaste el canal, elimina tambien el endpoint o crea la integracion nuevamente.</small>}
                      {(webhookCheck.recent_events || []).length ? (
                        <div className="debug-mini-list">
                          {(webhookCheck.recent_events || []).map((event, index) => (
                            <span key={`${event.received_at}-${index}`}>{compactDateTimeLabel(event.received_at)} · {event.status || "evento"}{event.error ? ` · ${event.error}` : ""}</span>
                          ))}
                        </div>
                      ) : <small>Sin eventos recientes para este endpoint.</small>}
                      {(webhookCheck.next_steps || []).length ? <ul className="compact-list">{webhookCheck.next_steps.map((step) => <li key={step}>{step}</li>)}</ul> : null}
                    </div>
                  ) : null}
                  <div className="panel-actions"><button type="button" onClick={processWebhookEvents}>Procesar eventos pendientes</button></div>
                </article>
              </div>
            ) : null}
            {settingsTab === "apis" ? <div className="settings-stack">
              <article className="panel glass-card api-console">
                <div className="panel-head"><h2>Proveedores IA</h2><span>LLM / modelos</span></div>
                <p className="soft-copy">Agrega solo los proveedores que vas a usar. Las llaves se guardan cifradas por empresa y los modelos se cargan al expandir cada proveedor.</p>
                {renderCredentialSection(AI_API_PROVIDERS)}
              </article>
              <article className="panel glass-card api-console">
                <div className="panel-head"><h2>Voz y TTS</h2><span>ElevenLabs / Google / Piper</span></div>
                {renderCredentialSection(TTS_API_PROVIDERS)}
              </article>
              <article className="panel glass-card api-console">
                <div className="panel-head"><h2>Busqueda web e imagenes</h2><span>Tavily / Brave / SerpAPI</span></div>
                <p className="soft-copy">Activa solo el proveedor que usaras para fuentes externas. Los resultados quedan pendientes de aprobacion humana antes de usarse con clientes.</p>
                {renderCredentialSection(SEARCH_API_PROVIDERS)}
              </article>
              <article className="panel glass-card api-console">
                <div className="panel-head"><h2>Canales y comercio</h2><span>WhatsApp / WooCommerce</span></div>
                {renderChannelCredentialSection(CHANNEL_API_PROVIDERS)}
              </article>
              <article className="panel glass-card"><div className="panel-head"><h2>API SaaS interna</h2><span>base URL</span></div><code className="code-block">{API_BASE || "sin configurar"}/saas/v1</code><p className="soft-copy">Usa Bearer JWT para endpoints privados. Los webhooks resuelven empresa por endpoint key.</p><div className="panel-actions"><button type="button" className="primary" onClick={loadApiCredentials}>Refrescar credenciales</button></div></article>
            </div> : null}
            {settingsTab === "debug" ? <div className="settings-stack">
              <article className="panel glass-card">
                <div className="panel-head"><h2>Diagnostico operativo</h2><span>Meta / IA / colas</span></div>
                <p className="soft-copy">Usa este panel cuando un cliente no recibe mensajes, no entran webhooks o la IA no responde. No muestra secretos, solo estado y ultimos errores.</p>
                <div className="panel-actions"><button type="button" className="primary" onClick={() => loadDiagnostics()} disabled={diagnosticsRunning}>Refrescar diagnostico</button><button type="button" onClick={runDiagnostics} disabled={diagnosticsRunning}>{diagnosticsRunning ? "Procesando..." : "Procesar pendientes"}</button><button type="button" onClick={checkWhatsappSubscription} disabled={diagnosticsRunning}>{diagnosticsRunning ? "Verificando..." : "Verificar WABA subscribed_apps"}</button></div>
                <div className="debug-grid">
                  <div><span>API</span><strong>{diagnostics?.runtime?.api_ok ? "OK" : "Sin datos"}</strong><small>Worker embebido: {diagnostics?.runtime?.embedded_worker_enabled ? "ON" : "OFF"}</small></div>
                  <div><span>Empresa</span><strong>{diagnostics?.tenant?.name || activeCompany?.tenant_name || "-"}</strong><small>{diagnostics?.tenant?.status || lifecycleStatus}</small></div>
                  <div><span>IA</span><strong>{diagnostics?.ai?.enabled ? "Activa" : "Inactiva"}</strong><small>{diagnostics?.ai?.provider || aiConfig.provider} / {diagnostics?.ai?.active_model || activeAiModel || "sin modelo"}</small></div>
                  <div><span>Knowledge</span><strong>{number(diagnostics?.totals?.knowledge_sources || knowledgeSources.length)}</strong><small>fuentes activas</small></div>
                  <div><span>Inbox</span><strong>{number(diagnostics?.totals?.conversations || conversations.length)}</strong><small>{number(diagnostics?.totals?.messages || 0)} mensajes</small></div>
                  <div><span>Webhook</span><strong>{number((diagnostics?.webhooks?.endpoints || []).length)}</strong><small>endpoints configurados</small></div>
                </div>
              </article>
              <article className="panel glass-card">
                <div className="panel-head"><h2>Checklist de conexion</h2><span>lo minimo para enviar/recibir</span></div>
                <div className="debug-checks">
                  <span className={diagnostics?.integrations?.some((item) => item.channel === "whatsapp" && item.status === "connected") ? "ok" : "bad"}>WhatsApp conectado</span>
                  <span className={diagnostics?.integrations?.some((item) => item.channel === "whatsapp" && item.dispatch_mode === "meta_cloud") ? "ok" : "warn"}>Modo Meta Cloud</span>
                  <span className={diagnostics?.integrations?.some((item) => item.channel === "whatsapp" && item.has_token) ? "ok" : "bad"}>Token Meta guardado</span>
                  <span className={(diagnostics?.webhooks?.endpoints || []).some((item) => item.is_active) ? "ok" : "bad"}>Webhook activo</span>
                  <span className={diagnostics?.credentials?.some((item) => item.category === "ai" && item.has_secret) ? "ok" : "bad"}>API IA guardada</span>
                  <span className={diagnostics?.ai?.active_model ? "ok" : "warn"}>Modelo IA seleccionado</span>
                  <span className={diagnostics?.whatsapp_symptoms?.statuses_without_inbound ? "bad" : "ok"}>Statuses vs inbound</span>
                </div>
                {diagnostics?.whatsapp_symptoms?.statuses_without_inbound ? (
                  <div className="debug-result bad">
                    <strong>Meta esta enviando statuses, pero no llegan mensajes entrantes</strong>
                    <span>{diagnostics.whatsapp_symptoms.recommendation}</span>
                    <small>Statuses 24h: {number(diagnostics.whatsapp_symptoms.status_events_24h || 0)} / inbound 24h: {number(diagnostics.whatsapp_symptoms.inbound_events_24h || 0)}</small>
                  </div>
                ) : null}
                {(subscriptionCheck || (diagnostics?.whatsapp_subscription_checks || []).length) ? (
                  <div className={`debug-result ${subscriptionCheck?.is_subscribed ? "ok" : subscriptionCheck?.ok === false ? "bad" : ""}`}>
                    <strong>WABA subscribed_apps</strong>
                    {subscriptionCheck ? (
                      <>
                        <span>{subscriptionCheck.is_subscribed ? "Suscrito correctamente a la app." : `Estado: ${subscriptionCheck.status || subscriptionCheck.error || "sin confirmar"}`}</span>
                        <small>WABA: {subscriptionCheck.waba_id || "-"} / App: {subscriptionCheck.connected_app_id || subscriptionCheck.app_id || "-"} / Telefonos: {number((subscriptionCheck.phone_numbers || []).length)}</small>
                        <small>Webhook local: {subscriptionCheck.webhook_status?.active ? "activo" : "no activo"} / Endpoint: {subscriptionCheck.webhook_status?.endpoint_key || "-"}</small>
                      </>
                    ) : null}
                    {(diagnostics?.whatsapp_subscription_checks || []).slice(0, 3).map((item, idx) => (
                      <small key={`${item.created_at}-${idx}`}>{compactDateTimeLabel(item.created_at)} - {item.waba_id}: {item.status} {item.auto_subscribe_attempted ? "(auto-subscribe)" : ""}</small>
                    ))}
                  </div>
                ) : null}
              </article>
              <article className="panel glass-card">
                <div className="panel-head"><h2>Simular mensaje entrante</h2><span>prueba pipeline interno</span></div>
                <p className="soft-copy">Esta prueba no llama a Meta. Inserta un webhook falso con el WABA/Phone configurado y verifica si Scentra lo convierte en conversacion y mensaje. Si pasa, el fallo esta en Meta: callback, suscripcion o campo messages.</p>
                <form className="debug-sim-form" onSubmit={simulateInboundWebhook}>
                  <label>Telefono cliente
                    <input value={debugInboundForm.from_phone} placeholder="573001112233" onChange={(event) => setDebugInboundForm((prev) => ({ ...prev, from_phone: event.target.value }))} />
                  </label>
                  <label>Nombre
                    <input value={debugInboundForm.contact_name} placeholder="Cliente Diagnostico" onChange={(event) => setDebugInboundForm((prev) => ({ ...prev, contact_name: event.target.value }))} />
                  </label>
                  <label>Mensaje
                    <input value={debugInboundForm.message} placeholder="Hola, prueba entrante" onChange={(event) => setDebugInboundForm((prev) => ({ ...prev, message: event.target.value }))} />
                  </label>
                  <button type="submit" className="primary" disabled={diagnosticsRunning}>{diagnosticsRunning ? "Probando..." : "Simular entrada"}</button>
                </form>
                {debugInboundResult ? (
                  <div className={`debug-result ${debugInboundResult.ok ? "ok" : "bad"}`}>
                    <strong>{debugInboundResult.ok ? "Pipeline interno OK" : "Pipeline interno con error"}</strong>
                    <span>{debugInboundResult.ok ? "Scentra pudo procesar un mensaje tipo Meta y crear/actualizar el Inbox." : (debugInboundResult.error || "No se creo mensaje desde el webhook simulado.")}</span>
                    {debugInboundResult.process_result ? <small>Webhooks procesados: {debugInboundResult.process_result.processed || 0} / mensajes insertados: {debugInboundResult.process_result.messages_inserted || 0} / errores: {debugInboundResult.process_result.errors || 0}</small> : null}
                    {debugInboundResult.conversation?.id ? <small>Conversacion: {debugInboundResult.conversation.display_name || debugInboundResult.conversation.phone || debugInboundResult.conversation.external_contact_id}</small> : null}
                  </div>
                ) : null}
              </article>
              <article className="panel glass-card">
                <div className="panel-head"><h2>Integraciones</h2><span>configuracion segura</span></div>
                <div className="debug-table">{(diagnostics?.integrations || []).map((item, idx) => {
                  const isIg = String(item.channel || "").toLowerCase() === "instagram";
                  const isFacebook = String(item.channel || "").toLowerCase() === "facebook";
                  const assetLine = isIg
                    ? `Page: ${item.page_id || "-"} / IG Business: ${item.instagram_business_account_id || "-"} / App: ${item.app_id || "-"}`
                    : isFacebook
                      ? `Page: ${item.page_id || "-"} / App: ${item.app_id || "-"}`
                    : `Phone: ${item.phone_number_id || "-"} / WABA: ${item.business_account_id || "-"} / App: ${item.app_id || "-"}`;
                  return <div className="debug-row" key={`${item.provider}-${item.channel}-${idx}`}><strong>{item.provider} / {item.channel}</strong><span>{item.status} / {item.dispatch_mode || "-"}</span><small>{assetLine} / Token: {item.has_token ? "guardado" : "faltante"}</small></div>;
                })}{!diagnostics?.integrations?.length ? <div className="empty">Sin integraciones registradas.</div> : null}</div>
              </article>
              <article className="panel glass-card">
                <div className="panel-head"><h2>Meta Social</h2><span>Facebook / Instagram</span></div>
                <div className="queue-grid">
                  <div><strong>Eventos Meta 24h</strong><span>{number(diagnostics?.meta_social?.webhook_signal?.meta_events_24h || 0)}</span></div>
                  <div><strong>Comentarios 24h</strong><span>{number(diagnostics?.meta_social?.webhook_signal?.comment_events_24h || 0)}</span></div>
                  <div><strong>DMs 24h</strong><span>{number(diagnostics?.meta_social?.webhook_signal?.dm_events_24h || 0)}</span></div>
                </div>
                {diagnostics?.meta_social?.recommendation ? <div className="debug-result warn"><strong>Revision recomendada</strong><span>{diagnostics.meta_social.recommendation}</span></div> : null}
                <div className="debug-table">
                  {(diagnostics?.meta_social?.last_comments || []).map((item, idx) => <div className="debug-row" key={`comment-${idx}`}><strong>{item.channel} / comentario</strong><span>{item.author_name || item.author_username || "sin nombre"}</span><small>{compactDateTimeLabel(item.updated_at)} - {item.message || "-"}</small></div>)}
                  {(diagnostics?.meta_social?.last_dms || []).map((item, idx) => <div className="debug-row" key={`dm-${idx}`}><strong>{item.channel} / DM</strong><span>{item.display_name || item.external_contact_id || "sin nombre"}</span><small>{compactDateTimeLabel(item.updated_at)} - {item.last_message_text || "-"}</small></div>)}
                  {!(diagnostics?.meta_social?.last_comments || []).length && !(diagnostics?.meta_social?.last_dms || []).length ? <div className="empty">Aun no hay comentarios ni DMs sociales registrados para este tenant.</div> : null}
                </div>
              </article>
              <article className="panel glass-card">
                <div className="panel-head"><h2>Colas y errores</h2><span>webhooks / IA / outbound</span></div>
                <div className="queue-grid">
                  <div><strong>Webhooks</strong>{(diagnostics?.webhooks?.events || []).map((item) => <span key={item.status}>{item.status}: {item.total}</span>)}</div>
                  <div><strong>IA pendiente</strong>{(diagnostics?.queues?.ai_pending || []).map((item) => <span key={item.status}>{item.status}: {item.total}</span>)}</div>
                  <div><strong>Outbound</strong>{(diagnostics?.queues?.outbound || []).map((item) => <span key={item.status}>{item.status}: {item.total}</span>)}</div>
                </div>
                <div className="debug-table">{(diagnostics?.queues?.outbound_errors || []).map((item, idx) => <div className="debug-row error" key={`${item.updated_at}-${idx}`}><strong>{item.status} / {item.channel}</strong><span>{item.recipient_external_id || "-"}</span><small>{item.error}</small></div>)}{!diagnostics?.queues?.outbound_errors?.length ? <div className="empty">Sin errores outbound recientes.</div> : null}</div>
              </article>
              <article className="panel glass-card">
                <div className="panel-head"><h2>AI Gateway</h2><button type="button" onClick={() => loadAiGateway()}>Refrescar</button></div>
                <div className="queue-grid">
                  <div><strong>Proveedores</strong>{aiGatewayProviders.map((item) => <span key={item.provider_code}>{item.provider_code}: {item.default_model}</span>)}</div>
                  <div><strong>Kimi</strong><span>{aiGatewayProviders.find((item) => item.provider_code === "kimi") ? "registrado como proveedor oficial" : "pendiente de migracion"}</span></div>
                  <div><strong>Ultimas llamadas</strong><span>{number(aiGatewayRuns.length)} registradas</span></div>
                </div>
                <div className="debug-table">{aiGatewayRuns.map((item) => <div className={`debug-row ${item.status === "failed" ? "error" : ""}`} key={item.id}><strong>{item.agent_type || "agent"} / {item.provider_code}</strong><span>{item.status} · {item.model || "-"}</span><small>{compactDateTimeLabel(item.created_at)} / {number(item.total_tokens)} tokens / {number(item.latency_ms)} ms {item.fallback_used ? "/ fallback" : ""}{item.error_code ? ` / ${item.error_code}: ${item.error_message}` : ""}</small></div>)}{!aiGatewayRuns.length ? <div className="empty">Sin llamadas AI todavia. Usa Probar IA o espera una respuesta automatica para llenar esta traza.</div> : null}</div>
              </article>
              <article className="panel glass-card">
                <div className="panel-head"><h2>Ultimos webhooks</h2><span>entrada Meta</span></div>
                <div className="debug-table">{(diagnostics?.webhooks?.last_events || []).map((item, idx) => <div className="debug-row" key={`${item.received_at}-${idx}`}><strong>{item.provider} / {item.status}</strong><span>{compactDateTimeLabel(item.received_at)}</span><small>{item.error || "sin error"}</small></div>)}{!diagnostics?.webhooks?.last_events?.length ? <div className="empty">No hay eventos webhook recientes. Si escribes por WhatsApp y esto sigue vacio, Meta no esta llegando a Scentra o el callback/token esta mal configurado.</div> : null}</div>
              </article>
            </div> : null}
            {settingsTab === "users" ? <div className="settings-grid"><article className="panel glass-card"><div className="panel-head"><h2>Usuarios</h2><span>equipo</span></div><div className="table"><div className="row"><span>{me.email}</span><span>{me.role}</span><span>activo</span></div></div></article><article className="panel glass-card"><div className="panel-head"><h2>Invitar usuario</h2><span>proximo</span></div><label>Email<input placeholder="correo@empresa.com" /></label><label>Rol<select><option>agent</option><option>supervisor</option><option>admin</option></select></label><button type="button" className="primary" onClick={() => showStatus("Invitaciones de usuarios pendientes de backend.", "neutral")}>Enviar invitacion</button></article></div> : null}
            {settingsTab === "profile" ? <div className="settings-grid profile-grid">
              <article className="panel glass-card profile-card"><div className="panel-head"><h2>Perfil</h2><span>datos personales</span></div><div className="avatar-editor"><div className="avatar-preview">{(profileForm.fullName || me.email || "S").slice(0,1).toUpperCase()}</div><div><strong>{profileForm.fullName || me.email}</strong><p className="soft-copy">Foto de perfil, nombre visible y datos de contacto.</p></div></div><label>URL foto de perfil<input placeholder="https://..." value={profileForm.avatarUrl} onChange={(event) => setProfileForm((prev) => ({ ...prev, avatarUrl: event.target.value }))} /></label><div className="form-grid two"><label>Nombre completo<input value={profileForm.fullName} placeholder={me.email} onChange={(event) => setProfileForm((prev) => ({ ...prev, fullName: event.target.value }))} /></label><label>Email<input value={profileForm.email} placeholder={me.email} onChange={(event) => setProfileForm((prev) => ({ ...prev, email: event.target.value }))} /></label><label>Telefono<input value={profileForm.phone} placeholder="+57..." onChange={(event) => setProfileForm((prev) => ({ ...prev, phone: event.target.value }))} /></label><label>Cargo / rol visible<input value={profileForm.role} placeholder={me.role} onChange={(event) => setProfileForm((prev) => ({ ...prev, role: event.target.value }))} /></label></div><div className="panel-actions"><button type="button" className="primary" onClick={saveProfileLocal}>Guardar perfil</button></div></article>
              <article className="panel glass-card"><div className="panel-head"><h2>Empresa</h2><span>workspace activo</span></div><div className="company-profile"><span>Empresa</span><strong>{activeCompany?.tenant_name || activeCompany?.name || "Scentra"}</strong><span>Rol</span><strong>{me.role}</strong><span>Plan</span><strong>{billingPlan.plan_code || activeCompany?.plan_code || "starter"}</strong><span>Industria</span><strong>{selectedVerticalPack?.label || currentIndustryCode}</strong></div></article>
            </div> : null}
            {settingsTab === "security" ? <div className="settings-grid security-grid">
              <article className="panel glass-card"><div className="panel-head"><h2>Cambiar clave</h2><span>acceso</span></div><label>Clave actual<input type="password" value={securityForm.currentPassword} onChange={(event) => setSecurityForm((prev) => ({ ...prev, currentPassword: event.target.value }))} /></label><label>Nueva clave<input type="password" value={securityForm.newPassword} onChange={(event) => setSecurityForm((prev) => ({ ...prev, newPassword: event.target.value }))} /></label><label>Confirmar nueva clave<input type="password" value={securityForm.confirmPassword} onChange={(event) => setSecurityForm((prev) => ({ ...prev, confirmPassword: event.target.value }))} /></label>{securityForm.passwordChangedAt ? <p className="soft-copy">Ultimo cambio: {dateLabel(securityForm.passwordChangedAt)}</p> : null}<div className="panel-actions"><button type="button" className="primary" onClick={savePasswordChange}>Actualizar clave</button></div></article>
              <article className="panel glass-card"><div className="panel-head"><h2>2FA por email</h2><span>seguridad adicional</span></div><label className="switch-row"><input type="checkbox" checked={securityForm.twoFactorEnabled} onChange={(event) => setSecurityForm((prev) => ({ ...prev, twoFactorEnabled: event.target.checked }))} /><span><strong>Exigir codigo OTP al iniciar sesion</strong><small>El backend no entrega tokens hasta validar el codigo enviado por correo.</small></span></label><label>Metodo<select value={securityForm.twoFactorMethod} disabled={!securityForm.twoFactorEnabled} onChange={(event) => setSecurityForm((prev) => ({ ...prev, twoFactorMethod: event.target.value }))}><option value="email_otp">Codigo por email</option></select></label><div className="twofa-box"><strong>{securityForm.twoFactorEnabled ? "2FA activo" : "2FA inactivo"}</strong><p>Usa SMTP en produccion para entregar codigos. En local el backend devuelve un OTP de desarrollo.</p></div><div className="panel-actions"><button type="button" onClick={saveTwoFactorPreference}>Guardar 2FA</button></div></article>
              <article className="panel glass-card"><div className="panel-head"><h2>Politicas</h2><span>estado</span></div><label className="check-row"><input type="checkbox" checked readOnly /> JWT requerido</label><label className="check-row"><input type="checkbox" checked readOnly /> RBAC por rol</label><label className="check-row"><input type="checkbox" checked={webhookSignatureRequired} onChange={(event) => setWebhookSignatureRequired(event.target.checked)} /> Firma HMAC por defecto en nuevos webhooks</label><p className="soft-copy">Auditoria de acciones criticas quedara en saas_audit_events.</p></article>
              <article className="panel glass-card"><div className="panel-head"><h2>Privacidad</h2><span>export/delete</span></div><p className="soft-copy">Exporta tu cuenta o el cliente seleccionado en Inbox. El borrado se registra como solicitud pendiente para evitar eliminaciones accidentales.</p><div className="panel-actions"><button type="button" onClick={exportMyAccountData}>Exportar mi cuenta</button><button type="button" onClick={exportSelectedCustomerData}>Exportar cliente</button><button type="button" onClick={requestSelectedCustomerDelete}>Solicitar borrado</button></div></article>
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
                  <div className="panel-head">
                    <h2>Planes disponibles</h2>
                    <label className="inline-select">Proveedor
                      <select value={billingCheckoutProvider} onChange={(event) => setBillingCheckoutProvider(event.target.value)}>
                        <option value="wompi">Wompi Bancolombia</option>
                        <option value="mercadopago">MercadoPago</option>
                        <option value="stripe">Stripe</option>
                        <option value="manual">Manual</option>
                      </select>
                    </label>
                  </div>
                  <div className="plan-cards">{billingPlans.map((plan) => <article className={`plan-card ${billingPlan.plan_code === plan.plan_code ? "active" : ""}`} key={plan.plan_code}><strong>{plan.display_name || plan.plan_code}</strong><span>{number(plan.max_monthly_messages)} mensajes/mes</span><span>{number(plan.max_campaigns)} campanas CRM</span><span>{number(plan.max_broadcasts)} broadcasts</span><span>{number(plan.max_ai_tokens)} tokens IA</span><span>{number(plan.max_integrations)} integraciones / {number(plan.max_agents)} usuarios</span><span>{(Number(plan.price_monthly_cents || 0) / 100).toLocaleString("es-CO", { style: "currency", currency: plan.currency || "USD", maximumFractionDigits: 0 })} / mes</span><button type="button" className="primary" disabled={!plan.is_active || billingCheckoutBusy === plan.plan_code} onClick={() => startPlanCheckout(plan.plan_code)}>{billingCheckoutBusy === plan.plan_code ? "Creando..." : "Pagar / activar"}</button>{billingPlan.plan_code === plan.plan_code ? <small>Plan actual</small> : null}<button type="button" className="ghost" onClick={() => changePlanDev(plan.plan_code)}>Usar en local</button></article>)}</div>
                  <p className="soft-copy">En produccion el plan se activa por checkout y webhook del proveedor. Wompi usa firma de integridad generada en backend.</p>
                  {billingCheckoutSessions.length ? <div className="billing-history"><strong>Ultimos checkouts</strong>{billingCheckoutSessions.slice(0, 4).map((item) => <div key={item.id}><span>{item.provider} / {item.plan_code}</span><small>{item.status} · {compactDateTimeLabel(item.created_at)}</small>{item.checkout_url ? <button type="button" onClick={() => window.open(item.checkout_url, "_blank", "noopener,noreferrer")}>Abrir</button> : null}</div>)}</div> : null}
                  {billingInvoices.length ? <div className="billing-history"><strong>Facturas</strong>{billingInvoices.slice(0, 6).map((item) => <div key={item.id}><span>{item.invoice_number || item.provider_invoice_id || item.id}</span><small>{item.status} · {money(item.total_cents, item.currency)} · {compactDateTimeLabel(item.paid_at || item.due_at || item.created_at)}</small><button type="button" onClick={() => downloadBillingInvoice(item)}>PDF</button></div>)}</div> : null}
                </article>
              </div>
            ) : null}
          </section>
        )}
      </main>
      <section className={`advisor-widget ${advisorOpen ? "open" : "closed"}`} aria-label="Scentra Advisor">
        {!advisorOpen ? (
          <button type="button" className="advisor-launcher glass-card" onClick={() => setAdvisorOpen(true)}>
            <span>AI</span>
            <strong>Advisor</strong>
            {advisorSignalCount ? <em>{number(advisorSignalCount)}</em> : null}
          </button>
        ) : (
          <div className="advisor-panel glass-card">
            <div className="advisor-head">
              <div><span>AI Business Advisor</span><strong>Scentra Advisor</strong></div>
              <div className="row-actions">
                <button type="button" onClick={() => loadAdvisorSignals()}>Refrescar</button>
                <button type="button" onClick={() => setAdvisorOpen(false)}>Cerrar</button>
              </div>
            </div>
            <div className="advisor-livebar">
              <span className={advisorLoading ? "live" : ""}>{advisorLoading ? (advisorStreamStatus || "Analizando...") : "Listo para ayudarte"}</span>
              <small>{advisorLastSync ? `Sinc. ${chatTimeLabel(advisorLastSync)}` : "Sinc. pendiente"}</small>
            </div>
            <div className="advisor-body">
            {advisorBriefing.length ? (
              <div className="advisor-briefing">
                <strong>Briefing predictivo</strong>
                {advisorBriefing.slice(0, 3).map((item) => (
                  <div key={item.key || item.title}>
                    <span>{item.title}</span>
                    <small>{advisorDisplayContent(item.summary)}</small>
                  </div>
                ))}
              </div>
            ) : null}
            {advisorMetrics ? (
              <div className="advisor-pulse">
                <div><strong>{number(advisorMetrics.pending_actions || 0)}</strong><span>Pendientes</span></div>
                <div><strong>{number(advisorMetrics.executed_actions || 0)}</strong><span>Ejecutadas</span></div>
                <div><strong>{number(advisorMetrics.events_24h || 0)}</strong><span>Eventos 24h</span></div>
                <div><strong>{number(advisorMetrics.negative_feedback || 0)}</strong><span>Alertas feedback</span></div>
              </div>
            ) : null}
            {advisorActivity.length ? (
              <div className="advisor-activity">
                <strong>Actividad reciente</strong>
                {advisorActivity.slice(0, 3).map((event) => (
                  <span className={event.severity || "info"} key={event.id}>{event.summary || event.event_type}</span>
                ))}
              </div>
            ) : null}
            <div className="advisor-signals">
              {[...advisorInsights.slice(0, 3).map((item) => ({ ...item, _kind: "insight" })), ...advisorRecommendations.slice(0, 2).map((item) => ({ ...item, _kind: "recommendation" }))].map((item) => (
                <article className={`advisor-signal ${item.severity || "info"}`} key={`${item._kind}-${item.id}`}>
                  <button type="button" className="advisor-signal-main" onClick={() => applyAdvisorSignal(item)}>
                    <span>{item._kind === "recommendation" ? "Recomendacion" : "Insight"} / {item.severity || "info"}</span>
                    <strong>{item.title}</strong>
                    <small>{item.description}</small>
                  </button>
                  <div className="advisor-signal-actions">
                    <button type="button" disabled={advisorBusyActionId === `prepare:${item.id}`} onClick={() => prepareAdvisorAction(item)}>
                      {advisorBusyActionId === `prepare:${item.id}` ? "Preparando..." : "Preparar"}
                    </button>
                    <button type="button" className="advisor-dismiss" onClick={() => dismissAdvisorSignal(item._kind, item.id)}>×</button>
                  </div>
                </article>
              ))}
              {!advisorSignalCount ? <div className="empty">Sin alertas proactivas por ahora. Puedes preguntarle al Advisor por el estado del negocio.</div> : null}
            </div>
            {advisorActions.length ? (
              <div className="advisor-actions">
                <div className="advisor-actions-head"><strong>Acciones Advisor</strong><span>{advisorActions.length}</span></div>
                {advisorActions.slice(0, 3).map((action) => (
                  <article className={`advisor-action ${action.status || "draft"}`} key={action.id}>
                    <div>
                      <span>{action.action_type} / riesgo {action.risk_level}</span>
                      <strong>{action.title}</strong>
                      <small>{action.status === "executed" ? "Ejecutada de forma segura." : action.status === "approved" ? "Aprobada, lista para ejecucion asistida." : action.description}</small>
                    </div>
                    <div className="advisor-action-buttons">
                      {["draft", "pending_approval"].includes(action.status) ? <button type="button" className="primary" disabled={advisorBusyActionId === `approve:${action.id}`} onClick={() => approveAdvisorAction(action.id)}>{advisorBusyActionId === `approve:${action.id}` ? "..." : "Aprobar"}</button> : null}
                      {action.status === "approved" ? <button type="button" className="primary" disabled={advisorBusyActionId === `execute:${action.id}`} onClick={() => executeAdvisorAction(action.id)}>{advisorBusyActionId === `execute:${action.id}` ? "..." : "Ejecutar"}</button> : null}
                      <button type="button" disabled={advisorBusyActionId === `dismiss:${action.id}`} onClick={() => dismissAdvisorAction(action.id)}>Descartar</button>
                    </div>
                  </article>
                ))}
              </div>
            ) : null}
            {advisorMemory?.summary ? (
              <div className="advisor-memory">
                <strong>Memoria activa</strong>
                <span>{advisorDisplayContent(advisorMemory.summary)}</span>
              </div>
            ) : null}
            <div className="advisor-chat" ref={advisorChatRef}>
              {advisorMessages.map((message) => (
                <div className={`advisor-message ${message.role}`} key={message.id}>
                  <span>{message.role === "user" ? "Tu" : "Advisor"}{message.metadata_json?.streaming ? " / en vivo" : ""}</span>
                  <p>{advisorDisplayContent(message.content)}</p>
                  {message.role === "assistant" && !message.metadata_json?.streaming ? (
                    <div className="advisor-feedback">
                      <button type="button" className={message.metadata_json?.feedback_rating === "helpful" ? "active" : ""} onClick={() => sendAdvisorFeedback(message.id, "helpful")}>Util</button>
                      <button type="button" className={message.metadata_json?.feedback_rating === "not_helpful" ? "active" : ""} onClick={() => sendAdvisorFeedback(message.id, "not_helpful")}>Revisar</button>
                    </div>
                  ) : null}
                </div>
              ))}
              {advisorLoading ? <div className="advisor-message assistant"><span>Advisor</span><p>Analizando contexto...</p></div> : null}
              {!advisorMessages.length ? (
                <div className="advisor-empty">
                  <strong>Preguntame por ventas, inbox, triggers o salud Meta.</strong>
                  {advisorQuickPrompts.map((prompt) => <button key={prompt} type="button" onClick={() => sendAdvisorMessage(prompt)}>{prompt}</button>)}
                </div>
              ) : null}
            </div>
            </div>
            <form className="advisor-input" onSubmit={submitAdvisorChat}>
              <input value={advisorInput} onChange={(event) => setAdvisorInput(event.target.value)} placeholder="Pregunta al Advisor..." />
              <button type="submit" className="primary" disabled={advisorLoading || !advisorInput.trim()}>{advisorLoading ? "..." : "Enviar"}</button>
            </form>
          </div>
        )}
      </section>
      {milestoneNotice ? (
        <div className="milestone-backdrop" role="presentation" onMouseDown={() => closeMilestoneNotice(false)}>
          <section className="milestone-card glass-card" role="dialog" aria-modal="true" aria-label="Actualizacion importante" onMouseDown={(event) => event.stopPropagation()}>
            <span className="milestone-eyebrow">{milestoneNotice.eyebrow || "Actualizacion importante"}</span>
            <h2>{milestoneNotice.title || "Scentra quedo actualizado"}</h2>
            <p>{milestoneNotice.body || "Esta mejora ya esta lista para usarse en tu empresa."}</p>
            {Array.isArray(milestoneNotice.items) && milestoneNotice.items.length ? (
              <ul className="compact-list">{milestoneNotice.items.map((item) => <li key={item}>{item}</li>)}</ul>
            ) : null}
            <div className="panel-actions">
              <button type="button" className="primary" onClick={() => closeMilestoneNotice(Boolean(milestoneNotice.actionType))}>{milestoneNotice.cta || "Entendido"}</button>
              <button type="button" onClick={() => closeMilestoneNotice(false)}>Cerrar</button>
            </div>
          </section>
        </div>
      ) : null}
      {aiTesterOpen ? <div className="modal-backdrop" role="presentation" onMouseDown={() => setAiTesterOpen(false)}><section className="modal-window glass-card" role="dialog" aria-modal="true" aria-label="Probar IA" onMouseDown={(event) => event.stopPropagation()}><div className="panel-head"><h2>Probar IA</h2><button type="button" onClick={() => setAiTesterOpen(false)}>Cerrar</button></div><form onSubmit={submitAiTest} className="modal-form"><label>Phone<input placeholder="57300..." value={aiTest.phone} onChange={(event) => setAiTest((prev) => ({ ...prev, phone: event.target.value }))} /></label><label>Mensaje<textarea rows={5} placeholder="Escribe un mensaje de prueba..." value={aiTest.message} onChange={(event) => setAiTest((prev) => ({ ...prev, message: event.target.value }))} /></label>{aiTestResult ? <div className="ai-test-result"><strong>Respuesta IA</strong><p>{aiTestResult}</p></div> : null}<div className="panel-actions"><button type="submit" className="primary">Procesar</button><button type="button" onClick={() => { setAiTest({ phone: "", message: "" }); setAiTestResult(""); }}>Limpiar</button></div></form></section></div> : null}
      {integrationSecretModal ? (
        <div className="modal-backdrop" role="presentation" onMouseDown={() => setIntegrationSecretModal(null)}>
          <section className="modal-window glass-card" role="dialog" aria-modal="true" aria-label="Actualizar secretos de integracion" onMouseDown={(event) => event.stopPropagation()}>
            <div className="panel-head">
              <div><h2>Actualizar secretos</h2><span>{integrationSecretModal.provider} / {integrationSecretModal.channel}</span></div>
              <button type="button" onClick={() => setIntegrationSecretModal(null)}>Cerrar</button>
            </div>
            <form onSubmit={saveIntegrationSecrets} className="modal-form">
              <p className="soft-copy">El valor guardado no se puede revelar. Para corregirlo, pega uno nuevo y confirma tu contrasena. El backend reemplaza el secreto cifrado y el navegador solo recibe una pista.</p>
              <div className="secret-box muted-secret">
                <strong>Estado actual</strong>
                <span>{["instagram","facebook"].includes(String(integrationSecretModal.channel || "").toLowerCase()) ? "Page Access Token" : "Token Meta"}: {integrationSecretModal.has_access_token ? `******** ${integrationSecretModal.token_hint || ""}` : "sin token guardado"}</span>
                <span>App Secret: {integrationSecretModal.has_app_secret ? `******** ${integrationSecretModal.app_secret_hint || ""}` : "sin app secret guardado"}</span>
              </div>
              <label>{["instagram","facebook"].includes(String(integrationSecretModal.channel || "").toLowerCase()) ? "Nuevo Page Access Token" : "Nuevo token permanente de Meta"}<input type="password" autoFocus placeholder="Pegar token completo solo si vas a reemplazarlo" autoComplete="off" spellCheck={false} value={integrationSecretModal.access_token || ""} onChange={(event) => setIntegrationSecretModal((prev) => ({ ...(prev || {}), access_token: event.target.value }))} /></label>
              <label>Nuevo Meta App Secret<input type="password" placeholder="Opcional: pegar app secret nuevo" autoComplete="off" spellCheck={false} value={integrationSecretModal.app_secret || ""} onChange={(event) => setIntegrationSecretModal((prev) => ({ ...(prev || {}), app_secret: event.target.value }))} /></label>
              <label>Tu contrasena<input type="password" placeholder="Confirma tu contrasena para guardar" autoComplete="current-password" value={integrationSecretModal.current_password || ""} onChange={(event) => setIntegrationSecretModal((prev) => ({ ...(prev || {}), current_password: event.target.value }))} /></label>
              <div className="panel-actions"><button type="submit" className="primary">Guardar cifrado</button><button type="button" onClick={() => setIntegrationSecretModal(null)}>Cancelar</button></div>
            </form>
          </section>
        </div>
      ) : null}
      {credentialModal ? (
        <div className="modal-backdrop" role="presentation" onMouseDown={() => setCredentialModal(null)}>
          <section className="modal-window glass-card" role="dialog" aria-modal="true" aria-label="Actualizar credencial" onMouseDown={(event) => event.stopPropagation()}>
            <div className="panel-head"><div><h2>{credentialModal.name}</h2><span>{credentialModal.credential_key}</span></div><button type="button" onClick={() => setCredentialModal(null)}>Cerrar</button></div>
            <form onSubmit={saveCredentialModal} className="modal-form">
              <p className="soft-copy">Pega el valor completo solo aqui. Al guardar se cifra en backend y desaparece del navegador; luego solo veras una pista. Los modelos se eligen despues con Cargar modelos.</p>
              <label>Nuevo valor<input type="password" autoFocus placeholder="Pegar API key / token / secreto" value={credentialModal.value || ""} onChange={(event) => setCredentialModal((prev) => ({ ...(prev || {}), value: event.target.value }))} /></label>
              <div className="panel-actions"><button type="submit" className="primary" disabled={credentialSaving}>{credentialSaving ? "Guardando..." : "Guardar cifrado"}</button><button type="button" onClick={() => setCredentialModal(null)}>Cancelar</button></div>
            </form>
          </section>
        </div>
      ) : null}
      {catalogOpen ? (
        <div className="modal-backdrop" role="presentation" onMouseDown={() => setCatalogOpen(false)}>
          <section className="modal-window glass-card catalog-modal" role="dialog" aria-modal="true" aria-label="Catalogo WooCommerce" onMouseDown={(event) => event.stopPropagation()}>
            <div className="panel-head"><div><h2>Catalogo WooCommerce</h2><span>Selecciona un producto para insertarlo en la respuesta</span></div><button type="button" onClick={() => setCatalogOpen(false)}>Cerrar</button></div>
            <form className="catalog-search" onSubmit={(event) => { event.preventDefault(); loadCatalogProducts(catalogSearch); }}>
              <input value={catalogSearch} onChange={(event) => setCatalogSearch(event.target.value)} placeholder="Buscar producto por nombre o SKU..." />
              <button type="submit" className="primary" disabled={catalogLoading}>{catalogLoading ? "Buscando..." : "Buscar"}</button>
            </form>
            {catalogError ? <div className="status error">{catalogError}</div> : null}
            <div className="catalog-grid">
              {catalogProducts.map((product) => (
                <button type="button" className="catalog-product-card" key={product.id || product.permalink || product.name} onClick={() => insertCatalogProduct(product)}>
                  {product.image_url ? <img src={product.image_url} alt={product.name} /> : <span className="catalog-image-placeholder">Producto</span>}
                  <strong>{product.name}</strong>
                  <span>{product.price ? `$ ${product.price}` : "Sin precio visible"}</span>
                  <small>{product.stock_status || "stock"}{product.sku ? ` / SKU ${product.sku}` : ""}</small>
                  {Array.isArray(product.attributes) && product.attributes.length ? <small>{product.attributes.slice(0, 2).map((item) => `${item.name}: ${item.value}`).join(" · ")}</small> : null}
                  <em>Enviar ficha</em>
                </button>
              ))}
              {!catalogLoading && catalogProducts.length === 0 ? <div className="empty">Sin productos para mostrar. Prueba otra busqueda o revisa que WooCommerce tenga productos publicados.</div> : null}
            </div>
          </section>
        </div>
      ) : null}
    </div>
  );
}

export default App;
