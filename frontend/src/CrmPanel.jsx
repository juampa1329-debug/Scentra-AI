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
};

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
  };
}

const number = (value) => Number(value || 0).toLocaleString("es-CO");

export default function CrmPanel({ apiCall, showStatus, onOpenInbox }) {
  const [customers, setCustomers] = useState([]);
  const [labels, setLabels] = useState([]);
  const [selectedId, setSelectedId] = useState("");
  const [form, setForm] = useState(emptyCustomerForm);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [creating, setCreating] = useState(false);

  const selectedCustomer = useMemo(
    () => customers.find((customer) => customer.id === selectedId) || null,
    [customers, selectedId],
  );

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
                  <small>{customer.crm_stage || "sin etapa"} / {customer.payment_status || "sin pago"}</small>
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
                <label>Etapa comercial<select value={form.crm_stage} onChange={(event) => updateField("crm_stage", event.target.value)}><option value="contactado">Contactado</option><option value="interes">Interes</option><option value="intencion_compra">Intencion de compra</option><option value="pago_pendiente">Pago pendiente</option><option value="pago_confirmado">Pago confirmado</option></select></label>
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
      </div>
    </section>
  );
}
