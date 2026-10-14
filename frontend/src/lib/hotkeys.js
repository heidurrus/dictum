// The hotkeys map (settings "hotkeys": action → "cmd+shift+l"). "cmd" is ⌘ on a Mac and Ctrl elsewhere.
import { keyOf } from "./keys.js";

// The same map as core/settings.py DEFAULTS, used until /settings has loaded (or if it fails).
export const DEFAULT_HOTKEYS = {
  record: "cmd+r", palette: "cmd+k", theme: "cmd+shift+l", ask: "cmd+j", whisper: "alt+space",
  nav1: "cmd+1", nav2: "cmd+2", nav3: "cmd+3", nav4: "cmd+4", nav5: "cmd+5", nav6: "cmd+6", nav7: "cmd+7", nav8: "cmd+8",
};

const NAMED = { space: " ", esc: "Escape", escape: "Escape", enter: "Enter" };

function parse(combo) {
  const parts = String(combo || "").toLowerCase().split("+").map(p => p.trim()).filter(Boolean);
  const key = parts.pop() || "";
  return { cmd: parts.includes("cmd") || parts.includes("ctrl"), shift: parts.includes("shift"), alt: parts.includes("alt"),
           key: NAMED[key] ?? key };
}

export function matches(e, combo) {
  const c = parse(combo);
  if (!c.key) return false;
  const k = keyOf(e);
  return (e.metaKey || e.ctrlKey) === c.cmd && e.shiftKey === c.shift && e.altKey === c.alt
    && (k.length === 1 ? k.toLowerCase() : k) === c.key;
}

// The action bound to this key press, or null.
export function actionFor(e, map) {
  const keys = { ...DEFAULT_HOTKEYS, ...(map || {}) };
  for (const [action, combo] of Object.entries(keys)) if (matches(e, combo)) return action;
  return null;
}

// "cmd+shift+l" → "⌘⇧L" on a Mac, "Ctrl+Shift+L" elsewhere: for tooltips and the palette.
export function comboLabel(combo) {
  const mac = typeof navigator !== "undefined" && /Mac/.test(navigator.platform);
  const c = parse(combo);
  const key = c.key === " " ? "Space" : c.key.length === 1 ? c.key.toUpperCase() : c.key;
  if (mac) return (c.alt ? "⌥" : "") + (c.cmd ? "⌘" : "") + (c.shift ? "⇧" : "") + key;
  return [c.cmd && "Ctrl", c.alt && "Alt", c.shift && "Shift", key].filter(Boolean).join("+");
}
