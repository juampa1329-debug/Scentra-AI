import React, { useEffect, useMemo, useState } from "react";
import "./SaasTriggerBuilderPanel.css";

const EMOJIS = ["✨", "🔥", "💎", "🎁", "👇", "🙌", "✅", "🛍️", "📦", "⏳", "💬", "🧪"];

const fallbackCatalog = {
  event_types: [
    { key: "message_in", label: "Mensaje entrante" },
    { key: "message_out", label: "Mensaje saliente" },
    { key: "comment_in", label: "Comentario entrante" },
    { key: "tag_changed", label: "Etiqueta cambiada" },
    { key: "time", label: "Tiempo" },
  ],
  trigger_types: [
    { key: "none", label: "Ninguna" },
    { key: "tag_changed", label: "Etiqueta cambiada" },
    { key: "logic", label: "Logica" },
    { key: "message_flow", label: "Flujo de mensajes" },
    { key: "comment_flow", label: "Flujo de comentarios" },
    { key: "time", label: "Tiempo" },
  ],
  flow_events: [
    { key: "received", label: "Recibido" },
    { key: "sent", label: "Enviado" },
    { key: "both", label: "Envia y recibe" },
  ],
  assistant_message_types: [
    { key: "auto", label: "Auto" },
    { key: "text", label: "Texto" },
    { key: "audio", label: "Audio" },
  ],
  condition_types: [
    { key: "last_message_sent", label: "Ultimo mensaje enviado" },
    { key: "sent_count", label: "Cantidad de mensajes enviados" },
    { key: "check_words", label: "Comprobar palabras" },
    { key: "comment_keywords", label: "Palabras clave en comentario" },
    { key: "template_sent_status", label: "Plantilla enviada/no enviada" },
    { key: "current_tag", label: "Etiqueta actual" },
    { key: "schedule", label: "Horario" },
  ],
  action_types: [
    { key: "send_template", label: "Enviar plantilla de mensaje" },
    { key: "reply_comment", label: "Responder comentario" },
    { key: "change_tag", label: "Cambiar etiqueta" },
    { key: "configure_conversation", label: "Configurar conversacion" },
    { key: "change_contact_status", label: "Cambiar estado contacto" },
    { key: "notify_admins", label: "Notificar administradores" },
    { key: "extract_conversation_info", label: "Extraer informacion" },
    { key: "schedule_message", label: "Programar mensaje" },
  ],
};

const conditionMenuGroups = [
  ["last_message_sent", "sent_count", "check_words", "comment_keywords"],
  ["template_sent_status", "current_tag", "schedule"],
];

const weekDays = [
  { key: "mon", label: "Lun" },
  { key: "tue", label: "Mar" },
  { key: "wed", label: "Mie" },
  { key: "thu", label: "Jue" },
  { key: "fri", label: "Vie" },
  { key: "sat", label: "Sab" },
  { key: "sun", label: "Dom" },
];

function blankTrigger() {
  return {
    id: "",
    name: "",
    channel: "whatsapp",
    event_type: "message_in",
    trigger_type: "message_flow",
    flow_event: "received",
    cooldown_minutes: 60,
    priority: 100,
    is_active: true,
    assistant_enabled: false,
    assistant_message_type: "auto",
    block_ai: true,
    stop_on_match: true,
    only_when_no_takeover: true,
  };
}

function blankCondition(type = "check_words") {
  if (type === "comment_keywords") return { type, mode: "any", words: [] };
  if (type === "template_sent_status") return { type, state: "not_sent", template_id: "" };
  if (type === "current_tag") return { type, state: "has", tag: "" };
  if (type === "last_message_sent") return { type, op: "gte", minutes: 10 };
  if (type === "sent_count") return { type, op: "gte", value: 1, window_hours: 24 };
  if (type === "schedule") return { type, timezone: "America/Bogota", start_time: "08:00", end_time: "20:00", days: ["mon", "tue", "wed", "thu", "fri", "sat"] };
  return { type: "check_words", mode: "any", words: [] };
}

function blankAction(type = "send_template") {
  if (type === "reply_comment") return { type, mode: "text", use_ai: false, reply_text: "", ai_prompt: "", template_id: "" };
  if (type === "change_tag") return { type, mode: "add", tag: "" };
  if (type === "configure_conversation") return { type, takeover: "keep", ai_state: "", clear_ai_state: false };
  if (type === "change_contact_status") return { type, field: "customer_type", status: "" };
  if (type === "notify_admins") return { type, phones: "", message: "" };
  if (type === "extract_conversation_info") return { type, last_messages: 10 };
  if (type === "schedule_message") return { type, template_id: "", delay_minutes: 30 };
  return { type: "send_template", template_id: "" };
}

