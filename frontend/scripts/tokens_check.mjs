// Fails when the built app still refers to a design token that no longer exists: the 4.x names of the
// deleted tokens.css (--c-*, --e-N, --t-<size>, the old radii) and the alias names app.css used to map onto
// them (--sp-*, --fs-*, --e1/--e2/--e3, --t-fast…), or any var(--x) whose --x is defined nowhere.
// Run after the build: node frontend/scripts/tokens_check.mjs
import { readdirSync, readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const dir = join(dirname(fileURLToPath(import.meta.url)), "../../static/app/assets");
const files = readdirSync(dir).filter(f => /\.(css|js)$/.test(f));
if (!files.some(f => f.endsWith(".css"))) { console.error(`tokens check: no built CSS in ${dir}`); process.exit(1); }

const DELETED = [
  /^--c-/, /^--sp-/, /^--fs-/, /^--e\d$/, /^--e-(\d|btn)$/, /^--t-/,
  /^--r-(sm|md|lg)$/, /^--font-(display|mono)$/,
  /^--(sidebar|overlay|text-on-accent|line|line-strong|line-control|accent|accent-bg|accent-line|primary-hover|focus)$/,
  /^--(ok-bg|warn-bg|danger-bg|danger-fill|q|q-bg|nfr|nfr-bg|ctl|ctl-lg|toolbar|ease|ease-exit)$/,
];

const defined = new Set();
const used = new Map();                 // name → first file that uses it
for (const f of files) {
  const text = readFileSync(join(dir, f), "utf8");
  for (const m of text.matchAll(/(--[A-Za-z0-9_-]+)\s*:/g)) defined.add(m[1]);
  for (const m of text.matchAll(/var\(\s*(--[A-Za-z0-9_-]+)/g)) if (!used.has(m[1])) used.set(m[1], f);
}

const problems = [];
for (const [name, f] of used) {
  if (DELETED.some(re => re.test(name))) problems.push(`${name} (deleted token) in ${f}`);
  else if (!defined.has(name)) problems.push(`${name} (never defined) in ${f}`);
}
if (problems.length) {
  console.error(`tokens check failed, ${problems.length} problem(s):`);
  for (const p of problems.sort()) console.error("  " + p);
  process.exit(1);
}
console.log(`tokens check passed: ${used.size} tokens used, all defined, none deleted (${files.length} files)`);
