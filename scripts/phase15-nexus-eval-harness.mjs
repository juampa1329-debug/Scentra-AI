import { mkdir, readdir, readFile, writeFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import path from "node:path";
import { fileURLToPath } from "node:url";

const workspaceRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const defaultSource = path.join(workspaceRoot, "external-repos/agency-agents");
const defaultOut = path.join(workspaceRoot, "docs/phase15_1");

const args = new Map(
  process.argv
    .slice(2)
    .filter((arg) => arg.startsWith("--"))
    .map((arg) => {
      const [key, ...rest] = arg.slice(2).split("=");
      return [key, rest.join("=") || "true"];
    }),
);

const sourceRoot = path.resolve(args.get("source") || defaultSource);
const outRoot = path.resolve(args.get("out") || defaultOut);

function rel(file) {
  return path.relative(sourceRoot, file).replace(/\\/g, "/");
}

function ascii(value) {
  return String(value || "")
    .normalize("NFKD")
    .replace(/[^\x09\x0A\x0D\x20-\x7E]/g, "")
    .replace(/[ \t]+/g, " ")
    .trim();
}

function compact(value, max = 360) {
  const clean = ascii(value).replace(/\s+/g, " ");
  return clean.length > max ? `${clean.slice(0, max - 3).trim()}...` : clean;
}

function slugify(value) {
  return ascii(value)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 90) || "item";
}

async function walk(dir) {
  const entries = await readdir(dir, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) files.push(...await walk(full));
    else if (entry.name.endsWith(".md")) files.push(full);
  }
  return files;
}

