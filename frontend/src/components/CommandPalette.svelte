<script>
  import { keyOf } from "../lib/keys.js";
  // ⌘K: every screen, source, document, requirement and command, by name (redesign §5.15).
  import Icon from "./Icon.svelte";
  import { api } from "../lib/api.js";
  import { app, t, go, setTheme, isDark, switchProject } from "../lib/state.svelte.js";
  import { DEFAULT_HOTKEYS, comboLabel } from "../lib/hotkeys.js";
  import { reopenOnboarding, startTutorial } from "../lib/onboarding.svelte.js";

  let query = $state("");
  let index = $state(0);
  let atoms = $state([]);
  let list = $state(null);
  const PREFIX = { functional: "FR", nfr: "NFR", question: "Q", business: "BR", risk: "RSK", current: "AS" };

  $effect(() => {
    if (!app.palette) return;
    query = ""; index = 0;
    const pid = app.currentProjectId;
    if (pid) api(`/api/projects/${pid}/atoms`).then(b => { atoms = (b.atoms || []).filter(a => a.status !== "rejected"); }).catch(() => { atoms = []; });
  });

  // In rail order, with the rail's shortcuts; Skills and Export are reached from here.
  const hk = $derived({ ...DEFAULT_HOTKEYS, ...(app.settings?.hotkeys || {}) });
  const screens = $derived([
    { icon: "sources", label: t("nav.meetings"), keys: [comboLabel(hk.nav1)], run: () => go("/meetings") },
    { icon: "file", label: t("nav.library"), keys: [comboLabel(hk.nav2)], run: () => go("/library") },
    { icon: "atoms", label: t("nav.atoms"), keys: [comboLabel(hk.nav3)], run: () => go("/atoms") },
    { icon: "doc", label: t("nav.document"), keys: [comboLabel(hk.nav4)], run: () => go("/document") },
    { icon: "tree", label: t("nav.decomposition"), keys: [comboLabel(hk.nav5)], run: () => go("/backlog") },
    { icon: "search", label: t("nav.ask"), keys: [comboLabel(hk.nav6)], run: () => go("/ask") },
    { icon: "mic", label: t("nav.whisper"), keys: [comboLabel(hk.nav7)], run: () => go("/whisper") },
    { icon: "gear", label: t("nav.settings"), keys: [comboLabel(hk.nav8)], run: () => go("/settings") },
    { icon: "skills", label: t("nav.skills"), run: () => go("/skills") },
    { icon: "export", label: t("nav.export"), run: () => go("/export") },
  ]);
  const commands = $derived([
    { icon: isDark() ? "sun" : "moon", label: t(isDark() ? "cmd.light" : "cmd.dark"), keys: [comboLabel(hk.theme)], run: () => setTheme(isDark() ? "light" : "dark") },
    { icon: "help", label: t("help.tips"), run: startTutorial },
    { icon: "help", label: t("help.onboarding"), run: reopenOnboarding },
  ]);

  const groups = $derived.by(() => {
    const q = query.trim().toLowerCase();
    const hit = s => !q || (s || "").toLowerCase().includes(q);
    const out = [];
    const push = (title, items) => { if (items.length) out.push({ title, items }); };
    push(t("cmd.g.go"), screens.filter(s => hit(s.label)));
    push(t("nav.meetings"), app.sources.filter(s => hit(s.title)).slice(0, q ? 8 : 4)
      .map(s => ({ icon: s.kind === "audio" ? "wave" : "file", label: s.title, run: () => go(`/source/${s.id}`) })));
    push(t("nav.document"), app.documents.filter(d => hit(d.title) || hit(d.short)).slice(0, 8)
      .map(d => ({ icon: "doc", label: d.title, hint: d.version ? "v" + d.version : "", run: () => go(`/document/${d.id}`) })));
    if (q) push(t("nav.atoms"), atoms.filter(a => hit(a.statement)).slice(0, 8)
      .map(a => ({ icon: "atoms", label: a.statement, hint: PREFIX[a.type], run: () => go(`/atoms/atom/${a.id}`) })));
    push(t("cmd.g.project"), app.projects.filter(p => p.id !== app.currentProjectId && hit(p.name)).slice(0, q ? 8 : 3)
      .map(p => ({ icon: "cube", label: p.name, run: () => switchProject(p.id) })));
    push(t("cmd.g.commands"), commands.filter(c => hit(c.label)));
    return out;
  });
  const flat = $derived(groups.flatMap(g => g.items));
  $effect(() => { query; index = 0; });

  function run(item) { app.palette = false; item?.run(); }
  function onKey(e) {
    const key = keyOf(e);
    if (!app.palette) return;
    if (key === "Escape") { e.preventDefault(); e.stopPropagation(); app.palette = false; }
    else if (key === "ArrowDown") { e.preventDefault(); index = Math.min(flat.length - 1, index + 1); scroll(); }
    else if (key === "ArrowUp") { e.preventDefault(); index = Math.max(0, index - 1); scroll(); }
    else if (key === "Enter") { e.preventDefault(); run(flat[index]); }
  }
  function scroll() { requestAnimationFrame(() => list?.querySelector(".pl.on")?.scrollIntoView({ block: "nearest" })); }
