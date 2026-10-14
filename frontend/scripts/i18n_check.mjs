// Fails when the Russian and English dictionaries drift: a key present in one and not the other,
// or a value that is empty or still equals its key. Run: node frontend/scripts/i18n_check.mjs
import { DICTS } from "../src/lib/i18n.js";

const langs = Object.keys(DICTS);
const all = new Set(langs.flatMap(l => Object.keys(DICTS[l])));
const problems = [];
for (const key of all) {
  for (const lang of langs) {
    const v = DICTS[lang][key];
    if (v === undefined) problems.push(`${lang}: missing "${key}"`);
    else if (typeof v === "string" && (!v.trim() || v === key)) problems.push(`${lang}: empty or untranslated "${key}"`);
  }
}
if (problems.length) {
  console.error(`i18n check failed, ${problems.length} problem(s):`);
  for (const p of problems.slice(0, 60)) console.error("  " + p);
  if (problems.length > 60) console.error(`  … and ${problems.length - 60} more`);
  process.exit(1);
}
console.log(`i18n ok: ${all.size} keys in ${langs.join(", ")}`);
