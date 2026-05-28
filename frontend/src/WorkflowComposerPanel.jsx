import React, { useEffect, useMemo, useState } from "react";

const tabs = [
  ["designer", "Composer"],
  ["templates", "Plantillas"],
  ["versions", "Versiones"],
  ["governance", "Gobierno"],
];

const nodeTypes = [
  ["event", "Evento"],
  ["condition", "Condicion"],
  ["ai_decision", "Decision IA"],
  ["approval", "Aprobacion"],
  ["action", "Accion"],
  ["delay", "Espera"],
  ["handoff", "Handoff"],
  ["end", "Fin"],
];

const blankGraph = () => ({
  nodes: [
    { id: "event_1", type: "event", label: "Lead or customer event", config: { event_type: "lead.created" } },
    { id: "decision_1", type: "ai_decision", label: "AI evaluates context", config: { uses_predictions: true } },
    { id: "approval_1", type: "approval", label: "Human approval", config: { required: true } },
    { id: "action_1", type: "action", label: "Create follow-up task", config: { action_type: "create_task" } },
    { id: "end_1", type: "end", label: "End", config: {} },
  ],
  edges: [
    { from: "event_1", to: "decision_1" },
    { from: "decision_1", to: "approval_1" },
    { from: "approval_1", to: "action_1" },
    { from: "action_1", to: "end_1" },
  ],
  settings: { requires_preflight: true, requires_approval: true },
});

const blankForm = () => ({
  name: "AI Workflow",
  description: "",
  category: "general",
  channel: "omnichannel",
  graph_json: blankGraph(),
  config_json: {},
});

function jsonText(value, fallback = {}) {
  try {
    return JSON.stringify(value ?? fallback, null, 2);
  } catch {
    return JSON.stringify(fallback, null, 2);
  }
}

function parseJson(value, fallback = {}) {
  try {
    const parsed = JSON.parse(value || "");
    return parsed && typeof parsed === "object" ? parsed : fallback;
  } catch {
    return fallback;
  }
}

function shortDate(value) {
  if (!value) return "-";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value).slice(0, 16);
  return parsed.toLocaleString("es-CO", { dateStyle: "short", timeStyle: "short" });
}

function statusTone(value) {
  const clean = String(value || "").toLowerCase();
  if (["active", "approved", "ready", "full"].includes(clean)) return "ok";
  if (["pending", "draft", "demo", "blocked"].includes(clean)) return "warn";
  return "neutral";
}

function StatusBadge({ value }) {
  return <span className={`status-pill ${statusTone(value)}`}>{value || "-"}</span>;
}

function scoreLabel(score) {
  const value = Number(score || 0);
  if (value >= 85) return "Alto";
  if (value >= 70) return "Listo";
  if (value >= 45) return "Revisar";
  return "Bloqueado";
}

