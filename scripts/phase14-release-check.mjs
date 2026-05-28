import { access, readFile } from "node:fs/promises";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const workspaceRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const saasRoot = path.join(workspaceRoot, "saas-version");

const requiredFiles = [
  "AGENTS.md",
  "docs/AGENT_RULES.md",
  "docs/PROJECT_CONTEXT.md",
  "ai-memory/CURRENT_STATE.md",
  "tasks/TASK_STATE.md",
  "docs/SAAS_PROJECT_STATUS.md",
  "docs/SEGUIMIENTO_PROYECTO_SAAS_ES.md",
  "docs/LOCALIZATION_PRODUCT_OPS.md",
  "architecture/LOCALIZATION_PRODUCT_OPS.md",
  "decisions/ADR-038-phase14-localization-product-ops.md",
  "saas-version/frontend/src/i18n.js",
  "saas-version/admin-frontend/src/i18n.js",
  "saas-version/scripts/phase14-copy-audit.mjs",
];

const missing = [];
for (const file of requiredFiles) {
  try {
    await access(path.join(workspaceRoot, file));
  } catch {
    missing.push(file);
  }
}

const docs = await Promise.all([
  readFile(path.join(workspaceRoot, "docs/SAAS_PROJECT_STATUS.md"), "utf8"),
  readFile(path.join(workspaceRoot, "docs/SEGUIMIENTO_PROYECTO_SAAS_ES.md"), "utf8"),
  readFile(path.join(workspaceRoot, "docs/ENVIRONMENT.md"), "utf8"),
]);

const docFindings = [];
if (!docs[0].includes("| 14 | Localization & Product Ops | 100% |")) docFindings.push("SAAS_PROJECT_STATUS phase 14 is not 100%.");
if (!docs[1].includes("| 14 | Localization & Product Ops | 100% |")) docFindings.push("SEGUIMIENTO phase 14 is not 100%.");
if (!docs[2].includes("VITE_APP_LOCALE")) docFindings.push("ENVIRONMENT missing VITE_APP_LOCALE.");
if (!docs[2].includes("VITE_ADMIN_LOCALE")) docFindings.push("ENVIRONMENT missing VITE_ADMIN_LOCALE.");

const copyAudit = spawnSync(process.execPath, [path.join(saasRoot, "scripts/phase14-copy-audit.mjs")], {
  cwd: workspaceRoot,
  encoding: "utf8",
});

if (copyAudit.status !== 0) {
  docFindings.push(`copy audit failed: ${copyAudit.stderr || copyAudit.stdout}`);
}

if (missing.length || docFindings.length) {
  console.error("PHASE14_RELEASE_CHECK_FAILED");
  console.error(JSON.stringify({ missing, findings: docFindings }, null, 2));
  process.exit(1);
}

console.log(JSON.stringify({
  ok: true,
  saas_root: path.relative(workspaceRoot, saasRoot).replace(/\\/g, "/"),
  required_files: requiredFiles.length,
  checks: ["memory_docs", "phase_status", "locale_env_docs", "copy_audit"],
}, null, 2));
