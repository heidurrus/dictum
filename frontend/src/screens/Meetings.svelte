<script>
  // Встречи (spec 5.0 C2, prototype-v5 pageMeetings): the home page. The pipeline strip, the meeting list
  // (search, sort) and the details panel (tabs, in-place rename). Hosts the import picker, the window-wide
  // drop zone, the recording consent sheet and the microphone choice.
  import { keyOf } from "../lib/keys.js";
  import Icon from "../components/Icon.svelte";
  import Page from "../components/Page.svelte";
  import PopMenu from "../components/PopMenu.svelte";
  import FirstRun from "../components/FirstRun.svelte";
  import AsrOptions from "../components/AsrOptions.svelte";
  import Recap from "../components/Recap.svelte";
  import { api } from "../lib/api.js";
  import { cap, importFiles, transcribeSaved, loadMics, askThenRecord, confirmConsent, stopRecording } from "../lib/capture.svelte.js";
  import { extractAtoms } from "../lib/atoms.js";
  import { nextStep } from "../lib/next.js";
  import { fmtDate, fmtTime, renderMarkdown, speakerClass, speakerDisplay } from "../lib/format.js";
  import { audioLabel, fmtBytes, saveAudio } from "../lib/audio.js";
  import { app, t, go, loadSources, toast, rememberSource, currentProject } from "../lib/state.svelte.js";

  let selectedId = $state(null);
  let query = $state("");
  let sort = $state("new");
  let hits = $state(null);               // ids from the server search, in its order; null while there is no query
  let tab = $state("summary");
  let recOpen = $state(false);
  let recWrap = $state(null);
  let fileInput = $state(null);
  let dragging = $state(0);
  let titleEl = $state(null);

  $effect(() => { app.device.desktop; loadMics(); });
  $effect(() => { app.currentProjectId; selectedId = null; query = ""; });

  // ── the list ──────────────────────────────────────────────────────────────
  const SORTS = { new: (a, b) => (b.created_at || 0) - (a.created_at || 0), old: (a, b) => (a.created_at || 0) - (b.created_at || 0),
                  az: (a, b) => a.title.localeCompare(b.title, app.lang) };
  const needleQ = $derived(query.trim());
  // Search goes through the server (titles, the source text, segments); without a query the list sorts here.
  $effect(() => {
    const q = needleQ, s = sort, pid = app.currentProjectId;
    app.sources;                                     // refresh the hits when the list changes
    if (!q || !pid) { hits = null; return; }
    const timer = setTimeout(() => {
      api(`/api/projects/${pid}/sources?q=${encodeURIComponent(q)}&sort=${s}`)
        .then(b => { if (q === needleQ && pid === app.currentProjectId) hits = b.sources.map(x => x.id); }).catch(() => {});
    }, 180);
    return () => clearTimeout(timer);
  });
  const rows = $derived(hits ? hits.map(id => app.sources.find(s => s.id === id)).filter(Boolean)
                             : [...app.sources].sort(SORTS[sort]));
  const selected = $derived(rows.find(s => s.id === selectedId) || null);
  $effect(() => { if (!selected && rows.length) selectedId = rows[0].id; });

  // Processing rows started elsewhere (another session, before a restart) are not tracked in app.jobs: poll the list.
  const untracked = $derived(app.sources.some(s => s.status === "processing" && !app.jobs[s.id]));
  $effect(() => {
    if (!untracked) return;
    const timer = setInterval(() => loadSources().catch(() => {}), 3000);
    return () => clearInterval(timer);
  });

  const kindIcon = s => ({ recording: "mic", import: "upload" }[s.tags] || "doc");
  const people = s => (s.people ? s.people.split(", ").map(l => speakerDisplay(l, null, t)).join(", ") : "");
  function stateOf(s) {
    if (s.status === "recording") return { cls: "rec", text: t("rec.recording"), dot: true };
    if (app.extracting[s.id]) return { cls: "prim", text: t("src.st.extracting") };
    if (s.status === "processing") return { cls: "warn", text: app.jobs[s.id] ? t("meet.st.processing", { p: Math.round(app.jobs[s.id].progress || 0) }) : t("meet.st.processing_q") };
    if (s.status === "failed") return { cls: "danger", text: t("src.st.failed"), tip: s.error || "" };
    if (s.status === "recorded") return { cls: "", text: t("meet.st.raw") };
    return { cls: "ok", text: t("src.st.ready") };
  }

  function open(id) { rememberSource(id); go(`/meeting/${id}`); }
  function pick(id) { if (id !== selectedId) { selectedId = id; tab = "summary"; } }

  // ── header and strip ──────────────────────────────────────────────────────
  const project = $derived(currentProject());
  const s = $derived(app.status);
  const next = $derived(nextStep());
  const sub = $derived([project?.name || "", t("meet.count", { n: app.sources.length }),
    t("src.atoms_n", { n: s?.atoms?.total || 0 })].filter(Boolean).join(" · "));
  // The same states and words the old overview pipeline used; the chip the next step points at is marked.
  const stages = $derived(!s ? [] : [
    { key: "meetings", path: "/meetings", name: t("nav.meetings"), ring: !s.sources ? "" : s.processing ? "active" : "done", p: s.processing ? 50 : 100,
      text: !s.sources ? t("ov.s.sources_none") : s.processing ? t("ov.s.sources_run", { n: s.processing, all: s.sources }) : t("ov.s.sources", { n: s.sources }) },
    { key: "atoms", path: "/atoms", name: t("nav.atoms"), ring: !s.atoms.total ? "" : s.atoms.review ? "active" : s.atoms.conflicts ? "stale" : "done",
      p: s.atoms.total ? Math.round(100 * (s.atoms.total - s.atoms.review) / s.atoms.total) : 0,
      text: !s.atoms.total ? t("ov.s.atoms_none") : t("ov.s.atoms", { n: s.atoms.review, accepted: s.atoms.accepted })
            + (s.atoms.conflicts ? " · " + t("nav.st.conflicts", { n: s.atoms.conflicts }) : "") },
    { key: "document", path: "/document", name: s.document.version ? t("meet.pipe.doc", { v: s.document.version }) : t("meet.pipe.doc_none"),
      ring: !s.document.version ? "" : (s.document.stale || s.document.others_stale) ? "stale" : s.document.status === "approved" ? "done" : "active", p: 50,
      text: !s.document.version ? t("ov.s.doc_none") : s.document.stale ? t("next.doc_stale", { n: s.document.changed })
            : t("ov.s.doc", { n: s.document.count, v: s.document.version }) },
    { key: "backlog", path: "/backlog", name: t("nav.decomposition"), ring: !s.backlog.items ? "" : s.backlog.stale ? "stale" : "active", p: 100,
      text: !s.backlog.items ? t("ov.s.bl_none") : s.backlog.stale ? t("next.bl_stale") : t("ov.s.bl", { n: s.backlog.included }) },
    { key: "export", path: "/export", name: "Jira",
      ring: !s.export.pushed ? "" : (s.export.stale || s.export.orphans) ? "stale" : "done",
      p: s.export.pushed ? Math.round(100 * s.export.pushed / (s.export.pushed + s.export.pending)) : 0,
      text: !s.export.pushed ? t("ov.s.ex_none") : t("ov.s.ex", { n: s.export.pushed }) + (s.export.pending ? " · " + t("ov.s.ex_pending", { n: s.export.pending }) : "") },
  ]);
  const nextKey = $derived(!next?.go ? "" : next.go === "/sources" ? "meetings" : next.go.slice(1));

  // ── the panel ─────────────────────────────────────────────────────────────
  let detail = $state(null);             // GET /api/sources/<id>: summary, segments, atom marks, audio files
  let atoms = $state([]);
  $effect(() => {
    const id = selectedId, sel = selected;
    if (!id || !sel) { detail = null; atoms = []; return; }
    sel.status; sel.has_summary; sel.atom_count; app.atomsVersion;
    api(`/api/sources/${id}`).then(b => { if (selectedId === id) detail = b; }).catch(() => {});
    if (sel.status === "ready" && app.currentProjectId)
      api(`/api/projects/${app.currentProjectId}/atoms?source_id=${id}`)
        .then(b => { if (selectedId === id) atoms = b.atoms.filter(a => a.status !== "merged"); }).catch(() => {});
    else atoms = [];
  });
  const cur = $derived(detail && detail.id === selectedId ? detail : null);

  // The title is edited in place: blur or Enter saves, Escape puts it back.
  $effect(() => {
    const title = selected?.title || "";
    if (titleEl && document.activeElement !== titleEl) titleEl.textContent = title;
  });
  async function saveTitle() {
    const sel = selected;
    if (!sel || !titleEl) return;
    const title = (titleEl.textContent || "").replace(/\s+/g, " ").trim();
    if (!title || title === sel.title) { titleEl.textContent = sel.title; return; }
    try {
      await api(`/api/sources/${sel.id}`, { method: "PATCH", body: { title } });
      const row = app.sources.find(x => x.id === sel.id);
      if (row) row.title = title;
      toast(t("meet.renamed"));
    } catch (err) { titleEl.textContent = sel.title; toast(err.message, { kind: "danger" }); }
  }
  function titleKey(e) {
    if (e.key === "Enter") { e.preventDefault(); e.currentTarget.blur(); }
    else if (e.key === "Escape") { e.preventDefault(); e.currentTarget.textContent = selected?.title || ""; e.currentTarget.blur(); }
  }
  function startRename() {
    if (!titleEl) return;
    titleEl.focus();
    const range = document.createRange();
    range.selectNodeContents(titleEl);
    const sel = window.getSelection();
    sel.removeAllRanges(); sel.addRange(range);
  }

  async function remove(src) {
    try {
      await api(`/api/sources/${src.id}`, { method: "DELETE" });
      await loadSources();
      toast(t("sources.deleted", { title: src.title }), {
        action: t("sources.undo"),
        onAction: async () => { await api(`/api/sources/${src.id}/restore`, { method: "POST" }); await loadSources(); },
      });
    } catch (err) { toast(err.message, { kind: "danger" }); }
  }
  // The raw state saves the main file (both sides of a recording, or the imported file); the menu offers each one.
  function saveMainAudio() {
    const f = cur?.audio_files?.[0];
    if (f) saveAudio(cur, f).catch(e => toast(String(e?.message || e), { kind: "danger" }));
  }
  const audioItems = $derived((cur?.audio_files || []).map((f, _, all) =>
    ({ value: "audio:" + f.id, label: audioLabel(f, all.length), icon: "download", hint: fmtBytes(f.size) })));
  const moreItems = $derived(!selected ? [] : [
    ...(audioItems.length ? [...audioItems, { sep: true }] : []),
    { value: "extract", label: t("at.extract"), icon: "spark", disabled: selected.status !== "ready" || !!app.extracting[selected.id] },
    { value: "rename", label: t("sources.rename"), icon: "pencil" },
    { sep: true },
    { value: "delete", label: t("sources.delete"), icon: "trash", danger: true },
  ]);
  function more(v) {
    const sel = selected;
    if (!sel) return;
    if (v === "extract") extractAtoms(sel.id);
    else if (v === "rename") requestAnimationFrame(startRename);
    else if (v === "delete") remove(sel);
    else if (v.startsWith("audio:") && cur) { const f = cur.audio_files.find(x => x.id === v.slice(6)); if (f) saveAudio(cur, f); }
  }

  // Резюме: the recap in the chosen style; its [Name, mm:ss] references open the meeting at that line.
  async function reloadDetail() {
    const id = selectedId;
    if (id) { const b = await api(`/api/sources/${id}`).catch(() => null); if (b && selectedId === id) detail = b; }
  }
  function openAt(at) {
    if (!cur) return;
    let idx = null;
    for (const seg of cur.segments) if (seg.start != null && seg.start <= at + 0.5) idx = seg.idx;
    if (idx == null && cur.segments.length) idx = cur.segments[0].idx;
    rememberSource(cur.id);
    go(idx == null ? `/meeting/${cur.id}` : `/meeting/${cur.id}/seg/${idx}`);
  }

  // Транскрипт: read-only lines with the quoted spans marked; a search highlights hits and counts them.
  let find = $state("");
  $effect(() => { selectedId; find = ""; });
  const marks = $derived(cur?.atom_marks || {});
  const speakerOrder = $derived(cur ? [...new Set(cur.segments.map(x => x.speaker).filter(Boolean))] : []);
  const needle = $derived(find.trim().toLowerCase());
  const PREFIX = { functional: "FR", nfr: "NFR", question: "Q", business: "BR", risk: "RSK", current: "AS" };
  const typeClass = { functional: "fr", nfr: "nfr", question: "q", business: "br", risk: "rsk", current: "as" };
  function quoteParts(seg) {
    const list = (marks[seg.idx] || []).filter(m => m.status !== "rejected" && m.quote);
    const low = seg.text.toLowerCase();
    const spans = [];
    for (const m of list) {
      const i = low.indexOf(m.quote.toLowerCase());
      if (i >= 0) spans.push([i, i + m.quote.length]);
    }
    spans.sort((a, b) => a[0] - b[0]);
    const out = [];
    let at = 0;
    for (const [a, b] of spans) {
      if (a < at) continue;
      if (a > at) out.push({ t: seg.text.slice(at, a) });
      out.push({ t: seg.text.slice(a, b), q: true });
      at = b;
    }
    if (at < seg.text.length) out.push({ t: seg.text.slice(at) });
    return out;
  }
  function pieces(seg) {
    const parts = quoteParts(seg);
    if (!needle) return parts;
    const out = [];
    for (const p of parts) {
      const low = p.t.toLowerCase();
      let at = 0, i;
      while ((i = low.indexOf(needle, at)) >= 0) {
        if (i > at) out.push({ t: p.t.slice(at, i), q: p.q });
        out.push({ t: p.t.slice(i, i + needle.length), q: p.q, h: true });
        at = i + needle.length;
      }
      if (at < p.t.length) out.push({ t: p.t.slice(at), q: p.q });
    }
    return out;
  }
  const hitCount = $derived.by(() => {
    if (!needle || !cur) return 0;
    let n = 0;
    for (const seg of cur.segments) { const low = seg.text.toLowerCase(); let i = -1; while ((i = low.indexOf(needle, i + 1)) >= 0) n++; }
    return n;
  });

  // ── keys, drop, recording ────────────────────────────────────────────────
  function onKey(e) {
    const key = keyOf(e);
    if (app.route.name !== "meetings" || app.palette || e.target.closest("input, textarea, select, [contenteditable], .menu")) return;
    if ((e.metaKey || e.ctrlKey) && (key === "o" || key === "O")) { e.preventDefault(); fileInput?.click(); return; }
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const i = rows.findIndex(x => x.id === selectedId);
    if (key === "ArrowDown" || key === "j") { if (rows[i + 1]) pick(rows[i + 1].id); }
    else if (key === "ArrowUp" || key === "k") { if (i > 0) pick(rows[i - 1].id); }
    else if (key === "Enter" && selected) open(selected.id);
    else if (key === "Escape") recOpen = false;
    else return;
    e.preventDefault();
    requestAnimationFrame(() => document.getElementById(`src-${selectedId}`)?.scrollIntoView({ block: "nearest" }));
  }
  function onDoc(e) { if (recOpen && recWrap && !recWrap.contains(e.target)) recOpen = false; }
  const hasFiles = e => [...(e.dataTransfer?.types || [])].includes("Files");
  function record() { recOpen = false; askThenRecord(); }
