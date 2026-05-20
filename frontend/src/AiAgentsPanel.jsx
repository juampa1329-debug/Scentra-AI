import React, { useEffect, useMemo, useState } from "react";

const FALLBACK_CHANNELS = [
  { code: "global", label: "Global", description: "Analisis interno." },
  { code: "whatsapp", label: "WhatsApp", description: "Conversaciones WhatsApp." },
  { code: "instagram", label: "Instagram", description: "DMs y comentarios." },
];

const FALLBACK_PROVIDERS = [
  { code: "google", label: "Google Gemini" },
  { code: "mistral", label: "Mistral" },
  { code: "openrouter", label: "OpenRouter" },
  { code: "kimi", label: "Kimi" },
];

const FALLBACK_ROUTES = [
  { code: "advisor", label: "Advisor" },
  { code: "sales", label: "Ventas" },
  { code: "support", label: "Soporte" },
  { code: "ops", label: "Operaciones" },
  { code: "vertical_ops", label: "Verticales" },
];

const FALLBACK_ACTION_PRESETS = [
  { tool_code: "advisor.actions", action_type: "advisor_action", target_module: "advisor", label: "Accion libre" },
  { tool_code: "crm.update", action_type: "review_crm", target_module: "customers", label: "Revisar CRM" },
  { tool_code: "campaigns.create_draft", action_type: "create_campaign_draft", target_module: "campaigns", label: "Campana draft" },
  { tool_code: "triggers.suggest", action_type: "create_trigger_draft", target_module: "campaigns", label: "Trigger draft" },
  { tool_code: "remarketing.suggest", action_type: "create_remarketing_flow_draft", target_module: "campaigns", label: "Remarketing draft" },
  { tool_code: "webhooks.repair", action_type: "open_debug", target_module: "settings", label: "Debug Meta" },
];

const number = (value) => Number(value || 0).toLocaleString("es-CO");

const statusLabel = (status) => ({
  active: "Activo",
  paused: "Pausado",
  draft: "Borrador",
  pending_approval: "Pendiente",
  approved: "Aprobado",
  executed: "Ejecutado",
  dismissed: "Descartado",
  archived: "Archivado",
}[String(status || "").toLowerCase()] || status || "Borrador");

const statusTone = (status) => ({
  active: "ok",
  paused: "warn",
  draft: "neutral",
  archived: "muted",
}[String(status || "").toLowerCase()] || "neutral");

const healthTone = (status) => ({
  healthy: "ok",
  warning: "warn",
  critical: "warn",
  idle: "muted",
}[String(status || "").toLowerCase()] || "muted");

const typeLabel = (type) => ({
  advisor: "Advisor",
  sales: "Ventas",
  support: "Soporte",
  crm_intelligence: "CRM Intelligence",
  campaign_strategist: "Campanas",
  retention: "Retencion",
  operations: "Operaciones",
  executive_summary: "Resumen ejecutivo",
  knowledge: "Knowledge",
  workflow_architect: "Workflow Architect",
  restaurant_reservations: "Restaurante Reservas",
  restaurant_menu: "Menu Restaurante",
  hotel_concierge: "Hotel Concierge",
  hotel_booking: "Reservas Hotel",
  appointment_scheduler: "Agenda / Citas",
  real_estate_leads: "Inmobiliaria",
  education_admissions: "Admisiones",
  automotive_service: "Automotriz",
  beauty_booking: "Belleza",
  logistics_tracking: "Logistica",
  collections_agent: "Cartera",
  reputation_manager: "Reputacion",
  medical_appointment: "Citas Medicas",
  tourism_itinerary: "Turismo",
  hr_recruiting: "Reclutamiento",
  multi_location_ops: "Multi-sede",
}[String(type || "").toLowerCase()] || type);

const categoryLabel = (category) => ({
  strategy: "Estrategia",
  revenue: "Ventas",
  service: "Soporte",
  crm: "CRM",
  marketing: "Marketing",
  growth: "Growth",
  ops: "Operaciones",
  executive: "Ejecutivo",
  knowledge: "Conocimiento",
  automation: "Automatizacion",
  vertical_restaurant: "Restaurantes",
  vertical_hospitality: "Hoteleria",
  vertical_services: "Servicios / citas",
  vertical_real_estate: "Inmobiliaria",
  vertical_education: "Educacion",
  vertical_automotive: "Automotriz",
  vertical_beauty: "Belleza",
  vertical_logistics: "Logistica",
  vertical_finance: "Finanzas / cartera",
  vertical_reputation: "Reputacion",
  vertical_health: "Salud",
  vertical_travel: "Turismo",
  vertical_hr: "RRHH",
  vertical_operations: "Multi-sede",
}[String(category || "").toLowerCase()] || category || "General");

function asList(value) {
  return Array.isArray(value) ? value.filter(Boolean) : [];
}

function asObject(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

function uniqueList(value) {
  return Array.from(new Set(asList(value).map((item) => String(item || "").trim()).filter(Boolean)));
}

function splitLines(value) {
  return String(value || "")
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean)
    .slice(0, 40);
}

function normalizeProvider(value) {
  const clean = String(value || "").trim().toLowerCase();
  if (clean === "gemini" || clean === "google_gemini" || clean === "google-gemini") return "google";
  if (clean === "moonshot" || clean === "moonshotai") return "kimi";
  return clean;
}

function makeEditor(agent) {
  const personality = asObject(agent?.personality_json);
  const providerPolicy = asObject(agent?.provider_policy_json);
  return {
    name: String(agent?.name || ""),
    description: String(agent?.description || ""),
    channels: uniqueList(agent?.channels_json),
    tools: uniqueList(agent?.tools_json),
    goalsText: asList(agent?.goals_json).join("\n"),
    rulesText: asList(agent?.rules_json).join("\n"),
    tone: String(personality.tone || ""),
    riskPosture: String(personality.risk_posture || ""),
    operatingStyle: String(personality.operating_style || ""),
    handoffPolicy: String(personality.handoff_policy || ""),
    providerRoute: String(providerPolicy.route || "advisor"),
    preferredProvider: normalizeProvider(providerPolicy.preferred || "google"),
    fallbackProvider: normalizeProvider(providerPolicy.fallback || "openrouter"),
    memory: { ...asObject(agent?.memory_policy_json) },
    approval: { ...asObject(agent?.approval_policy_json) },
  };
}

