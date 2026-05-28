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
const maxDrafts = Number.parseInt(args.get("max-drafts") || "30", 10);

const skippedTopDirs = new Set([
  ".github",
  "examples",
  "integrations",
  "scripts",
  "strategy",
]);

const pilotPaths = new Set([
  "specialized/customer-service.md",
  "support/support-support-responder.md",
  "sales/sales-pipeline-analyst.md",
  "sales/sales-outbound-strategist.md",
  "sales/sales-discovery-coach.md",
  "specialized/sales-outreach.md",
  "paid-media/paid-media-paid-social-strategist.md",
  "paid-media/paid-media-ppc-strategist.md",
  "paid-media/paid-media-tracking-specialist.md",
  "marketing/marketing-content-creator.md",
  "marketing/marketing-instagram-curator.md",
  "specialized/healthcare-customer-service.md",
  "specialized/hospitality-guest-services.md",
  "specialized/real-estate-buyer-seller.md",
  "specialized/legal-client-intake.md",
  "specialized/retail-customer-returns.md",
  "specialized/agents-orchestrator.md",
  "specialized/automation-governance-architect.md",
  "specialized/agentic-identity-trust.md",
  "specialized/specialized-workflow-architect.md",
  "testing/testing-reality-checker.md",
  "testing/testing-evidence-collector.md",
  "testing/testing-api-tester.md",
  "testing/testing-performance-benchmarker.md",
  "engineering/engineering-security-engineer.md",
  "engineering/engineering-sre.md",
  "engineering/engineering-incident-response-commander.md",
  "engineering/engineering-database-optimizer.md",
  "engineering/engineering-technical-writer.md",
]);

const internalCategoryHints = [
  "engineering/",
  "testing/",
  "support/support-infrastructure",
  "support/support-legal-compliance",
  "specialized/agents-orchestrator",
  "specialized/automation-governance",
  "specialized/agentic-identity",
  "specialized/specialized-workflow",
];

const deferCategoryHints = [
  "academic/",
  "game-development/",
  "spatial-computing/",
];

const complianceKeywords = {
  healthcare: ["healthcare", "medical advice", "patients", "clinic", "hipaa", "clinical emergency"],
  legal: ["legal advice", "lawyer", "attorney", "law firm", "court", "legal client"],
  finance: ["financial advice", "investment", "banking", "insurance", "tax compliance"],
  paid_media: ["paid media", "ads", "advertising", "ppc", "campaign budget", "roas"],
  security: ["credential", "secret", "api key", "private key", "vulnerability", "incident response"],
  outbound: ["outbound", "sales outreach", "cold email", "prospecting", "follow-up"],
};

const unsafeToolKeywords = [
  "bash",
  "shell",
  "rm -rf",
  "delete files",
  "execute script",
  "webfetch",
  "websearch",
  "filesystem",
  "credential",
  "secret",
  "token",
  "api key",
  "private key",
];

async function walk(dir) {
  const entries = await readdir(dir, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (dir === sourceRoot && skippedTopDirs.has(entry.name)) continue;
      files.push(...await walk(full));
    } else if (entry.name.endsWith(".md")) {
      files.push(full);
    }
  }
  return files;
}

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

function sentence(value, max = 240) {
  const clean = ascii(value).replace(/\s+/g, " ");
  return clean.length > max ? `${clean.slice(0, max - 3).trim()}...` : clean;
}

function slugify(value) {
  return ascii(value)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 80) || "agent";
}

