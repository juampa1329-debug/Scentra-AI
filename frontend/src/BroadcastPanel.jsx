import React, { useEffect, useMemo, useRef, useState } from "react";

const number = (value) => Number(value || 0).toLocaleString("es-CO");
const pct = (used, limit) => (!Number(limit || 0) ? 0 : Math.min(100, Math.round((Number(used || 0) / Number(limit || 0)) * 100)));

const MODULES = [
  ["ai_agent", "AI Agent", "Reglas IA para outbound y copys automaticos.", false],
  ["broadcast_campaign", "Broadcast Campaign", "Campanas de envio masivo con plantilla aprobada.", true],
  ["chat_widget", "Chat Widget", "Widget embebido para captura y conversion.", false],
  ["sequence", "Secuencia", "Secuencias de seguimiento por pasos y tiempos.", false],
  ["input_flow", "Input Flow", "Formularios/flows para calificar leads.", false],
  ["whatsapp_flows", "WhatsApp Flows", "Flows interactivos de WhatsApp.", false],
  ["message_template", "Message Template", "Plantillas oficiales Meta para broadcast.", true],
  ["commerce", "WC/Shopify Automation", "Automatizaciones ecommerce.", false],
  ["outbound_webhook", "Out-bound Webhook", "Webhooks de salida.", false],
  ["action_buttons", "Action Buttons", "Botones CTA de conversion.", false],
  ["configuration", "Configuracion", "Ajustes globales de mensajeria masiva.", false],
];

const LOCALES = [["es", "Spanish"], ["es_CO", "Spanish (CO)"], ["en_US", "English (US)"], ["pt_BR", "Portuguese (BR)"]];
const CATEGORIES = [["UTILITY", "Utility"], ["MARKETING", "Marketing"], ["AUTHENTICATION", "Auth/OTP"]];
const HEADER_TYPES = [["", "No Header"], ["TEXT", "Text"], ["IMAGE", "Image"], ["VIDEO", "Video"], ["DOCUMENT", "Document"]];
const EMOJIS = ["✨", "🔥", "💎", "🎁", "👇", "🙌", "✅", "🛍️", "📦", "⏳", "💬", "🌿"];
const TOKEN_EXAMPLES = {
  customer_name: "Juan Perez",
  customer_first_name: "Juan",
  customer_phone: "+573001112233",
  customer_email: "juan@email.com",
  customer_city: "Bogota",
  business_name: "Scentra +AI",
  assistant_name: "Laura",
  campaign_name: "Promo mayo",
};
const REPORT_STATUSES = [
  ["all", "Todos"],
  ["queued", "En cola"],
  ["processing", "Procesando"],
  ["sent", "Enviados"],
  ["delivered", "Entregados"],
  ["read", "Leidos"],
  ["replied", "Respondidos"],
  ["failed", "Fallidos"],
];
const REPORT_METRICS = [
  ["targeted", "Audiencia"],
  ["sent", "Enviados"],
  ["delivered", "Entregados"],
  ["read", "Leidos"],
  ["replied", "Respuestas"],
  ["failed", "Fallidos"],
];

const emptyMetaForm = () => ({
  name: "",
  language: "es",
  category: "UTILITY",
  header_type: "",
  header_text: "",
  header_media_handle: "",
  body_text: "",
  footer_text: "",
  buttons: [],
  allow_category_change: true,
});

const emptyBroadcast = () => ({
  name: "",
  channel: "whatsapp",
  meta_template_id: "",
  segment_id: "",
  body: "",
  status: "draft",
  scheduled_at: "",
});

function renderTokens(text) {
  return String(text || "").replace(/\{\{\s*([a-zA-Z0-9_-]+)\s*\}\}/g, (_, key) => TOKEN_EXAMPLES[key] || `{{${key}}}`);
}

function statusClass(status) {
  const token = String(status || "").toLowerCase();
  if (token === "approved") return "ok-chip";
  if (token === "rejected" || token === "disabled") return "danger-chip";
  if (token === "pending") return "warn-chip";
  return "done-chip";
}

function reportStatusClass(status) {
  const token = String(status || "").toLowerCase();
  if (["sent", "delivered", "read", "replied"].includes(token)) return "ok-chip";
  if (token === "failed" || token === "blocked") return "danger-chip";
  if (token === "queued" || token === "processing") return "warn-chip";
  return "done-chip";
}

function reportStatusLabel(status) {
  const token = String(status || "").toLowerCase();
  return REPORT_STATUSES.find(([value]) => value === token)?.[1] || (token ? token.toUpperCase() : "N/A");
}

