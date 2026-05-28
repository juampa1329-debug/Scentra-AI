import React, { useEffect, useMemo, useState } from "react";

const tabs = [
  ["marketplace", "Marketplace IA"],
  ["plugins", "Centro de plugins"],
  ["tools", "Registro de herramientas"],
  ["events", "Suscripciones a eventos"],
  ["developer", "Consola de desarrollo"],
  ["integrations", "Integraciones"],
  ["apps", "Apps IA"],
];

const blankPlugin = () => ({
  plugin_key: "custom.crm_plugin",
  name: "Custom CRM Plugin",
  category: "crm",
  status: "draft",
  description: "",
  permissions_json: ["crm:read"],
  manifest_json: { runtime: "metadata_only" },
  config_json: {},
});

const blankTool = () => ({
  tool_key: "tenant.custom_tool",
  name: "Custom Tool",
  category: "ai",
  description: "",
  status: "enabled",
  risk_level: "medium",
  runtime_type: "manifest",
  handler_ref: "tenant.manifest.custom_tool",
  input_schema_json: { type: "object" },
  output_schema_json: { type: "object" },
  permission_scopes_json: ["approval:required"],
  metadata_json: {},
});

const blankSubscription = () => ({
  subscriber_type: "plugin",
  subscriber_id: "custom.crm_plugin",
  event_type: "lead.created",
  target_type: "internal",
  target_ref: "custom.crm_plugin",
  status: "enabled",
  priority: 50,
  filters_json: {},
  retry_policy_json: { max_attempts: 3 },
});

const blankDeveloperApp = () => ({
  app_key: "tenant.ai_app",
  name: "Tenant AI App",
  description: "",
  status: "active",
  scopes_json: ["apps:read", "analytics:read"],
  webhook_url: "",
});

const blankIntegration = () => ({
  integration_key: "external.crm",
  provider_type: "crm",
  provider_name: "External CRM",
  status: "draft",
  auth_mode: "none",
  scopes_json: ["crm:read"],
  config_json: {},
});

