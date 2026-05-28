import React, { useEffect, useMemo, useState } from "react";

const tabs = [
  ["overview", "Centro"],
  ["policies", "Politicas"],
  ["risks", "Riesgos"],
  ["models", "Model cards"],
  ["incidents", "Incidentes"],
  ["audit", "Auditoria"],
];

const blankPolicy = () => ({
  policy_key: "tenant.custom_policy",
  name: "Politica AI personalizada",
  description: "",
  status: "enabled",
  risk_tier: "medium",
  enforcement_mode: "monitor",
  applies_to_json: ["agents"],
  rules_json: { requires_approval: true },
});

const blankModelCard = () => ({
  model_key: "tenant.model.v1",
  provider_key: "baseline_rules",
  task_type: "lead_scoring",
  version: "v1",
  status: "draft",
  intended_use: "",
  limitations: "",
  training_data_json: { source: "postgres_auto_labels" },
  evaluation_json: {},
  rollout_json: { mode: "shadow" },
  compliance_json: { human_review_required: true },
});

const blankIncident = () => ({
  incident_type: "ai_governance",
  severity: "medium",
  entity_type: "agent",
  entity_id: "",
  title: "Incidente de gobierno AI",
  description: "",
  remediation_json: { next_step: "review" },
});

function number(value) {
  return Number(value || 0).toLocaleString("es-CO");
}

function shortDate(value) {
  if (!value) return "-";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value).slice(0, 16);
  return parsed.toLocaleString("es-CO", { dateStyle: "short", timeStyle: "short" });
}

function compactJson(value) {
  try {
    return JSON.stringify(value || {}, null, 2);
  } catch {
    return "{}";
  }
}

function parseJson(value, fallback) {
  try {
    const parsed = JSON.parse(value || "");
    return parsed && typeof parsed === "object" ? parsed : fallback;
  } catch {
    return fallback;
  }
}

