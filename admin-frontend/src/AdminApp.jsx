import React, { useEffect, useMemo, useState } from "react";

const API_BASE = (import.meta.env.VITE_API_BASE || "").replace(/\/$/, "");
const CLIENT_APP_BASE = (import.meta.env.VITE_CLIENT_APP_BASE || "http://localhost:5174").replace(/\/$/, "");
const TOKEN_KEY = "scentra_admin_access_token";

const VIEWS = [
  ["overview", "Overview"],
  ["tenants", "Empresas"],
  ["plans", "Planes"],
  ["subscriptions", "Suscripciones"],
  ["operations", "Operacion"],
  ["audit", "Auditoria"],
];
const TENANT_STATUSES = ["active", "trial", "paused", "past_due", "suspended", "cancelled"];
const SUB_STATUSES = ["trial", "active", "past_due", "cancelled", "suspended"];
const DEFAULT_FEATURES = {
  inbox: true,
  ai: true,
  broadcast: true,
  triggers: false,
  remarketing: false,
  ads: false,
  whatsapp_cloud: true,
  elevenlabs_voice: false,
};

const number = (value) => Number(value || 0).toLocaleString("es-CO");
const money = (cents, currency = "USD") => `${currency} ${(Number(cents || 0) / 100).toLocaleString("es-CO", { minimumFractionDigits: 0, maximumFractionDigits: 2 })}`;
const pct = (used, limit) => (!Number(limit || 0) ? 0 : Math.min(100, Math.round((Number(used || 0) / Number(limit || 0)) * 100)));

function emptyLogin() {
  return { email: "", password: "" };
}

function emptyPlan() {
  return {
    plan_code: "",
    display_name: "",
    max_agents: 3,
    max_monthly_messages: 5000,
    max_integrations: 3,
    max_storage_gb: 5,
    max_campaigns: 10,
    max_broadcasts: 10,
    max_ai_tokens: 1000000,
    price_monthly_cents: 0,
    currency: "USD",
    is_public: true,
    is_active: true,
    sort_order: 100,
    feature_flags_json: { ...DEFAULT_FEATURES },
  };
}

function formatApiError(data, fallback) {
  const detail = data?.detail || data?.error;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((item) => item.msg || "dato invalido").join(" | ");
  if (detail && typeof detail === "object") return detail.message || detail.code || fallback;
  return fallback;
}

function statusClass(status) {
  const value = String(status || "").toLowerCase();
  if (["active", "trial", "sent", "ok"].includes(value)) return "ok";
  if (["past_due", "paused", "queued"].includes(value)) return "warn";
  if (["suspended", "cancelled", "failed", "error"].includes(value)) return "danger";
  return "neutral";
}

function queueTotal(rows, status) {
  return (rows || []).find((item) => item.status === status)?.total || 0;
}

