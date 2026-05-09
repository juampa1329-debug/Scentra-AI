import React, { useEffect, useState } from "react";

const number = (value) => Number(value || 0).toLocaleString("es-CO");

const emptyAccount = () => ({
  provider: "meta",
  external_account_id: "",
  name: "",
  status: "connected",
  currency: "COP",
  timezone: "America/Bogota",
});

const emptyCampaign = () => ({
  account_id: "",
  provider: "meta",
  channel: "facebook",
  external_campaign_id: "",
  name: "",
  objective: "messages",
  status: "active",
  daily_budget_cents: 0,
  currency: "COP",
  metrics_json: { ctr: 0, cpc: 0, leads: 0 },
});

const emptyLead = () => ({
  provider: "meta",
  channel: "facebook",
  external_lead_id: "",
  external_form_id: "",
  external_ad_id: "",
  external_campaign_id: "",
  contact_name: "",
  email: "",
  phone: "",
  status: "new",
  create_conversation: true,
});

const emptyComment = () => ({
  provider: "meta",
  channel: "facebook",
  external_comment_id: "",
  external_post_id: "",
  external_ad_id: "",
  external_campaign_id: "",
  author_id: "",
  author_name: "",
  message: "",
  permalink_url: "",
  status: "new",
  create_conversation: true,
});

function statusClass(status) {
  const token = String(status || "").toLowerCase();
  if (["new", "active", "connected"].includes(token)) return "ok-chip";
  if (["review", "paused", "unknown"].includes(token)) return "warn-chip";
  if (["resolved", "converted", "completed"].includes(token)) return "done-chip";
  return "";
}