function groupBy(items, key) {
  return asList(items).reduce((acc, item) => {
    const group = item?.[key] || "General";
    acc[group] = acc[group] || [];
    acc[group].push(item);
    return acc;
  }, {});
}

export default function AiAgentsPanel({ apiCall, showStatus, onOpenAdvisor, onOpenSettings, onMilestone }) {
  const [agents, setAgents] = useState([]);
  const [templates, setTemplates] = useState([]);
  const [catalog, setCatalog] = useState({});
  const [limits, setLimits] = useState(null);
  const [events, setEvents] = useState([]);
  const [memories, setMemories] = useState([]);
  const [selectedAgentId, setSelectedAgentId] = useState("");
  const [editor, setEditor] = useState(null);
  const [eventNote, setEventNote] = useState("");
  const [runtimeTest, setRuntimeTest] = useState({ message: "Hola, quiero saber que opciones tienen disponibles.", result: null });
  const [runtimeSummary, setRuntimeSummary] = useState(null);
  const [actionDraft, setActionDraft] = useState({
    preset: "advisor.actions",
    title: "",
    description: "",
    impact: "medium",
    risk_level: "medium",
  });
  const [dirty, setDirty] = useState(false);
  const [loading, setLoading] = useState(false);
  const [busyKey, setBusyKey] = useState("");
  const [agentView, setAgentView] = useState("agents");
  const [catalogCategory, setCatalogCategory] = useState("all");
  const [catalogSearch, setCatalogSearch] = useState("");
  const [archiveDraft, setArchiveDraft] = useState(null);

  const selectedAgent = useMemo(
    () => agents.find((agent) => agent.id === selectedAgentId) || agents[0] || null,
    [agents, selectedAgentId],
  );
  const activeAgents = agents.filter((agent) => agent.status === "active").length;
  const totalAgents = agents.filter((agent) => agent.status !== "archived").length;
  const remainingTotal = Number(limits?.remaining?.total ?? 0);
  const remainingActive = Number(limits?.remaining?.active ?? 0);
  const allowedAgentTypes = new Set(asList(limits?.allowed_agent_types).map((item) => String(item || "").toLowerCase()));
  const channelCatalog = asList(catalog.channels).length ? catalog.channels : FALLBACK_CHANNELS;
  const toolCatalog = asList(catalog.tools);
  const providerCatalog = asList(catalog.providers).length ? catalog.providers : FALLBACK_PROVIDERS;
  const routeCatalog = asList(catalog.provider_routes).length ? catalog.provider_routes : FALLBACK_ROUTES;
  const actionPresetCatalog = asList(catalog.action_draft_presets).length ? catalog.action_draft_presets : FALLBACK_ACTION_PRESETS;
  const memoryFlags = asList(catalog.memory_flags);
  const approvalFlags = asList(catalog.approval_flags);
  const groupedTools = groupBy(toolCatalog, "group");
  const runtimeEnabledForSelected = selectedAgent && ["sales", "support"].includes(selectedAgent.agent_type);
  const runtimeMetrics = asObject(runtimeSummary?.metrics || selectedAgent?.metrics_json);
  const runtimeHealth = asObject(runtimeSummary?.health || runtimeMetrics.runtime_health);
  const agentActionDrafts = asList(runtimeSummary?.actions);
  const availableActionPresets = actionPresetCatalog.filter((preset) => !asList(editor?.tools).length || asList(editor?.tools).includes(preset.tool_code));
  const selectedActionPreset = actionPresetCatalog.find((preset) => preset.tool_code === actionDraft.preset) || availableActionPresets[0] || actionPresetCatalog[0] || {};
  const catalogCategories = useMemo(
    () => Array.from(new Set(templates.map((template) => String(template.category || "").trim()).filter(Boolean)))
      .sort((a, b) => categoryLabel(a).localeCompare(categoryLabel(b), "es")),
    [templates],
  );
  const filteredTemplates = useMemo(() => {
    const search = catalogSearch.trim().toLowerCase();
    return templates.filter((template) => {
      const category = String(template.category || "").toLowerCase();
      if (catalogCategory !== "all" && category !== catalogCategory) return false;
      if (!search) return true;
      return [
        template.name,
        template.headline,
        template.description,
        template.agent_type,
        typeLabel(template.agent_type),
        categoryLabel(template.category),
      ].some((value) => String(value || "").toLowerCase().includes(search));
    });
  }, [templates, catalogCategory, catalogSearch]);

  const loadAgents = async (silent = false) => {
    setLoading(true);
    try {
      const [agentData, templateData, catalogData, memoryData] = await Promise.all([
        apiCall("/saas/v1/agents"),
        apiCall("/saas/v1/agents/templates"),
        apiCall("/saas/v1/agents/catalog"),
        apiCall("/saas/v1/agents/memories"),
      ]);
      const nextAgents = agentData?.agents || [];
      setAgents(nextAgents);
      setTemplates(templateData?.templates || []);
      setCatalog(catalogData?.catalog || {});
      setMemories(memoryData?.memories || []);
      setLimits(agentData?.limits || null);
      setSelectedAgentId((current) => (current && nextAgents.some((agent) => agent.id === current) ? current : (nextAgents[0]?.id || "")));
      if (!silent) showStatus("AI Agents actualizado", "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setLoading(false);
    }
  };

  const loadEvents = async (agentId) => {
    if (!agentId) return;
    try {
      const data = await apiCall(`/saas/v1/agents/${encodeURIComponent(agentId)}/events?limit=40`);
      setEvents(data?.events || []);
    } catch {
      setEvents([]);
    }
  };

  const loadRuntime = async (agentId) => {
    if (!agentId) return;
    try {
      const data = await apiCall(`/saas/v1/agents/${encodeURIComponent(agentId)}/runtime`);
      setRuntimeSummary(data || null);
      if (data?.agent?.id) {
        setAgents((prev) => prev.map((agent) => (agent.id === data.agent.id ? data.agent : agent)));
      }
    } catch {
      setRuntimeSummary(null);
    }
  };

  useEffect(() => { loadAgents(true); }, []);
  useEffect(() => {
    if (!selectedAgent?.id) return;
    setEditor(makeEditor(selectedAgent));
    setDirty(false);
    const allowed = uniqueList(selectedAgent.tools_json);
    const firstAllowedPreset = actionPresetCatalog.find((preset) => allowed.includes(preset.tool_code)) || actionPresetCatalog[0];
    setActionDraft({
      preset: firstAllowedPreset?.tool_code || "advisor.actions",
      title: "",
      description: "",
      impact: "medium",
      risk_level: "medium",
    });
    loadEvents(selectedAgent.id);
    loadRuntime(selectedAgent.id);
  }, [selectedAgent?.id, actionPresetCatalog]);

  const patchEditor = (patch) => {
    setEditor((prev) => ({ ...(prev || {}), ...patch }));
    setDirty(true);
  };

  const toggleArrayValue = (field, value) => {
    setEditor((prev) => {
      const current = new Set(asList(prev?.[field]));
      if (current.has(value)) current.delete(value);
      else current.add(value);
      return { ...(prev || {}), [field]: Array.from(current) };
    });
    setDirty(true);
  };

  const toggleObjectFlag = (section, key) => {
    setEditor((prev) => ({
      ...(prev || {}),
      [section]: { ...asObject(prev?.[section]), [key]: !Boolean(prev?.[section]?.[key]) },
    }));
    setDirty(true);
  };

  const createFromTemplate = async (agentType) => {
    setBusyKey(`create:${agentType}`);
    try {
      const data = await apiCall(`/saas/v1/agents/from-template/${encodeURIComponent(agentType)}`, { method: "POST" });
      await loadAgents(true);
      setSelectedAgentId(data?.agent?.id || "");
      showStatus("Agente creado desde plantilla", "ok");
      onMilestone?.(`agent:${agentType}:${data?.agent?.id || "nuevo"}`, {
        eyebrow: "Nuevo agente",
        title: `${typeLabel(agentType)} quedo creado`,
        body: "Ya puedes ajustar sus herramientas, canales, memoria y reglas de aprobacion. El Advisor queda disponible para ayudarte a operarlo.",
        cta: "Abrir Advisor",
        actionType: "advisor",
      });
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setBusyKey("");
    }
  };

  const saveAgent = async () => {
    if (!selectedAgent?.id || !editor) return;
    setBusyKey(`save:${selectedAgent.id}`);
    try {
      const payload = {
        name: editor.name,
        description: editor.description,
        channels_json: uniqueList(editor.channels),
        tools_json: uniqueList(editor.tools),
        goals_json: splitLines(editor.goalsText),
        rules_json: splitLines(editor.rulesText),
        personality_json: {
          ...asObject(selectedAgent.personality_json),
          tone: editor.tone,
          risk_posture: editor.riskPosture,
          operating_style: editor.operatingStyle,
          handoff_policy: editor.handoffPolicy,
        },
        provider_policy_json: {
          ...asObject(selectedAgent.provider_policy_json),
          route: editor.providerRoute,
          preferred: editor.preferredProvider,
          fallback: editor.fallbackProvider,
        },
        memory_policy_json: asObject(editor.memory),
        approval_policy_json: asObject(editor.approval),
      };
      const data = await apiCall(`/saas/v1/agents/${encodeURIComponent(selectedAgent.id)}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
      const saved = data?.agent;
      if (saved?.id) {
        setAgents((prev) => prev.map((agent) => (agent.id === saved.id ? saved : agent)));
        setSelectedAgentId(saved.id);
        setEditor(makeEditor(saved));
      }
      if (data?.limits) setLimits(data.limits);
      setDirty(false);
      await loadEvents(selectedAgent.id);
      await loadRuntime(selectedAgent.id);
      showStatus("Configuracion del agente guardada", "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setBusyKey("");
    }
  };

  const setStatus = async (agent, nextStatus) => {
    setBusyKey(`${nextStatus}:${agent.id}`);
    try {
      const path = nextStatus === "active" ? "activate" : nextStatus === "paused" ? "pause" : "archive";
      await apiCall(`/saas/v1/agents/${encodeURIComponent(agent.id)}/${path}`, { method: "POST" });
      await loadAgents(true);
      await loadEvents(agent.id);
      await loadRuntime(agent.id);
      showStatus(nextStatus === "active" ? "Agente activado" : nextStatus === "paused" ? "Agente pausado" : "Agente archivado", "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setBusyKey("");
    }
  };

  const openArchiveAgent = (agent) => {
    if (!agent?.id) return;
    if (agent.agent_type === "advisor") {
      showStatus("El Advisor base no se elimina; puedes pausarlo si no quieres usarlo.", "error");
      return;
    }
    setArchiveDraft({
      agent,
      preserveMemory: true,
      memoryTitle: `Memoria de ${agent.name}`,
      notes: "",
    });
  };

  const archiveSelectedAgent = async () => {
    const draft = archiveDraft;
    if (!draft?.agent?.id) return;
    setBusyKey(`archive:${draft.agent.id}`);
    try {
      const data = await apiCall(`/saas/v1/agents/${encodeURIComponent(draft.agent.id)}/archive`, {
        method: "POST",
        body: JSON.stringify({
          preserve_memory: Boolean(draft.preserveMemory),
          memory_title: draft.memoryTitle,
          notes: draft.notes,
        }),
      });
      setArchiveDraft(null);
      setSelectedAgentId("");
      await loadAgents(true);
      if (data?.memory?.id) setAgentView("memories");
      showStatus(data?.memory?.id ? "Agente eliminado y memoria guardada" : "Agente eliminado", "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setBusyKey("");
    }
  };

  const restoreMemory = async (memory) => {
    if (!memory?.id) return;
    setBusyKey(`restore:${memory.id}`);
    try {
      const data = await apiCall(`/saas/v1/agents/memories/${encodeURIComponent(memory.id)}/restore`, {
        method: "POST",
        body: JSON.stringify({ name: `${memory.source_agent_name || memory.title || "Agente"} restaurado`, status: "draft" }),
      });
      await loadAgents(true);
      if (data?.agent?.id) setSelectedAgentId(data.agent.id);
      setAgentView("agents");
      showStatus("Agente restaurado desde memoria", "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setBusyKey("");
    }
  };

  const addEventNote = async (event) => {
    event.preventDefault();
    const summary = eventNote.trim();
    if (!selectedAgent?.id || !summary) return;
    setBusyKey(`note:${selectedAgent.id}`);
    try {
      const data = await apiCall(`/saas/v1/agents/${encodeURIComponent(selectedAgent.id)}/events`, {
        method: "POST",
        body: JSON.stringify({ event_type: "agent.note", summary, details_json: { source: "agent_builder" } }),
      });
      setEvents(data?.events || []);
      setEventNote("");
      await loadRuntime(selectedAgent.id);
      showStatus("Nota agregada al agente", "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setBusyKey("");
    }
  };

  const runRuntimeTest = async () => {
    const message = String(runtimeTest.message || "").trim();
    if (!message) return;
    setBusyKey(`runtime-test:${selectedAgent?.id || "none"}`);
    try {
      const data = await apiCall("/saas/v1/ai/test", {
        method: "POST",
        body: JSON.stringify({ phone: "runtime-test", message }),
      });
      setRuntimeTest((prev) => ({ ...prev, result: data?.result || data }));
      if (selectedAgent?.id) {
        await loadEvents(selectedAgent.id);
        await loadRuntime(selectedAgent.id);
      }
      showStatus("Runtime probado con AI Gateway", "ok");
    } catch (err) {
      setRuntimeTest((prev) => ({ ...prev, result: { error: String(err.message || err) } }));
      showStatus(String(err.message || err), "error");
    } finally {
      setBusyKey("");
    }
  };

  const createActionDraft = async () => {
    if (!selectedAgent?.id) return;
    const preset = actionPresetCatalog.find((item) => item.tool_code === actionDraft.preset) || actionPresetCatalog[0] || {};
    const title = String(actionDraft.title || "").trim() || preset.label || "Accion sugerida por agente";
    const description = String(actionDraft.description || "").trim() || preset.description || "Borrador creado desde AI Agents.";
    setBusyKey(`action-draft:${selectedAgent.id}`);
    try {
      const data = await apiCall(`/saas/v1/agents/${encodeURIComponent(selectedAgent.id)}/action-drafts`, {
        method: "POST",
        body: JSON.stringify({
          title,
          description,
          action_type: preset.action_type || "",
          tool_code: preset.tool_code || actionDraft.preset,
          target_module: preset.target_module || "",
          impact: actionDraft.impact,
          risk_level: actionDraft.risk_level,
          payload_json: { ui_source: "ai_agents_builder" },
        }),
      });
      setRuntimeSummary(data || null);
      if (data?.agent?.id) {
        setAgents((prev) => prev.map((agent) => (agent.id === data.agent.id ? data.agent : agent)));
      }
      setActionDraft((prev) => ({ ...prev, title: "", description: "" }));
      await loadEvents(selectedAgent.id);
      showStatus("Borrador de accion creado para aprobacion humana", "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setBusyKey("");
    }
  };

  return (
    <section className="agents-page">
      <article className="agents-hero glass-card">
        <div>
          <p className="eyebrow">Agent Operating System</p>
          <h2>Scentra AI Agents</h2>
          <p>Configura agentes empresariales con canales, herramientas, memoria, permisos y politica de modelo.</p>
        </div>
        <div className="agents-hero-actions">
          <button type="button" onClick={() => loadAgents(false)} disabled={loading}>{loading ? "Actualizando..." : "Refrescar"}</button>
          <button type="button" className="primary" onClick={onOpenAdvisor}>Abrir Advisor</button>
        </div>
      </article>

      <section className="metric-grid">
        <article className="metric-card mint"><span>Agentes AI</span><strong>{number(totalAgents)} / {number(limits?.max_ai_agents || 0)}</strong><small>Plan {limits?.plan_code || "starter"}</small></article>
        <article className="metric-card blue"><span>Activos</span><strong>{number(activeAgents)} / {number(limits?.max_active_ai_agents || 0)}</strong><small>{number(remainingActive)} activaciones disponibles</small></article>
        <article className="metric-card amber"><span>Builder</span><strong>{limits?.builder_enabled ? "ON" : "OFF"}</strong><small>{limits?.notes || "Limites por plan aplicados"}</small></article>
        <article className="metric-card violet"><span>Catalogo</span><strong>{number(toolCatalog.length)}</strong><small>tools disponibles para conectar</small></article>
        <article className="metric-card rose"><span>Runtime seleccionado</span><strong>{runtimeHealth.label || "Sin datos"}</strong><small>{number(runtimeMetrics.runs_7d || 0)} runs / {number(runtimeMetrics.tokens_7d || 0)} tokens 7d</small></article>
      </section>

      <nav className="agent-tabs glass-card" aria-label="Secciones de AI Agents">
        <button type="button" className={agentView === "agents" ? "active" : ""} onClick={() => setAgentView("agents")}>Mis agentes</button>
        <button type="button" className={agentView === "catalog" ? "active" : ""} onClick={() => setAgentView("catalog")}>Catalogo</button>
        <button type="button" className={agentView === "memories" ? "active" : ""} onClick={() => setAgentView("memories")}>Memorias guardadas <span>{number(memories.length)}</span></button>
      </nav>

      {agentView === "agents" ? (
        <>
      <section className="agents-layout builder">
        <article className="panel glass-card">
          <div className="panel-head">
            <div><h2>Agentes configurados</h2><span>{number(remainingTotal)} espacios disponibles</span></div>
          </div>
          <div className="agent-card-grid">
            {agents.map((agent) => {
              const metrics = agent.metrics_json || {};
              const health = asObject(metrics.runtime_health);
              return (
                <button type="button" className={`agent-card ${selectedAgent?.id === agent.id ? "active" : ""}`} key={agent.id} onClick={() => setSelectedAgentId(agent.id)}>
                  <div className="agent-card-head">
                    <span className={`agent-status ${statusTone(agent.status)}`}>{statusLabel(agent.status)}</span>
                    <em>{typeLabel(agent.agent_type)}</em>
                  </div>
                  <strong>{agent.name}</strong>
                  <p>{agent.headline || agent.description}</p>
                  <div className="agent-chip-row">
                    {asList(agent.channels_json).slice(0, 3).map((item) => <span key={item}>{item}</span>)}
                    {asList(agent.tools_json).length ? <span>{number(asList(agent.tools_json).length)} tools</span> : null}
                  </div>
                  <div className="agent-mini-metrics">
                    <span>{number(metrics.runs_7d || metrics.assistant_messages_7d || 0)} runs 7d</span>
                    <span>{number(metrics.failed_runs_7d || metrics.failed_events_7d || 0)} fallos</span>
                    {health.label ? <span className={`agent-health-pill ${healthTone(health.status)}`}>{health.label}</span> : null}
                  </div>
                </button>
              );
            })}
            {!agents.length ? <div className="empty">Aun no hay agentes. El Advisor se crea automaticamente al cargar este modulo.</div> : null}
          </div>
        </article>

        <article className="panel glass-card agent-builder-card">
          <div className="panel-head">
            <div><h2>Builder del agente</h2><span>{selectedAgent ? `${typeLabel(selectedAgent.agent_type)} / ${statusLabel(selectedAgent.status)}` : "sin seleccion"}</span></div>
            {dirty ? <span className="agent-dirty">Cambios sin guardar</span> : null}
          </div>

          {selectedAgent && editor ? (
            <div className="agent-editor">
              <div className="agent-detail-title">
                <div><strong>{selectedAgent.name}</strong><span>{selectedAgent.headline || selectedAgent.description}</span></div>
                <span className={`agent-status ${statusTone(selectedAgent.status)}`}>{statusLabel(selectedAgent.status)}</span>
              </div>

              <div className="agent-editor-grid">
                <label>Nombre del agente
                  <input value={editor.name} onChange={(event) => patchEditor({ name: event.target.value })} />
                </label>
                <label>Descripcion operativa
                  <input value={editor.description} onChange={(event) => patchEditor({ description: event.target.value })} />
                </label>
                <label>Tono / personalidad
                  <input placeholder="Ej: cercano, estrategico, vendedor consultivo" value={editor.tone} onChange={(event) => patchEditor({ tone: event.target.value })} />
                </label>
                <label>Postura de riesgo
                  <select value={editor.riskPosture} onChange={(event) => patchEditor({ riskPosture: event.target.value })}>
                    <option value="">Auto</option>
                    <option value="conservador">Conservador</option>
                    <option value="moderado">Moderado</option>
                    <option value="agresivo_controlado">Agresivo controlado</option>
                  </select>
                </label>
                <label>Estilo operativo
                  <input placeholder="Ej: primero diagnostica, luego recomienda" value={editor.operatingStyle} onChange={(event) => patchEditor({ operatingStyle: event.target.value })} />
                </label>
                <label>Politica de escalacion humana
                  <input placeholder="Ej: escalar si hay queja, pago o dato sensible" value={editor.handoffPolicy} onChange={(event) => patchEditor({ handoffPolicy: event.target.value })} />
                </label>
              </div>

              <label>Objetivos, uno por linea
                <textarea rows={4} value={editor.goalsText} onChange={(event) => patchEditor({ goalsText: event.target.value })} />
              </label>
              <label>Reglas de comportamiento, una por linea
                <textarea rows={4} value={editor.rulesText} onChange={(event) => patchEditor({ rulesText: event.target.value })} placeholder="Ej: no prometer descuentos sin autorizacion" />
              </label>

              <section className="agent-builder-section">
                <div className="agent-section-label"><strong>Canales</strong><span>Donde puede observar o actuar este agente.</span></div>
                <div className="agent-toggle-grid compact">
                  {channelCatalog.map((channel) => (
                    <button type="button" key={channel.code} className={`agent-toggle ${editor.channels.includes(channel.code) ? "active" : ""}`} onClick={() => toggleArrayValue("channels", channel.code)}>
                      <strong>{channel.label}</strong><span>{channel.description}</span>
                    </button>
                  ))}
                </div>
              </section>

              <section className="agent-builder-section">
                <div className="agent-section-label"><strong>Politica de modelo</strong><span>Conecta el agente al AI Gateway sin exponer llaves.</span></div>
                <div className="agent-editor-grid three">
                  <label>Ruta
                    <select value={editor.providerRoute} onChange={(event) => patchEditor({ providerRoute: event.target.value })}>
                      {routeCatalog.map((route) => <option key={route.code} value={route.code}>{route.label}</option>)}
                    </select>
                  </label>
                  <label>Proveedor preferido
                    <select value={editor.preferredProvider} onChange={(event) => patchEditor({ preferredProvider: event.target.value })}>
                      {providerCatalog.map((provider) => <option key={provider.code} value={provider.code}>{provider.label}</option>)}
                    </select>
                  </label>
                  <label>Fallback
                    <select value={editor.fallbackProvider} onChange={(event) => patchEditor({ fallbackProvider: event.target.value })}>
                      {providerCatalog.map((provider) => <option key={provider.code} value={provider.code}>{provider.label}</option>)}
                    </select>
                  </label>
                </div>
              </section>

              <section className="agent-builder-section runtime">
                <div className="agent-section-label">
                  <strong>Runtime y observabilidad fase 4</strong>
                  <span>Salud, tokens, latencia, fallos y fallback del agente seleccionado.</span>
                </div>
                <div className="agent-runtime-status">
                  <span className={`agent-status ${selectedAgent.status === "active" ? "ok" : "paused"}`}>{selectedAgent.status === "active" ? "runtime activo" : "requiere activar"}</span>
                  <span>{runtimeEnabledForSelected ? "conversacional" : "interno/analitico"}</span>
                  <span>{editor.tools.includes("conversation.reply") ? "puede responder" : "sin tool conversation.reply"}</span>
                  <span className={`agent-status ${healthTone(runtimeHealth.status)}`}>{runtimeHealth.label || "sin salud"}</span>
                </div>
                <div className="agent-health-grid">
                  <div><span>Runs 7d</span><strong>{number(runtimeMetrics.runs_7d || 0)}</strong><small>{number(runtimeMetrics.success_runs_7d || 0)} exitosos</small></div>
                  <div><span>Errores 7d</span><strong>{number((runtimeMetrics.failed_runs_7d || 0) + (runtimeMetrics.skipped_runs_7d || 0))}</strong><small>{runtimeMetrics.last_error_code || "sin error reciente"}</small></div>
                  <div><span>Fallback</span><strong>{number(runtimeMetrics.fallback_runs_7d || 0)}</strong><small>{runtimeMetrics.last_provider || "sin proveedor"}</small></div>
                  <div><span>Latencia</span><strong>{number(runtimeMetrics.avg_latency_ms_7d || 0)}ms</strong><small>{runtimeMetrics.last_model || "sin modelo"}</small></div>
                  <div><span>Acciones</span><strong>{number(runtimeMetrics.pending_action_drafts || 0)}</strong><small>{number(runtimeMetrics.action_drafts_7d || 0)} creadas 7d</small></div>
                </div>
                {asList(runtimeHealth.issues).length ? (
                  <div className="agent-issues">{asList(runtimeHealth.issues).map((issue) => <span key={issue}>{issue}</span>)}</div>
                ) : null}
                {runtimeEnabledForSelected ? (
                  <div className="agent-runtime-test">
                    <textarea rows={3} value={runtimeTest.message} onChange={(event) => setRuntimeTest((prev) => ({ ...prev, message: event.target.value }))} />
                    <button type="button" className="primary" disabled={busyKey.startsWith("runtime-test:") || selectedAgent.status !== "active"} onClick={runRuntimeTest}>
                      {busyKey.startsWith("runtime-test:") ? "Probando..." : "Probar runtime"}
                    </button>
                    {runtimeTest.result ? (
                      <pre>{JSON.stringify(runtimeTest.result, null, 2)}</pre>
                    ) : null}
                  </div>
                ) : (
                  <div className="empty">Este tipo de agente aun opera como analitico. El primer runtime conversacional usa Sales y Support Agent.</div>
                )}
              </section>

              <section className="agent-builder-section actions">
                <div className="agent-section-label">
                  <strong>Acciones asistidas fase 5</strong>
                  <span>El agente crea borradores; un humano aprueba antes de ejecutar.</span>
                </div>
                <div className="agent-action-form">
                  <label>Tipo de accion
                    <select
                      value={actionDraft.preset}
                      onChange={(event) => setActionDraft((prev) => ({ ...prev, preset: event.target.value }))}
                    >
                      {(availableActionPresets.length ? availableActionPresets : actionPresetCatalog).map((preset) => (
                        <option key={`${preset.tool_code}:${preset.action_type}`} value={preset.tool_code}>
                          {preset.label} / {preset.tool_code}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>Impacto
                    <select value={actionDraft.impact} onChange={(event) => setActionDraft((prev) => ({ ...prev, impact: event.target.value }))}>
                      <option value="low">Bajo</option>
                      <option value="medium">Medio</option>
                      <option value="high">Alto</option>
                      <option value="critical">Critico</option>
                    </select>
                  </label>
                  <label>Riesgo
                    <select value={actionDraft.risk_level} onChange={(event) => setActionDraft((prev) => ({ ...prev, risk_level: event.target.value }))}>
                      <option value="low">Bajo</option>
                      <option value="medium">Medio</option>
                      <option value="high">Alto</option>
                      <option value="critical">Critico</option>
                    </select>
                  </label>
                  <label>Titulo
                    <input
                      value={actionDraft.title}
                      onChange={(event) => setActionDraft((prev) => ({ ...prev, title: event.target.value }))}
                      placeholder={selectedActionPreset.label || "Accion sugerida"}
                    />
                  </label>
                  <label className="wide">Descripcion y contexto
                    <textarea
                      rows={3}
                      value={actionDraft.description}
                      onChange={(event) => setActionDraft((prev) => ({ ...prev, description: event.target.value }))}
                      placeholder={selectedActionPreset.description || "Explica que deberia revisar o aprobar el equipo."}
                    />
                  </label>
                  <button type="button" className="primary" disabled={!selectedAgent || busyKey.startsWith("action-draft:")} onClick={createActionDraft}>
                    {busyKey.startsWith("action-draft:") ? "Creando..." : "Crear borrador seguro"}
                  </button>
                </div>
                <div className="agent-action-list">
                  {agentActionDrafts.map((action) => {
                    const payload = asObject(action.payload_json);
                    return (
                      <div key={action.id} className={`agent-action-row ${action.status}`}>
                        <div>
                          <strong>{action.title}</strong>
                          <span>{action.action_type} / {payload.tool_code || "tool"}</span>
                          <p>{action.description}</p>
                        </div>
                        <div>
                          <b>{statusLabel(action.status)}</b>
                          <span>{action.impact} impacto</span>
                          <span>{action.risk_level} riesgo</span>
                        </div>
                      </div>
                    );
                  })}
                  {!agentActionDrafts.length ? <div className="empty">Sin borradores de accion para este agente. Crea uno para probar el approval layer.</div> : null}
                </div>
              </section>

              <section className="agent-builder-section">
                <div className="agent-section-label"><strong>Herramientas</strong><span>El runtime solo podra usar herramientas permitidas aqui.</span></div>
                <div className="agent-tool-groups">
                  {Object.entries(groupedTools).map(([group, tools]) => (
                    <div key={group} className="agent-tool-group">
                      <strong>{group}</strong>
                      <div className="agent-toggle-grid">
                        {tools.map((tool) => (
                          <button type="button" key={tool.code} className={`agent-toggle ${editor.tools.includes(tool.code) ? "active" : ""}`} onClick={() => toggleArrayValue("tools", tool.code)}>
                            <strong>{tool.label}</strong><span>{tool.description}</span>
                          </button>
                        ))}
                      </div>
                    </div>
                  ))}
                  {!toolCatalog.length ? <div className="empty">Catalogo de herramientas no cargado todavia.</div> : null}
                </div>
              </section>

              <section className="agent-builder-section two">
                <div>
                  <div className="agent-section-label"><strong>Memoria</strong><span>Contexto que el agente puede recuperar.</span></div>
                  <div className="agent-flag-grid">
                    {memoryFlags.map((flag) => (
                      <label className="check-row" key={flag.code}>
                        <input type="checkbox" checked={Boolean(editor.memory?.[flag.code])} onChange={() => toggleObjectFlag("memory", flag.code)} />
                        <span><b>{flag.label}</b><small>{flag.description}</small></span>
                      </label>
                    ))}
                  </div>
                </div>
                <div>
                  <div className="agent-section-label"><strong>Permisos</strong><span>Acciones que requieren aprobacion o bloqueo.</span></div>
                  <div className="agent-flag-grid">
                    {approvalFlags.map((flag) => (
                      <label className="check-row" key={flag.code}>
                        <input type="checkbox" checked={Boolean(editor.approval?.[flag.code])} onChange={() => toggleObjectFlag("approval", flag.code)} />
                        <span><b>{flag.label}</b><small>{flag.description}</small></span>
                      </label>
                    ))}
                  </div>
                </div>
              </section>

              <div className="panel-actions agent-editor-actions">
                <button type="button" className="primary" disabled={!dirty || busyKey === `save:${selectedAgent.id}`} onClick={saveAgent}>{busyKey === `save:${selectedAgent.id}` ? "Guardando..." : "Guardar configuracion"}</button>
                {selectedAgent.status !== "active" ? <button type="button" disabled={busyKey === `active:${selectedAgent.id}`} onClick={() => setStatus(selectedAgent, "active")}>Activar</button> : null}
                {selectedAgent.status === "active" ? <button type="button" disabled={busyKey === `paused:${selectedAgent.id}`} onClick={() => setStatus(selectedAgent, "paused")}>Pausar</button> : null}
                {selectedAgent.agent_type === "advisor" ? <button type="button" onClick={onOpenAdvisor}>Abrir copiloto</button> : null}
                <button type="button" onClick={onOpenSettings}>Configurar APIs/modelos</button>
                {selectedAgent.agent_type !== "advisor" ? <button type="button" className="danger-button" onClick={() => openArchiveAgent(selectedAgent)}>Eliminar</button> : null}
              </div>
            </div>
          ) : <div className="empty">Selecciona un agente para abrir el builder.</div>}
        </article>
      </section>

      <section className="agents-layout bottom compact">
        <article className="panel glass-card">
          <div className="panel-head">
            <div><h2>Runs AI Gateway</h2><span>ultimas ejecuciones del agente</span></div>
          </div>
          <div className="agent-run-list">
            {asList(runtimeSummary?.runs).map((run) => (
              <div key={run.id} className={`agent-run-row ${run.status}`}>
                <div><strong>{run.provider_code || "provider"}</strong><span>{run.model || "modelo"}</span></div>
                <div><b>{run.status}</b><span>{number(run.total_tokens || 0)} tokens</span></div>
                <div><b>{number(run.latency_ms || 0)}ms</b><span>{run.fallback_used ? "fallback" : "primary"}</span></div>
                <small>{run.error_code || run.created_at}</small>
              </div>
            ))}
            {!asList(runtimeSummary?.runs).length ? <div className="empty">Sin runs todavia. Usa Probar runtime o espera una conversacion entrante.</div> : null}
          </div>
        </article>

        <article className="panel glass-card">
          <div className="panel-head">
            <div><h2>Actividad</h2><span>auditoria y notas</span></div>
          </div>
          <form className="agent-note-form" onSubmit={addEventNote}>
            <input value={eventNote} onChange={(event) => setEventNote(event.target.value)} placeholder="Agregar nota interna del agente..." />
            <button type="submit" disabled={!eventNote.trim() || !selectedAgent || busyKey.startsWith("note:")}>Agregar</button>
          </form>
          <div className="agent-events">
            {events.map((event) => (
              <div key={event.id}>
                <strong>{event.event_type}</strong>
                <span>{event.created_at}</span>
                <p>{event.summary}</p>
              </div>
            ))}
            {!events.length ? <div className="empty">Sin eventos todavia para este agente.</div> : null}
          </div>
        </article>
      </section>
        </>
      ) : null}

      {agentView === "catalog" ? (
        <section className="panel glass-card agent-catalog-panel">
          <div className="panel-head">
            <div><h2>Catalogo de agentes</h2><span>filtra por funcion o tipo de negocio</span></div>
            <button type="button" onClick={() => { setCatalogCategory("all"); setCatalogSearch(""); }}>Limpiar filtros</button>
          </div>
          <div className="agent-catalog-filters">
            <input value={catalogSearch} onChange={(event) => setCatalogSearch(event.target.value)} placeholder="Buscar por industria, funcion, canal o herramienta..." />
            <div className="agent-filter-pills">
              <button type="button" className={catalogCategory === "all" ? "active" : ""} onClick={() => setCatalogCategory("all")}>Todos</button>
              {catalogCategories.map((category) => (
                <button type="button" key={category} className={catalogCategory === category.toLowerCase() ? "active" : ""} onClick={() => setCatalogCategory(category.toLowerCase())}>
                  {categoryLabel(category)}
                </button>
              ))}
            </div>
          </div>
          <div className="template-agent-grid catalog">
            {filteredTemplates.map((template) => {
              const alreadyExists = agents.some((agent) => agent.agent_type === template.agent_type && agent.status !== "archived");
              const allowedByPlan = !allowedAgentTypes.size || allowedAgentTypes.has(String(template.agent_type || "").toLowerCase());
              const disabled = alreadyExists || !allowedByPlan || remainingTotal <= 0 || !limits?.builder_enabled || busyKey === `create:${template.agent_type}`;
              return (
                <article className={`template-agent-card ${allowedByPlan ? "" : "locked"}`} key={template.agent_type}>
                  <div className="agent-card-head">
                    <span>{categoryLabel(template.category)}</span>
                    <em>{typeLabel(template.agent_type)}</em>
                  </div>
                  <strong>{template.name}</strong>
                  <p>{template.headline || template.description}</p>
                  <div className="agent-chip-row">
                    {asList(template.channels).slice(0, 3).map((item) => <span key={item}>{item}</span>)}
                    {asList(template.tools).length ? <span>{number(asList(template.tools).length)} tools</span> : null}
                  </div>
                  <button type="button" className={alreadyExists || !allowedByPlan ? "" : "primary"} disabled={disabled} onClick={() => createFromTemplate(template.agent_type)}>
                    {alreadyExists ? "Ya creado" : !allowedByPlan ? "Plan requerido" : remainingTotal <= 0 ? "Limite del plan" : "Crear agente"}
                  </button>
                </article>
              );
            })}
            {!filteredTemplates.length ? <div className="empty">No encontramos agentes con esos filtros.</div> : null}
          </div>
        </section>
      ) : null}

      {agentView === "memories" ? (
        <section className="panel glass-card agent-memory-panel">
          <div className="panel-head">
            <div><h2>Memorias guardadas</h2><span>snapshots de agentes eliminados para reutilizar despues</span></div>
            <button type="button" onClick={() => loadAgents(false)}>Refrescar</button>
          </div>
          <div className="agent-memory-grid">
            {memories.map((memory) => (
              <article className="agent-memory-card" key={memory.id}>
                <div className="agent-card-head">
                  <span>{categoryLabel(memory.source_agent_type)}</span>
                  <em>{typeLabel(memory.source_agent_type)}</em>
                </div>
                <strong>{memory.title || memory.source_agent_name}</strong>
                <p>{memory.notes || `Memoria conservada desde ${memory.source_agent_name}.`}</p>
                <div className="agent-chip-row">
                  {asList(memory.summary?.channels).map((item) => <span key={item}>{item}</span>)}
                  {asList(memory.summary?.tools).slice(0, 3).map((item) => <span key={item}>{item}</span>)}
                </div>
                <small>{memory.created_at}</small>
                <button type="button" className="primary" disabled={remainingTotal <= 0 || busyKey === `restore:${memory.id}`} onClick={() => restoreMemory(memory)}>
                  {remainingTotal <= 0 ? "Sin cupo del plan" : busyKey === `restore:${memory.id}` ? "Restaurando..." : "Crear agente desde memoria"}
                </button>
              </article>
            ))}
            {!memories.length ? <div className="empty">Aun no hay memorias guardadas. Cuando elimines un agente, puedes conservar su memoria aqui.</div> : null}
          </div>
        </section>
      ) : null}

      {archiveDraft ? (
        <div className="modal-backdrop" role="presentation" onMouseDown={() => setArchiveDraft(null)}>
          <section className="modal-card glass-card agent-archive-modal" role="dialog" aria-modal="true" aria-label="Eliminar agente" onMouseDown={(event) => event.stopPropagation()}>
            <div className="panel-head">
              <div><h2>Eliminar agente</h2><span>{archiveDraft.agent?.name}</span></div>
              <button type="button" onClick={() => setArchiveDraft(null)}>Cerrar</button>
            </div>
            <p>El agente se quitara de la operacion. Puedes conservar su memoria para crear otro agente despues sin perder configuracion, reglas, objetivos y contexto reciente.</p>
            <label className="check-row">
              <input type="checkbox" checked={Boolean(archiveDraft.preserveMemory)} onChange={(event) => setArchiveDraft((prev) => ({ ...prev, preserveMemory: event.target.checked }))} />
              <span><b>Conservar memoria del agente</b><small>Guarda un snapshot reutilizable en la subpestaña Memorias guardadas.</small></span>
            </label>
            {archiveDraft.preserveMemory ? (
              <>
                <label>Titulo de la memoria
                  <input value={archiveDraft.memoryTitle} onChange={(event) => setArchiveDraft((prev) => ({ ...prev, memoryTitle: event.target.value }))} />
                </label>
                <label>Notas internas
                  <textarea rows={3} value={archiveDraft.notes} onChange={(event) => setArchiveDraft((prev) => ({ ...prev, notes: event.target.value }))} placeholder="Ej: conservar tono, herramientas y reglas para nueva version del agente." />
                </label>
              </>
            ) : null}
            <div className="panel-actions">
              <button type="button" onClick={() => setArchiveDraft(null)}>Cancelar</button>
              <button type="button" className="danger-button" disabled={busyKey === `archive:${archiveDraft.agent?.id}`} onClick={archiveSelectedAgent}>
                {busyKey === `archive:${archiveDraft.agent?.id}` ? "Eliminando..." : "Eliminar agente"}
              </button>
            </div>
          </section>
        </div>
      ) : null}
    </section>
  );
}