export default function AdminApp() {
  const [token, setToken] = useState(() => localStorage.getItem(TOKEN_KEY) || "");
  const [me, setMe] = useState(null);
  const [activeView, setActiveView] = useState("overview");
  const [login, setLogin] = useState(emptyLogin);
  const [bootstrap, setBootstrap] = useState({ email: "", password: "", full_name: "Scentra Admin", platform_role: "superadmin" });
  const [status, setStatus] = useState("");
  const [statusTone, setStatusTone] = useState("neutral");
  const [loading, setLoading] = useState(false);
  const [overview, setOverview] = useState(null);
  const [tenants, setTenants] = useState([]);
  const [tenantSearch, setTenantSearch] = useState("");
  const [tenantStatus, setTenantStatus] = useState("all");
  const [tenantPlan, setTenantPlan] = useState("all");
  const [selectedTenantId, setSelectedTenantId] = useState("");
  const [tenantDetail, setTenantDetail] = useState(null);
  const [plans, setPlans] = useState([]);
  const [planForm, setPlanForm] = useState(emptyPlan);
  const [subscriptions, setSubscriptions] = useState([]);
  const [audit, setAudit] = useState([]);
  const [queues, setQueues] = useState(null);
  const [features, setFeatures] = useState([]);

  const showStatus = (text, tone = "neutral") => { setStatus(text); setStatusTone(tone); };
  const headers = useMemo(() => {
    const next = { "Content-Type": "application/json" };
    if (token) next.Authorization = `Bearer ${token}`;
    return next;
  }, [token]);

  const apiCall = async (path, options = {}) => {
    if (!API_BASE) throw new Error("VITE_API_BASE requerido");
    const res = await fetch(`${API_BASE}${path}`, { ...options, headers: { ...headers, ...(options.headers || {}) } });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(formatApiError(data, `HTTP ${res.status}`));
    return data;
  };

  const setSession = (data) => {
    const nextToken = data?.access_token || "";
    setToken(nextToken);
    if (nextToken) localStorage.setItem(TOKEN_KEY, nextToken);
    setMe({ user_id: data?.user_id, email: data?.email, platform_role: data?.platform_role });
  };

  const clearSession = () => {
    setToken("");
    setMe(null);
    localStorage.removeItem(TOKEN_KEY);
  };

  const loadMe = async () => {
    if (!token) return;
    const data = await apiCall("/saas/v1/admin/auth/me");
    setMe(data);
  };

  const loadOverview = async () => {
    const data = await apiCall("/saas/v1/admin/overview");
    setOverview(data);
    setQueues(data?.queues || null);
  };

  const loadPlans = async () => {
    const data = await apiCall("/saas/v1/admin/plans");
    setPlans(data?.plans || []);
  };

  const loadFeatures = async () => {
    const data = await apiCall("/saas/v1/admin/feature-flags/catalog");
    setFeatures(data?.features || []);
  };

  const loadTenants = async () => {
    const params = new URLSearchParams({ search: tenantSearch, status: tenantStatus, plan_code: tenantPlan, limit: "100", offset: "0" });
    const data = await apiCall(`/saas/v1/admin/tenants?${params.toString()}`);
    setTenants(data?.tenants || []);
    if (!selectedTenantId && data?.tenants?.[0]?.id) setSelectedTenantId(data.tenants[0].id);
  };

  const loadTenantDetail = async (tenantId = selectedTenantId) => {
    if (!tenantId) return;
    const data = await apiCall(`/saas/v1/admin/tenants/${encodeURIComponent(tenantId)}`);
    setSelectedTenantId(tenantId);
    setTenantDetail(data);
  };

  const loadSubscriptions = async () => {
    const data = await apiCall("/saas/v1/admin/subscriptions?limit=200");
    setSubscriptions(data?.subscriptions || []);
  };

  const loadAudit = async () => {
    const data = await apiCall("/saas/v1/admin/audit?limit=120");
    setAudit(data?.audit || []);
  };

  const loadQueues = async () => {
    const data = await apiCall("/saas/v1/admin/operations/queues");
    setQueues(data?.queues || null);
  };

  const refreshActive = async (silent = false) => {
    if (!token) return;
    setLoading(true);
    try {
      if (activeView === "overview") await loadOverview();
      if (activeView === "tenants") { await Promise.all([loadTenants(), loadPlans(), loadFeatures()]); }
      if (activeView === "plans") { await Promise.all([loadPlans(), loadFeatures()]); }
      if (activeView === "subscriptions") await Promise.all([loadSubscriptions(), loadPlans()]);
      if (activeView === "operations") await loadQueues();
      if (activeView === "audit") await loadAudit();
      if (!silent) showStatus("Admin actualizado", "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!token) return;
    loadMe().catch(() => clearSession());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  useEffect(() => {
    refreshActive(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, activeView]);

  useEffect(() => {
    if (activeView === "tenants" && selectedTenantId) loadTenantDetail(selectedTenantId).catch((err) => showStatus(String(err.message || err), "error"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedTenantId]);

  const submitLogin = async (event) => {
    event.preventDefault();
    try {
      const data = await apiCall("/saas/v1/admin/auth/login", { method: "POST", body: JSON.stringify(login) });
      setSession(data);
      setLogin(emptyLogin());
      showStatus("Admin autenticado", "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    }
  };

  const submitBootstrap = async (event) => {
    event.preventDefault();
    try {
      const data = await apiCall("/saas/v1/admin/auth/bootstrap", { method: "POST", body: JSON.stringify(bootstrap) });
      setSession(data);
      showStatus("Admin local creado", "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    }
  };

  const updateTenant = async (tenantId, patch) => {
    try {
      await apiCall(`/saas/v1/admin/tenants/${encodeURIComponent(tenantId)}`, { method: "PATCH", body: JSON.stringify(patch) });
      showStatus("Empresa actualizada", "ok");
      await loadTenants();
      await loadTenantDetail(tenantId);
    } catch (err) {
      showStatus(String(err.message || err), "error");
    }
  };

  const setTenantFeature = async (tenantId, featureKey, enabled) => {
    try {
      await apiCall(`/saas/v1/admin/tenants/${encodeURIComponent(tenantId)}/feature-flags`, {
        method: "POST",
        body: JSON.stringify({ feature_key: featureKey, is_enabled: enabled, source: "admin", notes: "Cambio desde Scentra Admin" }),
      });
      showStatus("Feature flag actualizada", "ok");
      await loadTenantDetail(tenantId);
    } catch (err) {
      showStatus(String(err.message || err), "error");
    }
  };

  const impersonateTenant = async (tenantId) => {
    try {
      const data = await apiCall(`/saas/v1/admin/tenants/${encodeURIComponent(tenantId)}/impersonate`, {
        method: "POST",
        body: JSON.stringify({ role: "admin", reason: "Soporte desde Scentra Admin" }),
      });
      const url = `${CLIENT_APP_BASE}/#support_token=${encodeURIComponent(data.access_token)}`;
      window.open(url, "_blank", "noopener,noreferrer");
      showStatus(`Acceso de soporte generado para ${data.tenant_name}`, "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    }
  };

  const savePlan = async (event) => {
    event.preventDefault();
    try {
      const payload = { ...planForm, price_monthly_cents: Number(planForm.price_monthly_cents || 0) };
      await apiCall("/saas/v1/admin/plans", { method: "POST", body: JSON.stringify(payload) });
      showStatus("Plan guardado", "ok");
      setPlanForm(emptyPlan());
      await loadPlans();
    } catch (err) {
      showStatus(String(err.message || err), "error");
    }
  };

  const editPlan = (plan) => setPlanForm({ ...emptyPlan(), ...plan, feature_flags_json: { ...DEFAULT_FEATURES, ...(plan.feature_flags_json || {}) } });

  const patchSubscription = async (tenantId, patch) => {
    try {
      await apiCall(`/saas/v1/admin/subscriptions/${encodeURIComponent(tenantId)}`, { method: "PATCH", body: JSON.stringify(patch) });
      showStatus("Suscripcion actualizada", "ok");
      await loadSubscriptions();
    } catch (err) {
      showStatus(String(err.message || err), "error");
    }
  };

  const processQueue = async (kind) => {
    const endpoint = kind === "webhooks" ? "webhooks" : kind === "triggers" ? "triggers" : "outbound";
    try {
      const data = await apiCall(`/saas/v1/admin/operations/${endpoint}/process?limit=50`, { method: "POST" });
      showStatus(`Procesado: ${JSON.stringify(data.result)}`, "ok");
      await loadQueues();
    } catch (err) {
      showStatus(String(err.message || err), "error");
    }
  };

  if (!token || !me) {
    return (
      <main className="admin-auth">
        <section className="auth-card glass-card">
          <div className="brand-block">
            <span className="brand-glyph">S</span>
            <div><h1>Scentra Admin</h1><p>Centro de control interno para planes, clientes y operacion.</p></div>
          </div>
          {status ? <div className={`status ${statusTone}`}>{status}</div> : null}
          <form className="auth-grid" onSubmit={submitLogin}>
            <label>Email<input value={login.email} autoComplete="email" onChange={(event) => setLogin((prev) => ({ ...prev, email: event.target.value }))} /></label>
            <label>Password<input type="password" value={login.password} autoComplete="current-password" onChange={(event) => setLogin((prev) => ({ ...prev, password: event.target.value }))} /></label>
            <button type="submit" className="primary">Entrar al Admin</button>
          </form>
          <details className="bootstrap-box">
            <summary>Crear primer admin local</summary>
            <form className="auth-grid" onSubmit={submitBootstrap}>
              <label>Email<input value={bootstrap.email} onChange={(event) => setBootstrap((prev) => ({ ...prev, email: event.target.value }))} /></label>
              <label>Password<input type="password" value={bootstrap.password} onChange={(event) => setBootstrap((prev) => ({ ...prev, password: event.target.value }))} /></label>
              <label>Nombre<input value={bootstrap.full_name} onChange={(event) => setBootstrap((prev) => ({ ...prev, full_name: event.target.value }))} /></label>
              <label>Rol<select value={bootstrap.platform_role} onChange={(event) => setBootstrap((prev) => ({ ...prev, platform_role: event.target.value }))}><option value="superadmin">superadmin</option><option value="platform_admin">platform_admin</option><option value="billing_admin">billing_admin</option><option value="support">support</option></select></label>
              <button type="submit">Bootstrap local</button>
            </form>
          </details>
        </section>
      </main>
    );
  }

  return (
    <div className="admin-shell">
      <aside className="admin-sidebar glass-card">
        <div className="brand-block compact"><span className="brand-glyph">S</span><div><strong>Scentra Admin</strong><small>{me.platform_role}</small></div></div>
        <nav>{VIEWS.map(([id, label]) => <button key={id} type="button" className={activeView === id ? "active" : ""} onClick={() => setActiveView(id)}>{label}</button>)}</nav>
        <div className="operator-card"><small>Operador</small><strong>{me.email}</strong><button type="button" onClick={clearSession}>Salir</button></div>
      </aside>

      <main className="admin-content">
        <header className="topbar glass-card">
          <div><p className="eyebrow">Control interno</p><h1>{VIEWS.find(([id]) => id === activeView)?.[1]}</h1></div>
          <div className="top-actions"><button type="button" onClick={() => refreshActive(false)}>{loading ? "Actualizando..." : "Recargar"}</button></div>
        </header>
        {status ? <div className={`status floating ${statusTone}`}>{status}</div> : null}

        {activeView === "overview" ? <Overview overview={overview} /> : null}
        {activeView === "tenants" ? (
          <TenantsView
            tenants={tenants}
            plans={plans}
            features={features}
            tenantSearch={tenantSearch}
            tenantStatus={tenantStatus}
            tenantPlan={tenantPlan}
            selectedTenantId={selectedTenantId}
            tenantDetail={tenantDetail}
            setTenantSearch={setTenantSearch}
            setTenantStatus={setTenantStatus}
            setTenantPlan={setTenantPlan}
            loadTenants={loadTenants}
            selectTenant={setSelectedTenantId}
            updateTenant={updateTenant}
            setTenantFeature={setTenantFeature}
            impersonateTenant={impersonateTenant}
          />
        ) : null}
        {activeView === "plans" ? <PlansView plans={plans} features={features} planForm={planForm} setPlanForm={setPlanForm} savePlan={savePlan} editPlan={editPlan} /> : null}
        {activeView === "subscriptions" ? <SubscriptionsView subscriptions={subscriptions} plans={plans} patchSubscription={patchSubscription} /> : null}
        {activeView === "operations" ? <OperationsView queues={queues} processQueue={processQueue} /> : null}
        {activeView === "audit" ? <AuditView audit={audit} /> : null}
      </main>
    </div>
  );
}

function Overview({ overview }) {
  const tenants = overview?.tenants || {};
  const usage = Object.fromEntries((overview?.usage || []).map((item) => [item.metric_code, item.total]));
  return (
    <section className="stack">
      <div className="metric-grid">
        <Metric title="Empresas" value={tenants.total} hint={`${number(tenants.active)} activas`} tone="mint" />
        <Metric title="Trial" value={tenants.trial} hint="En evaluacion" tone="blue" />
        <Metric title="Past due" value={tenants.past_due} hint="Revisar pagos" tone="amber" />
        <Metric title="Suspendidas" value={tenants.suspended} hint="Bloqueadas" tone="rose" />
        <Metric title="Mensajes mes" value={usage.messages_in || 0} hint={`${number(usage.outbound_messages_queued || 0)} outbound`} tone="violet" />
      </div>
      <div className="dashboard-grid">
        <article className="panel glass-card"><div className="panel-head"><h2>Planes activos</h2><span>{overview?.period_yyyymm}</span></div><div className="list">{(overview?.plans || []).map((item) => <div key={item.plan_code}><strong>{item.plan_code}</strong><span>{number(item.tenants)} empresas</span></div>)}</div></article>
        <article className="panel glass-card"><div className="panel-head"><h2>Colas</h2><span>runtime</span></div><QueueSummary queues={overview?.queues} /></article>
      </div>
    </section>
  );
}

function Metric({ title, value, hint, tone }) {
  return <article className={`metric-card ${tone}`}><span>{title}</span><strong>{number(value)}</strong><small>{hint}</small></article>;
}

function TenantsView(props) {
  const {
    tenants, plans, features, tenantSearch, tenantStatus, tenantPlan, selectedTenantId, tenantDetail,
    setTenantSearch, setTenantStatus, setTenantPlan, loadTenants, selectTenant, updateTenant, setTenantFeature,
    impersonateTenant,
  } = props;
  const detail = tenantDetail || {};
  const selected = detail.tenant || {};
  const owner = detail.owner || {};
  const limits = detail.billing?.plan?.limits || {};
  const usage = detail.billing?.usage || {};
  const featureMap = Object.fromEntries((detail.feature_flags || []).map((item) => [item.feature_key, item]));
  const planName = (code) => plans.find((plan) => plan.plan_code === code)?.display_name || code || "Sin plan";
  return (
    <section className="tenant-layout">
      <article className="panel glass-card">
        <div className="panel-head"><h2>Empresas</h2><span>{number(tenants.length)}</span></div>
        <div className="filter-bar">
          <input value={tenantSearch} onChange={(event) => setTenantSearch(event.target.value)} placeholder="Buscar empresa..." />
          <select value={tenantStatus} onChange={(event) => setTenantStatus(event.target.value)}><option value="all">Todos</option>{TENANT_STATUSES.map((item) => <option key={item} value={item}>{item}</option>)}</select>
          <select value={tenantPlan} onChange={(event) => setTenantPlan(event.target.value)}><option value="all">Todos los planes</option>{plans.map((plan) => <option key={plan.plan_code} value={plan.plan_code}>{plan.plan_code}</option>)}</select>
          <button type="button" onClick={loadTenants}>Filtrar</button>
        </div>
        <div className="tenant-list">{tenants.map((tenant) => <button key={tenant.id} type="button" className={tenant.id === selectedTenantId ? "active" : ""} onClick={() => selectTenant(tenant.id)}><strong>{tenant.name}</strong><span>{tenant.owner_name || tenant.owner_email || "Owner sin nombre"}</span><mark className={statusClass(tenant.status)}>{tenant.status}</mark><small>{planName(tenant.plan_code)} / {number(tenant.used_monthly_messages)} msgs</small></button>)}</div>
      </article>
      <article className="panel glass-card tenant-detail">
        <div className="panel-head"><h2>{selected.name || "Selecciona empresa"}</h2><span>{owner.full_name || owner.email || "Cliente"}</span></div>
        {selected.id ? (
          <>
            <div className="admin-actions">
              {TENANT_STATUSES.map((item) => <button key={item} type="button" className={selected.status === item ? "primary" : ""} onClick={() => updateTenant(selected.id, { status: item, subscription_status: item === "past_due" ? "past_due" : item === "suspended" ? "suspended" : item === "cancelled" ? "cancelled" : "active" })}>{item}</button>)}
              <button type="button" onClick={() => impersonateTenant(selected.id)}>Abrir como soporte</button>
            </div>
            <div className="owner-card">
              <span>Cliente principal</span>
              <strong>{owner.full_name || owner.email || "Sin owner visible"}</strong>
              <small>{owner.email || "Sin email"}</small>
            </div>
            <div className="form-grid two">
              <label>Plan<select value={selected.plan_code || ""} onChange={(event) => updateTenant(selected.id, { plan_code: event.target.value, subscription_status: "active" })}>{plans.map((plan) => <option key={plan.plan_code} value={plan.plan_code}>{plan.display_name || plan.plan_code}</option>)}</select></label>
              <label>Nombre<input defaultValue={selected.name || ""} onBlur={(event) => event.target.value !== selected.name && updateTenant(selected.id, { name: event.target.value })} /></label>
            </div>
            <div className="usage-box">
              <div><strong>{number(usage.used_monthly_messages)}</strong><span>mensajes / {number(limits.max_monthly_messages)}</span><div className="meter"><span style={{ width: `${pct(usage.used_monthly_messages, limits.max_monthly_messages)}%` }} /></div></div>
              <div><strong>{number(usage.used_agents)}</strong><span>usuarios / {number(limits.max_agents)}</span></div>
              <div><strong>{number(usage.used_integrations)}</strong><span>integraciones / {number(limits.max_integrations)}</span></div>
            </div>
            <h3>Feature flags</h3>
            <div className="flag-grid">{features.map((feature) => <label key={feature.key} className="switch"><input type="checkbox" checked={Boolean(featureMap[feature.key]?.is_enabled)} onChange={(event) => setTenantFeature(selected.id, feature.key, event.target.checked)} /><span><strong>{feature.label}</strong><small>{featureMap[feature.key]?.source || "plan/default"}</small></span></label>)}</div>
            <h3>Usuarios</h3>
            <div className="table compact">{(detail.members || []).map((member) => <div className="row" key={member.id}><span>{member.email}</span><span>{member.role}</span><span>{member.is_active ? "activo" : "inactivo"}</span></div>)}</div>
          </>
        ) : <p className="empty">Sin empresa seleccionada.</p>}
      </article>
    </section>
  );
}

function PlansView({ plans, features, planForm, setPlanForm, savePlan, editPlan }) {
  const updateFeature = (key, value) => setPlanForm((prev) => ({ ...prev, feature_flags_json: { ...(prev.feature_flags_json || {}), [key]: value } }));
  return (
    <section className="plans-layout">
      <article className="panel glass-card">
        <div className="panel-head"><h2>Planes</h2><span>{number(plans.length)}</span></div>
        <div className="plan-grid">{plans.map((plan) => <button key={plan.plan_code} type="button" className="plan-card" onClick={() => editPlan(plan)}><strong>{plan.display_name || plan.plan_code}</strong><span>{money(plan.price_monthly_cents, plan.currency)} / mes</span><small>{number(plan.max_monthly_messages)} mensajes / {number(plan.tenants_count)} empresas</small><mark className={plan.is_active ? "ok" : "danger"}>{plan.is_active ? "activo" : "inactivo"}</mark></button>)}</div>
      </article>
      <article className="panel glass-card">
        <div className="panel-head"><h2>Crear / editar plan</h2><button type="button" onClick={() => setPlanForm(emptyPlan())}>Nuevo</button></div>
        <form className="plan-form" onSubmit={savePlan}>
          <div className="form-grid two"><label>Codigo<input value={planForm.plan_code} onChange={(event) => setPlanForm((prev) => ({ ...prev, plan_code: event.target.value }))} /></label><label>Nombre<input value={planForm.display_name} onChange={(event) => setPlanForm((prev) => ({ ...prev, display_name: event.target.value }))} /></label></div>
          <div className="form-grid four">
            {["max_agents", "max_monthly_messages", "max_integrations", "max_storage_gb", "max_campaigns", "max_broadcasts", "max_ai_tokens", "price_monthly_cents"].map((key) => <label key={key}>{key}<input type="number" value={planForm[key]} onChange={(event) => setPlanForm((prev) => ({ ...prev, [key]: Number(event.target.value || 0) }))} /></label>)}
          </div>
          <div className="form-grid two"><label>Moneda<input value={planForm.currency} onChange={(event) => setPlanForm((prev) => ({ ...prev, currency: event.target.value }))} /></label><label>Orden<input type="number" value={planForm.sort_order} onChange={(event) => setPlanForm((prev) => ({ ...prev, sort_order: Number(event.target.value || 0) }))} /></label></div>
          <div className="flag-grid">{features.map((feature) => <label className="switch" key={feature.key}><input type="checkbox" checked={Boolean(planForm.feature_flags_json?.[feature.key])} onChange={(event) => updateFeature(feature.key, event.target.checked)} /><span><strong>{feature.label}</strong><small>{feature.key}</small></span></label>)}</div>
          <label className="check"><input type="checkbox" checked={planForm.is_public} onChange={(event) => setPlanForm((prev) => ({ ...prev, is_public: event.target.checked }))} /> Publico</label>
          <label className="check"><input type="checkbox" checked={planForm.is_active} onChange={(event) => setPlanForm((prev) => ({ ...prev, is_active: event.target.checked }))} /> Activo</label>
          <button type="submit" className="primary">Guardar plan</button>
        </form>
      </article>
    </section>
  );
}

function SubscriptionsView({ subscriptions, plans, patchSubscription }) {
  return (
    <section className="panel glass-card">
      <div className="panel-head"><h2>Suscripciones</h2><span>{number(subscriptions.length)}</span></div>
      <div className="table">{subscriptions.map((sub) => <div className="row six" key={sub.id}><span><strong>{sub.tenant_name}</strong><small>{sub.owner_name || sub.owner_email || "Owner sin nombre"}</small></span><span>{sub.provider}</span><span><mark className={statusClass(sub.status)}>{sub.status}</mark></span><span>{plans.find((plan) => plan.plan_code === sub.plan_code)?.display_name || sub.plan_code}</span><span>{sub.current_period_end || "-"}</span><span className="row-actions"><select defaultValue={sub.plan_code} onChange={(event) => patchSubscription(sub.tenant_id, { status: "active", plan_code: event.target.value })}>{plans.map((plan) => <option key={plan.plan_code} value={plan.plan_code}>{plan.display_name || plan.plan_code}</option>)}</select>{SUB_STATUSES.map((status) => <button key={status} type="button" onClick={() => patchSubscription(sub.tenant_id, { status, plan_code: sub.plan_code })}>{status}</button>)}</span></div>)}</div>
    </section>
  );
}

function OperationsView({ queues, processQueue }) {
  return (
    <section className="dashboard-grid">
      <article className="panel glass-card"><div className="panel-head"><h2>Colas</h2><span>workers</span></div><QueueSummary queues={queues} /><div className="admin-actions"><button type="button" className="primary" onClick={() => processQueue("webhooks")}>Procesar webhooks</button><button type="button" className="primary" onClick={() => processQueue("outbound")}>Procesar outbound</button><button type="button" onClick={() => processQueue("triggers")}>Procesar triggers</button></div></article>
      <article className="panel glass-card"><div className="panel-head"><h2>Salud operativa</h2><span>local</span></div><p className="soft">Desde aqui podemos reintentar jobs y observar acumulaciones. La siguiente fase agregara logs filtrables por proveedor y tenant.</p></article>
    </section>
  );
}

function QueueSummary({ queues }) {
  const outbound = queues?.outbound || [];
  const webhooks = queues?.webhooks || [];
  const scheduled = queues?.scheduled_triggers || [];
  return (
    <div className="queue-grid">
      <div><span>Outbound queued</span><strong>{number(queueTotal(outbound, "queued"))}</strong></div>
      <div><span>Outbound failed</span><strong>{number(queueTotal(outbound, "failed"))}</strong></div>
      <div><span>Webhooks received</span><strong>{number(queueTotal(webhooks, "received"))}</strong></div>
      <div><span>Webhooks error</span><strong>{number(queueTotal(webhooks, "error"))}</strong></div>
      <div><span>Triggers pending</span><strong>{number(queueTotal(scheduled, "pending"))}</strong></div>
    </div>
  );
}

function AuditView({ audit }) {
  return (
    <section className="panel glass-card">
      <div className="panel-head"><h2>Auditoria</h2><span>{number(audit.length)}</span></div>
      <div className="table">{audit.map((item) => <div className="row audit-row" key={item.id}><span>{item.created_at}</span><span><strong>{item.action}</strong><small>{item.actor_email || "system"}</small></span><span>{item.tenant_name || "-"}</span><span>{item.resource_type}</span><span>{item.resource_id}</span></div>)}</div>
    </section>
  );
}
