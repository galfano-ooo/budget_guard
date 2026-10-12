#!/usr/bin/env node
/**
 * generate_dashboard.js
 * ------------------------------------------------------------------------
 * Rebuilds an audit_dashboard.html from an audit_asis.csv export.
 * Purely mechanical: parses the CSV, reduces each row to the handful of
 * fields the dashboard's own client-side JS needs, and stamps them into
 * dashboard_template.html (which always lives next to this script). All
 * counting/grouping/insight logic lives in the template's <script>
 * (data-driven, runs in the browser) — this file never needs to change
 * when the audit data changes shape.
 *
 * Usage:
 *   node generate_dashboard.js
 *     Reads ../exports/audit_asis.csv, writes ../exports/audit_dashboard.html
 *     (the terminal workflow documented in docs/USER_MANUAL.md).
 *
 *   node generate_dashboard.js <csv_path> <html_out_path> [--project <name>]
 *     Explicit paths — used by the action module (audit_actions.py),
 *     which exports to <Project>/Saved/BudgetGuard/ instead of the repo's
 *     exports/ folder. --project is the name shown as the page title
 *     (default "Project"); the scope line is computed from the asset paths.
 *
 * Run after any fresh `report.export_csv(...)` from the UE5 console.
 * ------------------------------------------------------------------------
 */

const fs = require("fs");
const path = require("path");

const HERE = __dirname;
const TEMPLATE_PATH = path.join(HERE, "dashboard_template.html");
const DEFAULT_CSV = path.join(HERE, "..", "exports", "audit_asis.csv");
const DEFAULT_OUT = path.join(HERE, "..", "exports", "audit_dashboard.html");

// --flag value pairs anywhere; everything else is positional (csv, html out).
const positional = [];
const flags = {};
const argv = process.argv.slice(2);
for (let i = 0; i < argv.length; i++) {
  if (argv[i].startsWith("--")) { flags[argv[i].slice(2)] = argv[i + 1]; i++; }
  else positional.push(argv[i]);
}
const CSV_PATH = positional[0] ? path.resolve(positional[0]) : DEFAULT_CSV;
const OUT_PATH = positional[1] ? path.resolve(positional[1]) : DEFAULT_OUT;
const PROJECT_NAME = flags.project || "Project";

function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// Longest shared folder path of every scanned asset, e.g. "/Game/MyContent".
function commonFolder(folders) {
  if (!folders.length) return "/Game";
  const split = folders.map((f) => f.split("/"));
  let common = split[0];
  for (const parts of split.slice(1)) {
    let n = 0;
    while (n < common.length && n < parts.length && common[n] === parts[n]) n++;
    common = common.slice(0, n);
  }
  return common.join("/") || "/Game";
}

function parseCsv(text) {
  const rows = [];
  let i = 0, field = "", row = [], inQuotes = false;
  const pushField = () => { row.push(field); field = ""; };
  const pushRow = () => { rows.push(row); row = []; };
  while (i < text.length) {
    const c = text[i];
    if (inQuotes) {
      if (c === '"') {
        if (text[i + 1] === '"') { field += '"'; i += 2; continue; }
        inQuotes = false; i++; continue;
      }
      field += c; i++; continue;
    }
    if (c === '"') { inQuotes = true; i++; continue; }
    if (c === ",") { pushField(); i++; continue; }
    if (c === "\r") { i++; continue; }
    if (c === "\n") { pushField(); pushRow(); i++; continue; }
    field += c; i++;
  }
  if (field.length || row.length) { pushField(); pushRow(); }
  const header = rows.shift();
  return rows
    .filter((r) => r.length === header.length)
    .map((r) => Object.fromEntries(header.map((h, idx) => [h, r[idx]])));
}

if (!fs.existsSync(CSV_PATH)) {
  console.error(`Missing ${CSV_PATH} — run report.export_csv(...) from the UE5 console first.`);
  process.exit(1);
}

const records = parseCsv(fs.readFileSync(CSV_PATH, "utf8"));

const compact = records.map((r) => {
  const segments = r.asset_path.split("/");
  const last = segments[segments.length - 1].split(".")[0];
  const folder = segments
    .slice(0, -1)
    .join("/")
    .replace(/^\/Game\/?/, "");
  return {
    c: r.category,
    p: last,
    f: folder,
    t: r.tier,
    s: r.severity,
    g: r.untagged === "True",
    m: r.messages,
  };
});

const scope = commonFolder(records.map((r) => r.asset_path.split("/").slice(0, -1).join("/")));
const template = fs.readFileSync(TEMPLATE_PATH, "utf8");
if (!template.includes("__RECORDS_JSON__")) {
  console.error("Template is missing the __RECORDS_JSON__ placeholder.");
  process.exit(1);
}
// Local wall-clock time of the machine that ran this script, not UTC —
// this is a "generated on <date>" stamp meant for a human reading the page,
// not a machine-comparable timestamp (that's generated_at in export_json).
function formatLocalTimestamp(date) {
  const pad = (n) => String(n).padStart(2, "0");
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())} (${tz})`;
}
const generatedAt = formatLocalTimestamp(new Date());
// split/join, not replace(): a placeholder can appear more than once, and a
// project name containing "$&" must not be read as a replacement pattern.
const out = template
  .split("__PROJECT_NAME__").join(escapeHtml(PROJECT_NAME))
  .split("__SCOPE__").join(escapeHtml(scope))
  .split("__GENERATED_AT__").join(generatedAt)
  .replace("__RECORDS_JSON__", () => JSON.stringify(compact));

fs.mkdirSync(path.dirname(OUT_PATH), { recursive: true });
fs.writeFileSync(OUT_PATH, out, "utf8");
console.log(`Wrote ${OUT_PATH} — ${compact.length} rows, generated ${generatedAt}.`);
