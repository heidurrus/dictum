<script module>
  // In rail order; the hotkeys nav1…nav8 (⌘1…⌘8 by default) follow it. `opt` items are left out of the phone bar.
  export const RAIL_ITEMS = [
    { route: "meetings", path: "/meetings", icon: "meet", key: "nav.meetings" },
    { route: "library", path: "/library", icon: "lib", key: "nav.library" },
    { route: "atoms", path: "/atoms", icon: "req", key: "nav.atoms" },
    { route: "document", path: "/document", icon: "doc", key: "nav.document", opt: true },
    { route: "backlog", path: "/backlog", icon: "tree", key: "nav.decomposition", opt: true },
    { route: "ask", path: "/ask", icon: "chat", key: "nav.ask", opt: true },
    { route: "whisper", path: "/whisper", icon: "mic", key: "nav.whisper" },
  ];
  export const RAIL_SETTINGS = { route: "settings", path: "/settings", icon: "set", key: "nav.settings" };
  export const RAIL_PATHS = [...RAIL_ITEMS, RAIL_SETTINGS].map(i => i.path);
</script>

<script>
  // Navigation rail (prototype-v5 .rail): the mark, the record button, the sections, Настройки at the bottom.
  // Phone width (≤ 760 px): a bottom bar with five items; the record button moves into the page head.
  import { keyOf } from "../lib/keys.js";
  import { app, t, go } from "../lib/state.svelte.js";
  import { recordFromShell } from "../lib/capture.svelte.js";
  import { DEFAULT_HOTKEYS, comboLabel } from "../lib/hotkeys.js";

  // 24-px filled icons from the prototype.
  const I = {
    meet: '<path d="M4 5h16a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1Zm1 2v10h14V7H5Zm2 2h6v2H7V9Zm0 4h10v2H7v-2Z"/>',
    lib: '<path d="M4 4h5l2 2h9a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1Zm1 4v10h14V8H5Z"/>',
    req: '<path d="M4 6h10v2H4V6Zm0 5h16v2H4v-2Zm0 5h12v2H4v-2Zm13-11 2 2 4-4-1.4-1.4L19 4.2l-.6-.6L17 5Z"/>',
    doc: '<path d="M6 2h8l5 5v14a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1Zm1 2v16h10V8h-4V4H7Zm2 7h8v2H9v-2Zm0 4h8v2H9v-2Z"/>',
    tree: '<path d="M3 4h8v4H3V4Zm2 6h2v8h4v2H5v-10Zm6 2h8v4h-8v-4Z"/>',
    chat: '<path d="M4 3h16a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H8l-5 4V4a1 1 0 0 1 1-1Zm1 2v11.5L7.3 15H19V5H5Z"/>',
    mic: '<path d="M12 14a3 3 0 0 0 3-3V5a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3Zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.92V21h2v-3.08A7 7 0 0 0 19 11h-2Z"/>',
    set: '<path d="M12 8a4 4 0 1 1 0 8 4 4 0 0 1 0-8Zm0 2a2 2 0 1 0 0 4 2 2 0 0 0 0-4Zm-2-7h4l.5 2.6 2.2 1.3 2.5-.9 2 3.4-2 1.7v2.6l2 1.7-2 3.4-2.5-.9-2.2 1.3L14 21h-4l-.5-2.6-2.2-1.3-2.5.9-2-3.4 2-1.7v-2.6l-2-1.7 2-3.4 2.5.9 2.2-1.3L10 3Z"/>',
    more: '<path d="M6 10a2 2 0 1 1 0 4 2 2 0 0 1 0-4Zm6 0a2 2 0 1 1 0 4 2 2 0 0 1 0-4Zm6 0a2 2 0 1 1 0 4 2 2 0 0 1 0-4Z"/>',
  };

  const items = RAIL_ITEMS;
  const settings = RAIL_SETTINGS;
  const more = [{ route: "skills", path: "/skills", key: "nav.skills" }, { route: "export", path: "/export", key: "nav.export" }];

  // A transcript belongs to Встречи; Skills and Export light up Ещё.
  const current = $derived(app.route.name === "transcript" ? "meetings"
    : more.some(m => m.route === app.route.name) ? "more" : app.route.name);
  const review = $derived(app.status?.atoms?.review || 0);
  const stale = $derived(!!(app.status?.document?.stale || app.status?.document?.others_stale));

  let moreOpen = $state(false);
  let moreWrap = $state(null);
  const hk = n => comboLabel({ ...DEFAULT_HOTKEYS, ...(app.settings?.hotkeys || {}) }["nav" + n]);

  function onKey(e) {
    const key = keyOf(e);
    if (key === "Escape" && moreOpen) { moreOpen = false; return; }
    if (!(e.metaKey || e.ctrlKey) || e.altKey || e.shiftKey) return;
    if (key === ",") { e.preventDefault(); go("/settings"); return; }
    // ⌘1…⌘8 and ⌘R come from the hotkeys map, in App.svelte.
  }
  function onDoc(e) { if (moreOpen && moreWrap && !moreWrap.contains(e.target)) moreOpen = false; }
  function pickMore(path) { moreOpen = false; go(path); }
</script>

<svelte:window onkeydown={onKey} />
<svelte:document onmousedown={onDoc} />

