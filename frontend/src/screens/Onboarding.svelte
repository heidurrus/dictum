<script>
  // First run (5.0 C8, prototype-v5 onboarding()): six steps, full screen, instead of the shell. Every step is saved, so a
  // restart resumes where the BA stopped; "Пропустить" or the last step marks it done for good (#/onboarding reopens it).
  import Icon from "../components/Icon.svelte";
  import PanelArt from "../components/PanelArt.svelte";
  import { api } from "../lib/api.js";
  import { optionsPayload, track } from "../lib/capture.svelte.js";
  import { DEFAULT_HOTKEYS, comboLabel } from "../lib/hotkeys.js";
  import { onb, STEPS, setStep, finishOnboarding, queueDownloads, retryDownload, downloadsBusy } from "../lib/onboarding.svelte.js";
  import { app, t, currentProject, loadSources, toast } from "../lib/state.svelte.js";

  const step = $derived(onb.step);
  const go = n => setStep(Math.min(Math.max(n, 1), STEPS));
  const gb = n => (n / 1024 ** 3).toLocaleString(app.lang, { maximumFractionDigits: 1, minimumFractionDigits: n >= 1024 ** 3 ? 0 : 1 });
  const hk = $derived({ ...DEFAULT_HOTKEYS, ...(app.settings?.hotkeys || {}) });

  // ── 1. welcome ──────────────────────────────────────────────────────────────
  let showTerms = $state(false);

  // ── 2. permissions ──────────────────────────────────────────────────────────
  const PERMS = [["microphone", "mic"], ["system_audio", "wave"], ["notifications", "bell"]];
  let perms = $state(null);
  let asking = $state("");
  let hints = $state({});          // which → "no_audio" when the tap opened but stayed silent (prompt pending or off)
  async function loadPerms() {
    try { perms = await api("/api/permissions"); } catch (err) { toast(err.message, { kind: "danger" }); }
  }
  async function allow(which) {
    asking = which;
    try {
      const { hint, ...next } = await api(`/api/permissions/request/${which}`, { method: "POST" });
      perms = next;
      hints = { ...hints, [which]: hint || "" };
    }
    catch (err) { toast(err.message, { kind: "danger" }); }
    finally { asking = ""; }
  }
  async function allowAll() {
    for (const [which] of PERMS) if (open(which)) await allow(which);
  }
  async function openSettings(which) {
    try { await api(`/api/permissions/open-settings/${which}`, { method: "POST" }); } catch (err) { toast(err.message, { kind: "danger" }); }
  }
  const open = which => perms && perms[which] !== "granted" && perms[which] !== "unsupported";
  const allSet = $derived(!!perms && PERMS.every(([w]) => !open(w)));
  const unsupportedLabel = $derived(app.health?.platform === "darwin" ? t("perm.unsupported") : t("perm.not_needed"));

  // ── 3. models ───────────────────────────────────────────────────────────────
  let asr = $state(null);          // /api/asr/models
  let llm = $state(null);          // /api/local-llm
  let pickAsr = $state("");
  let pickLlm = $state("");        // a local model id, or "claude"
  let pickIndex = $state(true);
  let apiKey = $state("");
  let keySaved = $state(false);

  async function loadModels() {
    try {
      const [a, l] = await Promise.all([api("/api/asr/models"), api("/api/local-llm")]);
      asr = a; llm = l;
      keySaved = !!app.settings?.anthropic_key_set;
      if (!pickAsr) pickAsr = (a.models.find(m => m.installed) || a.models.find(m => m.recommended) || a.models[0])?.id || "";
      if (!pickLlm) pickLlm = !l.supported ? "claude" : (l.models.find(m => m.installed) || l.models.find(m => m.recommended))?.id || "claude";
      pickIndex = !(l.embed_models || []).every(m => m.installed);
    } catch (err) { toast(err.message, { kind: "danger" }); }
  }
  const asrShown = $derived(asr ? asr.models.filter(m => m.recommended || m.installed || m.id === "v3_e2e_ctc") : []);
  const asrLabel = id => "GigaAM " + id.replace(/_/g, " ").replace(/ rnnt$/, "").replace(/\bctc\b/, "CTC");
  const asrNote = m => t(m.langs === "multi" ? "onb.m.multi" : m.id.endsWith("ctc") ? "onb.m.faster" : "onb.m.accurate", { gb: gb(m.size) });
  const index = $derived(llm?.embed_models?.[0] || null);
  const machineLine = $derived.by(() => {
    const m = llm?.machine;
    if (!m?.ram) return t("onb.m.lead");
    const ram = Math.round(m.ram / 1024 ** 3);
    return m.chip ? t("onb.m.lead_chip", { ram, chip: m.chip }) : t("onb.m.lead_ram", { ram });
  });

  async function saveKey() {
    try {
      const s = await api("/settings", { method: "POST", body: { anthropic_api_key: apiKey.trim(), llm_provider: "claude" } });
      app.settings = { ...(app.settings || {}), ...s };
      keySaved = s.anthropic_key_set;
      apiKey = "";
    } catch (err) { toast(err.message, { kind: "danger" }); }
  }

  async function download() {
    const list = [];
    const a = asr?.models.find(m => m.id === pickAsr);
    if (a && !a.installed) list.push({ kind: "asr", id: a.id, label: asrLabel(a.id), size: a.size });
    if (pickIndex && index && !index.installed) list.push({ kind: "llm", id: index.id, label: index.label, size: index.size });
    const l = llm?.models.find(m => m.id === pickLlm);
    if (l && !l.installed) list.push({ kind: "llm", id: l.id, label: l.label, size: l.size });
    try {
      if (pickAsr) { app.options.model = pickAsr; }
      if (l) {
        const s = await api("/settings", { method: "POST", body: { llm_provider: "local", local_model: l.id } });
        app.settings = { ...(app.settings || {}), ...s };
      }
    } catch (err) { toast(err.message, { kind: "danger" }); }
    if (list.length) queueDownloads(list);
    go(4);
  }

  // ── 4. download ─────────────────────────────────────────────────────────────
  const busy = $derived(downloadsBusy());
  const finished = $derived(onb.downloads.filter(d => d.status === "done").length);
  const pct = d => d.total ? Math.min(100, Math.round(100 * d.done / d.total)) : 0;

  // ── 5. materials ────────────────────────────────────────────────────────────
  let found = $state(null);        // null while loading
  let checked = $state({});
  let folderOpen = $state(false);
  let folder = $state("");
  let shownFolder = $state("");
  let adding = $state(false);
  async function discover(path = "") {
    found = null;
    try {
      const r = await api("/api/discover" + (path ? "?folder=" + encodeURIComponent(path) : ""));
      found = r.candidates;
      shownFolder = path;
      checked = {};
    } catch (err) { found = found || []; toast(err.message, { kind: "danger" }); }
  }
  const picked = $derived((found || []).filter(c => checked[c.path]));
  const fileExt = name => (name.split(".").pop() || "").toLowerCase();
  const fileSize = n => n >= 1024 ** 3 ? `${gb(n)} ${app.lang === "ru" ? "ГБ" : "GB"}`
    : n >= 1024 ** 2 ? `${Math.round(n / 1024 ** 2)} ${app.lang === "ru" ? "МБ" : "MB"}` : `${Math.max(1, Math.round(n / 1024))} ${app.lang === "ru" ? "КБ" : "KB"}`;
  const fileDate = s => new Date(s * 1000).toLocaleDateString(app.lang === "en" ? "en-GB" : "ru-RU", { day: "numeric", month: "short" });
  const folderName = f => (["Downloads", "Documents", "Desktop"].includes(f) ? t("onb.f." + f) : f);

  async function addPicked() {
    if (!picked.length) { go(6); return; }
    adding = true;
    try {
      const r = await api("/api/discover/import", { method: "POST", body: { paths: picked.map(c => c.path),
        project_id: app.currentProjectId, options: optionsPayload() } });
      for (const m of r.meetings) track(m.source_id, m.job_id);
      await loadSources();
      toast(t("onb.f.added", { n: r.meetings.length + r.materials.length }));
      if (r.failed.length) toast(r.failed.join("; "), { kind: "danger" });
      go(6);
    } catch (err) { toast(err.message, { kind: "danger" }); }
    finally { adding = false; }
  }

  // ── 6. done ─────────────────────────────────────────────────────────────────
  const DONE = $derived([
    ["mic", t("onb.done.rec"), t("onb.done.rec_d", { key: comboLabel(hk.record) })],
    ["sources", t("nav.meetings"), t("onb.done.meetings_d")],
    ["folder", t("nav.library"), t("onb.done.library_d")],
    ["search", t("nav.ask"), t("onb.done.ask_d")],
    ["bell", t("nav.whisper"), t("onb.done.whisper_d", { key: comboLabel(hk.whisper) })],
    ["gear", t("nav.settings"), t("onb.done.settings_d")],
  ]);

  // Load what a step needs when it opens (also after a restart that resumes there).
  let started = {};
  $effect(() => {
    if (started[step]) return;
    started[step] = true;
    if (step === 2) loadPerms();
    else if (step === 3) loadModels();
    else if (step === 5) discover();
  });

  const canBack = $derived(step > 1 && !(step === 4 && busy));
  let body = $state(null);
  $effect(() => { step; body?.scrollTo?.(0, 0); });