function formatDate(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat("es-CO", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function csvCell(value) {
  const text = String(value ?? "").replace(/\r?\n/g, " ").trim();
  return `"${text.replace(/"/g, '""')}"`;
}

function downloadCsv(filename, rows) {
  const blob = new Blob([rows.map((row) => row.map(csvCell).join(",")).join("\n")], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function safeFilename(value) {
  return String(value || "broadcast").toLowerCase().replace(/[^a-z0-9_-]+/g, "_").replace(/^_+|_+$/g, "") || "broadcast";
}

function reportMetricPct(metrics, key) {
  if (key === "read") return metrics?.opened_pct || metrics?.read_rate_pct || 0;
  if (key === "replied") return metrics?.reply_rate_pct || 0;
  return metrics?.[`${key}_pct`] || 0;
}

function emptyButton(kind = "QUICK_REPLY") {
  if (kind === "URL") return { type: "URL", text: "Ver sitio", url: "https://", phone_number: "" };
  if (kind === "PHONE_NUMBER") return { type: "PHONE_NUMBER", text: "Llamar", url: "", phone_number: "+57" };
  return { type: "QUICK_REPLY", text: "Responder", url: "", phone_number: "" };
}

function EmojiButton({ onPick }) {
  const [open, setOpen] = useState(false);
  return (
    <span className="emoji-wrap">
      <button type="button" className="tiny-button" onClick={() => setOpen((value) => !value)}>Emoji</button>
      {open ? (
        <span className="emoji-popover">
          {EMOJIS.map((emoji) => <button key={emoji} type="button" onClick={() => { onPick(emoji); setOpen(false); }}>{emoji}</button>)}
        </span>
      ) : null}
    </span>
  );
}

function PhonePreview({ form }) {
  const headerType = String(form.header_type || "").toUpperCase();
  const buttons = Array.isArray(form.buttons) ? form.buttons : [];
  return (
    <div className="phone-preview">
      <div className="phone-top"><strong>Business</strong><span>WhatsApp</span></div>
      <div className="phone-screen">
        <div className="wa-bubble">
          {headerType === "TEXT" && form.header_text ? <strong className="wa-header">{renderTokens(form.header_text)}</strong> : null}
          {["IMAGE", "VIDEO", "DOCUMENT"].includes(headerType) ? <strong className="wa-header">[{headerType}] {form.header_media_handle ? "media listo" : "media pendiente"}</strong> : null}
          <span>{renderTokens(form.body_text) || "[Escribe el body de la plantilla]"}</span>
          {form.footer_text ? <small>{renderTokens(form.footer_text)}</small> : null}
          {buttons.length ? <div className="wa-buttons">{buttons.map((button, idx) => <span key={`${button.type}-${idx}`}>{button.text || `Boton ${idx + 1}`}</span>)}</div> : null}
        </div>
      </div>
    </div>
  );
}

export default function BroadcastPanel({ apiCall, showStatus, onGoCampaigns }) {
  const bodyRef = useRef(null);
  const [activeModule, setActiveModule] = useState("message_template");
  const [metaTemplates, setMetaTemplates] = useState([]);
  const [segments, setSegments] = useState([]);
  const [broadcasts, setBroadcasts] = useState([]);
  const [billing, setBilling] = useState(null);
  const [metaForm, setMetaForm] = useState(emptyMetaForm);
  const [broadcastForm, setBroadcastForm] = useState(emptyBroadcast);
  const [preview, setPreview] = useState(null);
  const [saving, setSaving] = useState("");
  const [loading, setLoading] = useState(true);
  const [reportOpen, setReportOpen] = useState(false);
  const [reportLoading, setReportLoading] = useState(false);
  const [reportData, setReportData] = useState(null);
  const [reportBroadcastId, setReportBroadcastId] = useState("");
  const [reportStatus, setReportStatus] = useState("all");
  const [reportSearch, setReportSearch] = useState("");
  const [reportPage, setReportPage] = useState(1);

  const billingPlan = billing?.plan || {};
  const billingLimits = billingPlan?.limits || {};
  const billingUsage = billing?.usage || {};
  const billingRemaining = billing?.remaining || {};
  const approvedTemplates = useMemo(() => metaTemplates.filter((item) => String(item.status || "").toLowerCase() === "approved"), [metaTemplates]);
  const selectedMetaTemplate = useMemo(() => metaTemplates.find((item) => item.id === broadcastForm.meta_template_id) || null, [metaTemplates, broadcastForm.meta_template_id]);
  const reportCampaign = reportData?.campaign || {};
  const reportMetrics = reportData?.metrics || {};
  const reportRecipients = reportData?.recipients || {};
  const reportItems = reportRecipients?.items || [];
  const reportPages = Number(reportRecipients?.pages || 1);
  const currentReportPage = Number(reportRecipients?.page || reportPage || 1);
  const bodyChars = String(metaForm.body_text || "").length;

  const loadAll = async (silent = false) => {
    setLoading(true);
    try {
      const [metaData, segmentData, broadcastData, billingData] = await Promise.all([
        apiCall("/saas/v1/broadcasts/meta/templates"),
        apiCall("/saas/v1/campaigns/segments"),
        apiCall("/saas/v1/broadcasts"),
        apiCall("/saas/v1/billing/overview"),
      ]);
      setMetaTemplates(metaData?.templates || []);
      setSegments(segmentData?.segments || []);
      setBroadcasts(broadcastData?.broadcasts || []);
      setBilling(billingData);
      if (!silent) showStatus("Mensajeria masiva actualizada", "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadAll(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const insertToken = (token) => {
    const value = `{{${token}}}`;
    const el = bodyRef.current;
    if (!el) {
      setMetaForm((prev) => ({ ...prev, body_text: `${prev.body_text}${value}` }));
      return;
    }
    const start = el.selectionStart || 0;
    const end = el.selectionEnd || 0;
    const current = String(metaForm.body_text || "");
    const next = `${current.slice(0, start)}${value}${current.slice(end)}`;
    setMetaForm((prev) => ({ ...prev, body_text: next }));
    setTimeout(() => { el.focus(); el.setSelectionRange(start + value.length, start + value.length); }, 0);
  };

  const addEmoji = (emoji) => setMetaForm((prev) => ({ ...prev, body_text: `${prev.body_text || ""}${emoji}` }));
  const addButton = (kind) => setMetaForm((prev) => ({ ...prev, buttons: [...(prev.buttons || []), emptyButton(kind)].slice(0, 3) }));
  const updateButton = (idx, patch) => setMetaForm((prev) => ({ ...prev, buttons: (prev.buttons || []).map((button, i) => (i === idx ? { ...button, ...patch } : button)) }));
  const removeButton = (idx) => setMetaForm((prev) => ({ ...prev, buttons: (prev.buttons || []).filter((_, i) => i !== idx) }));

  const rewriteBody = () => {
    const clean = String(metaForm.body_text || "").replace(/\s+\n/g, "\n").replace(/\n{3,}/g, "\n\n").replace(/[ \t]{2,}/g, " ").trim();
    setMetaForm((prev) => ({ ...prev, body_text: clean }));
    showStatus("Texto optimizado localmente", "ok");
  };

  const createMetaTemplate = async () => {
    if (!metaForm.name.trim()) return showStatus("Nombre de plantilla requerido", "error");
    if (!metaForm.body_text.trim()) return showStatus("Body requerido", "error");
    setSaving("meta-create");
    try {
      const data = await apiCall("/saas/v1/broadcasts/meta/templates", { method: "POST", body: JSON.stringify(metaForm) });
      setMetaForm(emptyMetaForm());
      await loadAll(true);
      const status = data?.template?.status || "pending";
      showStatus(`Plantilla Meta creada/sometida: ${status}`, status === "approved" ? "ok" : "neutral");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setSaving("");
    }
  };

  const syncMetaTemplates = async () => {
    setSaving("meta-sync");
    try {
      const data = await apiCall("/saas/v1/broadcasts/meta/templates/sync?limit=300", { method: "POST" });
      setMetaTemplates(data?.templates || []);
      showStatus(`Sincronizacion Meta: ${number(data?.synced || 0)} actualizadas`, "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setSaving("");
    }
  };

  const patchMetaStatus = async (template, status) => {
    setSaving(`tpl-${template.id}`);
    try {
      await apiCall(`/saas/v1/broadcasts/meta/templates/${encodeURIComponent(template.id)}`, { method: "PATCH", body: JSON.stringify({ status }) });
      await loadAll(true);
      showStatus(`Plantilla marcada como ${status}`, "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setSaving("");
    }
  };

  const updateBroadcastForm = (field, value) => {
    setBroadcastForm((prev) => {
      const next = { ...prev, [field]: value };
      if (field === "meta_template_id") {
        const tpl = metaTemplates.find((item) => item.id === value);
        next.body = tpl?.body_text || "";
      }
      return next;
    });
    setPreview(null);
  };

  const previewBroadcast = async () => {
    setSaving("preview");
    try {
      const data = await apiCall("/saas/v1/broadcasts/preview", {
        method: "POST",
        body: JSON.stringify({ channel: broadcastForm.channel, meta_template_id: broadcastForm.meta_template_id || null, segment_id: broadcastForm.segment_id || null, body: broadcastForm.body, limit: 500 }),
      });
      setPreview(data);
      showStatus(`Audiencia estimada: ${number(data?.audience_count)}`, "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setSaving("");
    }
  };

  const createBroadcast = async (enqueue = false) => {
    if (!broadcastForm.name.trim()) return showStatus("Nombre de difusion requerido", "error");
    if (!broadcastForm.meta_template_id) return showStatus("Selecciona una plantilla Meta aprobada", "error");
    if (selectedMetaTemplate?.status !== "approved") return showStatus("La plantilla Meta debe estar aprobada antes de enviar", "error");
    if (!broadcastForm.segment_id) return showStatus("Selecciona un segmento", "error");
    setSaving(enqueue ? "enqueue-new" : "create");
    try {
      const payload = {
        ...broadcastForm,
        meta_template_name: selectedMetaTemplate?.name || "",
        meta_template_language: selectedMetaTemplate?.language || "",
        meta_template_category: selectedMetaTemplate?.category || "",
        meta_template_body: selectedMetaTemplate?.body_text || broadcastForm.body,
      };
      const data = await apiCall("/saas/v1/broadcasts", { method: "POST", body: JSON.stringify(payload) });
      if (enqueue) {
        const queued = await apiCall(`/saas/v1/broadcasts/${encodeURIComponent(data.broadcast.id)}/enqueue`, { method: "POST", body: JSON.stringify({ limit: 500, process_now: false }) });
        showStatus(`Difusion creada y encolada: ${number(queued.queued)} mensajes`, "ok");
      } else {
        showStatus("Difusion guardada", "ok");
      }
      setBroadcastForm(emptyBroadcast());
      setPreview(null);
      await loadAll(true);
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setSaving("");
    }
  };

  const enqueueExisting = async (broadcast) => {
    setSaving(`enqueue-${broadcast.id}`);
    try {
      const data = await apiCall(`/saas/v1/broadcasts/${encodeURIComponent(broadcast.id)}/enqueue`, { method: "POST", body: JSON.stringify({ limit: 500, process_now: false }) });
      showStatus(`Mensajes encolados: ${number(data.queued)}`, "ok");
      await loadAll(true);
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setSaving("");
    }
  };

  const fetchReportPage = async (broadcastId, { status = reportStatus, search = reportSearch, page = reportPage, perPage = 25 } = {}) => {
    const params = new URLSearchParams({
      status: status || "all",
      search: search || "",
      page: String(page || 1),
      per_page: String(perPage || 25),
    });
    return apiCall(`/saas/v1/broadcasts/${encodeURIComponent(broadcastId)}/report?${params.toString()}`);
  };

  const loadReport = async (broadcastId = reportBroadcastId, overrides = {}) => {
    const targetId = broadcastId || reportBroadcastId;
    if (!targetId) return;
    const nextStatus = overrides.status ?? reportStatus;
    const nextSearch = overrides.search ?? reportSearch;
    const nextPage = overrides.page ?? reportPage;
    setReportLoading(true);
    try {
      const data = await fetchReportPage(targetId, { status: nextStatus, search: nextSearch, page: nextPage, perPage: 25 });
      setReportBroadcastId(targetId);
      setReportData(data);
      setReportOpen(true);
      setReportStatus(nextStatus || "all");
      setReportSearch(nextSearch || "");
      setReportPage(Number(data?.recipients?.page || nextPage || 1));
      if (!overrides.silent) showStatus("Informe de difusion cargado", "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setReportLoading(false);
    }
  };

  const openReport = async (broadcast) => {
    setReportData(null);
    setReportStatus("all");
    setReportSearch("");
    setReportPage(1);
    await loadReport(broadcast.id, { status: "all", search: "", page: 1, silent: true });
  };

  const applyReportFilters = async () => {
    setReportPage(1);
    await loadReport(reportBroadcastId, { page: 1 });
  };

  const moveReportPage = async (nextPage) => {
    const safePage = Math.max(1, Math.min(Number(nextPage || 1), reportPages));
    setReportPage(safePage);
    await loadReport(reportBroadcastId, { page: safePage, silent: true });
  };

  const exportReportCsv = async (broadcast) => {
    const targetId = broadcast?.id || reportBroadcastId;
    if (!targetId) return;
    const statusForExport = targetId === reportBroadcastId ? reportStatus : "all";
    const searchForExport = targetId === reportBroadcastId ? reportSearch : "";
    setSaving(`csv-${targetId}`);
    try {
      let page = 1;
      let firstPayload = null;
      const allItems = [];
      do {
        const payload = await fetchReportPage(targetId, { status: statusForExport, search: searchForExport, page, perPage: 500 });
        if (!firstPayload) firstPayload = payload;
        allItems.push(...(payload?.recipients?.items || []));
        page += 1;
      } while (page <= Number(firstPayload?.recipients?.pages || 1));

      const campaign = firstPayload?.campaign || broadcast || {};
      const rows = [
        ["#", "Chat ID", "Nombre", "Status", "Queued at", "Sent at", "Delivered at", "Opened at", "Replied at", "Failed at", "Message ID", "Error", "Body"],
        ...allItems.map((item) => [
          item.index,
          item.chat_id,
          item.name,
          item.status,
          item.queued_at,
          item.sent_at,
          item.delivered_at,
          item.opened_at,
          item.replied_at,
          item.failed_at,
          item.message_id,
          item.error,
          item.body_text,
        ]),
      ];
      downloadCsv(`${safeFilename(campaign.name)}_report.csv`, rows);
      showStatus(`CSV generado: ${number(allItems.length)} destinatarios`, "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setSaving("");
    }
  };

  const retryFailedRecipients = async (broadcastId = reportBroadcastId) => {
    if (!broadcastId) return;
    setSaving(`retry-${broadcastId}`);
    try {
      const data = await apiCall(`/saas/v1/broadcasts/${encodeURIComponent(broadcastId)}/retry-failed?limit=200&process_now=true`, { method: "POST" });
      showStatus(`Fallidos reintentados: ${number(data?.retried || 0)}`, "ok");
      await loadAll(true);
      await loadReport(broadcastId, { silent: true });
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setSaving("");
    }
  };

  return (
    <section className="module-page broadcast-page mass-page">
      <div className="hero-card glass-card">
        <div>
          <p className="eyebrow">WhatsApp Template Manager</p>
          <h2>Mensajeria masiva</h2>
          <p>Broadcast separado de Campanas CRM: crea plantillas oficiales Meta, espera aprobacion/sincronizacion y envia solo con templates aprobadas.</p>
        </div>
        <div className="panel-actions hero-actions"><button type="button" onClick={() => loadAll(false)}>Recargar</button><button type="button" className="primary" onClick={syncMetaTemplates} disabled={saving === "meta-sync"}>{saving === "meta-sync" ? "Sincronizando..." : "Sincronizar Meta"}</button></div>
      </div>

      <div className="mass-module-grid glass-card">
        {MODULES.map(([id, title, description, live], idx) => <button key={id} type="button" className={activeModule === id ? "active" : ""} onClick={() => setActiveModule(id)}><strong>{title}</strong><span>{description}</span><mark className={live ? "ok-chip" : "done-chip"}>{live ? "LIVE" : `SK-${idx + 1}`}</mark></button>)}
      </div>

      {activeModule === "message_template" ? (
        <div className="mass-template-layout">
          <article className="panel glass-card module-card">
            <div className="panel-head"><h2>Plantilla de mensaje</h2><span>{bodyChars} / 1024</span></div>
            <div className="form-grid two">
              <label>Nombre de plantilla *<input value={metaForm.name} onChange={(event) => setMetaForm((prev) => ({ ...prev, name: event.target.value }))} placeholder="system_order_success_notification" /></label>
              <label>Idioma *<select value={metaForm.language} onChange={(event) => setMetaForm((prev) => ({ ...prev, language: event.target.value }))}>{LOCALES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
            </div>
            <div className="button-choice-row">{CATEGORIES.map(([value, label]) => <button key={value} type="button" className={metaForm.category === value ? "active" : ""} onClick={() => setMetaForm((prev) => ({ ...prev, category: value }))}>{label}</button>)}</div>
            <label>Tipo de encabezado *<select value={metaForm.header_type} onChange={(event) => setMetaForm((prev) => ({ ...prev, header_type: event.target.value }))}>{HEADER_TYPES.map(([value, label]) => <option key={value || "none"} value={value}>{label}</option>)}</select></label>
            {metaForm.header_type === "TEXT" ? <label>Texto de encabezado<input value={metaForm.header_text} onChange={(event) => setMetaForm((prev) => ({ ...prev, header_text: event.target.value }))} maxLength={60} /></label> : null}
            {["IMAGE", "VIDEO", "DOCUMENT"].includes(metaForm.header_type) ? <label>Handle de media<input value={metaForm.header_media_handle} onChange={(event) => setMetaForm((prev) => ({ ...prev, header_media_handle: event.target.value }))} placeholder="Handle de Meta" /></label> : null}
            <div className="template-tools"><button type="button" onClick={() => insertToken("customer_name")}>Nombre</button><button type="button" onClick={() => insertToken("customer_city")}>Ciudad</button><button type="button" onClick={() => insertToken("business_name")}>Empresa</button><button type="button" onClick={rewriteBody}>Reescribir con IA</button><EmojiButton onPick={addEmoji} /></div>
            <label>Cuerpo del mensaje *<textarea ref={bodyRef} rows={8} maxLength={1024} value={metaForm.body_text} onChange={(event) => setMetaForm((prev) => ({ ...prev, body_text: event.target.value }))} placeholder="Hola, {{customer_name}}, ..." /></label>
            <label>Texto de pie<input value={metaForm.footer_text} onChange={(event) => setMetaForm((prev) => ({ ...prev, footer_text: event.target.value }))} maxLength={60} placeholder="Atentamente, Equipo Scentra" /></label>
            <div className="template-tools"><button type="button" onClick={() => addButton("QUICK_REPLY")}>+ Respuesta rapida</button><button type="button" onClick={() => addButton("URL")}>+ URL</button><button type="button" onClick={() => addButton("PHONE_NUMBER")}>+ Telefono</button></div>
            <div className="button-editor-list">{(metaForm.buttons || []).map((button, idx) => <div key={`${button.type}-${idx}`}><select value={button.type} onChange={(event) => updateButton(idx, emptyButton(event.target.value))}><option value="QUICK_REPLY">Respuesta rapida</option><option value="URL">URL</option><option value="PHONE_NUMBER">Telefono</option></select><input value={button.text} onChange={(event) => updateButton(idx, { text: event.target.value })} placeholder="Texto del boton" />{button.type === "URL" ? <input value={button.url} onChange={(event) => updateButton(idx, { url: event.target.value })} placeholder="https://..." /> : null}{button.type === "PHONE_NUMBER" ? <input value={button.phone_number} onChange={(event) => updateButton(idx, { phone_number: event.target.value })} placeholder="+573..." /> : null}<button type="button" onClick={() => removeButton(idx)}>x</button></div>)}</div>
            <label className="check-row"><input type="checkbox" checked={metaForm.allow_category_change} onChange={(event) => setMetaForm((prev) => ({ ...prev, allow_category_change: event.target.checked }))} /> Permitir ajuste de categoria por Meta</label>
            <div className="panel-actions"><button type="button" className="primary" onClick={createMetaTemplate} disabled={saving === "meta-create"}>{saving === "meta-create" ? "Creando..." : "Crear plantilla en Meta"}</button><button type="button" onClick={() => setMetaForm(emptyMetaForm())}>Limpiar</button></div>
          </article>

          <aside className="mass-side-stack">
            <article className="panel glass-card"><div className="panel-head"><h2>Vista previa</h2><span>chat</span></div><PhonePreview form={metaForm} /></article>
            <article className="panel glass-card meta-template-list"><div className="panel-head"><h2>Plantillas de Meta</h2><span>{loading ? "cargando" : number(metaTemplates.length)}</span></div><div className="mini-table">{metaTemplates.map((tpl) => <div key={tpl.id}><strong>{tpl.name}</strong><span><mark className={statusClass(tpl.status)}>{String(tpl.status || "pending").toUpperCase()}</mark> {tpl.category} / {tpl.language}</span><p>{tpl.body_text || "[Sin body]"}</p><div className="panel-actions"><button type="button" onClick={() => patchMetaStatus(tpl, "approved")} disabled={saving === `tpl-${tpl.id}`}>Aprobar local</button><button type="button" onClick={() => patchMetaStatus(tpl, "rejected")} disabled={saving === `tpl-${tpl.id}`}>Rechazar</button></div></div>)}{metaTemplates.length === 0 ? <div className="empty">No hay plantillas Meta sincronizadas.</div> : null}</div></article>
          </aside>
        </div>
      ) : null}

      {activeModule === "broadcast_campaign" ? (
        <div className="module-grid broadcast-layout">
          <article className="panel glass-card module-card"><div className="panel-head"><h2>Crear broadcast</h2><span>{number(billingRemaining.monthly_messages)} mensajes disponibles</span></div><form className="campaign-form" onSubmit={(event) => { event.preventDefault(); createBroadcast(false); }}><label>Nombre<input value={broadcastForm.name} onChange={(event) => updateBroadcastForm("name", event.target.value)} placeholder="Promo VIP mayo" /></label><div className="form-grid two"><label>Plantilla Meta aprobada<select value={broadcastForm.meta_template_id} onChange={(event) => updateBroadcastForm("meta_template_id", event.target.value)}><option value="">Seleccionar plantilla</option>{approvedTemplates.map((template) => <option key={template.id} value={template.id}>{template.name} / {template.language}</option>)}</select></label><label>Segmento<select value={broadcastForm.segment_id} onChange={(event) => updateBroadcastForm("segment_id", event.target.value)}><option value="">Seleccionar segmento</option>{segments.map((segment) => <option key={segment.id} value={segment.id}>{segment.name} ({segment.audience_count})</option>)}</select></label><label>Estado<select value={broadcastForm.status} onChange={(event) => updateBroadcastForm("status", event.target.value)}><option value="draft">Borrador</option><option value="scheduled">Programada</option></select></label><label>Programar<input type="datetime-local" value={broadcastForm.scheduled_at} onChange={(event) => updateBroadcastForm("scheduled_at", event.target.value)} /></label></div><label>Body de referencia<textarea rows={7} value={broadcastForm.body} onChange={(event) => updateBroadcastForm("body", event.target.value)} /></label><div className="panel-actions"><button type="button" onClick={previewBroadcast} disabled={saving === "preview"}>{saving === "preview" ? "Calculando..." : "Previsualizar"}</button><button type="submit" className="primary" disabled={saving === "create"}>Guardar</button><button type="button" className="primary" onClick={() => createBroadcast(true)} disabled={saving === "enqueue-new"}>Crear y encolar</button><button type="button" onClick={onGoCampaigns}>Crear segmentos</button></div></form></article>
          <article className="panel glass-card module-card"><div className="panel-head"><h2>Control de envio</h2><span>plan {billingPlan.plan_code || "starter"}</span></div><div className="quota-ring"><strong>{pct(billingUsage.used_monthly_messages, billingLimits.max_monthly_messages)}%</strong><span>uso mensual</span></div><div className="rule-list"><div><strong>Plantillas aprobadas</strong><span>{number(approvedTemplates.length)} disponibles para broadcast.</span></div><div><strong>Audiencia preview</strong><span>{preview ? `${number(preview.audience_count)} contactos` : "Calcula antes de enviar"}</span></div><div><strong>Regla SaaS</strong><span>No se encola si Meta no esta aprobada.</span></div></div></article>
        </div>
      ) : null}

      {activeModule === "broadcast_campaign" && preview ? <article className="panel glass-card"><div className="panel-head"><h2>Preview de destinatarios</h2><span>{number(preview.audience_count)} contactos</span></div><div className="mini-table preview-table">{(preview.sample || []).map((item) => <div key={item.conversation_id}><strong>{item.display_name}</strong><span>{item.recipient}</span><p>{item.body}</p></div>)}</div></article> : null}

      {activeModule === "broadcast_campaign" ? (
        <article className="panel glass-card">
          <div className="panel-head"><h2>Difusiones</h2><span>{loading ? "cargando" : number(broadcasts.length)}</span></div>
          <div className="mini-table">
            {broadcasts.map((broadcast) => {
              const metrics = broadcast.metrics_json || {};
              const sentCount = Number(metrics.sent ?? broadcast.sent_count ?? 0);
              const failedCount = Number(metrics.failed ?? broadcast.failed_count ?? 0);
              const totalCount = Number(metrics.total ?? broadcast.queued_count ?? 0);
              return (
                <div key={broadcast.id} className="broadcast-row-card">
                  <strong>{broadcast.name}</strong>
                  <span>{broadcast.status} / {broadcast.segment_name || "sin segmento"} / {number(broadcast.queued_count)} en cola</span>
                  <p>{broadcast.meta_template_name || broadcast.template_name || "Mensaje manual"} / audiencia {number(broadcast.audience_count)}</p>
                  <div className="broadcast-mini-metrics">
                    <mark className="done-chip">{number(totalCount)} total</mark>
                    <mark className="ok-chip">{number(sentCount)} enviados</mark>
                    <mark className={failedCount ? "danger-chip" : "done-chip"}>{number(failedCount)} fallidos</mark>
                  </div>
                  <div className="panel-actions">
                    <button type="button" disabled={Number(broadcast.queued_count || 0) > 0 || saving === `enqueue-${broadcast.id}`} onClick={() => enqueueExisting(broadcast)}>{saving === `enqueue-${broadcast.id}` ? "Encolando..." : Number(broadcast.queued_count || 0) > 0 ? "Ya encolada" : "Encolar"}</button>
                    <button type="button" onClick={() => openReport(broadcast)} disabled={reportLoading && reportBroadcastId === broadcast.id}>{reportLoading && reportBroadcastId === broadcast.id ? "Cargando..." : "Informe"}</button>
                    <button type="button" onClick={() => exportReportCsv(broadcast)} disabled={saving === `csv-${broadcast.id}`}>{saving === `csv-${broadcast.id}` ? "Generando..." : "CSV"}</button>
                    <button type="button" onClick={() => retryFailedRecipients(broadcast.id)} disabled={!failedCount || saving === `retry-${broadcast.id}`}>{saving === `retry-${broadcast.id}` ? "Reintentando..." : "Reintentar fallidos"}</button>
                  </div>
                </div>
              );
            })}
            {!loading && broadcasts.length === 0 ? <div className="empty">Sin difusiones todavia.</div> : null}
          </div>
        </article>
      ) : null}

      {reportOpen ? (
        <div className="modal-backdrop report-backdrop" role="presentation" onMouseDown={() => setReportOpen(false)}>
          <section className="modal-window glass-card report-window" role="dialog" aria-modal="true" aria-label="Informe de difusion" onMouseDown={(event) => event.stopPropagation()}>
            <div className="panel-head">
              <div>
                <h2>Informe de difusion</h2>
                <span>{reportCampaign.name || "Broadcast"} / {reportCampaign.segment_name || "sin segmento"}</span>
              </div>
              <div className="panel-actions compact-actions">
                <button type="button" onClick={() => loadReport(reportBroadcastId, { silent: true })} disabled={reportLoading}>{reportLoading ? "Actualizando..." : "Actualizar"}</button>
                <button type="button" onClick={() => exportReportCsv()} disabled={saving === `csv-${reportBroadcastId}`}>{saving === `csv-${reportBroadcastId}` ? "Generando..." : "Exportar CSV"}</button>
                <button type="button" onClick={() => setReportOpen(false)}>Cerrar</button>
              </div>
            </div>

            <div className="report-kpi-grid">
              {REPORT_METRICS.map(([key, label]) => (
                <div key={key} className="report-kpi">
                  <span>{label}</span>
                  <strong>{number(reportMetrics[key])}</strong>
                  {key !== "targeted" ? <small>{number(reportMetricPct(reportMetrics, key))}%</small> : <small>{reportMetrics.status || reportCampaign.status || "draft"}</small>}
                </div>
              ))}
            </div>

            <div className="report-progress">
              <div><span style={{ width: `${Math.min(100, Number(reportMetrics.sent_pct || 0))}%` }} /></div>
              <p>{number(reportMetrics.sent_pct || 0)}% enviado / {number(reportMetrics.failed_pct || 0)}% fallido / {number(reportMetrics.reply_rate_pct || 0)}% respuesta</p>
            </div>

            <div className="report-filter-bar">
              <select value={reportStatus} onChange={(event) => setReportStatus(event.target.value)}>{REPORT_STATUSES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
              <input value={reportSearch} onChange={(event) => setReportSearch(event.target.value)} placeholder="Buscar por nombre, telefono, error o mensaje..." />
              <button type="button" className="primary" onClick={applyReportFilters} disabled={reportLoading}>Filtrar</button>
              <button type="button" onClick={() => { setReportStatus("all"); setReportSearch(""); loadReport(reportBroadcastId, { status: "all", search: "", page: 1, silent: true }); }}>Limpiar</button>
              <button type="button" onClick={() => retryFailedRecipients(reportBroadcastId)} disabled={!Number(reportMetrics.failed || 0) || saving === `retry-${reportBroadcastId}`}>Reintentar fallidos</button>
            </div>

            <div className="report-rules">
              <span>Canal: <strong>{reportData?.rules_summary?.channel || "whatsapp"}</strong></span>
              <span>Etiqueta: <strong>{(reportData?.rules_summary?.included_labels || []).join(", ") || "todas"}</strong></span>
              <span>Ciudad: <strong>{reportData?.rules_summary?.city || "N/A"}</strong></span>
              <span>Etapa CRM: <strong>{reportData?.rules_summary?.crm_stage || "N/A"}</strong></span>
            </div>

            <div className="report-table-wrap">
              <table className="report-table">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>Cliente</th>
                    <th>Status</th>
                    <th>Enviado</th>
                    <th>Mensaje</th>
                    <th>Error</th>
                  </tr>
                </thead>
                <tbody>
                  {reportItems.map((item) => (
                    <tr key={item.recipient_id}>
                      <td>{item.index}</td>
                      <td><strong>{item.name || "Sin nombre"}</strong><small>{item.chat_id || "-"}</small></td>
                      <td><mark className={reportStatusClass(item.status)}>{reportStatusLabel(item.status)}</mark></td>
                      <td><small>{formatDate(item.sent_at || item.queued_at)}</small>{item.message_id ? <small>{item.message_id}</small> : null}</td>
                      <td>{item.body_text || "-"}</td>
                      <td>{item.error || "-"}</td>
                    </tr>
                  ))}
                  {!reportLoading && reportItems.length === 0 ? <tr><td colSpan="6" className="empty-cell">No hay destinatarios para este filtro.</td></tr> : null}
                </tbody>
              </table>
            </div>

            <div className="report-pagination">
              <span>{number(reportRecipients.filtered_total || 0)} de {number(reportRecipients.total || 0)} destinatarios</span>
              <div className="panel-actions compact-actions">
                <button type="button" onClick={() => moveReportPage(currentReportPage - 1)} disabled={currentReportPage <= 1 || reportLoading}>Anterior</button>
                <mark className="done-chip">{currentReportPage} / {reportPages}</mark>
                <button type="button" onClick={() => moveReportPage(currentReportPage + 1)} disabled={currentReportPage >= reportPages || reportLoading}>Siguiente</button>
              </div>
            </div>
          </section>
        </div>
      ) : null}
    </section>
  );
}
