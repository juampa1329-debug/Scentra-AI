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
  { code: "google", category: "ai", name: "Google / Gemini", env: "GOOGLE_AI_API_KEY", alt: "GEMINI_API_KEY", models: "gemini-2.5-flash, gemini-2.5-pro, gemma-3-*", supportsModels: true },
  { code: "groq", category: "ai", name: "Groq", env: "GROQ_API_KEY", alt: "", models: "llama-3.1-8b-instant, llama-3.1-70b-versatile", supportsModels: true },
  { code: "mistral", category: "ai", name: "Mistral", env: "MISTRAL_API_KEY", alt: "", models: "mistral-small-latest, mistral-medium-latest", supportsModels: true },
  { code: "openrouter", category: "ai", name: "OpenRouter", env: "OPENROUTER_API_KEY", alt: "OPENROUTER_SITE / OPENROUTER_APP_NAME", models: "catalogo live de OpenRouter", supportsModels: true },
];

const TTS_API_PROVIDERS = [
  { code: "elevenlabs", category: "tts", name: "ElevenLabs", env: "ELEVENLABS_API_KEY", fields: "ELEVENLABS_VOICE_ID, ELEVENLABS_MODEL_ID", supportsModels: true },
  { code: "google_tts", category: "tts", name: "Google Cloud TTS", env: "GOOGLE_CLOUD_TTS_API_KEY", fields: "GOOGLE_TTS_LANGUAGE_CODE, GOOGLE_TTS_VOICE_NAME", supportsModels: true },
  { code: "piper", category: "tts", name: "Piper local", env: "PIPER_BIN", fields: "PIPER_MODEL_PATH", supportsModels: false },
];