</script>

<div class="onb" data-step={step}>
  <header class="onb-top">
    <span class="mark" aria-hidden="true">
      <svg width="20" height="12" viewBox="144 300 736 420">
        <g stroke="currentColor" stroke-width="84" stroke-linecap="round" fill="none">
          <line x1="208" y1="424" x2="208" y2="600"/><line x1="304" y1="352" x2="304" y2="672"/><line x1="400" y1="388" x2="400" y2="636"/>
          <line x1="496" y1="416" x2="816" y2="416"/><line x1="496" y1="512" x2="816" y2="512"/><line x1="496" y1="608" x2="816" y2="608"/>
        </g>
      </svg>
    </span>
    <b>{t("app.name")}</b><span class="t3">· {t("onb.top")}</span>
    <div class="steps" role="progressbar" aria-valuemin="1" aria-valuemax={STEPS} aria-valuenow={step}
         aria-label={t("onb.progress", { n: step, total: STEPS })}>
      {#each Array(STEPS) as _, i}<i class:on={i < step}></i>{/each}
    </div>
  </header>

  <div class="onb-body" bind:this={body}>
    <div class="onb-inner">
      {#if step === 1}
        <h1>{t("onb.w.title")}</h1>
        <p class="lead">{t("onb.w.lead")}</p>
        <div class="panels">
          <PanelArt kind="record" /><PanelArt kind="review" /><PanelArt kind="docs" />
        </div>
        <p class="fine">{t("onb.w.terms_a")} <button class="link" onclick={() => (showTerms = !showTerms)} aria-expanded={showTerms}>{t("onb.w.terms_link")}</button>{t("onb.w.terms_b")}</p>
        {#if showTerms}<p class="fine terms">{t("onb.w.terms_text")}</p>{/if}

      {:else if step === 2}
        <h1>{t("perm.title")}</h1>
        <p class="lead">{t("perm.lead")}</p>
        <div class="card-m perm-card">
          {#each PERMS as [which, icon] (which)}
            {@const st = perms?.[which]}
            <div class="perm" data-perm={which}>
              <span class="ic"><Icon name={icon} size={20} /></span>
              <div class="l"><b>{t("perm." + which)}</b><small>{st === "denied" ? t("perm.denied_hint") : t(`perm.${which}_d`)}</small>
                {#if hints[which] === "no_audio" && st !== "granted"}<small class="hint" role="status">{t("perm.no_audio_hint")}</small>{/if}</div>
              {#if !perms}<span class="spinner"></span>
              {:else if st === "granted"}<span class="tag ok">{t("perm.granted")}</span>
              {:else if st === "unsupported"}<span class="tag">{unsupportedLabel}</span>
              {:else}
                <span class="tag" class:danger={st === "denied"}>{t("perm.not_granted")}</span>
                <button class="btn sm tonal" onclick={() => allow(which)} disabled={!!asking}>
                  {#if asking === which}<span class="spinner"></span>{/if}{t("perm.allow")}</button>
                <button class="btn sm ghost" onclick={() => openSettings(which)}>{t("perm.settings")}</button>
              {/if}
            </div>
          {/each}
        </div>
        {#if perms && !allSet}<button class="btn primary" onclick={allowAll} disabled={!!asking}>{t("perm.allow_all")}</button>{/if}
        <p class="fine with-icon"><Icon name="lock" size={14} /> {t("perm.note")}</p>

      {:else if step === 3}
        <h1>{t("onb.m.title")}</h1>
        <p class="lead">{machineLine}</p>
        {#if !asr || !llm}
          <p class="fine"><span class="spinner"></span></p>
        {:else}
          <section class="card-m setcard">
            <h3>{t("onb.m.asr")}</h3><p class="d">{t("onb.m.asr_d")}</p>
            <div class="models" role="radiogroup" aria-label={t("onb.m.asr")}>
              {#each asrShown as m (m.id)}
                <button class="model" class:on={pickAsr === m.id} role="radio" aria-checked={pickAsr === m.id} onclick={() => (pickAsr = m.id)}>
                  <b>{asrLabel(m.id)}</b>
                  <small>{asrNote(m)}</small>
                  {#if m.installed}<span class="tag ok">{t("onb.m.installed")}</span>
                  {:else if m.recommended}<span class="tag ok">{t("onb.m.recommended")}</span>{/if}
                </button>
              {/each}
            </div>
          </section>
          <section class="card-m setcard">
            <h3>{t("onb.m.llm")}</h3><p class="d">{t("onb.m.llm_d")}</p>
            {#if !llm.supported}<p class="note warn">{t("onb.m.unsupported")}</p>{/if}
            <div class="models" role="radiogroup" aria-label={t("onb.m.llm")}>
              {#if llm.supported}
                {#each llm.models as m (m.id)}
                  <button class="model" class:on={pickLlm === m.id} class:dim={!m.fits} role="radio" aria-checked={pickLlm === m.id}
                          onclick={() => (pickLlm = m.id)}>
                    <b>{m.label}</b>
                    <small>{t("onb.m.llm_size", { ram: m.min_ram_gb, gb: gb(m.size) })}{m.fits ? "" : " · " + t("onb.m.too_big")}</small>
                    {#if m.installed}<span class="tag ok">{t("onb.m.installed")}</span>
                    {:else if m.recommended}<span class="tag ok">{t("onb.m.recommended")}</span>{/if}
                  </button>
                {/each}
              {/if}
              <button class="model" class:on={pickLlm === "claude"} role="radio" aria-checked={pickLlm === "claude"} onclick={() => (pickLlm = "claude")}>
                <b>{t("onb.m.claude")}</b><small>{keySaved ? t("onb.m.claude_set") : t("onb.m.claude_d")}</small>
                <span class="tag warn">{t("onb.m.cloud")}</span>
              </button>
            </div>
            {#if pickLlm === "claude"}
              <form class="key" onsubmit={e => { e.preventDefault(); saveKey(); }}>
                <input class="input" type="password" bind:value={apiKey} placeholder={t("onb.m.key_ph")} aria-label={t("onb.m.key_ph")} autocomplete="off" />
                <button class="btn" disabled={!apiKey.trim()}>{t("onb.m.key_save")}</button>
                {#if keySaved}<span class="status ok"><Icon name="check" size={14} /> {t("onb.m.claude_set")}</span>{/if}
              </form>
            {/if}
          </section>
          {#if index && llm.supported}
            <section class="card-m setcard">
              <h3>{t("onb.m.index")}</h3><p class="d">{t("onb.m.index_d")}</p>
              <div class="models">
                <button class="model" class:on={pickIndex || index.installed} role="checkbox" aria-checked={pickIndex || index.installed}
                        disabled={index.installed} onclick={() => (pickIndex = !pickIndex)}>
                  <b>{index.label}</b><small>{t("onb.m.index_size", { gb: gb(index.size) })}</small>
                  {#if index.installed}<span class="tag ok">{t("onb.m.installed")}</span>
                  {:else}<span class="tag ok">{t("onb.m.recommended")}</span>{/if}
                </button>
              </div>
            </section>
          {/if}
        {/if}

      {:else if step === 4}
        <h1>{busy ? t("onb.d.title_run") : t("onb.d.title_done")}</h1>
        <p class="lead">{busy ? t("onb.d.lead_run") : t("onb.d.lead_done")}</p>
        <div class="card-m setcard dl">
          {#each onb.downloads as d (d.kind + d.id)}
            <div class="dl-row" data-model={d.id}>
              <div class="dl-head"><b>{d.label}</b>
                <span class="t2 num">{d.status === "queued" ? t("onb.d.queued") : d.status === "done" ? `100% · ${gb(d.total)} ${app.lang === "ru" ? "ГБ" : "GB"}`
                  : t("onb.d.pct", { pct: pct(d), gb: gb(d.total) })}</span></div>
              <div class="progress"><i style:width={(d.status === "done" ? 100 : pct(d)) + "%"}></i></div>
              {#if d.status === "error"}
                <p class="err">{t("onb.d.failed", { error: d.error })} <button class="btn sm ghost" onclick={() => retryDownload(d)}>{t("onb.d.retry")}</button></p>
              {/if}
            </div>
          {:else}
            <p class="t2">{t("onb.d.none")}</p>
          {/each}
          <div class="fine dl-foot">
            {#if busy}<span class="spinner"></span> {t("onb.d.running", { n: finished, total: onb.downloads.length })}
            {:else}<span class="okmark"><Icon name="check" size={14} /></span> {t("onb.d.checked")}{/if}
          </div>
        </div>

      {:else if step === 5}
        <h1>{t("onb.f.title")}</h1>
        <p class="lead">{shownFolder ? t("onb.f.lead_folder", { folder: shownFolder }) : t("onb.f.lead")}</p>
        <div class="card-m disc-card">
          {#if found === null}
            <p class="disc-empty"><span class="spinner"></span> {t("onb.f.loading")}</p>
          {:else}
            {#each found as c (c.path)}
              <label class="disc">
                <input type="checkbox" bind:checked={checked[c.path]} />
                <span class="fico" data-ext={fileExt(c.name)}>{fileExt(c.name).toUpperCase()}</span>
                <span class="l"><b>{c.name}</b><small>{folderName(c.folder)} · {fileSize(c.size)} · {fileDate(c.modified)}</small></span>
              </label>
            {:else}
              <p class="disc-empty">{t("onb.f.empty")}</p>
            {/each}
          {/if}
        </div>
        <div class="row">
          <button class="btn" onclick={() => (folderOpen = !folderOpen)} aria-expanded={folderOpen}><Icon name="folder" size={16} /> {t("onb.f.pick")}</button>
          <button class="btn ghost" onclick={() => go(6)}>{t("onb.f.nothing")}</button>
        </div>
        {#if folderOpen}
          <form class="row folder" onsubmit={e => { e.preventDefault(); if (folder.trim()) discover(folder.trim()); }}>
            <input class="input" bind:value={folder} placeholder={t("onb.f.folder_ph")} aria-label={t("onb.f.pick")} />
            <button class="btn" disabled={!folder.trim()}>{t("onb.f.show")}</button>
          </form>
        {/if}
        <p class="fine with-icon">{t("onb.f.hint", { project: currentProject()?.name || "" })}</p>

      {:else}
        <h1>{t("onb.done.title")}</h1>
        <p class="lead">{t("onb.done.lead")}</p>
        <div class="done-grid">
          {#each DONE as [icon, title, d] (title)}
            <div class="card-m done-card"><span class="ic"><Icon name={icon} size={20} /></span><div><b>{title}</b><div class="t2">{d}</div></div></div>
          {/each}
        </div>
      {/if}
    </div>
  </div>

  <footer class="onb-bot">
    {#if canBack}<button class="btn ghost back" onclick={() => go(step - 1)}><Icon name="back" size={16} /> {t("onb.back")}</button>{/if}
    <div class="right">
      {#if step === 1}
        <button class="btn primary lg" onclick={() => go(2)}>{t("onb.w.start")} <Icon name="arrow" size={16} /></button>
      {:else if step === 2}
        <button class="btn ghost" onclick={() => go(3)}>{t("onb.later")}</button>
        <button class="btn primary lg" onclick={() => go(3)}>{t("onb.next")} <Icon name="arrow" size={16} /></button>
      {:else if step === 3}
        <button class="btn primary lg" onclick={download} disabled={!asr || !llm}>{t("onb.m.download")} <Icon name="arrow" size={16} /></button>
      {:else if step === 4}
        <button class="btn primary lg" onclick={() => go(5)}>{busy ? t("onb.d.background") : t("onb.next")} <Icon name="arrow" size={16} /></button>
      {:else if step === 5}
        <button class="btn primary lg" onclick={addPicked} disabled={adding || found === null}>
          {#if adding}<span class="spinner"></span>{/if}{picked.length ? t("onb.f.add", { n: picked.length }) : t("onb.next")} <Icon name="arrow" size={16} /></button>
      {:else}
        <button class="btn ghost" onclick={() => finishOnboarding(false)}>{t("onb.skip")}</button>
        <button class="btn primary lg" onclick={() => finishOnboarding(true)}>{t("onb.done.tips")} <Icon name="arrow" size={16} /></button>
      {/if}
    </div>
  </footer>
</div>

<style>
  .onb { position: fixed; inset: 0; background: var(--bg); color: var(--text); display: grid; grid-template-rows: auto minmax(0, 1fr) auto; z-index: 50; }
  .onb-top { display: flex; align-items: center; gap: 12px; padding: 20px 28px; }
  .mark { width: 32px; height: 32px; border-radius: 10px; background: var(--primary); color: var(--on-primary); display: grid; place-items: center; flex: none; }
  .steps { margin-left: auto; display: flex; gap: 6px; }
  .steps i { width: 28px; height: 4px; border-radius: 2px; background: var(--surface-4); transition: background .2s; }
  .steps i.on { background: var(--primary); }
  .onb-body { overflow: auto; padding: 0 28px; }
  .onb-inner { max-width: 880px; margin: 0 auto; padding-bottom: 24px; animation: fade .3s; }
  h1 { font-size: 36px; line-height: 44px; letter-spacing: -.025em; font-weight: 600; margin: 24px 0 8px; }
  .lead { color: var(--text-2); font-size: 16px; line-height: 24px; max-width: 620px; }
  .fine { color: var(--text-3); font-size: 13px; line-height: 19px; margin-top: 16px; }
  .fine.terms { max-width: 620px; margin-top: 8px; }
  .with-icon { display: flex; align-items: center; gap: 6px; }
  .link { border: 0; background: none; padding: 0; color: var(--primary); text-decoration: underline; cursor: pointer; font: inherit; }
  .onb-bot { display: flex; align-items: center; gap: 10px; padding: 18px 28px 24px; max-width: 936px; margin: 0 auto; width: 100%; }
  .onb-bot .right { margin-left: auto; display: flex; gap: 8px; }
  .btn.lg { border-radius: 24px; padding: 0 24px; }
  .btn.tonal { background: var(--primary-c); color: var(--on-primary-c); box-shadow: none; }
  .back { color: var(--primary); }
  .panels { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; margin: 28px 0 8px; }
  .card-m { background: var(--surface); border-radius: 24px; box-shadow: var(--shadow-1); }
  .perm-card { margin: 24px 0 16px; }
  .perm { display: flex; align-items: center; gap: 14px; padding: 16px 18px; border-top: 1px solid var(--outline-2); flex-wrap: wrap; }
  .perm:first-child { border-top: 0; }
  .perm .ic, .done-card .ic { width: 44px; height: 44px; border-radius: 14px; background: var(--surface-2); display: grid; place-items: center; color: var(--text-2); flex: none; }
  .perm .l { flex: 1; min-width: 200px; } .perm .l b { display: block; } .perm .l small { color: var(--text-3); }
  .perm .l small.hint { display: block; margin-top: 4px; color: var(--text-2); }
  .setcard { padding: 20px; margin-top: 14px; }
  .setcard:first-of-type { margin-top: 24px; }
  .setcard h3 { font-size: 16px; font-weight: 600; }
  .setcard .d { color: var(--text-2); font-size: 13px; margin-top: 2px; }
  .models { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 10px; margin-top: 14px; }
  .model { position: relative; text-align: left; border: 0; border-radius: 16px; padding: 14px 16px; background: var(--surface-2); color: var(--text);
    display: grid; gap: 4px; cursor: pointer; font: inherit; }
  .model:hover:not(:disabled) { background: var(--surface-3); }
  .model.on { box-shadow: inset 0 0 0 2px var(--primary); background: var(--primary-c); color: var(--on-primary-c); }
  .model:disabled { cursor: default; }
  .model.dim:not(.on) { opacity: .6; }
  .model b { font-size: 14px; padding-right: 96px; } .model small { color: var(--text-2); font-size: 12px; } .model.on small { color: inherit; opacity: .8; }
  .model .tag { position: absolute; top: 12px; right: 12px; }
  .key { display: flex; gap: 8px; margin-top: 14px; align-items: center; flex-wrap: wrap; }
  .key .input { flex: 1; min-width: 240px; }
  .dl { display: grid; gap: 14px; }
  .dl-head { display: flex; justify-content: space-between; gap: 12px; margin-bottom: 6px; }
  .dl .progress { height: 8px; border-radius: 4px; background: var(--surface-3); }
  .dl .progress i { background: var(--primary); transition: width .4s; }
  .dl-foot { margin-top: 0; display: flex; align-items: center; gap: 6px; }
  .okmark { color: var(--ok); display: inline-grid; }
  .err { color: var(--danger); font-size: 13px; margin-top: 6px; display: flex; align-items: center; gap: 8px; }
  .disc-card { margin: 24px 0 14px; overflow: hidden; }
  .disc { display: flex; align-items: center; gap: 12px; padding: 12px 16px; border-top: 1px solid var(--outline-2); cursor: pointer; }
  .disc:first-child { border-top: 0; }
  .disc:hover { background: var(--surface-2); }
  .disc .l { flex: 1; min-width: 0; } .disc .l b { display: block; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .disc .l small { color: var(--text-3); }
  .disc-empty { padding: 18px; color: var(--text-2); display: flex; align-items: center; gap: 8px; }
  .fico { width: 40px; height: 28px; border-radius: 8px; background: var(--surface-3); color: var(--text-2); font: 600 10px/28px var(--font); text-align: center;
    flex: none; letter-spacing: .02em; }
  .fico[data-ext="docx"], .fico[data-ext="rtf"] { background: #DCE7FB; color: #1B4FB4; }
  .fico[data-ext="pdf"] { background: #FBDDDB; color: #B3261E; }
  .fico[data-ext="md"], .fico[data-ext="txt"] { background: var(--secondary-c); color: var(--on-secondary-c); }
  .row { display: flex; gap: 8px; flex-wrap: wrap; }
  .row.folder { margin-top: 10px; }
  .row.folder .input { flex: 1; min-width: 240px; }
  .done-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 14px; margin: 28px 0; }
  .done-card { padding: 20px; display: flex; gap: 14px; align-items: center; }
  .done-card .ic { background: var(--primary-c); color: var(--on-primary-c); }
  .done-card .t2 { font-size: 13px; }
  @media (max-width: 760px) {
    .onb-top, .onb-body, .onb-bot { padding-left: 16px; padding-right: 16px; }
    .panels, .done-grid { grid-template-columns: 1fr; }
    h1 { font-size: 28px; line-height: 36px; }
    .steps i { width: 16px; }
  }
</style>
