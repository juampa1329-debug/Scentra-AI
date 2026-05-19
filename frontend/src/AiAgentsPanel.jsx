import React, { useEffect, useMemo, useState } from "react";

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

export default function AiAgentsPanel({ apiCall, showStatus, onOpenAdvisor, onOpenSettings }) {
  const [agents, setAgents] = useState([]);
  const [templates, setTemplates] = useState([]);
  const [limits, setLimits] = useState(null);
  const [events, setEvents] = useState([]);
  const [selectedAgentId, setSelectedAgentId] = useState("");
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

  const loadAgents = async (silent = false) => {
    setLoading(true);
    try {
      const [agentData, templateData] = await Promise.all([
        apiCall("/saas/v1/agents"),
        apiCall("/saas/v1/agents/templates"),
      ]);
      const nextAgents = agentData?.agents || [];
      setAgents(nextAgents);
      setTemplates(templateData?.templates || []);
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
  useEffect(() => { if (selectedAgent?.id) loadEvents(selectedAgent.id); }, [selectedAgent?.id]);

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

  return (
    <section className="agents-page">
      <article className="agents-hero glass-card">
        <div>
          <p className="eyebrow">Agent Operating System</p>
          <h2>Scentra AI Agents</h2>
          <p>Administra agentes empresariales para ventas, soporte, CRM, campanas, retencion, operaciones y estrategia.</p>
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
        <article className="metric-card violet"><span>Templates</span><strong>{number(templates.length)}</strong><small>Sistema omnicanal modular</small></article>
      </section>

      <section className="agents-layout">
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

        <article className="panel glass-card">
          <div className="panel-head">
            <div><h2>Detalle del agente</h2><span>configuracion inicial</span></div>
          </div>
          {selectedAgent ? (
            <div className="agent-detail">
              <div className="agent-detail-title">
                <div><strong>{selectedAgent.name}</strong><span>{typeLabel(selectedAgent.agent_type)} / {statusLabel(selectedAgent.status)}</span></div>
                <span className={`agent-status ${statusTone(selectedAgent.status)}`}>{selectedAgent.status}</span>
              </div>
              <p>{selectedAgent.description}</p>
              <h3>Objetivos</h3>
              <div className="agent-list">
                {asList(selectedAgent.goals_json).map((goal) => <span key={goal}>{goal}</span>)}
              </div>
              <h3>Herramientas</h3>
              <div className="agent-chip-row wide">
                {asList(selectedAgent.tools_json).map((tool) => <span key={tool}>{tool}</span>)}
              </div>
              <h3>Politica AI</h3>
              <div className="agent-policy">
                <span>Ruta: <b>{selectedAgent.provider_policy_json?.route || "default"}</b></span>
                <span>Preferido: <b>{selectedAgent.provider_policy_json?.preferred || "auto"}</b></span>
                <span>Fallback: <b>{selectedAgent.provider_policy_json?.fallback || "openrouter"}</b></span>
              </div>
              <div className="panel-actions">
                {selectedAgent.status !== "active" ? <button type="button" className="primary" disabled={busyKey === `active:${selectedAgent.id}`} onClick={() => setStatus(selectedAgent, "active")}>Activar</button> : null}
                {selectedAgent.status === "active" ? <button type="button" disabled={busyKey === `paused:${selectedAgent.id}`} onClick={() => setStatus(selectedAgent, "paused")}>Pausar</button> : null}
                {selectedAgent.agent_type === "advisor" ? <button type="button" onClick={onOpenAdvisor}>Abrir copiloto</button> : null}
                <button type="button" onClick={onOpenSettings}>Configurar modelos</button>
              </div>
            </div>
          ) : <div className="empty">Selecciona un agente para ver su configuracion.</div>}
        </article>
      </section>

      <section className="agents-layout bottom">
        <article className="panel glass-card">
          <div className="panel-head">
            <div><h2>Builder visual por plantillas</h2><span>fase 1: registry seguro</span></div>
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
            <div><h2>Actividad</h2><span>auditoria de agentes</span></div>
          </div>
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