</script>

<svelte:window onkeydown={onKey}
  ondragenter={e => { if (hasFiles(e)) { e.preventDefault(); dragging++; } }}
  ondragover={e => { if (hasFiles(e)) e.preventDefault(); }}
  ondragleave={e => { if (hasFiles(e)) dragging = Math.max(0, dragging - 1); }}
  ondrop={e => { if (hasFiles(e)) { e.preventDefault(); dragging = 0; importFiles(e.dataTransfer.files); } }} />
<svelte:document onmousedown={onDoc} />

<!-- no accept filter: the macOS desktop picker ignores extensions; the server validates -->
<input type="file" multiple class="hidden" bind:this={fileInput} aria-label={t("meet.import")}
       onchange={e => { importFiles(e.currentTarget.files); e.currentTarget.value = ""; }} />

<Page title={t("nav.meetings")} {sub} record={false} card={false}>
  {#snippet actions()}
    <button class="btn lg outlined" onclick={() => fileInput.click()} disabled={cap.uploading} title="⌘O">
      {#if cap.uploading}<span class="spinner"></span>{:else}<Icon name="upload" size={16} />{/if} {t("meet.import")}</button>
    <span class="rec-wrap" bind:this={recWrap}>
      {#if cap.recording}
        <button class="btn lg rec" onclick={stopRecording}><i class="recdot sq"></i> {t("rec.stop_save")}</button>
      {:else}
        <button class="btn lg rec rmain" onclick={record}><i class="recdot"></i> {t("shell.record")}</button>
        <button class="btn lg rec chev" onclick={() => (recOpen = !recOpen)} aria-expanded={recOpen} aria-haspopup="dialog"
                aria-label={t("meet.rec_options")} title={t("meet.rec_options")}><Icon name="chevd" size={14} /></button>
      {/if}
      {#if recOpen}
        <div class="menu right rec-pop" role="dialog" aria-label={t("meet.rec_options")}>
          <p class="t2">{app.device.desktop ? t("sources.record.desc") : t("sources.record.desc_browser")}</p>
          <div class="field">
            <label class="label" for="rec-mic">{t("rec.mic")}</label>
            <select class="select" id="rec-mic" bind:value={cap.mic}>
              <option value="">{t("rec.mic_default")}</option>
              {#each cap.mics as m (m.id)}<option value={m.id}>{m.name}</option>{/each}
            </select>
          </div>
          <details>
            <summary>{t("sources.options")}</summary>
            <AsrOptions />
          </details>
          <button class="btn lg primary" onclick={record}><i class="recdot"></i> {t("rec.start")}</button>
        </div>
      {/if}
    </span>
  {/snippet}

  <div class="home">
    {#if stages.length}
      <nav class="pipe" aria-label={t("nav.pipeline")}>
        {#each stages as st (st.key)}
          <button class="step" class:next={st.key === nextKey} onclick={() => go(st.path)} title={st.key === nextKey ? next.title : st.text}>
            <span class="pring {st.ring}" style="--p: {st.ring ? st.p : 0}"></span>{st.name} <small>· {st.text}</small>
          </button>
        {/each}
      </nav>
    {/if}

    <div class="meetings" class:solo={!app.sources.length}>
      <section class="card list-card" id="t-list" aria-label={t("nav.meetings")}>
        {#if cap.error}
          <div class="banner danger notice"><Icon name="warn" /><span class="grow">{cap.error}</span>
            <button class="btn sm ghost" onclick={() => (cap.error = "")}>{t("src.dismiss")}</button></div>
        {/if}
        {#if !app.sources.length}
          <div class="scroll grow"><FirstRun onRecord={askThenRecord} onImport={() => fileInput.click()} /></div>
        {:else}
          <div class="list-tools">
            <label class="msearch grow"><Icon name="search" size={16} />
              <input type="search" bind:value={query} placeholder={t("meet.search")} aria-label={t("meet.search")}
                     onkeydown={e => { if (e.key === "Escape") { query = ""; e.currentTarget.blur(); } }} /></label>
            <div class="mseg" role="group" aria-label={t("meet.sort")}>
              {#each ["new", "old", "az"] as k (k)}
                <button class:on={sort === k} aria-pressed={sort === k} onclick={() => (sort = k)}>{t("meet.sort." + k)}</button>
              {/each}
            </div>
          </div>
          <div class="scroll grow rows" role="listbox" aria-label={t("nav.meetings")}>
            {#each rows as m (m.id)}
              {@const st = stateOf(m)}
              {@const who = people(m)}
              <div id="src-{m.id}" class="mrow item" class:on={m.id === selectedId} data-id={m.id} role="option" tabindex="-1"
                   aria-selected={m.id === selectedId} onclick={() => pick(m.id)} ondblclick={() => open(m.id)}
                   onkeydown={e => { if (e.key === "Enter") open(m.id); }}>
                <span class="ic"><Icon name={kindIcon(m)} size={20} /></span>
                <div class="grow">
                  <h3 class="trunc" title={m.title}>{m.title}</h3>
                  <div class="meta"><span class="num">{fmtDate(m.created_at, app.lang)}</span>
                    {#if m.duration}<span>·</span><span class="num">{fmtTime(m.duration)}</span>{/if}
                    {#if who}<span>·</span><span class="trunc who">{who}</span>{/if}
                    <span class="tag">{t("meet.tag." + m.tags)}</span></div>
                </div>
                <div class="right">
                  <span class="tag {st.cls}" title={st.tip || undefined}>{#if st.dot}<i class="live-dot"></i>{/if}{st.text}</span>
                  <span class="num">{m.atoms ? t("meet.reqs_short", { n: m.atoms }) : ""}</span>
                </div>
              </div>
            {:else}
              <div class="empty"><p>{t("meet.none_found", { q: needleQ })}</p></div>
            {/each}
          </div>
        {/if}
      </section>

      {#if selected}
        {@const st = stateOf(selected)}
        {@const who = people(selected)}
        <aside class="card panel" aria-label={selected.title}>
          <div class="panel-head">
            <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
            <h2 contenteditable="true" spellcheck="false" bind:this={titleEl} title={t("meet.title_tip")} aria-label={t("sources.rename")}
                onblur={saveTitle} onkeydown={titleKey}></h2>
            <div class="meta"><span class="num">{fmtDate(selected.created_at, app.lang)}</span>
              {#if selected.duration}<span class="num">{fmtTime(selected.duration)}</span>{/if}
              {#if who}<span>{who}</span>{/if}
              <span>{t("src.atoms_n", { n: selected.atoms || 0 })}</span></div>
          </div>
          <div class="mtabs" role="tablist">
            {#each [["summary", t("meet.tab.summary")], ["transcript", t("nav.transcript")], ["notes", t("meet.tab.notes")], ["atoms", t("nav.atoms")]] as [k, label] (k)}
              <button role="tab" class:on={tab === k} aria-selected={tab === k} onclick={() => (tab = k)}>{label}</button>
            {/each}
          </div>
          <div class="panel-body scroll">
            {#if selected.status === "recording"}
              <div class="empty"><p><span class="tag rec"><i class="live-dot"></i>{t("rec.recording")}</span></p>
                <p class="t3 small">{t("live.panel_hint")}</p></div>
            {:else if selected.status === "processing"}
              <div class="empty"><span class="spinner"></span>
                <p>{st.text}{#if app.jobs[selected.id]?.eta} · {app.jobs[selected.id].eta}{/if}</p>
                <p class="t3 small">{t("meet.keep_working")}</p></div>
            {:else if selected.status === "recorded" || (selected.status === "failed" && selected.audio_file)}
              <div class="empty">
                {#if selected.status === "failed" && selected.error}<div class="banner danger"><Icon name="warn" /><span class="grow">{selected.error}</span></div>{/if}
                <p>{t("meet.raw")}</p>
                <div class="acts">
                  <button class="btn tonal" onclick={() => transcribeSaved(selected.id)}>{t("meet.transcribe")}</button>
                  {#if cur?.audio_files?.length}<button class="btn" onclick={saveMainAudio}><Icon name="download" size={14} /> {t("tr.save_audio")}</button>{/if}
                </div>
              </div>
            {:else if selected.status === "failed"}
              <div class="banner danger"><Icon name="warn" /><span class="grow">{selected.error || t("src.st.failed")}</span></div>
            {:else if tab === "summary"}
              {#if cur}<Recap source={cur} onref={openAt} onchange={reloadDetail} />{/if}
            {:else if tab === "transcript"}
              <div class="find-row">
                <label class="msearch sm grow"><Icon name="search" size={14} />
                  <input type="search" bind:value={find} placeholder={t("meet.find")} aria-label={t("meet.find")} /></label>
                {#if needle}<span class="t3 num">{t("meet.hits", { n: hitCount })}</span>{/if}
              </div>
              {#if cur}
                {#each cur.segments as seg (seg.idx)}
                  {@const m = (marks[seg.idx] || []).filter(a => a.status !== "rejected")}
                  <div class="line">
                    <span class="lt num">{seg.start != null ? fmtTime(seg.start) : ""}</span>
                    <div>
                      {#if seg.speaker}<span class="spk {speakerClass(seg.speaker, speakerOrder)}">{speakerDisplay(seg.speaker, seg.speaker_name, t)}</span>{" "}{/if}<span
                        class="tx">{#each pieces(seg) as p, k (k)}<span class:q={p.q} class:hit={p.h}>{p.t}</span>{/each}</span>
                      {#if m.length}
                        <div class="latoms">{#each m as a, k (a.atom_id + ":" + k)}<button class="latom" title={a.statement}
                            onclick={() => go(`/atoms/atom/${a.atom_id}`)}><span class="type plain {typeClass[a.type]}">{PREFIX[a.type]}</span><span class="trunc">{a.statement}</span></button>{/each}</div>
                      {/if}
                    </div>
                  </div>
                {:else}
                  <div class="empty"><p>{t("tr.no_segments")}</p></div>
                {/each}
              {/if}
            {:else if tab === "notes"}
              {#if cur?.notes?.trim()}
                <div class="md notes-view">{@html renderMarkdown(cur.notes)}</div>
                <p class="hint">{t("nt.panel_foot")} · <button class="link" onclick={() => open(selected.id)}>{t("nt.edit_link")}</button></p>
              {:else if cur}
                <div class="empty"><p>{t("nt.empty")}</p>
                  <button class="btn" onclick={() => open(selected.id)}><Icon name="pencil" size={14} /> {t("nt.write")}</button></div>
              {/if}
            {:else}
              {#each atoms as a (a.id)}
                <button class="req" class:rejected={a.status === "rejected"} onclick={() => go(`/atoms/atom/${a.id}`)}>
                  <span class="type plain {typeClass[a.type]}">{a.rid || PREFIX[a.type]}</span>
                  <span class="st">{a.statement}</span>
                  <span class="t3 small">{t("at.st." + a.status)}</span>
                </button>
              {:else}
                <div class="empty"><p>{t("meet.no_atoms")}</p>
                  {#if !app.extracting[selected.id]}<button class="btn" onclick={() => extractAtoms(selected.id)}>{t("at.extract")}</button>
                  {:else}<p class="t3 small"><span class="spinner"></span> {app.extracting[selected.id].message}</p>{/if}</div>
              {/each}
            {/if}
          </div>
          <div class="panel-foot">
            <button class="btn lg primary" onclick={() => open(selected.id)} disabled={selected.status === "processing" && !selected.duration}>
              {t("meet.open")} <Icon name="arrow" size={14} /></button>
            <button class="btn lg" onclick={() => go(`/atoms/source/${selected.id}`)}>{t("meet.atoms_btn", { n: selected.atoms || 0 })}</button>
            <span class="up"><PopMenu cls="btn lg ghost icon" icon="more" chevron="" ariaLabel={t("tr.more")} title={t("tr.more")} align="right"
                              items={moreItems} onpick={more} /></span>
          </div>
        </aside>
      {/if}
    </div>
  </div>
</Page>

{#if dragging}
  <div class="dropzone"><div><Icon name="upload" size={20} /><h3>{t("src.drop_now")}</h3><p>{t("sources.upload.formats")}</p></div></div>
{/if}

{#if cap.consentAsk}
  <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
  <div class="scrim" onclick={e => e.target === e.currentTarget && (cap.consentAsk = false)} onkeydown={e => e.key === "Escape" && (cap.consentAsk = false)}>
    <div class="sheet" role="dialog" aria-modal="true" aria-labelledby="consent-h">
      <h2 id="consent-h">{t("rec.consent_q")}</h2>
      <p>{t("rec.consent_body")}</p>
      <div class="acts">
        <button class="btn" onclick={() => (cap.consentAsk = false)}>{t("at.cancel")}</button>
        <!-- svelte-ignore a11y_autofocus -->
        <button class="btn primary" autofocus onclick={confirmConsent}>{t("rec.consent_yes")}</button>
      </div>
    </div>
  </div>
{/if}

<style>
  /* prototype-v5 "Meetings" */
  .home { display: flex; flex-direction: column; height: 100%; min-height: 0; }
  .pipe { display: flex; gap: 8px; padding: 0 4px 14px; flex-wrap: wrap; flex: none; }
  .step { display: inline-flex; align-items: center; gap: 10px; height: 44px; padding: 0 16px 0 12px; border: 0; border-radius: 22px;
    background: var(--surface); box-shadow: var(--shadow-1); font: 500 14px/20px var(--font); color: var(--text); cursor: pointer; white-space: nowrap; }
  .step:hover { box-shadow: var(--shadow-2); }
  .step.next { box-shadow: var(--shadow-1), inset 0 0 0 2px var(--primary-c); }
  .step small { color: var(--text-3); font-weight: 400; font-size: 12px; }
  .pring { width: 20px; height: 20px; border-radius: 50%; flex: none; position: relative;
    background: conic-gradient(var(--c, var(--primary)) calc(var(--p) * 1%), var(--surface-3) 0); }
  .pring::after { content: ""; position: absolute; inset: 4px; border-radius: 50%; background: var(--surface); }
  .pring.stale { --c: var(--warn); }
  .pring.done { background: var(--ok); }
  .pring.done::after { inset: 0; background: none; content: "✓"; color: #fff; font-size: 12px; font-weight: 700; display: grid; place-items: center; }

  .meetings { display: grid; grid-template-columns: minmax(0, 1fr) minmax(360px, 34%); gap: 16px; flex: 1; min-height: 0; }
  .meetings.solo { grid-template-columns: minmax(0, 1fr); }
  .card { background: var(--surface); border-radius: var(--r-l); box-shadow: var(--shadow-1); min-width: 0; }
  .list-card { overflow: hidden; }
  .list-card, .panel { display: flex; padding: 0; flex-direction: column; min-height: 0; }
  .notice { margin: 14px 16px 0; }
  .list-tools { display: flex; align-items: center; gap: 10px; padding: 14px 16px; flex: none; }
  .msearch { display: flex; align-items: center; gap: 10px; height: 44px; padding: 0 16px; border-radius: 22px; background: var(--surface-2);
    color: var(--text-2); min-width: 0; }
  .msearch.sm { height: 36px; border-radius: 18px; }
  .msearch input { flex: 1; min-width: 0; border: 0; background: none; outline: none; color: var(--text); font: inherit; box-shadow: none; }
  .msearch:focus-within { box-shadow: 0 0 0 2px var(--primary); }
  .mseg { display: inline-flex; background: var(--surface-2); border-radius: 20px; padding: 3px; gap: 2px; flex: none; }
  .mseg button { height: 32px; padding: 0 14px; border: 0; border-radius: 17px; background: none; font: 500 13px/1 var(--font); color: var(--text-2); cursor: pointer; }
  .mseg button.on { background: var(--surface); color: var(--text); box-shadow: var(--shadow-1); }
  .rows { padding-bottom: 8px; }
  .mrow { display: grid; grid-template-columns: 44px minmax(0, 1fr) auto; gap: 14px; align-items: center; padding: 12px 16px; border-radius: 16px;
    margin: 0 8px; cursor: pointer; transition: background .12s; outline: none; }
  .mrow:hover { background: var(--surface-2); }
  .mrow.on { background: var(--secondary-c); }
  .mrow:focus-visible { box-shadow: inset 0 0 0 2px var(--primary); }
  .ic { width: 44px; height: 44px; border-radius: 14px; background: var(--surface-2); display: grid; place-items: center; color: var(--text-2); }
  .mrow.on .ic { background: var(--surface); }
  .mrow h3 { font-size: 15px; font-weight: 600; line-height: 20px; }
  .meta { color: var(--text-3); font-size: 13px; margin-top: 2px; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; min-width: 0; }
  .who { max-width: 40ch; }
  .right { text-align: right; color: var(--text-3); font-size: 13px; display: grid; gap: 4px; justify-items: end; }
  .tag { display: inline-flex; align-items: center; height: 22px; padding: 0 8px; border-radius: 6px; font-size: 12px; font-weight: 500;
    background: var(--surface-2); color: var(--text-2); white-space: nowrap; }
  .tag.ok { background: var(--ok-c); color: var(--ok); } .tag.warn { background: var(--warn-c); color: var(--warn); }
  .tag.danger { background: var(--danger-c); color: var(--danger); } .tag.prim { background: var(--primary-c); color: var(--on-primary-c); }
  .tag.rec { background: var(--danger-c); color: var(--rec); gap: 6px; }
  .live-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--rec); flex: none; animation: live-pulse 1.6s ease-in-out infinite; }
  @keyframes live-pulse { 50% { opacity: .35; } }

  .panel-head { padding: 18px 20px 8px; flex: none; }
  .panel-head h2 { font-size: 20px; line-height: 26px; font-weight: 600; letter-spacing: -.01em; outline: none; border-radius: 6px; cursor: text; word-break: break-word; }
  .panel-head h2:focus { box-shadow: 0 0 0 2px var(--primary); padding: 0 4px; }
  .panel-head .meta { margin-top: 4px; gap: 10px; }
  .mtabs { display: flex; gap: 2px; border-bottom: 1px solid var(--outline-2); padding: 0 8px; flex: none; overflow-x: auto; }
  .mtabs button { height: 44px; padding: 0 14px; border: 0; background: none; font: 500 14px/1 var(--font); color: var(--text-2); position: relative; cursor: pointer; white-space: nowrap; }
  .mtabs button.on { color: var(--primary); }
  .mtabs button.on::after { content: ""; position: absolute; left: 12px; right: 12px; bottom: 0; height: 3px; border-radius: 3px 3px 0 0; background: var(--primary); }
  .panel-body { flex: 1; min-height: 0; padding: 16px 20px; }
  .panel-foot { display: flex; gap: 8px; padding: 12px 20px 16px; flex-wrap: wrap; align-items: center; flex: none; }
  .panel-foot .up :global(.menu) { top: auto; bottom: calc(100% + 6px); }
  .panel .empty { padding: 40px 12px; }
  .empty .acts { display: flex; gap: 8px; flex-wrap: wrap; justify-content: center; }
  .small { font-size: 12px; }
  .hint { color: var(--text-3); font-size: 12px; margin-top: 14px; display: flex; align-items: center; gap: 4px; flex-wrap: wrap; }
  .link { border: 0; background: none; padding: 0; font: inherit; color: var(--primary); cursor: pointer; }
  .link:hover { text-decoration: underline; }
  .notes-view { line-height: 22px; }
  .find-row { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
  .line { display: grid; grid-template-columns: 52px minmax(0, 1fr); gap: 10px; padding: 8px 0; line-height: 22px; }
  .lt { color: var(--text-3); font-family: var(--mono); font-size: 12px; padding-top: 1px; }
  .spk { font-weight: 600; font-size: 12px; display: inline-flex; align-items: center; gap: 6px; }
  .spk::before { content: ""; width: 8px; height: 8px; border-radius: 50%; background: currentColor; }
  .q { background: var(--mark); border-radius: 3px; padding: 0 2px; }
  .hit { background: var(--primary-c); color: var(--on-primary-c); border-radius: 3px; }
  .latoms { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 4px; }
  .latom { display: inline-flex; gap: 6px; align-items: center; height: 24px; padding: 0 8px 0 4px; border: 0; border-radius: 6px; background: var(--surface-2);
    font-size: 12px; color: var(--text-2); max-width: 100%; cursor: pointer; }
  .latom:hover { background: var(--surface-3); color: var(--text); }
  .req { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; gap: 10px; padding: 10px 0; border: 0; border-bottom: 1px solid var(--outline-2);
    align-items: start; background: none; width: 100%; text-align: left; cursor: pointer; font: inherit; color: inherit; }
  .req:hover .st { color: var(--primary); }
  .req .st { font-size: 14px; line-height: 20px; }
  .req.rejected .st { text-decoration: line-through; color: var(--text-3); }

  .btn.outlined { background: transparent; box-shadow: inset 0 0 0 1px var(--outline); }
  .btn.outlined:hover:not(:disabled) { background: var(--surface-2); }
  .btn.rec { background: var(--rec); color: #fff; box-shadow: none; }
  .btn.rec:hover:not(:disabled) { background: color-mix(in srgb, var(--rec), #000 8%); }
  .btn.rec.rmain { border-radius: 24px 0 0 24px; }
  .btn.rec.chev { border-radius: 0 24px 24px 0; margin-left: 1px; padding: 0 12px; }
  .btn.tonal { background: var(--primary-c); color: var(--on-primary-c); box-shadow: none; }
  .recdot { width: 10px; height: 10px; border-radius: 50%; background: #fff; flex: none; }
  .rec-pop .recdot { background: var(--rec); }
  .recdot.sq { border-radius: 2px; width: 9px; height: 9px; }
  .rec-wrap { position: relative; display: inline-flex; }
  .rec-pop { top: calc(100% + 6px); width: 320px; max-width: none; padding: var(--s-6); display: grid; gap: var(--s-5); grid-template-columns: minmax(0, 1fr); }
  .rec-pop details summary { cursor: pointer; color: var(--c-text-2); font-size: var(--t-foot); }
  .rec-pop details[open] summary { margin-bottom: var(--s-5); }

  .dropzone { position: fixed; inset: 0; z-index: 140; background: color-mix(in srgb, var(--c-accent) 14%, var(--c-scrim)); display: grid; place-items: center;
    pointer-events: none; animation: fade var(--d-fast) var(--ease-out); }
  .dropzone div { background: var(--c-raised); border-radius: var(--r-xl); box-shadow: var(--e-4); padding: var(--s-9) var(--s-10); text-align: center;
    display: grid; justify-items: center; gap: var(--s-3); max-width: 480px; color: var(--c-accent-text); }
  .dropzone h3 { font: var(--w-semibold) var(--t-title-2)/var(--lh-title-2) var(--font-display); color: var(--c-text); }
  .dropzone p { color: var(--c-text-3); font-size: var(--t-foot); }

  /* Below 900 px the panel goes; a double-click (or Enter) opens the meeting. */
  @container ws (max-width: 900px) {
    .meetings { grid-template-columns: minmax(0, 1fr); }
    .panel { display: none; }
  }
  @media (max-width: 760px) {
    .step small { display: none; }
    .list-tools { flex-wrap: wrap; }
    .btn.outlined { display: none; }
  }
</style>
