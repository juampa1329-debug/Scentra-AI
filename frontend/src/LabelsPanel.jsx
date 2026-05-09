import React, { useEffect, useState } from "react";

const defaultLabel = () => ({
  name: "",
  color: "#5eead4",
  category: "ventas",
  description: "",
});

const number = (value) => Number(value || 0).toLocaleString("es-CO");

export default function LabelsPanel({ apiCall, showStatus, onGoCampaigns }) {
  const [labels, setLabels] = useState([]);
  const [form, setForm] = useState(defaultLabel);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const loadLabels = async () => {
    setLoading(true);
    try {
      const data = await apiCall("/saas/v1/labels");
      setLabels(data?.labels || []);
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadLabels();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const createLabel = async (event) => {
    event.preventDefault();
    if (!form.name.trim()) return showStatus("Nombre de etiqueta requerido.", "error");
    setSaving(true);
    try {
      await apiCall("/saas/v1/labels", { method: "POST", body: JSON.stringify(form) });
      setForm(defaultLabel());
      await loadLabels();
      showStatus("Etiqueta creada", "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setSaving(false);
    }
  };

  const toggleLabel = async (label) => {
    try {
      await apiCall(`/saas/v1/labels/${encodeURIComponent(label.id)}`, {
        method: "PATCH",
        body: JSON.stringify({ is_active: !label.is_active }),
      });
      await loadLabels();
      showStatus(label.is_active ? "Etiqueta pausada" : "Etiqueta activada", "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    }
  };

  return (
    <section className="module-page">
      <div className="hero-card glass-card">
        <div>
          <p className="eyebrow">Segmentacion</p>
          <h2>Etiquetas y reglas</h2>
          <p>Catalogo real por empresa para clasificar clientes, alimentar segmentos y preparar automatizaciones.</p>
        </div>
        <button type="button" onClick={loadLabels}>Refrescar</button>
      </div>

      <div className="module-grid">
        <article className="panel glass-card module-card">
          <div className="panel-head">
            <h2>Etiquetas comerciales</h2>
            <span>{loading ? "cargando" : `${number(labels.length)} etiquetas`}</span>
          </div>
          <div className="label-cloud">
            {labels.map((label) => (
              <button
                type="button"
                key={label.id}
                className={`label-pill ${label.is_active ? "" : "muted-label"}`}
                style={{ borderColor: label.color }}
                onClick={() => toggleLabel(label)}
              >
                {label.name}<small>{label.usage_count || 0}</small>
              </button>
            ))}
            {!loading && labels.length === 0 ? <div className="empty">Aun no hay etiquetas.</div> : null}
          </div>
        </article>

        <article className="panel glass-card module-card">
          <div className="panel-head">
            <h2>Nueva etiqueta</h2>
            <span>CRM</span>
          </div>
          <form className="label-form" onSubmit={createLabel}>
            <div className="form-grid two">
              <label>Nombre<input value={form.name} onChange={(event) => setForm((prev) => ({ ...prev, name: event.target.value }))} placeholder="Ej: Pago pendiente" /></label>
              <label>Color<input type="color" value={form.color} onChange={(event) => setForm((prev) => ({ ...prev, color: event.target.value }))} /></label>
              <label>Categoria<select value={form.category} onChange={(event) => setForm((prev) => ({ ...prev, category: event.target.value }))}><option value="ventas">Ventas</option><option value="soporte">Soporte</option><option value="automatizacion">Automatizacion</option><option value="retencion">Retencion</option></select></label>
            </div>
            <label>Descripcion<textarea rows={4} value={form.description} onChange={(event) => setForm((prev) => ({ ...prev, description: event.target.value }))} /></label>
            <div className="panel-actions">
              <button type="submit" className="primary" disabled={saving}>{saving ? "Creando..." : "Crear etiqueta"}</button>
              <button type="button" onClick={onGoCampaigns}>Usar en campanas</button>
            </div>
          </form>
        </article>

        <article className="panel glass-card module-card wide-api-card">
          <div className="panel-head">
            <h2>Reglas sugeridas</h2>
            <span>IA + CRM</span>
          </div>
          <div className="rule-list">
            <div><strong>Si pregunta precio</strong><span>Aplicar Interes compra y activar seguimiento.</span></div>
            <div><strong>Si envia comprobante</strong><span>Aplicar Pago pendiente y notificar humano.</span></div>
            <div><strong>Si no responde 48h</strong><span>Enviar flow de remarketing suave.</span></div>
          </div>
        </article>
      </div>
    </section>
  );
}
