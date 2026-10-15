<script>
  // Top bar (prototype-v5 .topbar): the project chip and its menu on the left; the status chip slot,
  // the theme toggle and help on the right.
  import { keyOf } from "../lib/keys.js";
  import Icon from "./Icon.svelte";
  import StatusChip from "./StatusChip.svelte";
  import { DEFAULT_HOTKEYS, comboLabel } from "../lib/hotkeys.js";
  import { api } from "../lib/api.js";
  import { reopenOnboarding, startTutorial } from "../lib/onboarding.svelte.js";
  import { app, t, currentProject, switchProject, loadProjects, restoreProject, toast, setTheme, isDark } from "../lib/state.svelte.js";

  let menuOpen = $state(false);
  let showArchive = $state(false);
  let archiveAsk = $state(null);   // the project the confirm sheet asks about
  let archiving = $state(false);
  let newName = $state("");
  let newAnalysis = $state(true);          // 5.0.4: off makes the new project a meeting recorder
  let creating = $state(false);
  let query = $state("");
  let wrap = $state(null);
  const mod = typeof navigator !== "undefined" && /Mac/.test(navigator.platform) ? "⌘" : "Ctrl+";

  // Help (5.0 C8): the commands, the tips again, the first run again.
  let helpOpen = $state(false);
  let helpWrap = $state(null);
  function helpPick(fn) { helpOpen = false; fn(); }

  function onKey(e) {
    const key = keyOf(e);
    if (key === "Escape" && archiveAsk) { archiveAsk = null; return; }
    if (key === "Escape" && helpOpen) { helpOpen = false; return; }
    if (key === "Escape" && menuOpen) { menuOpen = false; return; }
    if ((e.metaKey || e.ctrlKey) && !e.altKey && e.shiftKey && (key === "p" || key === "P")) { e.preventDefault(); menuOpen = !menuOpen; }
  }
  function onDoc(e) {
    if (menuOpen && wrap && !wrap.contains(e.target)) menuOpen = false;
    if (helpOpen && helpWrap && !helpWrap.contains(e.target)) helpOpen = false;
  }
  $effect(() => { if (!menuOpen) { showArchive = false; query = ""; } });

  async function createProject(e) {
    e.preventDefault();
    if (!newName.trim()) return;
    creating = true;
    try {
      const p = await api("/api/projects", { method: "POST", body: { name: newName.trim(), analysis: newAnalysis } });
      newName = "";
      newAnalysis = true;
      await loadProjects();
      await switchProject(p.id);
      menuOpen = false;
    } catch (err) {
      toast(err.message, { kind: "danger" });
    } finally {
      creating = false;
    }
  }

  let importInput = $state(null);
  async function importProject(e) {
    const f = e.currentTarget.files[0];
    e.currentTarget.value = "";
    if (!f) return;
    const form = new FormData();
    form.append("file", f);
    try {
      const p = await api("/api/projects/import", { method: "POST", form });
      await loadProjects();
      await switchProject(p.id);
      menuOpen = false;
      toast(t("project.imported", { name: p.name }));
    } catch (err) { toast(err.message, { kind: "danger" }); }
  }

  async function pick(id) {
    menuOpen = false;
    if (id !== app.currentProjectId) await switchProject(id);
  }
  async function restore(id) {
    try { await restoreProject(id); } catch (err) { toast(err.message, { kind: "danger" }); }
  }

  // Archive the current project (5.0.2: moved here from Settings → Проект). The last open project stays.
  function askArchive() { if (project && app.projects.length > 1) { archiveAsk = project; menuOpen = false; } }
  async function archive() {
    const p = archiveAsk;
    if (!p) return;
    archiving = true;
    try {
      await api(`/api/projects/${p.id}`, { method: "PATCH", body: { archived: true } });
      await loadProjects();
      const next = app.projects.find(x => x.id !== p.id);
      if (next && app.currentProjectId !== next.id) await switchProject(next.id);
      archiveAsk = null;
      toast(t("project.archived_done", { name: p.name }));
    } catch (err) { toast(err.message, { kind: "danger" }); }
    finally { archiving = false; }
  }

  const shown = $derived(app.projects.filter(p => p.name.toLowerCase().includes(query.trim().toLowerCase())));
  const project = $derived(currentProject());
  const hk = $derived({ ...DEFAULT_HOTKEYS, ...(app.settings?.hotkeys || {}) });
