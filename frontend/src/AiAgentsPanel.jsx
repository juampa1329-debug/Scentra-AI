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
  { tool_code: "webhooks.repair", action_type: "open_debug", target_module: "settings", label: "Diagnostico Meta" },
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
  custom: "Custom Agent",
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
  teacher: "Profesor",
  automotive_service: "Automotriz",
  beauty_booking: "Belleza",
  logistics_tracking: "Logistica",
  collections_agent: "Cartera",
  reputation_manager: "Reputacion",
  medical_appointment: "Citas Medicas",
  tourism_itinerary: "Turismo",
  hr_recruiting: "Reclutamiento",
  multi_location_ops: "Multi-sede",
  legal_intake: "Legal Intake",
  insurance_claims: "Seguros",
  financial_services: "Finanzas",
  dental_booking: "Dental",
  fitness_membership: "Fitness",
  event_planner: "Eventos",
  nonprofit_donor: "ONG / Donantes",
  public_sector_services: "Sector publico",
  saas_onboarding: "SaaS Onboarding",
  field_service_dispatch: "Servicio tecnico",
}[String(type || "").toLowerCase()] || type);

const categoryLabel = (category) => ({
  strategy: "Estrategia",
  custom: "Personalizados",
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
  vertical_legal: "Legal",
  vertical_insurance: "Seguros",
  vertical_events: "Eventos",
  vertical_nonprofit: "ONG",
  vertical_public_sector: "Sector publico",
  vertical_b2b: "B2B / SaaS",
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
  const budget = asObject(providerPolicy.budget);
  const experiment = asObject(providerPolicy.experiment);
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
    isCustom: Boolean(agent?.is_custom),
    baseTemplateType: String(agent?.base_template_type || ""),
    systemPromptTemplate: String(agent?.system_prompt_template || ""),
    systemPromptRendered: String(agent?.system_prompt_rendered || ""),
    systemPromptVariablesText: JSON.stringify(asObject(agent?.system_prompt_variables_json), null, 2),
    providerRoute: String(providerPolicy.route || "advisor"),
    preferredProvider: normalizeProvider(providerPolicy.preferred || "google"),
    fallbackProvider: normalizeProvider(providerPolicy.fallback || "openrouter"),
    budget: {
      monthlyTokenLimit: String(budget.monthly_token_limit ?? ""),
      monthlyCostLimitUsd: String(budget.monthly_cost_limit_usd ?? ""),
      alertThresholdPercent: String(budget.alert_threshold_percent ?? "80"),
      hardStop: Boolean(budget.hard_stop),
    },
    experiment: {
      enabled: Boolean(experiment.enabled),
      variantKey: String(experiment.variant_key || "A"),
      compareAgainst: String(experiment.compare_against || ""),
      trafficPercent: String(experiment.traffic_percent ?? "50"),
    },
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
  const [governance, setGovernance] = useState(null);
  const [orchestrator, setOrchestrator] = useState(null);
  const [agentOs, setAgentOs] = useState(null);
  const [multimodalRuns, setMultimodalRuns] = useState([]);
  const [multimodalMemoryEvents, setMultimodalMemoryEvents] = useState([]);
  const [selectedAgentId, setSelectedAgentId] = useState("");
  const [editor, setEditor] = useState(null);
  const [eventNote, setEventNote] = useState("");
  const [runtimeTest, setRuntimeTest] = useState({ message: "Hola, quiero saber que opciones tienen disponibles.", result: null });
  const [runtimeSummary, setRuntimeSummary] = useState(null);
  const [preflightResult, setPreflightResult] = useState(null);
  const [memoryImportPayload, setMemoryImportPayload] = useState("");
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
  const [collectiveDraft, setCollectiveDraft] = useState({
    memory_type: "fact",
    title: "",
    content: "",
    confidence_score: 80,
    tags: "",
  });
  const [orchestratorDraft, setOrchestratorDraft] = useState({
    event_type: "conversation.message_received",
    entity_type: "conversation",
    entity_id: "",
    channel: "whatsapp",
    priority: 70,
    text: "Cliente pregunta por precio y disponibilidad.",
  });
  const [multimodalDraft, setMultimodalDraft] = useState({
    tool_code: "media.voice_analyze",
    message_id: "",
    conversation_id: "",
    query: "",
    search_type: "mixed",
    provider_code: "",
    force: false,
    limit: 6,
  });

  const selectedAgent = useMemo(
    () => agents.find((agent) => agent.id === selectedAgentId) || agents[0] || null,
    [agents, selectedAgentId],
  );
  const activeAgents = agents.filter((agent) => agent.status === "active").length;
  const totalAgents = agents.filter((agent) => agent.status !== "archived").length;
  const remainingTotal = Number(limits?.remaining?.total ?? 0);
  const remainingActive = Number(limits?.remaining?.active ?? 0);
  const usedMemoryArchives = Number(limits?.usage?.memory_archives ?? memories.length);
  const maxMemoryArchives = Number(limits?.max_memory_archives ?? 0);
  const remainingMemoryArchives = Number(
    limits?.remaining?.memory_archives ?? Math.max(0, maxMemoryArchives - usedMemoryArchives),
  );
  const memoryVaultFull = maxMemoryArchives > 0 && usedMemoryArchives >= maxMemoryArchives;
  const allowedAgentTypes = new Set(asList(limits?.allowed_agent_types).map((item) => String(item || "").toLowerCase()));
  const channelCatalog = asList(catalog.channels).length ? catalog.channels : FALLBACK_CHANNELS;
  const toolCatalog = asList(catalog.tools);
  const providerCatalog = asList(catalog.providers).length ? catalog.providers : FALLBACK_PROVIDERS;
  const routeCatalog = asList(catalog.provider_routes).length ? catalog.provider_routes : FALLBACK_ROUTES;
  const actionPresetCatalog = asList(catalog.action_draft_presets).length ? catalog.action_draft_presets : FALLBACK_ACTION_PRESETS;
  const industryPolicyPresets = asList(catalog.industry_policy_presets);
  const budgetDefaults = asObject(catalog.budget_defaults);
  const memoryFlags = asList(catalog.memory_flags);
  const approvalFlags = asList(catalog.approval_flags);
  const groupedTools = groupBy(toolCatalog, "group");
  const runtimeEnabledForSelected = selectedAgent && asList(selectedAgent.tools_json).includes("conversation.reply");
  const runtimeMetrics = asObject(runtimeSummary?.metrics || selectedAgent?.metrics_json);
  const runtimeHealth = asObject(runtimeSummary?.health || runtimeMetrics.runtime_health);
  const agentActionDrafts = asList(runtimeSummary?.actions);
  const collectiveMemories = asList(governance?.collective_memory);
  const phase6Counts = asObject(governance?.counts);
  const orchestratorCounts = asObject(orchestrator?.counts);
  const agentOsCounts = asObject(agentOs?.counts);
  const agentOsPremium = asObject(agentOs?.premium);
  const agentOsReadiness = asObject(agentOs?.readiness);
  const agentOsMemoryLayers = asObject(agentOs?.memory_layers);
  const agentOsCoverage = asList(agentOs?.coverage);
  const agentOsMessages = asList(agentOs?.communication?.messages);
  const agentOsTraces = asList(agentOs?.observability?.traces);
  const agentOsToolRuns = asList(agentOs?.tooling?.recent_runs);
  const agentMultimodalTools = asList(agentOs?.tooling?.multimodal_tools).length
    ? asList(agentOs?.tooling?.multimodal_tools)
    : toolCatalog.filter((item) => ["media.voice_analyze", "media.vision_analyze", "media.web_image_search"].includes(item.code));
  const agentMultimodalRuns = multimodalRuns.length
    ? multimodalRuns
    : agentOsToolRuns.filter((item) => ["media.voice_analyze", "media.vision_analyze", "media.web_image_search"].includes(item.tool_code));
  const agentMultimodalMemoryEvents = asList(multimodalMemoryEvents);
  const agentOsSubscriptions = asList(agentOs?.event_driven?.subscriptions);
  const orchestrationJobs = asList(orchestrator?.jobs);
  const orchestrationLocks = asList(orchestrator?.locks);
  const orchestrationHandoffs = asList(orchestrator?.handoffs);
  const orchestrationConflicts = asList(orchestrator?.conflicts);
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
      const governanceData = await apiCall("/saas/v1/agents/governance").catch(() => null);
      const orchestratorData = await apiCall("/saas/v1/agents/orchestrator?limit=20").catch(() => null);
      const agentOsData = await apiCall("/saas/v1/agents/os?limit=20").catch(() => null);
      const nextAgents = agentData?.agents || [];
      setAgents(nextAgents);
      setTemplates(templateData?.templates || []);
      setCatalog(catalogData?.catalog || {});
      setMemories(memoryData?.memories || []);
      setGovernance(governanceData || null);
      setOrchestrator(orchestratorData || null);
      setAgentOs(agentOsData || null);
      setLimits(agentData?.limits || null);
      setSelectedAgentId((current) => (current && nextAgents.some((agent) => agent.id === current) ? current : (nextAgents[0]?.id || "")));
      if (!silent) showStatus("Agentes IA actualizados", "ok");
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

  const loadMultimodalRuns = async (agentId) => {
    if (!agentId) {
      setMultimodalRuns([]);
      return;
    }
    try {
      const data = await apiCall(`/saas/v1/agents/${encodeURIComponent(agentId)}/multimodal-tools/runs?limit=20`);
      setMultimodalRuns(data?.tool_runs || []);
    } catch {
      setMultimodalRuns([]);
    }
  };

  const loadMultimodalMemoryEvents = async () => {
    try {
      const data = await apiCall("/saas/v1/agents/multimodal-memory/events?limit=30");
      setMultimodalMemoryEvents(data?.events || []);
    } catch {
      setMultimodalMemoryEvents([]);
    }
  };

  useEffect(() => { loadAgents(true); }, []);
  useEffect(() => {
    if (!selectedAgent?.id) return;
    setEditor(makeEditor(selectedAgent));
    setDirty(false);
    setPreflightResult(null);
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
    loadMultimodalRuns(selectedAgent.id);
    loadMultimodalMemoryEvents();
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

  const applyIndustryPolicy = (preset) => {
    if (!preset || !editor) return;
    const nextRules = uniqueList([
      ...splitLines(editor.rulesText),
      ...asList(preset.rules),
    ]);
    patchEditor({
      riskPosture: preset.risk_posture || editor.riskPosture,
      handoffPolicy: editor.handoffPolicy || "Escalar casos sensibles, pagos, quejas o datos regulados antes de ejecutar acciones.",
      memory: { ...asObject(editor.memory), ...asObject(preset.memory) },
      approval: { ...asObject(editor.approval), ...asObject(preset.approval) },
      rulesText: nextRules.join("\n"),
    });
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

  const createCustomAgent = async () => {
    setBusyKey("create:custom");
    try {
      const data = await apiCall("/saas/v1/agents", {
        method: "POST",
        body: JSON.stringify({
          agent_type: "custom",
          name: "Custom Agent",
          description: "Agente personalizado creado por la empresa.",
          is_custom: true,
          channels_json: ["whatsapp"],
          tools_json: ["conversation.reply", "crm.update", "knowledge.search", "media.voice_analyze", "media.vision_analyze", "media.web_image_search"],
          goals_json: ["Atender conversaciones asignadas", "Usar contexto del negocio", "Escalar casos sensibles"],
          approval_policy_json: { requires_human_approval: true, can_send_messages: true, can_update_crm: true },
          memory_policy_json: { short_term: true, semantic: true, customer_profile: true, collective_memory: true },
        }),
      });
      await loadAgents(true);
      setSelectedAgentId(data?.agent?.id || "");
      setAgentView("agents");
      showStatus("Custom Agent creado. Completa su prompt y ejecuta preflight antes de activar.", "ok");
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
      let promptVariables = {};
      try {
        promptVariables = JSON.parse(editor.systemPromptVariablesText || "{}");
      } catch {
        showStatus("Variables del system prompt deben ser JSON valido.", "error");
        return;
      }
      const payload = {
        name: editor.name,
        description: editor.description,
        is_custom: Boolean(editor.isCustom),
        base_template_type: editor.baseTemplateType,
        system_prompt_template: editor.systemPromptTemplate,
        system_prompt_variables_json: promptVariables,
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
          budget: {
            monthly_token_limit: Number(editor.budget?.monthlyTokenLimit || budgetDefaults.monthly_token_limit || 0),
            monthly_cost_limit_usd: Number(editor.budget?.monthlyCostLimitUsd || budgetDefaults.monthly_cost_limit_usd || 0),
            alert_threshold_percent: Number(editor.budget?.alertThresholdPercent || budgetDefaults.alert_threshold_percent || 80),
            hard_stop: Boolean(editor.budget?.hardStop),
          },
          experiment: {
            enabled: Boolean(editor.experiment?.enabled),
            variant_key: editor.experiment?.variantKey || "A",
            compare_against: editor.experiment?.compareAgainst || "",
            traffic_percent: Number(editor.experiment?.trafficPercent || 50),
          },
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
      preserveMemory: !memoryVaultFull,
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
          preserve_memory: Boolean(draft.preserveMemory) && !memoryVaultFull,
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

  const deleteMemory = async (memory) => {
    if (!memory?.id) return;
    const label = memory.title || memory.source_agent_name || "esta memoria";
    const confirmed = window.confirm(`Borrar la memoria "${label}" de la boveda? Esta accion no elimina agentes activos.`);
    if (!confirmed) return;
    setBusyKey(`delete-memory:${memory.id}`);
    try {
      const data = await apiCall(`/saas/v1/agents/memories/${encodeURIComponent(memory.id)}`, { method: "DELETE" });
      setMemories((prev) => prev.filter((item) => item.id !== memory.id));
      if (data?.limits) setLimits(data.limits);
      showStatus("Memoria eliminada de la boveda", "ok");
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

  const runPreflight = async () => {
    if (!selectedAgent?.id) return;
    setBusyKey(`preflight:${selectedAgent.id}`);
    try {
      const data = await apiCall(`/saas/v1/agents/${encodeURIComponent(selectedAgent.id)}/preflight`);
      setPreflightResult(data?.preflight || null);
      showStatus(data?.preflight?.ready ? "Preflight aprobado: el agente puede activarse." : "Preflight completado: revisa ajustes antes de activar.", data?.preflight?.ready ? "ok" : "neutral");
      await loadEvents(selectedAgent.id);
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setBusyKey("");
    }
  };

  const exportMemory = async (memory) => {
    if (!memory?.id) return;
    setBusyKey(`export-memory:${memory.id}`);
    try {
      const data = await apiCall(`/saas/v1/agents/memories/${encodeURIComponent(memory.id)}/export`);
      const blob = new Blob([JSON.stringify(data?.export || data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `scentra-agent-memory-${memory.id}.json`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
      showStatus("Memoria exportada como JSON", "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setBusyKey("");
    }
  };

  const importMemory = async () => {
    const raw = memoryImportPayload.trim();
    if (!raw) return showStatus("Pega un JSON de memoria exportada.", "error");
    try {
      const payload = JSON.parse(raw);
      setBusyKey("import-memory");
      const data = await apiCall("/saas/v1/agents/memories/import", {
        method: "POST",
        body: JSON.stringify({ payload_json: payload, title: "", notes: "Importada desde la boveda de agentes IA." }),
      });
      if (data?.memory) setMemories((prev) => [data.memory, ...prev]);
      if (data?.limits) setLimits(data.limits);
      setMemoryImportPayload("");
      showStatus("Memoria importada a la boveda", "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setBusyKey("");
    }
  };

  const saveCollectiveMemory = async () => {
    const title = collectiveDraft.title.trim();
    const content = collectiveDraft.content.trim();
    if (!title || !content) return showStatus("La memoria colectiva necesita titulo y contenido.", "error");
    setBusyKey("collective-memory");
    try {
      const data = await apiCall("/saas/v1/agents/collective-memory", {
        method: "POST",
        body: JSON.stringify({
          source_agent_id: selectedAgent?.id || "",
          source_agent_type: selectedAgent?.agent_type || "",
          memory_scope: "tenant",
          memory_type: collectiveDraft.memory_type,
          title,
          content,
          confidence_score: Number(collectiveDraft.confidence_score || 80),
          visibility: "agents",
          tags_json: collectiveDraft.tags.split(",").map((item) => item.trim()).filter(Boolean),
        }),
      });
      setGovernance(data || null);
      setCollectiveDraft({ memory_type: "fact", title: "", content: "", confidence_score: 80, tags: "" });
      showStatus("Memoria colectiva guardada para los agentes", "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setBusyKey("");
    }
  };

  const deleteCollectiveMemoryItem = async (memory) => {
    if (!memory?.id) return;
    const confirmed = window.confirm(`Borrar la memoria colectiva "${memory.title}"?`);
    if (!confirmed) return;
    setBusyKey(`delete-collective:${memory.id}`);
    try {
      const data = await apiCall(`/saas/v1/agents/collective-memory/${encodeURIComponent(memory.id)}`, { method: "DELETE" });
      setGovernance(data || null);
      showStatus("Memoria colectiva eliminada", "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setBusyKey("");
    }
  };

  const refreshOrchestrator = async (silent = false) => {
    try {
      const data = await apiCall("/saas/v1/agents/orchestrator?limit=30");
      setOrchestrator(data || null);
      if (!silent) showStatus("Orquestador actualizado", "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    }
  };

  const createOrchestratorEvent = async () => {
    setBusyKey("orchestrator-event");
    try {
      const data = await apiCall("/saas/v1/agents/orchestrator/events", {
        method: "POST",
        body: JSON.stringify({
          event_type: orchestratorDraft.event_type,
          entity_type: orchestratorDraft.entity_type,
          entity_id: orchestratorDraft.entity_id || `manual-${Date.now()}`,
          channel: orchestratorDraft.channel,
          priority: Number(orchestratorDraft.priority || 50),
          payload_json: {
            text: orchestratorDraft.text,
            summary: orchestratorDraft.text,
            manual_test: true,
          },
        }),
      });
      setOrchestrator(data?.orchestrator || data || null);
      showStatus("Evento enviado al orquestador", "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setBusyKey("");
    }
  };

  const runOrchestratorTick = async () => {
    setBusyKey("orchestrator-tick");
    try {
      const data = await apiCall("/saas/v1/agents/orchestrator/tick?limit=10", { method: "POST" });
      setOrchestrator(data?.orchestrator || null);
      const result = asObject(data?.result);
      showStatus(`Orquestador: ${number(result.completed || 0)} completados, ${number(result.conflicts || 0)} conflictos`, "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setBusyKey("");
    }
  };

  const refreshAgentOs = async (silent = false) => {
    try {
      const data = await apiCall("/saas/v1/agents/os?limit=30");
      setAgentOs(data || null);
      if (selectedAgent?.id) await loadMultimodalRuns(selectedAgent.id);
      await loadMultimodalMemoryEvents();
      if (!silent) showStatus("Agent OS actualizado", "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    }
  };

  const syncAgentOsEvents = async () => {
    setBusyKey("agent-os-sync");
    try {
      const data = await apiCall("/saas/v1/agents/os/event-sync", {
        method: "POST",
        body: JSON.stringify({ limit: 50, lookback_days: 7, dry_run: false }),
      });
      setAgentOs(data || null);
      setOrchestrator(data?.orchestrator || orchestrator);
      const result = asObject(data?.result);
      const mode = result.dry_run ? "demo" : "full";
      showStatus(`Agent OS ${mode}: ${number(result.created || 0)} jobs, ${number(result.candidates || 0)} senales`, "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setBusyKey("");
    }
  };

  const executeMultimodalTool = async () => {
    if (!selectedAgent?.id) return;
    const toolCode = multimodalDraft.tool_code;
    if (["media.voice_analyze", "media.vision_analyze"].includes(toolCode) && !String(multimodalDraft.message_id || "").trim()) {
      showStatus("Ingresa el message_id del audio, imagen o documento.", "error");
      return;
    }
    if (toolCode === "media.web_image_search" && !String(multimodalDraft.query || "").trim()) {
      showStatus("Ingresa una consulta para la busqueda web/imagen.", "error");
      return;
    }
    setBusyKey(`multimodal:${toolCode}`);
    try {
      const data = await apiCall(`/saas/v1/agents/${encodeURIComponent(selectedAgent.id)}/multimodal-tools/execute`, {
        method: "POST",
        body: JSON.stringify({
          tool_code: toolCode,
          message_id: multimodalDraft.message_id,
          conversation_id: multimodalDraft.conversation_id,
          query: multimodalDraft.query,
          search_type: multimodalDraft.search_type,
          provider_code: multimodalDraft.provider_code,
          force: Boolean(multimodalDraft.force),
          limit: Number(multimodalDraft.limit || 6),
          metadata_json: { ui_source: "ai_agents_panel" },
        }),
      });
      setRuntimeSummary(data || null);
      setMultimodalRuns(data?.tool_runs || []);
      await loadMultimodalMemoryEvents();
      await refreshAgentOs(true);
      showStatus(toolCode === "media.web_image_search" ? "Busqueda registrada; revisa y aprueba fuentes antes de usarlas." : "Herramienta multimodal ejecutada", "ok");
    } catch (err) {
      await refreshAgentOs(true).catch(() => null);
      showStatus(String(err.message || err), "error");
    } finally {
      setBusyKey("");
    }
  };

  const reviewSearchResult = async (resultId, approvalStatus) => {
    if (!resultId || !selectedAgent?.id) return;
    setBusyKey(`search-review:${resultId}:${approvalStatus}`);
    try {
      await apiCall(`/saas/v1/media/search/results/${encodeURIComponent(resultId)}/approval`, {
        method: "POST",
        body: JSON.stringify({
          approval_status: approvalStatus,
          reason: approvalStatus === "rejected" ? "Rechazado desde herramientas multimodales del agente." : "",
        }),
      });
      await loadMultimodalRuns(selectedAgent.id);
      await loadMultimodalMemoryEvents();
      showStatus(approvalStatus === "approved" ? "Fuente aprobada" : "Fuente rechazada", "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setBusyKey("");
    }
  };

  const syncMultimodalMemory = async () => {
    setBusyKey("multimodal-memory-sync");
    try {
      const data = await apiCall("/saas/v1/agents/multimodal-memory/sync", {
        method: "POST",
        body: JSON.stringify({
          agent_id: selectedAgent?.id || "",
          conversation_id: multimodalDraft.conversation_id || "",
          message_id: multimodalDraft.message_id || "",
          lookback_days: 30,
          limit: 60,
          include_voice: true,
          include_vision: true,
          include_search: true,
          include_agent_runs: true,
        }),
      });
      setMultimodalMemoryEvents(data?.events || []);
      await refreshAgentOs(true);
      showStatus(`Memoria multimodal sincronizada: ${number(data?.synced || 0)} eventos`, "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setBusyKey("");
    }
  };

  const materializeMultimodalEvent = async (event, destination) => {
    if (!event?.id) return;
    const safety = asObject(event.safety_json);
    const needsCustomerApproval = Boolean(safety.contains_customer_content || safety.rag_materialization_requires_allow_customer_content);
    const allowCustomerContent = needsCustomerApproval
      ? window.confirm("Este evento puede contener texto de cliente. Confirmas materializarlo para el tenant?")
      : false;
    if (needsCustomerApproval && !allowCustomerContent) return;
    setBusyKey(`multimodal-materialize:${event.id}:${destination}`);
    try {
      await apiCall(`/saas/v1/agents/multimodal-memory/events/${encodeURIComponent(event.id)}/materialize`, {
        method: "POST",
        body: JSON.stringify({
          destination,
          title: `Multimodal ${event.source_kind}`,
          allow_customer_content: allowCustomerContent,
        }),
      });
      await loadMultimodalMemoryEvents();
      await loadAgents(true);
      showStatus(destination === "knowledge" ? "Evento enviado a RAG" : "Evento guardado en memoria colectiva", "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setBusyKey("");
    }
  };

  const createActionDraft = async () => {
    if (!selectedAgent?.id) return;
    const preset = actionPresetCatalog.find((item) => item.tool_code === actionDraft.preset) || actionPresetCatalog[0] || {};
    const title = String(actionDraft.title || "").trim() || preset.label || "Accion sugerida por agente";
    const description = String(actionDraft.description || "").trim() || preset.description || "Borrador creado desde agentes IA.";
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
          <h2>Agentes IA de Scentra</h2>
          <p>Configura agentes empresariales con canales, herramientas, memoria, permisos y politica de modelo.</p>
        </div>
        <div className="agents-hero-actions">
          <button type="button" onClick={() => loadAgents(false)} disabled={loading}>{loading ? "Actualizando..." : "Refrescar"}</button>
          <button type="button" onClick={createCustomAgent} disabled={busyKey === "create:custom" || remainingTotal <= 0}>{busyKey === "create:custom" ? "Creando..." : "Crear agente personalizado"}</button>
          <button type="button" className="primary" onClick={onOpenAdvisor}>Abrir asesor</button>
        </div>
      </article>

      <section className="metric-grid">
        <article className="metric-card mint"><span>Agentes IA</span><strong>{number(totalAgents)} / {number(limits?.max_ai_agents || 0)}</strong><small>Plan {limits?.plan_code || "starter"}</small></article>
        <article className="metric-card blue"><span>Activos</span><strong>{number(activeAgents)} / {number(limits?.max_active_ai_agents || 0)}</strong><small>{number(remainingActive)} activaciones disponibles</small></article>
        <article className="metric-card amber"><span>Constructor</span><strong>{limits?.builder_enabled ? "ON" : "OFF"}</strong><small>{limits?.notes || "Limites por plan aplicados"}</small></article>
        <article className="metric-card violet"><span>Catalogo</span><strong>{number(toolCatalog.length)}</strong><small>tools disponibles para conectar</small></article>
        <article className="metric-card"><span>Boveda memorias</span><strong>{number(usedMemoryArchives)} / {number(maxMemoryArchives)}</strong><small>{number(remainingMemoryArchives)} espacios disponibles</small></article>
        <article className="metric-card rose"><span>Score agente</span><strong>{number(runtimeMetrics.health_score || 0)} / 100</strong><small>{runtimeHealth.label || "Sin datos"} / {number(runtimeMetrics.tokens_7d || 0)} tokens 7d</small></article>
        <article className="metric-card teal"><span>Agent OS</span><strong>{agentOsPremium.mode || "demo"}</strong><small>{number(agentOsReadiness.score || 0)}% cobertura core</small></article>
      </section>

      <nav className="agent-tabs glass-card" aria-label="Secciones de agentes IA">
        <button type="button" className={agentView === "agents" ? "active" : ""} onClick={() => setAgentView("agents")}>Mis agentes</button>
        <button type="button" className={agentView === "catalog" ? "active" : ""} onClick={() => setAgentView("catalog")}>Catalogo</button>
        <button type="button" className={agentView === "memories" ? "active" : ""} onClick={() => setAgentView("memories")}>Memorias guardadas <span>{number(usedMemoryArchives)} / {number(maxMemoryArchives)}</span></button>
        <button type="button" className={agentView === "governance" ? "active" : ""} onClick={() => setAgentView("governance")}>Gobierno fase 6 <span>{number(phase6Counts.collective_memories || 0)}</span></button>
        <button type="button" className={agentView === "orchestrator" ? "active" : ""} onClick={() => setAgentView("orchestrator")}>Orquestador fase 7 <span>{number(orchestratorCounts.queued_jobs || 0)}</span></button>
        <button type="button" className={agentView === "agent-os" ? "active" : ""} onClick={() => setAgentView("agent-os")}>Agent OS <span>{number(agentOsCounts.active_subscriptions || 0)}</span></button>
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

              <section className="agent-builder-section prompt">
                <div className="agent-section-label"><strong>System prompt rellenable</strong><span>Prompt base del agente y variables que la empresa completa antes del preflight.</span></div>
                <div className="agent-editor-grid">
                  <label className="check-row">
                    <input type="checkbox" checked={Boolean(editor.isCustom)} onChange={() => patchEditor({ isCustom: !editor.isCustom })} />
                    <span><b>Agente personalizado</b><small>Permite roles propios del tenant, no solo agentes de fabrica.</small></span>
                  </label>
                  <label>Plantilla base
                    <input value={editor.baseTemplateType} onChange={(event) => patchEditor({ baseTemplateType: event.target.value })} placeholder="Ej: sales, support, custom" />
                  </label>
                </div>
                <label>Prompt operativo
                  <textarea rows={8} value={editor.systemPromptTemplate} onChange={(event) => patchEditor({ systemPromptTemplate: event.target.value })} placeholder="Define rol, limites, tono, herramientas y politicas..." />
                </label>
                <label>Variables JSON
                  <textarea rows={6} value={editor.systemPromptVariablesText} onChange={(event) => patchEditor({ systemPromptVariablesText: event.target.value })} />
                </label>
              </section>

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

              <section className="agent-builder-section">
                <div className="agent-section-label"><strong>Presupuesto y A/B testing</strong><span>Gobierna consumo, costos y experimentos antes de escalar.</span></div>
                <div className="agent-editor-grid three">
                  <label>Tokens mensuales
                    <input
                      type="number"
                      min="0"
                      value={editor.budget.monthlyTokenLimit}
                      placeholder={String(budgetDefaults.monthly_token_limit || 250000)}
                      onChange={(event) => patchEditor({ budget: { ...editor.budget, monthlyTokenLimit: event.target.value } })}
                    />
                  </label>
                  <label>Presupuesto USD/mes
                    <input
                      type="number"
                      min="0"
                      step="0.01"
                      value={editor.budget.monthlyCostLimitUsd}
                      placeholder={String(budgetDefaults.monthly_cost_limit_usd || 20)}
                      onChange={(event) => patchEditor({ budget: { ...editor.budget, monthlyCostLimitUsd: event.target.value } })}
                    />
                  </label>
                  <label>Alerta de uso %
                    <input
                      type="number"
                      min="1"
                      max="100"
                      value={editor.budget.alertThresholdPercent}
                      onChange={(event) => patchEditor({ budget: { ...editor.budget, alertThresholdPercent: event.target.value } })}
                    />
                  </label>
                </div>
                <label className="check-row">
                  <input type="checkbox" checked={Boolean(editor.budget.hardStop)} onChange={() => patchEditor({ budget: { ...editor.budget, hardStop: !editor.budget.hardStop } })} />
                  <span><b>Hard stop al superar presupuesto</b><small>Recomendado en demos o clientes con costos sensibles.</small></span>
                </label>
                <div className="agent-editor-grid three">
                  <label className="check-row">
                    <input type="checkbox" checked={Boolean(editor.experiment.enabled)} onChange={() => patchEditor({ experiment: { ...editor.experiment, enabled: !editor.experiment.enabled } })} />
                    <span><b>Activar experimento A/B</b><small>Compara este agente contra otra variante.</small></span>
                  </label>
                  <label>Variante
                    <input value={editor.experiment.variantKey} onChange={(event) => patchEditor({ experiment: { ...editor.experiment, variantKey: event.target.value } })} />
                  </label>
                  <label>Comparar contra
                    <input value={editor.experiment.compareAgainst} onChange={(event) => patchEditor({ experiment: { ...editor.experiment, compareAgainst: event.target.value } })} placeholder="Ej: Sales Agent v2" />
                  </label>
                  <label>Porcentaje trafico variante
                    <input
                      type="number"
                      min="1"
                      max="100"
                      value={editor.experiment.trafficPercent}
                      onChange={(event) => patchEditor({ experiment: { ...editor.experiment, trafficPercent: event.target.value } })}
                    />
                  </label>
                </div>
                <div className="agent-budget-summary">
                  <span><b>{number(runtimeMetrics.tokens_30d || 0)}</b><small>tokens 30d</small></span>
                  <span><b>US$ {Number(runtimeMetrics.estimated_cost_30d_usd || 0).toFixed(4)}</b><small>costo estimado 30d</small></span>
                  <span><b>{Number(runtimeMetrics.budget_usage_percent || 0).toFixed(1)}%</b><small>uso del presupuesto</small></span>
                </div>
              </section>

              <section className="agent-builder-section">
                <div className="agent-section-label"><strong>Politicas por industria</strong><span>Aplica compliance base para restaurante, hotel, clinica, legal, seguros y mas.</span></div>
                <div className="agent-filter-pills">
                  {industryPolicyPresets.map((preset) => (
                    <button type="button" key={preset.code} onClick={() => applyIndustryPolicy(preset)}>
                      {preset.label}
                    </button>
                  ))}
                  {!industryPolicyPresets.length ? <span className="soft-copy">Catalogo de politicas no cargado.</span> : null}
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
                  <div><span>Score salud</span><strong>{number(runtimeMetrics.health_score || 0)}</strong><small>precision, fallos, costo</small></div>
                  <div><span>Tokens 30d</span><strong>{number(runtimeMetrics.tokens_30d || 0)}</strong><small>{Number(runtimeMetrics.budget_usage_percent || 0).toFixed(1)}% presupuesto</small></div>
                  <div><span>Costo 30d</span><strong>US$ {Number(runtimeMetrics.estimated_cost_30d_usd || 0).toFixed(3)}</strong><small>estimado por tokens</small></div>
                </div>
                {asList(runtimeHealth.issues).length ? (
                  <div className="agent-issues">{asList(runtimeHealth.issues).map((issue) => <span key={issue}>{issue}</span>)}</div>
                ) : null}
                <div className="agent-preflight-box">
                  <div>
                    <strong>Test antes de activar</strong>
                    <span>Valida tono, canales, permisos, memoria, presupuesto y herramientas antes de ponerlo en produccion.</span>
                  </div>
                  <button type="button" className="primary" disabled={busyKey === `preflight:${selectedAgent.id}`} onClick={runPreflight}>
                    {busyKey === `preflight:${selectedAgent.id}` ? "Validando..." : "Ejecutar preflight"}
                  </button>
                </div>
                {preflightResult ? (
                  <div className={`agent-preflight-result ${preflightResult.ready ? "ready" : "blocked"}`}>
                    <div className="agent-preflight-head">
                      <strong>{preflightResult.ready ? "Listo para activar" : "Requiere ajustes"}</strong>
                      <span>Score {number(preflightResult.score || 0)} / 100</span>
                    </div>
                    <div className="agent-preflight-list">
                      {asList(preflightResult.checks).map((check) => (
                        <div className={`agent-preflight-row ${check.ok ? "ok" : "warn"}`} key={check.code}>
                          <b>{check.ok ? "OK" : "Revisar"}</b>
                          <span>{check.label}</span>
                          <small>{check.detail || check.hint}</small>
                        </div>
                      ))}
                    </div>
                    {preflightResult.recommendation ? <p>{preflightResult.recommendation}</p> : null}
                  </div>
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
            <div><h2>Memorias guardadas</h2><span>Boveda del plan: {number(usedMemoryArchives)} / {number(maxMemoryArchives)} memorias</span></div>
            <button type="button" onClick={() => loadAgents(false)}>Refrescar</button>
          </div>
          <div className="agent-import-box">
            <div>
              <strong>Importar memoria</strong>
              <span>Pega un archivo JSON exportado desde Scentra para mover contexto entre agentes o tenants enterprise.</span>
            </div>
            <textarea
              rows={4}
              value={memoryImportPayload}
              onChange={(event) => setMemoryImportPayload(event.target.value)}
              placeholder='{"schema":"scentra.agent_memory.v1","memory":{...}}'
            />
            <button type="button" className="primary" disabled={busyKey === "import-memory" || memoryVaultFull} onClick={importMemory}>
              {memoryVaultFull ? "Boveda llena" : busyKey === "import-memory" ? "Importando..." : "Importar JSON"}
            </button>
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
                <div className="agent-memory-actions">
                  <button type="button" className="primary" disabled={remainingTotal <= 0 || busyKey === `restore:${memory.id}`} onClick={() => restoreMemory(memory)}>
                    {remainingTotal <= 0 ? "Sin cupo del plan" : busyKey === `restore:${memory.id}` ? "Restaurando..." : "Crear agente desde memoria"}
                  </button>
                  <button type="button" disabled={busyKey === `export-memory:${memory.id}`} onClick={() => exportMemory(memory)}>
                    {busyKey === `export-memory:${memory.id}` ? "Exportando..." : "Exportar JSON"}
                  </button>
                  <button type="button" className="danger-button" disabled={busyKey === `delete-memory:${memory.id}`} onClick={() => deleteMemory(memory)}>
                    {busyKey === `delete-memory:${memory.id}` ? "Borrando..." : "Borrar memoria"}
                  </button>
                </div>
              </article>
            ))}
            {!memories.length ? <div className="empty">Aun no hay memorias guardadas. Cuando elimines un agente, puedes conservar su memoria aqui.</div> : null}
          </div>
        </section>
      ) : null}

      {agentView === "governance" ? (
        <section className="panel glass-card agent-governance-panel">
          <div className="panel-head">
            <div>
              <h2>Gobierno AI y memoria colectiva</h2>
              <span>Fase 6: coordina agentes, prompts, aprobaciones y memoria compartida por tenant.</span>
            </div>
            <button type="button" onClick={() => loadAgents(false)}>Refrescar</button>
          </div>

          <div className="agent-governance-grid">
            <article>
              <span>Memorias colectivas</span>
              <strong>{number(phase6Counts.collective_memories || collectiveMemories.length)}</strong>
              <small>hechos, decisiones y handoffs compartidos</small>
            </article>
            <article>
              <span>Aprobaciones pendientes</span>
              <strong>{number(phase6Counts.pending_approvals || 0)}</strong>
              <small>tool calls sensibles antes de ejecutar</small>
            </article>
            <article>
              <span>Versiones de prompt</span>
              <strong>{number(phase6Counts.prompt_versions || 0)}</strong>
              <small>control de cambios por agente</small>
            </article>
            <article>
              <span>Eventos coordinacion 7d</span>
              <strong>{number(phase6Counts.coordination_events_7d || 0)}</strong>
              <small>base para orquestador multiagente</small>
            </article>
          </div>

          <section className="agent-builder-section">
            <div className="agent-section-label">
              <strong>Orquestador propuesto</strong>
              <span>Blackboard + memoria colectiva + aprobacion humana.</span>
            </div>
            <div className="agent-orchestrator-map">
              <div><b>1. Observa</b><span>Lee eventos de inbox, CRM, workflows, comments, Meta diagnostics y runs AI.</span></div>
              <div><b>2. Coordina</b><span>Detecta conflictos entre agentes, asigna propietario y crea handoffs.</span></div>
              <div><b>3. Comparte memoria</b><span>Guarda hechos con fuente, confianza, etiquetas y alcance del tenant.</span></div>
              <div><b>4. Bloquea riesgos</b><span>Acciones sensibles pasan a aprobacion humana antes de ejecutarse.</span></div>
            </div>
          </section>

          <section className="agent-builder-section">
            <div className="agent-section-label">
              <strong>Crear memoria colectiva</strong>
              <span>Lo que un agente aprende puede servirle a los demas sin mezclar tenants.</span>
            </div>
            <div className="agent-editor-grid three">
              <label>Tipo
                <select value={collectiveDraft.memory_type} onChange={(event) => setCollectiveDraft((prev) => ({ ...prev, memory_type: event.target.value }))}>
                  <option value="fact">Hecho</option>
                  <option value="decision">Decision</option>
                  <option value="constraint">Restriccion</option>
                  <option value="insight">Insight</option>
                  <option value="handoff">Handoff</option>
                  <option value="risk">Riesgo</option>
                  <option value="preference">Preferencia</option>
                </select>
              </label>
              <label>Confianza
                <input type="number" min="0" max="100" value={collectiveDraft.confidence_score} onChange={(event) => setCollectiveDraft((prev) => ({ ...prev, confidence_score: event.target.value }))} />
              </label>
              <label>Etiquetas
                <input value={collectiveDraft.tags} onChange={(event) => setCollectiveDraft((prev) => ({ ...prev, tags: event.target.value }))} placeholder="ventas, educacion, riesgo" />
              </label>
            </div>
            <label>Titulo
              <input value={collectiveDraft.title} onChange={(event) => setCollectiveDraft((prev) => ({ ...prev, title: event.target.value }))} placeholder="Ej: Politica de descuentos aprobada" />
            </label>
            <label>Contenido
              <textarea rows={4} value={collectiveDraft.content} onChange={(event) => setCollectiveDraft((prev) => ({ ...prev, content: event.target.value }))} placeholder="Describe el aprendizaje que otros agentes deben considerar." />
            </label>
            <div className="panel-actions">
              <button type="button" className="primary" disabled={busyKey === "collective-memory"} onClick={saveCollectiveMemory}>
                {busyKey === "collective-memory" ? "Guardando..." : "Guardar memoria colectiva"}
              </button>
            </div>
          </section>

          <div className="agent-collective-list">
            {collectiveMemories.map((memory) => (
              <article className="agent-memory-card" key={memory.id}>
                <div className="agent-card-head">
                  <span>{memory.memory_type}</span>
                  <em>{typeLabel(memory.source_agent_type) || "Tenant"}</em>
                </div>
                <strong>{memory.title}</strong>
                <p>{memory.content}</p>
                <div className="agent-chip-row">
                  <span>{number(memory.confidence_score)}% confianza</span>
                  <span>{memory.visibility}</span>
                  {asList(memory.tags_json).slice(0, 4).map((tag) => <span key={tag}>{tag}</span>)}
                </div>
                <small>{memory.updated_at}</small>
                <div className="agent-memory-actions">
                  <button type="button" className="danger-button" disabled={busyKey === `delete-collective:${memory.id}`} onClick={() => deleteCollectiveMemoryItem(memory)}>
                    {busyKey === `delete-collective:${memory.id}` ? "Borrando..." : "Borrar"}
                  </button>
                </div>
              </article>
            ))}
            {!collectiveMemories.length ? <div className="empty">Aun no hay memoria colectiva. Esta es la base del futuro orquestador multiagente.</div> : null}
          </div>
        </section>
      ) : null}

      {agentView === "orchestrator" ? (
        <section className="panel glass-card agent-orchestrator-panel">
          <div className="panel-head">
            <div>
              <h2>Orquestador multiagente</h2>
              <span>Fase 7: seleccion de agente, locks, handoffs y conflictos sin ejecutar acciones sensibles.</span>
            </div>
            <div className="panel-actions inline">
              <button type="button" onClick={() => refreshOrchestrator(false)}>Refrescar</button>
              <button type="button" className="primary" disabled={busyKey === "orchestrator-tick"} onClick={runOrchestratorTick}>
                {busyKey === "orchestrator-tick" ? "Procesando..." : "Procesar tick"}
              </button>
            </div>
          </div>

          <div className="agent-governance-grid">
            <article><span>En cola</span><strong>{number(orchestratorCounts.queued_jobs || 0)}</strong><small>eventos esperando coordinacion</small></article>
            <article><span>Completados 7d</span><strong>{number(orchestratorCounts.completed_7d || 0)}</strong><small>asignaciones realizadas</small></article>
            <article><span>Handoffs 7d</span><strong>{number(orchestratorCounts.handoffs_7d || 0)}</strong><small>traspasos entre agentes</small></article>
            <article><span>Locks activos</span><strong>{number(orchestratorCounts.active_locks || 0)}</strong><small>conversaciones/casos protegidos</small></article>
            <article><span>Conflictos abiertos</span><strong>{number(orchestratorCounts.open_conflicts || 0)}</strong><small>posibles duplicados a revisar</small></article>
          </div>

          <section className="agent-builder-section">
            <div className="agent-section-label">
              <strong>Crear evento de prueba</strong>
              <span>Permite validar que el orquestador elija el agente correcto antes de depender solo de eventos reales.</span>
            </div>
            <div className="agent-editor-grid three">
              <label>Tipo de evento
                <select value={orchestratorDraft.event_type} onChange={(event) => setOrchestratorDraft((prev) => ({ ...prev, event_type: event.target.value }))}>
                  <option value="conversation.message_received">Mensaje entrante</option>
                  <option value="social.comment_received">Comentario social</option>
                  <option value="diagnostic.error_detected">Error operativo</option>
                  <option value="workflow.opportunity_detected">Oportunidad workflow</option>
                  <option value="education.student_question">Pregunta estudiante</option>
                </select>
              </label>
              <label>Entidad
                <select value={orchestratorDraft.entity_type} onChange={(event) => setOrchestratorDraft((prev) => ({ ...prev, entity_type: event.target.value }))}>
                  <option value="conversation">Conversacion</option>
                  <option value="social_comment">Comentario</option>
                  <option value="diagnostic">Diagnostico</option>
                  <option value="workflow">Workflow</option>
                  <option value="education">Educacion</option>
                </select>
              </label>
              <label>Canal
                <select value={orchestratorDraft.channel} onChange={(event) => setOrchestratorDraft((prev) => ({ ...prev, channel: event.target.value }))}>
                  {channelCatalog.map((channel) => <option key={channel.code} value={channel.code}>{channel.label}</option>)}
                </select>
              </label>
              <label>ID entidad
                <input value={orchestratorDraft.entity_id} onChange={(event) => setOrchestratorDraft((prev) => ({ ...prev, entity_id: event.target.value }))} placeholder="Opcional, se autogenera si queda vacio" />
              </label>
              <label>Prioridad
                <input type="number" min="1" max="100" value={orchestratorDraft.priority} onChange={(event) => setOrchestratorDraft((prev) => ({ ...prev, priority: event.target.value }))} />
              </label>
            </div>
            <label>Resumen del evento
              <textarea rows={3} value={orchestratorDraft.text} onChange={(event) => setOrchestratorDraft((prev) => ({ ...prev, text: event.target.value }))} placeholder="Describe lo que acaba de pasar para que el orquestador lo enrute." />
            </label>
            <div className="panel-actions">
              <button type="button" className="primary" disabled={busyKey === "orchestrator-event"} onClick={createOrchestratorEvent}>
                {busyKey === "orchestrator-event" ? "Creando..." : "Enviar evento"}
              </button>
            </div>
          </section>

          <section className="agent-builder-section">
            <div className="agent-section-label">
              <strong>Jobs recientes</strong>
              <span>Seleccion de agente, estado y motivo operativo.</span>
            </div>
            <div className="agent-orchestration-list">
              {orchestrationJobs.map((job) => {
                const result = asObject(job.result_json);
                return (
                  <article key={job.id}>
                    <div>
                      <strong>{job.event_type}</strong>
                      <span>{job.channel || "global"} / {job.entity_type} / {statusLabel(job.status)}</span>
                    </div>
                    <p>{result.selected_agent_name ? `Asignado a ${result.selected_agent_name}` : job.error || job.lock_key}</p>
                    <small>{job.created_at}</small>
                  </article>
                );
              })}
              {!orchestrationJobs.length ? <div className="empty">Aun no hay jobs del orquestador. Crea un evento de prueba o espera mensajes entrantes.</div> : null}
            </div>
          </section>

          <div className="agent-orchestrator-columns">
            <section className="agent-builder-section">
              <div className="agent-section-label"><strong>Locks activos</strong><span>Evitan respuestas o acciones duplicadas.</span></div>
              <div className="agent-mini-list">
                {orchestrationLocks.map((item) => <div key={item.lock_key}><strong>{item.lock_key}</strong><span>vence {item.expires_at}</span></div>)}
                {!orchestrationLocks.length ? <div className="empty">Sin locks activos.</div> : null}
              </div>
            </section>
            <section className="agent-builder-section">
              <div className="agent-section-label"><strong>Handoffs</strong><span>Traspasos propuestos entre agentes.</span></div>
              <div className="agent-mini-list">
                {orchestrationHandoffs.map((item) => <div key={item.id}><strong>{item.reason}</strong><span>{item.status} / {item.created_at}</span></div>)}
                {!orchestrationHandoffs.length ? <div className="empty">Sin handoffs por ahora.</div> : null}
              </div>
            </section>
            <section className="agent-builder-section">
              <div className="agent-section-label"><strong>Conflictos</strong><span>Cuando otro agente ya tiene ownership temporal.</span></div>
              <div className="agent-mini-list">
                {orchestrationConflicts.map((item) => <div key={item.id}><strong>{item.lock_key}</strong><span>{item.resolution_status} / {item.created_at}</span></div>)}
                {!orchestrationConflicts.length ? <div className="empty">Sin conflictos abiertos.</div> : null}
              </div>
            </section>
          </div>
        </section>
      ) : null}

      {agentView === "agent-os" ? (
        <section className="panel glass-card agent-orchestrator-panel">
          <div className="panel-head">
            <div>
              <h2>Multi-Agent Operating System</h2>
              <span>Fase 11: agentes coordinados por eventos, memoria compartida, tools con aprobacion y observabilidad.</span>
            </div>
            <div className="panel-actions inline">
              <button type="button" onClick={() => refreshAgentOs(false)}>Refrescar</button>
              <button type="button" className="primary" disabled={busyKey === "agent-os-sync"} onClick={syncAgentOsEvents}>
                {busyKey === "agent-os-sync" ? "Sincronizando..." : "Sincronizar eventos IA"}
              </button>
            </div>
          </div>

          <div className="agent-governance-grid">
            <article><span>Modo premium</span><strong>{agentOsPremium.mode || "demo"}</strong><small>{agentOsPremium.enabled ? "event-driven activo" : agentOsPremium.demo_mode ? "preview sin encolar jobs" : "feature deshabilitada"}</small></article>
            <article><span>Cobertura core</span><strong>{number(agentOsReadiness.score || 0)}%</strong><small>{number(agentOsCoverage.filter((item) => item.active).length)} agentes activos</small></article>
            <article><span>Mensajes 7d</span><strong>{number(agentOsCounts.messages_7d || 0)}</strong><small>comunicacion inter-agente</small></article>
            <article><span>Tool runs</span><strong>{number(agentOsCounts.tool_runs_7d || 0)}</strong><small>{number(agentOsCounts.pending_tool_runs || 0)} pendientes</small></article>
            <article><span>Traces 7d</span><strong>{number(agentOsCounts.traces_7d || 0)}</strong><small>runtime, sync y herramientas</small></article>
          </div>

          <section className="agent-builder-section">
            <div className="agent-section-label">
              <strong>Arquitectura de memoria</strong>
              <span>Cada capa se mantiene aislada por tenant y alimenta al orquestador sin mezclar datos entre empresas.</span>
            </div>
            <div className="agent-orchestrator-map">
              {Object.entries(agentOsMemoryLayers).map(([key, layer]) => {
                const info = asObject(layer);
                return (
                  <div key={key}>
                    <b>{key.replace(/_/g, " ")}</b>
                    <span>{info.status || "unknown"} / {number(info.records || 0)} registros</span>
                  </div>
                );
              })}
              {!Object.keys(agentOsMemoryLayers).length ? <div><b>Sin snapshot</b><span>Refresca Agent OS para cargar memoria.</span></div> : null}
            </div>
          </section>

          <section className="agent-builder-section">
            <div className="agent-section-label">
              <strong>Agentes especializados</strong>
              <span>Los faltantes pueden existir como draft; solo los activos participan en coordinacion runtime.</span>
            </div>
            <div className="agent-chip-row wide">
              {agentOsCoverage.map((item) => (
                <span key={item.agent_type} className={item.active ? "agent-status ok" : item.configured ? "agent-status warn" : "agent-status muted"}>
                  {typeLabel(item.agent_type)}: {item.active ? "activo" : item.configured ? "draft/pausado" : "faltante"}
                </span>
              ))}
              {!agentOsCoverage.length ? <span>Sin cobertura cargada</span> : null}
            </div>
          </section>

          <div className="agent-orchestrator-columns">
            <section className="agent-builder-section">
              <div className="agent-section-label"><strong>Subscripciones event-driven</strong><span>Mapean senales predictivas hacia agentes.</span></div>
              <div className="agent-mini-list">
                {agentOsSubscriptions.slice(0, 8).map((item) => (
                  <div key={item.id}>
                    <strong>{item.event_type}</strong>
                    <span>{typeLabel(item.agent_type)} / prioridad {number(item.priority)} / {item.mode}</span>
                  </div>
                ))}
                {!agentOsSubscriptions.length ? <div className="empty">Sin subscripciones inicializadas.</div> : null}
              </div>
            </section>
            <section className="agent-builder-section">
              <div className="agent-section-label"><strong>Mensajes inter-agente</strong><span>Contexto, delegaciones y handoffs.</span></div>
              <div className="agent-mini-list">
                {agentOsMessages.slice(0, 8).map((item) => (
                  <div key={item.id}>
                    <strong>{item.subject || item.message_type}</strong>
                    <span>{item.source_agent_name || "Sistema"} {"->"} {item.target_agent_name || "Todos"} / {item.status}</span>
                  </div>
                ))}
                {!agentOsMessages.length ? <div className="empty">Sin mensajes Agent OS recientes.</div> : null}
              </div>
            </section>
            <section className="agent-builder-section">
              <div className="agent-section-label"><strong>Tool runs</strong><span>Las herramientas quedan como borrador aprobable.</span></div>
              <div className="agent-mini-list">
                {agentOsToolRuns.slice(0, 8).map((item) => (
                  <div key={item.id}>
                    <strong>{item.tool_code}</strong>
                    <span>{item.agent_name} / {item.status} / {item.risk_level}</span>
                  </div>
                ))}
                {!agentOsToolRuns.length ? <div className="empty">Sin tool runs registrados.</div> : null}
              </div>
            </section>
          </div>

          <section className="agent-builder-section">
            <div className="agent-section-label">
              <strong>Herramientas multimodales para agentes</strong>
              <span>Ejecutan analisis de audio, vision o busqueda externa como contexto trazable; no envian mensajes ni modifican CRM.</span>
            </div>
            <div className="agent-chip-row wide">
              {agentMultimodalTools.map((tool) => (
                <span key={tool.code} className={asList(selectedAgent?.tools_json).includes(tool.code) ? "agent-status ok" : "agent-status muted"}>
                  {tool.label || tool.code}: {asList(selectedAgent?.tools_json).includes(tool.code) ? "permitida" : "no asignada"}
                </span>
              ))}
              {!agentMultimodalTools.length ? <span>Sin herramientas multimodales en catalogo.</span> : null}
            </div>
            <div className="agent-import-box">
              <div>
                <strong>Ejecutar herramienta</strong>
                <span>Usa IDs reales del Inbox. La busqueda externa deja resultados pendientes de aprobacion humana.</span>
              </div>
              <div className="form-grid two">
                <label>
                  <span>Herramienta</span>
                  <select value={multimodalDraft.tool_code} onChange={(event) => setMultimodalDraft((prev) => ({ ...prev, tool_code: event.target.value }))}>
                    {(agentMultimodalTools.length ? agentMultimodalTools : [
                      { code: "media.voice_analyze", label: "Analizar audio" },
                      { code: "media.vision_analyze", label: "Analizar imagen/documento" },
                      { code: "media.web_image_search", label: "Buscar web/imagen" },
                    ]).map((tool) => <option key={tool.code} value={tool.code}>{tool.label || tool.code}</option>)}
                  </select>
                </label>
                <label>
                  <span>Message ID</span>
                  <input value={multimodalDraft.message_id} onChange={(event) => setMultimodalDraft((prev) => ({ ...prev, message_id: event.target.value }))} placeholder="UUID del mensaje con media" />
                </label>
                <label>
                  <span>Conversation ID</span>
                  <input value={multimodalDraft.conversation_id} onChange={(event) => setMultimodalDraft((prev) => ({ ...prev, conversation_id: event.target.value }))} placeholder="Opcional para busqueda/contexto" />
                </label>
                <label>
                  <span>Proveedor</span>
                  <input value={multimodalDraft.provider_code} onChange={(event) => setMultimodalDraft((prev) => ({ ...prev, provider_code: event.target.value }))} placeholder="google, kimi, tavily..." />
                </label>
                {multimodalDraft.tool_code === "media.web_image_search" ? (
                  <>
                    <label>
                      <span>Consulta</span>
                      <input value={multimodalDraft.query} onChange={(event) => setMultimodalDraft((prev) => ({ ...prev, query: event.target.value }))} placeholder="Foto/referencia/fuente a buscar" />
                    </label>
                    <label>
                      <span>Tipo busqueda</span>
                      <select value={multimodalDraft.search_type} onChange={(event) => setMultimodalDraft((prev) => ({ ...prev, search_type: event.target.value }))}>
                        <option value="mixed">Mixta</option>
                        <option value="web">Web</option>
                        <option value="image">Imagen</option>
                      </select>
                    </label>
                    <label>
                      <span>Limite</span>
                      <input type="number" min="1" max="12" value={multimodalDraft.limit} onChange={(event) => setMultimodalDraft((prev) => ({ ...prev, limit: event.target.value }))} />
                    </label>
                  </>
                ) : (
                  <label className="check-row">
                    <input type="checkbox" checked={Boolean(multimodalDraft.force)} onChange={(event) => setMultimodalDraft((prev) => ({ ...prev, force: event.target.checked }))} />
                    <span><b>Reanalizar</b><small>Ignora cache si ya existe analisis.</small></span>
                  </label>
                )}
              </div>
              <button type="button" className="primary" disabled={!selectedAgent?.id || busyKey.startsWith("multimodal:")} onClick={executeMultimodalTool}>
                {busyKey.startsWith("multimodal:") ? "Ejecutando..." : "Ejecutar"}
              </button>
            </div>
            <div className="agent-orchestration-list">
              {agentMultimodalRuns.slice(0, 8).map((item) => {
                const output = asObject(item.output_json);
                const results = asList(output.results);
                return (
                  <article key={item.id}>
                    <div>
                      <strong>{item.tool_code}</strong>
                      <span>{statusLabel(item.status)} / {item.approval_status || "not_required"} / {item.updated_at}</span>
                    </div>
                    <p>{output.summary || output.visual_description || output.query || output.error?.code || output.safety || item.error_text || "Sin salida compacta."}</p>
                    {results.length ? (
                      <div className="agent-mini-list">
                        {results.slice(0, 4).map((result) => (
                          <div key={result.id || result.url}>
                            <strong>{result.title || result.url}</strong>
                            <span>{result.source_name || result.result_type} / {result.safety_status} / {result.approval_status}</span>
                            <small>{result.snippet || result.url}</small>
                            <div className="agent-memory-actions">
                              <button type="button" disabled={!result.id || result.safety_status === "blocked" || busyKey.startsWith(`search-review:${result.id}`)} onClick={() => reviewSearchResult(result.id, "approved")}>Aprobar fuente</button>
                              <button type="button" disabled={!result.id || busyKey.startsWith(`search-review:${result.id}`)} onClick={() => reviewSearchResult(result.id, "rejected")}>Rechazar</button>
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : null}
                    <small>{item.id}</small>
                  </article>
                );
              })}
              {!agentMultimodalRuns.length ? <div className="empty">Sin herramientas multimodales ejecutadas para este agente.</div> : null}
            </div>
          </section>

          <section className="agent-builder-section">
            <div className="agent-section-label">
              <strong>Memoria y training multimodal</strong>
              <span>Destila resultados utiles de voz, vision, fuentes aprobadas y tool-runs para ML, RAG y memoria de agentes.</span>
            </div>
            <div className="agent-governance-grid">
              <article><span>Eventos memoria</span><strong>{number(agentOsCounts.multimodal_memory_events || agentMultimodalMemoryEvents.length)}</strong><small>senales tenant-scoped</small></article>
              <article><span>Training ready</span><strong>{number(agentOsCounts.multimodal_training_events || agentMultimodalMemoryEvents.filter((item) => item.eligible_for_training).length)}</strong><small>features limpias para ML</small></article>
              <article><span>RAG candidates</span><strong>{number(agentOsCounts.multimodal_rag_candidates || agentMultimodalMemoryEvents.filter((item) => item.eligible_for_rag).length)}</strong><small>fuentes revisables</small></article>
              <article><span>Materializados</span><strong>{number(agentMultimodalMemoryEvents.filter((item) => item.knowledge_source_id || item.collective_memory_id).length)}</strong><small>RAG o memoria colectiva</small></article>
            </div>
            <div className="panel-actions inline">
              <button type="button" className="primary" disabled={busyKey === "multimodal-memory-sync"} onClick={syncMultimodalMemory}>
                {busyKey === "multimodal-memory-sync" ? "Sincronizando..." : "Sincronizar eventos"}
              </button>
              <button type="button" onClick={loadMultimodalMemoryEvents}>Refrescar memoria</button>
            </div>
            <div className="agent-orchestration-list">
              {agentMultimodalMemoryEvents.slice(0, 10).map((event) => {
                const features = asObject(event.training_features_json);
                const safety = asObject(event.safety_json);
                return (
                  <article key={event.id}>
                    <div>
                      <strong>{event.source_kind} / {event.event_type}</strong>
                      <span>{event.approval_status} / training {event.eligible_for_training ? "si" : "no"} / RAG {event.eligible_for_rag ? "si" : "no"}</span>
                    </div>
                    <p>{event.memory_text || "Sin texto de memoria."}</p>
                    <div className="agent-chip-row">
                      <span>conf {number(features.confidence || 0)}</span>
                      <span>sent {number(features.sentiment_score || 0)}</span>
                      <span>urg {number(features.urgency_score || 0)}</span>
                      {event.knowledge_source_id ? <span>RAG activo</span> : null}
                      {event.collective_memory_id ? <span>Memoria activa</span> : null}
                      {safety.contains_customer_content ? <span>cliente</span> : <span>externo/aprobado</span>}
                    </div>
                    <div className="agent-memory-actions">
                      <button
                        type="button"
                        disabled={Boolean(event.knowledge_source_id) || busyKey.startsWith(`multimodal-materialize:${event.id}`)}
                        onClick={() => materializeMultimodalEvent(event, "knowledge")}
                      >
                        {event.knowledge_source_id ? "En RAG" : "Enviar a RAG"}
                      </button>
                      <button
                        type="button"
                        disabled={Boolean(event.collective_memory_id) || busyKey.startsWith(`multimodal-materialize:${event.id}`)}
                        onClick={() => materializeMultimodalEvent(event, "collective_memory")}
                      >
                        {event.collective_memory_id ? "En memoria" : "Guardar memoria"}
                      </button>
                    </div>
                    <small>{event.updated_at} / {event.id}</small>
                  </article>
                );
              })}
              {!agentMultimodalMemoryEvents.length ? <div className="empty">Sin eventos multimodales sincronizados todavia.</div> : null}
            </div>
          </section>

          <section className="agent-builder-section">
            <div className="agent-section-label">
              <strong>Observabilidad AI</strong>
              <span>Tracing de razonamiento, sincronizacion, providers, tokens y latencia.</span>
            </div>
            <div className="agent-orchestration-list">
              {agentOsTraces.slice(0, 10).map((item) => (
                <article key={item.id}>
                  <div>
                    <strong>{item.trace_type} / {item.trace_status}</strong>
                    <span>{item.agent_name || "Agent OS"} / {item.provider_code || "internal"} / {number(item.tokens_total || 0)} tokens</span>
                  </div>
                  <p>{item.output_summary || item.input_summary || item.step_key}</p>
                  <small>{item.created_at}</small>
                </article>
              ))}
              {!agentOsTraces.length ? <div className="empty">Sin traces recientes. La sincronizacion event-driven registrara trazas cuando el modo full este activo.</div> : null}
            </div>
          </section>
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
            {memoryVaultFull ? (
              <div className="agent-vault-warning">
                <strong>Boveda de memorias llena</strong>
                <span>Este plan ya usa {number(usedMemoryArchives)} de {number(maxMemoryArchives)} memorias. Si eliminas el agente ahora, su memoria se perdera porque no hay espacio para guardarla.</span>
              </div>
            ) : null}
            <label className="check-row">
              <input
                type="checkbox"
                checked={Boolean(archiveDraft.preserveMemory) && !memoryVaultFull}
                disabled={memoryVaultFull}
                onChange={(event) => setArchiveDraft((prev) => ({ ...prev, preserveMemory: memoryVaultFull ? false : event.target.checked }))}
              />
              <span><b>Conservar memoria del agente</b><small>Guarda un snapshot reutilizable en la subpestana Memorias guardadas.</small></span>
            </label>
            {archiveDraft.preserveMemory && !memoryVaultFull ? (
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
                {busyKey === `archive:${archiveDraft.agent?.id}` ? "Eliminando..." : memoryVaultFull ? "Eliminar sin guardar memoria" : "Eliminar agente"}
              </button>
            </div>
          </section>
        </div>
      ) : null}
    </section>
  );
}
