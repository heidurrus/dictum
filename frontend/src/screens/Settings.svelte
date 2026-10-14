<script>
  // Settings as sections (spec 5.0 C9, prototype-v5 pageSettings): a left column of sections and cards per section,
  // #/settings/<section>; #/settings opens the first. Every 4.x control is kept, moved into its section.
  import Page from "../components/Page.svelte";
  import LocalModel from "../components/LocalModel.svelte";
  import SettingsModels from "../components/SettingsModels.svelte";
  import SettingsStorage from "../components/SettingsStorage.svelte";
  import SettingsHotkeys from "../components/SettingsHotkeys.svelte";
  import Icon from "../components/Icon.svelte";
  import { api } from "../lib/api.js";
  import { saveUrl } from "../lib/save.js";
  import { LANGS } from "../lib/i18n.js";
  import { cap, loadMics } from "../lib/capture.svelte.js";
  import { app, t, go, setLang, setTheme, currentProject, loadProjects, switchProject, restoreProject, toast } from "../lib/state.svelte.js";

  let s = $state(null);              // server settings payload
  let projectName = $state("");
  let localReady = $state(true);

  async function checkLocal() {
    const st = await api("/api/local-llm").catch(() => null);
    localReady = !st || !st.supported || st.models.some(m => m.installed);
  }
  async function load() {
    s = await api("/settings");
    app.settings = s;
    projectName = currentProject()?.name || "";
    checkLocal();
  }
  $effect(() => { load(); });
  $effect(() => { projectName = currentProject()?.name || ""; });

  // Every change goes through here; the app-wide copy (hotkeys, recap style) follows.
  async function save(body, { rethrow = false } = {}) {
    try { s = await api("/settings", { method: "POST", body }); app.settings = s; }
    catch (err) { if (rethrow) throw err; toast(err.message, { kind: "danger" }); }
  }

  async function updateProject(changes) {
    const p = currentProject();
    if (!p) return;
    try { await api(`/api/projects/${p.id}`, { method: "PATCH", body: changes }); await loadProjects(); }
    catch (err) { toast(err.message, { kind: "danger" }); projectName = p.name; }
  }
  async function archive() {
    await updateProject({ archived: true });
    await loadProjects();
    if (app.projects[0]) await switchProject(app.projects[0].id);
  }
  const effectiveQuotes = $derived.by(() => {
    const p = currentProject();
    const q = p?.jira_quotes || "auto";
    return q === "auto" ? (p?.local_only ? "link" : "full") : q;
  });
  function exportProject() {
    const p = currentProject();
    saveUrl(`/api/projects/${p.id}/export.zip`, `${p.name}.rwproject.zip`.replace(/[\\/:*?"<>|]/g, ""));
  }
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
      toast(t("project.imported", { name: p.name }));
    } catch (err) { toast(err.message, { kind: "danger" }); }
  }

  // ── sections ──
  const ALL = [["project", "cube"], ["models", "spark"], ["privacy", "lock"], ["storage", "folder"], ["record", "mic"],
               ["jira", "jira"], ["keys", "bolt"], ["interface", "sun"], ["system", "info"]];
  const sections = $derived(ALL.filter(([id]) => id !== "project" && id !== "privacy" || currentProject()));
  const sec = $derived(sections.some(([id]) => id === app.route.section) ? app.route.section : sections[0][0]);

  // ── Запись ──
  $effect(() => { if (sec === "record") loadMics(); });
  let silenceDraft = $state(10);
  $effect(() => { if (s && s.silence_stop_minutes) silenceDraft = s.silence_stop_minutes; });

  // ── Jira (read here; the connection card with sign-in and the target lives on Выгрузка) ──
  let jira = $state(null);
  $effect(() => {
    if (sec !== "jira") return;
    const pid = app.currentProjectId;
    Promise.all([api("/api/jira/status").catch(() => ({ connected: false })),
                 pid ? api(`/api/projects/${pid}/jira/target`).catch(() => ({ target: null })) : { target: null }])
      .then(([st, tg]) => (jira = { connected: st.connected, target: tg.target }));
  });

  // ── Система ──
  let dataDir = $state("");
  $effect(() => { if (sec === "system" && !dataDir) api("/api/storage").then(r => (dataDir = r.path)).catch(() => {}); });
  const desktop = () => !!window.pywebview?.api;
  const env = $derived(app.health ? [
    [t("env.ffmpeg"), app.health.ffmpeg ? t("env.found") : t("env.missing"), app.health.ffmpeg],
    [t("env.gpu"), app.health.gpu.gpu_name || (app.health.gpu.mps ? "Apple Silicon (MPS)" : t("env.cpu_only")),
      app.health.gpu.cuda || app.health.gpu.mps],
    [t("env.hf"), app.health.hf_token ? t("env.set") : t("env.missing"), app.health.hf_token],
    [t("env.ollama"), app.health.ollama ? t("env.running") : t("env.stopped"), app.health.ollama],
    [t("env.sysaudio"), app.health.system_audio_capture ? t("env.supported") : t("env.unsupported"), app.health.system_audio_capture],
  ] : []);

  const back = $derived(app.returnTo && app.returnTo.name !== "settings" ? app.returnTo : null);
  const backName = $derived(back ? t("nav." + ({ backlog: "decomposition", transcript: "meetings", home: "meetings" }[back.name] || back.name)) : "");
</script>

<Page title={t("set.title")} sub={t("set.sub")} crumb={backName} crumbPath={back?.hash || ""} card={false}>
  <div class="settings-page">
    <nav class="setnav card-m" aria-label={t("set.title")}>
      {#each sections as [id, icon] (id)}
        <button class="node cat" data-section={id} aria-current={sec === id ? "page" : undefined} onclick={() => go("/settings/" + id)}>
          <Icon name={icon} size={18} /> <span class="trunc">{t("set.cat." + id)}</span></button>
      {/each}
    </nav>
    <div class="setcards scroll" data-section={sec}>
      <h2 class="sec-title">{t("set.cat." + sec)}</h2>

      {#if sec === "project" && currentProject()}
        <div class="setcard card-m" id="set-project">
          <div class="row first">
            <label class="l" for="pname"><b>{t("set.project_name")}</b></label>
            <input class="input w-320" id="pname" bind:value={projectName}
                   onblur={() => projectName.trim() && projectName.trim() !== currentProject().name && updateProject({ name: projectName.trim() })}
                   onkeydown={e => e.key === "Enter" && e.currentTarget.blur()} />
          </div>
          <div class="row">
            <span class="l"><b>{t("set.out_lang")}</b><small>{t("set.out_lang_hint")}</small></span>
            <div class="seg out-lang" role="group" aria-label={t("set.out_lang")}>
              {#each ["auto", "ru", "en"] as l (l)}
                <button aria-pressed={(currentProject().language || "auto") === l} onclick={() => updateProject({ language: l })}>{t("set.out_lang." + l)}</button>
              {/each}
            </div>
          </div>
          <label class="row">
            <span class="l"><b>{t("set.auto_extract")}</b><small>{t("set.auto_extract_hint")}</small></span>
            <input type="checkbox" class="switch" checked={currentProject().auto_extract !== false}
                   onchange={e => updateProject({ auto_extract: e.currentTarget.checked })} />
          </label>
          <div class="row">
            <span class="l"><b>{t("set.jira_quotes")}</b><small>{t("set.jira_quotes_hint." + effectiveQuotes)}</small></span>
            <div class="seg jira-quotes" role="group" aria-label={t("set.jira_quotes")}>
              {#each ["auto", "full", "link", "none"] as q (q)}
                <button aria-pressed={(currentProject().jira_quotes || "auto") === q} onclick={() => updateProject({ jira_quotes: q })}>{t("set.jq." + q)}</button>
              {/each}
            </div>
          </div>
        </div>
        <div class="setcard card-m">
          <h3>{t("set.project_file")}</h3><p class="d">{t("set.project_file_hint")}</p>
          <div class="row">
            <button class="btn" onclick={exportProject}><Icon name="download" size={14} /> {t("set.export_project")}</button>
            <label class="btn"><Icon name="upload" size={14} /> {t("project.import")}
              <input type="file" accept=".zip" class="visually-hidden" onchange={importProject} /></label>
          </div>
          <div class="row">
            <span class="l"><b>{t("set.archive")}</b><small>{t("set.archive_hint")}</small></span>
            <button class="btn btn-danger" onclick={archive} disabled={app.projects.length < 2}>{t("set.archive")}</button>
          </div>
          {#if app.archivedProjects.length}
            <div class="row col">
              <span class="label">{t("project.archived")}</span>
              {#each app.archivedProjects as p (p.id)}
                <div class="archived-row"><span>{p.name}</span>
                  <button class="btn btn-ghost btn-sm" onclick={() => restoreProject(p.id)}>{t("project.restore")}</button></div>
              {/each}
            </div>
          {/if}
        </div>

      {:else if sec === "models" && s}
        <SettingsModels {s} {save} />

      {:else if sec === "privacy" && currentProject()}
        <div class="setcard card-m">
          <h3>{t("set.pr.title")}</h3><p class="d">{t("set.pr.d")}</p>
          <label class="row">
            <span class="l"><b>{t("project.local_only")}</b><small>{t("set.local_only_hint")}</small></span>
            <input type="checkbox" class="switch local-only" checked={currentProject().local_only}
                   onchange={e => updateProject({ local_only: e.currentTarget.checked })} aria-label={t("project.local_only")} />
          </label>
          {#if currentProject().local_only && !localReady && s && s.llm_provider !== "ollama"}
            <div class="row col">
              <p class="banner warn"><span>{t("llm.local_only_needs")}</span></p>
              <LocalModel only="recommended" selected={s.local_model} onSelect={id => save({ local_model: id })} onReady={checkLocal} />
            </div>
          {/if}
          <label class="row">
            <span class="l"><b>{t("set.pr.consent")}</b><small>{t("set.pr.consent_d")}</small></span>
            <input type="checkbox" class="switch" checked disabled aria-label={t("set.pr.consent")} />
          </label>
        </div>
        <div class="setcard card-m">
          <h3>{t("set.pr.leaves")}</h3><p class="d">{t("set.pr.leaves_d")}</p>
          {#each ["asr", "local", "index", "ollama", "claude", "jira"] as p (p)}
            <div class="row provider-row" class:current={s && (p === s.llm_provider)}>
              <span class="l"><b>{t("set.pr.p." + p)}</b><small>{t("set.pr.s." + p)}</small></span>
              {#if p === "claude" && currentProject().local_only}<span class="tag ok">{t("set.pr.off_here")}</span>
              {:else if s && p === s.llm_provider}<span class="tag accent">{t("set.m.active")}</span>{/if}
            </div>
          {/each}
        </div>

      {:else if sec === "storage"}
        <SettingsStorage />

      {:else if sec === "record" && s}
        <div class="setcard card-m">
          <h3>{t("set.rec.title")}</h3><p class="d">{t("set.rec.d")}</p>
          <div class="row first">
            <label class="l" for="set-mic"><b>{t("rec.mic")}</b></label>
            <select class="select w-320" id="set-mic" bind:value={cap.mic}>
              <option value="">{t("rec.mic_default")}</option>
              {#each cap.mics as m (m.id)}<option value={m.id}>{m.name}</option>{/each}
            </select>
          </div>
          <label class="row">
            <span class="l"><b>{t("set.rec.live")}</b><small>{t("set.rec.live_d")}</small></span>
            <input type="checkbox" class="switch" checked={s.live_transcription} aria-label={t("set.rec.live")}
                   onchange={e => save({ live_transcription: e.currentTarget.checked })} />
          </label>
          <label class="row">
            <span class="l"><b>{t("set.rec.reqs")}</b><small>{t("set.rec.reqs_d")}</small></span>
            <input type="checkbox" class="switch live-reqs" checked={s.live_requirements} aria-label={t("set.rec.reqs")}
                   onchange={e => save({ live_requirements: e.currentTarget.checked })} />
          </label>
          <label class="row">
            <span class="l"><b>{t("set.rec.questions")}</b><small>{t("set.rec.questions_d")}</small></span>
            <input type="checkbox" class="switch" checked={s.live_questions} aria-label={t("set.rec.questions")}
                   onchange={e => save({ live_questions: e.currentTarget.checked })} />
          </label>
          <div class="row">
            <span class="l"><b>{t("set.rec.silence")}</b>
              <small>{s.silence_stop_minutes ? t("set.rec.silence_on", { n: s.silence_stop_minutes }) : t("set.rec.silence_off")}</small></span>
            {#if s.silence_stop_minutes}
              <input class="input num w-80" type="number" min="1" max="240" bind:value={silenceDraft} aria-label={t("set.rec.minutes")}
                     onchange={() => save({ silence_stop_minutes: Math.max(1, Math.min(240, Math.round(Number(silenceDraft) || 10))) })} />
              <span class="t2">{t("set.rec.min")}</span>
            {/if}
            <input type="checkbox" class="switch" checked={!!s.silence_stop_minutes} aria-label={t("set.rec.silence")}
                   onchange={e => save({ silence_stop_minutes: e.currentTarget.checked ? (silenceDraft || 10) : 0 })} />
          </div>
        </div>
        <div class="setcard card-m">
          <h3>{t("set.rec.recap")}</h3><p class="d">{t("set.rec.recap_d")}</p>
          <div class="row first">
            <span class="l"><b>{t("set.rec.recap_style")}</b><small>{t("set.rec.recap_style_d")}</small></span>
            <div class="seg recap-style" role="group" aria-label={t("set.rec.recap_style")}>
              {#each ["brief", "bullets", "actions"] as r (r)}
                <button aria-pressed={s.recap_style === r} onclick={() => save({ recap_style: r })}>{t("rc." + r)}</button>
              {/each}
            </div>
          </div>
          <div class="row">
            <span class="l"><b>{t("set.rec.notes_style")}</b><small>{t("set.rec.notes_style_d")}</small></span>
            <div class="seg notes-style" role="group" aria-label={t("set.rec.notes_style")}>
              {#each ["standard", "concise"] as n (n)}
                <button aria-pressed={s.notes_style === n} onclick={() => save({ notes_style: n })}>{t("set.rec.ns." + n)}</button>
              {/each}
            </div>
          </div>
        </div>

      {:else if sec === "jira"}
        <div class="setcard card-m jira-card">
          <h3>Jira</h3><p class="d">{t("set.jira.d")}</p>
          {#if jira}
            <div class="row first">
              <span class="l"><b>{jira.target?.site_url ? jira.target.site_url.replace(/^https?:\/\//, "") : t("set.jira.no_site")}</b>
                <small>{jira.target ? t("set.jira.target", { key: jira.target.project_key, name: jira.target.project_name || "" }) : t("set.jira.no_target")} ·
                  {jira.connected ? t("set.jira.connected") : t("set.jira.disconnected")}</small></span>
              <span class="tag" class:ok={jira.connected}>{jira.connected ? t("set.jira.connected") : t("set.jira.disconnected")}</span>
              <button class="btn sm" onclick={() => go("/export")}>{t("set.jira.open")}</button>
            </div>
          {/if}
        </div>

      {:else if sec === "keys" && s}
        <SettingsHotkeys {s} {save} />

      {:else if sec === "interface"}
        <div class="setcard card-m">
          <div class="row first">
            <span class="l"><b>{t("set.language")}</b></span>
            <div class="seg" role="group" aria-label={t("set.language")}>
              {#each LANGS as l (l.id)}
                <button aria-pressed={app.lang === l.id} onclick={() => setLang(l.id)}>{l.label}</button>
              {/each}
            </div>
          </div>
          <div class="row">
            <span class="l"><b>{t("set.theme")}</b><small>{t("set.theme_hint")}</small></span>
            <div class="seg" role="group" aria-label={t("set.theme")}>
              {#each ["auto", "light", "dark"] as th (th)}
                <button aria-pressed={app.theme === th} onclick={() => setTheme(th)}>{t("theme.s." + th)}</button>
              {/each}
            </div>
          </div>
        </div>

      {:else if sec === "system"}
        <div class="setcard card-m">
          {#if app.health?.version}
            <div class="row first"><span class="l"><b>{t("app.name")}</b></span><span class="t2 num version">v{app.health.version}</span></div>
          {/if}
          <div class="row">
            <span class="l"><b>{t("set.sys.data")}</b><small class="mono">{dataDir}</small></span>
            {#if desktop() && dataDir}<button class="btn sm" onclick={() => window.pywebview.api.reveal(dataDir)}><Icon name="folder" size={14} /> {t("set.sto.show")}</button>{/if}
            <button class="btn sm ghost" onclick={() => go("/settings/storage")}>{t("set.cat.storage")}</button>
          </div>
          <div class="row">
            <span class="l"><b>{t("set.sys.logs")}</b><small class="mono">{dataDir ? dataDir + "/logs/jobs.log" : ""}</small></span>
            {#if desktop() && dataDir}<button class="btn sm" onclick={() => window.pywebview.api.reveal(dataDir + "/logs/jobs.log")}><Icon name="doc" size={14} /> {t("set.sys.logs_show")}</button>{/if}
          </div>
        </div>
        <div class="setcard card-m">
          <h3>{t("set.cat.env")}</h3>
          {#each env as [name, value, ok] (name)}
            <div class="row"><span class="l"><b>{name}</b></span>
              <span class="status" class:ok class:danger={!ok}><Icon name={ok ? "check" : "warn"} size={12} /> {value}</span></div>
          {/each}
        </div>
      {/if}
    </div>
  </div>
</Page>

<style>
  .settings-page { display: grid; grid-template-columns: 220px minmax(0, 1fr); gap: 16px; height: 100%; min-height: 0; }
  .setnav { padding: 10px 8px; align-self: start; display: grid; gap: 2px; }
  .setnav .node { display: flex; align-items: center; gap: 10px; height: 40px; padding: 0 14px; border-radius: 14px; border: 0; background: none;
    color: var(--text-2); font: inherit; font-weight: 500; cursor: pointer; text-align: left; }
  .setnav .node:hover { background: var(--surface-2); }
  .setnav .node[aria-current="page"] { background: var(--secondary-c); color: var(--on-secondary-c); }
  .setcards { display: grid; gap: 14px; align-content: start; min-height: 0; overflow: auto; padding-bottom: 24px; max-width: 980px; }
  .sec-title { font: 600 20px/28px var(--font-display, inherit); margin: 4px 0 0; }
  .settings-page :global(.card-m) { background: var(--surface); border-radius: 24px; box-shadow: var(--shadow-1); }
  .settings-page :global(.setcard) { padding: 18px 20px; }
  .settings-page :global(.setcard h3) { font-size: 16px; font-weight: 600; margin-bottom: 4px; }
  .settings-page :global(.setcard .d) { color: var(--text-2); font-size: 13px; margin-bottom: 8px; }
  .settings-page :global(.row) { display: flex; align-items: center; gap: 12px; padding: 12px 0; border-top: 1px solid var(--outline-2); flex-wrap: wrap; }
  .settings-page :global(.row.first), .settings-page :global(.setcard > .row:first-child) { border-top: 0; }
  .settings-page :global(label.row) { cursor: pointer; }
  .settings-page :global(.row.col) { flex-direction: column; align-items: stretch; }
  .settings-page :global(.row .l) { flex: 1; min-width: 200px; }
  .settings-page :global(.row .l b) { display: block; font-weight: 500; }
  .settings-page :global(.row .l small) { display: block; color: var(--text-3); font-size: 12px; line-height: 17px; max-width: 64ch; }
  .w-320 { width: 320px; max-width: 100%; }
  .w-80 { width: 80px; }
  .archived-row { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
  .visually-hidden { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
  label.btn { position: relative; cursor: pointer; }
  .provider-row.current b { color: var(--primary); }
  .status.ok { color: var(--ok); } .status.danger { color: var(--danger); }
  @container ws (max-width: 760px) {
    .settings-page { grid-template-columns: minmax(0, 1fr); grid-template-rows: auto minmax(0, 1fr); }
    .setnav { display: flex; overflow-x: auto; padding: 6px; }
    .setnav .node { flex: none; height: 36px; }
  }
</style>