const CHANNEL_API_PROVIDERS = [
  { code: "whatsapp_cloud", category: "channel", name: "WhatsApp Cloud API", env: "WHATSAPP_PERMANENT_TOKEN", fields: ["WHATSAPP_TOKEN", "META_ACCESS_TOKEN", "WHATSAPP_PHONE_NUMBER_ID", "WHATSAPP_WABA_ID", "META_APP_ID", "WHATSAPP_GRAPH_VERSION"] },
  { code: "woocommerce", category: "commerce", name: "WooCommerce", env: "WC_BASE_URL", fields: ["WC_CONSUMER_KEY", "WC_CONSUMER_SECRET"] },
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
  { key: "dashboard", label: "Dashboard", icon: "▥" },
  { key: "inbox", label: "Inbox", icon: "□" },
  { key: "customers", label: "Clientes", icon: "◎" },
  { key: "labels", label: "Etiquetas", icon: "◇" },
  { key: "campaigns", label: "CRM", icon: "↯" },
  { key: "broadcast", label: "Masiva", icon: "◁" },
  { key: "ads", label: "Ads", icon: "▤" },
  { key: "settings", label: "Ajustes", icon: "⚙" },
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
  typingIndicator: true,
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
  { label: "Caras", icon: "☺", items: ["😀", "😃", "😄", "😁", "😆", "😅", "😂", "🤣", "🙂", "🙃", "😉", "😊", "😇", "🥰", "😍", "😘", "😋", "😜", "🤪", "🤗", "🤭", "🤔", "😎", "🥳", "😌", "😔", "😢", "😭", "😤", "😡"] },
  { label: "Gestos", icon: "☝", items: ["👍", "👎", "👌", "👏", "🙌", "🙏", "🤝", "💪", "👀", "🫶", "💅", "✍️", "💃", "🕺", "🏃", "🧘"] },
  { label: "Ventas", icon: "$", items: ["💬", "📲", "📞", "📩", "✅", "❌", "⏰", "📌", "📦", "🚚", "💳", "💰", "🛍️", "🎁", "🏷️", "🧾", "📊", "📈", "🤝", "🔥"] },
  { label: "Objetos", icon: "□", items: ["🌸", "💐", "💎", "✨", "⭐", "🌟", "❤️", "💚", "💙", "💜", "🖤", "🤍", "🎉", "🎊", "☕", "🍫", "🍔", "🎵", "📍", "🔗"] },
];
const RECENT_EMOJIS_KEY = "scentra_recent_emojis";
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
  const composerFileRef = useRef(null);
  const messagesPanelRef = useRef(null);
  const messagesEndRef = useRef(null);
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
  const refreshPromiseRef = useRef(null);
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
  const [whatsappPhones, setWhatsappPhones] = useState([]);
  const [phoneRegisterForm, setPhoneRegisterForm] = useState({ phone_number_id: "", pin: "" });
  const [phoneSyncing, setPhoneSyncing] = useState(false);
  const [integrationForm, setIntegrationForm] = useState({ provider: "meta", channel: "whatsapp", status: "connected", dispatch_mode: "stub", phone_number_id: "", business_account_id: "", app_id: "", graph_api_version: "v24.0", access_token_env: "SCENTRA_META_ACCESS_TOKEN" });
  const [aiConfig, setAiConfig] = useState(defaultAiConfig);
  const [aiTesterOpen, setAiTesterOpen] = useState(false);
  const [aiTest, setAiTest] = useState({ phone: "", message: "" });
  const [aiTestResult, setAiTestResult] = useState("");
  const [profileForm, setProfileForm] = useState({ fullName: "", email: "", phone: "", role: "", avatarUrl: "" });
  const [securityForm, setSecurityForm] = useState({ currentPassword: "", newPassword: "", confirmPassword: "", twoFactorEnabled: false });
  const [apiCredentials, setApiCredentials] = useState([]);
  const [credentialModal, setCredentialModal] = useState(null);
  const [credentialSaving, setCredentialSaving] = useState(false);
  const [credentialModels, setCredentialModels] = useState({});
  const [conversations, setConversations] = useState([]);
  const [selectedConversation, setSelectedConversation] = useState(null);
  const [conversationMemory, setConversationMemory] = useState(null);
  const [messages, setMessages] = useState([]);
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
  const [emojiOpen, setEmojiOpen] = useState(false);
  const [emojiSearch, setEmojiSearch] = useState("");
  const [recentEmojis, setRecentEmojis] = useState(() => {
    try { return JSON.parse(localStorage.getItem(RECENT_EMOJIS_KEY) || "[]"); }
    catch { return []; }
  });
  const [attachMenuOpen, setAttachMenuOpen] = useState(false);
  const [inboxChannelFilter, setInboxChannelFilter] = useState("all");
  const [inboxSearch, setInboxSearch] = useState("");
  const [crmPanelOpen, setCrmPanelOpen] = useState(true);
  const [crmDraft, setCrmDraft] = useState({});
  const [savingCrm, setSavingCrm] = useState(false);
  const [notificationSoundEnabled, setNotificationSoundEnabled] = useState(true);
  const [isRecording, setIsRecording] = useState(false);
  const [recordingSeconds, setRecordingSeconds] = useState(0);
  const [recordingLevels, setRecordingLevels] = useState(EMPTY_WAVEFORM);
  const [composerSending, setComposerSending] = useState(false);
  const [status, setStatus] = useState("");
  const [statusTone, setStatusTone] = useState("neutral");

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
    settings: true,
  };
  const activeViewAllowed = moduleAccess[activeView] !== false;
  const navItems = NAV_ITEMS.filter((item) => moduleAccess[item.key] !== false);
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
  const activeAiModel = selectedAiCredential.selected_model || "";
  const activeFallbackModel = selectedFallbackCredential.selected_model || "";
  const activeTtsModel = selectedTtsCredential.selected_model || "";
  const availableInboxChannels = Array.from(new Set([
    ...integrations.filter((item) => item.status === "connected").map((item) => String(item.channel || "").toLowerCase()),
    ...conversations.map((item) => String(item.channel || "").toLowerCase()),
  ].filter(Boolean))).filter((channel) => !["billing"].includes(channel)).sort();
  const filteredConversations = conversations.filter((conversation) => {
    const channelOk = inboxChannelFilter === "all" || String(conversation.channel || "").toLowerCase() === inboxChannelFilter;
    const needle = inboxSearch.trim().toLowerCase();
    if (!channelOk) return false;
    if (!needle) return true;
    return [
      conversation.display_name,
      conversation.phone,
      conversation.external_contact_id,
      conversation.last_message_text,
      conversation.tags,
    ].some((value) => String(value || "").toLowerCase().includes(needle));
  });
  const emojiNeedle = emojiSearch.trim().toLowerCase();
  const visibleEmojiGroups = [
    { label: "Recientes", icon: "↺", items: recentEmojis },
    ...EMOJI_GROUPS,
  ].map((group) => ({
    ...group,
    items: emojiNeedle ? group.items.filter((emoji) => emoji.includes(emojiNeedle)) : group.items,
  })).filter((group) => group.items.length);
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
    const skipAuthRefreshPath = ["/saas/v1/auth/login", "/saas/v1/auth/register", "/saas/v1/auth/refresh"].some((prefix) => String(path || "").startsWith(prefix));
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
    setConversations([]); setSelectedConversation(null); setConversationMemory(null); setMessages([]); setReplyText("");
    clearComposerAttachment(); setEmojiOpen(false); setAttachMenuOpen(false); setInboxChannelFilter("all"); setInboxSearch(""); setIsRecording(false); setRecordingSeconds(0); setRecordingLevels(EMPTY_WAVEFORM);
    recordingLevelsRef.current = EMPTY_WAVEFORM;
    setIntegrations([]); setWebhooks([]); setWebhookEvents([]); setBillingOverview(null); setBillingPlans([]); setLastWebhookSecret(null);
    setApiCredentials([]); setCredentialModal(null); setCredentialModels({});
    setWhatsappPhones([]); setPhoneRegisterForm({ phone_number_id: "", pin: "" });
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
      setProfileForm((prev) => ({ ...prev, fullName: prev.fullName || data?.full_name || "", email: prev.email || data?.email || "" }));
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
        chunks: String(meta.reply_chunk_chars ?? prev.chunks),
        delayBetween: String(meta.reply_chunk_delay_ms ?? prev.delayBetween),
        typingDelay: String(meta.reply_initial_delay_ms ?? prev.typingDelay),
        cooldown: String(meta.inbound_cooldown_seconds ?? prev.cooldown),
        typingIndicator: meta.typing_indicator_enabled !== false,
        voiceEnabled: meta.voice_enabled ?? prev.voiceEnabled,
        preferVoice: meta.prefer_voice ?? prev.preferVoice,
        ttsProvider: meta.tts_provider || prev.ttsProvider,
        voiceId: meta.voice_id || prev.voiceId,
        voiceName: meta.voice_name || prev.voiceName,
        voicePrompt: meta.voice_prompt || prev.voicePrompt,
      }));
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

  const loadMessages = async (conversation, options = {}) => {
    if (!conversation?.id) return;
    try {
      const [data, memoryData] = await Promise.all([
        apiCall(`/saas/v1/conversations/${encodeURIComponent(conversation.id)}/messages`),
        apiCall(`/saas/v1/ai/conversations/${encodeURIComponent(conversation.id)}/memory`).catch(() => null),
      ]);
      const selected = { ...conversation, unread_count: 0 };
      setSelectedConversation(selected); setMessages(data?.messages || []);
      setConversationMemory(memoryData || null);
      if (!options.preserveComposer) { setReplyText(""); clearComposerAttachment(); setEmojiOpen(false); setAttachMenuOpen(false); }
      if (Number(conversation.unread_count || 0) > 0) markConversationRead(conversation.id, { silent: true });
    } catch (err) { showStatus(String(err.message || err), "error"); }
  };

  const loadInbox = async () => {
    if (!accessToken) return;
    try {
      const data = await apiCall("/saas/v1/conversations?limit=100");
      const items = data?.conversations || [];
      const nextUnread = items.reduce((sum, item) => sum + Number(item.unread_count || 0), 0);
      if (lastUnreadTotalRef.current && nextUnread > lastUnreadTotalRef.current && notificationSoundEnabled) playIncomingSound();
      lastUnreadTotalRef.current = nextUnread;
      setConversations(items);
      if (items.length && !selectedConversation) await loadMessages(items[0]);
      if (items.length && selectedConversation?.id) {
        const updatedSelected = items.find((item) => item.id === selectedConversation.id);
        if (updatedSelected) await loadMessages({ ...selectedConversation, ...updatedSelected }, { preserveComposer: true });
      }
      if (!items.length) { setSelectedConversation(null); setConversationMemory(null); setMessages([]); setReplyText(""); clearComposerAttachment(); }
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
    if (accessToken && activeView === "settings") Promise.all([loadIntegrations(), loadWebhooks(), loadBilling(), loadApiCredentials(), loadAiSettings()]);
    if (accessToken && activeView === "inbox") loadInbox();
  }, [accessToken, activeView]);

  useEffect(() => {
    if (!accessToken || activeView !== "inbox") return undefined;
    const timer = window.setInterval(() => loadInbox(), 6000);
    return () => window.clearInterval(timer);
  }, [accessToken, activeView, selectedConversation?.id, notificationSoundEnabled]);

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
    if (!selectedConversation?.id) {
      setCrmDraft({});
      setConversationMemory(null);
      return;
    }
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
    });
  }, [selectedConversation?.id]);

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
    const appSecret = (metaAppSecretRef.current?.value || "").trim();
    const phoneNumberId = (integrationForm.phone_number_id || "").trim();
    const dispatchMode = (integrationForm.dispatch_mode || "stub").trim();
    if (dispatchMode !== "stub" && !phoneNumberId) return showStatus("Phone Number ID requerido para Meta Cloud real.", "error");
    try {
      const configJson = { dispatch_mode: dispatchMode, phone_number_id: phoneNumberId, business_account_id: (integrationForm.business_account_id || "").trim(), app_id: (integrationForm.app_id || "").trim(), graph_api_version: (integrationForm.graph_api_version || "v24.0").trim(), access_token_env: accessTokenEnv };
      if (accessToken) configJson.access_token = accessToken;
      if (appSecret) configJson.app_secret = appSecret;
      await apiCall("/saas/v1/integrations", { method: "POST", body: JSON.stringify({ provider: integrationForm.provider, channel: integrationForm.channel, status: integrationForm.status, secret_ref: accessToken ? "tenant:meta:whatsapp" : dispatchMode === "stub" ? "" : `env:${accessTokenEnv}`, config_json: configJson }) });
      if (metaAccessTokenRef.current) metaAccessTokenRef.current.value = "";
      if (metaAppSecretRef.current) metaAppSecretRef.current.value = "";
      showStatus("Integracion guardada", "ok"); await loadIntegrations(); await loadBilling();
    } catch (err) { showStatus(String(err.message || err), "error"); }
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
  const appendEmoji = (emoji) => {
    setReplyText((prev) => `${prev}${emoji}`);
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
    const price = product.price ? ` - ${product.price}` : "";
    const sku = product.sku ? `\nSKU: ${product.sku}` : "";
    const url = product.permalink ? `\n${product.permalink}` : "";
    const text = `${product.name || "Producto"}${price}${sku}${url}`;
    setReplyText((prev) => `${prev}${prev.trim() ? "\n\n" : ""}${text}`);
    setCatalogOpen(false);
    showStatus("Producto insertado en el mensaje. Cuando activemos mensajes de catalogo nativos, saldra como tarjeta interactiva.", "ok");
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
      showStatus("Ficha CRM guardada", "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setSavingCrm(false);
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
    return type;
  };
  const messageSenderLabel = (message) => {
    if (String(message?.direction || "").toLowerCase() === "out") return "Tu";
    const fullName = [selectedConversation?.first_name, selectedConversation?.last_name].filter(Boolean).join(" ").trim();
    return fullName || selectedConversation?.display_name || "Cliente";
  };
  const renderMessageContent = (message) => {
    const type = String(message?.msg_type || "text").toLowerCase();
    const url = messageMediaUrl(message);
    const label = messageLabel(message);
    return (
      <>
        {type === "image" && url ? <img className="chat-media image" src={url} alt={message.text || "Imagen recibida"} loading="lazy" /> : null}
        {type === "video" && url ? <video className="chat-media video" src={url} controls playsInline /> : null}
        {type === "audio" && url ? (
          <div className="audio-message">
            <AudioWaveform src={url} seed={message.id || message.created_at || message.media_id} />
            <audio src={url} controls preload="metadata" />
          </div>
        ) : null}
        {(type === "document" || type === "file") && url ? <a className="document-chip" href={url} target="_blank" rel="noreferrer">Abrir {label}</a> : null}
        {message.text && !/^\[(image|video|audio|document|file)\]$/i.test(message.text) ? <p>{message.text}</p> : !url ? <p>[{label}]</p> : null}
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
    if (!replyText.trim() && !attachmentFile) return;
    setComposerSending(true);
    try {
      let mediaId = "";
      let msgType = "text";
      let mimeType = "";
      let filename = "";
      if (attachmentFile) {
        msgType = attachmentKind || mediaKindFromMime(attachmentFile.type);
        mimeType = attachmentFile.type || "";
        filename = attachmentFile.name || "";
        const formData = new FormData();
        formData.append("kind", msgType);
        formData.append("file", attachmentFile);
        const upload = await apiCall("/saas/v1/media/upload", { method: "POST", body: formData });
        mediaId = upload?.media_id || upload?.media?.id || "";
      }
      const data = await apiCall(`/saas/v1/conversations/${encodeURIComponent(selectedConversation.id)}/messages`, {
        method: "POST",
        body: JSON.stringify({ text: replyText, msg_type: msgType, media_id: mediaId, mime_type: mimeType, filename }),
      });
      const dispatch = data?.dispatch || {};
      const outboundError = dispatch.last_error || data?.outbound_status?.error || "";
      if (Number(dispatch.failed || 0) > 0 || Number(dispatch.blocked || 0) > 0) {
        showStatus(outboundError ? `Meta no envio el mensaje: ${outboundError}` : "Mensaje guardado, pero Meta no lo envio. Revisa integracion, plan o logs de outbound.", "error");
      } else if (Number(dispatch.sent || 0) > 0 && whatsappDispatchMode === "stub") {
        showStatus("Mensaje procesado en modo prueba. Cambia Canales a Meta Cloud para enviarlo al telefono.", "neutral");
      } else if (Number(dispatch.sent || 0) > 0) {
        showStatus("Mensaje enviado por WhatsApp", "ok");
      } else {
        showStatus("Mensaje encolado para envio", "ok");
      }
      setReplyText("");
      clearComposerAttachment();
      setEmojiOpen(false);
      await loadMessages(selectedConversation);
      await loadInbox();
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setComposerSending(false);
    }
  };
  const changePlanDev = async (planCode) => { try { const data = await apiCall("/saas/v1/billing/dev/change-plan", { method: "POST", body: JSON.stringify({ plan_code: planCode }) }); setBillingOverview(data); showStatus(`Plan actualizado a ${planCode}`, "ok"); await loadSession(); } catch (err) { showStatus(String(err.message || err), "error"); } };
  const saveAiLocal = async () => {
    try {
      const data = await apiCall("/saas/v1/ai/settings", {
        method: "PUT",
        body: JSON.stringify({
          enabled: Boolean(aiConfig.enabled),
          provider_code: aiConfig.provider,
          fallback_provider_code: aiConfig.fallbackProvider,
          system_prompt: aiConfig.systemPrompt,
          max_tokens: Number(aiConfig.maxTokens || 1800),
          temperature: Number(aiConfig.temperature || 0.5),
          metadata_json: {
            voice_enabled: Boolean(aiConfig.voiceEnabled),
            prefer_voice: Boolean(aiConfig.preferVoice),
            tts_provider: aiConfig.ttsProvider,
            voice_id: aiConfig.voiceId,
            voice_name: aiConfig.voiceName,
            voice_prompt: aiConfig.voicePrompt,
            typing_indicator_enabled: Boolean(aiConfig.typingIndicator),
            inbound_cooldown_seconds: Number(aiConfig.cooldown || 6),
            reply_initial_delay_ms: Number(aiConfig.typingDelay || 4000),
            reply_chunk_delay_ms: Number(aiConfig.delayBetween || 4000),
            reply_chunk_chars: Number(aiConfig.chunks || 480),
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
        chunks: String(asObject(data?.metadata_json).reply_chunk_chars ?? prev.chunks),
        delayBetween: String(asObject(data?.metadata_json).reply_chunk_delay_ms ?? prev.delayBetween),
        typingDelay: String(asObject(data?.metadata_json).reply_initial_delay_ms ?? prev.typingDelay),
        cooldown: String(asObject(data?.metadata_json).inbound_cooldown_seconds ?? prev.cooldown),
        typingIndicator: asObject(data?.metadata_json).typing_indicator_enabled !== false,
      }));
      showStatus("Ajustes IA guardados. El agente usara el modelo seleccionado en APIs.", "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    }
  };
  const saveProfileLocal = () => showStatus("Perfil preparado. Falta conectar persistencia de usuario y foto.", "ok");
  const saveSecurityLocal = () => showStatus("Seguridad preparada. Cambio de clave y 2FA requieren endpoints backend.", "neutral");
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

  const renderCredentialCard = (provider, credentialKey = provider.env) => {
    const credential = credentialByKey[credentialKey] || {};
    const modelsState = credentialModels[credentialKey] || {};
    const modelOptions = modelsState.models || [];
    const selectedModel = modelsState.selected ?? credential.selected_model ?? "";
    return (
      <div className="api-card" key={`${provider.code}-${credentialKey}`}>
        <div className="api-card-headline">
          <div><strong>{provider.name}</strong><span>{provider.models || provider.fields || `Principal: ${provider.env}`}</span></div>
          <span className={`secret-pill ${credential.has_secret ? "saved" : "missing"}`}>{credential.has_secret ? `Guardada ${credential.secret_hint || ""}` : "Sin guardar"}</span>
        </div>
        <div className="api-key-row">
          <span>{credentialKey}</span>
          <button type="button" onClick={() => openCredentialModal(provider, credentialKey)}>{credential.has_secret ? "Actualizar" : "Agregar"}</button>
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
          {navItems.map(({ key, label, icon }) => <button key={key} className={"nav-item " + (activeView === key ? "active" : "")} onClick={() => setActiveView(key)}><span className="nav-icon">{icon}</span><span>{label}</span></button>)}
        </nav>
        <div className="company-card"><span>Empresa activa</span><strong>{activeCompany?.tenant_name || activeCompany?.name || me.tenant_id}</strong><small>{me.role} / plan {billingPlan.display_name || billingPlan.plan_code || activeCompany?.plan_code || "starter"}</small></div>
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
            </div>
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
              <div className="panel-head inbox-list-head"><h2>Inbox</h2><span>{unreadTotal ? `${number(unreadTotal)} sin leer` : `${filteredConversations.length} chats`}</span></div>
              <div className="inbox-filters">
                <button type="button" className={inboxChannelFilter === "all" ? "active" : ""} onClick={() => setInboxChannelFilter("all")}>Todos</button>
                {availableInboxChannels.map((channel) => <button type="button" key={channel} className={inboxChannelFilter === channel ? "active" : ""} onClick={() => setInboxChannelFilter(channel)}>{channelLabel(channel)}</button>)}
                <input value={inboxSearch} onChange={(event) => setInboxSearch(event.target.value)} placeholder="Buscar telefono, nombre o preview..." />
                <button type="button" onClick={() => { setInboxSearch(""); setInboxChannelFilter("all"); }}>Limpiar</button>
              </div>
              <div className="conversation-list">
                {filteredConversations.map((conversation) => (
                  <button type="button" className={`conversation-item ${selectedConversation?.id === conversation.id ? "active" : ""}`} key={conversation.id} onClick={() => loadMessages(conversation)}>
                    <span className="conversation-title"><strong>{conversation.display_name || conversation.phone || conversation.external_contact_id}</strong>{Number(conversation.unread_count || 0) > 0 ? <em>{number(conversation.unread_count)}</em> : null}</span>
                    <span className="conversation-meta"><b>{channelLabel(conversation.channel)}</b>{Number(conversation.unread_count || 0) > 0 ? <small>Sin leer</small> : <small>Leido</small>}</span>
                    <small>{conversation.last_message_text || "-"}</small>
                  </button>
                ))}
                {filteredConversations.length === 0 ? <div className="empty">Sin conversaciones para este filtro.</div> : null}
              </div>
            </div>
            <div className="panel glass-card inbox-thread">
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
                  <button type="submit" className="primary send-button" disabled={composerSending || (!replyText.trim() && !attachmentFile)}>{composerSending ? "..." : "➤"}</button>
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
            </div>
            {crmPanelOpen ? (
              <aside className="panel glass-card inbox-crm">
                <div className="panel-head"><h2>CRM - Cliente</h2><button type="button" onClick={() => setCrmPanelOpen(false)}>×</button></div>
                {selectedConversation ? (
                  <div className="crm-mini-form">
                    <div className="crm-snapshot"><span>Telefono</span><strong>{selectedConversation.phone || selectedConversation.external_contact_id}</strong><span>Canal</span><strong>{channelLabel(selectedConversation.channel)}</strong></div>
                    <label>Nombre<input value={crmDraft.first_name || ""} onChange={(event) => updateCrmDraft("first_name", event.target.value)} placeholder="Ej: Juan" /></label>
                    <label>Apellido<input value={crmDraft.last_name || ""} onChange={(event) => updateCrmDraft("last_name", event.target.value)} placeholder="Ej: Perez" /></label>
                    <label>Ciudad<input value={crmDraft.city || ""} onChange={(event) => updateCrmDraft("city", event.target.value)} /></label>
                    <label>Tipo<select value={crmDraft.customer_type || ""} onChange={(event) => updateCrmDraft("customer_type", event.target.value)}><option value="">Sin definir</option><option value="minorista">Minorista</option><option value="mayorista">Mayorista</option><option value="vip">VIP</option></select></label>
                    <label>Etapa<select value={crmDraft.crm_stage || ""} onChange={(event) => updateCrmDraft("crm_stage", event.target.value)}><option value="">Sin etapa</option><option value="contactado">Contactado</option><option value="interes">Interes</option><option value="intencion_compra">Intencion compra</option><option value="pago_pendiente">Pago pendiente</option><option value="pago_confirmado">Pago confirmado</option></select></label>
                    <label>Pago<select value={crmDraft.payment_status || ""} onChange={(event) => updateCrmDraft("payment_status", event.target.value)}><option value="">Sin estado</option><option value="pending">Pendiente</option><option value="paid">Pagado</option><option value="failed">Fallido</option></select></label>
                    <label>Intereses<input value={crmDraft.interests || ""} onChange={(event) => updateCrmDraft("interests", event.target.value)} placeholder="dulces, frescos..." /></label>
                    <label>Etiquetas<input value={crmDraft.tags || ""} onChange={(event) => updateCrmDraft("tags", event.target.value)} placeholder="vip, pago pendiente..." /></label>
                    <label>Notas<textarea rows={4} value={crmDraft.notes || ""} onChange={(event) => updateCrmDraft("notes", event.target.value)} /></label>
                    <div className="ai-context-card">
                      <div className="ai-context-head"><strong>Contexto IA</strong><button type="button" onClick={() => loadConversationMemory(selectedConversation.id)}>Refrescar</button></div>
                      <p>{conversationMemory?.summary || "La IA aun no ha construido memoria para esta conversacion."}</p>
                      <div className="ai-facts">
                        {Object.entries(conversationMemory?.facts_json || {}).filter(([, value]) => String(value || "").trim()).slice(0, 8).map(([key, value]) => <span key={key}><b>{key}</b>{String(value)}</span>)}
                      </div>
                      <button type="button" onClick={processSelectedWithAi}>Procesar con IA ahora</button>
                    </div>
                    <label className="check-row"><input type="checkbox" checked={Boolean(crmDraft.takeover)} onChange={(event) => updateCrmDraft("takeover", event.target.checked)} /> Takeover humano</label>
                    <button type="button" className="primary" onClick={saveSelectedCrm} disabled={savingCrm}>{savingCrm ? "Guardando..." : "Guardar ficha"}</button>
                  </div>
                ) : <div className="empty">Selecciona una conversacion para ver la ficha CRM.</div>}
              </aside>
            ) : null}
          </section>
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
                  <div className="form-grid four">
                    <label>Espera antes de responder (seg)<input type="number" min="0" value={aiConfig.cooldown} onChange={(event) => setAiConfig((prev) => ({ ...prev, cooldown: event.target.value }))} /></label>
                    <label>Typing antes del primer envio (ms)<input type="number" min="0" value={aiConfig.typingDelay} onChange={(event) => setAiConfig((prev) => ({ ...prev, typingDelay: event.target.value }))} /></label>
                    <label>Chars por fragmento<input type="number" min="0" value={aiConfig.chunks} onChange={(event) => setAiConfig((prev) => ({ ...prev, chunks: event.target.value }))} /></label>
                    <label>Delay entre fragmentos (ms)<input type="number" min="0" value={aiConfig.delayBetween} onChange={(event) => setAiConfig((prev) => ({ ...prev, delayBetween: event.target.value }))} /></label>
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
                    <label>Voice ID manual opcional<input value={aiConfig.voiceId} onChange={(event) => setAiConfig((prev) => ({ ...prev, voiceId: event.target.value }))} /></label>
                    <label>Nombre visible de voz<input value={aiConfig.voiceName} onChange={(event) => setAiConfig((prev) => ({ ...prev, voiceName: event.target.value }))} /></label>
                  </div>
                  <label>Prompt de voz<textarea rows={4} value={aiConfig.voicePrompt} onChange={(event) => setAiConfig((prev) => ({ ...prev, voicePrompt: event.target.value }))} /></label>
                </article>
                <article className="panel glass-card">
                  <div className="panel-head"><h2>Knowledge Base</h2><span>fuentes</span></div>
                  <div className="inline-form compact"><select><option>Mostrar: Todos</option></select><button type="button">Refrescar</button></div>
                  <label>Notas<input placeholder="ej: catalogo 2026, politicas de envio..." /></label>
                  <div className="upload-zone">Arrastra PDF/TXT aqui o elige archivo</div>
                  <h3>Fuentes Web</h3>
                  <label>URL<input placeholder="https://tutienda.com/pagina-o-blog" /></label>
                  <button type="button">Anadir fuente web</button>
                </article>
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
                  <form className="meta-grid" onSubmit={saveIntegration}>
                    <label>Proveedor
                      <select value={integrationForm.provider} onChange={(event) => setIntegrationForm((prev) => ({ ...prev, provider: event.target.value }))}>
                        <option value="meta">Meta</option>
                        <option value="whatsapp">WhatsApp</option>
                        <option value="instagram">Instagram</option>
                        <option value="facebook">Facebook</option>
                        <option value="stripe">Stripe</option>
                      </select>
                    </label>
                    <label>Canal
                      <select value={integrationForm.channel} onChange={(event) => setIntegrationForm((prev) => ({ ...prev, channel: event.target.value }))}>
                        <option value="whatsapp">WhatsApp</option>
                        <option value="instagram">Instagram</option>
                        <option value="facebook">Facebook</option>
                        <option value="billing">Billing</option>
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
                    <label className="token-field">Meta App Secret
                      <input ref={metaAppSecretRef} type="password" placeholder="Opcional: valida x-hub-signature-256" autoComplete="off" spellCheck={false} />
                    </label>
                    <label>Graph API
                      <input placeholder="v24.0" value={integrationForm.graph_api_version} onChange={(event) => setIntegrationForm((prev) => ({ ...prev, graph_api_version: event.target.value }))} />
                    </label>
                    <label className="token-field">Token permanente de Meta
                      <input ref={metaAccessTokenRef} type="password" placeholder="Pegar token permanente" autoComplete="off" spellCheck={false} />
                    </label>
                    <button type="submit" className="primary">Guardar integracion</button>
                  </form>
                  <div className="integration-cards">
                    {integrations.map((integration) => {
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
                        </div>
                      );
                    })}
                    {integrations.length === 0 ? <div className="empty">Sin integraciones configuradas.</div> : null}
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
                    <button type="button" className="primary" onClick={createWebhook}>Crear endpoint</button>
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
                          <button type="button" onClick={() => updateWebhookEndpoint(endpoint, { signature_required: !endpoint.signature_required })}>{endpoint.signature_required ? "Permitir token" : "Exigir firma"}</button>
                          <button type="button" onClick={() => rotateWebhookToken(endpoint)}>Rotar token</button>
                          <button type="button" onClick={() => rotateWebhookSignature(endpoint)}>Rotar firma</button>
                        </div>
                      </div>
                    ))}
                    {webhooks.length === 0 ? <div className="empty">Sin endpoints webhook.</div> : null}
                  </div>
                  <div className="panel-actions"><button type="button" onClick={processWebhookEvents}>Procesar eventos pendientes</button></div>
                </article>
              </div>
            ) : null}
            {settingsTab === "apis" ? <div className="settings-stack">
              <article className="panel glass-card api-console">
                <div className="panel-head"><h2>Proveedores IA</h2><span>LLM / modelos</span></div>
                <p className="soft-copy">Las llaves se guardan cifradas por empresa. En el navegador solo mostramos una pista; para rotarlas usa Actualizar y pega el valor nuevo en el modal.</p>
                <div className="api-card-grid">{AI_API_PROVIDERS.map((provider) => renderCredentialCard(provider))}</div>
              </article>
              <article className="panel glass-card api-console">
                <div className="panel-head"><h2>Voz y TTS</h2><span>ElevenLabs / Google / Piper</span></div>
                <div className="api-card-grid">{TTS_API_PROVIDERS.map((provider) => renderCredentialCard(provider))}</div>
              </article>
              <article className="panel glass-card api-console">
                <div className="panel-head"><h2>Canales y comercio</h2><span>WhatsApp / WooCommerce</span></div>
                <div className="api-card-grid channel-api-grid">{CHANNEL_API_PROVIDERS.map((provider) => <div className="api-card wide-api-card" key={provider.name}><div><strong>{provider.name}</strong><span>Principal: {provider.env}</span></div>{renderCredentialCard(provider)}<div className="api-field-list">{provider.fields.map((field) => renderCredentialCard({ ...provider, name: field, env: field, supportsModels: false }, field))}</div></div>)}</div>
              </article>
              <article className="panel glass-card"><div className="panel-head"><h2>API SaaS interna</h2><span>base URL</span></div><code className="code-block">{API_BASE || "sin configurar"}/saas/v1</code><p className="soft-copy">Usa Bearer JWT para endpoints privados. Los webhooks resuelven empresa por endpoint key.</p><div className="panel-actions"><button type="button" className="primary" onClick={loadApiCredentials}>Refrescar credenciales</button></div></article>
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
      {aiTesterOpen ? <div className="modal-backdrop" role="presentation" onMouseDown={() => setAiTesterOpen(false)}><section className="modal-window glass-card" role="dialog" aria-modal="true" aria-label="Probar IA" onMouseDown={(event) => event.stopPropagation()}><div className="panel-head"><h2>Probar IA</h2><button type="button" onClick={() => setAiTesterOpen(false)}>Cerrar</button></div><form onSubmit={submitAiTest} className="modal-form"><label>Phone<input placeholder="57300..." value={aiTest.phone} onChange={(event) => setAiTest((prev) => ({ ...prev, phone: event.target.value }))} /></label><label>Mensaje<textarea rows={5} placeholder="Escribe un mensaje de prueba..." value={aiTest.message} onChange={(event) => setAiTest((prev) => ({ ...prev, message: event.target.value }))} /></label>{aiTestResult ? <div className="ai-test-result"><strong>Respuesta IA</strong><p>{aiTestResult}</p></div> : null}<div className="panel-actions"><button type="submit" className="primary">Procesar</button><button type="button" onClick={() => { setAiTest({ phone: "", message: "" }); setAiTestResult(""); }}>Limpiar</button></div></form></section></div> : null}
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
