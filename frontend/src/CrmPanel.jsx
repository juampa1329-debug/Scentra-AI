import React, { useEffect, useMemo, useState } from "react";

const emptyCustomerForm = {
  display_name: "",
  phone: "",
  first_name: "",
  last_name: "",
  city: "",
  customer_type: "",
  interests: "",
  tags: "",
  notes: "",
  payment_status: "",
  payment_reference: "",
  crm_stage: "contactado",
  intent: "",
  custom_fields: {},
};

const emptyCustomFieldForm = { field_key: "", label: "", field_type: "text", options: "", display_order: 100 };
const emptyStageForm = { stage_key: "", label: "", probability: 0, display_order: 100 };

function toCustomerForm(customer) {
  return {
    ...emptyCustomerForm,
    display_name: customer?.display_name || "",
    phone: customer?.phone || "",
    first_name: customer?.first_name || "",
    last_name: customer?.last_name || "",
    city: customer?.city || "",
    customer_type: customer?.customer_type || "",
    interests: customer?.interests || "",
    tags: customer?.tags || "",
    notes: customer?.notes || "",
    payment_status: customer?.payment_status || "",
    payment_reference: customer?.payment_reference || "",
    crm_stage: customer?.crm_stage || "contactado",
    intent: customer?.intent || "",
    custom_fields: { ...(customer?.custom_fields || customer?.profile_json?.custom_fields || {}) },
  };
}

const number = (value) => Number(value || 0).toLocaleString("es-CO");
const customFieldOptions = (field) => {
  const raw = field?.options_json;
  if (Array.isArray(raw)) return raw.map((item) => String(item || "").trim()).filter(Boolean);
  if (raw && typeof raw === "object" && Array.isArray(raw.options)) return raw.options.map((item) => String(item || "").trim()).filter(Boolean);
  return [];
};
const customFieldInputType = (fieldType) => ({
  number: "number",
  date: "date",
  url: "url",
  email: "email",
  phone: "tel",
}[String(fieldType || "text").toLowerCase()] || "text");