</script>

<svelte:window onkeydown={onKey} />
<svelte:document onmousedown={onDoc} />

<div class="topbar">
  <div class="proj-wrap" bind:this={wrap}>
    <button class="project-chip proj" onclick={() => (menuOpen = !menuOpen)} aria-expanded={menuOpen} aria-haspopup="menu"
            title={`${t("project.switch")} · ${mod}⇧P`}>
      <span class="av" aria-hidden="true"></span><span class="trunc">{project?.name || "…"}</span><span class="t3" aria-hidden="true">▾</span>
    </button>
    {#if menuOpen}
      <div class="menu proj-menu" role="menu">
        {#if app.projects.length > 6}
          <div class="search find"><Icon name="search" size={14} />
            <!-- svelte-ignore a11y_autofocus -->
            <input bind:value={query} placeholder={t("project.find")} aria-label={t("project.find")} autofocus /></div>
        {/if}
        {#each shown as p (p.id)}
          <button class="menu-item" role="menuitem" class:on={p.id === app.currentProjectId} onclick={() => pick(p.id)}>
            <span class="tick">{#if p.id === app.currentProjectId}<Icon name="check" size={12} />{/if}</span>
            <span class="grow trunc">{p.name}</span>
            {#if p.local_only}<Icon name="lock" size={12} />{/if}
          </button>
        {/each}
        {#if project}
          <button class="menu-item archive-it" role="menuitem" onclick={askArchive} disabled={app.projects.length < 2}
                  title={app.projects.length < 2 ? t("project.archive_last") : ""}>
            <span class="tick"></span><Icon name="trash" size={12} /><span class="grow">{t("project.archive")}</span></button>
        {/if}
        <hr />
        <p class="menu-label">{t("project.new")}</p>
        <form class="menu-new" onsubmit={createProject}>
          <input class="input" bind:value={newName} placeholder={t("project.new_placeholder")} aria-label={t("project.new")} />
          <button class="btn sm primary" disabled={creating || !newName.trim()}>{t("project.create")}</button>
        </form>
        <label class="menu-check" title={t("set.analysis_hint")}><input type="checkbox" class="new-analysis" bind:checked={newAnalysis} /> {t("set.analysis")}</label>
        <button class="menu-item import" role="menuitem" onclick={() => importInput.click()}>
          <span class="tick"></span><Icon name="upload" size={14} /> <span>{t("project.import")}</span></button>
        <input type="file" accept=".zip" class="hidden" bind:this={importInput} onchange={importProject} aria-label={t("project.import")} />
        <button class="menu-item" role="menuitem" aria-expanded={showArchive} onclick={() => (showArchive = !showArchive)}>
          <span class="tick"></span><span class="grow">{t("project.archived")}</span>
          <span class="t3 num">{app.archivedProjects.length || ""}</span><Icon name={showArchive ? "chevd" : "chevron"} size={12} /></button>
        {#if showArchive}
          {#each app.archivedProjects as p (p.id)}
            <div class="arch"><span class="grow trunc">{p.name}</span>
              <button class="btn sm ghost" onclick={() => restore(p.id)}>{t("project.restore")}</button></div>
          {:else}
            <p class="menu-label">{t("project.archive_empty")}</p>
          {/each}
        {/if}
      </div>
    {/if}
  </div>

  <span class="grow"></span>
  <StatusChip />
  <button class="icon-btn-m" onclick={() => setTheme(isDark() ? "light" : "dark")}
          aria-label={t("shell.theme")} title={`${t("shell.theme")} · ${comboLabel(hk.theme)}`}>
    <Icon name={isDark() ? "sun" : "moon"} size={18} /></button>
  <div class="help-wrap help" bind:this={helpWrap}>
    <button class="icon-btn-m" onclick={() => (helpOpen = !helpOpen)} aria-label={t("shell.help")} aria-haspopup="menu" aria-expanded={helpOpen}
            title={t("shell.help")}><Icon name="help" size={18} /></button>
    {#if helpOpen}
      <div class="menu right help-menu" role="menu">
        <button class="menu-item" role="menuitem" onclick={() => helpPick(() => (app.palette = true))}>
          <span class="grow">{t("help.commands")}</span><span class="t3">{comboLabel(hk.palette)}</span></button>
        <button class="menu-item" role="menuitem" onclick={() => helpPick(startTutorial)}><span class="grow">{t("help.tips")}</span></button>
        <button class="menu-item" role="menuitem" onclick={() => helpPick(reopenOnboarding)}><span class="grow">{t("help.onboarding")}</span></button>
      </div>
    {/if}
  </div>
</div>

{#if archiveAsk}
  <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
  <div class="scrim" onclick={e => e.target === e.currentTarget && !archiving && (archiveAsk = null)}>
    <div class="sheet archive-sheet" role="dialog" aria-modal="true" aria-labelledby="archive-h">
      <h2 id="archive-h">{t("project.archive_q", { name: archiveAsk.name })}</h2>
      <p>{t("project.archive_body")}</p>
      <div class="acts">
        <!-- svelte-ignore a11y_autofocus -->
        <button class="btn" autofocus onclick={() => (archiveAsk = null)} disabled={archiving}>{t("at.cancel")}</button>
        <button class="btn danger-fill" onclick={archive} disabled={archiving}>
          {#if archiving}<span class="spinner"></span>{/if}{t("project.archive")}</button>
      </div>
    </div>
  </div>
{/if}

<style>
  .topbar { display: flex; align-items: center; gap: 10px; height: 40px; margin-bottom: 8px; flex: none; min-width: 0; }
  .proj-wrap { position: relative; min-width: 0; }
  .project-chip { display: inline-flex; align-items: center; gap: 8px; height: 36px; padding: 0 14px 0 10px; border: 0; border-radius: 18px;
    background: var(--surface); color: var(--text); box-shadow: var(--shadow-1); font-weight: 600; cursor: pointer; max-width: 100%; }
  .project-chip:hover { background: color-mix(in srgb, var(--surface), var(--text) 4%); }
  .project-chip .av { width: 22px; height: 22px; border-radius: 7px; background: linear-gradient(135deg, #7C4DFF, #0B57D0); flex: none; }
  .proj-menu { left: 0; top: calc(100% + 6px); width: 300px; }
  .find { margin: var(--s-2) var(--s-2) var(--s-3); }
  .menu-check { display: flex; align-items: center; gap: var(--s-3); padding: 0 var(--s-4) var(--s-3); font-size: var(--size-foot); color: var(--text-2); cursor: pointer; }
  .menu-new { display: flex; gap: var(--s-3); padding: 0 var(--s-2) var(--s-3); }
  .menu-new .input { height: var(--h-ctl-sm); font-size: var(--size-foot); min-width: 0; flex: 1; }
  .menu-item.archive-it:not(:hover):not(:focus-visible) { color: var(--danger); }
  .menu-item.archive-it:disabled { color: var(--text-3); background: none; cursor: default; }
  .arch { display: flex; align-items: center; gap: var(--s-4); padding: var(--s-1) var(--s-4) var(--s-1) 28px; }
  .icon-btn-m { width: 36px; height: 36px; border: 0; border-radius: 18px; display: grid; place-items: center; background: none;
    color: var(--text-2); cursor: pointer; flex: none; }
  .icon-btn-m:hover { background: var(--surface-2); color: var(--text); }
  .help-wrap { position: relative; }
  .help-menu { top: calc(100% + 6px); }
  @media (max-width: 760px) { .help { display: none; } }
</style>
