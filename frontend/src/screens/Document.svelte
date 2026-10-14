<script>
  import { keyOf } from "../lib/keys.js";
  import Icon from "../components/Icon.svelte";
  import Page from "../components/Page.svelte";
  import Panes from "../components/Panes.svelte";
  import PopMenu from "../components/PopMenu.svelte";
  import SourceContext from "../components/SourceContext.svelte";
  import { explain } from "../lib/errors.js";
  import { api, pollJob } from "../lib/api.js";
  import { fmtDate, fmtTime } from "../lib/format.js";
  import { saveUrl } from "../lib/save.js";
  import { app, t, go, toast } from "../lib/state.svelte.js";

  let body = $state(null);
  let error = $state("");
  let viewing = $state(null);            // version number, null = latest
  let diff = $state(null);               // {from, to, changes} while comparing
  let build = $state(null);              // {progress, message} while building
  let editingTitle = $state(false);
  let titleDraft = $state("");
  let editAtom = $state(null);           // {atom_id, text}
  let freeDraft = $state(null);          // {section, id?, text}
  let fixes = $state({});                // `${atom_id}:${rule}` → {loading, statement}
  let exportSkills = $state([]);
  $effect(() => { api("/api/skills").then(b => (exportSkills = b.skills.filter(s => s.stage === "export" && !s.error))).catch(() => {}); });

  // Several documents per project (BRD, SRS, Vision & Scope, risks, As-Is/To-Be…), one tab each.
  let docList = $state(null);            // {documents, types, requirements_document}
  let confirmDelete = $state(null);      // the document about to be deleted
  const docId = $derived(app.route.doc || docList?.documents?.[0]?.id || null);
  async function loadDocs() {
    try { docList = await api(`/api/projects/${app.currentProjectId}/documents`); } catch (err) { error = err.message; }
  }
  $effect(() => { app.currentProjectId; app.atomsVersion; app.lang; loadDocs(); });
  async function createDoc(kind) {
    try {
      const d = await api(`/api/projects/${app.currentProjectId}/documents`, { method: "POST", body: { kind } });
      await loadDocs();
      go(`/document/${d.id}`);
    } catch (err) { toast(err.message, { kind: "danger" }); }
  }
  // Opened from a skill: "create a document of this type"
  let createdFor = null;
  $effect(() => {
    const kind = app.route.newKind;
    if (kind && docList && createdFor !== kind) { createdFor = kind; createDoc(kind); }
  });
  async function deleteDocById(d) {
    confirmDelete = null;
    try {
      await api(`/api/documents/${d.id}`, { method: "DELETE" });
      await loadDocs();
      go("/document");
    } catch (err) { toast(err.message, { kind: "danger" }); }
  }
  async function changeType(kind) {
    if (kind === doc.kind) return;
    try {
      await api(`/api/documents/${doc.id}`, { method: "PATCH", body: { kind } });
      await loadDocs();
      await load();
      toast(t("doc.type_changed"));
    } catch (err) { toast(err.message, { kind: "danger" }); }
  }
  const hasRequirements = $derived(!!body?.document?.decomposes);
  const typeTag = { functional: "fr", nfr: "nfr", question: "q", business: "br", risk: "rsk", current: "as" };
  async function setDecompose(on) {
    try {
      await api(`/api/documents/${doc.id}`, { method: "PATCH", body: { decompose: on } });
      await loadDocs();
      await load();
      toast(on ? t("doc.decompose_on") : t("doc.decompose_off"));
    } catch (err) { toast(err.message, { kind: "danger" }); }
  }

  async function load() {
    const pid = app.currentProjectId;
    if (!docId) return;
    try {
      const q = `?document=${docId}` + (viewing ? `&version=${viewing}` : "");
      const b = await api(`/api/projects/${pid}/document${q}`);
      if (pid !== app.currentProjectId) return;
      body = b;
      error = "";
      if (b.building && !build) follow(b.building);
    } catch (err) { error = err.message; }
  }
  $effect(() => { app.currentProjectId; app.atomsVersion; app.lang; docId; viewing; load(); });
  $effect(() => { docId; viewing = null; diff = null; });

  const doc = $derived(body?.document);
  const version = $derived(body?.version);
  const content = $derived(version?.content);
  const latest = $derived(body?.versions?.[0]?.number || 0);
  const isLatest = $derived(!version || version.number === latest);
  const stats = $derived(body?.stats);
  const freeBy = $derived.by(() => {
    const out = {};
    for (const f of body?.free_blocks || []) (out[f.section] ||= []).push(f);
    return out;
  });
  const findings = $derived.by(() => {
    if (!content) return [];
    const out = [];
    for (const sec of content.sections)
      for (const b of [...sec.blocks, ...(sec.subsections || []).flatMap(s => s.blocks)])
        if (b.kind === "req") for (const i of b.issues || []) out.push({ ...i, block: b });
    return out;
  });
  const projectLang = $derived(({ ru: "ru", en: "en" })[app.projects.find(p => p.id === app.currentProjectId)?.language] || null);
  const staleSections = $derived(body?.stale ? Object.keys(body.stale.sections).sort().join(", ") : "");

  async function follow(jobId) {
    build = { progress: 0, message: t("doc.writing") };
    try {
      const job = await pollJob(jobId, j => (build = { progress: j.progress || 0, message: j.progress_msg || "" }), { interval: 800 });
      viewing = null;
      diff = null;
      toast(t("doc.built", { v: job.result.version }));
    } catch (err) {
      const e = explain(err);
      toast(e.message, { kind: "danger", ...(e.setup ? { action: t("err.open_settings"), onAction: () => go("/settings") } : {}) });
    } finally {
      build = null;
      load();
    }
  }

  async function runBuild(mode, note = null) {
    confirmFull = false;
    refineOpen = false;
    try {
      const { job_id } = await api(`/api/projects/${app.currentProjectId}/document/build`, { method: "POST",
                                                                                          body: { mode, document_id: doc?.id || docId, ...(note ? { note } : {}) } });
      follow(job_id);
    } catch (err) {
      const e = explain(err);
      toast(e.message, { kind: "danger", ...(e.setup ? { action: t("err.open_settings"), onAction: () => go("/settings") } : {}) });
    }
  }

  async function patchDoc(changes) {
    try { body.document = await api(`/api/documents/${doc.id}`, { method: "PATCH", body: changes }); }
    catch (err) { toast(err.message, { kind: "danger" }); }
  }
  function saveTitle() {
    editingTitle = false;
    if (titleDraft.trim() && titleDraft.trim() !== doc.title) patchDoc({ title: titleDraft.trim() });
  }

  async function toggleDiff() {
    if (diff) { diff = null; return; }
    try { diff = await api(`/api/documents/${doc.id}/diff?to=${version.number}`); side = "changes"; }
    catch (err) { toast(err.message, { kind: "danger" }); }
  }

  // PM-12: a full rewrite is one click away from approved prose — ask first, and say what's kept.
  let confirmFull = $state(false);
  // PM-32: a one-off instruction for this build
  let refineOpen = $state(false);
  let refineNote = $state("");
  let reviewInput = $state(null);

  function exportMarkdown() {
    saveUrl(`/api/documents/${doc.id}/export.md?version=${version.number}`, `${doc.title} v${version.number}.md`.replace(/[\\/:*?"<>|]/g, ""));
  }
  function exportTrace() {
    saveUrl(`/api/projects/${app.currentProjectId}/traceability.xlsx?lang=${app.lang}`, `${doc.title} — traceability.xlsx`.replace(/[\\/:*?"<>|]/g, ""));
  }
  async function importReview(e) {
    const f = e.currentTarget.files[0];
    e.currentTarget.value = "";
    if (!f) return;
    const form = new FormData();
    form.append("file", f);
    try {
      const r = await api(`/api/documents/${doc.id}/review`, { method: "POST", form });
      toast(t("doc.review_imported", { n: r.comments, linked: r.linked }), { action: t("doc.review_open"),
                                                                             onAction: () => go(`/source/${r.source_id}`) });
    } catch (err) { toast(err.message, { kind: "danger" }); }
  }

  // Sign-off and change requests (PM-34)
  const baseline = $derived(body?.versions?.filter(v => v.status === "approved").map(v => v.number).sort((a, b) => b - a)[0] || null);
  let changes = $state(null);
  $effect(() => {
    if (doc && baseline && latest > baseline) {
      api(`/api/documents/${doc.id}/changes`).then(r => (changes = r)).catch(() => (changes = null));
    } else changes = null;
  });
  async function setStatus(status) {
    try {
      const r = await api(`/api/documents/${doc.id}/versions/${version.number}/status`, { method: "POST", body: { status } });
      body.versions = r.versions;
      toast(t("doc.st_set", { v: version.number, s: t("doc.st." + status) }));
    } catch (err) { toast(err.message, { kind: "danger" }); }
  }

  // Jira keys on requirements (PM-11)
  let jiraByReq = $state({});
  $effect(() => {
    app.currentProjectId; body;
    api(`/api/projects/${app.currentProjectId}/backlog`).then(b => {
      const m = {};
      for (const i of b.items) if (i.jira_key) for (const r of i.refs || []) (m[r.id] ||= []).push({ key: i.jira_key, url: i.jira_url });
      jiraByReq = m;
    }).catch(() => {});
  });

  // PM-27: fix every finding, accept the proposals, update once — one version, not one per finding.
  let fixingAll = $state(null);
  async function fixAll() {
    const list = findings.filter(f => !fixes[fixKey(f)]);
    fixingAll = { done: 0, total: list.length };
    let applied = 0;
    for (const f of list) {
      try {
        const { job_id } = await api(`/api/documents/${doc.id}/fix`, { method: "POST",
          body: { atom_id: f.block.atom_id, rule: f.rule, message: f.message } });
        const job = await pollJob(job_id, null, { interval: 700 });
        await api(`/api/atoms/${f.block.atom_id}`, { method: "PATCH", body: { statement: job.result.statement } });
        applied++;
      } catch (_) { /* skip this one, keep going */ }
      fixingAll = { done: fixingAll.done + 1, total: list.length };
    }
    fixingAll = null;
    app.atomsVersion++;
    if (applied) { toast(t("doc.fixed_all", { n: applied })); runBuild("changed"); }
  }

  function exportDocx() {
    const name = `${doc.title} v${version.number}.docx`.replace(/[\\/:*?"<>|]/g, "");
    saveUrl(`/api/documents/${doc.id}/export.docx?version=${version.number}&template=${doc.template}`, name);
  }

  // editing the atom behind a block (D-07: prose changes through atoms; marks the section stale)
  async function saveAtom() {
    const { atom_id, text } = editAtom;
    editAtom = null;
    try {
      await api(`/api/atoms/${atom_id}`, { method: "PATCH", body: { statement: text } });
      app.atomsVersion++;
    } catch (err) { toast(err.message, { kind: "danger" }); }
  }

  async function saveFree() {
    const f = freeDraft;
    freeDraft = null;
    if (!f.text.trim()) return;
    try {
      if (f.id) await api(`/api/free-blocks/${f.id}`, { method: "PATCH", body: { text: f.text } });
      else await api(`/api/documents/${doc.id}/free-blocks`, { method: "POST", body: { section: f.section, text: f.text } });
      load();
    } catch (err) { toast(err.message, { kind: "danger" }); }
  }
  async function removeFree(f) {
    await api(`/api/free-blocks/${f.id}`, { method: "DELETE" });
    load();
    toast(t("doc.free_deleted"), { action: t("at.undo"),
      onAction: async () => { await api(`/api/free-blocks/${f.id}/restore`, { method: "POST" }); load(); } });
  }

  const fixKey = f => `${f.block.atom_id}:${f.rule}`;
  async function fix(f) {
    fixes[fixKey(f)] = { loading: true };
    try {
      const { job_id } = await api(`/api/documents/${doc.id}/fix`, { method: "POST",
        body: { atom_id: f.block.atom_id, rule: f.rule, message: f.message } });
      const job = await pollJob(job_id, null, { interval: 700 });
      fixes[fixKey(f)] = { statement: job.result.statement };
    } catch (err) {
      delete fixes[fixKey(f)];
      toast(err.message, { kind: "danger" });
    }
  }
  async function acceptFix(f) {
    const statement = fixes[fixKey(f)].statement;
    delete fixes[fixKey(f)];
    try {
      await api(`/api/atoms/${f.block.atom_id}`, { method: "PATCH", body: { statement } });
      app.atomsVersion++;
      toast(t("doc.fix_applied"));
    } catch (err) { toast(err.message, { kind: "danger" }); }
  }
  async function dismiss(f) {
    await api(`/api/documents/${doc.id}/dismiss`, { method: "POST", body: { atom_id: f.block.atom_id, rule: f.rule } });
    load();
  }

  function sourcesLabel(b) {
    const n = b.sources.length;
    return n ? t("doc.from_atom_n", { n }) : t("doc.from_atom");
  }
  function sourceRef(s) {
    const date = s.source_date ? new Date(s.source_date * 1000).toLocaleDateString(app.lang, { day: "2-digit", month: "2-digit" }) : "";
    return [date, s.start != null ? fmtTime(s.start) : null].filter(Boolean).join(" — ");
  }
  function scrollTo(id) { document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" }); }
  const ago = ts => fmtDate(ts, app.lang);
  const staleIds = $derived(new Set(isLatest && body?.stale?.stale ? body.stale.atom_ids : []));
  const flaggedSecs = $derived.by(() => {
    const out = {};
    if (!content) return out;
    for (const sec of content.sections) {
      const all = [...sec.blocks, ...(sec.subsections || []).flatMap(x => x.blocks)].filter(b => b.kind === "req");
      if (all.some(b => b.conflict)) out[sec.key] = "danger";
      else if (all.some(b => (b.issues || []).length || staleIds.has(b.atom_id))) out[sec.key] = "warn";
    }
    return out;
  });
  // probability rows (high → low) × impact columns (low → high)
  const heatClass = (i, j) => { const score = (2 - i) + (j - 1); return score >= 3 ? "h-high" : score >= 2 ? "h-mid" : "h-low"; };
  const PREFIX = { functional: "FR", nfr: "NFR", question: "Q", business: "BR", risk: "RSK", current: "AS" };
  const typeOf = b => ({ FR: "fr", NFR: "nfr", Q: "q", BR: "br", RSK: "rsk", AS: "as" })[String(b.id).split("-")[0]] || "fr";

  // The selected requirement: its finding in the inspector, its evidence in the context pane.
  let selected = $state(null);           // block id, e.g. FR-3
  let side = $state("quality");          // inspector segment: quality | changes | info
  const allReqs = $derived(!content ? [] : content.sections.flatMap(sec =>
    [...sec.blocks, ...(sec.subsections || []).flatMap(x => x.blocks)].filter(b => b.kind === "req")));
  const selSource = $derived(allReqs.find(b => b.id === selected)?.sources?.[0] || null);
  $effect(() => { docId; selected = null; });
  function selectBlock(b, scroll = false) {
    selected = b.id;
    if (scroll) scrollTo("blk-" + b.id);
  }
  function exportPick(v) {
    if (v === "md") exportMarkdown();
    else if (v === "trace") exportTrace();
    else if (v.startsWith("tpl:")) patchDoc({ template: v.slice(4) });
  }
  // [ and ] walk the findings.
  function onKey(e) {
    const key = keyOf(e);
    if (app.route.name !== "document" || app.palette || e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.target.closest("input, textarea, select, [contenteditable], .menu")) return;
    if ((key === "[" || key === "]") && findings.length) {
      const i = findings.findIndex(f => f.block.id === selected);
      const next = findings[(i + (key === "]" ? 1 : -1) + findings.length) % findings.length] || findings[0];
      side = "quality";
      selectBlock(next.block, true);
      e.preventDefault();
    }
  }
</script>

<svelte:window onkeydown={onKey} />

<Page title={doc?.title || t("nav.document")} inspector={version ? "document" : ""}
        sub={!doc ? "" : version ? t("doc.sub", { v: version.number, n: version.atom_count, when: ago(version.created_at) }) + " · " + t("doc.st." + (version.status || "draft")).toLowerCase() : t("doc.never")}>
  {#snippet heading()}
    {#if doc && editingTitle}
      <!-- svelte-ignore a11y_autofocus -->
      <input class="input title-input" bind:value={titleDraft} autofocus onblur={saveTitle} aria-label={t("tr.edit_title")}
             onkeydown={e => { if (e.key === "Enter") saveTitle(); if (e.key === "Escape") editingTitle = false; }} />
    {:else}
      <h1 class="screen-title">{#if doc}<button class="title-btn" title={t("tr.edit_title")} onclick={() => { titleDraft = doc.title; editingTitle = true; }}>{doc.title}</button>{:else}{t("nav.document")}{/if}</h1>
    {/if}
  {/snippet}
  {#snippet actions()}
    {#if doc && !version}
      {#if stats?.accepted && body.relevant}
        <button class="btn primary" disabled={!!build} onclick={() => runBuild("full")}>{t("doc.build")}</button>
      {/if}
    {:else if doc && version}
      <PopMenu label={t("doc.status")} value={version.status || "draft"} ariaLabel={t("doc.st.label")}
               items={["draft", "review", "approved"].map(s => ({ value: s, label: t("doc.st." + s) }))} onpick={setStatus} />
      {#if version.number > 1}
        <button class="btn tb-opt" aria-pressed={!!diff} onclick={toggleDiff}>
          <Icon name="compare" size={14} /> {diff ? t("doc.hide_diff") : t("doc.diff", { v: version.number - 1 })}</button>
      {/if}
      <div class="split">
        <button class="btn" class:primary={!body.stale?.stale && !hasRequirements} onclick={exportDocx}><Icon name="word" size={14} /> {t("doc.export")}</button>
        <PopMenu cls={"btn tpl" + (!body.stale?.stale && !hasRequirements ? " primary" : "")} chevron="chevd" ariaLabel={t("doc.more_export")} align="right"
                 onpick={exportPick}
                 items={[{ heading: t("doc.template") },
                         ...exportSkills.map(s => ({ value: "tpl:" + s.name, label: s.title, icon: s.name === doc.template ? "check" : "word" })),
                         { sep: true },
                         { value: "md", label: t("doc.export_md"), icon: "file" },
                         { value: "trace", label: t("doc.export_trace"), icon: "table" }]} />
      </div>
      {#if body.stale?.stale}
        <button class="btn primary" disabled={!!build} onclick={() => runBuild("changed")}>
          <Icon name="refresh" size={14} /> {t("doc.rebuild")} · {body.stale.changed + body.stale.removed + body.stale.added}</button>
      {:else if hasRequirements}
        <button class="btn primary" onclick={() => go("/backlog")}>{t("doc.to_backlog")} <Icon name="arrow" size={14} /></button>
      {/if}
    {/if}
  {/snippet}

  <div class="doc-screen">
    {#if docList}
      <div class="tabs doc-tabs" role="tablist" aria-label={t("nav.document")}>
        {#each docList.documents as d (d.id)}
          <button role="tab" aria-selected={d.id === docId} onclick={() => go(`/document/${d.id}`)} title={d.title}>
            {d.short}{#if d.version}<span class="n">v{d.version}</span>{/if}
            {#if d.stale}<span class="dot warn" title={t("nav.st.stale")}></span>
            {:else if d.status === "approved"}<span class="dot ok" title={t("doc.st.approved")}></span>{/if}
          </button>
        {/each}
        <span class="add-wrap">
          <PopMenu cls="btn sm ghost" icon="plus" chevron="" text={t("doc.add")} ariaLabel={t("doc.add")} onpick={v => (v === "custom" ? go("/skills") : createDoc(v))}
                   items={[...docList.types.map(ty => ({ value: ty.name, label: ty.title, hint: (ty.atom_types || []).map(x => PREFIX[x]).join(" ") })),
                           { sep: true }, { value: "custom", label: t("doc.add_custom_short"), icon: "skills" }]} />
        </span>
      </div>
    {/if}

    {#if error}<div class="pad"><div class="banner danger"><Icon name="warn" /><span class="grow">{error}</span>
      <button class="btn sm" onclick={load}>{t("ov.retry")}</button></div></div>{/if}

    {#if body && !version}
      <div class="fill scroll">
        {#if build}
          <div class="pad"><div class="banner info"><span class="spinner"></span><span class="grow num">{build.message}</span>
            <span class="progress w"><i style="width: {build.progress}%"></i></span></div>
            <div class="paper skeleton">{#each [40, 92, 86, 70, 0, 30, 94, 88, 60] as w, i (i)}<i style="width: {w}%"></i>{/each}</div></div>
        {:else if !stats.accepted}
          <div class="empty">
            <div class="glyph"><Icon name="doc" size={20} /></div>
            <h3>{t("doc.no_atoms_title")}</h3>
            <p>{t("doc.no_atoms")}</p>
            <button class="btn lg primary" onclick={() => go("/atoms")}>{t("doc.to_atoms")} <Icon name="arrow" size={14} /></button>
          </div>
        {:else if body.relevant}
          <div class="empty">
            <div class="glyph"><Icon name="doc" size={20} /></div>
            <h3>{t("doc.ready_title", { n: body.relevant })}</h3>
            <p>{t("doc.ready")}</p>
            {#if stats.pending}<p class="hint">{t("doc.pending", { n: stats.pending })}</p>{/if}
            {#if docList && docList.documents.length > 1}
              <button class="btn ghost danger" onclick={() => (confirmDelete = doc)}>{t("doc.delete")}…</button>
            {/if}
          </div>
        {:else}
          <div class="empty">
            <div class="glyph"><Icon name="doc" size={20} /></div>
            <h3>{t("doc.no_relevant_title")}</h3>
            <p>{t("doc.no_relevant", { types: (doc.atom_types || []).map(ty => t("at.f." + ty)).join(", ") })}</p>
            <button class="btn lg" onclick={() => go("/atoms")}>{t("doc.to_atoms")} <Icon name="arrow" size={14} /></button>
            {#if docList && docList.documents.length > 1}
              <button class="btn ghost danger" onclick={() => (confirmDelete = doc)}>{t("doc.delete")}…</button>
            {/if}
          </div>
        {/if}
      </div>
    {:else if body && version}
      <div class="fill">
      <Panes screen="document" contentClass="deskpane">
        {#snippet outline()}
          <div class="pane-body scroll">
            <nav class="outline-body" aria-label={t("doc.toc")}>
              <p class="cap">{t("doc.toc")}</p>
              {#each content.sections as sec (sec.key)}
                <button class="ol-row" onclick={() => scrollTo("sec-" + sec.key)}><span class="n">{sec.number}</span><span class="grow">{sec.title}</span>
                  {#if flaggedSecs[sec.key]}<span class="dot {flaggedSecs[sec.key]}"></span>{/if}</button>
                {#each sec.subsections || [] as sub (sub.key)}
                  <button class="ol-row l2" onclick={() => scrollTo("sec-" + sub.key)}><span class="n">{sub.number}</span><span class="grow">{sub.title}</span></button>
                {/each}
              {/each}
              <p class="cap vers">{t("doc.versions")}</p>
              {#each body.versions as v (v.number)}
                <button class="ver" aria-current={v.number === version.number}
                        onclick={() => { diff = null; viewing = v.number === latest ? null : v.number; }}>
                  <b>{t("doc.version")} {v.number}</b>
                  <span class="status" class:ok={v.status === "approved"} class:accent={v.status === "review"}>{t("doc.st." + (v.status || "draft"))}</span>
                  <span class="num">{ago(v.created_at)} · {t("src.atoms_n", { n: v.atom_count })}</span>
                </button>
              {/each}
            </nav>
          </div>
        {/snippet}

        {#if build}
          <div class="over"><div class="banner info"><span class="spinner"></span><span class="grow num">{build.message}</span>
            <span class="progress w"><i style="width: {build.progress}%"></i></span></div></div>
        {:else if !isLatest}
          <div class="over"><div class="banner"><Icon name="clock" /><span class="grow">{t("doc.viewing_old", { v: version.number })}</span>
            <button class="btn sm" onclick={() => (viewing = null)}>{t("doc.back_latest", { v: latest })}</button></div></div>
        {/if}
        <div class="pane-body scroll" class:busy={!!build}>
          <div class="desk">
            <article class="paper">
              <p class="paper-kicker">{doc.short} · {t("doc.sub", { v: version.number, n: version.atom_count, when: ago(version.created_at) })}{#if version.model} · {version.model}{/if}</p>
              <h1>{doc.title}</h1>
              {#each content.sections as sec (sec.key)}
                <section class="sec" id="sec-{sec.key}">
                  <h2>{sec.number}. {sec.title}</h2>
                  {#each freeBy[sec.key] || [] as f (f.id)}
                    {@render freeBlock(f)}
                  {/each}
                  {@render blocks(sec.blocks)}
                  {#each sec.subsections || [] as sub (sub.key)}
                    <section class="sub" id="sec-{sub.key}">
                      <h3>{sub.number} {sub.title}</h3>
                      {@render blocks(sub.blocks)}
                    </section>
                  {/each}
                  {#if !sec.blocks.length && !(sec.subsections || []).length && !(freeBy[sec.key] || []).length}
                    <p class="muted-i">{t("doc.empty_section")}</p>
                  {/if}
                  {#if isLatest}
                    {#if freeDraft && !freeDraft.id && freeDraft.section === sec.key}
                      {@render freeEditor()}
                    {:else}
                      <button class="btn ghost sm add-free" onclick={() => (freeDraft = { section: sec.key, text: "" })}>
                        <Icon name="plus" size={14} /> {t("doc.add_free")}</button>
                    {/if}
                  {/if}
                </section>
              {/each}
            </article>
          </div>
        </div>

        {#snippet inspector()}
          <div class="pane-head">
            <div class="seg" role="tablist">
              <button role="tab" aria-selected={side === "quality"} onclick={() => (side = "quality")}>{t("doc.seg.quality")}{#if findings.length && isLatest}<span class="n">{findings.length}</span>{/if}</button>
              <button role="tab" aria-selected={side === "changes"} onclick={() => (side = "changes")}>{t("doc.seg.changes")}{#if diff}<span class="n">{diff.changes.length}</span>{/if}</button>
              <button role="tab" aria-selected={side === "info"} onclick={() => (side = "info")}>{t("doc.seg.info")}</button>
            </div>
          </div>
          <div class="pane-body scroll">
            {#if side === "quality"}
              <div class="findings">
                {#if isLatest && body.stale?.stale}
                  <div class="banner warn row-note">
                    <Icon name="warn" />
                    <span class="grow"><b>{t("doc.stale", { n: body.stale.changed + body.stale.removed + body.stale.added })}</b>{#if staleSections}. {t("doc.stale_sections", { s: staleSections })}{/if}</span>
                    <button class="btn sm" disabled={!!build} onclick={() => runBuild("changed")}>{t("doc.rebuild")}</button>
                  </div>
                {/if}
                {#if stats.open_conflicts}
                  <div class="banner danger"><Icon name="warn" /><span class="grow">{t("doc.conflicts", { n: stats.open_conflicts })}</span>
                    <button class="btn sm" onclick={() => go("/atoms")}>{t("at.resolve_conflicts")}</button></div>
                {/if}
                {#if isLatest && projectLang && content.language !== projectLang}
                  <div class="banner"><Icon name="info" /><span class="grow">{t("doc.lang_mismatch", { doc: t("lang." + content.language), want: t("lang." + projectLang) })}</span>
                    <button class="btn sm" disabled={!!build} onclick={() => (confirmFull = true)}>{t("doc.full")}</button></div>
                {/if}
                {#if stats.pending}<p class="hint">{t("doc.pending", { n: stats.pending })}</p>{/if}
                {#if !findings.length || !isLatest}
                  <div class="empty small"><div class="glyph ok"><Icon name="check" size={20} /></div><p>{isLatest ? t("doc.no_findings") : t("doc.findings_latest")}</p></div>
                {:else}
                  {#each findings as f (fixKey(f))}
                    <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
                    <div class="finding" aria-selected={selected === f.block.id} onclick={() => selectBlock(f.block, true)}>
                      <div class="finding-head">
                        <span class="status warn"><Icon name="warn" size={12} /> {t("doc.rule." + f.rule)}</span>
                        <span class="grow"></span><span class="mono t3">{f.block.id}</span>
                      </div>
                      <p>{f.message}</p>
                      {#if fixes[fixKey(f)]?.statement !== undefined}
                        <p class="cap">{t("doc.fix_proposal")}</p>
                        <textarea class="input" rows="3" bind:value={fixes[fixKey(f)].statement} aria-label={t("doc.fix_proposal")}
                                  onclick={e => e.stopPropagation()}></textarea>
                        <div class="finding-actions">
                          <button class="btn sm primary" disabled={!fixes[fixKey(f)].statement.trim()} onclick={e => { e.stopPropagation(); acceptFix(f); }}>{t("doc.fix_accept")}</button>
                          <button class="btn sm ghost" onclick={e => { e.stopPropagation(); delete fixes[fixKey(f)]; }}>{t("at.cancel")}</button>
                        </div>
                      {:else if fixes[fixKey(f)]?.loading}
                        <div class="finding-actions"><span class="spinner"></span> <span class="t3">{t("doc.fixing")}</span></div>
                      {:else}
                        <div class="finding-actions">
                          <button class="btn sm" onclick={e => { e.stopPropagation(); fix(f); }}><Icon name="spark" size={12} /> {t("doc.fix")}</button>
                          <button class="btn sm ghost" onclick={e => { e.stopPropagation(); dismiss(f); }}>{t("doc.dismiss")}</button>
                        </div>
                      {/if}
                    </div>
                  {/each}
                {/if}
              </div>
            {:else if side === "changes"}
              <div class="findings">
                {#if version.number > 1}
                  <button class="btn" onclick={toggleDiff}><Icon name="compare" size={14} /> {diff ? t("doc.hide_diff") : t("doc.diff", { v: version.number - 1 })}</button>
                {/if}
                {#if diff}
                  <p class="cap">{t("doc.diff_title", { a: diff.from, b: diff.to })}</p>
                  {#if !diff.changes.length}<p class="hint">{t("doc.no_changes")}</p>{/if}
                  {#each diff.changes as c (c.id + c.change)}
                    <div class="finding change {c.change}">
                      <div class="finding-head"><span class="mono">{c.id}</span><span class="t3 trunc grow">{c.section}</span>
                        <span class="badge {c.change === 'added' ? 'ok' : c.change === 'removed' ? 'danger' : 'warn'}">{t("doc.change." + c.change)}</span></div>
                      {#if c.moved_from}<p class="hint">{t("doc.moved", { s: c.moved_from })}</p>{/if}
                      {#if c.old}<p><del>{c.old}</del></p>{/if}
                      {#if c.new}<p><ins>{c.new}</ins></p>{/if}
                    </div>
                  {/each}
                {/if}
                {#if changes && changes.changes.length}
                  <p class="cap">{t("doc.cr_title", { a: changes.baseline, b: changes.to })}</p>
                  {#each changes.changes as c (c.id + c.change)}
                    <div class="finding cr">
                      <div class="finding-head"><span class="mono">{c.id}</span><span class="grow"></span>
                        <span class="badge {c.change === 'added' ? 'ok' : c.change === 'removed' ? 'danger' : 'warn'}">{t("doc.change." + c.change)}</span></div>
                      <p>{c.new || c.old}</p>
                      {#if c.impact.length}
                        <p class="hint">{t("doc.cr_impact")}: {#each c.impact as im, i (i)}{#if im.key}<a href={im.url} target="_blank" rel="noreferrer" class="mono">{im.key}</a>{:else}{im.title}{/if}{i < c.impact.length - 1 ? ", " : ""}{/each}</p>
                      {/if}
                    </div>
                  {/each}
                {:else if !diff}
                  <p class="hint">{version.number > 1 ? t("doc.changes_hint") : t("doc.changes_first")}</p>
                {/if}
              </div>
            {:else}
              <div class="insp-body">
                <div class="insp-sec">
                  <p class="cap">{t("doc.change_type")}</p>
                  <PopMenu value={doc.kind} ariaLabel={t("doc.change_type")} items={(docList?.types || []).map(ty => ({ value: ty.name, label: ty.title }))} onpick={changeType} />
                  <dl class="kv">
                    <dt>{t("doc.takes")}</dt>
                    <dd class="types">{#each doc.atom_types || [] as ty (ty)}<span class="type {typeTag[ty]}" title={t("at.full." + ty)}>{PREFIX[ty]}</span>{/each}</dd>
                    {#if doc.context_types?.length}
                      <dt>{t("doc.reads")}</dt>
                      <dd class="types">{#each doc.context_types as ty (ty)}<span class="type {typeTag[ty]}" title={t("at.full." + ty)}>{PREFIX[ty]}</span>{/each}</dd>
                    {/if}
                    {#if baseline}<dt>{t("doc.st.approved")}</dt><dd>{t("doc.version")} {baseline}</dd>{/if}
                    {#if version.model}<dt>{t("at.model")}</dt><dd class="t2 trunc">{version.model}</dd>{/if}
                  </dl>
                </div>
                <label class="sw">
                  <span><b>{t("doc.decompose")}</b><span class="hint">{t("doc.decompose_hint")}{#if doc.decomposes !== doc.decompose_default} {t("doc.changed_from_type")}{/if}</span></span>
                  <input type="checkbox" class="switch" checked={doc.decomposes} onchange={e => setDecompose(e.currentTarget.checked)} />
                </label>
                <div class="insp-sec">
                  <p class="cap">{t("doc.rebuilds")}</p>
                  <button class="btn" disabled={!!build} onclick={() => (confirmFull = true)}><Icon name="refresh" size={14} /> {t("doc.full")}</button>
                  <p class="hint">{t("doc.full_hint")}</p>
                  <button class="btn" onclick={() => { refineNote = ""; refineOpen = true; }}><Icon name="spark" size={14} /> {t("doc.refine")}</button>
                  <p class="hint">{t("ai.refine_hint")}</p>
                </div>
                <div class="insp-sec">
                  <p class="cap">{t("doc.client")}</p>
                  <button class="btn" onclick={() => reviewInput.click()}><Icon name="upload" size={14} /> {t("doc.import_review")}</button>
                  <input type="file" accept=".docx" class="hidden" bind:this={reviewInput} onchange={importReview} aria-label={t("doc.import_review")} />
                </div>
                {#if docList && docList.documents.length > 1}
                  <div class="insp-sec"><button class="btn sm ghost danger" onclick={() => (confirmDelete = doc)}><Icon name="trash" size={14} /> {t("doc.delete")}…</button></div>
                {/if}
              </div>
            {/if}
          </div>
          {#if side === "quality" && isLatest && findings.length > 1}
            <div class="pane-foot">
              <button class="btn primary" disabled={!!fixingAll || !!build} onclick={fixAll}>
                {#if fixingAll}<span class="spinner"></span> {fixingAll.done}/{fixingAll.total}{:else}{t("doc.fix_all", { n: findings.length })}{/if}</button>
            </div>
          {/if}
        {/snippet}

        {#snippet context()}
          <SourceContext sourceId={selSource?.source_id || null} segmentIdx={selSource?.segment_idx ?? null} quote={selSource?.quote || ""}
                         title={selSource?.source_title || ""} head={selected ? t("ctx.where", { code: selected }) : t("ctx.title")} />
        {/snippet}
      </Panes>
      </div>
    {/if}
  </div>
</Page>

{#if confirmFull}
  <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
  <div class="scrim" onclick={e => e.target === e.currentTarget && (confirmFull = false)}>
    <div class="sheet" role="dialog" aria-modal="true" aria-labelledby="full-h">
      <h2 id="full-h">{t("doc.full_q")}</h2>
      <p>{t("doc.full_body")}</p>
      <dl class="facts">
        <dt>{t("doc.full_kept")}</dt><dd>{t("doc.full_kept_v")}</dd>
        <dt>{t("doc.full_new")}</dt><dd>{t("doc.full_new_v")}</dd>
      </dl>
      <div class="acts">
        <!-- svelte-ignore a11y_autofocus -->
        <button class="btn" autofocus onclick={() => (confirmFull = false)}>{t("at.cancel")}</button>
        <button class="btn primary" onclick={() => runBuild("full")}>{t("doc.full_yes")}</button>
      </div>
    </div>
  </div>
{/if}

{#if refineOpen}
  <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
  <div class="scrim" onclick={e => e.target === e.currentTarget && (refineOpen = false)}>
    <div class="sheet" role="dialog" aria-modal="true" aria-labelledby="refine-h">
      <h2 id="refine-h">{t("doc.refine")}</h2>
      <p>{t("ai.refine_hint")}</p>
      <!-- svelte-ignore a11y_autofocus -->
      <textarea class="input" rows="3" bind:value={refineNote} autofocus placeholder={t("ai.refine_ph.doc")} aria-label={t("doc.refine")}></textarea>
      <div class="acts">
        <button class="btn" onclick={() => (refineOpen = false)}>{t("at.cancel")}</button>
        <button class="btn" disabled={!refineNote.trim() || !!build} onclick={() => runBuild("changed", refineNote)}>{t("doc.rebuild")}</button>
        <button class="btn primary" disabled={!refineNote.trim() || !!build} onclick={() => runBuild("full", refineNote)}>{t("doc.full_short")}</button>
      </div>
    </div>
  </div>
{/if}

{#if confirmDelete}
  <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
  <div class="scrim" onclick={e => e.target === e.currentTarget && (confirmDelete = null)}>
    <div class="sheet" role="dialog" aria-modal="true" aria-labelledby="del-h">
      <h2 id="del-h">{t("doc.delete_q", { title: confirmDelete.title })}</h2>
      <p>{t("doc.delete_body")}</p>
      <div class="acts">
        <!-- svelte-ignore a11y_autofocus -->
        <button class="btn" autofocus onclick={() => (confirmDelete = null)}>{t("at.cancel")}</button>
        <button class="btn danger-fill" onclick={() => deleteDocById(confirmDelete)}>{t("doc.delete_yes")}</button>
      </div>
    </div>
  </div>
{/if}

{#snippet freeEditor()}
  <div class="free-edit">
    <!-- svelte-ignore a11y_autofocus -->
    <textarea class="input" rows="3" bind:value={freeDraft.text} autofocus placeholder={t("doc.free_placeholder")}
              aria-label={t("doc.add_free")} onkeydown={e => e.key === "Escape" && (freeDraft = null)}></textarea>
    <div class="actions">
      <button class="btn sm primary" disabled={!freeDraft.text.trim()} onclick={saveFree}>{t("at.save")}</button>
      <button class="btn sm ghost" onclick={() => (freeDraft = null)}>{t("at.cancel")}</button>
    </div>
  </div>
{/snippet}

{#snippet freeBlock(f)}
  {#if freeDraft?.id === f.id}
    {@render freeEditor()}
  {:else}
    <div class="blk free">
      <p class="cap">{t("doc.free_cap")}</p>
      <p class="body">{f.text}</p>
      {#if isLatest}<div class="blk-acts">
        <button class="btn sm ghost" onclick={() => (freeDraft = { section: f.section, id: f.id, text: f.text })}>{t("at.edit")}</button>
        <button class="btn sm ghost danger" onclick={() => removeFree(f)}>{t("at.delete")}</button>
      </div>{/if}
    </div>
  {/if}
{/snippet}

{#snippet blocks(list)}
  {#each list as b (b.id)}
    {#if b.kind === "req"}
      <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
      <div class="blk req" id="blk-{b.id}" class:stale={staleIds.has(b.atom_id)} aria-selected={selected === b.id} onclick={() => selectBlock(b)}>
        <span class="req-id type plain {typeOf(b)}" title={sourcesLabel(b)}>{b.id}</span>
        {#if editAtom?.atom_id === b.atom_id}
          <div class="free-edit">
            <!-- svelte-ignore a11y_autofocus -->
            <textarea class="input" rows="3" bind:value={editAtom.text} autofocus aria-label={t("doc.edit_atom")} onclick={e => e.stopPropagation()}
                      onkeydown={e => e.key === "Escape" && (editAtom = null)}></textarea>
            <span class="hint">{t("doc.edit_atom_hint")}</span>
            <div class="actions">
              <button class="btn sm primary" disabled={!editAtom.text.trim()} onclick={e => { e.stopPropagation(); saveAtom(); }}>{t("at.save")}</button>
              <button class="btn sm ghost" onclick={e => { e.stopPropagation(); editAtom = null; }}>{t("at.cancel")}</button>
            </div>
          </div>
        {:else}
          <p class="body">{b.text}</p>
        {/if}
        <div class="req-foot">
          {#if b.sources.length}
            <span class="src" aria-label={sourcesLabel(b)}>
              {#each b.sources as s, i (i)}<button class="chip" title={s.quote}
                onclick={e => { e.stopPropagation(); go(`/source/${s.source_id}/seg/${s.segment_idx}`); }}><Icon name={s.start != null ? "wave" : "file"} size={12} />
                <span class="trunc">{s.source_title}</span>{#if sourceRef(s)}<span class="num mono">{sourceRef(s)}</span>{/if}</button>{/each}
            </span>
          {/if}
          {#each jiraByReq[b.id] || [] as j (j.key)}<a class="chip mono" href={j.url} target="_blank" rel="noreferrer" onclick={e => e.stopPropagation()}>{j.key}</a>{/each}
          {#if b.conflict}<span class="badge danger" title={b.conflict}>{t("at.conflict_with", { text: b.conflict })}</span>
          {:else if (b.issues || []).length}<span class="badge warn">{t("doc.rule." + b.issues[0].rule)}</span>
          {:else if staleIds.has(b.atom_id)}<span class="badge warn">{t("doc.block_stale")}</span>{/if}
          {#if isLatest && editAtom?.atom_id !== b.atom_id}
            <button class="btn sm ghost edit-req" onclick={e => { e.stopPropagation(); editAtom = { atom_id: b.atom_id, text: b.text }; }}>{t("doc.edit_atom")}</button>
          {/if}
        </div>
      </div>
    {:else if b.kind === "text"}
      <p class="prose">{b.text}</p>
    {:else if b.kind === "list"}
      {#if b.title}<p class="list-title">{b.title}</p>{/if}
      <ul class="prose-list">{#each b.items as item, i (i)}<li>{item}</li>{/each}</ul>
    {:else if b.kind === "table"}
      {#if b.title}<p class="list-title">{b.title}</p>{/if}
      <div class="doc-table-wrap" class:heat={b.heatmap}>
        <table class="doc-table">
          <thead><tr>{#each b.columns as c, i (i)}<th>{c}</th>{/each}</tr></thead>
          <tbody>
            {#each b.rows as r, i (i)}
              <tr>{#each r as v, j (j)}<td class={b.heatmap && j > 0 ? heatClass(i, j) : ""}>{v}</td>{/each}</tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
  {/each}
{/snippet}

<style>
  .doc-screen { display: grid; grid-template-rows: auto auto minmax(0, 1fr); height: 100%; min-height: 0; }
  .doc-screen > .fill { grid-row: 3; min-height: 0; container-type: inline-size; container-name: ws; }
  .pad { padding: var(--s-5) var(--gutter); display: grid; gap: var(--s-6); justify-items: center; }
  .pad .banner { width: min(100%, var(--w-paper)); }
  .title-btn:hover { color: var(--c-accent-text); }
  .title-input { font: var(--w-semibold) var(--t-title-3)/var(--lh-title-3) var(--font-display); width: min(520px, 40vw); height: 24px; }
  .doc-tabs { align-items: center; gap: var(--s-6); }
  .doc-tabs .dot { margin-left: 2px; }
  .add-wrap { display: inline-flex; margin-left: calc(var(--s-3) * -1); }
  .add-wrap :global(.menu) { position: fixed; top: auto; left: auto; margin-top: 24px; }
  .split :global(.pop .btn) { border-radius: 0 var(--r-sm) var(--r-sm) 0; padding: 0 var(--s-3); margin-left: 1px; }
  .split > .btn { border-radius: var(--r-sm) 0 0 var(--r-sm); }
  .progress.w { width: 120px; flex: none; }

  .outline-body { padding: var(--s-5) var(--s-4) var(--s-9); display: grid; gap: 1px; align-content: start; grid-template-columns: minmax(0, 1fr); }
  .outline-body .cap { padding: var(--s-3) var(--s-4); }
  .outline-body .vers { margin-top: var(--s-6); }
  .ol-row { display: flex; align-items: center; gap: var(--s-4); min-height: 28px; padding: var(--s-2) var(--s-4); border: 0; background: none;
    border-radius: var(--r-sm); text-align: left; width: 100%; color: var(--c-text-2); cursor: pointer; }
  .ol-row:hover { background: var(--c-fill-1); color: var(--c-text); }
  .ol-row.l2 { padding-left: var(--s-8); }
  .ol-row .n { color: var(--c-text-3); font-variant-numeric: tabular-nums; min-width: 20px; }
  .ver { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 0 var(--s-4); padding: var(--s-4); border-radius: var(--r-sm); border: 0;
    background: none; text-align: left; width: 100%; cursor: pointer; }
  .ver:hover { background: var(--c-fill-1); } .ver[aria-current="true"] { background: var(--c-fill-2); }
  .ver b { font-weight: var(--w-medium); }
  .ver .num { font-size: var(--t-foot); color: var(--c-text-3); grid-column: 1 / -1; }

  :global(.pane.deskpane) { background: var(--c-pane); container-type: inline-size; }
  .over { padding: var(--s-4) var(--gutter) 0; flex: none; }
  .busy { opacity: .6; transition: opacity var(--d-base); }
  .desk { padding: var(--s-8) var(--gutter) var(--s-12); display: flex; justify-content: center; align-items: flex-start; }
  .paper { width: 100%; max-width: var(--w-paper); background: var(--c-content); border-radius: var(--r-lg); box-shadow: var(--e-2);
    padding: clamp(40px, 7cqw, 72px) clamp(32px, 7cqw, 80px) clamp(56px, 8cqw, 96px) clamp(72px, 10cqw, 112px); }
  .paper.skeleton { display: grid; gap: var(--s-5); align-content: start; min-height: 60vh; }
  .paper.skeleton i { height: 12px; border-radius: var(--r-xs); background: var(--c-fill-2); animation: breathe 1.6s ease-in-out infinite; }
  @keyframes breathe { 50% { opacity: .45; } }
  .paper-kicker { font-size: var(--t-foot); color: var(--c-text-3); }
  .paper h1 { font: var(--w-bold) var(--t-large)/var(--lh-large) var(--font-display); letter-spacing: -.02em; margin: var(--s-3) 0 var(--s-9); text-wrap: balance; }
  .paper h2 { font: var(--w-semibold) var(--t-title-1)/var(--lh-title-1) var(--font-display); letter-spacing: -.016em; margin: var(--s-10) 0 var(--s-5); }
  .paper h3 { font: var(--w-semibold) var(--t-title-2)/var(--lh-title-2) var(--font-display); letter-spacing: -.012em; margin: var(--s-8) 0 var(--s-4); }
  .paper .body, .prose, .prose-list { font: var(--w-regular) var(--t-read)/var(--lh-read) var(--font); letter-spacing: -.005em; text-wrap: pretty; }
  .prose { margin: 0 0 var(--s-5); }
  .prose-list { margin: 0 0 var(--s-5); padding-left: 22px; }
  .list-title { font-weight: var(--w-semibold); margin: var(--s-4) 0 var(--s-2); }
  .muted-i { color: var(--c-text-3); font-style: italic; }
  .sec { scroll-margin-top: var(--s-6); } .sub { scroll-margin-top: var(--s-6); }
  .req { position: relative; padding: var(--s-4) var(--s-5); margin: var(--s-2) calc(var(--s-5) * -1); border-radius: var(--r-md);
    transition: background var(--d-fast); scroll-margin: 96px 0; cursor: default; }
  .req:hover { background: var(--c-fill-1); }
  .req[aria-selected="true"] { background: var(--c-accent-tint); }
  .req.stale { box-shadow: inset 2px 0 0 var(--c-warn-mark); border-radius: 0 var(--r-md) var(--r-md) 0; }
  .req-id { position: absolute; right: calc(100% + 4px); top: 11px; white-space: nowrap; }
  .req-foot { display: flex; flex-wrap: wrap; gap: var(--s-3); margin-top: var(--s-3); align-items: center; min-height: 24px; }
  .req-foot .src { display: contents; }
  .req-foot .chip { max-width: min(100%, 360px); text-decoration: none; }
  .edit-req { margin-left: auto; opacity: 0; transition: opacity var(--d-fast); }
  .req:hover .edit-req, .req[aria-selected="true"] .edit-req, .edit-req:focus-visible { opacity: 1; }
  @media (hover: none) { .edit-req { opacity: 1; } }
  .blk.free { margin: var(--s-4) calc(var(--s-5) * -1); padding: var(--s-4) var(--s-5); background: var(--c-fill-1); box-shadow: inset 2px 0 0 var(--c-line-control);
    border-radius: 0 var(--r-md) var(--r-md) 0; }
  .blk.free .cap { margin-bottom: 2px; }
  .blk-acts { display: flex; gap: var(--s-2); margin-top: var(--s-3); opacity: 0; transition: opacity var(--d-fast); }
  .blk.free:hover .blk-acts, .blk.free:focus-within .blk-acts { opacity: 1; }
  .free-edit { display: grid; gap: var(--s-3); margin: var(--s-3) 0; grid-template-columns: minmax(0, 1fr); }
  .free-edit textarea { font: var(--w-regular) var(--t-read)/var(--lh-read) var(--font); }
  .add-free { margin: var(--s-3) 0 0 calc(var(--s-4) * -1); opacity: .0; transition: opacity var(--d-fast); }
  .sec:hover .add-free, .add-free:focus-visible { opacity: 1; }
  @media (hover: none) { .add-free { opacity: 1; } }
  .doc-table-wrap { overflow-x: auto; margin: var(--s-4) 0 var(--s-6); }
  .doc-table { width: 100%; border-collapse: collapse; line-height: 18px; }
  .doc-table th { text-align: left; font-weight: var(--w-semibold); font-size: var(--t-foot); color: var(--c-text-2); background: var(--c-fill-1);
    padding: var(--s-3) var(--s-4); border: 1px solid var(--c-line); }
  .doc-table td { padding: var(--s-3) var(--s-4); border: 1px solid var(--c-line); vertical-align: top; }
  .doc-table td:first-child { white-space: nowrap; }
  .heat .doc-table { width: auto; }
  .heat .doc-table td { min-width: 110px; text-align: center; font-weight: var(--w-semibold); }
  .heat .doc-table td:first-child { text-align: left; font-weight: var(--w-medium); background: var(--c-fill-1); }
  .h-high { background: var(--c-danger-tint); color: var(--c-danger); }
  .h-mid { background: var(--c-warn-tint); color: var(--c-warn); }
  .h-low { background: var(--c-ok-tint); color: var(--c-ok); }

  .findings { padding: var(--s-5) var(--s-6) var(--s-9); display: grid; grid-template-columns: minmax(0, 1fr); gap: var(--s-4); align-content: start; }
  .finding { display: grid; grid-template-columns: minmax(0, 1fr); gap: var(--s-3); padding: var(--s-5); border-radius: var(--r-md); background: var(--c-content);
    box-shadow: 0 0 0 1px var(--c-line); text-align: left; transition: box-shadow var(--d-fast); }
  .finding:hover { box-shadow: 0 0 0 1px var(--c-line-strong); }
  .finding[aria-selected="true"] { box-shadow: 0 0 0 2px var(--c-accent); }
  .finding-head { display: flex; align-items: center; gap: var(--s-4); min-width: 0; }
  .finding p { color: var(--c-text-2); }
  .finding-actions { display: flex; gap: var(--s-3); flex-wrap: wrap; align-items: center; }
  .banner { align-items: flex-start; flex-wrap: wrap; }
  .banner :global(svg) { margin-top: 2px; flex: none; }
  .empty.small { padding: var(--s-9) 0; }
  .empty.small p { font-size: var(--t-body); }
  .glyph.ok { background: var(--c-ok-tint); color: var(--c-ok); }
  .types { display: flex; flex-wrap: wrap; gap: var(--s-4); }
  .sw { display: flex; align-items: center; gap: var(--s-6); justify-content: space-between; cursor: pointer; }
  .sw b { font-weight: var(--w-medium); display: block; }
  .sw .hint { display: block; }
  .insp-sec { justify-items: start; }
</style>
