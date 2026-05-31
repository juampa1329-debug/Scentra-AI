import React, { useEffect, useMemo, useState } from "react";

const number = (value) => Number(value || 0).toLocaleString("es-CO");
const pct = (value) => `${Math.max(0, Math.min(100, Number(value || 0))).toFixed(0)}%`;
const usd = (value) => `USD ${Number(value || 0).toFixed(4)}`;
const DEFAULT_TIME_ZONE = "America/Bogota";
const TIME_ZONE_KEY = "scentra_user_timezone";

function currentUiTimeZone() {
  const candidate = String(localStorage.getItem(TIME_ZONE_KEY) || DEFAULT_TIME_ZONE).trim() || DEFAULT_TIME_ZONE;
  try {
    new Intl.DateTimeFormat("es-CO", { timeZone: candidate }).format(new Date());
    return candidate;
  } catch {
    return DEFAULT_TIME_ZONE;
  }
}

const PREDICTION_ACTIONS = [
  { key: "lead_scoring", feature: "lead_scoring_ml", label: "Lead scoring", tone: "mint" },
  { key: "churn_prediction", feature: "churn_prediction", label: "Riesgo de abandono", tone: "rose" },
  { key: "smart_remarketing", feature: "smart_remarketing", label: "Remarketing", tone: "amber" },
  { key: "operational_anomaly", feature: "ai_operational_intelligence", label: "Operacion", tone: "blue" },
];

const FEATURE_ORDER = [
  "intelligence_demo",
  "ai_premium",
  "lead_scoring_ml",
  "churn_prediction",
  "smart_remarketing",
  "ai_operational_intelligence",
  "predictive_recommendations",
  "advanced_analytics",
  "ai_advisors_premium",
  "autonomous_operations",
  "ai_self_healing",
  "ai_control_center",
  "enterprise_ai_network",
  "vertical_ai_intelligence",
  "industry_ai_models",
  "benchmark_intelligence",
  "cross_tenant_intelligence",
  "vertical_ai_advisors",
  "ai_playbook_library",
  "federated_learning",
  "federated_model_updates",
  "privacy_safe_model_aggregation",
  "global_intelligence",
  "federated_benchmarking",
  "realtime_intelligence_layer",
  "realtime_event_stream",
  "realtime_ai_alerts",
  "realtime_intelligence_dashboard",
  "multimodal_observability",
  "multimodal_cost_observability",
  "multimodal_quality_monitoring",
  "multimodal_safe_rollout",
  "multimodal_canary",
  "autonomous_revenue_engine",
  "revenue_opportunity_detection",
  "revenue_forecasting",
  "revenue_playbooks",
  "revenue_experiments",
  "enterprise_memory_network",
  "memory_graph",
  "memory_governance",
  "cross_agent_memory_routing",
  "memory_quality_scoring",
];

const MEMORY_SCOPE_OPTIONS = ["tenant", "agent", "customer", "knowledge", "workflow"];
const FEDERATED_TASK_OPTIONS = ["lead_scoring", "churn_prediction", "smart_remarketing", "operational_anomaly"];

function shortDate(value) {
  if (!value) return "-";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value).slice(0, 16);
  return parsed.toLocaleString("es-CO", { timeZone: currentUiTimeZone(), dateStyle: "short", timeStyle: "short" });
}

function asPercent(value) {
  const numeric = Number(value || 0);
  if (numeric <= 1) return pct(numeric * 100);
  return pct(numeric);
}

function modeLabel(mode) {
  const clean = String(mode || "disabled").toLowerCase();
  if (clean === "full") return "Full";
  if (clean === "demo") return "Demo";
  if (clean === "shadow") return "Shadow";
  return "Off";
}

function featureLabel(feature) {
  return feature?.label || feature?.key || "Feature";
}

function featureUsage(feature) {
  const quota = Number(feature?.quota_monthly || 0);
  const used = Number(feature?.quota_used || 0);
  if (quota <= 0) return `${number(used)} usadas`;
  return `${number(used)} / ${number(quota)}`;
}

function rolloutLabel(prediction) {
  const rollout = prediction?.output_json?.model_rollout || {};
  const mode = rollout.rollout_mode || prediction?.status || "production";
  const traffic = rollout.traffic_percent ?? 100;
  return `${mode} / ${number(traffic)}%`;
}

function predictionTitle(type) {
  return PREDICTION_ACTIONS.find((item) => item.key === type)?.label || String(type || "Prediccion");
}