export default function CrmPanel({ apiCall, showStatus, onOpenInbox, crmConfig = {}, onConfigChange = () => {} }) {
  const [customers, setCustomers] = useState([]);
  const [labels, setLabels] = useState([]);
  const [selectedId, setSelectedId] = useState("");
  const [form, setForm] = useState(emptyCustomerForm);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [creating, setCreating] = useState(false);
  const [fieldForm, setFieldForm] = useState(emptyCustomFieldForm);
  const [stageForm, setStageForm] = useState(emptyStageForm);
  const [presetCode, setPresetCode] = useState("general");

  const selectedCustomer = useMemo(
    () => customers.find((customer) => customer.id === selectedId) || null,
    [customers, selectedId],
  );
  const customFields = useMemo(() => (crmConfig.custom_fields || []).filter((field) => field.is_active !== false), [crmConfig.custom_fields]);
  const pipelineStages = useMemo(() => ((crmConfig.pipeline || {}).stages || []).filter((stage) => stage.is_active !== false), [crmConfig.pipeline]);
  const stageLabel = (stageKey) => (pipelineStages.find((stage) => stage.stage_key === stageKey)?.label || stageKey || "sin etapa");

  const loadCustomers = async (silent = false) => {
    setLoading(true);
    try {
      const query = search.trim() ? `?search=${encodeURIComponent(search.trim())}&limit=100` : "?limit=100";
      const data = await apiCall(`/saas/v1/customers${query}`);
      const rows = data?.customers || [];
      setCustomers(rows);
      const nextSelected = rows.find((item) => item.id === selectedId) || rows[0] || null;
      setSelectedId(nextSelected?.id || "");
      setForm(toCustomerForm(nextSelected));
      setCreating(false);
      if (!silent) showStatus("Clientes actualizados", "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setLoading(false);
    }
  };

  const loadLabels = async () => {
    try {
      const data = await apiCall("/saas/v1/labels");
      setLabels(data?.labels || []);
    } catch (err) {
      showStatus(String(err.message || err), "error");
    }
  };

  useEffect(() => {
    loadCustomers(true);
    loadLabels();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const selectCustomer = (customer) => {
    setSelectedId(customer.id);
    setForm(toCustomerForm(customer));
    setCreating(false);
  };

  const startNewCustomer = () => {
    setSelectedId("");
    setForm(emptyCustomerForm);
    setCreating(true);
  };

  const cancelNewCustomer = () => {
    setCreating(false);
    const nextSelected = customers[0] || null;
    setSelectedId(nextSelected?.id || "");
    setForm(toCustomerForm(nextSelected));
  };

  const updateField = (field, value) => {
    setForm((prev) => ({ ...prev, [field]: value }));
  };
  const updateCustomField = (field, value) => {
    setForm((prev) => ({ ...prev, custom_fields: { ...(prev.custom_fields || {}), [field]: value } }));
  };

  const saveCustomer = async () => {
    if (!creating && !selectedId) return;
    if (creating && !form.display_name.trim() && !form.phone.trim()) {
      showStatus("Escribe al menos nombre visible o telefono para crear el cliente.", "error");
      return;
    }
    setSaving(true);
    try {
      const data = creating
        ? await apiCall("/saas/v1/customers", { method: "POST", body: JSON.stringify(form) })
        : await apiCall(`/saas/v1/customers/${encodeURIComponent(selectedId)}`, {
            method: "PATCH",
            body: JSON.stringify(form),
          });
      const updated = data?.customer;
      setCustomers((prev) => (creating ? [updated, ...prev] : prev.map((item) => (item.id === selectedId ? updated : item))));
      setSelectedId(updated?.id || "");
      setForm(toCustomerForm(updated));
      setCreating(false);
      showStatus(creating ? "Cliente creado" : "Ficha CRM guardada", "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setSaving(false);
    }
  };

  const assignLabel = async (labelId) => {
    if (!selectedId || !labelId) return;
    try {
      await apiCall(`/saas/v1/customers/${encodeURIComponent(selectedId)}/labels/${encodeURIComponent(labelId)}`, {
        method: "POST",
      });
      await loadCustomers(true);
      await loadLabels();
      showStatus("Etiqueta aplicada", "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    }
  };

  const createCustomField = async (event) => {
    event.preventDefault();
    if (!fieldForm.field_key.trim() || !fieldForm.label.trim()) return;
    const options = fieldForm.options.split(",").map((item) => item.trim()).filter(Boolean);
    try {
      await apiCall("/saas/v1/crm/custom-fields", {
        method: "POST",
        body: JSON.stringify({
          field_key: fieldForm.field_key,
          label: fieldForm.label,
          field_type: fieldForm.field_type,
          options_json: options,
          display_order: Number(fieldForm.display_order || 100),
        }),
      });
      setFieldForm(emptyCustomFieldForm);
      await onConfigChange();
      showStatus("Campo CRM creado", "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    }
  };

  const deactivateCustomField = async (fieldId) => {
    try {
      await apiCall(`/saas/v1/crm/custom-fields/${encodeURIComponent(fieldId)}`, { method: "DELETE" });
      await onConfigChange();
      showStatus("Campo CRM desactivado", "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    }
  };

  const applyPipelinePreset = async () => {
    try {
      await apiCall(`/saas/v1/crm/pipeline/presets/${encodeURIComponent(presetCode)}`, { method: "POST" });
      await onConfigChange();
      showStatus("Pipeline actualizado", "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    }
  };

  const createPipelineStage = async (event) => {
    event.preventDefault();
    if (!stageForm.stage_key.trim() || !stageForm.label.trim()) return;
    try {
      await apiCall("/saas/v1/crm/pipeline/stages", {
        method: "POST",
        body: JSON.stringify({
          stage_key: stageForm.stage_key,
          label: stageForm.label,
          probability: Number(stageForm.probability || 0),
          display_order: Number(stageForm.display_order || 100),
        }),
      });
      setStageForm(emptyStageForm);
      await onConfigChange();
      showStatus("Etapa CRM creada", "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    }
  };

  return (
    <section className="module-page">
      <div className="hero-card glass-card">
        <div>
          <p className="eyebrow">CRM comercial</p>
          <h2>Clientes y oportunidades</h2>
          <p>Ficha comercial persistente por empresa: datos del cliente, etapa, pago, intereses, notas y etiquetas.</p>
        </div>
        <button type="button" className="icon-button" onClick={() => loadCustomers(false)}>Actualizar</button>
      </div>

      <div className="module-grid customers-layout">
        <article className="panel glass-card module-card">
          <div className="panel-head">
            <h2>Base de clientes</h2>
            <span className="row-actions">
              <em>{loading ? "cargando" : `${number(customers.length)} registros`}</em>
              <button type="button" className="primary" onClick={startNewCustomer}>+ Nuevo</button>
            </span>
          </div>
          <form className="search-strip" onSubmit={(event) => { event.preventDefault(); loadCustomers(false); }}>
            <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Buscar por nombre, telefono, ciudad o etiqueta" />
            <button type="submit">Buscar</button>
          </form>
          <div className="customer-list">
            {customers.map((customer) => (
              <button
                type="button"
                className={`customer-row ${selectedId === customer.id ? "active" : ""}`}
                key={customer.id}
                onClick={() => selectCustomer(customer)}
              >
                <span className="avatar-dot">{String(customer.display_name || customer.phone || "S").slice(0, 1).toUpperCase()}</span>
                <span>
                  <strong>{customer.display_name || customer.phone || customer.external_contact_id || "Cliente sin nombre"}</strong>
                  <small>{stageLabel(customer.crm_stage)} / {customer.payment_status || "sin pago"}</small>
                </span>
                <em>{customer.takeover ? "Humano" : "IA"}</em>
              </button>
            ))}
            {!loading && customers.length === 0 ? <div className="empty">Aun no hay clientes sincronizados. Puedes crear uno manualmente.</div> : null}
          </div>
        </article>

        <article className="panel glass-card module-card">
          <div className="panel-head">
            <h2>Ficha CRM</h2>
            <span>{creating ? "nuevo cliente" : selectedCustomer ? selectedCustomer.channel : "selecciona cliente"}</span>
          </div>
          {selectedCustomer || creating ? (
            <>
              <div className="profile-mini">
                <div className="avatar-preview">{String(form.display_name || form.phone || "S").slice(0, 1).toUpperCase()}</div>
                <div>
                  <strong>{form.display_name || form.phone || "Cliente"}</strong>
                  <p>{selectedCustomer?.last_message_text || (creating ? "Crea una ficha comercial manual para seguimiento, pagos y remarketing." : "Sin ultimo mensaje registrado.")}</p>
                </div>
              </div>
              <div className="form-grid two">
                <label>Nombre visible<input value={form.display_name} onChange={(event) => updateField("display_name", event.target.value)} /></label>
                <label>Telefono<input value={form.phone} onChange={(event) => updateField("phone", event.target.value)} /></label>
                <label>Nombre<input value={form.first_name} onChange={(event) => updateField("first_name", event.target.value)} /></label>
                <label>Apellido<input value={form.last_name} onChange={(event) => updateField("last_name", event.target.value)} /></label>
                <label>Ciudad<input value={form.city} onChange={(event) => updateField("city", event.target.value)} /></label>
                <label>Tipo de cliente<input value={form.customer_type} placeholder="minorista, mayorista, VIP..." onChange={(event) => updateField("customer_type", event.target.value)} /></label>
                <label>Etapa comercial<select value={form.crm_stage} onChange={(event) => updateField("crm_stage", event.target.value)}>{pipelineStages.length ? pipelineStages.map((stage) => <option key={stage.id || stage.stage_key} value={stage.stage_key}>{stage.label}</option>) : <><option value="contactado">Contactado</option><option value="interes">Interes</option><option value="intencion_compra">Intencion de compra</option><option value="pago_pendiente">Pago pendiente</option><option value="pago_confirmado">Pago confirmado</option></>}</select></label>
                <label>Estado de pago<select value={form.payment_status} onChange={(event) => updateField("payment_status", event.target.value)}><option value="">Sin estado</option><option value="pending">Pendiente</option><option value="paid">Pagado</option><option value="failed">Fallido</option><option value="refunded">Devuelto</option></select></label>
                <label>Referencia pago<input value={form.payment_reference} onChange={(event) => updateField("payment_reference", event.target.value)} /></label>
                <label>Intencion IA<input value={form.intent} placeholder="precio, compra, soporte..." onChange={(event) => updateField("intent", event.target.value)} /></label>
              </div>
              <label>Intereses<textarea rows={3} value={form.interests} onChange={(event) => updateField("interests", event.target.value)} /></label>
              <label>Etiquetas texto<input value={form.tags} placeholder="VIP, Pago pendiente..." onChange={(event) => updateField("tags", event.target.value)} /></label>
              <div className="label-cloud compact-labels">
                {labels.filter((label) => label.is_active).map((label) => (
                  <button type="button" key={label.id} className="label-pill" style={{ borderColor: label.color }} onClick={() => assignLabel(label.id)}>
                    {label.name}<small>{label.usage_count || 0}</small>
                  </button>
                ))}
              </div>
              <label>Notas internas<textarea rows={5} value={form.notes} onChange={(event) => updateField("notes", event.target.value)} /></label>
              {customFields.length ? (
                <div className="crm-custom-card">
                  <div className="ai-context-head"><strong>Campos personalizados</strong><small>{customFields.length}</small></div>
                  <div className="form-grid two">
                    {customFields.map((field) => {
                      const value = (form.custom_fields || {})[field.field_key] ?? "";
                      const options = customFieldOptions(field);
                      if (String(field.field_type).toLowerCase() === "boolean") {
                        return <label className="check-row" key={field.id || field.field_key}><input type="checkbox" checked={Boolean(value)} onChange={(event) => updateCustomField(field.field_key, event.target.checked)} /> {field.label}</label>;
                      }
                      if (["select", "multiselect"].includes(String(field.field_type).toLowerCase())) {
                        return <label key={field.id || field.field_key}>{field.label}<select value={Array.isArray(value) ? value[0] || "" : value} onChange={(event) => updateCustomField(field.field_key, event.target.value)}><option value="">Sin valor</option>{options.map((option) => <option key={option} value={option}>{option}</option>)}</select></label>;
                      }
                      return <label key={field.id || field.field_key}>{field.label}<input type={customFieldInputType(field.field_type)} value={value} onChange={(event) => updateCustomField(field.field_key, event.target.value)} /></label>;
                    })}
                  </div>
                </div>
              ) : null}
              <div className="panel-actions">
                <button type="button" className="primary" disabled={saving} onClick={saveCustomer}>{saving ? "Guardando..." : creating ? "Crear cliente" : "Guardar ficha"}</button>
                {creating ? <button type="button" onClick={cancelNewCustomer}>Cancelar</button> : null}
                {selectedCustomer ? <button type="button" onClick={() => onOpenInbox(selectedCustomer)}>Abrir en inbox</button> : null}
              </div>
            </>
          ) : (
            <div className="empty">Selecciona un cliente para editar su ficha.</div>
          )}
        </article>

        <article className="panel glass-card module-card crm-config-card">
          <div className="panel-head"><h2>Configuracion CRM</h2><span>{pipelineStages.length} etapas / {customFields.length} campos</span></div>
          <div className="crm-config-section">
            <div className="ai-context-head"><strong>Pipeline por industria</strong><small>{crmConfig.pipeline?.industry_code || "general"}</small></div>
            <div className="config-inline">
              <select value={presetCode} onChange={(event) => setPresetCode(event.target.value)}>
                {(crmConfig.industry_presets || [{ code: "general", label: "General" }]).map((preset) => <option key={preset.code} value={preset.code}>{preset.label}</option>)}
              </select>
              <button type="button" onClick={applyPipelinePreset}>Aplicar preset</button>
            </div>
            <div className="stage-list">
              {pipelineStages.map((stage) => <span key={stage.id || stage.stage_key}>{stage.display_order}. {stage.label}<small>{stage.probability}%</small></span>)}
              {!pipelineStages.length ? <p className="muted-note">Sin etapas configuradas.</p> : null}
            </div>
            <form className="config-grid" onSubmit={createPipelineStage}>
              <input value={stageForm.stage_key} onChange={(event) => setStageForm((prev) => ({ ...prev, stage_key: event.target.value }))} placeholder="clave_etapa" />
              <input value={stageForm.label} onChange={(event) => setStageForm((prev) => ({ ...prev, label: event.target.value }))} placeholder="Etiqueta visible" />
              <input type="number" min="0" max="100" value={stageForm.probability} onChange={(event) => setStageForm((prev) => ({ ...prev, probability: event.target.value }))} />
              <button type="submit">Agregar etapa</button>
            </form>
          </div>
          <div className="crm-config-section">
            <div className="ai-context-head"><strong>Campos personalizados</strong><small>{customFields.length}</small></div>
            <form className="config-grid" onSubmit={createCustomField}>
              <input value={fieldForm.field_key} onChange={(event) => setFieldForm((prev) => ({ ...prev, field_key: event.target.value }))} placeholder="clave_campo" />
              <input value={fieldForm.label} onChange={(event) => setFieldForm((prev) => ({ ...prev, label: event.target.value }))} placeholder="Etiqueta visible" />
              <select value={fieldForm.field_type} onChange={(event) => setFieldForm((prev) => ({ ...prev, field_type: event.target.value }))}><option value="text">Texto</option><option value="number">Numero</option><option value="select">Lista</option><option value="date">Fecha</option><option value="boolean">Si/No</option><option value="email">Email</option><option value="phone">Telefono</option><option value="url">URL</option></select>
              <input value={fieldForm.options} onChange={(event) => setFieldForm((prev) => ({ ...prev, options: event.target.value }))} placeholder="Opciones separadas por coma" />
              <button type="submit">Crear campo</button>
            </form>
            <div className="stage-list">
              {customFields.map((field) => (
                <span key={field.id || field.field_key}>{field.label}<small>{field.field_key} / {field.field_type}</small><button type="button" onClick={() => deactivateCustomField(field.id)}>Desactivar</button></span>
              ))}
              {!customFields.length ? <p className="muted-note">Crea campos para adaptar la ficha comercial por tenant.</p> : null}
            </div>
          </div>
        </article>
      </div>
    </section>
  );
}
