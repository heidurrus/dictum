<script>
  import Icon from "../components/Icon.svelte";
  import Page from "../components/Page.svelte";
  import Panes from "../components/Panes.svelte";
  import PopMenu from "../components/PopMenu.svelte";
  import { api, pollJob } from "../lib/api.js";
  import { saveUrl, saveText } from "../lib/save.js";
  import { app, t, go, toast, currentProject } from "../lib/state.svelte.js";

  let connected = $state(null);
  let waiting = $state(false);           // sign-in open in the browser
  let target = $state(null);
  let editingTarget = $state(false);
  let sites = $state([]);
  let projects = $state([]);
  let pick = $state({ cloud_id: "", project_key: "", q: "", types: {} });
  let loadingProjects = $state(false);
  let preview = $state(null);            // {rows, counts, target}
  let selected = $state({});             // item_id → bool
  let busy = $state(null);               // {kind, progress, message}
  let confirming = $state(false);
  let result = $state(null);

  const KINDS = ["epic", "story", "nfr", "subtask"];

  async function status() {
    try { connected = (await api("/api/jira/status")).connected; } catch (_) { connected = false; }
  }
  async function loadTarget() {
    target = (await api(`/api/projects/${app.currentProjectId}/jira/target`)).target;
    editingTarget = !target;
  }
  $effect(() => { app.currentProjectId; preview = null; result = null; status(); loadTarget(); });
  $effect(() => { if (connected && !sites.length) loadSites(); });

  function fail(err) {
    if (err.body?.needs_connect) connected = false;
    toast(err.message, { kind: "danger", ms: 10000 });
  }

  let privateNote = $state("");
  async function connect(privateWindow = true) {
    try {
      const { url, opened_private } = await api("/api/jira/connect", { method: "POST", body: { private: privateWindow } });
      if (opened_private) {
        privateNote = t("jr.private_opened", { browser: opened_private });
      } else {
        privateNote = privateWindow ? t("jr.private_missing") : "";
        if (window.pywebview?.api?.open_url) await window.pywebview.api.open_url(url);
        else window.open(url, "_blank");
      }
      waiting = true;
      for (let i = 0; i < 150 && waiting; i++) {          // up to 5 minutes for the sign-in
        await new Promise(r => setTimeout(r, 2000));
        await status();
        if (connected) { waiting = false; toast(t("jr.connected")); loadSites(); break; }
      }
      waiting = false;
    } catch (err) { waiting = false; fail(err); }
  }
  async function disconnect() {
    await api("/api/jira/disconnect", { method: "POST" });
    connected = false;
    preview = null;
    sites = [];
    projects = [];
  }

  async function loadSites() {
    try {
      sites = (await api("/api/jira/sites")).sites;
      if (!pick.cloud_id) pick.cloud_id = target?.cloud_id || sites[0]?.cloud_id || "";
      if (pick.cloud_id) loadProjects();
    } catch (err) { fail(err); }
  }
  async function loadProjects() {
    loadingProjects = true;
    try {
      const q = pick.q ? `&q=${encodeURIComponent(pick.q)}` : "";
      projects = (await api(`/api/jira/projects?cloud_id=${pick.cloud_id}${q}`)).projects;
      if (target && target.cloud_id === pick.cloud_id && projects.some(p => p.key === target.project_key)) {
        pick.project_key = target.project_key;
        pick.types = { ...target.types };
      }
    } catch (err) { fail(err); }
    finally { loadingProjects = false; }
  }
  const chosenProject = $derived(projects.find(p => p.key === pick.project_key));
  function chooseProject(key) {
    pick.project_key = key;
    const p = projects.find(x => x.key === key);
    pick.types = p ? { ...p.suggested_types } : {};
  }
  async function saveTarget() {
    const site = sites.find(s => s.cloud_id === pick.cloud_id);
    try {
      target = (await api(`/api/projects/${app.currentProjectId}/jira/target`, { method: "PUT", body: {
        cloud_id: pick.cloud_id, site_url: site?.url || "", project_key: pick.project_key,
        project_name: chosenProject?.name, types: pick.types } })).target;
      editingTarget = false;
      preview = null;
    } catch (err) { fail(err); }
  }

  async function runPreview() {
    result = null;
    busy = { kind: "preview", progress: 0, message: t("jr.reading") };
    try {
      const { job_id } = await api(`/api/projects/${app.currentProjectId}/jira/preview`, { method: "POST" });
      const job = await pollJob(job_id, j => (busy = { kind: "preview", progress: j.progress || 0, message: j.progress_msg || "" }));
      preview = job.result;
      // Creates and updates start ticked; unchanged rows and rows edited in Jira need an explicit tick (FR-JIRA-03/06).
      selected = Object.fromEntries(preview.rows.map(r => [r.item_id,
        ["create", "update"].includes(r.action) && !r.flags.includes("changed_in_jira")]));
    } catch (err) { fail(err); }
    finally { busy = null; }
  }
  // The preview only reads, so it simply runs when the screen opens (PM review 2.5).
  let autoRan = $state(null);
  $effect(() => {
    if (connected && target && !editingTarget && !preview && !busy && autoRan !== app.currentProjectId) {
      autoRan = app.currentProjectId;
      runPreview();
    }
  });
  async function forgetOrphan(o) {
    try {
      const r = await api(`/api/projects/${app.currentProjectId}/jira/orphans/${encodeURIComponent(o.key)}/forget`, { method: "POST" });
      preview = { ...preview, orphans: r.orphans };
    } catch (err) { fail(err); }
  }
  const pushable = $derived(preview ? preview.rows.filter(r => ["create", "update"].includes(r.action) && selected[r.item_id]) : []);

  async function push(ids = pushable.map(r => r.item_id)) {
    confirming = false;
    busy = { kind: "push", progress: 0, message: "" };
    try {
      const { job_id } = await api(`/api/projects/${app.currentProjectId}/jira/push`, { method: "POST",
        body: { item_ids: ids, confirm_project_key: target.project_key } });
      const job = await pollJob(job_id, j => (busy = { kind: "push", progress: j.progress || 0, message: j.progress_msg || "" }));
      result = job.result;
      toast(t("jr.pushed", { n: result.done.length }));
      preview = null;
    } catch (err) { fail(err); }
    finally { busy = null; }
  }
  const indent = { epic: 0, story: 1, nfr: 1, subtask: 2 };
  const badge = { epic: "br", story: "fr", subtask: "as", nfr: "nfr" };     // the backlog's E/S badges
  const glyph = { epic: "E", story: "S", subtask: "T", nfr: "N" };
  const site = u => (u || "").replace("https://", "");
  const pushCounts = $derived({ create: pushable.filter(r => r.action === "create").length,
                                update: pushable.filter(r => r.action === "update").length });

  let cancelBtn = $state(null);
  $effect(() => { if (confirming && cancelBtn) cancelBtn.focus(); });
  function onKey(e) {
    if (app.route.name !== "export" || dest !== "jira") return;
    if (confirming && e.key === "Escape") { e.preventDefault(); confirming = false; return; }
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter" && preview && pushable.length && !busy) {
      e.preventDefault();
      if (confirming) push(); else confirming = true;
    }
  }

  // Four destinations, one place.
  let dest = $state("jira");             // jira | word | trace | letter
  let docs = $state([]);
  let templates = $state([]);
  let letter = $state(null);             // {text, question_ids}
  let letterText = $state("");
  let copied = $state(false);
  let showConn = $state(false);
  $effect(() => {
    app.currentProjectId; app.lang;
    api(`/api/projects/${app.currentProjectId}/documents`).then(b => (docs = b.documents.filter(d => d.version))).catch(() => (docs = []));
    api("/api/skills").then(b => (templates = b.skills.filter(s => s.stage === "export" && !s.error))).catch(() => {});
    api(`/api/projects/${app.currentProjectId}/followup?lang=${app.lang}`).then(b => { letter = b; letterText = b.text; }).catch(() => (letter = null));
  });
  const clean = s => s.replace(/[\\/:*?"<>|]/g, "");
  function exportDoc(d) {
    saveUrl(`/api/documents/${d.id}/export.docx?version=${d.version}&template=${d.template}`, clean(`${d.title} v${d.version}.docx`));
  }
  async function setTemplate(d, name) {
    try {
      await api(`/api/documents/${d.id}`, { method: "PATCH", body: { template: name } });
      docs = docs.map(x => (x.id === d.id ? { ...x, template: name } : x));
    } catch (err) { fail(err); }
  }
  function exportTrace() {
    saveUrl(`/api/projects/${app.currentProjectId}/traceability.xlsx?lang=${app.lang}`, clean(`${currentProject()?.name || "project"} — traceability.xlsx`));
  }
  async function copyLetter() {
    await navigator.clipboard.writeText(letterText);
    copied = true;
    setTimeout(() => (copied = false), 1500);
  }
  function saveEml() {
    const subject = t("ex.letter_subject", { name: currentProject()?.name || "" });
    saveText(clean(`${subject}.eml`), `Subject: ${subject}\nMIME-Version: 1.0\nContent-Type: text/plain; charset=utf-8\nX-Unsent: 1\n\n${letterText}\n`);
  }
  async function markSent() {
    try {
      await api(`/api/projects/${app.currentProjectId}/followup/sent`, { method: "POST", body: { question_ids: letter.question_ids } });
      toast(t("oi.marked", { n: letter.question_ids.length }));
      app.atomsVersion++;
    } catch (err) { fail(err); }
  }
  const pending = $derived(app.status?.export?.pending || 0);
  const pushed = $derived(app.status?.export?.pushed || 0);
  const dests = $derived([
    { id: "jira", icon: "jira", title: t("ex.jira"), sub: !connected ? t("ex.jira_off") : preview ? t("ex.jira_n", { n: pushable.length })
        : pushed ? t("ov.s.ex", { n: pushed }) : t("ex.jira_on") , state: connected ? (pending && pushed ? "warn" : pushed ? "ok" : "") : "" },
    { id: "word", icon: "word", title: t("ex.word"), sub: t("ex.word_n", { n: docs.length }), state: "" },
    { id: "trace", icon: "table", title: t("ex.trace"), sub: t("ex.trace_d"), state: "" },
    { id: "letter", icon: "mail", title: t("ex.letter"), sub: letter ? t("ex.letter_n", { n: letter.question_ids.length, a: letter.actions || 0 }) : "", state: "" },
  ]);
  const sub = $derived(target ? [target.project_key, target.project_name, site(target.site_url)].filter(Boolean).join(" · ") : t("ex.sub"));
</script>

<svelte:window onkeydown={onKey} />

<Page title={t("nav.export")} {sub} headClass="m" card={false}>
  {#snippet actions()}
    {#if dest === "jira" && connected && target && !editingTarget}
      <button class="btn" disabled={!!busy} onclick={runPreview}>
        <Icon name="refresh" size={14} /> {preview ? t("jr.refresh") : t("jr.show_preview")}</button>
      <button class="btn primary" disabled={!pushable.length || !!busy} onclick={() => (confirming = true)}>
        {pushable.length ? t("jr.push", { n: pushable.length }) : t("jr.nothing")}
        {#if pushable.length}<span class="kbd">⌘↵</span>{/if}</button>
    {:else if dest === "word" && docs.length > 1}
      <button class="btn primary" onclick={() => docs.forEach(exportDoc)}><Icon name="word" size={14} /> {t("ex.word_all")}</button>
    {:else if dest === "trace"}
      <button class="btn primary" onclick={exportTrace}><Icon name="download" size={14} /> {t("ex.trace_save")}</button>
    {:else if dest === "letter" && letter}
      <button class="btn primary" onclick={copyLetter}><Icon name={copied ? "check" : "copy"} size={14} /> {copied ? t("tr.copied") : t("ex.letter_copy")}</button>
    {/if}
  {/snippet}

  <div class="pane-cards">
  <Panes wideOutline>
    {#snippet outline()}
      <div class="pane-head"><h2>{t("ex.where")}</h2></div>
      <div class="pane-body scroll">
        <div class="dests">
          {#each dests as d (d.id)}
            <button class="dest" aria-current={dest === d.id} onclick={() => (dest = d.id)}>
              <span class="kind"><Icon name={d.icon} /></span>
              <b class="trunc">{d.title}</b>
              {#if d.state}<span class="dot {d.state}"></span>{:else}<span></span>{/if}
              <span class="sub trunc">{d.sub}</span>
            </button>
          {/each}
        </div>
      </div>
    {/snippet}

    {#if dest === "jira"}
      <div class="pane-body scroll">
        <div class="detail">
          {#if connected === false}
            <div class="empty">
              <div class="glyph"><Icon name="jira" size={20} /></div>
              <h3>{t("ex.connect_title")}</h3>
              <p>{t("jr.connect_hint")}</p>
              {#if privateNote}<p class="hint">{privateNote}</p>{/if}
              <button class="btn lg primary" disabled={waiting} onclick={() => connect(true)}>
                {#if waiting}<span class="spinner"></span> {t("jr.waiting")}{:else}{t("jr.connect")}{/if}</button>
              {#if !waiting}<button class="btn ghost" onclick={() => connect(false)}>{t("ex.normal_window")}</button>{/if}
            </div>
          {:else if connected}
            <section class="conn">
              <button class="conn-head" onclick={() => (showConn = !showConn)} aria-expanded={showConn || !target || editingTarget}>
                <span class="twist" class:open={showConn || !target || editingTarget}><Icon name="chevron" size={12} /></span>
                <b>{t("ex.connection")}</b>
                <span class="status ok"><Icon name="check" size={12} /> {t("jr.is_connected")}</span>
                {#if target && !editingTarget}<span class="t3 trunc grow">{target.project_key}{target.project_name ? " · " + target.project_name : ""} · {site(target.site_url)}</span>{/if}
              </button>
              {#if showConn || !target || editingTarget}
                <div class="conn-body">
                  <div class="form-card">
                    <div class="form-row">
                      <div><span class="lab">{t("jr.account")}</span>
                        {#if sites.length}<p>{t("jr.access", { sites: sites.map(s => site(s.url)).join(", ") })}</p>{/if}
                        {#if target && sites.length && !sites.some(s => s.cloud_id === target.cloud_id)}
                          <p class="danger-text">{t("jr.target_not_visible", { site: site(target.site_url) })}</p>
                        {:else if sites.length}<p>{t("jr.wrong_account")}</p>{/if}
                      </div>
                      <div class="ctl"><button class="btn" onclick={disconnect}>{t("jr.disconnect")}</button></div>
                    </div>
                    {#if target && !editingTarget}
                      <div class="form-row">
                        <div><span class="lab">{t("jr.target")}</span>
                          <p><b>{target.project_key}</b>{target.project_name ? " · " + target.project_name : ""} · {site(target.site_url)}</p>
                          <p>{KINDS.map(k => `${t("bl.kind_full." + k)} → ${target.types?.[k] || "—"}`).join(" · ")}</p></div>
                        <div class="ctl"><button class="btn" onclick={() => { editingTarget = true; loadSites(); }}>{t("jr.change")}</button></div>
                      </div>
                    {:else}
                      <div class="form-block">
                        <span class="lab">{t("jr.target")}</span>
                        <div class="grid2">
                          <div class="field">
                            <label class="label" for="jr-site">{t("jr.site")}</label>
                            <select class="select" id="jr-site" bind:value={pick.cloud_id} onchange={loadProjects}>
                              {#each sites as s (s.cloud_id)}<option value={s.cloud_id}>{s.url}</option>{/each}
                            </select>
                          </div>
                          <div class="field">
                            <label class="label" for="jr-q">{t("jr.search")}</label>
                            <div class="input-row">
                              <input class="input" id="jr-q" bind:value={pick.q} placeholder={t("jr.search_ph")}
                                     onkeydown={e => e.key === "Enter" && loadProjects()} />
                              <button class="btn" onclick={loadProjects} disabled={loadingProjects}>{t("jr.find")}</button>
                            </div>
                          </div>
                        </div>
                        {#if projects.length}
                          <div class="field">
                            <label class="label" for="jr-project">{t("jr.project")}</label>
                            <select class="select" id="jr-project" value={pick.project_key} onchange={e => chooseProject(e.currentTarget.value)}>
                              <option value="" disabled>{t("jr.choose_project")}</option>
                              {#each projects as p (p.key)}<option value={p.key}>{p.key} · {p.name}</option>{/each}
                            </select>
                          </div>
                        {/if}
                        {#if chosenProject}
                          <p class="label">{t("jr.types")}</p>
                          <div class="types">
                            {#each KINDS as k (k)}
                              <label class="field">
                                <span class="hint">{t("bl.kind_full." + k)}</span>
                                <select class="select" bind:value={pick.types[k]}>
                                  <option value={null}>—</option>
                                  {#each chosenProject.issue_types.filter(it => k === "subtask" ? it.subtask : !it.subtask) as it (it.id)}
                                    <option value={it.name}>{it.name}</option>
                                  {/each}
                                </select>
                              </label>
                            {/each}
                          </div>
                        {/if}
                        <div class="actions">
                          <button class="btn primary" disabled={!pick.project_key} onclick={saveTarget}>{t("at.save")}</button>
                          {#if target}<button class="btn ghost" onclick={() => (editingTarget = false)}>{t("at.cancel")}</button>{/if}
                        </div>
                      </div>
                    {/if}
                  </div>
                </div>
              {/if}
            </section>

            {#if target && !editingTarget}
              {#if busy}
                <div class="banner info"><span class="spinner"></span><span class="grow num">{busy.message}</span>
                  <span class="progress w"><i style="width: {busy.progress}%"></i></span></div>
              {:else if preview?.stale?.document || preview?.stale?.backlog}
                <div class="banner warn"><Icon name="warn" />
                  <span class="grow">{preview.stale.document ? t("jr.stale_doc") : t("jr.stale_backlog")}</span>
                  <button class="btn sm" onclick={() => go(preview.stale.document ? "/document" : "/backlog")}>{t("next.update_cta")}</button></div>
              {:else if preview && !result}
                <div class="banner"><Icon name="lock" /><span class="grow">{t("jr.no_writes")}
                  {#if preview.quotes !== "full"} {t("jr.quotes." + preview.quotes)}.{/if}</span></div>
              {/if}

              {#if result}
                <div class="result">
                  <div class="banner ok"><Icon name="check" /><span class="grow"><b>{t("jr.result", { n: result.done.length })}</b></span></div>
                  <table class="rtable"><tbody>
                    {#each result.done as d (d.item_id)}
                      <tr><td class="w1"><span class="status ok">{t("jr.did." + d.action)}</span></td>
                        <td class="w1"><a href={d.url} target="_blank" rel="noreferrer" class="mono">{d.key}</a></td>
                        <td>{d.title}</td></tr>
                    {/each}
                  </tbody></table>
                  {#if result.failed.length}
                    <div class="banner danger"><Icon name="warn" />
                      <div class="grow"><b>{t("jr.failed", { n: result.failed.length })}</b>
                        <ul>{#each result.failed as f (f.item_id)}<li>{f.title}: {f.error}</li>{/each}</ul></div>
                      <button class="btn sm" disabled={!!busy} onclick={() => push(result.failed.map(f => f.item_id))}>{t("jr.retry")}</button>
                    </div>
                  {/if}
                </div>
              {/if}

              {#if preview}
                <div class="counts">
                  {#each ["create", "update", "unchanged", "skip", "blocked"] as a (a)}
                    {#if preview.counts[a]}<div><b>{preview.counts[a]}</b><span>{t("jr.action." + a)}: {preview.counts[a]}</span></div>{/if}
                  {/each}
                </div>
                <div class="card-in"><table class="rtable pv">
                  <thead><tr>
                    <th class="w1"><span class="sr">{t("bl.to_jira")}</span></th><th>{t("bl.col.item")}</th>
                    <th class="c-wide">{t("bl.col.refs")}</th><th class="c-wide">{t("at.priority")}</th>
                    <th>{t("jr.col_key")}</th><th>{t("jr.col_action")}</th>
                  </tr></thead>
                  <tbody>
                    {#each preview.rows as r (r.item_id)}
                      <tr class:skip={["skip", "blocked", "unchanged"].includes(r.action) && !selected[r.item_id]}>
                        <td class="w1"><input type="checkbox" disabled={!["create", "update", "unchanged"].includes(r.action)}
                                              bind:checked={selected[r.item_id]} aria-label={r.title} /></td>
                        <td><div class="ttl" style="padding-left: calc({indent[r.kind]} * 20px)">
                          <span class="type idb {badge[r.kind]}" title={t("bl.kind_full." + r.kind)}>{glyph[r.kind]}</span>
                          <span class="grow">
                            <span class="tt">{r.title}</span>
                            {#if r.reason || r.flags.length}
                              <span class="why">{#if r.reason}{t("jr.reason." + r.reason)}{/if}{#each r.flags as f (f)}<span class:warn-t={f === "changed_in_jira"}>{r.reason ? " · " : ""}{t("jr.flag." + f)}</span>{/each}</span>
                            {/if}
                          </span>
                        </div></td>
                        <td class="c-wide mono t3">{(r.refs || []).map(x => x.id || x).join(", ")}</td>
                        <td class="c-wide t2">{r.priority ? t("at.prio." + r.priority) : ""}</td>
                        <td class="nowrap">{#if r.key}<a href={r.url} target="_blank" rel="noreferrer" class="mono">{r.key}</a>{:else}<span class="t3">—</span>{/if}</td>
                        <td class="nowrap"><span class="tag-m" class:ok={r.action === "create"} class:prim={r.action === "update"} class:danger={r.action === "blocked"}>{t("jr.act." + r.action)}</span></td>
                      </tr>
                    {/each}
                  </tbody>
                </table></div>
                <p class="hint note-line">{t("jr.target_note", { key: target.project_key })}</p>
              {:else if !busy && !result}
                <div class="empty"><div class="glyph"><Icon name="export" size={20} /></div>
                  <h3>{t("jr.show_preview")}</h3><p>{t("jr.no_writes")}</p></div>
              {/if}

              {#if preview?.orphans?.length}
                <section class="orphans">
                  <div class="sec-title"><h3>{t("jr.orphans_title", { n: preview.orphans.length })}</h3></div>
                  <p class="hint">{t("jr.orphans_desc")}</p>
                  {#each preview.orphans as o (o.key)}
                    <div class="orph-row">
                      <a href={o.url} target="_blank" rel="noreferrer" class="mono">{o.key}</a>
                      <span class="grow">{o.title}</span>
                      <button class="btn sm" onclick={() => forgetOrphan(o)}>{t("jr.orphan_done")}</button>
                    </div>
                  {/each}
                </section>
              {/if}
            {/if}
          {/if}
        </div>
      </div>
    {:else if dest === "word"}
      <div class="pane-body scroll">
        {#if !docs.length}
          <div class="empty"><div class="glyph"><Icon name="word" size={20} /></div><h3>{t("ex.word_none")}</h3><p>{t("ex.word_none_d")}</p>
            <button class="btn lg primary" onclick={() => go("/document")}>{t("bl.to_doc")} <Icon name="arrow" size={14} /></button></div>
        {:else}
          <table class="rtable">
            <thead><tr><th>{t("ex.col.doc")}</th><th>{t("doc.version")}</th><th>{t("doc.status")}</th><th>{t("doc.template")}</th><th></th></tr></thead>
            <tbody>
              {#each docs as d (d.id)}
                <tr>
                  <td><button class="link-t trunc" onclick={() => go(`/document/${d.id}`)}>{d.title}</button><span class="sub trunc">{d.type}</span></td>
                  <td class="num nowrap">v{d.version}{#if d.stale} <span class="status warn">{t("nav.st.stale")}</span>{/if}</td>
                  <td class="nowrap"><span class="tag-m" class:ok={d.status === "approved"} class:prim={d.status === "review"}>{t("doc.st." + (d.status || "draft"))}</span></td>
                  <td><PopMenu value={d.template} ariaLabel={t("doc.template")} items={templates.map(s => ({ value: s.name, label: s.title }))} onpick={v => setTemplate(d, v)} /></td>
                  <td class="w1"><button class="btn" onclick={() => exportDoc(d)}><Icon name="word" size={14} /> {t("ex.word_one")}</button></td>
                </tr>
              {/each}
            </tbody>
          </table>
        {/if}
      </div>
    {:else if dest === "trace"}
      <div class="pane-body scroll">
        <div class="empty">
          <div class="glyph"><Icon name="table" size={20} /></div>
          <h3>{t("ex.trace")}</h3>
          <p>{t("ex.trace_long")}</p>
          <button class="btn lg primary" onclick={exportTrace}><Icon name="download" size={14} /> {t("ex.trace_save")}</button>
        </div>
      </div>
    {:else}
      <div class="pane-body scroll">
        <div class="detail letter">
          {#if letter && (letter.question_ids.length || letter.actions)}
            <p class="hint">{t("ex.letter_hint")}</p>
            <textarea class="input" rows="22" bind:value={letterText} aria-label={t("ex.letter")}></textarea>
            <div class="actions">
              <button class="btn" onclick={saveEml}><Icon name="mail" size={14} /> {t("ex.letter_eml")}</button>
              <button class="btn" disabled={!letter.question_ids.length} onclick={markSent}>{t("ex.letter_sent")}</button>
            </div>
          {:else}
            <div class="empty"><div class="glyph"><Icon name="mail" size={20} /></div><h3>{t("ex.letter_none")}</h3><p>{t("ex.letter_none_d")}</p></div>
          {/if}
        </div>
      </div>
    {/if}
  </Panes>
  </div>
</Page>

{#if confirming && target}
  <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
  <div class="scrim" onclick={e => e.target === e.currentTarget && (confirming = false)}>
    <div class="sheet" role="dialog" aria-modal="true" aria-labelledby="push-q">
      <h2 id="push-q">{t("jr.confirm", { n: pushable.length, key: target.project_key, site: site(target.site_url) })}</h2>
      <p>{t("jr.sheet_body")}</p>
      <dl class="facts">
        <dt>{t("jr.site")}</dt><dd>{site(target.site_url)}</dd>
        <dt>{t("jr.project")}</dt><dd>{target.project_key}{target.project_name ? " · " + target.project_name : ""}</dd>
        {#if pushCounts.create}<dt>{t("jr.action.create")}</dt><dd class="num">{pushCounts.create}</dd>{/if}
        {#if pushCounts.update}<dt>{t("jr.action.update")}</dt><dd class="num">{pushCounts.update}</dd>{/if}
      </dl>
      <div class="acts">
        <button class="btn" bind:this={cancelBtn} onclick={() => (confirming = false)}>{t("at.cancel")}</button>
        <button class="btn primary" onclick={() => push()}>{t("jr.confirm_yes", { key: target.project_key })} <span class="kbd">⌘↵</span></button>
      </div>
    </div>
  </div>
{/if}

<style>
  /* 5.0: the destinations and the detail as cards; tonal connection card, count tiles, tables of the prototype */
  .pane-cards :global(.pane-head) { height: 56px; padding: 0 20px; border-bottom-color: var(--outline-2); }
  .dests { padding: 8px; display: grid; gap: 2px; }
  .dest { display: grid; grid-template-columns: 36px minmax(0, 1fr) auto; gap: 0 12px; align-items: center; padding: 10px 12px; border: 0;
    background: none; border-radius: 16px; text-align: left; width: 100%; cursor: pointer; color: var(--text); }
  .dest:hover { background: var(--surface-2); } .dest[aria-current="true"] { background: var(--secondary-c); color: var(--on-secondary-c); }
  .dest b { font-weight: 600; }
  .dest .sub { grid-column: 2 / span 2; font-size: 12px; color: var(--text-3); }
  .dest[aria-current="true"] .sub { color: inherit; opacity: .75; }
  .dest .kind { grid-row: 1 / span 2; align-self: center; }
  .kind { width: 36px; height: 36px; border-radius: 12px; background: var(--surface-2); color: var(--text-2); display: grid; place-items: center; flex: none; }
  .dest[aria-current="true"] .kind { background: var(--surface); }
  .detail { padding: 20px 20px 56px; display: grid; gap: 16px; grid-template-columns: minmax(0, 1fr); align-content: start; }
  .rtable td { vertical-align: middle; }
  .rtable th:first-child, .rtable td:first-child { padding-left: 20px; }
  .rtable th:last-child, .rtable td:last-child { padding-right: 20px; }
  .detail .rtable th:first-child, .detail .rtable td:first-child { padding-left: 14px; }
  .detail .rtable th:last-child, .detail .rtable td:last-child { padding-right: 14px; }
  .card-in { border-radius: 16px; box-shadow: inset 0 0 0 1px var(--outline-2); overflow: hidden; }
  .card-in .rtable tbody tr:last-child td { border-bottom: 0; }
  .w1 { width: 1%; white-space: nowrap; }
  .nowrap { white-space: nowrap; }
  .progress.w { width: 120px; flex: none; }
  .banner { border-radius: 16px; }
  .conn { border-radius: 20px; background: var(--surface-2); }
  .conn-head { display: flex; align-items: center; gap: var(--s-4); width: 100%; min-height: 52px; padding: 0 18px; border: 0; background: none;
    text-align: left; cursor: pointer; border-radius: 20px; min-width: 0; color: var(--text); }
  .conn-head b { font-weight: 600; }
  .twist { width: 16px; height: 16px; color: var(--text-3); display: grid; place-items: center; transition: transform var(--d-base) var(--ease-out); flex: none; }
  .twist.open { transform: rotate(90deg); }
  .conn-body { border-top: 1px solid var(--outline-2); }
  .form-row { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: var(--s-2) var(--s-8); align-items: center; padding: 14px 18px; }
  .form-row + .form-row, .form-row + .form-block { border-top: 1px solid var(--outline-2); }
  .form-block { padding: 14px 18px 18px; display: grid; gap: var(--s-5); grid-template-columns: minmax(0, 1fr); }
  .conn .btn { border-radius: 16px; box-shadow: none; background: var(--surface); }
  .conn .btn.primary { background: var(--primary); }
  .conn .btn.ghost { background: none; }
  .conn .input, .conn .select { background-color: var(--surface); border-radius: 12px; }
  .lab { font-weight: 500; }
  .form-row p { font-size: 12px; line-height: var(--lh-foot); color: var(--text-3); margin-top: 2px; }
  .grid2 { display: grid; gap: var(--s-5); grid-template-columns: repeat(auto-fit, minmax(min(100%, 260px), 1fr)); }
  .types { display: grid; gap: var(--s-5); grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); }
  .counts { display: flex; gap: 10px; flex-wrap: wrap; }
  .counts div { display: grid; padding: 12px 18px; border-radius: 16px; background: var(--surface-2); min-width: 120px; }
  .counts b { font: 600 24px/30px var(--font); letter-spacing: -.016em; font-variant-numeric: tabular-nums; }
  .counts span { font-size: 12px; color: var(--text-3); }
  .ttl { display: flex; align-items: flex-start; gap: 10px; min-width: 0; }
  .tt { font-weight: 500; display: block; }
  .why { display: block; font-size: 12px; color: var(--text-3); }
  .warn-t { color: var(--warn); }
  tr.skip .tt { color: var(--text-3); font-weight: 400; }
  .type.idb { flex: none; min-width: 20px; justify-content: center; margin-top: 1px; }
  .note-line { max-width: var(--w-measure); }
  .result { display: grid; gap: var(--s-4); grid-template-columns: minmax(0, 1fr); }
  .result ul { margin: var(--s-2) 0 0; padding-left: var(--s-6); }
  .sec-title { padding-bottom: var(--s-3); border-bottom: 1px solid var(--outline-2); }
  .sec-title h3 { font: 600 16px/22px var(--font); }
  .orphans { display: grid; gap: var(--s-3); }
  .orph-row { display: flex; align-items: center; gap: var(--s-5); padding: var(--s-3) 0; border-bottom: 1px solid var(--outline-2); }
  .orph-row .btn { border-radius: 14px; }
  .link-t { border: 0; background: none; padding: 0; font: 500 14px/20px var(--font); color: var(--text); cursor: pointer; text-align: left;
    display: block; max-width: 100%; }
  .link-t:hover { color: var(--primary); }
  .sub { font-size: 12px; color: var(--text-3); display: block; }
  .rtable :global(.popbtn) { border-radius: 14px; }
  .rtable .btn { border-radius: 16px; box-shadow: none; background: var(--surface-2); }
  .letter { max-width: 880px; }
  .letter textarea { font: 400 14px/22px var(--font); padding: 16px; border-radius: 16px; }
  .letter .btn { border-radius: 16px; }
</style>
