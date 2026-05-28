import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const appArg = process.argv.find((arg) => arg.startsWith("--app="))?.split("=")[1] || "all";
const srcRoots = appArg === "frontend"
  ? ["frontend/src"]
  : appArg === "admin"
    ? ["admin-frontend/src"]
    : ["frontend/src", "admin-frontend/src"];

const blocked = [
  "Dashboard",
  "Overview",
  "Performance",
  "AI Ecosystem",
  "AI Agents",
  "Facebook Login",
  "Sales intelligence cockpit",
  "Operations Dashboard",
  "Benchmark Dashboard",
  "Footer text",
];

const ignoredFiles = new Set([
  "frontend/src/i18n.js",
  "admin-frontend/src/i18n.js",
]);

async function walk(dir) {
  const entries = await readdir(dir, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    if (entry.name === "node_modules" || entry.name === "dist") continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) files.push(...await walk(full));
    else if (/\.(jsx?|tsx?)$/.test(entry.name)) files.push(full);
  }
  return files;
}

function isUiStringLine(line, term) {
  const escaped = term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const patterns = [
    new RegExp(`>[^<]*\\b${escaped}\\b[^<]*<`),
    new RegExp(`["'\`][^"'\`]*\\b${escaped}\\b[^"'\`]*["'\`]`),
    new RegExp(`label\\s*:\\s*["'\`][^"'\`]*\\b${escaped}\\b[^"'\`]*["'\`]`),
    new RegExp(`\\[[^\\]]*["'\`][^"'\`]*\\b${escaped}\\b[^"'\`]*["'\`]`),
  ];
  return patterns.some((pattern) => pattern.test(line));
}

const findings = [];
for (const relativeRoot of srcRoots) {
  const absoluteRoot = path.join(root, relativeRoot);
  const files = await walk(absoluteRoot);
  for (const file of files) {
    const relativeFile = path.relative(root, file).replace(/\\/g, "/");
    if (ignoredFiles.has(relativeFile)) continue;
    const content = await readFile(file, "utf8");
    content.split(/\r?\n/).forEach((line, index) => {
      for (const term of blocked) {
        if (isUiStringLine(line, term)) findings.push({ file: relativeFile, line: index + 1, term, text: line.trim() });
      }
    });
  }
}

if (findings.length) {
  console.error("PHASE14_COPY_AUDIT_FAILED");
  console.error(JSON.stringify({ findings }, null, 2));
  process.exit(1);
}

console.log(JSON.stringify({ ok: true, checked_roots: srcRoots, blocked_terms: blocked.length }, null, 2));