function parseList(value) {
  return String(value || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function StatusBadge({ value }) {
  const clean = String(value || "off").toLowerCase();
  const tone = ["enabled", "full", "completed", "attested", "closed", "low"].includes(clean)
    ? "ok"
    : ["demo", "draft", "open", "medium", "monitoring"].includes(clean)
      ? "warn"
      : clean.includes("high") || clean.includes("critical")
        ? "danger"
        : "neutral";
  return <span className={`status-pill ${tone}`}>{value || "-"}</span>;
}

function FeatureMode({ item }) {
  if (!item) return <StatusBadge value="disabled" />;
  return <StatusBadge value={item.mode || (item.enabled ? "enabled" : "disabled")} />;
}

export default function TrustCenterPanel({ apiCall, showStatus }) {
  const [activeTab, setActiveTab] = useState("overview");
  const [overview, setOverview] = useState(null);
  const [policies, setPolicies] = useState([]);
  const [risks, setRisks] = useState([]);
  const [modelCards, setModelCards] = useState([]);
  const [registryModels, setRegistryModels] = useState([]);
  const [incidents, setIncidents] = useState([]);
  const [audits, setAudits] = useState([]);
  const [reports, setReports] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [policyForm, setPolicyForm] = useState(blankPolicy);
  const [policyRulesText, setPolicyRulesText] = useState(compactJson(blankPolicy().rules_json));
  const [modelForm, setModelForm] = useState(blankModelCard);
  const [modelJsonText, setModelJsonText] = useState(compactJson({
    training_data_json: blankModelCard().training_data_json,
    evaluation_json: {},
    rollout_json: blankModelCard().rollout_json,
    compliance_json: blankModelCard().compliance_json,
  }));
  const [incidentForm, setIncidentForm] = useState(blankIncident);
  const [incidentJsonText, setIncidentJsonText] = useState(compactJson(blankIncident().remediation_json));

  const features = overview?.features || {};
  const accessMode = overview?.access?.mode || "disabled";
  const canWrite = Object.values(features).some((item) => item?.mode === "full") || accessMode === "full";
  const counts = overview?.counts || {};
  const signals = overview?.source_signals || {};
  const riskGroups = useMemo(() => {
    const grouped = { critical: 0, high: 0, medium: 0, low: 0 };
    (risks || []).forEach((item) => {
      const key = String(item.risk_level || "medium").toLowerCase();
      grouped[key] = (grouped[key] || 0) + 1;
    });
    return grouped;
  }, [risks]);

  const loadAll = async (silent = false) => {
    setLoading(true);
    try {
      const [overviewData, policiesData, risksData, modelsData, incidentsData, auditsData, reportsData] = await Promise.all([
        apiCall("/saas/v1/trust-center/overview").catch(() => null),
        apiCall("/saas/v1/trust-center/policies").catch(() => ({ policies: [] })),
        apiCall("/saas/v1/trust-center/risk-assessments").catch(() => ({ assessments: [] })),
        apiCall("/saas/v1/trust-center/model-cards").catch(() => ({ model_cards: [], registry_models: [] })),
        apiCall("/saas/v1/trust-center/incidents").catch(() => ({ incidents: [] })),
        apiCall("/saas/v1/trust-center/audits?limit=120").catch(() => ({ audits: [] })),
        apiCall("/saas/v1/trust-center/reports").catch(() => ({ reports: [] })),
      ]);
      setOverview(overviewData || null);
      setPolicies(policiesData?.policies || []);
      setRisks(risksData?.assessments || []);
      setModelCards(modelsData?.model_cards || []);
      setRegistryModels(modelsData?.registry_models || []);
      setIncidents(incidentsData?.incidents || []);
      setAudits(auditsData?.audits || []);
      setReports(reportsData?.reports || []);
      if (!silent) showStatus("Trust Center actualizado", "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadAll(true); }, []);

  const runAction = async (key, fn, okMessage) => {
    setBusy(key);
    try {
      await fn();
      showStatus(okMessage, "ok");
      await loadAll(true);
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setBusy("");
    }
  };

  const savePolicy = () => runAction("policy", async () => {
    await apiCall("/saas/v1/trust-center/policies", {
      method: "POST",
      body: JSON.stringify({
        ...policyForm,
        applies_to_json: Array.isArray(policyForm.applies_to_json) ? policyForm.applies_to_json : parseList(policyForm.applies_to_json),
        rules_json: parseJson(policyRulesText, {}),
      }),
    });
  }, "Politica guardada");

  const attestPolicy = (policyId) => runAction(`attest-${policyId}`, async () => {
    await apiCall(`/saas/v1/trust-center/policies/${encodeURIComponent(policyId)}/attest`, {
      method: "POST",
      body: JSON.stringify({ notes: "Revision humana desde Trust Center", evidence_json: { ui: "trust_center" } }),
    });
  }, "Politica atestada");

  const runRiskAssessment = (persist = true) => runAction(persist ? "risk-run" : "risk-preview", async () => {
    await apiCall("/saas/v1/trust-center/risk-assessments/run", {
      method: "POST",
      body: JSON.stringify({ scope: "all", persist, max_items: 160 }),
    });
  }, persist ? "Evaluacion de riesgos guardada" : "Preview de riesgos generado");

  const closeRisk = (assessment) => runAction(`risk-${assessment.id}`, async () => {
    await apiCall(`/saas/v1/trust-center/risk-assessments/${encodeURIComponent(assessment.id)}`, {
      method: "PATCH",
      body: JSON.stringify({
        status: "mitigated",
        mitigations_json: [...(assessment.mitigations_json || []), { action: "Reviewed from Trust Center" }],
        evidence_json: { ...(assessment.evidence_json || {}), reviewed_from_ui: true },
      }),
    });
  }, "Riesgo marcado como mitigado");

  const saveModelCard = () => runAction("model-card", async () => {
    const blocks = parseJson(modelJsonText, {});
    await apiCall("/saas/v1/trust-center/model-cards", {
      method: "POST",
      body: JSON.stringify({
        ...modelForm,
        training_data_json: blocks.training_data_json || {},
        evaluation_json: blocks.evaluation_json || {},
        rollout_json: blocks.rollout_json || {},
        compliance_json: blocks.compliance_json || {},
      }),
    });
  }, "Model card guardada");

  const saveIncident = () => runAction("incident", async () => {
    await apiCall("/saas/v1/trust-center/incidents", {
      method: "POST",
      body: JSON.stringify({ ...incidentForm, remediation_json: parseJson(incidentJsonText, {}) }),
    });
  }, "Incidente registrado");

  const closeIncident = (incident) => runAction(`incident-${incident.id}`, async () => {
    await apiCall(`/saas/v1/trust-center/incidents/${encodeURIComponent(incident.id)}`, {
      method: "PATCH",
      body: JSON.stringify({ status: "closed", remediation_json: { ...(incident.remediation_json || {}), closed_from_ui: true } }),
    });
  }, "Incidente cerrado");

  const generateReport = () => runAction("report", async () => {
    await apiCall("/saas/v1/trust-center/reports/generate", {
      method: "POST",
      body: JSON.stringify({ report_type: "trust_summary" }),
    });
  }, "Reporte generado");

  if (loading) return <section className="panel glass-card"><p>Cargando Trust Center...</p></section>;

  return (
    <section className="trust-center">
      <div className="trust-hero glass-card">
        <div>
          <p className="eyebrow">AI Trust, Compliance & Governance</p>
          <h2>Centro de confianza AI</h2>
          <p>Politicas, riesgos, model cards, incidentes y auditoria para operar IA con control humano.</p>
        </div>
        <div className="trust-mode">
          <span>Acceso</span>
          <StatusBadge value={accessMode} />
          <small>{canWrite ? "Mutaciones habilitadas por feature full" : "Solo lectura/demo hasta habilitar AI Trust full"}</small>
        </div>
      </div>

      <div className="trust-tabs glass-card">
        {tabs.map(([key, label]) => <button key={key} type="button" className={activeTab === key ? "active" : ""} onClick={() => setActiveTab(key)}>{label}</button>)}
      </div>

      {activeTab === "overview" ? (
        <div className="trust-grid">
          <article className="panel glass-card">
            <div className="panel-head"><h2>Controles AI</h2><span>{overview?.phase || "phase_22"}</span></div>
            <div className="metric-grid compact">
              <Metric title="Politicas" value={number(counts.enabled_policies)} hint={`${number(counts.policies)} totales`} />
              <Metric title="Riesgos abiertos" value={number(counts.open_risks)} hint={`${number(counts.high_risks)} altos`} tone={counts.high_risks ? "amber" : "mint"} />
              <Metric title="Incidentes" value={number(counts.open_incidents)} hint="abiertos" tone={counts.open_incidents ? "amber" : "mint"} />
              <Metric title="Model cards" value={number(counts.model_cards)} hint={`${number(signals.registry_models)} modelos registry`} />
            </div>
            <div className="trust-control-list">
              {(overview?.controls || []).map((item) => (
                <div className="trust-control" key={item.key}>
                  <strong>{item.label}</strong>
                  <StatusBadge value={item.status} />
                </div>
              ))}
            </div>
          </article>
          <article className="panel glass-card">
            <div className="panel-head"><h2>Feature gates</h2><span>premium</span></div>
            <div className="trust-feature-grid">
              {["ai_trust_center", "ai_governance_policies", "ai_risk_assessments", "ai_model_cards", "ai_compliance_reports", "ai_audit_exports"].map((key) => (
                <div key={key}><span>{key}</span><FeatureMode item={features[key]} /></div>
              ))}
            </div>
          </article>
          <article className="panel glass-card">
            <div className="panel-head"><h2>Senales gobernadas</h2><span>runtime existente</span></div>
            <div className="trust-signal-list">
              {Object.entries(signals).map(([key, value]) => <div key={key}><span>{key}</span><strong>{number(value)}</strong></div>)}
            </div>
          </article>
          <article className="panel glass-card">
            <div className="panel-head"><h2>Acciones seguras</h2><span>control-plane</span></div>
            <div className="panel-actions">
              <button type="button" onClick={() => runRiskAssessment(false)} disabled={busy === "risk-preview"}>Preview riesgos</button>
              <button type="button" className="primary" onClick={() => runRiskAssessment(true)} disabled={!canWrite || busy === "risk-run"}>Guardar evaluacion</button>
              <button type="button" onClick={generateReport} disabled={!canWrite || busy === "report"}>Generar reporte</button>
            </div>
          </article>
        </div>
      ) : null}

      {activeTab === "policies" ? (
        <div className="trust-grid two">
          <article className="panel glass-card">
            <div className="panel-head"><h2>Politicas activas</h2><span>{number(policies.length)}</span></div>
            <div className="trust-list">
              {policies.map((policy) => (
                <div className="trust-row" key={policy.id}>
                  <div><strong>{policy.name}</strong><small>{policy.policy_key}</small><p>{policy.description}</p></div>
                  <div><StatusBadge value={policy.risk_tier} /><StatusBadge value={policy.enforcement_mode} /></div>
                  <button type="button" onClick={() => attestPolicy(policy.id)} disabled={!canWrite || busy === `attest-${policy.id}`}>Atestar</button>
                </div>
              ))}
            </div>
          </article>
          <article className="panel glass-card">
            <div className="panel-head"><h2>Nueva politica</h2><span>tenant-level</span></div>
            <label>Key<input value={policyForm.policy_key} onChange={(event) => setPolicyForm((prev) => ({ ...prev, policy_key: event.target.value }))} /></label>
            <label>Nombre<input value={policyForm.name} onChange={(event) => setPolicyForm((prev) => ({ ...prev, name: event.target.value }))} /></label>
            <div className="form-grid two">
              <label>Riesgo<select value={policyForm.risk_tier} onChange={(event) => setPolicyForm((prev) => ({ ...prev, risk_tier: event.target.value }))}><option value="low">low</option><option value="medium">medium</option><option value="high">high</option><option value="critical">critical</option></select></label>
              <label>Modo<select value={policyForm.enforcement_mode} onChange={(event) => setPolicyForm((prev) => ({ ...prev, enforcement_mode: event.target.value }))}><option value="monitor">monitor</option><option value="approval_required">approval_required</option><option value="block">block</option></select></label>
            </div>
            <label>Aplica a<input value={Array.isArray(policyForm.applies_to_json) ? policyForm.applies_to_json.join(", ") : policyForm.applies_to_json} onChange={(event) => setPolicyForm((prev) => ({ ...prev, applies_to_json: parseList(event.target.value) }))} /></label>
            <label>Descripcion<textarea rows={3} value={policyForm.description} onChange={(event) => setPolicyForm((prev) => ({ ...prev, description: event.target.value }))} /></label>
            <label>Rules JSON<textarea rows={8} value={policyRulesText} onChange={(event) => setPolicyRulesText(event.target.value)} /></label>
            <div className="panel-actions"><button type="button" className="primary" onClick={savePolicy} disabled={!canWrite || busy === "policy"}>Guardar politica</button></div>
          </article>
        </div>
      ) : null}

      {activeTab === "risks" ? (
        <article className="panel glass-card">
          <div className="panel-head"><h2>Risk assessments</h2><span>{number(risks.length)} registros</span></div>
          <div className="metric-grid compact">
            <Metric title="Critical" value={number(riskGroups.critical)} tone={riskGroups.critical ? "amber" : "mint"} />
            <Metric title="High" value={number(riskGroups.high)} tone={riskGroups.high ? "amber" : "mint"} />
            <Metric title="Medium" value={number(riskGroups.medium)} />
            <Metric title="Low" value={number(riskGroups.low)} />
          </div>
          <div className="panel-actions"><button type="button" className="primary" onClick={() => runRiskAssessment(true)} disabled={!canWrite || busy === "risk-run"}>Recalcular riesgos</button></div>
          <div className="trust-list">
            {risks.map((risk) => (
              <div className="trust-row" key={risk.id}>
                <div><strong>{risk.title}</strong><small>{risk.entity_type} / {risk.entity_id}</small><p>{(risk.findings_json || []).map((item) => item.message || item.key).join(" · ")}</p></div>
                <div><StatusBadge value={risk.risk_level} /><StatusBadge value={risk.status} /><small>Score {number(risk.score)}</small></div>
                <button type="button" onClick={() => closeRisk(risk)} disabled={!canWrite || risk.status !== "open" || busy === `risk-${risk.id}`}>Mitigar</button>
              </div>
            ))}
            {risks.length === 0 ? <p className="empty">Sin evaluaciones de riesgo. Ejecuta un preview o guarda una evaluacion.</p> : null}
          </div>
        </article>
      ) : null}

      {activeTab === "models" ? (
        <div className="trust-grid two">
          <article className="panel glass-card">
            <div className="panel-head"><h2>Model cards</h2><span>{number(modelCards.length)}</span></div>
            <div className="trust-list">
              {modelCards.map((card) => (
                <div className="trust-row" key={card.id}>
                  <div><strong>{card.model_key}</strong><small>{card.task_type || "-"} / {card.version}</small><p>{card.intended_use || "Sin uso previsto documentado."}</p></div>
                  <StatusBadge value={card.status} />
                </div>
              ))}
              {modelCards.length === 0 ? <p className="empty">Aun no hay model cards tenant-level.</p> : null}
            </div>
            <div className="trust-registry">
              <h3>Registry observado</h3>
              {(registryModels || []).slice(0, 8).map((model) => <div key={model.model_key}><span>{model.model_key}</span><small>{model.rollout_mode} / {model.promotion_status}</small></div>)}
            </div>
          </article>
          <article className="panel glass-card">
            <div className="panel-head"><h2>Nueva model card</h2><span>documentacion viva</span></div>
            <label>Model key<input value={modelForm.model_key} onChange={(event) => setModelForm((prev) => ({ ...prev, model_key: event.target.value }))} /></label>
            <div className="form-grid two">
              <label>Task<input value={modelForm.task_type} onChange={(event) => setModelForm((prev) => ({ ...prev, task_type: event.target.value }))} /></label>
              <label>Status<select value={modelForm.status} onChange={(event) => setModelForm((prev) => ({ ...prev, status: event.target.value }))}><option value="draft">draft</option><option value="monitoring">monitoring</option><option value="completed">completed</option></select></label>
            </div>
            <label>Uso previsto<textarea rows={3} value={modelForm.intended_use} onChange={(event) => setModelForm((prev) => ({ ...prev, intended_use: event.target.value }))} /></label>
            <label>Limitaciones<textarea rows={3} value={modelForm.limitations} onChange={(event) => setModelForm((prev) => ({ ...prev, limitations: event.target.value }))} /></label>
            <label>Bloques JSON<textarea rows={10} value={modelJsonText} onChange={(event) => setModelJsonText(event.target.value)} /></label>
            <div className="panel-actions"><button type="button" className="primary" onClick={saveModelCard} disabled={!canWrite || busy === "model-card"}>Guardar model card</button></div>
          </article>
        </div>
      ) : null}

      {activeTab === "incidents" ? (
        <div className="trust-grid two">
          <article className="panel glass-card">
            <div className="panel-head"><h2>Incidentes AI</h2><span>{number(incidents.length)}</span></div>
            <div className="trust-list">
              {incidents.map((incident) => (
                <div className="trust-row" key={incident.id}>
                  <div><strong>{incident.title}</strong><small>{incident.incident_type} / {shortDate(incident.created_at)}</small><p>{incident.description}</p></div>
                  <div><StatusBadge value={incident.severity} /><StatusBadge value={incident.status} /></div>
                  <button type="button" onClick={() => closeIncident(incident)} disabled={!canWrite || incident.status === "closed" || busy === `incident-${incident.id}`}>Cerrar</button>
                </div>
              ))}
              {incidents.length === 0 ? <p className="empty">Sin incidentes abiertos.</p> : null}
            </div>
          </article>
          <article className="panel glass-card">
            <div className="panel-head"><h2>Registrar incidente</h2><span>auditable</span></div>
            <label>Titulo<input value={incidentForm.title} onChange={(event) => setIncidentForm((prev) => ({ ...prev, title: event.target.value }))} /></label>
            <div className="form-grid two">
              <label>Severidad<select value={incidentForm.severity} onChange={(event) => setIncidentForm((prev) => ({ ...prev, severity: event.target.value }))}><option value="low">low</option><option value="medium">medium</option><option value="high">high</option><option value="critical">critical</option></select></label>
              <label>Entidad<input value={incidentForm.entity_type} onChange={(event) => setIncidentForm((prev) => ({ ...prev, entity_type: event.target.value }))} /></label>
            </div>
            <label>Descripcion<textarea rows={4} value={incidentForm.description} onChange={(event) => setIncidentForm((prev) => ({ ...prev, description: event.target.value }))} /></label>
            <label>Remediacion JSON<textarea rows={7} value={incidentJsonText} onChange={(event) => setIncidentJsonText(event.target.value)} /></label>
            <div className="panel-actions"><button type="button" className="primary" onClick={saveIncident} disabled={!canWrite || busy === "incident"}>Registrar</button></div>
          </article>
        </div>
      ) : null}

      {activeTab === "audit" ? (
        <div className="trust-grid two">
          <article className="panel glass-card">
            <div className="panel-head"><h2>Reportes</h2><span>{number(reports.length)}</span></div>
            <div className="panel-actions"><button type="button" className="primary" onClick={generateReport} disabled={!canWrite || busy === "report"}>Generar reporte</button></div>
            <div className="trust-list">
              {reports.map((report) => <div className="trust-row" key={report.id}><div><strong>{report.report_type}</strong><small>{report.period_key} / {shortDate(report.updated_at)}</small><p>{report.summary}</p></div><StatusBadge value={report.status} /></div>)}
            </div>
          </article>
          <article className="panel glass-card">
            <div className="panel-head"><h2>Auditoria AI</h2><span>{number(audits.length)}</span></div>
            <div className="trust-list audit-list">
              {audits.map((audit) => <div className="trust-row" key={audit.id}><div><strong>{audit.event_type}</strong><small>{shortDate(audit.created_at)} / {audit.entity_type || "-"}</small><p>{audit.summary}</p></div><StatusBadge value={audit.severity} /></div>)}
            </div>
          </article>
        </div>
      ) : null}
    </section>
  );
}

function Metric({ title, value, hint = "", tone = "" }) {
  return (
    <div className={`metric-card ${tone}`}>
      <span>{title}</span>
      <strong>{value}</strong>
      {hint ? <small>{hint}</small> : null}
    </div>
  );
}
