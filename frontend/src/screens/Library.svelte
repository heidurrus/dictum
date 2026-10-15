<script>
  // Материалы (spec 5.0 C5; prototype-v5 pageLibrary): documents, links and pasted text of the project.
  // Left: kinds and labels with counts. Middle: the add row, Граф (default) / Список / Плитка, the drop hint.
  // Right: the selected material: preview, labels (auto ones marked), the in-context switch, "Похожие материалы",
  // "Где используется", Открыть / Показать в Finder / Ещё. The header search runs the project-wide keyword search.
  // The graph, related materials and labels by meaning need the local index model; without it they offer the download.
  import Graph from "../components/Graph.svelte";
  import Icon from "../components/Icon.svelte";
  import Page from "../components/Page.svelte";
  import PopMenu from "../components/PopMenu.svelte";
  import { api, pollJob } from "../lib/api.js";
  import { extractAtoms } from "../lib/atoms.js";
  import { fmtBytes } from "../lib/audio.js";
  import { app, t, go, toast, currentProject, writePref } from "../lib/state.svelte.js";

  let list = $state([]);                  // GET /api/projects/<id>/materials
  let labels = $state([]);                // GET /api/projects/<id>/labels
  let loaded = $state(false);
  let kind = $state("all");
  let labelFilter = $state(null);
  let view = $state(readView());
  let selectedId = $state(null);
  let detail = $state(null);              // GET /api/materials/<id>: the preview, labels, in_context
  let busy = $state(false);
  let fileInput = $state(null);
  let dragging = $state(0);
  let sheet = $state(null);               // "url" | "text" | "folder" | "read"
  let form = $state({ url: "", title: "", text: "", folder: "" });
  let readText = $state("");
  let folderJob = $state(null);           // {progress, message} while a folder is imported
  let newLabel = $state(null);            // null: the "Создать метку" row; a string: the inline form
  let newLabelEl = $state(null);
  let graph = $state(null);               // GET /api/projects/<id>/materials/graph: nodes, edges, truncated, available
  let related = $state(null);             // GET /api/materials/<id>/related
  let usedIn = $state(null);              // GET /api/materials/<id>/used-in
  let indexing = $state(false);           // an index pass started from here is running
  let modelDl = $state(null);             // {done, total} while the index model downloads

  function readView() {
    try { const v = JSON.parse(localStorage.getItem("wb.libraryView")); return ["graph", "list", "grid"].includes(v) ? v : "graph"; }
    catch (_) { return "graph"; }
  }
  function setView(v) { view = v; writePref("libraryView", v); }

  // ── loading ───────────────────────────────────────────────────────────────
  async function load() {
    const pid = app.currentProjectId;
    if (!pid) return;
    try {
      const [m, l] = await Promise.all([api(`/api/projects/${pid}/materials`), api(`/api/projects/${pid}/labels`)]);
      if (pid !== app.currentProjectId) return;
      list = m.materials;
      labels = l.labels;
      loaded = true;
    } catch (err) { toast(err.message, { kind: "danger" }); }
    loadGraph();
  }
  async function loadGraph() {
    const pid = app.currentProjectId;
    try { const g = await api(`/api/projects/${pid}/materials/graph`); if (pid === app.currentProjectId) graph = g; }
    catch (_) { /* the list still works */ }
  }
  const indexReady = $derived(!!graph?.available);
  const shownIds = $derived(new Set(rows.map(m => m.id)));       // the graph follows the kind and label filters
  const graphNodes = $derived((graph?.nodes || []).filter(n => shownIds.has(n.id)));
  $effect(() => { app.currentProjectId; kind = "all"; labelFilter = null; query = ""; load(); });
  // #/library/<id> (a search hit, a requirement's evidence) selects that material.
  $effect(() => { if (app.route.name === "library" && app.route.id) selectedId = app.route.id; });

  const KINDS = [["all", "folder"], ["file", "doc"], ["url", "link"], ["note", "pencil"]];
  const countKind = k => (k === "all" ? list.length : list.filter(m => m.material_kind === k).length);
  const countLabel = id => list.filter(m => m.labels.some(l => l.id === id)).length;
  const rows = $derived(list.filter(m => (kind === "all" || m.material_kind === kind)
                                          && (!labelFilter || m.labels.some(l => l.id === labelFilter))));
  const selected = $derived(list.find(m => m.id === selectedId) || null);
  $effect(() => { if (loaded && !selected && rows.length) selectedId = rows[0].id; });

  $effect(() => {
    const id = selectedId, sel = selected;
    if (!id || !sel) { detail = null; return; }
    sel.title; sel.in_context; sel.labels; sel.error;
    api(`/api/materials/${id}`).then(b => { if (selectedId === id) detail = b; }).catch(() => {});
  });
  const cur = $derived(detail && detail.id === selectedId ? detail : null);
  // "Похожие материалы" and "Где используется" of the selected material; again whenever the graph was reloaded
  // (the index changed).
  $effect(() => {
    const id = selectedId;
    graph;
    if (!id) return;
    api(`/api/materials/${id}/related`).then(b => { if (selectedId === id) related = { ...b, id }; }).catch(() => {});
    api(`/api/materials/${id}/used-in`).then(b => { if (selectedId === id) usedIn = { ...b, id }; }).catch(() => {});
  });
  const rel = $derived(related?.id === selectedId ? related : null);
  const uses = $derived(usedIn?.id === selectedId ? usedIn : null);
  const pct = s => Math.round(s * 100) + "%";

  function patchRow(id, changes) {
    const row = list.find(m => m.id === id);
    if (row) Object.assign(row, changes);
    if (detail?.id === id) detail = { ...detail, ...changes };
  }

  // ── formatting ────────────────────────────────────────────────────────────
  const shortDate = ts => (ts ? new Date(ts * 1000).toLocaleDateString(app.lang === "en" ? "en-GB" : "ru-RU", { day: "numeric", month: "short" }) : "");
  function ago(ts) {
    const s = Math.max(0, Date.now() / 1000 - ts);
    if (s < 3600) return t("lib.ago_min", { n: Math.max(1, Math.round(s / 60)) });
    if (s < 86400) return t("lib.ago_h", { n: Math.round(s / 3600) });
    return shortDate(ts);
  }
  const changed = m => (m.material_kind === "url" ? (m.synced_at ? t("lib.synced", { when: ago(m.synced_at) }) : "—") : shortDate(m.updated_at));
  const size = m => (m.size ? fmtBytes(m.size) : "—");
  const badge = m => (m.ext || "txt").slice(0, 4).toUpperCase();
  const tagStyle = l => `background:${l.color}1f;color:${l.color}`;

  // ── adding ────────────────────────────────────────────────────────────────
  const ADD_ITEMS = $derived([
    { value: "files", label: t("lib.add.files"), icon: "upload" },
    { value: "url", label: t("lib.add.url"), icon: "link" },
    { value: "text", label: t("lib.add.text"), icon: "copy" },
    { value: "folder", label: t("lib.add.folder"), icon: "folder" },
  ]);
  function add(what) {
    if (what === "files") { fileInput?.click(); return; }
    form = { url: "", title: "", text: "", folder: "" };
    sheet = what;
  }
  async function added(body) {
    const done = body.materials || [], failed = body.failed || [];
    await load();
    if (done.length) { selectedId = done[0].id; kind = "all"; labelFilter = null; }
    const msg = t("lib.added_n", { n: done.length }) + (failed.length ? " · " + t("sources.failed_n", { n: failed.length }) : "");
    toast(failed.length ? msg + ": " + failed.join("; ") : msg, failed.length ? { kind: "danger" } : {});
    if (body.index_job) followIndex(body.index_job);
  }

  // ── the index ─────────────────────────────────────────────────────────────
  // A pass runs as a job (the status chip shows it); when it ends, labels may have landed and the graph changed.
  async function followIndex(jobId) {
    indexing = true;
    try { await pollJob(jobId); } catch (err) { toast(err.message, { kind: "danger" }); }
    finally { indexing = false; }
    await load();
  }
  async function reindex(materialId) {
    try {
      const b = await api(`/api/projects/${app.currentProjectId}/index`, { method: "POST", body: materialId ? { material_id: materialId } : {} });
      if (b.job_id) await followIndex(b.job_id);
      else await loadGraph();
    } catch (err) { toast(err.message, { kind: "danger" }); }
  }
  // "Скачайте модель индекса": the same download as the chat models (Settings → AI), then a first index pass.
  async function downloadModel() {
    if (modelDl) return;
    modelDl = { done: 0, total: graph?.size || 0 };
    try {
      let st = await api("/api/local-llm/download", { method: "POST", body: { model: graph?.model } });
      while (["downloading", "verifying"].includes(st.download?.status)) {
        modelDl = { done: st.download.done || 0, total: st.download.total || modelDl.total };
        await new Promise(r => setTimeout(r, 1000));
        st = await api("/api/local-llm");
      }
      if (st.download?.status === "error") throw new Error(st.download.error);
      modelDl = null;
      await reindex();
    } catch (err) { toast(err.message, { kind: "danger" }); }
    finally { modelDl = null; }
  }
  const dlPct = $derived(modelDl && modelDl.total ? Math.round(100 * modelDl.done / modelDl.total) : 0);
  async function uploadFiles(files) {
    files = [...(files || [])];
    if (!files.length || busy) return;
    const body = new FormData();
    files.forEach(f => body.append("files", f));
    busy = true;
    try { await added(await api(`/api/projects/${app.currentProjectId}/materials`, { method: "POST", form: body })); }
    catch (err) { toast(err.message, { kind: "danger" }); }
    finally { busy = false; }
  }
  async function submit(payload) {
    busy = true;
    try {
      const body = await api(`/api/projects/${app.currentProjectId}/materials`, { method: "POST", body: payload });
      if (body.job_id) { sheet = null; followFolder(body.job_id); return; }
      sheet = null;
      await added(body);
    } catch (err) { toast(err.message, { kind: "danger" }); }
    finally { busy = false; }
  }
  async function followFolder(jobId) {
    folderJob = { progress: 0, message: "" };
    try {
      const job = await pollJob(jobId, j => { folderJob = { progress: j.progress || 0, message: j.progress_msg || "" }; });
      await added({ materials: job.result.imported.map(id => ({ id })), failed: job.result.failed });
      if (job.result.truncated) toast(t("lib.folder_limit", { n: job.result.limit }));
      if (job.result.imported.length && indexReady) reindex();
    } catch (err) { toast(err.message, { kind: "danger" }); }
    finally { folderJob = null; }
  }
  function sheetSubmit(e) {
    e.preventDefault();
    if (sheet === "url") submit({ url: form.url.trim() });
    else if (sheet === "text") submit({ text: form.text, title: form.title });
    else if (sheet === "folder") submit({ folder: form.folder.trim() });
  }

  // The window-wide drop adds materials while this screen is open (Встречи has its own for meetings).
  const hasFiles = e => [...(e.dataTransfer?.types || [])].includes("Files");
  const hasLink = e => [...(e.dataTransfer?.types || [])].includes("text/uri-list");
  function onDrop(e) {
    if (hasFiles(e)) { e.preventDefault(); dragging = 0; uploadFiles(e.dataTransfer.files); }
    else if (hasLink(e)) {
      e.preventDefault(); dragging = 0;
      const url = (e.dataTransfer.getData("text/uri-list") || "").split("\n").find(l => l && !l.startsWith("#"));
      if (url) submit({ url: url.trim() });
    }
  }

  // ── a material ────────────────────────────────────────────────────────────
  async function setContext(m, on) {
    patchRow(m.id, { in_context: on });
    try { await api(`/api/materials/${m.id}`, { method: "PATCH", body: { in_context: on } }); }
    catch (err) { patchRow(m.id, { in_context: !on }); toast(err.message, { kind: "danger" }); }
  }
  async function resync() {
    const m = selected;
    if (!m) return;
    busy = true;
    try { const b = await api(`/api/materials/${m.id}/resync`, { method: "POST" }); patchRow(m.id, { synced_at: b.synced_at, error: b.error, size: b.size }); detail = b; }
    catch (err) { toast(err.message, { kind: "danger" }); }
    finally { busy = false; }
  }
  async function remove(m) {
    try {
      await api(`/api/materials/${m.id}`, { method: "DELETE" });
      list = list.filter(x => x.id !== m.id);
      if (selectedId === m.id) selectedId = null;
      await load();
      toast(t("sources.deleted", { title: m.title }), {
        action: t("sources.undo"),
        onAction: async () => { await api(`/api/sources/${m.id}/restore`, { method: "POST" }); await load(); selectedId = m.id; },
      });
    } catch (err) { toast(err.message, { kind: "danger" }); }
  }
  const desktop = () => !!window.pywebview?.api;
  async function openMaterial() {
    const m = cur;
    if (!m) return;
    if (desktop() && m.has_file) {
      try { await api(`/api/materials/${m.id}/open`, { method: "POST" }); return; }
      catch (_) { /* fall back to the text */ }
    }
    try { readText = (await api(`/api/materials/${m.id}?full=1`)).text; sheet = "read"; }
    catch (err) { toast(err.message, { kind: "danger" }); }
  }
  function reveal() { if (cur?.path) window.pywebview?.api?.reveal?.(cur.path); }
  const moreItems = $derived(!selected ? [] : [
    { value: "extract", label: t("at.extract"), icon: "spark", disabled: !selected.chars || !!app.extracting[selected.id] },
    ...(selected.material_kind === "url" ? [{ value: "resync", label: t("lib.resync"), icon: "refresh" }] : []),
    { value: "reindex", label: t("lib.reindex"), icon: "refresh", disabled: !indexReady || indexing },
    { sep: true },
    { value: "delete", label: t("sources.delete"), icon: "trash", danger: true },
  ]);
  function more(v) {
    if (!selected) return;
    if (v === "extract") extractAtoms(selected.id);
    else if (v === "resync") resync();
    else if (v === "reindex") reindex(selected.id);
    else if (v === "delete") remove(selected);
  }

  // ── labels ────────────────────────────────────────────────────────────────
  async function assign(m, labelId) {
    try {
      const b = await api(`/api/materials/${m.id}/labels/${labelId}`, { method: "POST" });
      patchRow(m.id, { labels: b.labels });
      loadGraph();
    } catch (err) { toast(err.message, { kind: "danger" }); }
  }
  async function unassign(m, l) {
    try {
      const b = await api(`/api/materials/${m.id}/labels/${l.id}`, { method: "DELETE" });
      patchRow(m.id, { labels: b.labels });
      loadGraph();
    } catch (err) { toast(err.message, { kind: "danger" }); }
  }
  // "Создать и назначить": the label goes on the selected material and, with the index, on every material close to
  // it in meaning; the toast counts them.
  async function createLabel(e) {
    e.preventDefault();
    const name = (newLabel || "").trim();
    if (!name) return;
    try {
      const b = await api(`/api/projects/${app.currentProjectId}/labels`, { method: "POST",
        body: { name, ...(selected ? { seed_material_id: selected.id } : {}) } });
      newLabel = null;
      await load();
      toast(b.index ? t("lib.label_assigned", { name: b.label.name, n: b.assigned.length }) : t("lib.label_created", { name: b.label.name }));
    } catch (err) { toast(err.message, { kind: "danger" }); }
  }
  const autoTip = l => t("lib.label_auto_tip", { p: pct(l.score || 0) });
  function startLabel() {
    newLabel = "";
    requestAnimationFrame(() => newLabelEl?.focus());
  }
  const labelItems = $derived(!selected ? [] : [
    ...labels.filter(l => !selected.labels.some(x => x.id === l.id)).map(l => ({ value: l.id, label: l.name })),
    ...(labels.length > selected.labels.length ? [{ sep: true }] : []),
    { value: "__new", label: t("lib.label_new_dots"), icon: "plus" },
  ]);
  function pickLabel(v) {
    if (v === "__new") startLabel();
    else if (selected) assign(selected, v);
  }

  // ── search ────────────────────────────────────────────────────────────────
  let query = $state("");
  let hits = $state(null);
  let searchWrap = $state(null);
  const needle = $derived(query.trim());
  $effect(() => {
    const q = needle, pid = app.currentProjectId;
    if (!q || !pid) { hits = null; return; }
    const timer = setTimeout(() => {
      api(`/api/projects/${pid}/search?q=${encodeURIComponent(q)}`)
        .then(b => { if (q === needle) hits = b.hits; }).catch(() => {});
    }, 180);
    return () => clearTimeout(timer);
  });
  const GROUPS = [["meetings", ["segment", "note"]], ["materials", ["material"]], ["atoms", ["atom"]]];
  const groups = $derived(!hits ? [] : GROUPS.map(([key, ents]) => ({ key, hits: hits.filter(h => ents.includes(h.entity)) }))
                                             .filter(g => g.hits.length));
  // The snippet marks matches with \x02…\x03; split it into parts, never into HTML.
  function parts(snippet) {
    const out = [];
    for (const [i, piece] of (snippet || "").split("\x02").entries()) {
      if (!i) { out.push({ t: piece }); continue; }
      const [m, rest = ""] = piece.split("\x03");
      out.push({ t: m, m: true }, { t: rest });
    }
    return out.filter(p => p.t);
  }
  function openHit(h) {
    query = "";
    if (h.entity === "segment") go(`/meeting/${h.source_id}/seg/${h.idx}`);
    else if (h.entity === "note") go(`/meeting/${h.source_id}`);
    else if (h.entity === "material") { kind = "all"; labelFilter = null; selectedId = h.id; go(`/library/${h.id}`); }
    else go(`/atoms/atom/${h.id}`);
  }
  const PREFIX = { functional: "FR", nfr: "NFR", question: "Q", business: "BR", risk: "RSK", current: "AS" };
  function onDoc(e) { if (needle && searchWrap && !searchWrap.contains(e.target)) query = ""; }

  const project = $derived(currentProject());