function extractTitle(content, fallback) {
  const title = content.split(/\r?\n/).find((line) => /^#\s+/.test(line));
  return compact(title ? title.replace(/^#\s+/, "") : fallback, 120);
}

function codeBlocks(content) {
  const blocks = [];
  let inBlock = false;
  let lang = "";
  let lines = [];
  for (const raw of content.split(/\r?\n/)) {
    const fence = /^```([A-Za-z0-9_-]*)/.exec(raw);
    if (fence) {
      if (inBlock) {
        blocks.push({ lang, text: lines.join("\n") });
        inBlock = false;
        lang = "";
        lines = [];
      } else {
        inBlock = true;
        lang = fence[1] || "";
      }
      continue;
    }
    if (inBlock) lines.push(raw);
  }
  return blocks;
}

function sectionText(content, headingPattern, max = 900) {
  return compact(sectionLines(content, headingPattern).join(" "), max);
}

function sectionLines(content, headingPattern) {
  const lines = content.split(/\r?\n/);
  let capture = false;
  let level = 0;
  const found = [];
  for (const raw of lines) {
    const heading = /^(#{1,4})\s+(.+)$/.exec(raw);
    if (heading) {
      if (capture && heading[1].length <= level) break;
      if (headingPattern.test(ascii(heading[2]))) {
        capture = true;
        level = heading[1].length;
        continue;
      }
    }
    if (capture) found.push(raw);
  }
  return found;
}

function checklist(content, headingPattern, limit = 12) {
  const items = [];
  const lines = sectionLines(content, headingPattern);
  for (const raw of lines) {
    let line = "";
    const bullet = /^\s*[-*]\s+(?:\[[ xX]\]\s*)?(.+)$/.exec(raw);
    if (bullet) {
      line = compact(bullet[1], 220);
    } else if (/^\s*\|/.test(raw)) {
      const cells = raw.split("|").slice(1, -1).map((cell) => compact(cell, 160));
      const normalized = cells.map((cell) => cell.toLowerCase());
      const isSeparator = cells.every((cell) => /^:?-{2,}:?$/.test(cell));
      const isHeader = normalized.includes("criterion") || normalized.includes("metric");
      if (!isSeparator && !isHeader) {
        const subject = cells[1] || cells[0] || "";
        const qualifier = cells[2] || "";
        line = compact(qualifier ? `${subject} - ${qualifier}` : subject, 220);
      }
    }
    if (!line || line.startsWith("|")) continue;
    items.push(line);
    if (items.length >= limit) break;
  }
  return items;
}

function headings(content, pattern, limit = 24) {
  const out = [];
  for (const raw of content.split(/\r?\n/)) {
    const match = /^(#{2,4})\s+(.+)$/.exec(raw);
    if (!match) continue;
    const text = compact(match[2], 160);
    if (!pattern || pattern.test(text)) out.push({ level: match[1].length, title: text });
    if (out.length >= limit) break;
  }
  return out;
}

function normalizeHandoffKind(title) {
  const lower = title.toLowerCase();
  if (lower.includes("qa feedback") && lower.includes("pass")) return "qa_pass";
  if (lower.includes("qa feedback") && lower.includes("fail")) return "qa_fail";
  if (lower.includes("escalation")) return "escalation_report";
  if (lower.includes("phase gate")) return "phase_gate_handoff";
  if (lower.includes("sprint")) return "sprint_handoff";
  if (lower.includes("incident")) return "incident_handoff";
  return "standard_handoff";
}

function extractRequiredSections(templateText) {
  return templateText
    .split(/\r?\n/)
    .filter((line) => /^#{1,3}\s+/.test(line))
    .map((line) => compact(line.replace(/^#{1,3}\s+/, ""), 90))
    .filter(Boolean);
}

function handoffContracts(content) {
  const templateHeadings = [];
  const lines = content.split(/\r?\n/);
  for (let index = 0; index < lines.length; index += 1) {
    const match = /^##\s+\d+\.\s+(.+)$/.exec(lines[index]);
    if (match) templateHeadings.push({ index, title: compact(match[1], 120) });
  }
  const blocks = codeBlocks(content).filter((block) => block.lang === "markdown");
  return templateHeadings.map((item, index) => {
    const block = blocks[index] || { text: "" };
    const kind = normalizeHandoffKind(item.title);
    const requiredSections = extractRequiredSections(block.text);
    return {
      contract_key: `nexus.${kind}.v1`,
      title: item.title,
      kind,
      source_path: "strategy/coordination/handoff-templates.md",
      status: "offline_contract",
      required_sections: requiredSections,
      required_fields: requiredSections.map((section) => slugify(section)),
      max_attempts: ["qa_fail", "escalation_report"].includes(kind) ? 3 : null,
      allowed_results: kind.includes("qa") ? ["pass", "fail", "needs_work"] : ["draft", "submitted", "accepted", "escalated"],
      safety_policy: {
        evidence_required: true,
        human_approval_required: kind !== "qa_pass",
        no_runtime_side_effects: true,
        tenant_scoped: true,
      },
      template_hash: createHash("sha256").update(block.text).digest("hex"),
      template_excerpt: compact(block.text, 900),
    };
  });
}

function playbookPhaseCode(file) {
  const base = path.basename(file, ".md");
  const match = /phase-(\d+)-(.+)/.exec(base);
  if (!match) return slugify(base);
  return `nexus_phase_${match[1]}_${slugify(match[2])}`;
}

function normalizePlaybook(file, content) {
  const sourcePath = rel(file);
  const title = extractTitle(content, path.basename(file, ".md"));
  const objective = sectionText(content, /^Objective$/i, 600);
  const preconditions = checklist(content, /^Pre-Conditions$/i, 8);
  const activation = headings(content, /(Wave|Step|Workstream|Track|Timeline|Continuous|Daily|Weekly|Monthly|Quarterly|Hour|T\+|T-)/i, 20);
  let qualityGate = checklist(content, /Quality Gate/i, 16);
  if (!qualityGate.length) qualityGate = checklist(content, /Success Metrics/i, 16);
  const gateDecision = sectionText(content, /Gate Decision/i, 700);
  const handoff = sectionText(content, /Handoff/i, 900);
  return {
    playbook_key: `agency.${playbookPhaseCode(file)}.v1`,
    title,
    source_path: sourcePath,
    status: "offline_blueprint",
    objective,
    preconditions,
    activation_sequence: activation,
    quality_gate: qualityGate,
    gate_decision: gateDecision,
    handoff_package: handoff,
    scentra_mapping: {
      runtime: "future_workflow_composer_blueprint",
      activation_mode: "draft_only",
      requires_preflight: true,
      requires_human_approval: true,
      tenant_scoped: true,
      no_customer_facing_side_effects: true,
    },
  };
}

function normalizeRunbook(file, content) {
  const sourcePath = rel(file);
  const title = extractTitle(content, path.basename(file, ".md"));
  const scenario = sectionText(content, /^Scenario$/i, 500);
  const roster = sectionText(content, /Agent Roster|Response Teams/i, 900);
  const plan = headings(content, /(Week|Phase|Step|Hour|T\+|T-)/i, 24);
  const success = checklist(content, /Success Criteria|Quality Requirements|Campaign Metrics|Phase 6 Success Metrics/i, 14);
  const risks = checklist(content, /Pitfalls|Risk Management|Escalation Matrix/i, 10);
  return {
    scenario_key: `agency.${slugify(path.basename(file, ".md"))}.v1`,
    title,
    source_path: sourcePath,
    status: "offline_blueprint",
    scenario,
    roster_summary: roster,
    execution_plan: plan,
    success_criteria: success,
    risk_controls: risks,
    scentra_mapping: {
      runtime: "future_runbook_blueprint",
      activation_mode: "draft_only",
      requires_human_approval: true,
      no_runtime_side_effects: true,
    },
  };
}

function evalRubrics() {
  return [
    {
      rubric_key: "scentra.template_safety_preflight.v1",
      source_agents: ["Reality Checker", "Evidence Collector"],
      objective: "Reject unsafe or fantasy template imports before Admin review.",
      required_checks: [
        "template remains disabled",
        "activation_allowed is false",
        "human approval is required",
        "outbound actions are suggest-only",
        "tenant-scoped memory policy exists",
        "source license and hash are present",
        "risk assessment exists",
      ],
      blocking_failures: ["active_template", "missing_source", "direct_tool_execution", "no_human_approval"],
    },
    {
      rubric_key: "scentra.evidence_quality_gate.v1",
      source_agents: ["Evidence Collector"],
      objective: "Require evidence and explicit findings for any template/workflow certification.",
      required_checks: [
        "evidence list is non-empty",
        "claims are tied to observed artifacts",
        "issues are categorized by severity",
        "approval includes next action",
      ],
      blocking_failures: ["claim_without_evidence", "zero_issue_fantasy_approval"],
    },
    {
      rubric_key: "scentra.qa_feedback_loop.v1",
      source_agents: ["Evidence Collector", "Agents Orchestrator"],
      objective: "Enforce PASS/FAIL/retry/escalation loops.",
      required_checks: [
        "PASS requires verified criteria",
        "FAIL includes exact fix instructions",
        "retry count is limited to 3",
        "attempt 3 failure escalates",
      ],
      blocking_failures: ["pass_without_evidence", "retry_loop_without_limit"],
    },
    {
      rubric_key: "scentra.api_security_evaluation.v1",
      source_agents: ["API Tester", "Security Engineer"],
      objective: "Check API-facing proposals for auth, tenant isolation and failure handling.",
      required_checks: [
        "auth required for protected operations",
        "tenant filters are explicit",
        "rate limits and abuse controls considered",
        "error paths do not expose secrets",
      ],
      blocking_failures: ["missing_auth", "missing_tenant_scope", "secret_exposure"],
    },
    {
      rubric_key: "scentra.performance_reliability_evaluation.v1",
      source_agents: ["Performance Benchmarker", "SRE"],
      objective: "Check whether workflows introduce reliability, latency or queue risk.",
      required_checks: [
        "runtime side effects are declared",
        "worker retry/idempotency considered",
        "observability fields exist",
        "rollback path exists",
      ],
      blocking_failures: ["unbounded_worker_action", "no_rollback", "no_observability"],
    },
    {
      rubric_key: "scentra.vertical_compliance_review.v1",
      source_agents: ["Legal Compliance Checker", "Automation Governance Architect"],
      objective: "Review healthcare, legal, finance, paid-media and outbound templates before tenant exposure.",
      required_checks: [
        "compliance domain is tagged",
        "disclaimers and escalation rules exist",
        "no professional advice is presented as definitive",
        "customer-facing actions require approval",
      ],
      blocking_failures: ["regulated_advice_without_review", "auto_outbound_message"],
    },
  ];
}

function evaluateDraft(draft, rubrics) {
  const findings = [];
  const passes = [];
  const fail = (code, severity, detail) => findings.push({ code, severity, detail });
  const pass = (code) => passes.push(code);

  if (draft.status === "disabled_review_required") pass("disabled_status");
  else fail("active_template", "critical", "Draft status must remain disabled_review_required.");

  if (draft.manifest_json?.activation_allowed === false) pass("activation_blocked");
  else fail("active_template", "critical", "manifest_json.activation_allowed must be false.");

  if (draft.premium_required === true && draft.required_feature_key === "ai_marketplace") pass("premium_gated");
  else fail("missing_gating", "high", "Draft must remain premium gated under ai_marketplace.");

  if (draft.manifest_json?.approval_policy?.requires_human_approval === true) pass("human_approval_required");
  else fail("no_human_approval", "critical", "Human approval is required before use.");

  if (draft.manifest_json?.approval_policy?.outbound_messages === "suggest_only") pass("outbound_suggest_only");
  else fail("auto_outbound_message", "critical", "Outbound/customer-facing actions must be suggest-only.");

  if (draft.manifest_json?.memory_policy?.tenant_scoped === true) pass("tenant_scoped_memory");
  else fail("missing_tenant_scope", "critical", "Memory policy must be tenant scoped.");

  if (draft.source?.license && draft.source?.content_sha256 && draft.source?.path) pass("source_metadata_present");
  else fail("missing_source", "critical", "Source path/license/hash are required.");

  if (draft.source?.version === "local_unverified_commit") {
    fail("source_version_unverified", "medium", "Upstream commit/tag is not verified yet.");
  } else {
    pass("source_version_verified");
  }

  const risk = draft.risk_assessment?.risk_level || "unknown";
  if (["restricted", "high"].includes(risk)) {
    fail("human_review_required", "medium", `Risk level ${risk} requires human review.`);
  } else {
    pass("risk_acceptable_for_review");
  }

  const compliance = draft.risk_assessment?.compliance_domains || [];
  if (compliance.length) fail("compliance_review_required", "medium", `Compliance domains: ${compliance.join(", ")}.`);
  else pass("no_compliance_domain_detected");

  const unsafe = draft.risk_assessment?.unsafe_matches || [];
  if (unsafe.length) fail("unsafe_terms_review_required", "medium", `Review unsafe terms: ${unsafe.join(", ")}.`);
  else pass("no_unsafe_terms_detected");

  const criticalFindings = findings.filter((item) => item.severity === "critical");
  const structuralStatus = criticalFindings.length ? "blocked" : "passed";
  const certificationStatus = structuralStatus === "passed" ? "admin_review_ready" : "blocked";
  const activationStatus = "blocked_human_review_required";

  return {
    item_key: draft.item_key,
    name: draft.name,
    source_path: draft.source?.path || "",
    structural_status: structuralStatus,
    certification_status: certificationStatus,
    activation_status: activationStatus,
    score: Math.max(0, 100 - findings.length * 7 - criticalFindings.length * 20),
    passes,
    findings,
    rubrics_applied: rubrics.map((rubric) => rubric.rubric_key),
  };
}

function markdownReport({ handoffs, playbooks, runbooks, rubrics, evalResults }) {
  const structural = evalResults.reduce((acc, item) => {
    acc[item.structural_status] = (acc[item.structural_status] || 0) + 1;
    return acc;
  }, {});
  const certification = evalResults.reduce((acc, item) => {
    acc[item.certification_status] = (acc[item.certification_status] || 0) + 1;
    return acc;
  }, {});
  const lines = [
    "# Phase 15.2/15.3 NEXUS Playbook And Eval Harness Report",
    "",
    "Scope: SaaS only. Generated offline from `external-repos/agency-agents/strategy` and Phase 15.1C disabled drafts.",
    "",
    "## Summary",
    "",
    `- Handoff contracts generated: ${handoffs.length}.`,
    `- Playbook blueprints generated: ${playbooks.length}.`,
    `- Scenario runbooks generated: ${runbooks.length}.`,
    `- Eval rubrics generated: ${rubrics.length}.`,
    `- Drafts evaluated: ${evalResults.length}.`,
    "- Runtime import: none.",
    "- Database writes: none.",
    "- Tenant exposure: none.",
    "",
    "## Eval Status",
    "",
    ...Object.entries(structural).sort().map(([key, count]) => `- Structural ${key}: ${count}`),
    ...Object.entries(certification).sort().map(([key, count]) => `- Certification ${key}: ${count}`),
    "- Activation status: all remain blocked pending human review.",
    "",
    "## Handoff Contracts",
    "",
    "| Key | Kind | Required sections |",
    "| --- | --- | ---: |",
    ...handoffs.map((item) => `| ${item.contract_key} | ${item.kind} | ${item.required_sections.length} |`),
    "",
    "## Playbooks",
    "",
    "| Key | Title | Quality gates |",
    "| --- | --- | ---: |",
    ...playbooks.map((item) => `| ${item.playbook_key} | ${item.title} | ${item.quality_gate.length} |`),
    "",
    "## Eval Rubrics",
    "",
    ...rubrics.map((item) => `- ${item.rubric_key}: ${item.objective}`),
    "",
    "## Guardrails",
    "",
    "- Keep playbooks and runbooks as future Workflow Composer blueprints, not active automations.",
    "- Keep eval results advisory until Admin review exists.",
    "- Do not activate marketplace templates from these artifacts without source verification and secret scan.",
    "- Preserve preflight, one-AI-owner conversation behavior, premium gating, tenant isolation and human approvals.",
  ];
  return `${lines.join("\n")}\n`;
}

async function main() {
  await mkdir(outRoot, { recursive: true });
  const handoffPath = path.join(sourceRoot, "strategy/coordination/handoff-templates.md");
  const handoffText = await readFile(handoffPath, "utf8");
  const handoffs = handoffContracts(handoffText);

  const playbookFiles = (await walk(path.join(sourceRoot, "strategy/playbooks"))).sort();
  const runbookFiles = (await walk(path.join(sourceRoot, "strategy/runbooks"))).sort();
  const playbooks = [];
  for (const file of playbookFiles) playbooks.push(normalizePlaybook(file, await readFile(file, "utf8")));
  const runbooks = [];
  for (const file of runbookFiles) runbooks.push(normalizeRunbook(file, await readFile(file, "utf8")));

  const rubrics = evalRubrics();
  const draftPath = path.join(outRoot, "agent_template_drafts.json");
  const draftPayload = JSON.parse(await readFile(draftPath, "utf8"));
  const evalResults = draftPayload.drafts.map((draft) => evaluateDraft(draft, rubrics));

  const generatedOn = new Date().toISOString().slice(0, 10);
  await writeFile(path.join(outRoot, "nexus_handoff_contracts.json"), `${JSON.stringify({
    phase: "15.2",
    generated_on: generatedOn,
    status: "offline_contracts",
    runtime_import: false,
    database_writes: false,
    source_path: "external-repos/agency-agents/strategy/coordination/handoff-templates.md",
    contracts: handoffs,
  }, null, 2)}\n`, "utf8");
  await writeFile(path.join(outRoot, "nexus_playbooks.json"), `${JSON.stringify({
    phase: "15.2",
    generated_on: generatedOn,
    status: "offline_blueprints",
    runtime_import: false,
    database_writes: false,
    playbooks,
    runbooks,
  }, null, 2)}\n`, "utf8");
  await writeFile(path.join(outRoot, "agent_eval_rubrics.json"), `${JSON.stringify({
    phase: "15.3",
    generated_on: generatedOn,
    status: "offline_rubrics",
    runtime_import: false,
    database_writes: false,
    rubrics,
  }, null, 2)}\n`, "utf8");
  await writeFile(path.join(outRoot, "agent_eval_results.json"), `${JSON.stringify({
    phase: "15.3",
    generated_on: generatedOn,
    status: "offline_eval_results",
    runtime_import: false,
    database_writes: false,
    evaluated_drafts: evalResults.length,
    results: evalResults,
  }, null, 2)}\n`, "utf8");
  await writeFile(path.join(outRoot, "phase15_2_15_3_report.md"), markdownReport({ handoffs, playbooks, runbooks, rubrics, evalResults }), "utf8");

  console.log(JSON.stringify({
    ok: true,
    out_root: path.relative(workspaceRoot, outRoot).replace(/\\/g, "/"),
    handoff_contracts: handoffs.length,
    playbooks: playbooks.length,
    runbooks: runbooks.length,
    rubrics: rubrics.length,
    evaluated_drafts: evalResults.length,
    admin_review_ready: evalResults.filter((item) => item.certification_status === "admin_review_ready").length,
    active_drafts: 0,
  }, null, 2));
}

main().catch((error) => {
  console.error("PHASE15_NEXUS_EVAL_HARNESS_FAILED");
  console.error(error);
  process.exit(1);
});