function normalizeConditions(raw) {
  const root = raw && typeof raw === "object" ? raw : {};
  let rows = Array.isArray(root.conditions) ? root.conditions : [];
  if (!rows.length && Array.isArray(root.all)) rows = root.all;
  if (!rows.length && root.contains) rows = [{ type: "check_words", words: [String(root.contains)] }];
  return rows.filter((x) => x && typeof x === "object");
}

function normalizeActions(raw) {
  const root = raw && typeof raw === "object" ? raw : {};
  let rows = Array.isArray(root.actions) ? root.actions : [];
  if (!rows.length && Array.isArray(root.list)) rows = root.list;
  if (!rows.length && root.type) rows = [root];
  return rows.filter((x) => x && typeof x === "object");
}

function cleanConditions(conditions) {
  return (conditions || [])
    .map((c) => {
      const type = String(c?.type || "").trim().toLowerCase();
      if (!type) return null;
      if (type === "check_words" || type === "comment_keywords") {
        const words = Array.isArray(c.words) ? c.words.map((w) => String(w || "").trim()).filter(Boolean) : [];
        return { type, mode: c.mode === "all" ? "all" : "any", words };
      }
      if (type === "template_sent_status") return { type, state: c.state === "sent" ? "sent" : "not_sent", template_id: c.template_id || null };
      if (type === "current_tag") return { type, state: c.state === "not_has" ? "not_has" : "has", tag: String(c.tag || "").trim() };
      if (type === "last_message_sent") return { type, op: c.op || "gte", minutes: Number(c.minutes || 0) };
      if (type === "sent_count") return { type, op: c.op || "gte", value: Number(c.value || 0), window_hours: Number(c.window_hours || 24) };
      if (type === "schedule") {
        return {
          type,
          timezone: String(c.timezone || "America/Bogota").trim(),
          start_time: String(c.start_time || "08:00"),
          end_time: String(c.end_time || "20:00"),
          days: Array.isArray(c.days) ? c.days.map((d) => String(d || "").slice(0, 3).toLowerCase()) : [],
        };
      }
      return c;
    })
    .filter(Boolean);
}

function cleanActions(actions) {
  return (actions || [])
    .map((a) => {
      const type = String(a?.type || "").trim().toLowerCase();
      if (!type) return null;
      if (type === "send_template") return { type, template_id: a.template_id || null };
      if (type === "reply_comment") {
        const rawMode = String(a.mode || "").trim().toLowerCase();
        const mode = rawMode === "template" ? "template" : (rawMode === "ai" || a.use_ai ? "ai" : "text");
        return {
          type,
          mode,
          use_ai: mode === "ai",
          reply_text: String(a.reply_text || a.text || "").trim(),
          ai_prompt: String(a.ai_prompt || "").trim(),
          template_id: a.template_id || null,
          template_name: String(a.template_name || "").trim(),
        };
      }
      if (type === "change_tag") return { type, mode: a.mode || "add", tag: String(a.tag || "").trim() };
      if (type === "configure_conversation") return { type, takeover: String(a.takeover || "keep"), ai_state: String(a.ai_state || "").trim(), clear_ai_state: !!a.clear_ai_state };
      if (type === "change_contact_status") return { type, field: a.field || "customer_type", status: String(a.status || "").trim() };
      if (type === "notify_admins") return { type, phones: String(a.phones || "").trim(), message: String(a.message || "").trim() };
      if (type === "extract_conversation_info") return { type, last_messages: Number(a.last_messages || 10) };
      if (type === "schedule_message") return { type, template_id: a.template_id || null, delay_minutes: Number(a.delay_minutes || 0) };
      return a;
    })
    .filter(Boolean);
}

function labelFor(items, key, fallback = "") {
  const row = (items || []).find((x) => String(x?.key || "") === String(key || ""));
  return row?.label || fallback || String(key || "");
}

function EmojiButton({ onPick, title = "Emoji" }) {
  const [open, setOpen] = useState(false);
  return (
    <span className="saas-emoji-wrap">
      <button type="button" className="tiny-button" onClick={() => setOpen((v) => !v)}>{title}</button>
      {open ? (
        <span className="emoji-popover">
          {EMOJIS.map((emoji) => <button type="button" key={emoji} onClick={() => { onPick(emoji); setOpen(false); }}>{emoji}</button>)}
        </span>
      ) : null}
    </span>
  );
}

