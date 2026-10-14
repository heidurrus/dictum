<script>
  // Settings → Горячие клавиши (5.0 C9): the settings `hotkeys` map as rows. Double-click a row or "Изменить", then press
  // the new combination; a combination another action has, or one macOS keeps, is refused with a message. "Сбросить"
  // puts the default back. Status per row from /api/hotkeys/status for the global ones (⌥Space, ⌘R).
  import { api } from "../lib/api.js";
  import { keyOf } from "../lib/keys.js";
  import { DEFAULT_HOTKEYS, comboLabel } from "../lib/hotkeys.js";
  import { RAIL_ITEMS, RAIL_SETTINGS } from "./Rail.svelte";
  import { app, t } from "../lib/state.svelte.js";

  let { s, save } = $props();

  let status = $state(null);                 // {available, whisper, record}
  let recording = $state(null);              // the action being rebound
  let message = $state(null);                // {action, text}
  async function loadStatus() { status = await api("/api/hotkeys/status").catch(() => null); }
  $effect(() => { loadStatus(); });

  const ACTIONS = Object.keys(DEFAULT_HOTKEYS);
  const SYSTEM = new Set(["cmd+space", "cmd+tab", "cmd+q", "cmd+h", "cmd+m", "cmd+alt+esc", "ctrl+space"]);
  const ORDER = ["cmd", "ctrl", "alt", "shift"];
  const mac = typeof navigator !== "undefined" && /Mac/.test(navigator.platform);
  const map = $derived({ ...DEFAULT_HOTKEYS, ...(s.hotkeys || {}) });
  const NAV = [...RAIL_ITEMS, RAIL_SETTINGS];
  const name = a => /^nav\d$/.test(a) ? t("set.k.nav", { name: t(NAV[Number(a.slice(3)) - 1]?.key || "") }) : t("set.k." + a);

  // Same spelling and order as core/settings.normalize_combo.
  function canon(combo) {
    const parts = String(combo || "").toLowerCase().split("+").map(p => p.trim()).filter(Boolean);
    const key = parts.pop() || "";
    const mods = parts.map(p => ({ command: "cmd", meta: "cmd", control: "ctrl", option: "alt", opt: "alt" }[p] || p));
    return [...ORDER.filter(m => mods.includes(m)), key].join("+");
  }
  const NAMED = { " ": "space", Escape: "esc", Enter: "enter", Tab: "tab", Backspace: "backspace",
                  ArrowLeft: "left", ArrowRight: "right", ArrowUp: "up", ArrowDown: "down" };
  function comboOf(e) {
    const k = keyOf(e);
    if (["Meta", "Control", "Alt", "Shift", "CapsLock", "Fn"].includes(k)) return null;   // still holding modifiers
    const key = NAMED[k] || (/^F\d{1,2}$/.test(k) ? k.toLowerCase() : k.length === 1 ? k.toLowerCase() : null);
    if (!key) return null;
    const mods = [];
    if (e.metaKey || (!mac && e.ctrlKey)) mods.push("cmd");
    if (mac && e.ctrlKey) mods.push("ctrl");
    if (e.altKey) mods.push("alt");
    if (e.shiftKey) mods.push("shift");
    return canon([...mods, key].join("+"));
  }

  function problem(action, combo) {
    if (!combo.includes("+") && !/^f\d{1,2}$/.test(combo)) return t("set.k.needs_mod");
    if (SYSTEM.has(combo)) return t("set.k.system", { keys: comboLabel(combo) });
    const other = ACTIONS.find(a => a !== action && canon(map[a]) === combo);
    return other ? t("set.k.conflict", { keys: comboLabel(combo), action: name(other) }) : null;
  }
  async function apply(action, combo) {
    const why = problem(action, combo);
    if (why) { message = { action, text: why, bad: true }; return; }
    try {
      await save({ hotkeys: { [action]: combo } }, { rethrow: true });
      message = { action, text: t("set.k.saved", { keys: comboLabel(combo) }) };
      loadStatus();
    } catch (err) { message = { action, text: err.message, bad: true }; }
  }

  function start(action) { recording = action; message = null; }
  function onKey(e) {
    if (!recording) return;
    e.preventDefault();
    e.stopPropagation();                      // the app's key handler must not act on the keys being recorded
    if (e.key === "Escape" && !e.metaKey && !e.altKey && !e.ctrlKey && !e.shiftKey) { recording = null; return; }
    const combo = comboOf(e);
    if (!combo) return;
    const action = recording;
    recording = null;
    apply(action, combo);
  }
  $effect(() => {
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  });

  const stateOf = a => {
    if (status?.available && (a === "whisper" || a === "record")) return status[a] === "off" ? "window" : status[a];
    return "window";
  };
</script>

<div class="setcard card-m hotkeys">
  <h3>{t("set.k.title")}</h3><p class="d">{t("set.k.d")}</p>
  {#each ACTIONS as a (a)}
    {@const st = stateOf(a)}
    <div class="row hk" data-action={a} class:rec={recording === a} ondblclick={() => start(a)} role="group" aria-label={name(a)}>
      <div class="l"><b>{name(a)}</b>
        {#if message?.action === a}<small class="msg" class:bad={message.bad}>{message.text}</small>
        {:else}<small class="hk-status" data-status={st}>{t("set.k.st." + st)}</small>{/if}</div>
      {#if recording === a}
        <span class="kbd rec-kbd">{t("set.k.press")}</span>
        <button class="btn sm ghost" onclick={() => (recording = null)}>{t("at.cancel")}</button>
      {:else}
        <span class="kbd combo">{comboLabel(map[a])}</span>
        <button class="btn sm" onclick={() => start(a)}>{t("set.k.change")}</button>
        <button class="btn sm ghost" disabled={canon(map[a]) === DEFAULT_HOTKEYS[a]} onclick={() => apply(a, DEFAULT_HOTKEYS[a])}>{t("set.k.reset")}</button>
      {/if}
    </div>
  {/each}
</div>

<div class="setcard card-m">
  <label class="row">
    <span class="l"><b>{t("set.k.menubar")}</b><small>{t("set.k.menubar_d")}</small></span>
    <input type="checkbox" class="switch" checked={s.menubar} onchange={e => save({ menubar: e.currentTarget.checked })} aria-label={t("set.k.menubar")} />
  </label>
</div>

<style>
  .hk { user-select: none; }
  .hk.rec { background: var(--primary-c); border-radius: 12px; padding-left: 10px; padding-right: 10px; }
  .kbd.combo, .rec-kbd { height: 24px; padding: 0 10px; font-size: 13px; }
  .msg { color: var(--ok) !important; }
  .msg.bad { color: var(--danger) !important; }
  .hk-status[data-status="taken"], .hk-status[data-status="invalid"] { color: var(--warn) !important; }
</style>