export default function AdsPanel({ apiCall, showStatus, onConnectMeta, onOpenInbox }) {
  const [tab, setTab] = useState("leads");
  const [summary, setSummary] = useState({});
  const [accounts, setAccounts] = useState([]);
  const [campaigns, setCampaigns] = useState([]);
  const [leads, setLeads] = useState([]);
  const [comments, setComments] = useState([]);
  const [accountForm, setAccountForm] = useState(emptyAccount);
  const [campaignForm, setCampaignForm] = useState(emptyCampaign);
  const [leadForm, setLeadForm] = useState(emptyLead);
  const [commentForm, setCommentForm] = useState(emptyComment);
  const [saving, setSaving] = useState("");
  const [loading, setLoading] = useState(true);

  const loadAll = async (silent = false) => {
    setLoading(true);
    try {
      const [summaryData, accountData, campaignData, leadData, commentData] = await Promise.all([
        apiCall("/saas/v1/ads/summary"),
        apiCall("/saas/v1/ads/accounts"),
        apiCall("/saas/v1/ads/campaigns"),
        apiCall("/saas/v1/ads/leads"),
        apiCall("/saas/v1/ads/comments"),
      ]);
      setSummary(summaryData?.summary || {});
      setAccounts(accountData?.accounts || []);
      setCampaigns(campaignData?.campaigns || []);
      setLeads(leadData?.leads || []);
      setComments(commentData?.comments || []);
      if (!silent) showStatus("Ads Manager actualizado", "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadAll(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const saveAccount = async (event) => {
    event.preventDefault();
    setSaving("account");
    try {
      await apiCall("/saas/v1/ads/accounts", { method: "POST", body: JSON.stringify(accountForm) });
      setAccountForm(emptyAccount());
      await loadAll(true);
      showStatus("Cuenta publicitaria guardada", "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setSaving("");
    }
  };

  const saveCampaign = async (event) => {
    event.preventDefault();
    setSaving("campaign");
    try {
      await apiCall("/saas/v1/ads/campaigns", { method: "POST", body: JSON.stringify(campaignForm) });
      setCampaignForm(emptyCampaign());
      await loadAll(true);
      showStatus("Campana ads guardada", "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setSaving("");
    }
  };

  const importLead = async (event) => {
    event.preventDefault();
    setSaving("lead");
    try {
      await apiCall("/saas/v1/ads/leads/import", { method: "POST", body: JSON.stringify(leadForm) });
      setLeadForm(emptyLead());
      await loadAll(true);
      showStatus("Lead importado", "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setSaving("");
    }
  };

  const importComment = async (event) => {
    event.preventDefault();
    setSaving("comment");
    try {
      await apiCall("/saas/v1/ads/comments/import", { method: "POST", body: JSON.stringify(commentForm) });
      setCommentForm(emptyComment());
      await loadAll(true);
      showStatus("Comentario importado", "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setSaving("");
    }
  };

  const processWebhooks = async () => {
    setSaving("webhooks");
    try {
      const data = await apiCall("/saas/v1/ads/webhook-events/process?limit=100", { method: "POST" });
      const result = data?.result || {};
      await loadAll(true);
      showStatus(`Webhooks Ads: ${number(result.leads)} leads, ${number(result.comments)} comentarios`, "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setSaving("");
    }
  };

  const convertLead = async (lead) => {
    setSaving(`lead-${lead.id}`);
    try {
      const data = await apiCall(`/saas/v1/ads/leads/${encodeURIComponent(lead.id)}/to-inbox`, { method: "POST" });
      await loadAll(true);
      showStatus("Lead convertido a inbox", "ok");
      if (data?.conversation_id) onOpenInbox({ id: data.conversation_id, channel: lead.channel, external_contact_id: lead.phone || lead.email || lead.external_lead_id, display_name: lead.contact_name || "Lead" });
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setSaving("");
    }
  };

  const convertComment = async (comment) => {
    setSaving(`comment-${comment.id}`);
    try {
      const data = await apiCall(`/saas/v1/ads/comments/${encodeURIComponent(comment.id)}/to-inbox`, { method: "POST" });
      await loadAll(true);
      showStatus("Comentario convertido a inbox", "ok");
      if (data?.conversation_id) onOpenInbox({ id: data.conversation_id, channel: comment.channel, external_contact_id: comment.author_id || comment.external_comment_id, display_name: comment.author_name || "Comentario" });
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setSaving("");
    }
  };

  const updateLeadStatus = async (lead, status) => {
    try {
      await apiCall(`/saas/v1/ads/leads/${encodeURIComponent(lead.id)}`, { method: "PATCH", body: JSON.stringify({ status }) });
      await loadAll(true);
      showStatus("Lead actualizado", "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    }
  };

  const updateCommentStatus = async (comment, status) => {
    try {
      await apiCall(`/saas/v1/ads/comments/${encodeURIComponent(comment.id)}`, { method: "PATCH", body: JSON.stringify({ status }) });
      await loadAll(true);
      showStatus("Comentario actualizado", "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    }
  };

  return (
    <section className="module-page ads-page">
      <div className="hero-card glass-card">
        <div>
          <p className="eyebrow">Meta y social inbox</p>
          <h2>Ads Manager y comentarios</h2>
          <p>Leads, comentarios y eventos de anuncios conectados a CRM e inbox. La sincronizacion real se apoya en webhooks y futuras llamadas Graph API.</p>
        </div>
        <div className="panel-actions hero-actions">
          <button type="button" onClick={processWebhooks} disabled={saving === "webhooks"}>{saving === "webhooks" ? "Procesando..." : "Procesar webhooks"}</button>
          <button type="button" className="primary" onClick={onConnectMeta}>Conectar Meta</button>
        </div>
      </div>

      <div className="ads-health">
        <div><strong>{number(summary.accounts)}</strong><span>Cuentas ads</span></div>
        <div><strong>{number(summary.campaigns)}</strong><span>Campanas ads</span></div>
        <div><strong>{number(summary.open_leads)}</strong><span>Leads abiertos</span></div>
        <div><strong>{number(summary.open_comments)}</strong><span>Comentarios abiertos</span></div>
        <div><strong>{number(summary.webhook_events)}</strong><span>Eventos webhook</span></div>
        <div><strong>{number(summary.social_conversations)}</strong><span>Chats sociales</span></div>
      </div>

      <div className="settings-tabs glass-card campaign-tabs">
        {[["leads", "Leads"], ["comments", "Comentarios"], ["accounts", "Cuentas"], ["campaigns", "Campanas"], ["webhooks", "Flujo Webhook"]].map(([key, label]) => (
          <button key={key} type="button" className={tab === key ? "active" : ""} onClick={() => setTab(key)}>{label}</button>
        ))}
      </div>

      {tab === "leads" ? (
        <div className="module-grid">
          <article className="panel glass-card module-card">
            <div className="panel-head"><h2>Leads capturados</h2><span>{loading ? "cargando" : number(leads.length)}</span></div>
            <div className="mini-table">
              {leads.map((lead) => (
                <div key={lead.id}>
                  <strong>{lead.contact_name || lead.email || lead.phone || lead.external_lead_id}</strong>
                  <span><mark className={statusClass(lead.status)}>{lead.status}</mark> {lead.channel} / form {lead.external_form_id || "-"}</span>
                  <p>{lead.email || "sin email"} / {lead.phone || "sin telefono"}</p>
                  <div className="panel-actions">
                    <button type="button" disabled={saving === `lead-${lead.id}`} onClick={() => convertLead(lead)}>{lead.conversation_id ? "Abrir/actualizar inbox" : "Convertir a inbox"}</button>
                    <button type="button" onClick={() => updateLeadStatus(lead, "review")}>Revision</button>
                    <button type="button" onClick={() => updateLeadStatus(lead, "converted")}>Convertido</button>
                  </div>
                </div>
              ))}
              {!loading && leads.length === 0 ? <div className="empty">Sin leads importados todavia.</div> : null}
            </div>
          </article>
          <article className="panel glass-card module-card">
            <div className="panel-head"><h2>Importar lead</h2><span>manual / QA</span></div>
            <form className="campaign-form" onSubmit={importLead}>
              <div className="form-grid two">
                <label>Lead ID<input value={leadForm.external_lead_id} onChange={(event) => setLeadForm((prev) => ({ ...prev, external_lead_id: event.target.value }))} placeholder="leadgen_id" /></label>
                <label>Canal<select value={leadForm.channel} onChange={(event) => setLeadForm((prev) => ({ ...prev, channel: event.target.value }))}><option value="facebook">Facebook</option><option value="instagram">Instagram</option></select></label>
                <label>Nombre<input value={leadForm.contact_name} onChange={(event) => setLeadForm((prev) => ({ ...prev, contact_name: event.target.value }))} /></label>
                <label>Email<input value={leadForm.email} onChange={(event) => setLeadForm((prev) => ({ ...prev, email: event.target.value }))} /></label>
                <label>Telefono<input value={leadForm.phone} onChange={(event) => setLeadForm((prev) => ({ ...prev, phone: event.target.value }))} /></label>
                <label>Campaign ID<input value={leadForm.external_campaign_id} onChange={(event) => setLeadForm((prev) => ({ ...prev, external_campaign_id: event.target.value }))} /></label>
              </div>
              <label className="check-row"><input type="checkbox" checked={leadForm.create_conversation} onChange={(event) => setLeadForm((prev) => ({ ...prev, create_conversation: event.target.checked }))} /> Crear conversacion en inbox</label>
              <div className="panel-actions"><button type="submit" className="primary" disabled={saving === "lead"}>{saving === "lead" ? "Importando..." : "Importar lead"}</button></div>
            </form>
          </article>
        </div>
      ) : null}

      {tab === "comments" ? (
        <div className="module-grid">
          <article className="panel glass-card module-card">
            <div className="panel-head"><h2>Comentarios</h2><span>{loading ? "cargando" : number(comments.length)}</span></div>
            <div className="mini-table">
              {comments.map((comment) => (
                <div key={comment.id}>
                  <strong>{comment.author_name || comment.author_id || "Autor social"}</strong>
                  <span><mark className={statusClass(comment.status)}>{comment.status}</mark> {comment.channel} / post {comment.external_post_id || "-"}</span>
                  <p>{comment.message}</p>
                  <div className="panel-actions">
                    <button type="button" disabled={saving === `comment-${comment.id}`} onClick={() => convertComment(comment)}>{comment.conversation_id ? "Abrir/actualizar inbox" : "Convertir a inbox"}</button>
                    <button type="button" onClick={() => updateCommentStatus(comment, "review")}>Revision</button>
                    <button type="button" onClick={() => updateCommentStatus(comment, "resolved")}>Resolver</button>
                    <button type="button" onClick={() => updateCommentStatus(comment, "ignored")}>Ignorar</button>
                  </div>
                </div>
              ))}
              {!loading && comments.length === 0 ? <div className="empty">Sin comentarios importados todavia.</div> : null}
            </div>
          </article>
          <article className="panel glass-card module-card">
            <div className="panel-head"><h2>Importar comentario</h2><span>manual / QA</span></div>
            <form className="campaign-form" onSubmit={importComment}>
              <div className="form-grid two">
                <label>Comment ID<input value={commentForm.external_comment_id} onChange={(event) => setCommentForm((prev) => ({ ...prev, external_comment_id: event.target.value }))} /></label>
                <label>Canal<select value={commentForm.channel} onChange={(event) => setCommentForm((prev) => ({ ...prev, channel: event.target.value }))}><option value="facebook">Facebook</option><option value="instagram">Instagram</option></select></label>
                <label>Autor ID<input value={commentForm.author_id} onChange={(event) => setCommentForm((prev) => ({ ...prev, author_id: event.target.value }))} /></label>
                <label>Autor<input value={commentForm.author_name} onChange={(event) => setCommentForm((prev) => ({ ...prev, author_name: event.target.value }))} /></label>
                <label>Post ID<input value={commentForm.external_post_id} onChange={(event) => setCommentForm((prev) => ({ ...prev, external_post_id: event.target.value }))} /></label>
                <label>Campaign ID<input value={commentForm.external_campaign_id} onChange={(event) => setCommentForm((prev) => ({ ...prev, external_campaign_id: event.target.value }))} /></label>
              </div>
              <label>Mensaje<textarea rows={5} value={commentForm.message} onChange={(event) => setCommentForm((prev) => ({ ...prev, message: event.target.value }))} /></label>
              <label className="check-row"><input type="checkbox" checked={commentForm.create_conversation} onChange={(event) => setCommentForm((prev) => ({ ...prev, create_conversation: event.target.checked }))} /> Crear conversacion en inbox</label>
              <div className="panel-actions"><button type="submit" className="primary" disabled={saving === "comment"}>{saving === "comment" ? "Importando..." : "Importar comentario"}</button></div>
            </form>
          </article>
        </div>
      ) : null}

      {tab === "accounts" ? (
        <div className="module-grid">
          <article className="panel glass-card module-card">
            <div className="panel-head"><h2>Cuentas publicitarias</h2><span>{number(accounts.length)}</span></div>
            <div className="mini-table">{accounts.map((account) => <div key={account.id}><strong>{account.name || account.external_account_id}</strong><span>{account.provider} / {account.status} / {account.currency}</span><p>{account.external_account_id}</p></div>)}{accounts.length === 0 ? <div className="empty">Sin cuentas todavia.</div> : null}</div>
          </article>
          <article className="panel glass-card module-card">
            <div className="panel-head"><h2>Registrar cuenta</h2><span>Meta</span></div>
            <form className="campaign-form" onSubmit={saveAccount}>
              <label>Account ID<input value={accountForm.external_account_id} onChange={(event) => setAccountForm((prev) => ({ ...prev, external_account_id: event.target.value }))} placeholder="act_..." /></label>
              <label>Nombre<input value={accountForm.name} onChange={(event) => setAccountForm((prev) => ({ ...prev, name: event.target.value }))} /></label>
              <div className="form-grid two"><label>Moneda<input value={accountForm.currency} onChange={(event) => setAccountForm((prev) => ({ ...prev, currency: event.target.value }))} /></label><label>Zona horaria<input value={accountForm.timezone} onChange={(event) => setAccountForm((prev) => ({ ...prev, timezone: event.target.value }))} /></label></div>
              <div className="panel-actions"><button type="submit" className="primary" disabled={saving === "account"}>{saving === "account" ? "Guardando..." : "Guardar cuenta"}</button></div>
            </form>
          </article>
        </div>
      ) : null}

      {tab === "campaigns" ? (
        <div className="module-grid">
          <article className="panel glass-card module-card">
            <div className="panel-head"><h2>Campanas ads</h2><span>{number(campaigns.length)}</span></div>
            <div className="mini-table">{campaigns.map((campaign) => <div key={campaign.id}><strong>{campaign.name || campaign.external_campaign_id}</strong><span>{campaign.channel} / {campaign.status} / {campaign.objective}</span><p>{campaign.account_name || "Sin cuenta"} / presupuesto diario {number(campaign.daily_budget_cents)}</p></div>)}{campaigns.length === 0 ? <div className="empty">Sin campanas ads todavia.</div> : null}</div>
          </article>
          <article className="panel glass-card module-card">
            <div className="panel-head"><h2>Registrar campana</h2><span>sincronizacion manual</span></div>
            <form className="campaign-form" onSubmit={saveCampaign}>
              <label>Campaign ID<input value={campaignForm.external_campaign_id} onChange={(event) => setCampaignForm((prev) => ({ ...prev, external_campaign_id: event.target.value }))} /></label>
              <label>Nombre<input value={campaignForm.name} onChange={(event) => setCampaignForm((prev) => ({ ...prev, name: event.target.value }))} /></label>
              <div className="form-grid two">
                <label>Cuenta<select value={campaignForm.account_id} onChange={(event) => setCampaignForm((prev) => ({ ...prev, account_id: event.target.value }))}><option value="">Sin cuenta</option>{accounts.map((account) => <option key={account.id} value={account.id}>{account.name || account.external_account_id}</option>)}</select></label>
                <label>Canal<select value={campaignForm.channel} onChange={(event) => setCampaignForm((prev) => ({ ...prev, channel: event.target.value }))}><option value="facebook">Facebook</option><option value="instagram">Instagram</option></select></label>
                <label>Objetivo<input value={campaignForm.objective} onChange={(event) => setCampaignForm((prev) => ({ ...prev, objective: event.target.value }))} /></label>
                <label>Estado<select value={campaignForm.status} onChange={(event) => setCampaignForm((prev) => ({ ...prev, status: event.target.value }))}><option value="active">Activa</option><option value="paused">Pausada</option><option value="unknown">Desconocida</option></select></label>
              </div>
              <div className="panel-actions"><button type="submit" className="primary" disabled={saving === "campaign"}>{saving === "campaign" ? "Guardando..." : "Guardar campana"}</button></div>
            </form>
          </article>
        </div>
      ) : null}

      {tab === "webhooks" ? (
        <div className="ads-grid">
          <article className="panel glass-card module-card">
            <div className="panel-head"><h2>Flujo recomendado</h2><span>lead/comment to inbox</span></div>
            <div className="flow-steps vertical">
              <div><strong>Webhook Meta</strong><small>Leadgen o comment llega a `/webhooks/meta/...`.</small></div>
              <div><strong>Procesar Ads</strong><small>El boton procesa eventos y separa leads/comentarios.</small></div>
              <div><strong>CRM + Inbox</strong><small>Se crea cliente/conversacion y queda disponible para IA o humano.</small></div>
            </div>
          </article>
          <article className="panel glass-card module-card">
            <div className="panel-head"><h2>Checklist Operativo</h2><span>Meta</span></div>
            <div className="rule-list">
              <div><strong>Permisos</strong><span>pages_manage_metadata, leads_retrieval, pages_read_engagement.</span></div>
              <div><strong>Firma</strong><span>Usar HMAC en produccion para validar payloads.</span></div>
              <div><strong>Secretos</strong><span>Tokens en Secret Manager o variables de entorno, no en frontend.</span></div>
            </div>
            <div className="panel-actions"><button type="button" className="primary" onClick={onConnectMeta}>Ir a Canales</button><button type="button" onClick={processWebhooks}>Procesar ahora</button></div>
          </article>
        </div>
      ) : null}
    </section>
  );
}