export default function WorkflowComposerPanel({ apiCall, showStatus }) {
  const [activeTab, setActiveTab] = useState("designer");
  const [overview, setOverview] = useState(null);
  const [templates, setTemplates] = useState([]);
  const [workflows, setWorkflows] = useState([]);
  const [selectedId, setSelectedId] = useState("");
  const [detail, setDetail] = useState(null);
  const [versions, setVersions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [form, setForm] = useState(blankForm);
  const [selectedNodeId, setSelectedNodeId] = useState("event_1");
  const [nodeConfigText, setNodeConfigText] = useState("{}");
  const [configText, setConfigText] = useState("{}");
  const [simulationInput, setSimulationInput] = useState('{"event_type":"lead.created","lead_score":82,"channel":"whatsapp"}');
  const [edgeDraft, setEdgeDraft] = useState({ from: "event_1", to: "decision_1" });

  const graph = form.graph_json || blankGraph();
  const nodes = Array.isArray(graph.nodes) ? graph.nodes : [];
  const edges = Array.isArray(graph.edges) ? graph.edges : [];
  const selectedNode = nodes.find((node) => node.id === selectedNodeId) || nodes[0] || null;
  const accessMode = overview?.access?.mode || "disabled";
  const canWrite = accessMode === "full";
  const workflow = detail?.workflow || null;
  const preflight = workflow?.preflight_json || form?.preflight_json || null;
  const simulation = workflow?.simulation_json || null;

  const counts = overview?.counts || {};
  const workflowById = useMemo(() => Object.fromEntries((workflows || []).map((item) => [item.id, item])), [workflows]);

  const loadAll = async (silent = false) => {
    setLoading(true);
    try {
      const [overviewData, templatesData, workflowsData] = await Promise.all([
        apiCall("/saas/v1/workflow-composer/overview").catch(() => null),
        apiCall("/saas/v1/workflow-composer/templates").catch(() => ({ templates: [] })),
        apiCall("/saas/v1/workflow-composer/workflows").catch(() => ({ workflows: [] })),
      ]);
      setOverview(overviewData);
      setTemplates(templatesData?.templates || []);
      const nextWorkflows = workflowsData?.workflows || [];
      setWorkflows(nextWorkflows);
      const nextSelected = selectedId || nextWorkflows[0]?.id || "";
      if (nextSelected) {
        setSelectedId(nextSelected);
        await loadDetail(nextSelected, true);
      }
      if (!silent) showStatus("Workflow Composer actualizado", "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setLoading(false);
    }
  };

  const loadDetail = async (workflowId, silent = false) => {
    if (!workflowId) return;
    try {
      const [detailData, versionsData] = await Promise.all([
        apiCall(`/saas/v1/workflow-composer/workflows/${encodeURIComponent(workflowId)}`),
        apiCall(`/saas/v1/workflow-composer/workflows/${encodeURIComponent(workflowId)}/versions`).catch(() => ({ versions: [] })),
      ]);
      const item = detailData?.workflow || workflowById[workflowId] || null;
      setDetail(detailData);
      setVersions(versionsData?.versions || []);
      if (item) {
        setForm({
          name: item.name || "",
          description: item.description || "",
          category: item.category || "general",
          channel: item.channel || "omnichannel",
          graph_json: item.graph_json || blankGraph(),
          config_json: item.config_json || {},
        });
        setConfigText(jsonText(item.config_json || {}));
        const firstNode = (item.graph_json?.nodes || [])[0];
        setSelectedNodeId(firstNode?.id || "");
        setNodeConfigText(jsonText(firstNode?.config || {}));
      }
      if (!silent) showStatus("Workflow cargado", "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    }
  };

  useEffect(() => { loadAll(true); }, []);

  useEffect(() => {
    if (!selectedNode) return;
    setNodeConfigText(jsonText(selectedNode.config || {}));
  }, [selectedNodeId]);

  const runAction = async (key, fn, okMessage, after = true) => {
    setBusy(key);
    try {
      const data = await fn();
      showStatus(okMessage, "ok");
      if (data?.workflow?.id) {
        setSelectedId(data.workflow.id);
        await loadDetail(data.workflow.id, true);
      }
      if (after) await loadAll(true);
      return data;
    } catch (err) {
      showStatus(String(err.message || err), "error");
      return null;
    } finally {
      setBusy("");
    }
  };

  const updateGraph = (nextGraph) => setForm((current) => ({ ...current, graph_json: nextGraph }));

  const upsertNode = (patch) => {
    if (!selectedNode) return;
    const nextNodes = nodes.map((node) => (node.id === selectedNode.id ? { ...node, ...patch } : node));
    updateGraph({ ...graph, nodes: nextNodes });
  };

  const addNode = () => {
    const nextIndex = nodes.length + 1;
    const newNode = { id: `node_${nextIndex}`, type: "action", label: `New action ${nextIndex}`, config: { action_type: "create_task" } };
    updateGraph({ ...graph, nodes: [...nodes, newNode] });
    setSelectedNodeId(newNode.id);
    setNodeConfigText(jsonText(newNode.config));
  };

  const removeNode = (nodeId) => {
    const nextNodes = nodes.filter((node) => node.id !== nodeId);
    const nextEdges = edges.filter((edge) => edge.from !== nodeId && edge.to !== nodeId);
    updateGraph({ ...graph, nodes: nextNodes, edges: nextEdges });
    setSelectedNodeId(nextNodes[0]?.id || "");
  };

  const addEdge = () => {
    if (!edgeDraft.from || !edgeDraft.to || edgeDraft.from === edgeDraft.to) return;
    const exists = edges.some((edge) => edge.from === edgeDraft.from && edge.to === edgeDraft.to);
    if (exists) return;
    updateGraph({ ...graph, edges: [...edges, edgeDraft] });
  };

  const removeEdge = (index) => {
    updateGraph({ ...graph, edges: edges.filter((_, itemIndex) => itemIndex !== index) });
  };

  const applyNodeConfig = () => {
    upsertNode({ config: parseJson(nodeConfigText, {}) });
    showStatus("Configuracion de nodo aplicada", "ok");
  };

  const saveWorkflow = () => {
    const payload = {
      ...form,
      config_json: parseJson(configText, {}),
      graph_json: form.graph_json || blankGraph(),
    };
    if (selectedId) {
      return runAction("save", () => apiCall(`/saas/v1/workflow-composer/workflows/${encodeURIComponent(selectedId)}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      }), "Workflow guardado");
    }
    return runAction("create", () => apiCall("/saas/v1/workflow-composer/workflows", {
      method: "POST",
      body: JSON.stringify(payload),
    }), "Workflow creado");
  };

  const instantiate = (item) => runAction(
    `template-${item.template_key}`,
    () => apiCall(`/saas/v1/workflow-composer/templates/${encodeURIComponent(item.template_key)}/instantiate`, {
      method: "POST",
      body: JSON.stringify({ name: item.name, config_json: { source: "workflow_composer_panel" } }),
    }),
    "Plantilla convertida en workflow",
  );

  const runPreflight = () => selectedId && runAction(
    "preflight",
    () => apiCall(`/saas/v1/workflow-composer/workflows/${encodeURIComponent(selectedId)}/preflight`, { method: "POST" }),
    "Preflight ejecutado",
  );

  const runSimulation = () => selectedId && runAction(
    "simulate",
    () => apiCall(`/saas/v1/workflow-composer/workflows/${encodeURIComponent(selectedId)}/simulate`, {
      method: "POST",
      body: JSON.stringify({ scenario_key: "manual", input_json: parseJson(simulationInput, {}) }),
    }),
    "Simulacion completada",
  );

  const requestApproval = () => selectedId && runAction(
    "request-approval",
    () => apiCall(`/saas/v1/workflow-composer/workflows/${encodeURIComponent(selectedId)}/approval/request`, {
      method: "POST",
      body: JSON.stringify({ note: "Solicitud desde Workflow Composer" }),
    }),
    "Aprobacion solicitada",
  );

  const reviewApproval = (status) => selectedId && runAction(
    `review-${status}`,
    () => apiCall(`/saas/v1/workflow-composer/workflows/${encodeURIComponent(selectedId)}/approval/review`, {
      method: "POST",
      body: JSON.stringify({ status, note: `Revision ${status}` }),
    }),
    status === "approved" ? "Workflow aprobado" : "Workflow rechazado",
  );

  const activate = () => selectedId && runAction(
    "activate",
    () => apiCall(`/saas/v1/workflow-composer/workflows/${encodeURIComponent(selectedId)}/activate`, { method: "POST" }),
    "Workflow activado en Composer",
  );

  const restoreVersion = (versionId) => selectedId && runAction(
    `restore-${versionId}`,
    () => apiCall(`/saas/v1/workflow-composer/workflows/${encodeURIComponent(selectedId)}/versions/${encodeURIComponent(versionId)}/restore`, {
      method: "POST",
      body: JSON.stringify({ note: "Rollback desde UI" }),
    }),
    "Version restaurada como borrador",
  );

  const newWorkflow = () => {
    const next = blankForm();
    setSelectedId("");
    setDetail(null);
    setVersions([]);
    setForm(next);
    setConfigText("{}");
    setSelectedNodeId(next.graph_json.nodes[0].id);
    setNodeConfigText(jsonText(next.graph_json.nodes[0].config));
  };

  if (loading) {
    return (
      <section className="module-page workflow-page">
        <div className="panel glass-card"><p>Cargando Workflow Composer...</p></div>
      </section>
    );
  }

  return (
    <section className="module-page workflow-page">
      <div className="hero-card compact-hero workflow-hero">
        <div>
          <p className="eyebrow">Fase 18</p>
          <h2>AI Workflow Composer</h2>
          <p>Disena, simula, aprueba y versiona workflows AI con ejecucion controlada y sin efectos externos durante pruebas.</p>
        </div>
        <div className="workflow-kpis">
          <div><strong>{counts.total_workflows || 0}</strong><span>Workflows</span></div>
          <div><strong>{counts.active_workflows || 0}</strong><span>Activos</span></div>
          <div><strong>{counts.pending_approvals || 0}</strong><span>Aprobaciones</span></div>
          <div><strong>{overview?.template_count || 0}</strong><span>Plantillas</span></div>
        </div>
      </div>

      <div className="settings-tabs compact-tabs">
        {tabs.map(([key, label]) => <button key={key} className={activeTab === key ? "active" : ""} onClick={() => setActiveTab(key)}>{label}</button>)}
        <span className="flex-spacer" />
        <StatusBadge value={accessMode} />
        <button className="ghost-button small" onClick={() => loadAll(false)} disabled={Boolean(busy)}>Actualizar</button>
      </div>

      {!canWrite && (
        <div className="panel glass-card warning-panel">
          <strong>Modo demo o feature desactivada.</strong>
          <span> Puedes ver plantillas y el estado del sistema, pero crear, aprobar o activar workflows requiere `ai_workflow_composer` en el plan o tenant.</span>
        </div>
      )}

      {activeTab === "templates" && (
        <div className="workflow-template-grid">
          {templates.map((item) => (
            <article className="panel glass-card workflow-template-card" key={item.template_key}>
              <div className="row-between">
                <div>
                  <p className="eyebrow">{item.category} / {item.industry_code}</p>
                  <h3>{item.name}</h3>
                </div>
                <StatusBadge value={item.status} />
              </div>
              <p>{item.description}</p>
              <div className="chip-row">
                {(item.tags_json || []).map((tag) => <span className="chip" key={tag}>{tag}</span>)}
              </div>
              <button className="primary-button" disabled={!canWrite || Boolean(busy)} onClick={() => instantiate(item)}>Usar plantilla</button>
            </article>
          ))}
        </div>
      )}

      {activeTab === "designer" && (
        <div className="workflow-layout">
          <aside className="panel glass-card workflow-sidebar">
            <div className="row-between">
              <h3>Workflows</h3>
              <button className="ghost-button small" onClick={newWorkflow}>Nuevo</button>
            </div>
            <div className="workflow-list">
              {workflows.map((item) => (
                <button
                  key={item.id}
                  className={selectedId === item.id ? "workflow-list-item active" : "workflow-list-item"}
                  onClick={() => { setSelectedId(item.id); loadDetail(item.id); }}
                >
                  <span>{item.name}</span>
                  <small>{item.status} / v{item.version_number}</small>
                </button>
              ))}
              {!workflows.length && <p className="muted">Aun no hay workflows creados.</p>}
            </div>
          </aside>

          <div className="panel glass-card workflow-editor">
            <div className="workflow-form-grid">
              <label>
                Nombre
                <input value={form.name} onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))} />
              </label>
              <label>
                Categoria
                <input value={form.category} onChange={(event) => setForm((current) => ({ ...current, category: event.target.value }))} />
              </label>
              <label>
                Canal
                <input value={form.channel} onChange={(event) => setForm((current) => ({ ...current, channel: event.target.value }))} />
              </label>
            </div>
            <label>
              Descripcion
              <textarea rows={2} value={form.description} onChange={(event) => setForm((current) => ({ ...current, description: event.target.value }))} />
            </label>

            <div className="workflow-canvas">
              {nodes.map((node, index) => (
                <button
                  key={node.id}
                  className={selectedNodeId === node.id ? "workflow-node selected" : "workflow-node"}
                  onClick={() => setSelectedNodeId(node.id)}
                >
                  <span className="workflow-node-index">{index + 1}</span>
                  <strong>{node.label}</strong>
                  <small>{node.type}</small>
                </button>
              ))}
            </div>

            <div className="workflow-actions-row">
              <button className="ghost-button small" onClick={addNode}>Agregar nodo</button>
              <button className="primary-button" onClick={saveWorkflow} disabled={!canWrite || Boolean(busy)}>{selectedId ? "Guardar" : "Crear workflow"}</button>
              <button className="ghost-button" onClick={runPreflight} disabled={!selectedId || !canWrite || Boolean(busy)}>Preflight</button>
              <button className="ghost-button" onClick={runSimulation} disabled={!selectedId || !canWrite || Boolean(busy)}>Simular</button>
            </div>

            <div className="workflow-designer-grid">
              <div className="workflow-node-editor">
                <h4>Nodo seleccionado</h4>
                {selectedNode ? (
                  <>
                    <label>
                      Label
                      <input value={selectedNode.label || ""} onChange={(event) => upsertNode({ label: event.target.value })} />
                    </label>
                    <label>
                      Tipo
                      <select value={selectedNode.type || "action"} onChange={(event) => upsertNode({ type: event.target.value })}>
                        {nodeTypes.map(([key, label]) => <option key={key} value={key}>{label}</option>)}
                      </select>
                    </label>
                    <label>
                      Config JSON
                      <textarea rows={7} value={nodeConfigText} onChange={(event) => setNodeConfigText(event.target.value)} />
                    </label>
                    <div className="workflow-actions-row">
                      <button className="ghost-button small" onClick={applyNodeConfig}>Aplicar config</button>
                      <button className="danger-button small" onClick={() => removeNode(selectedNode.id)}>Eliminar nodo</button>
                    </div>
                  </>
                ) : <p className="muted">Selecciona o crea un nodo.</p>}
              </div>

              <div className="workflow-node-editor">
                <h4>Edges y configuracion</h4>
                <div className="workflow-edge-form">
                  <select value={edgeDraft.from} onChange={(event) => setEdgeDraft((current) => ({ ...current, from: event.target.value }))}>
                    {nodes.map((node) => <option key={node.id} value={node.id}>{node.id}</option>)}
                  </select>
                  <span>-&gt;</span>
                  <select value={edgeDraft.to} onChange={(event) => setEdgeDraft((current) => ({ ...current, to: event.target.value }))}>
                    {nodes.map((node) => <option key={node.id} value={node.id}>{node.id}</option>)}
                  </select>
                  <button className="ghost-button small" onClick={addEdge}>Conectar</button>
                </div>
                <div className="workflow-edge-list">
                  {edges.map((edge, index) => (
                    <div key={`${edge.from}-${edge.to}-${index}`}>
                      <span>{edge.from} -&gt; {edge.to}</span>
                      <button className="icon-button" onClick={() => removeEdge(index)} title="Eliminar edge">x</button>
                    </div>
                  ))}
                </div>
                <label>
                  Config workflow JSON
                  <textarea rows={7} value={configText} onChange={(event) => setConfigText(event.target.value)} />
                </label>
              </div>
            </div>
          </div>

          <aside className="panel glass-card workflow-inspector">
            <h3>Inspector</h3>
            <div className="mini-metrics">
              <div><span>Estado</span><strong>{workflow?.status || "nuevo"}</strong></div>
              <div><span>Aprobacion</span><strong>{workflow?.approval_status || "draft"}</strong></div>
              <div><span>Preflight</span><strong>{scoreLabel(preflight?.score)}</strong></div>
              <div><span>Version</span><strong>v{workflow?.version_number || 1}</strong></div>
            </div>

            <h4>Preflight</h4>
            <div className="workflow-check-list">
              {(preflight?.checks || []).map((check) => (
                <div key={check.key} className={check.ok ? "ok" : check.severity}>
                  <strong>{check.ok ? "OK" : check.severity}</strong>
                  <span>{check.message}</span>
                </div>
              ))}
              {!preflight?.checks?.length && <p className="muted">Guarda y ejecuta preflight para validar.</p>}
            </div>

            <h4>Simulacion</h4>
            <textarea rows={4} value={simulationInput} onChange={(event) => setSimulationInput(event.target.value)} />
            {simulation && (
              <div className="workflow-simulation-box">
                <p><strong>Nodos visitados:</strong> {(simulation.visited_nodes || []).join(" -> ") || "-"}</p>
                <p><strong>Acciones planeadas:</strong> {(simulation.actions_planned || []).length}</p>
                <p><strong>Efectos ejecutados:</strong> {simulation.side_effects_executed ? "si" : "no"}</p>
              </div>
            )}
          </aside>
        </div>
      )}

      {activeTab === "versions" && (
        <div className="panel glass-card">
          <div className="row-between">
            <h3>Versiones</h3>
            <StatusBadge value={workflow?.approval_status || "draft"} />
          </div>
          <table className="mini-table">
            <thead><tr><th>Version</th><th>Motivo</th><th>Fecha</th><th /></tr></thead>
            <tbody>
              {versions.map((item) => (
                <tr key={item.id}>
                  <td>v{item.version_number}</td>
                  <td>{item.change_reason || "-"}</td>
                  <td>{shortDate(item.created_at)}</td>
                  <td><button className="ghost-button small" disabled={!canWrite || Boolean(busy)} onClick={() => restoreVersion(item.id)}>Restaurar</button></td>
                </tr>
              ))}
              {!versions.length && <tr><td colSpan={4}>Selecciona un workflow para ver versiones.</td></tr>}
            </tbody>
          </table>
        </div>
      )}

      {activeTab === "governance" && (
        <div className="workflow-governance-grid">
          <div className="panel glass-card">
            <h3>Aprobacion y activacion</h3>
            <p className="muted">La activacion es control-plane: no dispara WhatsApp, Instagram, triggers ni campanas automaticamente.</p>
            <div className="workflow-actions-row">
              <button className="ghost-button" disabled={!selectedId || !canWrite || Boolean(busy)} onClick={requestApproval}>Solicitar aprobacion</button>
              <button className="primary-button" disabled={!selectedId || !canWrite || Boolean(busy)} onClick={() => reviewApproval("approved")}>Aprobar</button>
              <button className="danger-button" disabled={!selectedId || !canWrite || Boolean(busy)} onClick={() => reviewApproval("rejected")}>Rechazar</button>
              <button className="primary-button" disabled={!selectedId || !canWrite || Boolean(busy)} onClick={activate}>Activar</button>
            </div>
          </div>
          <div className="panel glass-card">
            <h3>Historial de aprobaciones</h3>
            <table className="mini-table">
              <thead><tr><th>Estado</th><th>Riesgo</th><th>Fecha</th></tr></thead>
              <tbody>
                {(detail?.approvals || []).map((item) => (
                  <tr key={item.id}>
                    <td><StatusBadge value={item.status} /></td>
                    <td>{item.risk_level}</td>
                    <td>{shortDate(item.created_at)}</td>
                  </tr>
                ))}
                {!detail?.approvals?.length && <tr><td colSpan={3}>Sin aprobaciones.</td></tr>}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  );
}