</script>

<svelte:window
  ondragenter={e => { if (hasFiles(e) || hasLink(e)) { e.preventDefault(); dragging++; } }}
  ondragover={e => { if (hasFiles(e) || hasLink(e)) e.preventDefault(); }}
  ondragleave={e => { if (hasFiles(e) || hasLink(e)) dragging = Math.max(0, dragging - 1); }}
  ondrop={onDrop} />
<svelte:document onmousedown={onDoc} />

<input type="file" multiple class="hidden" bind:this={fileInput} aria-label={t("lib.add.files")}
       onchange={e => { uploadFiles(e.currentTarget.files); e.currentTarget.value = ""; }} />

<Page title={t("nav.library")} sub={[project?.name || "", t("lib.sub")].filter(Boolean).join(" · ")} card={false}>
  {#snippet actions()}
    <div class="lsearch-wrap" bind:this={searchWrap}>
      <label class="lsearch"><Icon name="search" size={16} />
        <input type="search" bind:value={query} placeholder={t("lib.search")} aria-label={t("lib.search")}
               onkeydown={e => { if (e.key === "Escape") { query = ""; e.currentTarget.blur(); } }} /></label>
      {#if needle && hits}
        <div class="hits" role="listbox" aria-label={t("lib.search")}>
          {#each groups as g (g.key)}
            <p class="hsec">{t("lib.hits." + g.key)}</p>
            {#each g.hits.slice(0, 6) as h (h.entity + h.id)}
              <button class="hit" role="option" aria-selected="false" onclick={() => openHit(h)}>
                <span class="hk">{#if h.entity === "atom"}<span class="type plain">{PREFIX[h.type]}</span>
                  {:else if h.entity === "material"}<span class="fico {h.ext}">{(h.ext || "").slice(0, 4).toUpperCase()}</span>
                  {:else}<Icon name={h.entity === "note" ? "pencil" : "transcript"} size={14} />{/if}</span>
                <span class="hb"><b class="trunc">{h.title}</b>
                  <span class="snip">{#each parts(h.snippet) as p, k (k)}{#if p.m}<mark>{p.t}</mark>{:else}{p.t}{/if}{/each}</span></span>
              </button>
            {/each}
          {:else}
            <p class="hnone">{t("lib.hits.none")}</p>
          {/each}
        </div>
      {/if}
    </div>
    <PopMenu cls="btn lg primary" icon="plus" label={t("lib.add")} chevron="" align="right" items={ADD_ITEMS} onpick={add}
             disabled={busy || !!folderJob} />
  {/snippet}

  <div class="library">
    <nav class="card tree scroll" aria-label={t("nav.library")}>
      {#each KINDS as [k, icon] (k)}
        <button class="node" class:on={kind === k} aria-pressed={kind === k} onclick={() => (kind = k)}>
          <Icon name={icon} size={16} />{t("lib.kind." + k)}<span class="n">{countKind(k)}</span></button>
      {/each}
      <p class="sec">{t("lib.labels")}</p>
      {#each labels as l (l.id)}
        <button class="lbl" class:on={labelFilter === l.id} aria-pressed={labelFilter === l.id} data-label={l.name}
                onclick={() => (labelFilter = labelFilter === l.id ? null : l.id)}>
          <i style="background:{l.color}"></i><span class="trunc">{l.name}</span><span class="n">{countLabel(l.id)}</span></button>
      {/each}
      {#if newLabel === null}
        <button class="lbl add" onclick={startLabel}><Icon name="plus" size={14} />{t("lib.label_new")}</button>
      {:else}
        <form class="newlbl" onsubmit={createLabel}>
          <input bind:this={newLabelEl} bind:value={newLabel} placeholder={t("lib.label_name")} aria-label={t("lib.label_name")}
                 onkeydown={e => { if (e.key === "Escape") newLabel = null; }} />
          <button class="btn sm primary" type="submit" disabled={!newLabel.trim()}>{selected ? t("lib.label_create_assign") : t("lib.label_create")}</button>
        </form>
        <p class="lhint">{indexReady ? t("lib.label_hint") : t("lib.label_hint_noindex")}</p>
      {/if}
    </nav>

    <section class="card files" aria-label={t("lib.kind." + kind)}>
      <div class="addrow">
        <button class="btn sm" onclick={() => add("files")} disabled={busy}><Icon name="upload" size={14} /> {t("lib.add.files")}</button>
        <button class="btn sm" onclick={() => add("url")} disabled={busy}><Icon name="link" size={14} /> {t("lib.add.url")}</button>
        <button class="btn sm" onclick={() => add("text")} disabled={busy}><Icon name="copy" size={14} /> {t("lib.add.text")}</button>
        <button class="btn sm" onclick={() => add("folder")} disabled={busy || !!folderJob}><Icon name="folder" size={14} /> {t("lib.add.folder")}</button>
        <span class="grow"></span>
        <div class="vseg" role="group" aria-label={t("lib.view")}>
          <button class:on={view === "graph"} aria-pressed={view === "graph"} onclick={() => setView("graph")} title={t("lib.view.graph")}
                  aria-label={t("lib.view.graph")}><Icon name="tree" size={16} /></button>
          <button class:on={view === "list"} aria-pressed={view === "list"} onclick={() => setView("list")} title={t("lib.view.list")}
                  aria-label={t("lib.view.list")}><Icon name="transcript" size={16} /></button>
          <button class:on={view === "grid"} aria-pressed={view === "grid"} onclick={() => setView("grid")} title={t("lib.view.grid")}
                  aria-label={t("lib.view.grid")}><Icon name="atoms" size={16} /></button>
        </div>
      </div>
      {#if folderJob}
        <div class="banner info fjob"><span class="spinner"></span><span class="grow">{t("lib.folder_run", { p: folderJob.progress })} {folderJob.message}</span></div>
      {/if}
      {#snippet needModel(compact)}
        <div class="needmodel" class:compact class:empty={!compact}>
          {#if !compact}<span class="glyph" aria-hidden="true"><Icon name="tree" size={24} /></span>{/if}
          <b>{t("lib.index.need")}</b>
          <p>{t("lib.index.need_hint", { size: fmtBytes(graph?.size || 0) })}</p>
          {#if modelDl}
            <div class="dlbar"><i style:width={dlPct + "%"}></i></div>
            <span class="t3 small">{t("lib.index.downloading", { p: dlPct })}</span>
          {:else}
            <button class="btn sm primary" onclick={downloadModel}><Icon name="download" size={14} /> {t("lib.index.download")}</button>
          {/if}
        </div>
      {/snippet}
      {#if view === "graph" && !(loaded && !list.length)}
        {#if indexReady}
          <Graph nodes={graphNodes} edges={graph.edges} selected={selectedId} truncated={graph.truncated} onselect={id => (selectedId = id)} />
        {:else if graph}
          <div class="grow gwait">{@render needModel(false)}</div>
        {/if}
      {:else}
      <div class="scroll grow">
        {#if loaded && !list.length}
          <div class="empty">
            <span class="glyph" aria-hidden="true"><Icon name="folder" size={24} /></span>
            <h3>{t("lib.empty_title")}</h3>
            <p>{t("lib.empty")}</p>
          </div>
        {:else if view === "list"}
          <table class="ftable">
            <thead><tr><th>{t("lib.col.name")}</th><th>{t("lib.col.labels")}</th><th>{t("lib.col.changed")}</th>
              <th>{t("lib.col.size")}</th><th>{t("lib.col.context")}</th></tr></thead>
            <tbody>
              {#each rows as m (m.id)}
                <tr class="item" class:on={m.id === selectedId} data-id={m.id} onclick={() => (selectedId = m.id)}>
                  <td><span class="fname"><span class="fico {m.ext}">{badge(m)}</span><span class="trunc" title={m.title}>{m.title}</span></span></td>
                  <td><span class="tags">{#each m.labels as l (l.id)}<span class="ltag" style={tagStyle(l)}>{l.name}</span>{/each}</span></td>
                  <td class="t2 nowrap">{changed(m)}</td>
                  <td class="t2 num nowrap">{size(m)}</td>
                  <td><input type="checkbox" checked={m.in_context} aria-label={t("lib.context_on")} title={t("lib.context_on")}
                             onclick={e => e.stopPropagation()} onchange={e => setContext(m, e.currentTarget.checked)} /></td>
                </tr>
              {/each}
            </tbody>
          </table>
          {#if !rows.length}<div class="empty"><p>{t("lib.none_found")}</p></div>{/if}
        {:else}
          <div class="grid">
            {#each rows as m (m.id)}
              <div class="fcard item" class:on={m.id === selectedId} data-id={m.id} role="button" tabindex="0"
                   onclick={() => (selectedId = m.id)} onkeydown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); selectedId = m.id; } }}>
                <span class="fico {m.ext}">{badge(m)}</span>
                <div class="name">{m.title}</div>
                <div class="meta">{t("lib.kind1." + m.material_kind)} · {changed(m)}</div>
                {#if m.labels.length}<div class="tags">{#each m.labels as l (l.id)}<span class="ltag" style={tagStyle(l)}>{l.name}</span>{/each}</div>{/if}
                <label class="ctx"><input type="checkbox" checked={m.in_context} onclick={e => e.stopPropagation()}
                                          onchange={e => setContext(m, e.currentTarget.checked)} />{t("lib.in_context")}</label>
              </div>
            {/each}
          </div>
          {#if !rows.length}<div class="empty"><p>{t("lib.none_found")}</p></div>{/if}
        {/if}
        <div class="drop">{t("lib.drop")}</div>
      </div>
      {/if}
    </section>

    {#if selected}
      <aside class="card panel" aria-label={selected.title}>
        <div class="panel-head">
          <h2 class="trunc" title={selected.title}>{selected.title}</h2>
          <div class="meta"><span class="fico sm {selected.ext}">{badge(selected)}</span><span>{t("lib.kind1." + selected.material_kind)}</span>
            {#if selected.size}<span>{size(selected)}</span>{/if}<span>· {changed(selected)}</span></div>
        </div>
        <div class="panel-body scroll">
          {#if selected.material_kind === "url" && selected.error}
            <div class="banner {selected.error === 'offline' ? 'info' : 'warn'}"><Icon name={selected.error === "offline" ? "lock" : "warn"} />
              <span class="grow">{selected.error === "offline" ? t("lib.offline") : t("lib.fetch_error", { error: selected.error })}</span></div>
          {/if}
          {#if cur?.preview}<div class="doc">{cur.preview}</div>{/if}
          <dl class="kv">
            <dt>{t("lib.col.labels")}</dt>
            <dd class="tags">
              {#each selected.labels as l (l.id)}
                <span class="ltag chipx" style={tagStyle(l)} data-label={l.name}>{l.name}{#if l.assigned_by === "auto"}<small class="auto"
                  title={autoTip(l)}>{t("lib.label_auto")}</small>{/if}<button aria-label={t("lib.label_remove", { name: l.name })}
                  title={t("lib.label_remove", { name: l.name })} onclick={() => unassign(selected, l)}><Icon name="close" size={10} /></button></span>
              {/each}
              <PopMenu cls="chip sm addlbl" label={t("lib.label_add")} chevron="" items={labelItems} onpick={pickLabel} />
            </dd>
            {#if selected.url}<dt>{t("lib.address")}</dt><dd class="trunc" title={selected.url}>{selected.url}</dd>{/if}
            <dt>{t("lib.added")}</dt><dd>{shortDate(selected.created_at)}</dd>
          </dl>
          <label class="crow">
            <span class="l"><b>{t("lib.context_on")}</b><small>{t("lib.context_hint")}</small></span>
            <input type="checkbox" class="switch" checked={selected.in_context} onchange={e => setContext(selected, e.currentTarget.checked)} />
          </label>
          <div class="links related">
            <h4>{t("lib.related")}{#if rel?.related.length}{" · " + rel.related.length}{/if}</h4>
            {#if graph && !indexReady}
              {@render needModel(true)}
            {:else if rel}
              {#each rel.related as r (r.id)}
                <button class="r" onclick={() => (selectedId = r.id)}><span class="fico sm {r.ext}">{(r.ext || "txt").slice(0, 4).toUpperCase()}</span>
                  <span class="trunc">{r.title}</span><span class="pct">{pct(r.score)}</span></button>
              {:else}
                <p class="t3 small">{t("lib.related_none")}</p>
              {/each}
            {/if}
          </div>
          <div class="links uses">
            <h4>{t("lib.used_in")}{#if uses && uses.atoms.length + uses.documents.length}{" · " + (uses.atoms.length + uses.documents.length)}{/if}</h4>
            {#if uses}
              {#each uses.atoms as a (a.id)}
                <button class="r" onclick={() => go(`/atoms/atom/${a.id}`)}><Icon name="atoms" size={14} />
                  <span class="type plain">{a.rid || PREFIX[a.type]}</span><span class="trunc" title={a.statement}>{a.statement}</span></button>
              {/each}
              {#each uses.documents as d (d.id)}
                <button class="r" onclick={() => go(`/document/${d.id}`)}><Icon name="doc" size={14} />
                  <span class="trunc">{d.title}</span><span class="pct">v{d.version}</span></button>
              {/each}
              {#if !uses.atoms.length && !uses.documents.length}<p class="t3 small">{t("lib.used_none")}</p>{/if}
            {/if}
          </div>
        </div>
        <div class="panel-foot">
          <button class="btn lg tonal" onclick={openMaterial}><Icon name="pencil" size={14} /> {t("lib.open")}</button>
          {#if desktop() && cur?.has_file}<button class="btn lg" onclick={reveal}><Icon name="doc" size={14} /> {t("lib.reveal")}</button>{/if}
          {#if app.extracting[selected.id]}<span class="t3 small"><span class="spinner"></span> {app.extracting[selected.id].message}</span>{/if}
          <span class="up"><PopMenu cls="btn lg ghost icon" icon="more" chevron="" ariaLabel={t("tr.more")} title={t("tr.more")} align="right"
                            items={moreItems} onpick={more} /></span>
        </div>
      </aside>
    {/if}
  </div>
</Page>

{#if dragging}
  <div class="dropzone"><div><Icon name="upload" size={20} /><h3>{t("lib.drop_now")}</h3><p>{t("lib.drop")}</p></div></div>
{/if}

{#if sheet}
  <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
  <div class="scrim" onclick={e => e.target === e.currentTarget && (sheet = null)} onkeydown={e => e.key === "Escape" && (sheet = null)}>
    {#if sheet === "read"}
      <div class="sheet read" role="dialog" aria-modal="true" aria-labelledby="lib-sheet-h">
        <h2 id="lib-sheet-h">{selected?.title || ""}</h2>
        <div class="readtext scroll">{readText}</div>
        <div class="acts"><button class="btn primary" onclick={() => (sheet = null)}>{t("lib.close")}</button></div>
      </div>
    {:else}
      <div class="sheet" role="dialog" aria-modal="true" aria-labelledby="lib-sheet-h"><form class="sheet-form" onsubmit={sheetSubmit}>
        <h2 id="lib-sheet-h">{t("lib.sheet." + sheet)}</h2>
        {#if sheet === "url"}
          <!-- svelte-ignore a11y_autofocus -->
          <input class="input" type="url" required autofocus bind:value={form.url} placeholder="https://" aria-label={t("lib.add.url")} />
          <p class="t3 small">{project?.local_only ? t("lib.offline") : t("lib.url_hint")}</p>
        {:else if sheet === "text"}
          <input class="input" bind:value={form.title} placeholder={t("lib.text_name")} aria-label={t("lib.text_name")} />
          <!-- svelte-ignore a11y_autofocus -->
          <textarea class="input" rows="9" autofocus bind:value={form.text} placeholder={t("lib.text_body")} aria-label={t("lib.text_body")}></textarea>
        {:else}
          <!-- svelte-ignore a11y_autofocus -->
          <input class="input" autofocus bind:value={form.folder} placeholder={t("lib.folder_path")} aria-label={t("lib.folder_path")} />
          <p class="t3 small">{t("lib.folder_hint")}</p>
        {/if}
        <div class="acts">
          <button class="btn" type="button" onclick={() => (sheet = null)}>{t("at.cancel")}</button>
          <button class="btn primary" type="submit"
                  disabled={busy || (sheet === "url" && !form.url.trim()) || (sheet === "text" && !form.text.trim()) || (sheet === "folder" && !form.folder.trim())}>
            {#if busy}<span class="spinner"></span>{/if} {t("lib.add")}</button>
        </div>
      </form></div>
    {/if}
  </div>
{/if}

<style>
  /* prototype-v5 "Library" and "Library: labels and graph" */
  .library { display: grid; grid-template-columns: 224px minmax(0, 1fr) minmax(300px, 26%); gap: 14px; height: 100%; min-height: 0; }
  .card { background: var(--surface); border-radius: var(--r-l); box-shadow: var(--shadow-1); min-width: 0; min-height: 0; }
  .tree { padding: 10px 8px; display: flex; flex-direction: column; gap: 2px; }
  .node, .lbl { display: flex; align-items: center; gap: 8px; width: 100%; border: 0; background: none; text-align: left; cursor: pointer;
    font: inherit; color: var(--text-2); }
  .node { height: 36px; padding: 0 10px; border-radius: 12px; font-weight: 500; }
  .node:hover, .lbl:hover { background: var(--surface-2); }
  .node.on, .lbl.on { background: var(--secondary-c); color: var(--on-secondary-c); }
  .n { margin-left: auto; color: var(--text-3); font-size: 12px; font-weight: 400; }
  .sec { font-size: 11px; font-weight: 600; letter-spacing: .06em; text-transform: uppercase; color: var(--text-3); padding: 14px 10px 6px; }
  .lbl { height: 32px; padding: 0 10px; border-radius: 12px; font-size: 13px; }
  .lbl i { width: 10px; height: 10px; border-radius: 50%; flex: none; }
  .lbl.add { color: var(--primary); }
  .newlbl { display: flex; gap: 6px; padding: 6px 4px; flex-wrap: wrap; }
  .newlbl input { flex: 1; min-width: 0; height: 32px; border-radius: 10px; border: 0; background: var(--surface-2); padding: 0 10px; outline: none; }
  .newlbl input:focus { box-shadow: 0 0 0 2px var(--primary); }
  .lhint { color: var(--text-3); font-size: 11px; padding: 0 10px 6px; line-height: 15px; }

  .files { display: flex; flex-direction: column; overflow: hidden; }
  .addrow { display: flex; gap: 8px; padding: 12px 12px 4px; flex-wrap: wrap; align-items: center; flex: none; }
  .vseg { display: inline-flex; background: var(--surface-2); border-radius: 20px; padding: 3px; gap: 2px; }
  .addrow .btn { height: 36px; padding: 0 14px; border-radius: 18px; background: var(--surface-2); box-shadow: none; font-weight: 600; font-size: 13px; }
  .addrow .btn:hover:not(:disabled) { background: var(--surface-3); }
  .vseg button { display: inline-flex; align-items: center; justify-content: center; gap: 6px; height: 30px; width: 44px; border: 0; border-radius: 16px; background: none;
    font: 500 13px/1 var(--font); color: var(--text-2); cursor: pointer; }
  .vseg button.on { background: var(--surface); color: var(--text); box-shadow: var(--shadow-1); }
  .vseg button:disabled { opacity: .45; cursor: default; }
  .fjob { margin: 8px 12px 0; flex: none; }
  .ftable { width: 100%; border-collapse: collapse; }
  .ftable th { text-align: left; font-size: 12px; font-weight: 600; color: var(--text-3); padding: 8px 12px; border-bottom: 1px solid var(--outline-2); }
  .ftable td { padding: 10px 12px; border-bottom: 1px solid var(--outline-2); font-size: 13px; vertical-align: middle; }
  .ftable tbody tr { cursor: pointer; }
  .ftable tbody tr:hover td { background: var(--surface-2); }
  .ftable tr.on td { background: var(--secondary-c); }
  .fname { display: flex; align-items: center; gap: 10px; font-weight: 500; color: var(--text); min-width: 0; max-width: 42ch; }
  .nowrap { white-space: nowrap; }
  .fico { width: 28px; height: 28px; border-radius: 8px; display: inline-grid; place-items: center; font: 700 9px/1 var(--mono); color: #fff;
    background: #5F6368; flex: none; }
  .fico.sm { width: 22px; height: 22px; font-size: 8px; }
  .fico.md { background: #5B45C9; } .fico.docx { background: #2B579A; } .fico.pdf { background: #D93025; }
  .fico.url { background: #9A5A00; } .fico.html { background: #0A6D66; } .fico.eml { background: #8F5200; } .fico.rtf { background: #2B579A; }
  .tags { display: flex; gap: 4px; flex-wrap: wrap; align-items: center; }
  .ltag { display: inline-flex; align-items: center; gap: 4px; height: 22px; padding: 0 8px; border-radius: 6px; font-size: 12px; font-weight: 500; white-space: nowrap; }
  .chipx button { border: 0; background: none; padding: 0; margin-right: -2px; color: inherit; cursor: pointer; display: inline-grid; opacity: .7; }
  .chipx button:hover { opacity: 1; }
  .tags :global(.addlbl) { height: 22px; font-size: 12px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 12px; padding: 12px; }
  .fcard { background: var(--surface-2); border-radius: 18px; padding: 14px; cursor: pointer; display: grid; gap: 8px; align-content: start; outline: none; }
  .fcard:hover { background: var(--surface-3); } .fcard.on { background: var(--secondary-c); }
  .fcard:focus-visible { box-shadow: inset 0 0 0 2px var(--primary); }
  .fcard .name { font-weight: 600; line-height: 18px; word-break: break-word; }
  .fcard .meta { color: var(--text-3); font-size: 12px; }
  .ctx { display: flex; gap: 8px; align-items: center; font-size: 12px; color: var(--text-2); cursor: pointer; }
  .drop { margin: 8px 12px 12px; padding: 18px; border-radius: 16px; border: 2px dashed var(--outline); text-align: center; color: var(--text-3); font-size: 13px; }

  .panel { display: flex; flex-direction: column; }
  .panel-head { padding: 18px 20px 8px; flex: none; }
  .panel-head h2 { font-size: 20px; line-height: 26px; font-weight: 600; letter-spacing: -.01em; }
  .panel-head .meta { margin-top: 4px; display: flex; gap: 8px; align-items: center; color: var(--text-3); font-size: 13px; flex-wrap: wrap; }
  .panel-body { flex: 1; min-height: 0; padding: 12px 20px; display: grid; gap: 12px; align-content: start; }
  .doc { background: var(--surface-2); border-radius: 14px; padding: 14px; font-size: 13px; line-height: 20px; color: var(--text-2);
    max-height: 180px; overflow: hidden; position: relative; white-space: pre-wrap; word-break: break-word; }
  .doc::after { content: ""; position: absolute; left: 0; right: 0; bottom: 0; height: 50px; background: linear-gradient(transparent, var(--surface-2)); }
  .kv { display: grid; grid-template-columns: 110px minmax(0, 1fr); gap: 8px 10px; font-size: 13px; margin: 2px 0; }
  .kv dt { color: var(--text-3); } .kv dd { margin: 0; min-width: 0; }
  .crow { display: flex; gap: 12px; align-items: center; padding-top: 12px; border-top: 1px solid var(--outline-2); cursor: pointer; }
  .crow .l { flex: 1; display: grid; gap: 2px; }
  .crow small { color: var(--text-3); font-size: 12px; }
  .links h4 { font-size: 12px; font-weight: 600; color: var(--text-3); text-transform: uppercase; letter-spacing: .04em; margin: 6px 0 4px; }
  .links { display: grid; gap: 2px; }
  .links .r { display: flex; gap: 8px; align-items: center; padding: 6px 8px; border-radius: 10px; cursor: pointer; font: inherit; font-size: 13px;
    border: 0; background: none; color: var(--text); text-align: left; width: 100%; min-width: 0; }
  .links .r:hover { background: var(--surface-2); }
  .links .r .pct { margin-left: auto; color: var(--text-3); font-size: 12px; flex: none; }
  .links .r .type { flex: none; font: 600 11px var(--mono); color: var(--text-2); }
  .ltag .auto { font-size: 10px; font-weight: 600; opacity: .75; text-transform: lowercase; cursor: help; }
  .needmodel { display: grid; justify-items: center; gap: 8px; text-align: center; padding: 24px; max-width: 360px; }
  .needmodel.compact { justify-items: start; text-align: left; padding: 4px 0; gap: 6px; }
  .needmodel b { font-weight: 600; } .needmodel p { color: var(--text-3); font-size: 13px; line-height: 18px; }
  .needmodel.compact p { font-size: 12px; }
  .gwait { display: grid; place-items: center; min-height: 360px; }
  .dlbar { width: 200px; height: 6px; border-radius: 3px; background: var(--surface-3); overflow: hidden; }
  .dlbar i { display: block; height: 100%; background: var(--primary); }
  .small { font-size: 12px; }
  .panel-foot { display: flex; gap: 8px; padding: 12px 20px 16px; flex-wrap: wrap; align-items: center; flex: none; }
  .panel-foot .up :global(.menu) { top: auto; bottom: calc(100% + 6px); }
  .btn.tonal { background: var(--primary-c); color: var(--on-primary-c); box-shadow: none; }

  .lsearch-wrap { position: relative; }
  .lsearch { display: flex; align-items: center; gap: 10px; height: 44px; padding: 0 16px; border-radius: 22px; background: var(--surface-2);
    color: var(--text-2); width: min(320px, 40vw); }
  .lsearch input { flex: 1; min-width: 0; border: 0; background: none; outline: none; color: var(--text); font: inherit; box-shadow: none; }
  .lsearch:focus-within { box-shadow: 0 0 0 2px var(--primary); }
  .hits { position: absolute; top: calc(100% + 6px); right: 0; width: min(440px, 92vw); max-height: 60vh; overflow-y: auto; z-index: 60;
    background: var(--surface); border-radius: 16px; box-shadow: var(--shadow-3, var(--shadow-2)); padding: 6px; }
  .hsec { font-size: 11px; font-weight: 600; letter-spacing: .06em; text-transform: uppercase; color: var(--text-3); padding: 10px 10px 4px; }
  .hit { display: grid; grid-template-columns: 28px minmax(0, 1fr); gap: 10px; align-items: start; width: 100%; padding: 8px 10px; border: 0;
    border-radius: 12px; background: none; text-align: left; cursor: pointer; font: inherit; color: inherit; }
  .hit:hover, .hit:focus-visible { background: var(--surface-2); }
  .hk { display: grid; place-items: center; height: 28px; color: var(--text-2); }
  .hk .fico { width: 24px; height: 24px; font-size: 8px; }
  .hb { display: grid; gap: 2px; min-width: 0; }
  .hb b { font-weight: 600; font-size: 13px; }
  .snip { font-size: 12px; color: var(--text-3); line-height: 17px; overflow: hidden; display: -webkit-box; -webkit-line-clamp: 2; line-clamp: 2; -webkit-box-orient: vertical; }
  .snip mark { background: var(--primary-c); color: var(--on-primary-c); border-radius: 3px; padding: 0 1px; }
  .hnone { padding: 14px; color: var(--text-3); font-size: 13px; }

  .sheet-form { display: contents; }
  .sheet.read { width: min(720px, calc(100vw - 32px)); }
  .readtext { max-height: 60vh; white-space: pre-wrap; line-height: 21px; word-break: break-word; }
  .dropzone { position: fixed; inset: 0; z-index: 140; background: color-mix(in srgb, var(--primary) 14%, var(--scrim)); display: grid; place-items: center;
    pointer-events: none; }
  .dropzone div { background: var(--surface); border-radius: var(--r-xl); box-shadow: var(--shadow-3); padding: var(--s-9) var(--s-10); text-align: center;
    display: grid; justify-items: center; gap: var(--s-3); max-width: 480px; color: var(--primary); }
  .dropzone h3 { font: var(--w-semibold) var(--size-title-2)/var(--lh-title-2) var(--font); color: var(--text); }
  .dropzone p { color: var(--text-3); font-size: var(--size-foot); }

  @container ws (max-width: 1100px) {
    .library { grid-template-columns: 200px minmax(0, 1fr); }
    .panel { display: none; }
  }
  @media (max-width: 760px) {
    .library { grid-template-columns: minmax(0, 1fr); height: auto; }
    .files { min-height: 70vh; }
    .tree { flex-direction: row; flex-wrap: wrap; align-content: flex-start; }
    .tree .node, .tree .lbl { width: auto; }
    .tree .sec, .newlbl, .lhint { flex-basis: 100%; }
    .lsearch-wrap { flex: 1; min-width: 0; }
    .lsearch { width: 100%; }
  }
</style>
