<script>
  // Top bar (prototype-v5 .topbar): the project chip and its menu on the left; the status chip slot,
  // the theme toggle and help on the right.
  import { keyOf } from "../lib/keys.js";
  import Icon from "./Icon.svelte";
  import { api } from "../lib/api.js";
  import { app, t, go, currentProject, switchProject, loadProjects, restoreProject, toast, setTheme, isDark } from "../lib/state.svelte.js";

  let menuOpen = $state(false);
  let showArchive = $state(false);
  let newName = $state("");
  let creating = $state(false);
  let query = $state("");
  let wrap = $state(null);
  const mod = typeof navigator !== "undefined" && /Mac/.test(navigator.platform) ? "⌘" : "Ctrl+";

  function onKey(e) {
    const key = keyOf(e);
    if (key === "Escape" && menuOpen) { menuOpen = false; return; }
    if ((e.metaKey || e.ctrlKey) && !e.altKey && e.shiftKey && (key === "p" || key === "P")) { e.preventDefault(); menuOpen = !menuOpen; }
  }
  function onDoc(e) { if (menuOpen && wrap && !wrap.contains(e.target)) menuOpen = false; }
  $effect(() => { if (!menuOpen) { showArchive = false; query = ""; } });

  async function createProject(e) {
    e.preventDefault();
    if (!newName.trim()) return;
    creating = true;
    try {
      const p = await api("/api/projects", { method: "POST", body: { name: newName.trim() } });
      newName = "";
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
  function openSettings() { menuOpen = false; go("/settings"); }

  const shown = $derived(app.projects.filter(p => p.name.toLowerCase().includes(query.trim().toLowerCase())));
  const project = $derived(currentProject());
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
          <button class="menu-item mode" role="menuitem" onclick={openSettings} title={t("nav.settings")}>
            <span class="tick"></span>
            {#if project.local_only}<Icon name="lock" size={12} /><span class="grow">{t("project.local_only")}</span>
            {:else}<Icon name="cloud" size={12} /><span class="grow">{t("project.cloud_ok")}</span>{/if}
          </button>
        {/if}
        <hr />
        <p class="menu-label">{t("project.new")}</p>
        <form class="menu-new" onsubmit={createProject}>
          <input class="input" bind:value={newName} placeholder={t("project.new_placeholder")} aria-label={t("project.new")} />
          <button class="btn sm primary" disabled={creating || !newName.trim()}>{t("project.create")}</button>
        </form>
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
  <!-- Slot for the 36-px status chip (jobs); it comes in the next increment and renders nothing until then. -->
  <button class="icon-btn-m" onclick={() => setTheme(isDark() ? "light" : "dark")}
          aria-label={t("shell.theme")} title={`${t("shell.theme")} · ${mod}⇧L`}>
    <Icon name={isDark() ? "sun" : "moon"} size={18} /></button>
  <button class="icon-btn-m help" onclick={() => (app.palette = true)} aria-label={t("shell.help")} title={`${t("shell.help")} · ${mod}K`}>
    <Icon name="help" size={18} /></button>
</div>

<style>
  .topbar { display: flex; align-items: center; gap: 10px; height: 40px; margin-bottom: 8px; flex: none; min-width: 0; }
  .proj-wrap { position: relative; min-width: 0; }
  .project-chip { display: inline-flex; align-items: center; gap: 8px; height: 36px; padding: 0 14px 0 10px; border: 0; border-radius: 18px;
    background: var(--surface); color: var(--text); box-shadow: var(--shadow-1); font-weight: 600; cursor: pointer; max-width: 100%; }
  .project-chip:hover { background: color-mix(in srgb, var(--surface), var(--text) 4%); }
  .project-chip .av { width: 22px; height: 22px; border-radius: 7px; background: linear-gradient(135deg, #7C4DFF, #0B57D0); flex: none; }
  .proj-menu { left: 0; top: calc(100% + 6px); width: 300px; }
  .find { margin: var(--s-2) var(--s-2) var(--s-3); }
  .menu-new { display: flex; gap: var(--s-3); padding: 0 var(--s-2) var(--s-3); }
  .menu-new .input { height: var(--h-ctl-sm); font-size: var(--t-foot); min-width: 0; flex: 1; }
  .mode { color: var(--text-2); }
  .arch { display: flex; align-items: center; gap: var(--s-4); padding: var(--s-1) var(--s-4) var(--s-1) 28px; }
  .icon-btn-m { width: 36px; height: 36px; border: 0; border-radius: 18px; display: grid; place-items: center; background: none;
    color: var(--text-2); cursor: pointer; flex: none; }
  .icon-btn-m:hover { background: var(--surface-2); color: var(--text); }
  @media (max-width: 760px) { .help { display: none; } }
</style>