function parseFrontmatter(content) {
  if (!content.startsWith("---")) return { frontmatter: null, body: content };
  const lines = content.split(/\r?\n/);
  let end = -1;
  for (let i = 1; i < lines.length; i += 1) {
    if (lines[i].trim() === "---") {
      end = i;
      break;
    }
  }
  if (end < 0) return { frontmatter: null, body: content };
  const frontmatter = {};
  for (const line of lines.slice(1, end)) {
    const match = /^([A-Za-z0-9_-]+):\s*(.*)$/.exec(line);
    if (!match) continue;
    const key = match[1].trim();
    const value = match[2].trim().replace(/^["']|["']$/g, "");
    frontmatter[key] = ascii(value);
  }
  return { frontmatter, body: lines.slice(end + 1).join("\n") };
}

function extractSections(body) {
  const sections = {};
  let current = "intro";
  for (const raw of body.split(/\r?\n/)) {
    const line = ascii(raw);
    const heading = /^(#{1,4})\s+(.+)$/.exec(line);
    if (heading) {
      current = heading[2]
        .replace(/\*\*/g, "")
        .replace(/agent personality$/i, "Agent")
        .trim();
      sections[current] = sections[current] || [];
      continue;
    }
    if (!sections[current]) sections[current] = [];
    if (line) sections[current].push(line);
  }
  return sections;
}

function findSection(sections, patterns) {
  const key = Object.keys(sections).find((name) => patterns.some((pattern) => pattern.test(name)));
  return key ? sections[key] : [];
}

function firstBullets(lines, max = 6) {
  const bullets = [];
  for (const line of lines) {
    const match = /^[-*]\s+(.+)$/.exec(line);
    if (match) bullets.push(sentence(match[1], 220));
    if (bullets.length >= max) break;
  }
  return bullets;
}

function compactSection(lines, max = 700) {
  const text = lines
    .filter((line) => !line.startsWith("```") && !line.startsWith("|"))
    .join(" ")
    .replace(/#+/g, "")
    .replace(/\s+/g, " ");
  return sentence(text, max);
}

function detectCompliance(text) {
  const lower = text.toLowerCase();
  return Object.entries(complianceKeywords)
    .filter(([, terms]) => terms.some((term) => lower.includes(term)))
    .map(([key]) => key);
}

function detectIndustry(relativePath, text) {
  if (relativePath.includes("healthcare")) return "healthcare";
  if (relativePath.includes("hospitality")) return "hospitality";
  if (relativePath.includes("real-estate")) return "real_estate";
  if (relativePath.includes("retail") || relativePath.includes("ecommerce")) return "retail_ecommerce";
  if (relativePath.includes("restaurant")) return "restaurant";
  if (relativePath.includes("legal")) return "legal";
  if (relativePath.startsWith("finance/")) return "financial_services";
  return "general";
}

function mapRole(relativePath, name, description) {
  const haystack = `${relativePath} ${name} ${description}`.toLowerCase();
  if (haystack.includes("orchestrator")) return "agent_orchestrator";
  if (haystack.includes("workflow")) return "workflow_architect";
  if (haystack.includes("governance") || haystack.includes("identity") || haystack.includes("trust")) return "ai_governance";
  if (haystack.includes("pipeline") || haystack.includes("crm")) return "crm_intelligence";
  if (haystack.includes("sales") || haystack.includes("outbound") || haystack.includes("deal")) return "sales";
  if (haystack.includes("paid-media") || haystack.includes("ppc") || haystack.includes("marketing") || haystack.includes("instagram") || haystack.includes("content")) return "campaign_strategist";
  if (haystack.includes("support") || haystack.includes("customer-service") || haystack.includes("returns") || haystack.includes("guest")) return "support";
  if (haystack.includes("retention")) return "retention";
  if (haystack.includes("sre") || haystack.includes("incident") || haystack.includes("database") || haystack.includes("security")) return "operations";
  if (haystack.includes("evidence") || haystack.includes("reality") || haystack.includes("tester") || haystack.includes("benchmarker")) return "qa_evaluator";
  return "advisor";
}

function recommendedSurface(relativePath, role, complianceDomains) {
  const lower = relativePath.toLowerCase();
  if (deferCategoryHints.some((hint) => lower.startsWith(hint))) return "defer";
  if (internalCategoryHints.some((hint) => lower.startsWith(hint))) return "internal_admin_eval";
  if (["qa_evaluator", "operations", "ai_governance", "workflow_architect", "agent_orchestrator"].includes(role)) return "internal_admin_eval";
  if (complianceDomains.includes("security")) return "internal_admin_eval";
  return "tenant_marketplace_draft";
}

function riskFor({ relativePath, body, frontmatter, complianceDomains, surface }) {
  const text = `${relativePath} ${body} ${Object.values(frontmatter || {}).join(" ")}`.toLowerCase();
  const declaredTools = String(frontmatter?.tools || "");
  const toolText = `${declaredTools} ${body.match(/tools?:[^\n]+/gi)?.join(" ") || ""}`.toLowerCase();
  const unsafeMatches = unsafeToolKeywords.filter((term) => toolText.includes(term));
  const reasons = [];
  let risk = "medium";
  if (surface === "defer") {
    risk = "high";
    reasons.push("Category is not aligned with near-term Scentra SaaS use.");
  }
  if (complianceDomains.length) {
    risk = "high";
    reasons.push(`Compliance-sensitive domain: ${complianceDomains.join(", ")}.`);
  }
  if (/(send|message|whatsapp|dm|campaign|outbound|ads|advertising|cold email|prospecting)/.test(text)) {
    risk = "high";
    reasons.push("Can influence outbound/customer-facing communication.");
  }
  if (unsafeMatches.length) {
    risk = "restricted";
    reasons.push(`Unsafe/direct tool terms detected: ${unsafeMatches.slice(0, 6).join(", ")}.`);
  }
  if (!reasons.length) reasons.push("General review required before tenant use.");
  return { risk, reasons, unsafe_matches: unsafeMatches };
}

function recommendedTools(role, risk) {
  const base = ["approval.required", "agent.preflight", "memory.tenant_scoped"];
  const byRole = {
    sales: ["crm.read", "conversation.suggest_reply", "advisor.create_action_draft"],
    support: ["knowledge.search", "conversation.suggest_reply", "crm.read"],
    crm_intelligence: ["crm.read", "analytics.read", "segments.suggest"],
    campaign_strategist: ["analytics.read", "campaigns.create_draft", "triggers.suggest", "remarketing.suggest"],
    retention: ["crm.read", "analytics.read", "remarketing.suggest"],
    operations: ["observability.read", "reliability.read", "advisor.create_action_draft"],
    qa_evaluator: ["evidence.read", "eval.run", "report.generate"],
    ai_governance: ["audit.read", "policy.suggest", "approval.required"],
    workflow_architect: ["workflow.create_draft", "triggers.suggest", "approval.required"],
    agent_orchestrator: ["agent_os.plan", "handoff.create", "eval.run"],
    advisor: ["analytics.read", "advisor.create_action_draft"],
  };
  const tools = [...new Set([...base, ...(byRole[role] || byRole.advisor)])];
  if (risk === "restricted") tools.push("sandbox.required");
  return tools;
}

function permissionsFor(role, surface) {
  const permissions = new Set(["agents:install", "approval:required"]);
  if (["sales", "support", "crm_intelligence", "retention"].includes(role)) permissions.add("crm:read");
  if (["crm_intelligence", "campaign_strategist", "retention", "operations", "advisor"].includes(role)) permissions.add("analytics:read");
  if (role === "support") permissions.add("knowledge:read");
  if (["campaign_strategist", "workflow_architect", "agent_orchestrator"].includes(role)) permissions.add("apps:write");
  if (surface === "internal_admin_eval") permissions.add("analytics:read");
  return [...permissions];
}

function buildPromptTemplate({ name, role, industry, mission, critical_rules: rules = [], recommended_tools: tools = [] }) {
  const safeRules = [
    "No ejecutes acciones reales sin aprobacion humana y preflight aprobado.",
    "No envies mensajes a clientes; solo sugiere respuestas o crea borradores.",
    "Respeta aislamiento multi-tenant, memoria tenant-scoped y one-AI-owner por conversacion.",
    "Si falta contexto, reporta incertidumbre y pide revision humana.",
  ];
  return [
    `Eres ${name}, un agente ${role} para Scentra.`,
    `Industria objetivo: ${industry}.`,
    "",
    "Mision:",
    mission || "Ayudar al equipo con analisis, recomendaciones y borradores seguros.",
    "",
    "Reglas obligatorias:",
    ...safeRules.map((rule) => `- ${rule}`),
    ...rules.slice(0, 4).map((rule) => `- ${rule}`),
    "",
    "Herramientas permitidas en Scentra:",
    ...tools.map((tool) => `- ${tool}`),
    "",
    "Salida esperada:",
    "- Resumen accionable.",
    "- Riesgos y supuestos.",
    "- Siguiente accion recomendada en modo borrador.",
  ].join("\n");
}

function normalizeAgent(file, content) {
  const relativePath = rel(file);
  const { frontmatter, body } = parseFrontmatter(content);
  if (!frontmatter?.name || !frontmatter?.description) return null;
  const sections = extractSections(body);
  const name = sentence(frontmatter.name, 120);
  const description = sentence(frontmatter.description, 500);
  const mission = compactSection(findSection(sections, [/core mission/i, /mission/i]), 700) || description;
  const rules = firstBullets(findSection(sections, [/critical rules/i, /rules/i]), 8);
  const deliverables = firstBullets(findSection(sections, [/deliverables/i, /technical deliverables/i]), 8);
  const successMetrics = firstBullets(findSection(sections, [/success metrics/i, /metrics/i]), 8);
  const fullText = `${name} ${description} ${body}`;
  const complianceDomains = detectCompliance(fullText);
  const industry = detectIndustry(relativePath, fullText);
  const role = mapRole(relativePath, name, description);
  const surface = recommendedSurface(relativePath, role, complianceDomains);
  const risk = riskFor({ relativePath, body, frontmatter, complianceDomains, surface });
  const tools = recommendedTools(role, risk.risk);
  const pilot = pilotPaths.has(relativePath);
  const draftStatus = pilot ? "disabled_review_required" : "inventory_only";
  const contentHash = createHash("sha256").update(content, "utf8").digest("hex");
  const topDir = relativePath.split("/")[0] || "uncategorized";
  const itemKey = `external.agency_agents.${slugify(relativePath.replace(/\.md$/, ""))}.v1`;
  return {
    source_path: relativePath,
    source_repo: "external-repos/agency-agents",
    source_license: "MIT",
    source_version: "local_unverified_commit",
    source_content_sha256: contentHash,
    category: topDir,
    name,
    description,
    vibe: sentence(frontmatter.vibe || "", 220),
    role,
    industry,
    recommended_surface: surface,
    draft_status: draftStatus,
    risk_level: risk.risk,
    risk_reasons: risk.reasons,
    unsafe_matches: risk.unsafe_matches,
    compliance_domains: complianceDomains,
    sections_detected: Object.keys(sections).slice(0, 18),
    mission,
    critical_rules: rules,
    deliverables,
    success_metrics: successMetrics,
    recommended_tools: tools,
    recommended_permissions: permissionsFor(role, surface),
    pilot_candidate: pilot,
    item_key: itemKey,
  };
}

function toDraft(agent) {
  const tags = [...new Set([
    "external-agency-agents",
    agent.category,
    agent.role,
    agent.industry,
    ...agent.compliance_domains,
    agent.risk_level,
  ].filter(Boolean))];
  return {
    item_key: agent.item_key,
    item_type: "agent_template",
    category: agent.recommended_surface === "internal_admin_eval" ? "internal_eval" : "agent_store",
    name: agent.name,
    description: agent.description,
    status: "disabled_review_required",
    premium_required: true,
    required_feature_key: "ai_marketplace",
    source: {
      repo: agent.source_repo,
      path: agent.source_path,
      license: agent.source_license,
      version: agent.source_version,
      content_sha256: agent.source_content_sha256,
    },
    manifest_json: {
      install_mode: "draft_metadata_only",
      recommended_status: "draft",
      agent_role: agent.role,
      industry: agent.industry,
      source_agent_name: agent.name,
      system_prompt_template_es: buildPromptTemplate(agent),
      memory_policy: {
        short_term: true,
        semantic: true,
        tenant_scoped: true,
        collective_memory_allowed: true,
        export_delete_controls_required: true,
      },
      approval_policy: {
        requires_human_approval: true,
        can_execute_safe_actions: false,
        outbound_messages: "suggest_only",
        tool_execution: "approval_first",
      },
      review_required: true,
      activation_allowed: false,
    },
    permissions_json: agent.recommended_permissions,
    tags_json: tags,
    risk_assessment: {
      risk_level: agent.risk_level,
      risk_reasons: agent.risk_reasons,
      compliance_domains: agent.compliance_domains,
      unsafe_matches: agent.unsafe_matches,
      required_reviews: [
        "security_review",
        "prompt_review",
        "tool_scope_review",
        "tenant_isolation_review",
        ...(agent.compliance_domains.length ? ["compliance_review"] : []),
      ],
    },
  };
}

function csvEscape(value) {
  return `"${String(value ?? "").replace(/"/g, '""')}"`;
}

function summarize(items, key) {
  return items.reduce((acc, item) => {
    const value = item[key] || "unknown";
    acc[value] = (acc[value] || 0) + 1;
    return acc;
  }, {});
}

function markdownReport({ inventory, drafts, strategyDocs, license }) {
  const categoryCounts = summarize(inventory, "category");
  const riskCounts = summarize(inventory, "risk_level");
  const surfaceCounts = summarize(inventory, "recommended_surface");
  const lines = [
    "# Phase 15.1B/15.1C Agent Template Intake Report",
    "",
    "Scope: SaaS only. Generated from `external-repos/agency-agents/` in read-only mode.",
    "",
    "## Summary",
    "",
    `- License detected: ${license}.`,
    `- Normalized agent templates: ${inventory.length}.`,
    `- Strategy/playbook docs detected: ${strategyDocs.length}.`,
    `- Disabled draft candidates generated: ${drafts.length}.`,
    "- Runtime import: none.",
    "- External scripts executed: none.",
    "- Database writes: none.",
    "",
    "## Counts By Risk",
    "",
    ...Object.entries(riskCounts).sort().map(([key, count]) => `- ${key}: ${count}`),
    "",
    "## Counts By Surface",
    "",
    ...Object.entries(surfaceCounts).sort().map(([key, count]) => `- ${key}: ${count}`),
    "",
    "## Counts By Category",
    "",
    ...Object.entries(categoryCounts).sort().map(([key, count]) => `- ${key}: ${count}`),
    "",
    "## Draft Candidates",
    "",
    "| Item key | Name | Surface | Risk | Industry | Source |",
    "| --- | --- | --- | --- | --- | --- |",
    ...drafts.map((draft) => {
      const risk = draft.risk_assessment?.risk_level || "";
      return `| ${draft.item_key} | ${draft.name} | ${draft.category} | ${risk} | ${draft.manifest_json.industry} | ${draft.source.path} |`;
    }),
    "",
    "## Mandatory Guardrails",
    "",
    "- Keep every generated item disabled until Admin/security review.",
    "- Do not map external tool declarations directly to Scentra tools.",
    "- Keep outbound/customer-facing behavior as suggest-only until explicit approval.",
    "- Preserve tenant isolation, premium gating, preflight, budgets, memory governance and one-AI-owner behavior.",
    "- Confirm upstream URL/commit/tag and run a formal secret scan before commercial use.",
  ];
  return `${lines.join("\n")}\n`;
}

async function main() {
  await mkdir(outRoot, { recursive: true });
  const licenseText = await readFile(path.join(sourceRoot, "LICENSE"), "utf8").catch(() => "");
  const license = /MIT License/i.test(licenseText) ? "MIT" : "unverified";
  const files = await walk(sourceRoot);
  const inventory = [];
  for (const file of files) {
    const content = await readFile(file, "utf8");
    const normalized = normalizeAgent(file, content);
    if (normalized) inventory.push(normalized);
  }
  inventory.sort((a, b) => a.source_path.localeCompare(b.source_path));
  const strategyDocs = (await walk(path.join(sourceRoot, "strategy")).catch(() => []))
    .map((file) => path.relative(sourceRoot, file).replace(/\\/g, "/"))
    .sort();

  const drafts = inventory
    .filter((item) => item.pilot_candidate && item.recommended_surface !== "defer")
    .sort((a, b) => {
      const surfaceA = a.recommended_surface === "tenant_marketplace_draft" ? 0 : 1;
      const surfaceB = b.recommended_surface === "tenant_marketplace_draft" ? 0 : 1;
      return surfaceA - surfaceB || a.source_path.localeCompare(b.source_path);
    })
    .slice(0, maxDrafts)
    .map(toDraft);

  const generatedOn = new Date().toISOString().slice(0, 10);
  const payload = {
    phase: "15.1B",
    generated_on: generatedOn,
    source_root: path.relative(workspaceRoot, sourceRoot).replace(/\\/g, "/"),
    source_license: license,
    source_version: "local_unverified_commit",
    runtime_import: false,
    external_scripts_executed: false,
    inventory_count: inventory.length,
    strategy_doc_count: strategyDocs.length,
    inventory,
  };
  const draftPayload = {
    phase: "15.1C",
    generated_on: generatedOn,
    status: "disabled_draft_only",
    source_root: path.relative(workspaceRoot, sourceRoot).replace(/\\/g, "/"),
    source_license: license,
    source_version: "local_unverified_commit",
    runtime_import: false,
    database_writes: false,
    drafts,
  };

  await writeFile(path.join(outRoot, "agent_template_inventory.json"), `${JSON.stringify(payload, null, 2)}\n`, "utf8");
  await writeFile(path.join(outRoot, "agent_template_drafts.json"), `${JSON.stringify(draftPayload, null, 2)}\n`, "utf8");
  await writeFile(path.join(outRoot, "agent_template_risk_report.md"), markdownReport({ inventory, drafts, strategyDocs, license }), "utf8");
  const csvLines = [
    ["source_path", "name", "category", "role", "industry", "surface", "risk_level", "draft_status", "compliance_domains"].map(csvEscape).join(","),
    ...inventory.map((item) => [
      item.source_path,
      item.name,
      item.category,
      item.role,
      item.industry,
      item.recommended_surface,
      item.risk_level,
      item.draft_status,
      item.compliance_domains.join("|"),
    ].map(csvEscape).join(",")),
  ];
  await writeFile(path.join(outRoot, "agent_template_inventory.csv"), `${csvLines.join("\n")}\n`, "utf8");

  console.log(JSON.stringify({
    ok: true,
    source_root: path.relative(workspaceRoot, sourceRoot).replace(/\\/g, "/"),
    out_root: path.relative(workspaceRoot, outRoot).replace(/\\/g, "/"),
    inventory_count: inventory.length,
    strategy_doc_count: strategyDocs.length,
    draft_count: drafts.length,
    license,
  }, null, 2));
}

main().catch((error) => {
  console.error("PHASE15_AGENT_TEMPLATE_INTAKE_FAILED");
  console.error(error);
  process.exit(1);
});
