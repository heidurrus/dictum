// Server errors about AI setup arrive in English; show them in the UI language
// and say whether Settings can fix them (design review: no English in the RU UI).
import { t } from "./state.svelte.js";

const KNOWN = [
  [/Add your Anthropic API key/i, "err.need_key", true],
  [/Anthropic rejected the API key/i, "err.bad_key", true],
  [/“Local only”.*local model|Local only.*download/i, "err.need_local_only", true],
  [/download the local model/i, "err.need_local", true],
  [/isn't allowed to use|isn't available to this API key/i, "err.model_access", true],
  [/rate limit/i, "err.rate_limit", false],
  [/overloaded/i, "err.overloaded", false],
  [/Could not reach Anthropic/i, "err.offline", false],
];

export function explain(err) {
  const raw = err?.message || String(err || "");
  for (const [re, key, setup] of KNOWN) if (re.test(raw)) return { message: t(key), setup: setup || !!err?.body?.needs_setup, raw };
  return { message: raw, setup: !!err?.body?.needs_setup || /Settings/.test(raw), raw };
}