export default function SaasTriggerBuilderPanel({ apiCall, templates = [], triggers = [], onReload, showStatus }) {
  const [catalog, setCatalog] = useState(fallbackCatalog);
  const [selectedTriggerId, setSelectedTriggerId] = useState("");
  const [form, setForm] = useState(blankTrigger());
  const [conditionMode, setConditionMode] = useState("all");
  const [conditions, setConditions] = useState([]);
  const [actions, setActions] = useState([]);
  const [builderTab, setBuilderTab] = useState("conditions");
  const [wordDraft, setWordDraft] = useState({});
  const [conditionMenuOpen, setConditionMenuOpen] = useState(false);
  const [actionMenuOpen, setActionMenuOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [search, setSearch] = useState("");

  useEffect(() => {
    let live = true;
    apiCall("/saas/v1/campaigns/triggers/catalog")
      .then((data) => { if (live) setCatalog({ ...fallbackCatalog, ...(data || {}) }); })
      .catch((err) => showStatus?.(String(err.message || err), "error"));
    return () => { live = false; };
  }, [apiCall, showStatus]);

  useEffect(() => {
    if (!selectedTriggerId && triggers?.[0]?.id) setSelectedTriggerId(triggers[0].id);
  }, [triggers, selectedTriggerId]);

  useEffect(() => {
    setConditionMenuOpen(false);
    setActionMenuOpen(false);
  }, [builderTab]);

  useEffect(() => {
    if (!selectedTriggerId) {
      setForm(blankTrigger());
      setConditionMode("all");
      setConditions([]);
      setActions([]);
      return;
    }
    const row = (triggers || []).find((item) => String(item.id) === String(selectedTriggerId));
    if (!row) return;
    const conditionRoot = row.conditions_json && typeof row.conditions_json === "object" ? row.conditions_json : {};
    setForm({
      id: row.id || "",
      name: row.name || "",
      channel: row.channel || "whatsapp",
      event_type: row.event_type || "message_in",
      trigger_type: row.trigger_type || "message_flow",
      flow_event: row.flow_event || "received",
      cooldown_minutes: Number(row.cooldown_minutes || 0),
      priority: Number(row.priority || 100),
      is_active: !!row.is_active,
      assistant_enabled: !!row.assistant_enabled,
      assistant_message_type: row.assistant_message_type || "auto",
      block_ai: !!row.block_ai,
      stop_on_match: !!row.stop_on_match,
      only_when_no_takeover: !!row.only_when_no_takeover,
    });
    setConditionMode(conditionRoot.match === "any" ? "any" : "all");
    setConditions(normalizeConditions(row.conditions_json));
    setActions(normalizeActions(row.actions_json || row.action_json));
  }, [selectedTriggerId, triggers]);

  const eventTypes = catalog.event_types || fallbackCatalog.event_types;
  const triggerTypes = catalog.trigger_types || fallbackCatalog.trigger_types;
  const flowEvents = catalog.flow_events || fallbackCatalog.flow_events;
  const assistantTypes = catalog.assistant_message_types || fallbackCatalog.assistant_message_types;
  const conditionTypes = catalog.condition_types || fallbackCatalog.condition_types;
  const actionTypes = catalog.action_types || fallbackCatalog.action_types;
  const filteredTriggers = useMemo(() => {
    const term = search.trim().toLowerCase();
    if (!term) return triggers || [];
    return (triggers || []).filter((item) => `${item.name} ${item.event_type} ${item.trigger_type}`.toLowerCase().includes(term));
  }, [triggers, search]);

  const updateCondition = (idx, patch) => setConditions((prev) => prev.map((c, i) => (i === idx ? { ...c, ...patch } : c)));
  const updateAction = (idx, patch) => setActions((prev) => prev.map((a, i) => (i === idx ? { ...a, ...patch } : a)));

  const moveItem = (kind, idx, direction) => {
    const setter = kind === "condition" ? setConditions : setActions;
    setter((prev) => {
      const next = [...prev];
      const to = idx + direction;
      if (to < 0 || to >= next.length) return prev;
      [next[idx], next[to]] = [next[to], next[idx]];
      return next;
    });
  };

  const preset = (kind) => {
    setSelectedTriggerId("");
    if (kind === "comment") {
      setForm({ ...blankTrigger(), name: "Auto respuesta comentarios", event_type: "comment_in", trigger_type: "comment_flow", cooldown_minutes: 45 });
      setConditionMode("any");
      setConditions([{ type: "comment_keywords", mode: "any", words: ["precio", "info"] }]);
      setActions([{ type: "reply_comment", mode: "text", reply_text: "Hola, te escribimos por interno para ayudarte." }]);
      return;
    }
    if (kind === "schedule") {
      setForm({ ...blankTrigger(), name: "Seguimiento programado", event_type: "message_out", trigger_type: "message_flow", flow_event: "sent", cooldown_minutes: 120 });
      setConditionMode("all");
      setConditions([{ type: "last_message_sent", op: "gte", minutes: 120 }, blankCondition("schedule")]);
      setActions([{ type: "schedule_message", template_id: templates[0]?.id || "", delay_minutes: 30 }]);
      return;
    }
    setForm({ ...blankTrigger(), name: "Respuesta por palabras clave" });
    setConditionMode("all");
    setConditions([{ type: "check_words", mode: "any", words: ["precio", "valor"] }]);
    setActions([{ type: "send_template", template_id: templates[0]?.id || "" }]);
  };

  const addCondition = (type) => {
    setConditions((prev) => [...prev, blankCondition(type)]);
    setConditionMenuOpen(false);
  };

  const addAction = (type) => {
    setActions((prev) => [...prev, blankAction(type)]);
    setActionMenuOpen(false);
  };

  const saveTrigger = async () => {
    const payload = {
      name: String(form.name || "").trim(),
      channel: String(form.channel || "whatsapp").trim().toLowerCase() || "whatsapp",
      event_type: form.event_type || "message_in",
      trigger_type: form.trigger_type || "message_flow",
      flow_event: form.flow_event || "received",
      cooldown_minutes: Number(form.cooldown_minutes || 0),
      priority: Number(form.priority || 100),
      is_active: !!form.is_active,
      assistant_enabled: !!form.assistant_enabled,
      assistant_message_type: form.assistant_message_type || "auto",
      block_ai: !!form.block_ai,
      stop_on_match: !!form.stop_on_match,
      only_when_no_takeover: !!form.only_when_no_takeover,
      conditions_json: { match: conditionMode, conditions: cleanConditions(conditions) },
      actions_json: { actions: cleanActions(actions) },
    };
    if (!payload.name) return showStatus?.("Nombre del trigger requerido.", "error");

    setSaving(true);
    try {
      const isUpdate = Boolean(form.id);
      const path = isUpdate ? `/saas/v1/campaigns/triggers/${encodeURIComponent(form.id)}` : "/saas/v1/campaigns/triggers";
      const data = await apiCall(path, { method: isUpdate ? "PATCH" : "POST", body: JSON.stringify(payload) });
      await onReload?.();
      const id = data?.trigger?.id || form.id;
      if (id) setSelectedTriggerId(id);
      showStatus?.(isUpdate ? "Trigger actualizado." : "Trigger creado.", "ok");
    } catch (err) {
      showStatus?.(String(err.message || err), "error");
    } finally {
      setSaving(false);
    }
  };

  const toggleActive = async (trigger) => {
    try {
      await apiCall(`/saas/v1/campaigns/triggers/${encodeURIComponent(trigger.id)}`, {
        method: "PATCH",
        body: JSON.stringify({ is_active: !trigger.is_active }),
      });
      await onReload?.();
      showStatus?.(trigger.is_active ? "Trigger pausado." : "Trigger activado.", "ok");
    } catch (err) {
      showStatus?.(String(err.message || err), "error");
    }
  };

  const copyTrigger = async (trigger) => {
    try {
      const data = await apiCall(`/saas/v1/campaigns/triggers/${encodeURIComponent(trigger.id)}/copy`, {
        method: "POST",
        body: JSON.stringify({ channel: trigger.channel || "whatsapp" }),
      });
      await onReload?.();
      if (data?.trigger?.id) setSelectedTriggerId(data.trigger.id);
      showStatus?.("Trigger duplicado.", "ok");
    } catch (err) {
      showStatus?.(String(err.message || err), "error");
    }
  };

  const deleteTrigger = async (trigger) => {
    const ok = window.confirm(`Se eliminara el trigger "${trigger?.name || ""}". Esta accion no se puede deshacer.\n\nContinuar?`);
    if (!ok) return;
    try {
      await apiCall(`/saas/v1/campaigns/triggers/${encodeURIComponent(trigger.id)}`, { method: "DELETE" });
      if (String(selectedTriggerId) === String(trigger.id)) setSelectedTriggerId("");
      await onReload?.();
      showStatus?.("Trigger eliminado.", "ok");
    } catch (err) {
      showStatus?.(String(err.message || err), "error");
    }
  };

  const renderTemplateOptions = () => (
    <>
      <option value="">Plantilla</option>
      {(templates || []).map((template) => (
        <option key={template.id} value={template.id}>{template.name} ({template.status})</option>
      ))}
    </>
  );

  return (
    <div className="saas-trigger-layout">
      <article className="panel glass-card saas-trigger-sidebar">
        <div className="panel-head">
          <div>
            <h2>Motor de triggers</h2>
            <span>Replica del constructor original</span>
          </div>
          <button type="button" onClick={() => setSelectedTriggerId("")}>Nuevo</button>
        </div>
        <div className="trigger-preset-row">
          <button type="button" onClick={() => preset("message")}>Preset mensajes</button>
          <button type="button" onClick={() => preset("comment")}>Preset comentarios</button>
          <button type="button" onClick={() => preset("schedule")}>Preset horario</button>
        </div>
        <input placeholder="Buscar trigger..." value={search} onChange={(event) => setSearch(event.target.value)} />
        <div className="trigger-list">
          {filteredTriggers.map((trigger) => (
            <div key={trigger.id} className={`trigger-list-item ${String(selectedTriggerId) === String(trigger.id) ? "active" : ""}`}>
              <button type="button" className="trigger-list-main" onClick={() => setSelectedTriggerId(trigger.id)}>
                <strong>{trigger.name}</strong>
                <span>{labelFor(triggerTypes, trigger.trigger_type)} / {labelFor(eventTypes, trigger.event_type)} / prioridad {trigger.priority}</span>
                <small>cooldown {trigger.cooldown_minutes} min / ejecuciones {trigger.executions_count || 0}</small>
              </button>
              <div className="trigger-list-actions">
                <button type="button" onClick={() => toggleActive(trigger)}>{trigger.is_active ? "OFF" : "ON"}</button>
                <button type="button" onClick={() => copyTrigger(trigger)}>Copiar</button>
                <button type="button" className="danger-button" onClick={() => deleteTrigger(trigger)}>Eliminar</button>
              </div>
            </div>
          ))}
          {!filteredTriggers.length ? <div className="empty">No hay triggers creados todavia.</div> : null}
        </div>
      </article>

      <article className="panel glass-card saas-trigger-editor">
        <div className="panel-head">
          <div>
            <h2>{form.id ? form.name || "Trigger" : "Nuevo trigger"}</h2>
            <span>Disparador, condiciones y acciones</span>
          </div>
          <mark className={form.is_active ? "ok-chip" : "warn-chip"}>{form.is_active ? "activo" : "pausado"}</mark>
        </div>

        <div className="trigger-form-grid">
          <label>Nombre<input value={form.name} onChange={(event) => setForm((prev) => ({ ...prev, name: event.target.value }))} /></label>
          <label>Canal<select value={form.channel} onChange={(event) => setForm((prev) => ({ ...prev, channel: event.target.value }))}><option value="whatsapp">WhatsApp</option><option value="facebook">Facebook</option><option value="instagram">Instagram</option><option value="tiktok">TikTok</option></select></label>
          <label>Evento<select value={form.event_type} onChange={(event) => setForm((prev) => ({ ...prev, event_type: event.target.value }))}>{eventTypes.map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}</select></label>
          <label>Tipo<select value={form.trigger_type} onChange={(event) => {
            const next = event.target.value;
            setForm((prev) => ({ ...prev, trigger_type: next, event_type: next === "comment_flow" ? "comment_in" : prev.event_type }));
          }}>{triggerTypes.map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}</select></label>
          <label>Evento de flujo<select value={form.flow_event} onChange={(event) => setForm((prev) => ({ ...prev, flow_event: event.target.value }))}>{flowEvents.map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}</select></label>
          <label>Tipo asistente<select value={form.assistant_message_type} onChange={(event) => setForm((prev) => ({ ...prev, assistant_message_type: event.target.value }))}>{assistantTypes.map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}</select></label>
          <label>Cooldown minutos<input type="number" min="0" value={form.cooldown_minutes} onChange={(event) => setForm((prev) => ({ ...prev, cooldown_minutes: event.target.value }))} /></label>
          <label>Prioridad<input type="number" min="1" value={form.priority} onChange={(event) => setForm((prev) => ({ ...prev, priority: event.target.value }))} /></label>
        </div>

        <div className="trigger-switch-grid">
          <label className="check-row"><input type="checkbox" checked={form.is_active} onChange={(event) => setForm((prev) => ({ ...prev, is_active: event.target.checked }))} /> Activo</label>
          <label className="check-row"><input type="checkbox" checked={form.assistant_enabled} onChange={(event) => setForm((prev) => ({ ...prev, assistant_enabled: event.target.checked }))} /> Enviar mensaje generado por asistente</label>
          <label className="check-row"><input type="checkbox" checked={form.block_ai} onChange={(event) => setForm((prev) => ({ ...prev, block_ai: event.target.checked }))} /> Bloquear IA si matchea</label>
          <label className="check-row"><input type="checkbox" checked={form.stop_on_match} onChange={(event) => setForm((prev) => ({ ...prev, stop_on_match: event.target.checked }))} /> Detener al primer match</label>
          <label className="check-row"><input type="checkbox" checked={form.only_when_no_takeover} onChange={(event) => setForm((prev) => ({ ...prev, only_when_no_takeover: event.target.checked }))} /> Solo sin takeover humano</label>
        </div>

        <div className="trigger-builder-tabs">
          <button type="button" className={builderTab === "conditions" ? "active danger-tab" : ""} onClick={() => setBuilderTab("conditions")}>Condiciones</button>
          <button type="button" className={builderTab === "actions" ? "active success-tab" : ""} onClick={() => setBuilderTab("actions")}>Acciones</button>
        </div>

        {builderTab === "conditions" ? (
          <div className="trigger-rule-stack">
            <div className="trigger-add-wrap">
              <button type="button" className="trigger-add-condition" onClick={() => setConditionMenuOpen((value) => !value)}>Agregar condicion</button>
              {conditionMenuOpen ? (
                <div className="trigger-dropdown">
                  {conditionMenuGroups.map((group, groupIdx) => (
                    <div key={groupIdx}>
                      {group.map((key) => <button type="button" key={key} onClick={() => addCondition(key)}>{labelFor(conditionTypes, key, key)}</button>)}
                      {groupIdx < conditionMenuGroups.length - 1 ? <hr /> : null}
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
            <label>Modo de coincidencia<select value={conditionMode} onChange={(event) => setConditionMode(event.target.value)}><option value="all">Cumplir todas</option><option value="any">Cumplir alguna</option></select></label>
            {conditions.map((condition, idx) => (
              <div className="trigger-rule-card" key={`${idx}-${condition.type}`}>
                <div className="trigger-rule-head">
                  <strong>{idx + 1}. {labelFor(conditionTypes, condition.type, condition.type)}</strong>
                  <span>
                    <button type="button" onClick={() => moveItem("condition", idx, -1)}>Subir</button>
                    <button type="button" onClick={() => moveItem("condition", idx, 1)}>Bajar</button>
                    <button type="button" className="danger-button" onClick={() => setConditions((prev) => prev.filter((_, i) => i !== idx))}>Eliminar</button>
                  </span>
                </div>

                {condition.type === "check_words" || condition.type === "comment_keywords" ? (
                  <div className="trigger-rule-fields">
                    <select value={condition.mode || "any"} onChange={(event) => updateCondition(idx, { mode: event.target.value })}><option value="any">Cualquiera</option><option value="all">Todas</option></select>
                    <div className="inline-form compact trigger-word-input">
                      <input placeholder="Escribir palabra..." value={wordDraft[idx] || ""} onChange={(event) => setWordDraft((prev) => ({ ...prev, [idx]: event.target.value }))} />
                      <button type="button" onClick={() => {
                        const val = String(wordDraft[idx] || "").trim();
                        if (!val) return;
                        const words = Array.isArray(condition.words) ? condition.words : [];
                        if (!words.includes(val)) updateCondition(idx, { words: [...words, val] });
                        setWordDraft((prev) => ({ ...prev, [idx]: "" }));
                      }}>Anadir</button>
                    </div>
                    <div className="trigger-chip-wrap">
                      {(Array.isArray(condition.words) ? condition.words : []).map((word, wordIdx) => (
                        <span className="trigger-chip" key={`${wordIdx}-${word}`}>{word}<button type="button" onClick={() => updateCondition(idx, { words: condition.words.filter((_, i) => i !== wordIdx) })}>x</button></span>
                      ))}
                    </div>
                  </div>
                ) : null}

                {condition.type === "template_sent_status" ? (
                  <div className="trigger-two-col">
                    <select value={condition.state || "not_sent"} onChange={(event) => updateCondition(idx, { state: event.target.value })}><option value="not_sent">No enviada</option><option value="sent">Enviada</option></select>
                    <select value={condition.template_id || ""} onChange={(event) => updateCondition(idx, { template_id: event.target.value })}>{renderTemplateOptions()}</select>
                  </div>
                ) : null}

                {condition.type === "current_tag" ? (
                  <div className="trigger-two-col">
                    <select value={condition.state || "has"} onChange={(event) => updateCondition(idx, { state: event.target.value })}><option value="has">Tiene etiqueta</option><option value="not_has">No tiene etiqueta</option></select>
                    <input placeholder="Etiqueta" value={condition.tag || ""} onChange={(event) => updateCondition(idx, { tag: event.target.value })} />
                  </div>
                ) : null}

                {condition.type === "last_message_sent" ? (
                  <div className="trigger-three-col">
                    <select value={condition.op || "gte"} onChange={(event) => updateCondition(idx, { op: event.target.value })}><option value="gte">Mayor o igual</option><option value="lte">Menor o igual</option><option value="gt">Mayor</option><option value="lt">Menor</option><option value="eq">Igual</option></select>
                    <input type="number" value={condition.minutes || 0} onChange={(event) => updateCondition(idx, { minutes: event.target.value })} />
                    <input value="Minutos desde ultimo envio" disabled />
                  </div>
                ) : null}

                {condition.type === "sent_count" ? (
                  <div className="trigger-three-col">
                    <select value={condition.op || "gte"} onChange={(event) => updateCondition(idx, { op: event.target.value })}><option value="gte">Mayor o igual</option><option value="lte">Menor o igual</option><option value="gt">Mayor</option><option value="lt">Menor</option><option value="eq">Igual</option></select>
                    <input type="number" value={condition.value || 0} onChange={(event) => updateCondition(idx, { value: event.target.value })} placeholder="Cantidad" />
                    <input type="number" value={condition.window_hours || 24} onChange={(event) => updateCondition(idx, { window_hours: event.target.value })} placeholder="Ultimas horas" />
                  </div>
                ) : null}

                {condition.type === "schedule" ? (
                  <div className="trigger-rule-fields">
                    <div className="trigger-three-col">
                      <input value={condition.timezone || "America/Bogota"} onChange={(event) => updateCondition(idx, { timezone: event.target.value })} placeholder="Zona horaria" />
                      <input value={condition.start_time || "08:00"} onChange={(event) => updateCondition(idx, { start_time: event.target.value })} placeholder="Inicio HH:MM" />
                      <input value={condition.end_time || "20:00"} onChange={(event) => updateCondition(idx, { end_time: event.target.value })} placeholder="Fin HH:MM" />
                    </div>
                    <div className="trigger-chip-wrap">
                      {weekDays.map((day) => {
                        const has = Array.isArray(condition.days) ? condition.days.includes(day.key) : false;
                        return <button type="button" key={day.key} className={`trigger-day ${has ? "on" : ""}`} onClick={() => {
                          const days = Array.isArray(condition.days) ? condition.days : [];
                          updateCondition(idx, { days: has ? days.filter((item) => item !== day.key) : [...days, day.key] });
                        }}>{day.label}</button>;
                      })}
                    </div>
                  </div>
                ) : null}
              </div>
            ))}
          </div>
        ) : null}

        {builderTab === "actions" ? (
          <div className="trigger-rule-stack">
            <div className="trigger-add-wrap">
              <button type="button" className="trigger-add-action" onClick={() => setActionMenuOpen((value) => !value)}>Agregar accion</button>
              {actionMenuOpen ? (
                <div className="trigger-dropdown">
                  {actionTypes.map((item) => <button type="button" key={item.key} onClick={() => addAction(item.key)}>{item.label}</button>)}
                </div>
              ) : null}
            </div>

            {actions.map((action, idx) => (
              <div className="trigger-rule-card" key={`${idx}-${action.type}`}>
                <div className="trigger-rule-head">
                  <strong>{idx + 1}. {labelFor(actionTypes, action.type, action.type)}</strong>
                  <span>
                    <button type="button" onClick={() => moveItem("action", idx, -1)}>Subir</button>
                    <button type="button" onClick={() => moveItem("action", idx, 1)}>Bajar</button>
                    <button type="button" className="danger-button" onClick={() => setActions((prev) => prev.filter((_, i) => i !== idx))}>Eliminar</button>
                  </span>
                </div>

                {action.type === "send_template" ? <select value={action.template_id || ""} onChange={(event) => updateAction(idx, { template_id: event.target.value })}>{renderTemplateOptions()}</select> : null}

                {action.type === "reply_comment" ? (
                  <div className="trigger-rule-fields">
                    <select value={action.mode || (action.use_ai ? "ai" : "text")} onChange={(event) => updateAction(idx, { mode: event.target.value, use_ai: event.target.value === "ai" })}><option value="text">Texto fijo</option><option value="ai">Generar con IA</option><option value="template">Usar plantilla</option></select>
                    {action.mode === "template" ? <select value={action.template_id || ""} onChange={(event) => updateAction(idx, { template_id: event.target.value })}>{renderTemplateOptions()}</select> : null}
                    {action.mode === "ai" || action.use_ai ? <input placeholder="Instrucciones IA opcionales" value={action.ai_prompt || ""} onChange={(event) => updateAction(idx, { ai_prompt: event.target.value })} /> : null}
                    {(!action.mode || action.mode === "text") && !action.use_ai ? (
                      <>
                        <div className="template-tools"><EmojiButton title="Emoji" onPick={(emoji) => updateAction(idx, { reply_text: `${action.reply_text || ""}${emoji}` })} /></div>
                        <textarea rows={4} placeholder="Respuesta para el comentario" value={action.reply_text || ""} onChange={(event) => updateAction(idx, { reply_text: event.target.value })} />
                      </>
                    ) : null}
                  </div>
                ) : null}

                {action.type === "change_tag" ? (
                  <div className="trigger-two-col">
                    <select value={action.mode || "add"} onChange={(event) => updateAction(idx, { mode: event.target.value })}><option value="add">Agregar</option><option value="remove">Quitar</option><option value="set">Reemplazar</option></select>
                    <input placeholder="Etiqueta" value={action.tag || ""} onChange={(event) => updateAction(idx, { tag: event.target.value })} />
                  </div>
                ) : null}

                {action.type === "configure_conversation" ? (
                  <div className="trigger-rule-fields">
                    <div className="trigger-two-col">
                      <select value={action.takeover || "keep"} onChange={(event) => updateAction(idx, { takeover: event.target.value })}><option value="keep">Takeover sin cambio</option><option value="on">Takeover ON</option><option value="off">Takeover OFF</option></select>
                      <input placeholder="Estado IA opcional" value={action.ai_state || ""} onChange={(event) => updateAction(idx, { ai_state: event.target.value })} />
                    </div>
                    <label className="check-row"><input type="checkbox" checked={!!action.clear_ai_state} onChange={(event) => updateAction(idx, { clear_ai_state: event.target.checked })} /> Limpiar AI state</label>
                  </div>
                ) : null}

                {action.type === "change_contact_status" ? (
                  <div className="trigger-two-col">
                    <select value={action.field || "customer_type"} onChange={(event) => updateAction(idx, { field: event.target.value })}><option value="customer_type">Estado contacto</option><option value="payment_status">Estado pago</option></select>
                    <input placeholder="Valor estado" value={action.status || ""} onChange={(event) => updateAction(idx, { status: event.target.value })} />
                  </div>
                ) : null}

                {action.type === "notify_admins" ? (
                  <div className="trigger-rule-fields">
                    <input placeholder="Telefonos admins separados por coma" value={action.phones || ""} onChange={(event) => updateAction(idx, { phones: event.target.value })} />
                    <div className="template-tools"><EmojiButton title="Emoji" onPick={(emoji) => updateAction(idx, { message: `${action.message || ""}${emoji}` })} /></div>
                    <textarea rows={4} placeholder="Mensaje para administradores" value={action.message || ""} onChange={(event) => updateAction(idx, { message: event.target.value })} />
                  </div>
                ) : null}

                {action.type === "extract_conversation_info" ? <input type="number" value={action.last_messages || 10} onChange={(event) => updateAction(idx, { last_messages: event.target.value })} placeholder="Ultimos mensajes a analizar" /> : null}

                {action.type === "schedule_message" ? (
                  <div className="trigger-two-col">
                    <select value={action.template_id || ""} onChange={(event) => updateAction(idx, { template_id: event.target.value })}>{renderTemplateOptions()}</select>
                    <input type="number" value={action.delay_minutes || 0} onChange={(event) => updateAction(idx, { delay_minutes: event.target.value })} placeholder="Retraso en minutos" />
                  </div>
                ) : null}
              </div>
            ))}
          </div>
        ) : null}

        <div className="trigger-save-bar">
          <button type="button" className="primary" disabled={saving} onClick={saveTrigger}>{saving ? "Guardando..." : "Guardar trigger"}</button>
          <button type="button" onClick={() => setSelectedTriggerId("")}>Limpiar / nuevo</button>
        </div>
      </article>
    </div>
  );
}