</script>

<svelte:window onkeydowncapture={onKey} />

{#if app.palette}
  <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
  <div class="scrim" onclick={e => { if (e.target === e.currentTarget) app.palette = false; }}>
    <div class="palette" role="dialog" aria-modal="true" aria-label={t("shell.search")}>
      <div class="palette-input">
        <Icon name="search" />
        <!-- svelte-ignore a11y_autofocus -->
        <input bind:value={query} placeholder={t("cmd.placeholder")} aria-label={t("shell.search")} autofocus />
        <span class="kbd">esc</span>
      </div>
      <div class="palette-list scroll" bind:this={list}>
        {#each groups as g (g.title)}
          <p class="cap">{g.title}</p>
          {#each g.items as item (item)}
            {@const i = flat.indexOf(item)}
            <button class="pl" class:on={i === index} onclick={() => run(item)} onmousemove={() => (index = i)}>
              <Icon name={item.icon} />
              <span class="grow trunc">{item.label}</span>
              {#if item.hint}<span class="t3 mono">{item.hint}</span>{/if}
              {#if item.keys}<span class="keys">{#each item.keys as k (k)}<span class="kbd">{k}</span>{/each}</span>{/if}
            </button>
          {/each}
        {:else}
          <p class="none">{t("cmd.none")}</p>
        {/each}
      </div>
    </div>
  </div>
{/if}

<style>
  .palette { width: min(640px, 92vw); border-radius: var(--r-xl); background: var(--surface); box-shadow: var(--shadow-3); overflow: hidden;
    animation: drop var(--d-slow) var(--ease-out); }
  .palette-input { display: flex; align-items: center; gap: var(--s-5); height: 52px; padding: 0 var(--s-7); border-bottom: 1px solid var(--outline-2);
    color: var(--text-3); }
  .palette-input input { flex: 1; border: 0; background: none; outline: none; box-shadow: none; font-size: var(--size-title-2); color: var(--text); min-width: 0; }
  .palette-list { max-height: 384px; padding: var(--s-3); }
  .palette-list .cap { padding: var(--s-4) var(--s-5) var(--s-2); }
  .pl { display: flex; align-items: center; gap: var(--s-5); height: 36px; padding: 0 var(--s-5); border-radius: var(--r-m); border: 0;
    background: none; width: 100%; text-align: left; cursor: pointer; }
  .pl :global(svg) { color: var(--text-2); }
  .pl.on { background: var(--primary); color: #fff; }
  .pl.on :global(svg), .pl.on .t3 { color: #fff; }
  .pl.on .kbd { background: rgba(255,255,255,.2); color: #fff; }
  .keys { margin-left: auto; display: flex; gap: var(--s-2); }
  .none { padding: var(--s-8); text-align: center; color: var(--text-3); }
</style>