{#snippet glyph(name)}
  <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">{@html I[name]}</svg>
{/snippet}

<nav class="rail" aria-label={t("shell.rail")}>
  <div class="logo" title={t("app.name")} aria-hidden="true">
    <svg width="24" height="14" viewBox="144 300 736 420">
      <g stroke="currentColor" stroke-width="84" stroke-linecap="round" fill="none">
        <line x1="208" y1="424" x2="208" y2="600"/><line x1="304" y1="352" x2="304" y2="672"/><line x1="400" y1="388" x2="400" y2="636"/>
        <line x1="496" y1="416" x2="816" y2="416"/><line x1="496" y1="512" x2="816" y2="512"/><line x1="496" y1="608" x2="816" y2="608"/>
      </g>
    </svg>
  </div>
  <button class="rec-fab" onclick={recordFromShell} aria-label={t("shell.record")} title={t("shell.record_tip")}><span class="dot"></span></button>

  {#each items as it, i (it.route)}
    <button class="nav-item" class:active={current === it.route} class:opt={it.opt} aria-current={current === it.route ? "page" : undefined}
            onclick={() => go(it.path)} title={`${t(it.key)} · ${hk(i + 1)}`}>
      <span class="pill">{@render glyph(it.icon)}</span>{t(it.key)}
      {#if it.route === "atoms" && review}<span class="nbadge num" title={t("nav.badge_review", { n: review })}>{review}</span>{/if}
      {#if it.route === "document" && stale}<span class="dotb" title={t("nav.badge_stale")}></span>{/if}
    </button>
  {/each}

  <div class="more-wrap opt" bind:this={moreWrap}>
    <button class="nav-item small" class:active={current === "more"} onclick={() => (moreOpen = !moreOpen)}
            aria-haspopup="menu" aria-expanded={moreOpen}>
      <span class="pill">{@render glyph("more")}</span>{t("nav.more")}
    </button>
    {#if moreOpen}
      <div class="menu more-menu" role="menu">
        {#each more as m (m.route)}
          <button class="menu-item" role="menuitem" class:on={app.route.name === m.route} onclick={() => pickMore(m.path)}>
            <span class="grow">{t(m.key)}</span></button>
        {/each}
      </div>
    {/if}
  </div>

  <span class="spacer"></span>
  <button class="nav-item" class:active={current === "settings"} aria-current={current === "settings" ? "page" : undefined}
          onclick={() => go(settings.path)} title={`${t(settings.key)} · ${hk(items.length + 1)}`}>
    <span class="pill">{@render glyph(settings.icon)}</span>{t(settings.key)}
  </button>
</nav>

<style>
  .rail { display: flex; flex-direction: column; align-items: center; padding: 14px 0 12px; gap: 4px; min-height: 0; position: relative; z-index: 30; }
  .logo { width: 40px; height: 40px; border-radius: 14px; background: var(--primary); color: var(--on-primary); display: grid; place-items: center;
    margin-bottom: 10px; flex: none; }
  .rec-fab { width: 56px; height: 56px; border: 0; border-radius: 18px; background: var(--primary-c); color: var(--on-primary-c); display: grid;
    place-items: center; margin-bottom: 14px; box-shadow: var(--shadow-1); transition: transform .15s, box-shadow .15s; cursor: pointer; flex: none; }
  .rec-fab:hover { transform: translateY(-1px); box-shadow: var(--shadow-2); }
  .rec-fab .dot { width: 14px; height: 14px; border-radius: 50%; background: var(--rec); box-shadow: 0 0 0 3px rgba(217,48,37,.2); }
  .nav-item { width: 76px; display: flex; flex-direction: column; align-items: center; gap: 4px; padding: 6px 0; border: 0; background: none;
    color: var(--text-2); font-size: 12px; line-height: 16px; font-weight: 500; letter-spacing: .01em; position: relative; cursor: pointer; flex: none; }
  .nav-item .pill { width: 56px; height: 32px; border-radius: 16px; display: grid; place-items: center; transition: background .15s, color .15s; }
  .nav-item:hover .pill { background: var(--surface-2); }
  .nav-item.active .pill { background: var(--secondary-c); color: var(--on-secondary-c); }
  .nav-item.active { color: var(--text); }
  .nav-item:focus-visible { box-shadow: none; outline: 2px solid var(--primary); outline-offset: 2px; border-radius: 8px; }
  .nav-item.small .pill { height: 24px; }
  .nbadge { position: absolute; top: 4px; right: 14px; min-width: 16px; height: 16px; border-radius: 8px; background: var(--danger); color: #fff;
    font-size: 10px; line-height: 16px; padding: 0 5px; font-weight: 600; }
  .dotb { position: absolute; top: 8px; right: 20px; width: 8px; height: 8px; border-radius: 50%; background: var(--warn); }
  .spacer { flex: 1; }
  .more-wrap { position: relative; }
  .more-menu { left: calc(100% + 4px); top: 0; min-width: 180px; }

  @media (max-width: 760px) {
    .rail { flex-direction: row; justify-content: space-around; order: 2; padding: 6px 8px; background: var(--surface); }
    .logo, .spacer, .rec-fab, .opt { display: none; }
    .nav-item { width: auto; flex: 1; }
  }
</style>