function metricTitle(key) {
  return String(key || "")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function feedbackMap(rows) {
  return Object.fromEntries((rows || []).map((row) => [row.prediction_id, row]));
}

function downloadJson(payload, filename) {
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json;charset=utf-8" });
  const url = window.URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
}

export default function IntelligencePanel({ apiCall, showStatus, tenantId = "" }) {
  const [state, setState] = useState(null);
  const [overview, setOverview] = useState(null);
  const [featureRows, setFeatureRows] = useState([]);
  const [predictions, setPredictions] = useState([]);
  const [recommendations, setRecommendations] = useState([]);
  const [feedback, setFeedback] = useState([]);
  const [metrics, setMetrics] = useState([]);
  const [networkCenter, setNetworkCenter] = useState(null);
  const [operationCenter, setOperationCenter] = useState(null);
  const [realtimeCenter, setRealtimeCenter] = useState(null);
  const [multimodalCenter, setMultimodalCenter] = useState(null);
  const [multimodalRollout, setMultimodalRollout] = useState(null);
  const [revenueCenter, setRevenueCenter] = useState(null);
  const [memoryNetworkCenter, setMemoryNetworkCenter] = useState(null);
  const [federatedCenter, setFederatedCenter] = useState(null);
  const [realtimeSession, setRealtimeSession] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");

  const stateFeatures = state?.features || [];
  const featuresByKey = useMemo(() => Object.fromEntries(stateFeatures.map((item) => [item.key, item])), [stateFeatures]);
  const feedbackByPrediction = useMemo(() => feedbackMap(feedback), [feedback]);
  const visibleFeatures = useMemo(() => {
    const ordered = FEATURE_ORDER.map((key) => featuresByKey[key]).filter(Boolean);
    const extras = stateFeatures.filter((item) => !FEATURE_ORDER.includes(item.key));
    return [...ordered, ...extras];
  }, [featuresByKey, stateFeatures]);

  const enabledCount = visibleFeatures.filter((item) => item.enabled).length;
  const fullCount = visibleFeatures.filter((item) => item.mode === "full").length;
  const demoCount = visibleFeatures.filter((item) => item.mode === "demo").length;
  const openRecommendations = recommendations.filter((item) => item.status === "open").length;
  const overviewCards = overview?.cards || [];
  const summaries = overview?.executive_summaries || {};
  const observability = overview?.observability || {};
  const networkAccess = networkCenter?.access || {};
  const networkIndustry = networkCenter?.industry || {};
  const networkBenchmarks = networkCenter?.tenant_benchmarks || [];
  const networkInsights = networkCenter?.insights || [];
  const networkPlaybooks = networkCenter?.playbooks || [];
  const networkModels = networkCenter?.industry_models || [];
  const networkKnowledge = networkCenter?.knowledge_network || [];
  const networkAdvisors = networkCenter?.vertical_advisors || [];
  const realtimeAccess = realtimeCenter?.access || {};
  const realtimeMetrics = realtimeCenter?.metrics || {};
  const realtimeAlerts = realtimeCenter?.alerts || [];
  const realtimeEvents = realtimeCenter?.events || [];
  const realtimeCounts = realtimeCenter?.event_type_counts || [];
  const realtimeStream = realtimeCenter?.stream || {};
  const multimodalAccess = multimodalCenter?.access || {};
  const multimodalMetrics = multimodalCenter?.metrics || {};
  const multimodalSummary = multimodalMetrics?.summary || {};
  const multimodalProviders = multimodalMetrics?.providers || [];
  const multimodalSources = multimodalMetrics?.sources || [];
  const rolloutCenter = multimodalRollout || multimodalCenter?.rollout || {};
  const rolloutAccess = rolloutCenter?.access || {};
  const rolloutPolicy = rolloutCenter?.policy || {};
  const rolloutPolicies = rolloutCenter?.policies || [];
  const rolloutEvents = rolloutCenter?.events || [];
  const revenueAccess = revenueCenter?.access || {};
  const revenuePolicy = revenueCenter?.policy || {};
  const revenueCounts = revenueCenter?.counts || {};
  const revenueMetrics = revenueCenter?.metrics || {};
  const revenueOpportunities = revenueCenter?.opportunities || [];
  const revenueForecasts = revenueCenter?.forecasts || [];
  const revenueReports = revenueCenter?.reports || [];
  const revenuePlaybooks = revenueCenter?.playbooks || [];
  const revenueActionTypes = Array.from(new Set(revenuePlaybooks.map((item) => item.action_type).filter(Boolean)));
  const memoryAccess = memoryNetworkCenter?.access || {};
  const memoryCounts = memoryNetworkCenter?.counts || {};
  const memoryNodes = memoryNetworkCenter?.nodes || [];
  const memoryEdges = memoryNetworkCenter?.edges || [];
  const memorySyncRuns = memoryNetworkCenter?.sync_runs || [];
  const memoryRouting = memoryNetworkCenter?.routing || {};
  const memoryPolicy = memoryNetworkCenter?.policy || {};
  const federatedAccess = federatedCenter?.access || {};
  const federatedPolicy = federatedCenter?.policy || {};
  const federatedPreviews = federatedCenter?.local_previews || [];
  const federatedRounds = federatedCenter?.rounds || [];
  const federatedUpdates = federatedCenter?.updates || [];
  const federatedAggregates = federatedCenter?.aggregates || [];
  const federatedSignals = federatedCenter?.global_signals || [];
  const [controlDraft, setControlDraft] = useState({
    autonomy_level: 0,
    auto_remediation_enabled: false,
    low_risk_auto_execute: false,
    sensitivity: "medium",
    max_daily_actions: 0,
    approval_required_from_level: 2,
  });
  const [rolloutDraft, setRolloutDraft] = useState({
    feature_key: "multimodal_safe_rollout",
    modality: "all",
    provider_code: "",
    enabled: false,
    mode: "off",
    demo_enabled: true,
    canary_percent: 10,
    max_error_rate: 0.08,
    max_latency_p95_ms: 15000,
    min_quality_score: 60,
    monthly_cost_limit_cents: 0,
  });
  const [revenuePolicyDraft, setRevenuePolicyDraft] = useState({
    autonomy_level: 0,
    currency: "USD",
    revenue_goal_cents: 0,
    approval_required_min_value_cents: 0,
    max_monthly_revenue_actions: 0,
    auto_execute_low_risk: false,
    allowed_action_types_json: [],
  });
  const [memoryPolicyDraft, setMemoryPolicyDraft] = useState({
    privacy_mode: "tenant_private",
    retention_days: 365,
    auto_capture_enabled: false,
    require_review_for_customer_content: true,
    allow_cross_agent_retrieval: true,
    allowed_scopes_json: MEMORY_SCOPE_OPTIONS,
  });
  const [memoryImportText, setMemoryImportText] = useState("");
  const [federatedPolicyDraft, setFederatedPolicyDraft] = useState({
    opt_in_enabled: false,
    auto_participation_enabled: false,
    privacy_mode: "aggregate_only",
    min_local_samples: 25,
    min_cohort_tenants: 3,
    allowed_task_types_json: FEDERATED_TASK_OPTIONS,
    differential_privacy_enabled: true,
    noise_multiplier: 0,
    clipping_norm: 1,
    share_model_metrics: true,
    share_feature_importance: true,
  });
  const [federatedRoundDraft, setFederatedRoundDraft] = useState({
    task_type: "lead_scoring",
    model_key: "",
    window_key: "90d",
    min_participants: 3,
    min_total_samples: 100,
    aggregation_strategy: "weighted_average",
  });
  const opsAccess = operationCenter?.access || {};
  const opsPolicy = operationCenter?.policy || {};
  const opsCounts = operationCenter?.counts || {};
  const opsAnomalies = operationCenter?.anomalies || [];
  const opsActions = operationCenter?.actions || [];
  const opsReports = operationCenter?.reports || [];
  const opsPlaybooks = operationCenter?.playbooks || [];

  useEffect(() => {
    if (!operationCenter?.policy) return;
    setControlDraft({
      autonomy_level: Number(operationCenter.policy.autonomy_level || 0),
      auto_remediation_enabled: Boolean(operationCenter.policy.auto_remediation_enabled),
      low_risk_auto_execute: Boolean(operationCenter.policy.low_risk_auto_execute),
      sensitivity: String(operationCenter.policy.sensitivity || "medium"),
      max_daily_actions: Number(operationCenter.policy.max_daily_actions || 0),
      approval_required_from_level: Number(operationCenter.policy.approval_required_from_level || 2),
    });
  }, [operationCenter?.policy?.updated_at, tenantId]);

  useEffect(() => {
    const policy = rolloutCenter?.policy;
    if (!policy) return;
    setRolloutDraft({
      feature_key: policy.feature_key || "multimodal_safe_rollout",
      modality: policy.modality || "all",
      provider_code: policy.provider_code || "",
      enabled: Boolean(policy.enabled),
      mode: policy.mode || "off",
      demo_enabled: policy.demo_enabled !== false,
      canary_percent: Number(policy.canary_percent || 10),
      max_error_rate: Number(policy.max_error_rate || 0.08),
      max_latency_p95_ms: Number(policy.max_latency_p95_ms || 15000),
      min_quality_score: Number(policy.min_quality_score || 60),
      monthly_cost_limit_cents: Number(policy.monthly_cost_limit_cents || 0),
    });
  }, [rolloutCenter?.policy?.updated_at, tenantId]);

  useEffect(() => {
    if (!revenueCenter?.policy) return;
    const policy = revenueCenter.policy;
    setRevenuePolicyDraft({
      autonomy_level: Number(policy.autonomy_level || 0),
      currency: String(policy.currency || "USD"),
      revenue_goal_cents: Number(policy.revenue_goal_cents || 0),
      approval_required_min_value_cents: Number(policy.approval_required_min_value_cents || 0),
      max_monthly_revenue_actions: Number(policy.max_monthly_revenue_actions || 0),
      auto_execute_low_risk: Boolean(policy.auto_execute_low_risk),
      allowed_action_types_json: Array.isArray(policy.allowed_action_types_json) ? policy.allowed_action_types_json : [],
    });
  }, [revenueCenter?.policy?.updated_at, tenantId]);

  useEffect(() => {
    if (!memoryNetworkCenter?.policy) return;
    const policy = memoryNetworkCenter.policy;
    setMemoryPolicyDraft({
      privacy_mode: policy.privacy_mode || "tenant_private",
      retention_days: Number(policy.retention_days || 365),
      auto_capture_enabled: Boolean(policy.auto_capture_enabled),
      require_review_for_customer_content: policy.require_review_for_customer_content !== false,
      allow_cross_agent_retrieval: policy.allow_cross_agent_retrieval !== false,
      allowed_scopes_json: Array.isArray(policy.allowed_scopes_json) && policy.allowed_scopes_json.length
        ? policy.allowed_scopes_json
        : MEMORY_SCOPE_OPTIONS,
    });
  }, [memoryNetworkCenter?.policy?.updated_at, tenantId]);

  useEffect(() => {
    if (!federatedCenter?.policy) return;
    const policy = federatedCenter.policy;
    setFederatedPolicyDraft({
      opt_in_enabled: Boolean(policy.opt_in_enabled),
      auto_participation_enabled: Boolean(policy.auto_participation_enabled),
      privacy_mode: policy.privacy_mode || "aggregate_only",
      min_local_samples: Number(policy.min_local_samples || 25),
      min_cohort_tenants: Number(policy.min_cohort_tenants || 3),
      allowed_task_types_json: Array.isArray(policy.allowed_task_types_json) && policy.allowed_task_types_json.length
        ? policy.allowed_task_types_json
        : FEDERATED_TASK_OPTIONS,
      differential_privacy_enabled: policy.differential_privacy_enabled !== false,
      noise_multiplier: Number(policy.noise_multiplier || 0),
      clipping_norm: Number(policy.clipping_norm || 1),
      share_model_metrics: policy.share_model_metrics !== false,
      share_feature_importance: policy.share_feature_importance !== false,
    });
  }, [federatedCenter?.policy?.updated_at, tenantId]);

  const loadAll = async (silent = false) => {
    setLoading(true);
    try {
      const [overviewData, stateData, featuresData, predictionsData, recommendationsData, feedbackData, metricsData, operationsData, networkData, realtimeData, multimodalData, rolloutData, revenueData, memoryData, federatedData] = await Promise.all([
        apiCall("/saas/v1/intelligence/overview?limit=40").catch(() => ({ overview: null })),
        apiCall("/saas/v1/intelligence/state"),
        apiCall("/saas/v1/intelligence/features?limit=80").catch(() => ({ features: [] })),
        apiCall("/saas/v1/intelligence/predictions?limit=40").catch(() => ({ predictions: [] })),
        apiCall("/saas/v1/intelligence/recommendations?status=open&limit=40").catch(() => ({ recommendations: [] })),
        apiCall("/saas/v1/intelligence/feedback?limit=80").catch(() => ({ feedback: [] })),
        apiCall("/saas/v1/intelligence/model-metrics?limit=80").catch(() => ({ metrics: [] })),
        apiCall("/saas/v1/intelligence/operations/center?limit=40").catch(() => ({ center: null })),
        apiCall("/saas/v1/intelligence/network/center?limit=60").catch(() => ({ network: null })),
        apiCall("/saas/v1/intelligence/realtime/center?limit=60").catch(() => ({ center: null })),
        apiCall("/saas/v1/intelligence/multimodal/observability/center?window_key=30d&limit=20").catch(() => ({ center: null })),
        apiCall("/saas/v1/intelligence/multimodal/rollout/center").catch(() => ({ rollout: null })),
        apiCall("/saas/v1/intelligence/revenue/center?limit=60").catch(() => ({ revenue: null })),
        apiCall("/saas/v1/intelligence/memory-network/center?limit=80").catch(() => ({ memory_network: null })),
        apiCall("/saas/v1/intelligence/federated/center?limit=80").catch(() => ({ federated: null })),
      ]);
      setOverview(overviewData?.overview || null);
      setState(stateData?.state || null);
      setFeatureRows(featuresData?.features || []);
      setPredictions(predictionsData?.predictions || []);
      setRecommendations(recommendationsData?.recommendations || []);
      setFeedback(feedbackData?.feedback || []);
      setMetrics(metricsData?.metrics || []);
      setOperationCenter(operationsData?.center || null);
      setNetworkCenter(networkData?.network || null);
      setRealtimeCenter(realtimeData?.center || null);
      setMultimodalCenter(multimodalData?.center || null);
      setMultimodalRollout(rolloutData?.rollout || null);
      setRevenueCenter(revenueData?.revenue || null);
      setMemoryNetworkCenter(memoryData?.memory_network || null);
      setFederatedCenter(federatedData?.federated || null);
      if (!silent) showStatus("Inteligencia actualizada", "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadAll(true); }, [tenantId]);

  useEffect(() => {
    let sessionId = "";
    let cancelled = false;
    apiCall("/saas/v1/intelligence/realtime/sessions", {
      method: "POST",
      body: JSON.stringify({
        channel: "tenant_intelligence_panel",
        client_meta_json: { source: "IntelligencePanel", transport: "polling" },
      }),
    }).then((data) => {
      if (cancelled) return;
      sessionId = data?.session?.id || "";
      setRealtimeSession(data?.session || null);
    }).catch(() => setRealtimeSession(null));
    return () => {
      cancelled = true;
      if (sessionId) {
        apiCall(`/saas/v1/intelligence/realtime/sessions/${encodeURIComponent(sessionId)}/close`, { method: "POST" }).catch(() => {});
      }
    };
  }, [tenantId]);

  useEffect(() => {
    let cancelled = false;
    const refreshRealtime = async () => {
      try {
        const latest = realtimeCenter?.stream?.latest_event_id || "";
        const suffix = latest ? `&since_event_id=${encodeURIComponent(latest)}` : "";
        const data = await apiCall(`/saas/v1/intelligence/realtime/center?limit=60${suffix}`).catch(() => ({ center: null }));
        if (!cancelled && data?.center) {
          setRealtimeCenter((prev) => {
            const incomingEvents = data.center.events || [];
            if (!prev || !incomingEvents.length) return data.center;
            const merged = [...incomingEvents, ...(prev.events || [])];
            const seen = new Set();
            return {
              ...data.center,
              events: merged.filter((item) => {
                const key = item.id || `${item.event_type}-${item.occurred_at}`;
                if (seen.has(key)) return false;
                seen.add(key);
                return true;
              }).slice(0, 60),
            };
          });
        }
      } catch {
        /* keep background refresh quiet */
      }
    };
    const id = window.setInterval(refreshRealtime, 8000);
    return () => { cancelled = true; window.clearInterval(id); };
  }, [tenantId, realtimeCenter?.stream?.latest_event_id]);

  const recomputeFeatures = async () => {
    setBusy("features");
    try {
      const data = await apiCall("/saas/v1/intelligence/features/recompute", {
        method: "POST",
        body: JSON.stringify({ subject_type: "tenant", subject_id: "", window_key: "latest" }),
      });
      const count = Object.keys(data?.snapshot?.features || {}).length;
      showStatus(`Feature store recalculado: ${number(count)} senales`, "ok");
      await loadAll(true);
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setBusy("");
    }
  };

  const runPrediction = async (action) => {
    const feature = featuresByKey[action.feature];
    if (!feature?.enabled) {
      showStatus(`Feature no habilitada: ${featureLabel(feature || action)}`, "neutral");
      return;
    }
    setBusy(action.key);
    try {
      const data = await apiCall("/saas/v1/intelligence/predict", {
        method: "POST",
        body: JSON.stringify({ prediction_type: action.key, subject_type: "tenant", subject_id: "", window_key: "latest", persist_recommendations: true }),
      });
      const prediction = data?.prediction || {};
      const suffix = prediction.status === "shadow" ? " en modo shadow" : "";
      showStatus(`${predictionTitle(action.key)} generado${suffix}`, prediction.status === "shadow" ? "neutral" : "ok");
      await loadAll(true);
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setBusy("");
    }
  };

  const submitFeedback = async (prediction, isCorrect) => {
    setBusy(`feedback-${prediction.id}`);
    try {
      await apiCall(`/saas/v1/intelligence/predictions/${encodeURIComponent(prediction.id)}/feedback`, {
        method: "POST",
        body: JSON.stringify({
          feedback_type: "outcome",
          actual_label: isCorrect ? prediction.label || "" : "needs_review",
          actual_score: isCorrect ? Number(prediction.score || 0) : null,
          is_correct: isCorrect,
          outcome_json: { source: "tenant_intelligence_panel" },
          notes: "Feedback desde panel tenant Intelligence",
        }),
      });
      showStatus("Feedback predictivo guardado", "ok");
      await loadAll(true);
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setBusy("");
    }
  };

  const dismissRecommendation = async (item) => {
    setBusy(`dismiss-${item.id}`);
    try {
      await apiCall(`/saas/v1/intelligence/recommendations/${encodeURIComponent(item.id)}/dismiss`, { method: "POST" });
      showStatus("Recomendacion descartada", "ok");
      await loadAll(true);
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setBusy("");
    }
  };

  const markRealtimeCursor = async () => {
    const latest = realtimeCenter?.stream?.latest_event_id || realtimeEvents[0]?.id || "";
    if (!latest) return;
    setBusy("realtime-cursor");
    try {
      const data = await apiCall("/saas/v1/intelligence/realtime/cursor", {
        method: "PATCH",
        body: JSON.stringify({ cursor_key: "default", last_event_id: latest, filters_json: { source: "IntelligencePanel" } }),
      });
      setRealtimeCenter((prev) => prev ? { ...prev, stream: { ...(prev.stream || {}), cursor: data?.cursor || prev.stream?.cursor } } : prev);
      showStatus("Cursor realtime actualizado", "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setBusy("");
    }
  };

  const refreshEnterpriseNetwork = async (dryRun = false) => {
    setBusy(dryRun ? "network-preview" : "network-refresh");
    try {
      const data = await apiCall("/saas/v1/intelligence/network/refresh", {
        method: "POST",
        body: JSON.stringify({ dry_run: dryRun, limit: 60 }),
      });
      setNetworkCenter(data?.network || null);
      const result = data?.result || {};
      const insights = (result.insights || []).length;
      const message = dryRun
        ? `Preview vertical: ${number(insights)} insights`
        : `Red AI actualizada: ${number(insights)} insights`;
      showStatus(message, "ok");
      await loadAll(true);
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setBusy("");
    }
  };

  const runRevenueAnalysis = async (dryRun = false) => {
    setBusy(dryRun ? "revenue-preview" : "revenue-analyze");
    try {
      const data = await apiCall("/saas/v1/intelligence/revenue/analyze", {
        method: "POST",
        body: JSON.stringify({ dry_run: dryRun, limit: 60 }),
      });
      setRevenueCenter(data?.revenue || null);
      const result = data?.result || {};
      const total = dryRun ? (result.candidate_opportunities || []).length : (result.created_opportunities || []).length;
      showStatus(dryRun ? `Preview revenue: ${number(total)} oportunidades` : `Revenue actualizado: ${number(total)} oportunidades`, "ok");
      await loadAll(true);
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setBusy("");
    }
  };

  const actOnRevenueOpportunity = async (opportunity, action) => {
    const id = opportunity?.id || "";
    if (!id) return;
    setBusy(`revenue-${action}-${id}`);
    try {
      await apiCall(`/saas/v1/intelligence/revenue/opportunities/${encodeURIComponent(id)}/${action}`, {
        method: "POST",
        body: JSON.stringify({ dry_run: false, notes: "Accion desde IntelligencePanel" }),
      });
      showStatus(action === "approve" ? "Oportunidad aprobada" : action === "execute" ? "Oportunidad marcada como ejecutada" : "Oportunidad descartada", "ok");
      await loadAll(true);
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setBusy("");
    }
  };

  const toggleRevenueActionType = (actionType) => {
    setRevenuePolicyDraft((prev) => {
      const current = new Set(prev.allowed_action_types_json || []);
      if (current.has(actionType)) current.delete(actionType);
      else current.add(actionType);
      return { ...prev, allowed_action_types_json: Array.from(current) };
    });
  };

  const saveRevenuePolicy = async () => {
    setBusy("revenue-policy");
    try {
      const payload = {
        ...revenuePolicyDraft,
        autonomy_level: Number(revenuePolicyDraft.autonomy_level || 0),
        revenue_goal_cents: Number(revenuePolicyDraft.revenue_goal_cents || 0),
        approval_required_min_value_cents: Number(revenuePolicyDraft.approval_required_min_value_cents || 0),
        max_monthly_revenue_actions: Number(revenuePolicyDraft.max_monthly_revenue_actions || 0),
        currency: String(revenuePolicyDraft.currency || "USD").trim().toUpperCase() || "USD",
      };
      const data = await apiCall("/saas/v1/intelligence/revenue/policy", {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
      setRevenueCenter((prev) => prev ? { ...prev, policy: data?.policy || prev.policy } : prev);
      showStatus("Politica Revenue AI guardada", "ok");
      await loadAll(true);
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setBusy("");
    }
  };

  const syncMemoryNetwork = async (dryRun = false) => {
    setBusy(dryRun ? "memory-preview" : "memory-sync");
    try {
      const data = await apiCall("/saas/v1/intelligence/memory-network/sync", {
        method: "POST",
        body: JSON.stringify({ dry_run: dryRun, limit: 80, source_types: [] }),
      });
      setMemoryNetworkCenter(data?.memory_network || null);
      const result = data?.result || {};
      const total = dryRun ? (result.candidate_nodes || []).length : (result.created_nodes || []).length + (result.updated_nodes || []).length;
      showStatus(dryRun ? `Preview memoria: ${number(total)} nodos` : `Memoria sincronizada: ${number(total)} nodos`, "ok");
      await loadAll(true);
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setBusy("");
    }
  };

  const reviewMemoryNode = async (node, status) => {
    const id = node?.id || "";
    if (!id) return;
    setBusy(`memory-${status}-${id}`);
    try {
      await apiCall(`/saas/v1/intelligence/memory-network/nodes/${encodeURIComponent(id)}/review`, {
        method: "POST",
        body: JSON.stringify({ status, notes: "Revision desde IntelligencePanel" }),
      });
      showStatus(status === "published" ? "Memoria publicada" : status === "archived" ? "Memoria archivada" : "Memoria revisada", "ok");
      await loadAll(true);
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setBusy("");
    }
  };

  const toggleMemoryScope = (scope) => {
    setMemoryPolicyDraft((prev) => {
      const current = Array.isArray(prev.allowed_scopes_json) ? prev.allowed_scopes_json : [];
      const next = current.includes(scope) ? current.filter((item) => item !== scope) : [...current, scope];
      return { ...prev, allowed_scopes_json: next.length ? next : ["tenant"] };
    });
  };

  const saveMemoryPolicy = async () => {
    setBusy("memory-policy");
    try {
      const data = await apiCall("/saas/v1/intelligence/memory-network/policy", {
        method: "PATCH",
        body: JSON.stringify({
          ...memoryPolicyDraft,
          retention_days: Number(memoryPolicyDraft.retention_days || 365),
          allowed_scopes_json: memoryPolicyDraft.allowed_scopes_json?.length ? memoryPolicyDraft.allowed_scopes_json : ["tenant"],
        }),
      });
      setMemoryNetworkCenter((prev) => prev ? { ...prev, policy: data?.policy || prev.policy } : prev);
      showStatus("Politica de memoria guardada", "ok");
      await loadAll(true);
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setBusy("");
    }
  };

  const exportMemoryNetwork = async () => {
    setBusy("memory-export");
    try {
      const data = await apiCall("/saas/v1/intelligence/memory-network/export?include_archived=true&limit=300");
      const exported = data?.export || {};
      downloadJson(exported, `scentra-memory-network-${Date.now()}.json`);
      showStatus(`Export de memoria listo: ${number((exported.nodes || []).length)} nodos`, "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setBusy("");
    }
  };

  const importMemoryNetwork = async (dryRun = true) => {
    setBusy(dryRun ? "memory-import-preview" : "memory-import");
    try {
      const parsed = JSON.parse(memoryImportText || "[]");
      const nodes = Array.isArray(parsed) ? parsed : parsed.nodes_json || parsed.nodes || [];
      if (!Array.isArray(nodes)) throw new Error("El JSON debe ser un array o contener nodes/nodes_json.");
      const data = await apiCall("/saas/v1/intelligence/memory-network/import", {
        method: "POST",
        body: JSON.stringify({ dry_run: dryRun, nodes_json: nodes }),
      });
      setMemoryNetworkCenter(data?.memory_network || memoryNetworkCenter);
      const result = data?.result || {};
      const total = dryRun ? (result.candidate_nodes || []).length : (result.created_nodes || []).length + (result.updated_nodes || []).length;
      showStatus(dryRun ? `Preview import: ${number(total)} nodos` : `Memoria importada: ${number(total)} nodos`, "ok");
      if (!dryRun) await loadAll(true);
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setBusy("");
    }
  };

  const deleteMemoryNode = async (node) => {
    const id = node?.id || "";
    if (!id) return;
    const ok = window.confirm(`Se borrara la memoria "${node.title || id}". Esta accion elimina sus relaciones del grafo. Continuar?`);
    if (!ok) return;
    setBusy(`memory-delete-${id}`);
    try {
      await apiCall(`/saas/v1/intelligence/memory-network/nodes/${encodeURIComponent(id)}?reason=${encodeURIComponent("Borrado desde IntelligencePanel")}`, {
        method: "DELETE",
      });
      showStatus("Memoria borrada", "ok");
      await loadAll(true);
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setBusy("");
    }
  };

  const toggleFederatedTask = (taskType) => {
    setFederatedPolicyDraft((prev) => {
      const current = Array.isArray(prev.allowed_task_types_json) ? prev.allowed_task_types_json : [];
      const next = current.includes(taskType) ? current.filter((item) => item !== taskType) : [...current, taskType];
      return { ...prev, allowed_task_types_json: next.length ? next : ["lead_scoring"] };
    });
  };

  const saveFederatedPolicy = async () => {
    setBusy("federated-policy");
    try {
      const payload = {
        ...federatedPolicyDraft,
        min_local_samples: Number(federatedPolicyDraft.min_local_samples || 25),
        min_cohort_tenants: Number(federatedPolicyDraft.min_cohort_tenants || 3),
        noise_multiplier: Number(federatedPolicyDraft.noise_multiplier || 0),
        clipping_norm: Number(federatedPolicyDraft.clipping_norm || 1),
        allowed_task_types_json: federatedPolicyDraft.allowed_task_types_json?.length ? federatedPolicyDraft.allowed_task_types_json : ["lead_scoring"],
      };
      const data = await apiCall("/saas/v1/intelligence/federated/policy", {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
      setFederatedCenter(data?.federated || null);
      showStatus(payload.opt_in_enabled ? "Federated Learning habilitado por opt-in" : "Federated Learning deshabilitado", "ok");
      await loadAll(true);
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setBusy("");
    }
  };

  const prepareFederatedRound = async (dryRun = true) => {
    setBusy(dryRun ? "federated-preview" : "federated-prepare");
    try {
      const data = await apiCall("/saas/v1/intelligence/federated/rounds/prepare", {
        method: "POST",
        body: JSON.stringify({
          ...federatedRoundDraft,
          dry_run: dryRun,
          min_participants: Number(federatedRoundDraft.min_participants || 3),
          min_total_samples: Number(federatedRoundDraft.min_total_samples || 100),
        }),
      });
      setFederatedCenter(data?.federated || federatedCenter);
      const local = data?.result?.local_update || {};
      const blockers = local.blockers || [];
      const message = dryRun
        ? `Preview federado: ${number(local.sample_count || 0)} muestras${blockers.length ? ` / bloqueos: ${blockers.join(", ")}` : ""}`
        : `Ronda federada preparada: ${number(local.sample_count || 0)} muestras`;
      showStatus(message, blockers.length ? "neutral" : "ok");
      if (!dryRun) await loadAll(true);
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setBusy("");
    }
  };

  const submitFederatedUpdate = async (round, dryRun = true) => {
    const id = round?.id || "";
    if (!id) return;
    setBusy(`${dryRun ? "federated-submit-preview" : "federated-submit"}-${id}`);
    try {
      const data = await apiCall(`/saas/v1/intelligence/federated/rounds/${encodeURIComponent(id)}/submit-update`, {
        method: "POST",
        body: JSON.stringify({ dry_run: dryRun }),
      });
      setFederatedCenter(data?.federated || federatedCenter);
      const local = data?.result?.local_update || {};
      const blockers = local.blockers || [];
      showStatus(dryRun ? `Preview update: ${number(local.sample_count || 0)} muestras` : "Update federado enviado", blockers.length ? "neutral" : "ok");
      if (!dryRun) await loadAll(true);
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setBusy("");
    }
  };

  const aggregateFederatedRound = async (round, dryRun = true) => {
    const id = round?.id || "";
    if (!id) return;
    setBusy(`${dryRun ? "federated-aggregate-preview" : "federated-aggregate"}-${id}`);
    try {
      const data = await apiCall(`/saas/v1/intelligence/federated/rounds/${encodeURIComponent(id)}/aggregate`, {
        method: "POST",
        body: JSON.stringify({ dry_run: dryRun, notes: "Agregacion desde IntelligencePanel" }),
      });
      setFederatedCenter(data?.federated || federatedCenter);
      const result = data?.result || {};
      showStatus(
        dryRun
          ? `Preview agregado: ${number(result.participant_count || 0)} tenants / ${number(result.total_samples || 0)} muestras`
          : `Agregado federado ${result.status || "calculado"}`,
        result.status === "insufficient_sample" ? "neutral" : "ok",
      );
      if (!dryRun) await loadAll(true);
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setBusy("");
    }
  };

  const runOperationsAnalysis = async (dryRun = false) => {
    setBusy(dryRun ? "ops-dry-run" : "ops-analyze");
    try {
      const data = await apiCall("/saas/v1/intelligence/operations/analyze", {
        method: "POST",
        body: JSON.stringify({ dry_run: dryRun, limit: 60 }),
      });
      setOperationCenter(data?.center || null);
      const result = data?.result || {};
      const created = (result.created_anomalies || []).length;
      const candidates = (result.candidate_anomalies || []).length;
      showStatus(dryRun ? `Preview autonomo: ${number(candidates)} senales` : `Analisis autonomo: ${number(created)} anomalias`, "ok");
      await loadAll(true);
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setBusy("");
    }
  };

  const saveControlPolicy = async () => {
    setBusy("ops-policy");
    try {
      const data = await apiCall("/saas/v1/intelligence/operations/control", {
        method: "PATCH",
        body: JSON.stringify({ ...controlDraft, settings_json: {} }),
      });
      showStatus(`Control AI actualizado a nivel ${number(data?.policy?.autonomy_level || 0)}`, "ok");
      await loadAll(true);
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setBusy("");
    }
  };

  const approveOperationAction = async (action) => {
    setBusy(`ops-approve-${action.id}`);
    try {
      await apiCall(`/saas/v1/intelligence/operations/actions/${encodeURIComponent(action.id)}/approve`, { method: "POST" });
      showStatus("Accion AI aprobada", "ok");
      await loadAll(true);
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setBusy("");
    }
  };

  const executeOperationAction = async (action, dryRun = false) => {
    setBusy(`ops-execute-${action.id}`);
    try {
      await apiCall(`/saas/v1/intelligence/operations/actions/${encodeURIComponent(action.id)}/execute`, {
        method: "POST",
        body: JSON.stringify({ dry_run: dryRun }),
      });
      showStatus(dryRun ? "Dry-run de accion AI registrado" : "Accion AI ejecutada de forma controlada", "ok");
      await loadAll(true);
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setBusy("");
    }
  };

  const dismissOperationAction = async (action) => {
    setBusy(`ops-dismiss-${action.id}`);
    try {
      await apiCall(`/saas/v1/intelligence/operations/actions/${encodeURIComponent(action.id)}/dismiss`, { method: "POST" });
      showStatus("Accion AI descartada", "ok");
      await loadAll(true);
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setBusy("");
    }
  };

  const refreshMultimodalObservability = async (dryRun = true) => {
    setBusy(dryRun ? "multimodal-preview" : "multimodal-refresh");
    try {
      const data = await apiCall("/saas/v1/intelligence/multimodal/observability/refresh", {
        method: "POST",
        body: JSON.stringify({ window_key: "30d", dry_run: dryRun, limit: 20 }),
      });
      setMultimodalCenter(data?.center || null);
      const total = data?.result?.metrics?.summary?.request_count || 0;
      showStatus(dryRun ? `Preview multimodal: ${number(total)} eventos` : data?.result?.persisted ? "Observabilidad multimodal persistida" : "Snapshot calculado; requiere modo full para persistir", "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setBusy("");
    }
  };

  const saveMultimodalRolloutPolicy = async (event) => {
    event.preventDefault();
    setBusy("multimodal-rollout");
    try {
      const data = await apiCall("/saas/v1/intelligence/multimodal/rollout/policy", {
        method: "PATCH",
        body: JSON.stringify({
          ...rolloutDraft,
          enabled: Boolean(rolloutDraft.enabled) && rolloutDraft.mode !== "off",
          canary_percent: Number(rolloutDraft.canary_percent || 0),
          max_error_rate: Number(rolloutDraft.max_error_rate || 0),
          max_latency_p95_ms: Number(rolloutDraft.max_latency_p95_ms || 0),
          min_quality_score: Number(rolloutDraft.min_quality_score || 0),
          monthly_cost_limit_cents: Number(rolloutDraft.monthly_cost_limit_cents || 0),
        }),
      });
      setMultimodalRollout(data?.rollout || null);
      showStatus("Policy de rollout multimodal actualizada", "ok");
    } catch (err) {
      showStatus(String(err.message || err), "error");
    } finally {
      setBusy("");
    }
  };

  return (
    <section className="module-page intelligence-page">
      <div className="hero-card glass-card">
        <div>
          <p className="eyebrow">Scentra Intelligence Engine</p>
          <h2>AI predictivo</h2>
          <p>Predicciones, recomendaciones, feature store y feedback de modelos para la empresa activa.</p>
        </div>
        <div className="row-actions">
          <button type="button" onClick={() => loadAll(false)} disabled={loading}>Actualizar</button>
          <button type="button" className="primary" onClick={recomputeFeatures} disabled={busy === "features"}>{busy === "features" ? "Calculando..." : "Recalcular features"}</button>
        </div>
      </div>

      <div className="metric-grid">
        <article className="metric-card mint"><span>Features activas</span><strong>{number(enabledCount)}</strong><small>{number(fullCount)} full / {number(demoCount)} demo</small></article>
        <article className="metric-card blue"><span>Predicciones</span><strong>{number(predictions.length)}</strong><small>ultimas generadas</small></article>
        <article className="metric-card amber"><span>Recomendaciones</span><strong>{number(openRecommendations)}</strong><small>abiertas</small></article>
        <article className="metric-card violet"><span>ModelOps</span><strong>{number(metrics.length)}</strong><small>{number(observability.fallback_count || 0)} fallback / {number(observability.shadow_count || 0)} shadow</small></article>
        <article className="metric-card teal"><span>AI Operations</span><strong>{number(opsCounts.open_anomalies || 0)}</strong><small>{number(opsCounts.pending_actions || 0)} acciones pendientes</small></article>
        <article className="metric-card blue"><span>Vertical AI</span><strong>{networkIndustry.label || "General"}</strong><small>{number(networkInsights.length)} insights / {number(networkBenchmarks.length)} benchmarks</small></article>
        <article className="metric-card mint"><span>Realtime AI</span><strong>{String(realtimeMetrics.status || "off").toUpperCase()}</strong><small>{number(realtimeMetrics.events_15m || 0)} eventos 15m / {number(realtimeAlerts.length)} alertas</small></article>
        <article className="metric-card teal"><span>Multimodal</span><strong>{number(multimodalSummary.request_count || 0)}</strong><small>{usd(multimodalSummary.estimated_cost_usd || 0)} / {rolloutPolicy.mode || "off"}</small></article>
        <article className="metric-card amber"><span>Revenue AI</span><strong>{number(revenueCounts.open_opportunities || 0)}</strong><small>{revenueAccess.mode || "off"} / {number(revenueCounts.estimated_open_value_cents || 0)} cents</small></article>
        <article className="metric-card violet"><span>Memory Network</span><strong>{number(memoryCounts.nodes || 0)}</strong><small>{number(memoryCounts.published_nodes || 0)} publicadas / {number(memoryEdges.length)} edges</small></article>
        <article className="metric-card mint"><span>Federated Learning</span><strong>{federatedPolicy.opt_in_enabled ? "OPT-IN" : "OFF"}</strong><small>{number(federatedUpdates.length)} updates / {number(federatedAggregates.length)} agregados</small></article>
      </div>

      <section className="predictive-board">
        <article className="panel glass-card predictive-summary">
          <div className="panel-head">
            <div>
              <h2>Phase 24.9 Observability</h2>
              <span>{multimodalAccess.mode || "disabled"} / costo, latencia, errores, calidad y fuentes</span>
            </div>
            <div className="row-actions">
              <button type="button" onClick={() => refreshMultimodalObservability(true)} disabled={busy === "multimodal-preview"}>{busy === "multimodal-preview" ? "Calculando..." : "Preview"}</button>
              <button type="button" className="primary" onClick={() => refreshMultimodalObservability(false)} disabled={busy === "multimodal-refresh"}>{busy === "multimodal-refresh" ? "Guardando..." : "Persistir snapshot"}</button>
            </div>
          </div>
          <div className="predictive-card-grid">
            <div className="predictive-card lead_scoring"><span>Requests 30d</span><strong>{number(multimodalSummary.request_count || 0)}</strong><small>{number(multimodalSummary.error_count || 0)} errores</small></div>
            <div className="predictive-card smart_remarketing"><span>Costo estimado</span><strong>{usd(multimodalSummary.estimated_cost_usd || 0)}</strong><small>precios Admin</small></div>
            <div className="predictive-card operational_anomaly"><span>P95 latencia</span><strong>{number(multimodalSummary.p95_latency_ms || 0)} ms</strong><small>promedio {number(multimodalSummary.avg_latency_ms || 0)} ms</small></div>
            <div className="predictive-card churn_prediction"><span>Calidad</span><strong>{number(multimodalSummary.avg_quality_score || 0)}</strong><small>{number(multimodalSummary.approved_source_count || 0)} fuentes aprobadas</small></div>
          </div>
          <div className="mini-table intelligence-list">
            {multimodalProviders.slice(0, 8).map((item, index) => (
              <div key={`${item.modality}-${item.provider_code || item.tool_code}-${item.model || index}`} className={`intelligence-row-card ${item.status || ""}`}>
                <div>
                  <strong>{item.modality} / {item.provider_code || item.tool_code || "internal"}</strong>
                  <span>{number(item.request_count)} requests / {number(item.error_count)} errores / {usd(Number(item.estimated_cost_cents || 0) / 100)}</span>
                  <p>Latencia p95 {number(item.p95_latency_ms || 0)} ms, calidad {number(item.avg_quality_score || 0)}, fuentes aprobadas {number(item.approved_source_count || 0)}.</p>
                </div>
                <small>{item.status || "ok"}</small>
              </div>
            ))}
            {!multimodalProviders.length ? <div className="empty">Activa Multimodal Observability para ver snapshots de voz, vision, busqueda, herramientas y memoria.</div> : null}
          </div>
        </article>

        <article className="panel glass-card predictive-cards">
          <div className="panel-head">
            <div>
              <h2>Phase 24.10 Safe Rollout</h2>
              <span>{rolloutAccess.mode || "disabled"} / {rolloutPolicy.mode || "off"}</span>
            </div>
          </div>
          <form className="crm-mini-form" onSubmit={saveMultimodalRolloutPolicy}>
            <label>Feature<input value={rolloutDraft.feature_key} onChange={(event) => setRolloutDraft((prev) => ({ ...prev, feature_key: event.target.value }))} /></label>
            <label>Modalidad<select value={rolloutDraft.modality} onChange={(event) => setRolloutDraft((prev) => ({ ...prev, modality: event.target.value }))}><option value="all">all</option><option value="voice">voice</option><option value="vision">vision</option><option value="web_search">web_search</option><option value="image_search">image_search</option><option value="mixed_search">mixed_search</option><option value="agent_tool">agent_tool</option><option value="memory">memory</option></select></label>
            <label>Proveedor<input value={rolloutDraft.provider_code} placeholder="opcional" onChange={(event) => setRolloutDraft((prev) => ({ ...prev, provider_code: event.target.value }))} /></label>
            <label>Modo<select value={rolloutDraft.mode} onChange={(event) => setRolloutDraft((prev) => ({ ...prev, mode: event.target.value, enabled: event.target.value !== "off" }))}><option value="off">off</option><option value="demo">demo</option><option value="canary">canary</option><option value="full">full</option></select></label>
            <label>Canary %<input type="number" min="0" max="100" value={rolloutDraft.canary_percent} onChange={(event) => setRolloutDraft((prev) => ({ ...prev, canary_percent: event.target.value }))} /></label>
            <label>P95 max ms<input type="number" min="0" value={rolloutDraft.max_latency_p95_ms} onChange={(event) => setRolloutDraft((prev) => ({ ...prev, max_latency_p95_ms: event.target.value }))} /></label>
            <label>Error max<input type="number" min="0" max="1" step="0.01" value={rolloutDraft.max_error_rate} onChange={(event) => setRolloutDraft((prev) => ({ ...prev, max_error_rate: event.target.value }))} /></label>
            <label>Calidad min<input type="number" min="0" max="100" value={rolloutDraft.min_quality_score} onChange={(event) => setRolloutDraft((prev) => ({ ...prev, min_quality_score: event.target.value }))} /></label>
            <label className="check-row"><input type="checkbox" checked={rolloutDraft.demo_enabled} onChange={(event) => setRolloutDraft((prev) => ({ ...prev, demo_enabled: event.target.checked }))} />Fallback demo fuera del canary</label>
            <button type="submit" className="primary" disabled={busy === "multimodal-rollout"}>{busy === "multimodal-rollout" ? "Guardando..." : "Guardar rollout"}</button>
          </form>
          <div className="mini-table intelligence-list compact">
            {rolloutEvents.slice(0, 5).map((event) => (
              <div key={event.id}>
                <strong>{event.decision} / {event.mode}</strong>
                <span>{event.modality} / bucket {number(event.canary_bucket)} de {number(event.canary_percent)}</span>
                <small>{event.reason} / {shortDate(event.created_at)}</small>
              </div>
            ))}
            {!rolloutPolicies.length ? <div className="empty">Sin policies activas. El rollout seguro esta apagado por defecto y no altera el runtime actual.</div> : null}
          </div>
          <div className="mini-table intelligence-list compact">
            {multimodalSources.slice(0, 5).map((source) => (
              <div key={source.source}>
                <strong>{source.source}</strong>
                <span>{number(source.approved)} aprobadas / {number(source.blocked)} bloqueadas</span>
                <small>{shortDate(source.last_seen_at)}</small>
              </div>
            ))}
          </div>
        </article>
      </section>

      <section className="predictive-board">
        <article className="panel glass-card predictive-summary">
          <div className="panel-head">
            <div>
              <h2>Autonomous Revenue Engine</h2>
              <span>{revenueAccess.mode || "disabled"} / Human approval</span>
            </div>
            <div className="row-actions">
              <button type="button" onClick={() => runRevenueAnalysis(true)} disabled={busy === "revenue-preview"}>{busy === "revenue-preview" ? "Simulando..." : "Vista previa"}</button>
              <button type="button" className="primary" onClick={() => runRevenueAnalysis(false)} disabled={busy === "revenue-analyze"}>{busy === "revenue-analyze" ? "Analizando..." : "Analizar revenue"}</button>
            </div>
          </div>
          <div className="predictive-card-grid">
            <div className="predictive-card lead_scoring"><span>Leads calientes</span><strong>{number(revenueMetrics.hot_leads || 0)}</strong><small>{number(revenueMetrics.conversations || 0)} conversaciones</small></div>
            <div className="predictive-card smart_remarketing"><span>Pagos pendientes</span><strong>{number(revenueMetrics.pending_payments || 0)}</strong><small>desde CRM</small></div>
            <div className="predictive-card churn_prediction"><span>Inactivos 14d</span><strong>{number(revenueMetrics.inactive_14d || 0)}</strong><small>candidatos winback</small></div>
          </div>
          <div className="agent-editor-grid two">
            <label>Nivel revenue
              <select value={revenuePolicyDraft.autonomy_level} onChange={(event) => setRevenuePolicyDraft((prev) => ({ ...prev, autonomy_level: Number(event.target.value) }))}>
                {[0, 1, 2, 3, 4].map((level) => <option key={level} value={level}>Level {level}</option>)}
              </select>
            </label>
            <label>Moneda
              <input value={revenuePolicyDraft.currency} onChange={(event) => setRevenuePolicyDraft((prev) => ({ ...prev, currency: event.target.value }))} />
            </label>
            <label>Meta revenue cents
              <input type="number" min="0" value={revenuePolicyDraft.revenue_goal_cents} onChange={(event) => setRevenuePolicyDraft((prev) => ({ ...prev, revenue_goal_cents: Number(event.target.value || 0) }))} />
            </label>
            <label>Max acciones/mes
              <input type="number" min="0" value={revenuePolicyDraft.max_monthly_revenue_actions} onChange={(event) => setRevenuePolicyDraft((prev) => ({ ...prev, max_monthly_revenue_actions: Number(event.target.value || 0) }))} />
            </label>
          </div>
          {revenueActionTypes.length ? (
            <div className="mini-table intelligence-list compact">
              <div>
                <strong>Action types permitidos</strong>
                <span>{revenuePolicyDraft.allowed_action_types_json.length ? revenuePolicyDraft.allowed_action_types_json.join(", ") : "Todos los playbooks control-plane"}</span>
                <small>Si seleccionas tipos, approve/execute solo permite esos action types.</small>
              </div>
              <div className="row-actions">
                {revenueActionTypes.map((actionType) => (
                  <button
                    key={actionType}
                    type="button"
                    className={(revenuePolicyDraft.allowed_action_types_json || []).includes(actionType) ? "primary" : ""}
                    onClick={() => toggleRevenueActionType(actionType)}
                  >
                    {actionType}
                  </button>
                ))}
              </div>
            </div>
          ) : null}
          <div className="panel-actions">
            <button type="button" onClick={saveRevenuePolicy} disabled={busy === "revenue-policy"}>{busy === "revenue-policy" ? "Guardando..." : "Guardar politica Revenue AI"}</button>
            <span className="field-hint">Execution sigue siendo solo registro control-plane: no envia mensajes, no cobra y no activa campanas.</span>
          </div>
          <div className="mini-table intelligence-list">
            {revenueOpportunities.slice(0, 8).map((item) => (
              <div key={item.id} className={`intelligence-row-card ${item.status || ""}`}>
                <div>
                  <strong>{item.title}</strong>
                  <span>{item.category} / {item.status} / score {number(item.priority_score)}</span>
                  <p>{item.description}</p>
                </div>
                <div className="row-actions">
                  {item.status === "suggested" ? <button type="button" onClick={() => actOnRevenueOpportunity(item, "approve")} disabled={busy === `revenue-approve-${item.id}`}>Aprobar</button> : null}
                  {item.status === "approved" ? <button type="button" className="primary" onClick={() => actOnRevenueOpportunity(item, "execute")} disabled={busy === `revenue-execute-${item.id}`}>Marcar ejecutada</button> : null}
                  {!["executed", "dismissed"].includes(item.status) ? <button type="button" onClick={() => actOnRevenueOpportunity(item, "dismiss")} disabled={busy === `revenue-dismiss-${item.id}`}>Descartar</button> : null}
                </div>
              </div>
            ))}
            {!revenueOpportunities.length ? <div className="empty">Ejecuta vista previa o analisis para detectar oportunidades comerciales.</div> : null}
          </div>
        </article>

        <article className="panel glass-card predictive-cards">
          <div className="panel-head"><h2>Revenue playbooks y forecasts</h2><span>{number(revenuePlaybooks.length)} playbooks</span></div>
          <div className="mini-table intelligence-list compact">
            {revenueForecasts.slice(0, 4).map((item) => (
              <div key={item.id}>
                <strong>{item.forecast_type}</strong>
                <span>{number(item.forecast_value_cents)} cents / {item.currency}</span>
                <small>confianza {asPercent(item.confidence)}</small>
              </div>
            ))}
            {revenueReports.slice(0, 3).map((item) => (
              <div key={item.id}>
                <strong>{item.title}</strong>
                <span>score {number(item.score)}</span>
                <small>{item.summary}</small>
              </div>
            ))}
            {!revenueForecasts.length && !revenueReports.length ? <div className="empty">Sin forecast/report aun. El motor no inventa valores si no hay datos comerciales.</div> : null}
          </div>
        </article>
      </section>

      <section className="predictive-board">
        <article className="panel glass-card predictive-summary">
          <div className="panel-head">
            <div>
              <h2>AI Enterprise Memory Network</h2>
              <span>{memoryAccess.mode || "disabled"} / {memoryRouting.privacy_mode || "tenant_private"}</span>
            </div>
            <div className="row-actions">
              <button type="button" onClick={() => syncMemoryNetwork(true)} disabled={busy === "memory-preview"}>{busy === "memory-preview" ? "Simulando..." : "Vista previa"}</button>
              <button type="button" className="primary" onClick={() => syncMemoryNetwork(false)} disabled={busy === "memory-sync"}>{busy === "memory-sync" ? "Sincronizando..." : "Sincronizar memoria"}</button>
            </div>
          </div>
          <div className="predictive-card-grid">
            <div className="predictive-card lead_scoring"><span>Nodos</span><strong>{number(memoryCounts.nodes || 0)}</strong><small>{number(memoryCounts.candidate_nodes || 0)} pendientes</small></div>
            <div className="predictive-card smart_remarketing"><span>Publicadas</span><strong>{number(memoryCounts.published_nodes || 0)}</strong><small>{memoryRouting.cross_agent_memory_routing ? "routing multiagente" : "routing limitado"}</small></div>
            <div className="predictive-card operational_anomaly"><span>Contenido cliente</span><strong>{number(memoryCounts.customer_content_nodes || 0)}</strong><small>{memoryRouting.requires_review_for_customer_content ? "requiere revision" : "politica flexible"}</small></div>
          </div>
          <div className="agent-editor-grid two">
            <label>Privacidad
              <select value={memoryPolicyDraft.privacy_mode} onChange={(event) => setMemoryPolicyDraft((prev) => ({ ...prev, privacy_mode: event.target.value }))}>
                <option value="tenant_private">tenant_private</option>
                <option value="tenant_restricted">tenant_restricted</option>
                <option value="aggregate_only">aggregate_only</option>
              </select>
            </label>
            <label>Retencion dias
              <input type="number" min="1" max="3650" value={memoryPolicyDraft.retention_days} onChange={(event) => setMemoryPolicyDraft((prev) => ({ ...prev, retention_days: Number(event.target.value || 365) }))} />
            </label>
          </div>
          <div className="mini-table intelligence-list compact">
            <div>
              <strong>Scopes permitidos</strong>
              <span>{(memoryPolicyDraft.allowed_scopes_json || []).join(", ") || "tenant"}</span>
              <small>La sincronizacion y publicacion respetan esta politica.</small>
            </div>
            <div className="row-actions">
              {MEMORY_SCOPE_OPTIONS.map((scope) => (
                <button
                  key={scope}
                  type="button"
                  className={(memoryPolicyDraft.allowed_scopes_json || []).includes(scope) ? "primary" : ""}
                  onClick={() => toggleMemoryScope(scope)}
                >
                  {scope}
                </button>
              ))}
            </div>
          </div>
          <div className="agent-editor-grid two">
            <label className="check-row"><input type="checkbox" checked={memoryPolicyDraft.require_review_for_customer_content} onChange={(event) => setMemoryPolicyDraft((prev) => ({ ...prev, require_review_for_customer_content: event.target.checked }))} />Revision obligatoria para clientes</label>
            <label className="check-row"><input type="checkbox" checked={memoryPolicyDraft.allow_cross_agent_retrieval} onChange={(event) => setMemoryPolicyDraft((prev) => ({ ...prev, allow_cross_agent_retrieval: event.target.checked }))} />Routing multiagente</label>
            <label className="check-row"><input type="checkbox" checked={memoryPolicyDraft.auto_capture_enabled} onChange={(event) => setMemoryPolicyDraft((prev) => ({ ...prev, auto_capture_enabled: event.target.checked }))} />Auto-captura habilitada</label>
          </div>
          <div className="panel-actions">
            <button type="button" onClick={saveMemoryPolicy} disabled={busy === "memory-policy"}>{busy === "memory-policy" ? "Guardando..." : "Guardar politica Memory Network"}</button>
            <span className="field-hint">Actual: {memoryPolicy.privacy_mode || "tenant_private"} / {number(memoryPolicy.retention_days || 365)} dias. La memoria importada queda como candidate.</span>
          </div>
          <div className="mini-table intelligence-list">
            {memoryNodes.slice(0, 8).map((node) => (
              <div key={node.id} className={`intelligence-row-card ${node.status || ""}`}>
                <div>
                  <strong>{node.title}</strong>
                  <span>{node.memory_scope} / {node.node_type} / {node.status} / expira {shortDate(node.expires_at)}</span>
                  <p>{node.summary}</p>
                </div>
                <div className="row-actions">
                  {node.status !== "published" ? <button type="button" onClick={() => reviewMemoryNode(node, "published")} disabled={busy === `memory-published-${node.id}`}>Publicar</button> : null}
                  {node.status !== "rejected" ? <button type="button" onClick={() => reviewMemoryNode(node, "rejected")} disabled={busy === `memory-rejected-${node.id}`}>Rechazar</button> : null}
                  {node.status !== "archived" ? <button type="button" onClick={() => reviewMemoryNode(node, "archived")} disabled={busy === `memory-archived-${node.id}`}>Archivar</button> : null}
                  <button type="button" onClick={() => deleteMemoryNode(node)} disabled={busy === `memory-delete-${node.id}`}>Borrar</button>
                </div>
              </div>
            ))}
            {!memoryNodes.length ? <div className="empty">Sin nodos de memoria empresarial. Sincroniza para capturar Knowledge, memoria colectiva y senales revisadas.</div> : null}
          </div>
        </article>

        <article className="panel glass-card predictive-cards">
          <div className="panel-head">
            <div><h2>Memory graph</h2><span>{number(memoryEdges.length)} relaciones</span></div>
            <button type="button" onClick={exportMemoryNetwork} disabled={busy === "memory-export"}>{busy === "memory-export" ? "Exportando..." : "Exportar JSON"}</button>
          </div>
          <div className="mini-table intelligence-list compact">
            <div>
              <strong>Importar memoria segura</strong>
              <span>JSON con nodes o nodes_json. Siempre entra como candidate y requiere revision.</span>
              <textarea rows={5} value={memoryImportText} onChange={(event) => setMemoryImportText(event.target.value)} placeholder='[{"title":"Politica de atencion","summary":"Resumen operativo revisable","memory_scope":"tenant"}]' />
            </div>
            <div className="row-actions">
              <button type="button" onClick={() => importMemoryNetwork(true)} disabled={!memoryImportText.trim() || busy === "memory-import-preview"}>{busy === "memory-import-preview" ? "Validando..." : "Preview import"}</button>
              <button type="button" className="primary" onClick={() => importMemoryNetwork(false)} disabled={!memoryImportText.trim() || busy === "memory-import"}>{busy === "memory-import" ? "Importando..." : "Importar"}</button>
            </div>
          </div>
          <div className="mini-table intelligence-list compact">
            {memoryEdges.slice(0, 8).map((edge) => (
              <div key={edge.id}>
                <strong>{edge.source_title}</strong>
                <span>{edge.relation_type} {"->"} {edge.target_title}</span>
                <small>peso {number(edge.weight)}</small>
              </div>
            ))}
            {memorySyncRuns.slice(0, 4).map((run) => (
              <div key={run.id}>
                <strong>Sync {run.sync_type}</strong>
                <span>{number(run.nodes_created)} nuevas / {number(run.nodes_updated)} actualizadas</span>
                <small>{shortDate(run.created_at)}</small>
              </div>
            ))}
            {!memoryEdges.length && !memorySyncRuns.length ? <div className="empty">El grafo se crea al sincronizar fuentes revisadas.</div> : null}
          </div>
        </article>
      </section>

      <section className="predictive-board">
        <article className="panel glass-card predictive-summary">
          <div className="panel-head">
            <div>
              <h2>Phase 17 Federated Learning</h2>
              <span>{federatedAccess.mode || "disabled"} / privacidad agregada</span>
            </div>
            <div className="row-actions">
              <button type="button" onClick={() => prepareFederatedRound(true)} disabled={busy === "federated-preview"}>{busy === "federated-preview" ? "Simulando..." : "Preview update"}</button>
              <button type="button" className="primary" onClick={() => prepareFederatedRound(false)} disabled={busy === "federated-prepare"}>{busy === "federated-prepare" ? "Preparando..." : "Crear ronda + enviar"}</button>
            </div>
          </div>
          <div className="predictive-card-grid">
            <div className="predictive-card lead_scoring"><span>Opt-in</span><strong>{federatedPolicy.opt_in_enabled ? "Activo" : "Apagado"}</strong><small>{federatedPolicy.auto_participation_enabled ? "auto worker" : "manual"}</small></div>
            <div className="predictive-card smart_remarketing"><span>Min muestras</span><strong>{number(federatedPolicy.min_local_samples || 25)}</strong><small>{number(federatedPolicy.min_cohort_tenants || 3)} tenants/cohorte</small></div>
            <div className="predictive-card operational_anomaly"><span>Rondas</span><strong>{number(federatedRounds.length)}</strong><small>{number(federatedUpdates.length)} updates locales</small></div>
            <div className="predictive-card churn_prediction"><span>Signals globales</span><strong>{number(federatedSignals.length)}</strong><small>{number(federatedAggregates.length)} agregados</small></div>
          </div>
          <div className="agent-editor-grid two">
            <label>Privacidad
              <select value={federatedPolicyDraft.privacy_mode} onChange={(event) => setFederatedPolicyDraft((prev) => ({ ...prev, privacy_mode: event.target.value }))}>
                <option value="aggregate_only">aggregate_only</option>
                <option value="differential_privacy">differential_privacy</option>
                <option value="secure_aggregation_ready">secure_aggregation_ready</option>
              </select>
            </label>
            <label>Min muestras locales
              <input type="number" min="1" value={federatedPolicyDraft.min_local_samples} onChange={(event) => setFederatedPolicyDraft((prev) => ({ ...prev, min_local_samples: Number(event.target.value || 25) }))} />
            </label>
            <label>Min tenants cohorte
              <input type="number" min="3" value={federatedPolicyDraft.min_cohort_tenants} onChange={(event) => setFederatedPolicyDraft((prev) => ({ ...prev, min_cohort_tenants: Number(event.target.value || 3) }))} />
            </label>
            <label>Noise multiplier
              <input type="number" min="0" step="0.01" value={federatedPolicyDraft.noise_multiplier} onChange={(event) => setFederatedPolicyDraft((prev) => ({ ...prev, noise_multiplier: Number(event.target.value || 0) }))} />
            </label>
          </div>
          <div className="mini-table intelligence-list compact">
            <div>
              <strong>Tareas federadas permitidas</strong>
              <span>{(federatedPolicyDraft.allowed_task_types_json || []).join(", ") || "lead_scoring"}</span>
              <small>Solo se envian estadisticas agregadas y hashes; nunca mensajes, media, prompts, secretos ni nombres de tenants.</small>
            </div>
            <div className="row-actions">
              {FEDERATED_TASK_OPTIONS.map((taskType) => (
                <button
                  key={taskType}
                  type="button"
                  className={(federatedPolicyDraft.allowed_task_types_json || []).includes(taskType) ? "primary" : ""}
                  onClick={() => toggleFederatedTask(taskType)}
                >
                  {predictionTitle(taskType)}
                </button>
              ))}
            </div>
          </div>
          <div className="agent-editor-grid two">
            <label className="check-row"><input type="checkbox" checked={federatedPolicyDraft.opt_in_enabled} onChange={(event) => setFederatedPolicyDraft((prev) => ({ ...prev, opt_in_enabled: event.target.checked }))} />Opt-in federado</label>
            <label className="check-row"><input type="checkbox" checked={federatedPolicyDraft.auto_participation_enabled} onChange={(event) => setFederatedPolicyDraft((prev) => ({ ...prev, auto_participation_enabled: event.target.checked }))} />Auto-participacion worker</label>
            <label className="check-row"><input type="checkbox" checked={federatedPolicyDraft.differential_privacy_enabled} onChange={(event) => setFederatedPolicyDraft((prev) => ({ ...prev, differential_privacy_enabled: event.target.checked }))} />Diferential privacy ready</label>
            <label className="check-row"><input type="checkbox" checked={federatedPolicyDraft.share_feature_importance} onChange={(event) => setFederatedPolicyDraft((prev) => ({ ...prev, share_feature_importance: event.target.checked }))} />Compartir importancia agregada</label>
          </div>
          <div className="panel-actions">
            <button type="button" onClick={saveFederatedPolicy} disabled={busy === "federated-policy"}>{busy === "federated-policy" ? "Guardando..." : "Guardar politica federada"}</button>
            <span className="field-hint">Feature apagada por defecto. El worker participa solo con modo full, opt-in y auto-participacion activos.</span>
          </div>
          <div className="mini-table intelligence-list">
            {federatedPreviews.slice(0, 4).map((item) => (
              <div key={item.task_type} className={`intelligence-row-card ${item.eligible ? "ok" : "warning"}`}>
                <div>
                  <strong>{predictionTitle(item.task_type)} / {item.industry_code || "general"}</strong>
                  <span>{number(item.sample_count || 0)} muestras / calidad {number(item.quality_score || 0)}</span>
                  <p>{item.blockers?.length ? `Bloqueos: ${item.blockers.join(", ")}` : "Elegible para update federado agregado."}</p>
                </div>
                <small>{item.privacy_json?.privacy_mode || "aggregate_only"}</small>
              </div>
            ))}
            {!federatedPreviews.length ? <div className="empty">Sin previews. Habilita demo/full o ajusta el acceso premium para ver paquetes locales.</div> : null}
          </div>
        </article>

        <article className="panel glass-card predictive-cards">
          <div className="panel-head"><h2>Rondas, agregados y signals</h2><span>{number(federatedRounds.length)} rondas</span></div>
          <div className="crm-mini-form">
            <label>Tarea
              <select value={federatedRoundDraft.task_type} onChange={(event) => setFederatedRoundDraft((prev) => ({ ...prev, task_type: event.target.value }))}>
                {FEDERATED_TASK_OPTIONS.map((taskType) => <option key={taskType} value={taskType}>{predictionTitle(taskType)}</option>)}
              </select>
            </label>
            <label>Model key<input value={federatedRoundDraft.model_key} placeholder="default por tarea" onChange={(event) => setFederatedRoundDraft((prev) => ({ ...prev, model_key: event.target.value }))} /></label>
            <label>Ventana<input value={federatedRoundDraft.window_key} onChange={(event) => setFederatedRoundDraft((prev) => ({ ...prev, window_key: event.target.value }))} /></label>
            <label>Min participantes<input type="number" min="3" value={federatedRoundDraft.min_participants} onChange={(event) => setFederatedRoundDraft((prev) => ({ ...prev, min_participants: Number(event.target.value || 3) }))} /></label>
            <label>Min muestras total<input type="number" min="1" value={federatedRoundDraft.min_total_samples} onChange={(event) => setFederatedRoundDraft((prev) => ({ ...prev, min_total_samples: Number(event.target.value || 100) }))} /></label>
          </div>
          <div className="mini-table intelligence-list">
            {federatedRounds.slice(0, 7).map((round) => (
              <div key={round.id} className={`intelligence-row-card ${round.status || ""}`}>
                <div>
                  <strong>{predictionTitle(round.task_type)} / {round.industry_code}</strong>
                  <span>{round.status} / {number(round.submitted_updates || 0)} updates / {number(round.submitted_samples || 0)} muestras</span>
                  <p>{round.model_key} / {round.window_key} / min {number(round.min_participants)} tenants y {number(round.min_total_samples)} muestras.</p>
                </div>
                <div className="row-actions">
                  <button type="button" onClick={() => submitFederatedUpdate(round, true)} disabled={busy === `federated-submit-preview-${round.id}`}>Preview update</button>
                  <button type="button" onClick={() => submitFederatedUpdate(round, false)} disabled={busy === `federated-submit-${round.id}`}>Enviar update</button>
                  <button type="button" className="primary" onClick={() => aggregateFederatedRound(round, true)} disabled={busy === `federated-aggregate-preview-${round.id}`}>Preview agg</button>
                  <button type="button" className="primary" onClick={() => aggregateFederatedRound(round, false)} disabled={busy === `federated-aggregate-${round.id}`}>Agregar</button>
                </div>
              </div>
            ))}
            {!federatedRounds.length ? <div className="empty">No hay rondas abiertas. Crea una desde el panel de politica.</div> : null}
          </div>
          <div className="mini-table intelligence-list compact">
            {federatedAggregates.slice(0, 4).map((item) => (
              <div key={item.id}>
                <strong>{predictionTitle(item.task_type)} / {item.status}</strong>
                <span>{number(item.participant_count)} tenants / {number(item.total_samples)} muestras</span>
                <small>{item.global_signal_json?.summary || "Agregado privacy-safe candidate."}</small>
              </div>
            ))}
            {federatedSignals.slice(0, 4).map((item) => (
              <div key={item.id}>
                <strong>{item.title}</strong>
                <span>{item.status} / confianza {asPercent(item.confidence)}</span>
                <small>{item.summary}</small>
              </div>
            ))}
            {!federatedAggregates.length && !federatedSignals.length ? <div className="empty">Los agregados se crean cuando la cohorte cumple muestra minima.</div> : null}
          </div>
        </article>
      </section>

      <section className="predictive-board realtime-intelligence-board">
        <article className="panel glass-card predictive-summary">
          <div className="panel-head">
            <div>
              <h2>AI Real-Time Intelligence Layer</h2>
              <span>{realtimeAccess.mode || "disabled"} / {realtimeStream.transport || "polling"}</span>
            </div>
            <div className="row-actions">
              <button type="button" onClick={() => loadAll(true)} disabled={loading}>Refrescar</button>
              <button type="button" className="primary" onClick={markRealtimeCursor} disabled={busy === "realtime-cursor" || !realtimeEvents.length}>Marcar visto</button>
            </div>
          </div>
          <div className="realtime-livebar">
            <span className={realtimeMetrics.status === "critical" ? "danger" : realtimeMetrics.status === "watch" ? "warn" : "live"}>{realtimeMetrics.status || "sin datos"}</span>
            <small>{realtimeSession?.status || "sin sesion"} / cursor {realtimeStream.cursor?.last_event_id ? "activo" : "nuevo"}</small>
            <small>{shortDate(realtimeCenter?.generated_at)}</small>
          </div>
          <div className="predictive-card-grid realtime-metrics">
            <div className="predictive-card lead_scoring"><span>Eventos 15m</span><strong>{number(realtimeMetrics.events_15m || 0)}</strong><small>{number(realtimeMetrics.events_1h || 0)} en 1h</small></div>
            <div className="predictive-card smart_remarketing"><span>Predicciones 1h</span><strong>{number(realtimeMetrics.predictions_1h || 0)}</strong><small>{number(realtimeMetrics.open_recommendations || 0)} recomendaciones</small></div>
            <div className="predictive-card operational_anomaly"><span>Anomalias</span><strong>{number(realtimeMetrics.open_anomalies || 0)}</strong><small>{number(realtimeMetrics.high_anomalies || 0)} altas</small></div>
            <div className="predictive-card churn_prediction"><span>Trust AI</span><strong>{number(realtimeMetrics.open_trust_incidents || 0)}</strong><small>{number(realtimeMetrics.high_trust_incidents || 0)} altas</small></div>
          </div>
        </article>
        <article className="panel glass-card predictive-cards">
          <div className="panel-head"><h2>Realtime alerts</h2><span>{number(realtimeAlerts.length)}</span></div>
          <div className="mini-table intelligence-list realtime-alerts">
            {realtimeAlerts.slice(0, 7).map((alert, index) => (
              <div key={`${alert.kind}-${alert.source_id || index}`} className={`intelligence-row-card ${alert.severity || ""}`}>
                <div>
                  <strong>{alert.title}</strong>
                  <span>{alert.kind} / {alert.severity}</span>
                  <p>{alert.description}</p>
                </div>
                <small>{shortDate(alert.created_at)}</small>
              </div>
            ))}
            {!realtimeAlerts.length ? <div className="empty">Sin alertas live. El sistema sigue monitoreando eventos, predicciones y operaciones.</div> : null}
          </div>
        </article>
      </section>

      <section className="intelligence-layout bottom realtime-feed-layout">
        <article className="panel glass-card module-card">
          <div className="panel-head"><h2>Live event feed</h2><span>{number(realtimeEvents.length)}</span></div>
          <div className="mini-table intelligence-list compact realtime-feed">
            {realtimeEvents.slice(0, 12).map((event) => (
              <div key={event.id}>
                <strong>{event.event_type}</strong>
                <span>{event.source || "intelligence"} / {event.channel || "tenant"} / {shortDate(event.occurred_at)}</span>
                <small>{event.entity_type || "entity"} {event.entity_id || event.conversation_id || ""}</small>
              </div>
            ))}
            {!realtimeEvents.length ? <div className="empty">Aun no hay eventos realtime para mostrar.</div> : null}
          </div>
        </article>
        <article className="panel glass-card module-card">
          <div className="panel-head"><h2>Event mix</h2><span>60 min</span></div>
          <div className="mini-table intelligence-list compact realtime-feed">
            {realtimeCounts.slice(0, 12).map((item) => (
              <div key={item.event_type}>
                <strong>{item.event_type}</strong>
                <span>{number(item.total)} eventos</span>
                <small>{shortDate(item.latest_at)}</small>
              </div>
            ))}
            {!realtimeCounts.length ? <div className="empty">Sin mezcla de eventos reciente.</div> : null}
          </div>
        </article>
      </section>

      <section className="predictive-board">
        <article className="panel glass-card predictive-summary">
          <div className="panel-head">
            <div>
              <h2>Industry Intelligence Center</h2>
              <span>{networkIndustry.label || "General"} / {networkAccess.mode || "disabled"}</span>
            </div>
            <div className="row-actions">
              <button type="button" onClick={() => refreshEnterpriseNetwork(true)} disabled={busy === "network-preview"}>{busy === "network-preview" ? "Simulando..." : "Vista previa"}</button>
              <button type="button" className="primary" onClick={() => refreshEnterpriseNetwork(false)} disabled={busy === "network-refresh"}>{busy === "network-refresh" ? "Actualizando..." : "Actualizar red"}</button>
            </div>
          </div>
          <div className="summary-stack">
            <div>
              <strong>{networkAdvisors[0]?.name || "Asesor IA vertical"}</strong>
              <p>Copiloto sectorial con KPIs, playbooks y recomendaciones comparativas sin compartir mensajes ni conversaciones crudas.</p>
            </div>
            <div>
              <strong>Privacidad multi-tenant</strong>
              <p>Benchmarks agregados con muestra minima {number(networkCenter?.privacy?.minimum_benchmark_sample || 3)}; no expone nombres, contenido privado ni datos sensibles de otros tenants.</p>
            </div>
          </div>
        </article>
        <article className="panel glass-card predictive-cards">
          <div className="panel-head"><h2>Panel comparativo</h2><span>{number(networkBenchmarks.length)} KPIs</span></div>
          <div className="predictive-card-grid">
            {networkBenchmarks.slice(0, 7).map((item) => (
              <div className={`predictive-card ${item.comparison_label || item.label || ""}`} key={item.metric_key}>
                <span>{metricTitle(item.metric_key)}</span>
                <strong>{item.tenant_value == null ? "-" : number(item.tenant_value)}</strong>
                <small>benchmark {item.benchmark_value == null ? "sin muestra" : number(item.benchmark_value)} / {item.comparison_label || item.label || "preview"}</small>
                <p>{item.recommendation_json?.message || item.recommendation || "Comparacion protegida por privacidad y muestra anonima."}</p>
              </div>
            ))}
            {!networkBenchmarks.length ? <div className="empty">Sin benchmarks aun. Ejecuta preview para calcular comparaciones protegidas.</div> : null}
          </div>
        </article>
      </section>

      <section className="intelligence-layout bottom">
        <article className="panel glass-card module-card">
          <div className="panel-head"><h2>Industry Insights Panel</h2><span>{number(networkInsights.length)}</span></div>
          <div className="mini-table intelligence-list">
            {networkInsights.slice(0, 8).map((item) => (
              <div key={item.id || item.insight_key} className={`intelligence-row-card ${item.severity || ""}`}>
                <div>
                  <strong>{item.title}</strong>
                  <span>{item.insight_type} / {item.kpi_key || "vertical"}</span>
                  <p>{item.description}</p>
                </div>
                <small>{item.status || "preview"}</small>
              </div>
            ))}
            {!networkInsights.length ? <div className="empty">Aun no hay insights verticales persistidos.</div> : null}
          </div>
        </article>
        <article className="panel glass-card module-card">
          <div className="panel-head"><h2>AI Playbook Marketplace</h2><span>{number(networkPlaybooks.length)}</span></div>
          <div className="mini-table intelligence-list compact">
            {networkPlaybooks.slice(0, 8).map((item) => (
              <div key={item.id || item.playbook_key}>
                <strong>{item.title}</strong>
                <span>{item.playbook_type} / {item.kpi_key || "kpi"}</span>
                <small>{item.description}</small>
              </div>
            ))}
            {!networkPlaybooks.length ? <div className="empty">Sin playbooks sectoriales cargados.</div> : null}
          </div>
        </article>
      </section>

      <section className="intelligence-layout bottom">
        <article className="panel glass-card module-card">
          <div className="panel-head"><h2>Industry AI Models</h2><span>{number(networkModels.length)}</span></div>
          <div className="mini-table intelligence-list compact">
            {networkModels.slice(0, 8).map((item) => (
              <div key={item.id || item.model_key}>
                <strong>{item.model_key}</strong>
                <span>{item.prediction_type} / {item.routing_mode}</span>
                <small>{item.model_metadata_json?.training_mode || "metadata_only"}</small>
              </div>
            ))}
            {!networkModels.length ? <div className="empty">Sin modelos verticales registrados.</div> : null}
          </div>
        </article>
        <article className="panel glass-card module-card">
          <div className="panel-head"><h2>AI Knowledge Network</h2><span>{number(networkKnowledge.length)}</span></div>
          <div className="mini-table intelligence-list compact">
            {networkKnowledge.slice(0, 8).map((item) => (
              <div key={item.id || item.node_key}>
                <strong>{item.title}</strong>
                <span>{item.node_type} / {item.privacy_class}</span>
                <small>{item.summary}</small>
              </div>
            ))}
            {!networkKnowledge.length ? <div className="empty">Sin nodos de conocimiento vertical publicados.</div> : null}
          </div>
        </article>
      </section>

      <section className="intelligence-layout">
        <article className="panel glass-card module-card ai-operations-center">
          <div className="panel-head">
            <div>
              <h2>AI Operations Center</h2>
              <span>{opsAccess.mode || "disabled"} / nivel {number(opsPolicy.autonomy_level || 0)}</span>
            </div>
            <div className="row-actions">
              <button type="button" onClick={() => runOperationsAnalysis(true)} disabled={busy === "ops-dry-run"}>{busy === "ops-dry-run" ? "Simulando..." : "Preview"}</button>
              <button type="button" className="primary" onClick={() => runOperationsAnalysis(false)} disabled={busy === "ops-analyze"}>{busy === "ops-analyze" ? "Analizando..." : "Analizar operacion"}</button>
            </div>
          </div>
          <div className="predictive-card-grid ops-grid">
            <div className="predictive-card operational_anomaly"><span>Anomalias abiertas</span><strong>{number(opsCounts.open_anomalies || 0)}</strong><small>{number(opsCounts.critical_anomalies || 0)} criticas</small></div>
            <div className="predictive-card smart_remarketing"><span>Acciones AI</span><strong>{number(opsCounts.pending_actions || 0)}</strong><small>{number(opsCounts.executed_actions || 0)} ejecutadas</small></div>
            <div className="predictive-card churn_prediction"><span>Playbooks</span><strong>{number(opsPlaybooks.length)}</strong><small>self-healing y optimizacion</small></div>
          </div>
          <div className="mini-table intelligence-list">
            {opsAnomalies.slice(0, 6).map((item) => (
              <div key={item.id} className={`intelligence-row-card ${item.severity || ""}`}>
                <div>
                  <strong>{item.title}</strong>
                  <span>{item.anomaly_type} / {asPercent(item.confidence)}</span>
                  <p>{item.description}</p>
                </div>
                <small>{item.recommended_playbook_key}</small>
              </div>
            ))}
            {!opsAnomalies.length ? <div className="empty">Sin anomalias abiertas. Ejecuta un analisis para recalcular senales.</div> : null}
          </div>
        </article>

        <article className="panel glass-card module-card ai-control-center">
          <div className="panel-head"><h2>AI Control Center</h2><span>Autonomous AI + Human Supervision</span></div>
          <div className="agent-editor-grid two">
            <label>Nivel de autonomia
              <select value={controlDraft.autonomy_level} onChange={(event) => setControlDraft((prev) => ({ ...prev, autonomy_level: Number(event.target.value) }))}>
                {(operationCenter?.autonomy_levels || []).map((level) => <option key={level.level} value={level.level}>Level {level.level}: {level.label}</option>)}
              </select>
            </label>
            <label>Sensibilidad
              <select value={controlDraft.sensitivity} onChange={(event) => setControlDraft((prev) => ({ ...prev, sensitivity: event.target.value }))}>
                <option value="low">Baja</option>
                <option value="medium">Media</option>
                <option value="high">Alta</option>
              </select>
            </label>
            <label>Max acciones/dia
              <input type="number" min="0" max="1000" value={controlDraft.max_daily_actions} onChange={(event) => setControlDraft((prev) => ({ ...prev, max_daily_actions: Number(event.target.value || 0) }))} />
            </label>
            <label>Aprobacion desde nivel
              <select value={controlDraft.approval_required_from_level} onChange={(event) => setControlDraft((prev) => ({ ...prev, approval_required_from_level: Number(event.target.value) }))}>
                {[0, 1, 2, 3, 4].map((level) => <option key={level} value={level}>Level {level}</option>)}
              </select>
            </label>
          </div>
          <label className="check-row">
            <input type="checkbox" checked={controlDraft.auto_remediation_enabled} onChange={(event) => setControlDraft((prev) => ({ ...prev, auto_remediation_enabled: event.target.checked }))} />
            <span><b>Auto-remediacion controlada</b><small>Solo se habilita en modo full; acciones criticas siguen requiriendo aprobacion.</small></span>
          </label>
          <label className="check-row">
            <input type="checkbox" checked={controlDraft.low_risk_auto_execute} onChange={(event) => setControlDraft((prev) => ({ ...prev, low_risk_auto_execute: event.target.checked }))} />
            <span><b>Ejecutar bajo riesgo en Level 4</b><small>Registra ejecucion controlada para playbooks report-only o de bajo riesgo.</small></span>
          </label>
          <div className="panel-actions">
            <button type="button" className="primary" onClick={saveControlPolicy} disabled={busy === "ops-policy"}>{busy === "ops-policy" ? "Guardando..." : "Guardar Control Center"}</button>
          </div>
        </article>
      </section>

      <section className="intelligence-layout bottom">
        <article className="panel glass-card module-card">
          <div className="panel-head"><h2>Autonomous actions</h2><span>{number(opsActions.length)}</span></div>
          <div className="mini-table intelligence-list">
            {opsActions.slice(0, 8).map((action) => (
              <div key={action.id} className={`intelligence-row-card ${action.risk_level || ""}`}>
                <div>
                  <strong>{action.title}</strong>
                  <span>{action.status} / {action.risk_level} / {action.playbook_key}</span>
                  <p>{action.description}</p>
                </div>
                <div className="row-actions">
                  {["suggested", "pending_approval"].includes(action.status) ? <button type="button" onClick={() => approveOperationAction(action)} disabled={busy === `ops-approve-${action.id}`}>Aprobar</button> : null}
                  {["approved"].includes(action.status) ? <button type="button" className="primary" onClick={() => executeOperationAction(action, false)} disabled={busy === `ops-execute-${action.id}`}>Ejecutar</button> : null}
                  {action.status !== "executed" && action.status !== "dismissed" ? <button type="button" onClick={() => dismissOperationAction(action)} disabled={busy === `ops-dismiss-${action.id}`}>Descartar</button> : null}
                </div>
              </div>
            ))}
            {!opsActions.length ? <div className="empty">Sin acciones autonomas. Sube el nivel a 2+ para generar acciones supervisadas.</div> : null}
          </div>
        </article>
        <article className="panel glass-card module-card">
          <div className="panel-head"><h2>Operational reports</h2><span>{number(opsReports.length)}</span></div>
          <div className="mini-table intelligence-list compact">
            {opsReports.slice(0, 8).map((report) => (
              <div key={report.id}>
                <strong>{report.title}</strong>
                <span>{report.report_type} / score {number(report.score)}</span>
                <small>{report.summary}</small>
              </div>
            ))}
            {!opsReports.length ? <div className="empty">Aun no hay reportes autonomos generados.</div> : null}
          </div>
        </article>
      </section>

      {overview ? (
        <section className="predictive-board">
          <article className="panel glass-card predictive-summary">
            <div className="panel-head"><h2>Executive intelligence</h2><span>{overview?.premium?.demo ? "demo/premium" : "premium"}</span></div>
            <div className="summary-stack">
              {["daily", "weekly", "operations"].map((key) => summaries[key] ? (
                <div key={key}>
                  <strong>{key === "daily" ? "Diario" : key === "weekly" ? "Semanal" : "Operacional"}</strong>
                  <p>{summaries[key]}</p>
                </div>
              ) : null)}
              {!Object.values(summaries).filter(Boolean).length ? <div className="empty">Aun no hay resumen ejecutivo calculado.</div> : null}
            </div>
          </article>
          <article className="panel glass-card predictive-cards">
            <div className="panel-head"><h2>Predictive dashboards</h2><span>{number(overviewCards.length)} senales</span></div>
            <div className="predictive-card-grid">
              {overviewCards.map((card) => (
                <div className={`predictive-card ${card.key}`} key={card.key}>
                  <span>{card.title}</span>
                  <strong>{number(card.value)}</strong>
                  <small>{card.label} / {card.detail}</small>
                  <p>{card.recommended_action}</p>
                </div>
              ))}
              {!overviewCards.length ? <div className="empty">Genera predicciones para activar el dashboard predictivo.</div> : null}
            </div>
          </article>
        </section>
      ) : null}

      <article className="panel glass-card">
        <div className="panel-head"><h2>Accesos AI premium</h2><span>{state?.period_yyyymm || "periodo"}</span></div>
        <div className="feature-grid intelligence-feature-grid">
          {visibleFeatures.map((feature) => (
            <div key={feature.key} className={`feature-pill ${feature.enabled ? "on" : "off"}`}>
              <strong>{featureLabel(feature)}</strong>
              <small>{modeLabel(feature.mode)} / {feature.source || "default"}</small>
              <small>{featureUsage(feature)}</small>
            </div>
          ))}
          {!visibleFeatures.length ? <div className="empty">No hay estado Intelligence cargado.</div> : null}
        </div>
      </article>

      <section className="intelligence-layout">
        <article className="panel glass-card module-card">
          <div className="panel-head"><h2>Predicciones</h2><span>{number(PREDICTION_ACTIONS.length)} tareas</span></div>
          <div className="intelligence-action-grid">
            {PREDICTION_ACTIONS.map((action) => {
              const feature = featuresByKey[action.feature];
              const disabled = !feature?.enabled || busy === action.key;
              return (
                <button key={action.key} type="button" className={`intelligence-action ${action.tone}`} onClick={() => runPrediction(action)} disabled={disabled}>
                  <strong>{action.label}</strong>
                  <span>{feature ? `${modeLabel(feature.mode)} / ${featureUsage(feature)}` : "Sin grant"}</span>
                </button>
              );
            })}
          </div>
          <div className="mini-table intelligence-list">
            {predictions.map((prediction) => {
              const rowFeedback = feedbackByPrediction[prediction.id];
              return (
                <div key={prediction.id} className={`intelligence-row-card ${prediction.status || ""}`}>
                  <div>
                    <strong>{predictionTitle(prediction.prediction_type)} / {prediction.label}</strong>
                    <span>{prediction.model_key} / {rolloutLabel(prediction)}</span>
                    <p>{JSON.stringify(prediction.explanation_json || {})}</p>
                  </div>
                  <span className="prediction-score">{number(prediction.score)}</span>
                  <div className="row-actions">
                    {rowFeedback ? <small>{rowFeedback.is_correct === true ? "validada" : rowFeedback.is_correct === false ? "marcada revision" : "feedback"}</small> : (
                      <>
                        <button type="button" onClick={() => submitFeedback(prediction, true)} disabled={busy === `feedback-${prediction.id}`}>Correcta</button>
                        <button type="button" onClick={() => submitFeedback(prediction, false)} disabled={busy === `feedback-${prediction.id}`}>Revisar</button>
                      </>
                    )}
                  </div>
                </div>
              );
            })}
            {!predictions.length ? <div className="empty">Aun no hay predicciones para este tenant.</div> : null}
          </div>
        </article>

        <article className="panel glass-card module-card">
          <div className="panel-head"><h2>Recomendaciones</h2><span>{number(recommendations.length)}</span></div>
          <div className="mini-table intelligence-list">
            {recommendations.map((item) => (
              <div key={item.id} className={`intelligence-row-card ${item.severity || ""}`}>
                <div>
                  <strong>{item.title}</strong>
                  <span>{item.recommendation_type} / {asPercent(item.confidence)}</span>
                  <p>{item.description}</p>
                </div>
                <button type="button" onClick={() => dismissRecommendation(item)} disabled={busy === `dismiss-${item.id}`}>Descartar</button>
              </div>
            ))}
            {!recommendations.length ? <div className="empty">Sin recomendaciones abiertas.</div> : null}
          </div>
        </article>
      </section>

      <section className="intelligence-layout bottom">
        <article className="panel glass-card module-card">
          <div className="panel-head"><h2>Feature store</h2><span>{number(featureRows.length)}</span></div>
          <div className="mini-table intelligence-list compact">
            {featureRows.slice(0, 18).map((item) => (
              <div key={item.id || `${item.feature_key}-${item.window_key}`}>
                <strong>{item.feature_key}</strong>
                <span>{number(item.value_numeric)} / {item.window_key}</span>
                <small>{shortDate(item.computed_at)}</small>
              </div>
            ))}
            {!featureRows.length ? <div className="empty">Recalcula features para poblar el snapshot tenant.</div> : null}
          </div>
        </article>

        <article className="panel glass-card module-card">
          <div className="panel-head"><h2>Metricas de modelos</h2><span>{number(metrics.length)}</span></div>
          <div className="mini-table intelligence-list compact">
            {metrics.map((metric) => (
              <div key={metric.id || `${metric.model_key}-${metric.prediction_type}`}>
                <strong>{metric.model_key}</strong>
                <span>{metric.prediction_type} / {metric.status}</span>
                <small>accuracy {metric.accuracy == null ? "-" : asPercent(metric.accuracy)} / drift {metric.drift_score == null ? "-" : number(metric.drift_score)}</small>
              </div>
            ))}
            {!metrics.length ? <div className="empty">Sin metricas; se alimentan con feedback validado.</div> : null}
          </div>
        </article>
      </section>
    </section>
  );
}
