import React, { useEffect, useMemo, useState } from "react";

const FALLBACK_CHANNELS = [
  { code: "global", label: "Global", description: "Analisis interno." },
  { code: "whatsapp", label: "WhatsApp", description: "Conversaciones WhatsApp." },
  { code: "instagram", label: "Instagram", description: "DMs y comentarios." },
];

const FALLBACK_PROVIDERS = [
  { code: "gemini", label: "Google Gemini" },
  { code: "mistral", label: "Mistral" },
  { code: "openrouter", label: "OpenRouter" },
  { code: "kimi", label: "Kimi" },
];

const FALLBACK_ROUTES = [
  { code: "advisor", label: "Advisor" },
  { code: "sales", label: "Ventas" },
  { code: "support", label: "Soporte" },
  { code: "ops", label: "Operaciones" },
];

const number = (value) => Number(value || 0).toLocaleString("es-CO");

const statusLabel = (status) => ({
  active: "Activo",
  paused: "Pausado",
  draft: "Borrador",
  archived: "Archivado",
}[String(status || "").toLowerCase()] || status || "Borrador");

const statusTone = (status) => ({
  active: "ok",
  paused: "warn",
  draft: "neutral",
  archived: "muted",
}[String(status || "").toLowerCase()] || "neutral");

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
}[String(type || "").toLowerCase()] || type);

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
    preferredProvider: String(providerPolicy.preferred || "gemini"),
    fallbackProvider: String(providerPolicy.fallback || "openrouter"),
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

export default function AiAgentsPanel({ apiCall, showStatus, onOpenAdvisor, onOpenSettings }) {
  const [agents, setAgents] = useState([]);
  const [templates, setTemplates] = useState([]);
  const [catalog, setCatalog] = useState({});
  const [limits, setLimits] = useState(null);
  const [events, setEvents] = useState([]);
  const [selectedAgentId, setSelectedAgentId] = useState("");
  const [editor, setEditor] = useState(null);
  const [eventNote, setEventNote] = useState("");
  const [dirty, setDirty] = useState(false);
  const [loading, setLoading] = useState(false);
  const [busyKey, setBusyKey] = useState("");

  const selectedAgent = useMemo(
    () => agents.find((agent) => agent.id === selectedAgentId) || agents[0] || null,
    [agents, selectedAgentId],
  );
  const activeAgents = agents.filter((agent) => agent.status === "active").length;
  const totalAgents = agents.filter((agent) => agent.status !== "archived").length;
  const remainingTotal = Number(limits?.remaining?.total ?? 0);
  const remainingActive = Number(limits?.remaining?.active ?? 0);
  const channelCatalog = asList(catalog.channels).length ? catalog.channels : FALLBACK_CHANNELS;
  const toolCatalog = asList(catalog.tools);
  const providerCatalog = asList(catalog.providers).length ? catalog.providers : FALLBACK_PROVIDERS;
  const routeCatalog = asList(catalog.provider_routes).length ? catalog.provider_routes : FALLBACK_ROUTES;
  const memoryFlags = asList(catalog.memory_flags);
  const approvalFlags = asList(catalog.approval_flags);
  const groupedTools = groupBy(toolCatalog, "group");

  const loadAgents = async (silent = false) => {
    setLoading(true);
    try {
      const [agentData, templateData, catalogData] = await Promise.all([
        apiCall("/saas/v1/agents"),
        apiCall("/saas/v1/agents/templates"),
        apiCall("/saas/v1/agents/catalog"),
      ]);
      const nextAgents = agentData?.agents || [];
      setAgents(nextAgents);
      setTemplates(templateData?.templates || []);
      setCatalog(catalogData?.catalog || {});
      setLimits(agentData?.limits || null);
      if (!selectedAgentId && nextAgents[0]?.id) setSelectedAgentId(nextAgents[0].id);
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

  useEffect(() => { loadAgents(true); }, []);
  useEffect(() => {
    if (!selectedAgent?.id) return;
    setEditor(makeEditor(selectedAgent));
    setDirty(false);
    loadEvents(selectedAgent.id);
  }, [selectedAgent?.id]);

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
      showStatus(nextStatus === "active" ? "Agente activado" : nextStatus === "paused" ? "Agente pausado" : "Agente archivado", "ok");
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
      showStatus("Nota agregada al agente", "ok");
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
      </section>

      <section className="agents-layout builder">
        <article className="panel glass-card">
          <div className="panel-head">
            <div><h2>Agentes configurados</h2><span>{number(remainingTotal)} espacios disponibles</span></div>
          </div>
          <div className="agent-card-grid">
            {agents.map((agent) => {
              const metrics = agent.metrics_json || {};
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
                    <span>{number(metrics.pending_actions || 0)} acciones</span>
                    <span>{number(metrics.open_insights || 0)} insights</span>
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
              </div>
            </div>
          ) : <div className="empty">Selecciona un agente para abrir el builder.</div>}
        </article>
      </section>

      <section className="agents-layout bottom">
        <article className="panel glass-card">
          <div className="panel-head">
            <div><h2>Plantillas de agentes</h2><span>creacion guiada por tipo de agente</span></div>
          </div>
          <div className="template-agent-grid">
            {templates.map((template) => {
              const alreadyExists = agents.some((agent) => agent.agent_type === template.agent_type && agent.status !== "archived");
              const disabled = alreadyExists || remainingTotal <= 0 || !limits?.builder_enabled || busyKey === `create:${template.agent_type}`;
              return (
                <article className="template-agent-card" key={template.agent_type}>
                  <div className="agent-card-head">
                    <span>{template.category}</span>
                    <em>{typeLabel(template.agent_type)}</em>
                  </div>
                  <strong>{template.name}</strong>
                  <p>{template.headline}</p>
                  <div className="agent-chip-row">
                    {asList(template.channels).slice(0, 3).map((item) => <span key={item}>{item}</span>)}
                  </div>
                  <button type="button" className={alreadyExists ? "" : "primary"} disabled={disabled} onClick={() => createFromTemplate(template.agent_type)}>
                    {alreadyExists ? "Ya creado" : remainingTotal <= 0 ? "Limite del plan" : "Crear agente"}
                  </button>
                </article>
              );
            })}
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
    </section>
  );
}