const blankAiApp = () => ({
  app_key: "ops.dashboard",
  name: "Panel de operaciones",
  app_type: "dashboard",
  description: "",
  status: "draft",
  manifest_json: { panels: ["insights", "actions"] },
  permissions_json: ["analytics:read"],
  layout_json: {},
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

function modeLabel(mode) {
  const clean = String(mode || "disabled").toLowerCase();
  if (clean === "full") return "Full";
  if (clean === "demo") return "Demo";
  return "Off";
}

function parseList(value) {
  return String(value || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function compactJson(value) {
  try {
    return JSON.stringify(value || {}, null, 2);
  } catch {
    return "{}";
  }
}

function StatusBadge({ value }) {
  const clean = String(value || "off").toLowerCase();
  const tone = clean.includes("full") || clean.includes("enabled") || clean.includes("active") ? "ok" : clean.includes("demo") || clean.includes("draft") ? "warn" : "neutral";
  return <span className={`status-pill ${tone}`}>{value || "off"}</span>;
}

export default function AiEcosystemPanel({ apiCall, showStatus }) {
  const [activeTab, setActiveTab] = useState("marketplace");
  const [overview, setOverview] = useState(null);
  const [marketplace, setMarketplace] = useState([]);
  const [installations, setInstallations] = useState([]);
  const [plugins, setPlugins] = useState([]);
  const [tools, setTools] = useState([]);
  const [subscriptions, setSubscriptions] = useState([]);
  const [developerApps, setDeveloperApps] = useState([]);
  const [integrations, setIntegrations] = useState([]);
  const [aiApps, setAiApps] = useState([]);
  const [sdk, setSdk] = useState(null);
  const [metrics, setMetrics] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [lastKey, setLastKey] = useState("");
  const [pluginForm, setPluginForm] = useState(blankPlugin);
  const [toolForm, setToolForm] = useState(blankTool);
  const [subscriptionForm, setSubscriptionForm] = useState(blankSubscription);
  const [developerForm, setDeveloperForm] = useState(blankDeveloperApp);
  const [integrationForm, setIntegrationForm] = useState(blankIntegration);
  const [aiAppForm, setAiAppForm] = useState(blankAiApp);

  const accessFeatures = overview?.access?.features || {};
  const counts = metrics?.counts || overview?.metrics || {};
  const canInstall = Object.values(accessFeatures).some((item) => item.mode === "full");
  const installedByItem = useMemo(() => Object.fromEntries((installations || []).map((item) => [item.item_id, item])), [installations]);

  const loadAll = async (silent = false) => {
    setLoading(true);
    try {
      const [overviewData, marketplaceData, installationsData, pluginsData, toolsData, subscriptionsData, developerData, integrationsData, appsData, sdkData, metricsData] = await Promise.all([
        apiCall("/saas/v1/ecosystem/overview").catch(() => ({ overview: null })),
        apiCall("/saas/v1/ecosystem/marketplace").catch(() => ({ items: [] })),
        apiCall("/saas/v1/ecosystem/installations").catch(() => ({ installations: [] })),
        apiCall("/saas/v1/ecosystem/plugins").catch(() => ({ plugins: [] })),
        apiCall("/saas/v1/ecosystem/tools").catch(() => ({ tools: [] })),
        apiCall("/saas/v1/ecosystem/event-subscriptions").catch(() => ({ subscriptions: [] })),
        apiCall("/saas/v1/ecosystem/developer/apps").catch(() => ({ apps: [] })),
        apiCall("/saas/v1/ecosystem/external-integrations").catch(() => ({ integrations: [] })),
        apiCall("/saas/v1/ecosystem/ai-apps").catch(() => ({ apps: [] })),
        apiCall("/saas/v1/ecosystem/sdk/manifest").catch(() => ({ manifest: null })),
        apiCall("/saas/v1/ecosystem/metrics").catch(() => ({ metrics: null })),
      ]);
      setOverview(overviewData?.overview || null);
      setMarketplace(marketplaceData?.items || []);
      setInstallations(installationsData?.installations || []);
      setPlugins(pluginsData?.plugins || []);
      setTools(toolsData?.tools || []);
      setSubscriptions(subscriptionsData?.subscriptions || []);
      setDeveloperApps(developerData?.apps || []);
      setIntegrations(integrationsData?.integrations || []);
      setAiApps(appsData?.apps || []);
      setSdk(sdkData?.manifest || null);
      setMetrics(metricsData?.metrics || null);
      if (!silent) showStatus("Ecosistema IA actualizado", "ok");
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
      const data = await fn();
      if (data?.app?.api_key_once) setLastKey(data.app.api_key_once);
      showStatus(okMessage, "ok");
      await loadAll(true);
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setBusy("");
    }
  };

  const installItem = (item, createResources = false) => runAction(
    `install-${item.id}-${createResources ? "resources" : "metadata"}`,
    () => apiCall(`/saas/v1/ecosystem/marketplace/${encodeURIComponent(item.id)}/install`, {
      method: "POST",
      body: JSON.stringify({ enable: true, create_resources: createResources, config_json: { source: "tenant_ai_ecosystem_panel" } }),
    }),
    createResources ? "Item instalado y recurso creado" : "Item instalado",
  );

  const toggleInstallation = (item) => {
    const nextStatus = String(item.status || "").toLowerCase() === "enabled" ? "disabled" : "enabled";
    return runAction(
      `installation-${item.id}`,
      () => apiCall(`/saas/v1/ecosystem/installations/${encodeURIComponent(item.id)}`, {
        method: "PATCH",
        body: JSON.stringify({ status: nextStatus, config_json: {} }),
      }),
      `Instalacion ${nextStatus}`,
    );
  };

  const createPlugin = () => runAction("plugin", () => apiCall("/saas/v1/ecosystem/plugins", {
    method: "POST",
    body: JSON.stringify(pluginForm),
  }), "Plugin guardado");

  const createTool = () => runAction("tool", () => apiCall("/saas/v1/ecosystem/tools", {
    method: "POST",
    body: JSON.stringify(toolForm),
  }), "Tool registrado");

  const createSubscription = () => runAction("subscription", () => apiCall("/saas/v1/ecosystem/event-subscriptions", {
    method: "POST",
    body: JSON.stringify(subscriptionForm),
  }), "Suscripcion registrada");

  const createDeveloperApp = () => runAction("developer", () => apiCall("/saas/v1/ecosystem/developer/apps", {
    method: "POST",
    body: JSON.stringify(developerForm),
  }), "Developer app creada");

  const rotateDeveloperKey = (app) => runAction(`rotate-${app.id}`, () => apiCall(`/saas/v1/ecosystem/developer/apps/${encodeURIComponent(app.id)}/rotate-key`, {
    method: "POST",
    body: JSON.stringify({}),
  }), "API key rotada");

  const createIntegration = () => runAction("integration", () => apiCall("/saas/v1/ecosystem/external-integrations", {
    method: "POST",
    body: JSON.stringify(integrationForm),
  }), "Integracion registrada");

  const createAiApp = () => runAction("aiapp", () => apiCall("/saas/v1/ecosystem/ai-apps", {
    method: "POST",
    body: JSON.stringify(aiAppForm),
  }), "AI app guardada");

  return (
    <section className="panel glass-card">
      <div className="panel-head">
        <div>
          <h2>AI Platform Ecosystem</h2>
          <span>Marketplace, plugins, SDK, tools, apps e integraciones AI gobernadas por tenant.</span>
        </div>
        <button type="button" onClick={() => loadAll()} disabled={loading}>{loading ? "Actualizando..." : "Actualizar"}</button>
      </div>

      <div className="stats-grid">
        {Object.entries({
          marketplace_items: "Items",
          installations: "Instalados",
          plugins: "Plugins",
          tools: "Tools",
          active_subscriptions: "Eventos",
          developer_apps: "Dev Apps",
          external_integrations: "Integraciones",
          ai_apps: "AI Apps",
        }).map(([key, label]) => (
          <article className="stat-card" key={key}>
            <span>{label}</span>
            <strong>{number(counts[key])}</strong>
          </article>
        ))}
      </div>

      <div className="settings-tabs glass-card">
        {tabs.map(([key, label]) => <button key={key} type="button" className={activeTab === key ? "active" : ""} onClick={() => setActiveTab(key)}>{label}</button>)}
      </div>

      <div className="ai-context-card">
        <div className="ai-context-head">
          <strong>Premium gating</strong>
          <span>{canInstall ? "Full disponible" : "Demo / bloqueado"}</span>
        </div>
        <div className="ai-facts">
          {Object.entries(accessFeatures).map(([key, value]) => (
            <span key={key}><b>{key}</b>{modeLabel(value?.mode)}</span>
          ))}
        </div>
      </div>

      {activeTab === "marketplace" ? (
        <div className="panel-grid">
          {marketplace.map((item) => {
            const installation = installedByItem[item.id] || {};
            return (
              <article className="ai-context-card" key={item.id}>
                <div className="ai-context-head">
                  <strong>{item.name}</strong>
                  <StatusBadge value={installation.status || item.access?.mode || "available"} />
                </div>
                <p>{item.description}</p>
                <div className="ai-facts">
                  <span><b>Tipo</b>{item.item_type}</span>
                  <span><b>Categoria</b>{item.category}</span>
                  <span><b>Feature</b>{item.required_feature_key}</span>
                  <span><b>Version</b>{item.version}</span>
                </div>
                <div className="panel-actions">
                  <button type="button" onClick={() => installItem(item, false)} disabled={busy || item.access?.mode !== "full"}>
                    {busy === `install-${item.id}-metadata` ? "Instalando..." : "Instalar"}
                  </button>
                  {item.item_type === "agent_template" ? (
                    <button type="button" className="primary" onClick={() => installItem(item, true)} disabled={busy || item.access?.mode !== "full"}>
                      Crear agente
                    </button>
                  ) : null}
                </div>
              </article>
            );
          })}
          {marketplace.length === 0 ? <p className="muted-note">Sin items publicados.</p> : null}
        </div>
      ) : null}

      {activeTab === "plugins" ? (
        <div className="form-grid two">
          <article className="ai-context-card">
            <div className="ai-context-head"><strong>Nuevo plugin</strong><StatusBadge value="metadata_only" /></div>
            <label>Key<input value={pluginForm.plugin_key} onChange={(event) => setPluginForm((prev) => ({ ...prev, plugin_key: event.target.value }))} /></label>
            <label>Nombre<input value={pluginForm.name} onChange={(event) => setPluginForm((prev) => ({ ...prev, name: event.target.value }))} /></label>
            <label>Categoria<input value={pluginForm.category} onChange={(event) => setPluginForm((prev) => ({ ...prev, category: event.target.value }))} /></label>
            <label>Scopes CSV<input value={(pluginForm.permissions_json || []).join(", ")} onChange={(event) => setPluginForm((prev) => ({ ...prev, permissions_json: parseList(event.target.value) }))} /></label>
            <label>Descripcion<textarea rows={3} value={pluginForm.description} onChange={(event) => setPluginForm((prev) => ({ ...prev, description: event.target.value }))} /></label>
            <button type="button" className="primary" onClick={createPlugin} disabled={busy === "plugin"}>{busy === "plugin" ? "Guardando..." : "Guardar plugin"}</button>
          </article>
          <article className="ai-context-card">
            <div className="ai-context-head"><strong>Plugins tenant</strong><span>{plugins.length}</span></div>
            {plugins.map((item) => (
              <div className="timeline-event" key={item.id}>
                <strong>{item.name}</strong>
                <span>{item.plugin_key} · {item.category}</span>
                <small>{item.status} · {item.sandbox_mode} · {shortDate(item.updated_at)}</small>
              </div>
            ))}
          </article>
        </div>
      ) : null}

      {activeTab === "tools" ? (
        <div className="form-grid two">
          <article className="ai-context-card">
            <div className="ai-context-head"><strong>Registrar tool tenant</strong><StatusBadge value={toolForm.risk_level} /></div>
            <label>Key<input value={toolForm.tool_key} onChange={(event) => setToolForm((prev) => ({ ...prev, tool_key: event.target.value }))} /></label>
            <label>Nombre<input value={toolForm.name} onChange={(event) => setToolForm((prev) => ({ ...prev, name: event.target.value }))} /></label>
            <label>Categoria<input value={toolForm.category} onChange={(event) => setToolForm((prev) => ({ ...prev, category: event.target.value }))} /></label>
            <label>Riesgo<select value={toolForm.risk_level} onChange={(event) => setToolForm((prev) => ({ ...prev, risk_level: event.target.value }))}><option>low</option><option>medium</option><option>high</option></select></label>
            <label>Handler ref<input value={toolForm.handler_ref} onChange={(event) => setToolForm((prev) => ({ ...prev, handler_ref: event.target.value }))} /></label>
            <button type="button" className="primary" onClick={createTool} disabled={busy === "tool"}>{busy === "tool" ? "Registrando..." : "Registrar tool"}</button>
          </article>
          <article className="ai-context-card">
            <div className="ai-context-head"><strong>Registry</strong><span>{tools.length}</span></div>
            {tools.slice(0, 20).map((item) => (
              <div className="timeline-event" key={item.id}>
                <strong>{item.name}</strong>
                <span>{item.tool_key} · {item.category}</span>
                <small>{item.tenant_id ? "tenant" : "system"} · {item.risk_level} · {item.status}</small>
              </div>
            ))}
          </article>
        </div>
      ) : null}

      {activeTab === "events" ? (
        <div className="form-grid two">
          <article className="ai-context-card">
            <div className="ai-context-head"><strong>Nueva suscripcion</strong><StatusBadge value={subscriptionForm.status} /></div>
            <label>Subscriber<input value={subscriptionForm.subscriber_id} onChange={(event) => setSubscriptionForm((prev) => ({ ...prev, subscriber_id: event.target.value }))} /></label>
            <label>Evento<input value={subscriptionForm.event_type} onChange={(event) => setSubscriptionForm((prev) => ({ ...prev, event_type: event.target.value }))} /></label>
            <label>Target<input value={subscriptionForm.target_ref} onChange={(event) => setSubscriptionForm((prev) => ({ ...prev, target_ref: event.target.value }))} /></label>
            <label>Prioridad<input type="number" value={subscriptionForm.priority} onChange={(event) => setSubscriptionForm((prev) => ({ ...prev, priority: Number(event.target.value || 0) }))} /></label>
            <button type="button" className="primary" onClick={createSubscription} disabled={busy === "subscription"}>{busy === "subscription" ? "Guardando..." : "Crear suscripcion"}</button>
          </article>
          <article className="ai-context-card">
            <div className="ai-context-head"><strong>Suscripciones</strong><span>{subscriptions.length}</span></div>
            {subscriptions.map((item) => (
              <div className="timeline-event" key={item.id}>
                <strong>{item.event_type}</strong>
                <span>{item.subscriber_type}:{item.subscriber_id}</span>
                <small>{item.status} · prioridad {item.priority} · {item.target_ref || "internal"}</small>
              </div>
            ))}
          </article>
        </div>
      ) : null}

      {activeTab === "developer" ? (
        <div className="form-grid two">
          <article className="ai-context-card">
            <div className="ai-context-head"><strong>Developer app</strong><StatusBadge value={developerForm.status} /></div>
            <label>Key<input value={developerForm.app_key} onChange={(event) => setDeveloperForm((prev) => ({ ...prev, app_key: event.target.value }))} /></label>
            <label>Nombre<input value={developerForm.name} onChange={(event) => setDeveloperForm((prev) => ({ ...prev, name: event.target.value }))} /></label>
            <label>Scopes CSV<input value={(developerForm.scopes_json || []).join(", ")} onChange={(event) => setDeveloperForm((prev) => ({ ...prev, scopes_json: parseList(event.target.value) }))} /></label>
            <label>Webhook URL<input value={developerForm.webhook_url} onChange={(event) => setDeveloperForm((prev) => ({ ...prev, webhook_url: event.target.value }))} /></label>
            <button type="button" className="primary" onClick={createDeveloperApp} disabled={busy === "developer"}>{busy === "developer" ? "Creando..." : "Crear app"}</button>
            {lastKey ? <p className="soft-copy">API key one-time: <code>{lastKey}</code></p> : null}
          </article>
          <article className="ai-context-card">
            <div className="ai-context-head"><strong>SDK manifest</strong><StatusBadge value={sdk?.mode} /></div>
            <pre className="code-block">{compactJson({ version: sdk?.version, scopes: sdk?.scopes, event_types: sdk?.event_types, endpoints: sdk?.endpoints })}</pre>
            <div className="ai-context-head"><strong>Apps</strong><span>{developerApps.length}</span></div>
            {developerApps.map((item) => (
              <div className="timeline-event" key={item.id}>
                <strong>{item.name}</strong>
                <span>{item.app_key} · {item.api_key_hint}</span>
                <small>{item.status} · {shortDate(item.updated_at)}</small>
                <button type="button" onClick={() => rotateDeveloperKey(item)} disabled={Boolean(busy)}>Rotar key</button>
              </div>
            ))}
          </article>
        </div>
      ) : null}

      {activeTab === "integrations" ? (
        <div className="form-grid two">
          <article className="ai-context-card">
            <div className="ai-context-head"><strong>Nueva integracion externa</strong><StatusBadge value={integrationForm.status} /></div>
            <label>Key<input value={integrationForm.integration_key} onChange={(event) => setIntegrationForm((prev) => ({ ...prev, integration_key: event.target.value }))} /></label>
            <label>Proveedor<input value={integrationForm.provider_name} onChange={(event) => setIntegrationForm((prev) => ({ ...prev, provider_name: event.target.value }))} /></label>
            <label>Tipo<select value={integrationForm.provider_type} onChange={(event) => setIntegrationForm((prev) => ({ ...prev, provider_type: event.target.value }))}><option>crm</option><option>erp</option><option>ecommerce</option><option>analytics</option><option>support</option><option>knowledge_base</option></select></label>
            <label>Auth mode<select value={integrationForm.auth_mode} onChange={(event) => setIntegrationForm((prev) => ({ ...prev, auth_mode: event.target.value }))}><option>none</option><option>oauth</option><option>api_key_reference</option><option>webhook_signature</option></select></label>
            <button type="button" className="primary" onClick={createIntegration} disabled={busy === "integration"}>{busy === "integration" ? "Guardando..." : "Registrar integracion"}</button>
          </article>
          <article className="ai-context-card">
            <div className="ai-context-head"><strong>Integraciones AI</strong><span>{integrations.length}</span></div>
            {integrations.map((item) => (
              <div className="timeline-event" key={item.id}>
                <strong>{item.provider_name}</strong>
                <span>{item.integration_key} · {item.provider_type}</span>
                <small>{item.status} · {item.auth_mode}</small>
              </div>
            ))}
          </article>
        </div>
      ) : null}

      {activeTab === "apps" ? (
        <div className="form-grid two">
          <article className="ai-context-card">
            <div className="ai-context-head"><strong>Nueva AI app</strong><StatusBadge value={aiAppForm.status} /></div>
            <label>Key<input value={aiAppForm.app_key} onChange={(event) => setAiAppForm((prev) => ({ ...prev, app_key: event.target.value }))} /></label>
            <label>Nombre<input value={aiAppForm.name} onChange={(event) => setAiAppForm((prev) => ({ ...prev, name: event.target.value }))} /></label>
            <label>Tipo<select value={aiAppForm.app_type} onChange={(event) => setAiAppForm((prev) => ({ ...prev, app_type: event.target.value }))}><option>dashboard</option><option>copilot</option><option>operational_app</option><option>advisor_widget</option></select></label>
            <label>Descripcion<textarea rows={3} value={aiAppForm.description} onChange={(event) => setAiAppForm((prev) => ({ ...prev, description: event.target.value }))} /></label>
            <button type="button" className="primary" onClick={createAiApp} disabled={busy === "aiapp"}>{busy === "aiapp" ? "Guardando..." : "Guardar AI app"}</button>
          </article>
          <article className="ai-context-card">
            <div className="ai-context-head"><strong>AI apps</strong><span>{aiApps.length}</span></div>
            {aiApps.map((item) => (
              <div className="timeline-event" key={item.id}>
                <strong>{item.name}</strong>
                <span>{item.app_key} · {item.app_type}</span>
                <small>{item.status} · {shortDate(item.updated_at)}</small>
              </div>
            ))}
          </article>
        </div>
      ) : null}
    </section>
  );
}
