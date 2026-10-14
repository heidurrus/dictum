<script>
  import { keyOf } from "../lib/keys.js";
  import Icon from "../components/Icon.svelte";
  import Page from "../components/Page.svelte";
  import Panes from "../components/Panes.svelte";
  import PopMenu from "../components/PopMenu.svelte";
  import { explain } from "../lib/errors.js";
  import { api, pollJob } from "../lib/api.js";
  import { extractAtoms } from "../lib/atoms.js";
  import { transcribeSaved } from "../lib/capture.svelte.js";
  import { fmtTime, fmtDate, fmtDuration, renderMarkdown, speakerClass, speakerDisplay } from "../lib/format.js";
  import { saveText } from "../lib/save.js";
  import { audioLabel, fmtBytes, saveAudio } from "../lib/audio.js";
  import { app, t, go, loadSources, toast, rememberSource } from "../lib/state.svelte.js";

  let { id, autoSummarize = false, focusSeg = null } = $props();

  let source = $state(null);
  let loadError = $state("");
  let audio = $state(null);
  let playing = $state(false);
  let now = $state(0);
  let duration = $state(0);

  let summaryText = $state("");
  let summaryMeta = $state("");
  let summaryError = $state(null);          // {message, setup}
  let summarizing = $state(false);
  let summaryStarted = $state(0);
  let tick = $state(0);

  let editingTitle = $state(false);
  let titleDraft = $state("");
  let names = $state({});
  let copied = $state(false);

  // Lines that became atoms (FR-TR-03 / PM-17) and in-place corrections (PM-25).
  const marks = $derived(source?.atom_marks || {});
  let editSeg = $state(null);            // {idx, text}
  async function saveSegment() {
    const e = editSeg;
    editSeg = null;
    try {
      const r = await api(`/api/sources/${id}/segments/${e.idx}`, { method: "PATCH", body: { text: e.text } });
      await load();
      if (r.broken.length) toast(t("tr.quote_broken", { n: r.broken.length }), { kind: "danger", action: t("at.open"),
                                                                                  onAction: () => go(`/atoms/atom/${r.broken[0]}`) });
    } catch (err) { toast(err.message, { kind: "danger" }); }
  }
  let summaryCopied = $state(false);
  async function copySummaryAsEmail() {
    const plain = summaryText.replace(/^#+\s*/gm, "").replace(/\*\*(.+?)\*\*/g, "$1").replace(/\[(\d\d:\d\d)[^\]]*\]/g, "($1)");
    await navigator.clipboard.writeText(t("tr.recap_intro", { title: source.title }) + "\n\n" + plain.trim());
    summaryCopied = true;
    setTimeout(() => (summaryCopied = false), 1500);
  }

  async function load() {
    loadError = "";
    try {
      source = await api(`/api/sources/${id}`);
      names = { ...source.speaker_names };
      summaryText = source.summary?.text || "";
      summaryMeta = source.summary ? t("tr.summarised_with", { model: source.summary.model }) : "";
      rememberSource(id);
    } catch (err) {
      source = null;
      loadError = err.message;
    }
  }

  // Reload when the route points at another source; keep polling while it's being processed.
  $effect(() => {
    const current = id;
    let stop = false;
    load().then(async () => {
      if (autoSummarize && source?.status === "ready" && !summaryText) summarize();
      if (focusSeg != null) showSegment(focusSeg);
      while (!stop && source && source.id === current && source.status === "processing") {
        await new Promise(r => setTimeout(r, 2000));
        if (!stop) await load();
      }
    });
    return () => { stop = true; };
  });

  const speakerOrder = $derived(source ? [...new Set(source.segments.map(s => s.speaker).filter(Boolean))] : []);
  // Documents and emails have no timing: shown as paragraphs, without the time column.
  const isText = $derived(source ? !source.segments.some(s => s.start != null) : false);
  const blockTitle = $derived(source?.kind === "email" ? t("tr.block.email")
    : source?.kind === "document" ? t("tr.block.document") : t("nav.transcript"));
  const email = $derived(source?.meta?.email || null);
  const activeIdx = $derived.by(() => {
    if (!source || !playing && !now) return -1;
    const segs = source.segments;
    for (let i = segs.length - 1; i >= 0; i--) if (segs[i].start != null && segs[i].start <= now + 0.05) return segs[i].idx;
    return -1;
  });

  // Opened from an atom's quote: bring its line into view and mark it briefly.
  let flashIdx = $state(null);
  function showSegment(idx) {
    const seg = source?.segments.find(s => s.idx === idx);
    if (!seg) return;
    flashIdx = idx;
    requestAnimationFrame(() => document.getElementById(`seg-${idx}`)?.scrollIntoView({ block: "center" }));
    if (audio && seg.start != null) audio.currentTime = seg.start;
    setTimeout(() => (flashIdx = null), 2400);
  }

  const atomCount = $derived(app.sources.find(s => s.id === id)?.atom_count || 0);

  function seek(seconds) {
    if (!audio || seconds == null) return;
    audio.currentTime = seconds;
    audio.play();
  }
  function togglePlay() { if (!audio) return; audio.paused ? audio.play() : audio.pause(); }

  $effect(() => {
    // Keep the playing line in view.
    if (activeIdx < 0 || !playing) return;
    document.getElementById(`seg-${activeIdx}`)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  });

  async function saveTitle() {
    editingTitle = false;
    const title = titleDraft.trim();
    if (!title || title === source.title) return;
    try { source = { ...source, ...(await api(`/api/sources/${id}`, { method: "PATCH", body: { title } })) }; loadSources(); }
    catch (err) { toast(err.message, { kind: "danger" }); }
  }

  async function renameSpeaker(label) {
    const name = (names[label] || "").trim();
    if ((source.speaker_names[label] || "") === name) return;
    try {
      await api(`/api/sources/${id}/speakers/${encodeURIComponent(label)}`, { method: "PUT", body: { name } });
      await load();
    } catch (err) { toast(err.message, { kind: "danger" }); }
  }

  async function summarize() {
    summarizing = true;
    summaryError = null;
    summaryText = "";
    summaryStarted = Date.now();
    const timer = setInterval(() => (tick = Math.round((Date.now() - summaryStarted) / 1000)), 500);
    try {
      const { job_id } = await api("/summarize", { method: "POST", body: { source_id: id } });
      const job = await pollJob(job_id, j => { if (j.partial) summaryText = j.partial; }, { interval: 600 });
      summaryText = job.result.summary;
      summaryMeta = t("tr.summarised_with", { model: job.result.model });
      loadSources();
    } catch (err) {
      summaryError = explain(err);
    } finally {
      clearInterval(timer);
      summarizing = false;
    }
  }

  // Through the shared tracker, so the job shows in the sidebar card and in this screen's banner.
  async function retranscribe() {
    await transcribeSaved(id);
    await load();
  }

  async function copyText() {
    await navigator.clipboard.writeText(source.text);
    copied = true;
    setTimeout(() => (copied = false), 1500);
  }

  const meta = $derived(source ? [fmtDate(source.created_at, app.lang), t("kind." + source.kind), fmtDuration(source.duration, app.lang),
    source.speakers && !["email", "document"].includes(source.kind) ? t("meta.speakers", { n: source.speakers }) : null,
    source.asr_model || source.import_format]
    .filter(Boolean).join(" · ") : "");

  // View: every line, or only the lines that became requirements; a search over the text.
  let only = $state(false);
  let find = $state("");
  let focusIdx = $state(null);
  let side = $state("summary");          // inspector segment: summary | speakers
  let speed = $state(1);
  let refine = $state(null);             // {note}: extract again, with a one-off instruction
  const needle = $derived(find.trim().toLowerCase());
  const markedCount = $derived(Object.keys(marks).length);
  const lines = $derived(!source ? [] : source.segments.filter(s =>
    (!only || marks[s.idx]) && (!needle || s.text.toLowerCase().includes(needle))));
  const PREFIX = { functional: "FR", nfr: "NFR", question: "Q", business: "BR", risk: "RSK", current: "AS" };
  const typeClass = { functional: "fr", nfr: "nfr", question: "q", business: "br", risk: "rsk", current: "as" };
  $effect(() => { if (audio) audio.playbackRate = speed; });

  // Quotes of the requirements made from a line, marked in its text.
  function parts(seg) {
    const list = (marks[seg.idx] || []).filter(m => m.status !== "rejected" && m.quote);
    const low = seg.text.toLowerCase();
    const spans = [];
    for (const m of list) {
      const i = low.indexOf(m.quote.toLowerCase());
      if (i >= 0) spans.push([i, i + m.quote.length]);
    }
    if (!spans.length) return [{ t: seg.text }];
    spans.sort((a, b) => a[0] - b[0]);
    const out = [];
    let at = 0;
    for (const [a, b] of spans) {
      if (a < at) continue;
      if (a > at) out.push({ t: seg.text.slice(at, a) });
      out.push({ t: seg.text.slice(a, b), m: true });
      at = b;
    }
    if (at < seg.text.length) out.push({ t: seg.text.slice(at) });
    return out;
  }

  // Requirements of this source, for the context pane.
  let atoms = $state([]);
  $effect(() => {
    const sid = id;
    app.atomsVersion; atomCount;
    if (!sid || !app.currentProjectId) return;
    api(`/api/projects/${app.currentProjectId}/atoms?source_id=${sid}`).then(b => { if (sid === id) atoms = b.atoms.filter(a => a.status !== "merged"); }).catch(() => {});
  });

  // Neighbouring sources: ⌥↑ / ⌥↓.
  const ordered = $derived([...app.sources].sort((a, b) => (b.created_at || 0) - (a.created_at || 0)));
  function onKey(e) {
    const key = keyOf(e);
    if (app.route.name !== "transcript" || app.palette) return;
    if (e.altKey && (key === "ArrowUp" || key === "ArrowDown")) {
      const i = ordered.findIndex(s => s.id === id);
      const next = ordered[i + (key === "ArrowDown" ? 1 : -1)];
      if (next) { e.preventDefault(); go(`/source/${next.id}`); }
      return;
    }
    if (e.target.closest("input, textarea, select, [contenteditable], .menu")) return;
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    if (key === " " && source?.audio_url) { e.preventDefault(); togglePlay(); }
    else if (key === "/") { e.preventDefault(); document.getElementById("tr-find")?.focus(); }
    else if (key === "Escape" && refine) refine = null;
  }
  // One "Save audio…" item per file the source keeps: a recording has both sides mixed plus each channel,
  // an import has the file the user dropped in.
  const audioItems = $derived((source?.audio_files || []).map((f, _, all) =>
    ({ value: "audio:" + f.id, label: audioLabel(f, all.length), icon: "download", hint: fmtBytes(f.size) })));
  function more(v) {
    if (v === "copy") copyText();
    else if (v === "txt") saveText(`${source.title}.txt`, source.text);
    else if (v === "asr") retranscribe();
    else if (v === "extract") refine = { note: "" };
    else if (v.startsWith("audio:")) { const f = source.audio_files.find(x => x.id === v.slice(6)); if (f) saveAudio(source, f); }
  }
  function runRefine() {
    const note = refine.note.trim();
    refine = null;
    extractAtoms(id, note || null);
  }
  const sub = $derived(meta + (email && (email.from || email.to) ? " · " + [email.from ? `${t("tr.email_from")}: ${email.from}` : "", email.to ? `${t("tr.email_to")}: ${email.to}` : ""].filter(Boolean).join(" · ") : ""));
</script>

<svelte:window onkeydown={onKey} />

<Page title={source?.title || ""} crumb={t("sources.title")} crumbPath="/sources" {sub} inspector={source?.status === "ready" ? "source" : ""}>
  {#snippet heading()}
    {#if source && editingTitle}
      <!-- svelte-ignore a11y_autofocus -->
      <input class="input title-input" bind:value={titleDraft} autofocus onblur={saveTitle} aria-label={t("tr.edit_title")}
             onkeydown={e => { if (e.key === "Enter") saveTitle(); if (e.key === "Escape") editingTitle = false; }} />
    {:else}
      <h1 class="screen-title"><button class="tb-crumb" onclick={() => go("/sources")}>{t("sources.title")}</button><span class="tb-crumb">{" › "}</span>{#if source}<button
          class="title-btn" title={t("tr.edit_title")} onclick={() => { editingTitle = true; titleDraft = source.title; }}>{source.title}</button>{/if}</h1>
    {/if}
  {/snippet}
  {#snippet actions()}
    {#if source}
      {#if source.status !== "ready" && audioItems.length}
        <PopMenu cls="btn ghost" text={t("tr.more")} ariaLabel={t("tr.more")} align="right" onpick={more} items={audioItems} />
      {/if}
      {#if source.status === "ready"}
        <PopMenu cls="btn ghost" text={t("tr.more")} ariaLabel={t("tr.more")} align="right" onpick={more}
                 items={[{ value: "copy", label: copied ? t("tr.copied") : t("tr.copy_text"), icon: "copy" },
                         { value: "txt", label: t("tr.save_txt"), icon: "download" },
                         ...(audioItems.length ? [{ sep: true }, ...audioItems] : []),
                         ...(atomCount ? [{ sep: true }, { value: "extract", label: t("tr.extract_again"), icon: "refresh", disabled: !!app.extracting[id] }] : []),
                         ...(source.audio_url ? [{ sep: true }, { value: "asr", label: t("tr.asr_again"), icon: "wave" }] : [])]} />
        <button class="btn" class:primary={!summaryText && !atomCount} onclick={summarize} disabled={summarizing}>
          {#if summarizing}<span class="spinner"></span>{:else}<Icon name="spark" size={14} />{/if}
          {summaryText ? t("tr.resummarize") : t("tr.summarize")}
        </button>
        {#if app.extracting[id]}
          <button class="btn primary" disabled><span class="spinner"></span> {app.extracting[id].message || t("src.st.extracting")}</button>
        {:else if atomCount}
          <button class="btn primary" onclick={() => go(`/atoms/source/${id}`)}>{t("tr.to_atoms", { n: atomCount })} <Icon name="arrow" size={14} /></button>
        {:else}
          <button class="btn" class:primary={!!summaryText} onclick={() => extractAtoms(id)}>{t("at.extract")}</button>
        {/if}
      {:else if source.audio_url && source.status !== "processing"}
        <button class="btn primary" onclick={retranscribe}>{t("tr.transcribe")}</button>
      {/if}
    {/if}
  {/snippet}

  {#if !id}
    <div class="empty"><p>{t("tr.none")}</p>
      <button class="btn" onclick={() => go("/sources")}>{t("tr.back")}</button></div>
  {:else if loadError}
    <div class="pad"><div class="banner danger"><Icon name="warn" /><span class="grow">{loadError}</span>
      <button class="btn sm" onclick={load}>{t("ov.retry")}</button></div></div>
  {:else if source}
    {#if source.audio_url}
      <audio bind:this={audio} src={source.audio_url} preload="metadata"
             ontimeupdate={() => (now = audio.currentTime)} onloadedmetadata={() => (duration = audio.duration)}
             onplay={() => (playing = true)} onpause={() => (playing = false)}></audio>
    {/if}
    {#if source.status !== "ready"}
      <div class="pad">
        {#if source.status === "processing"}
          <div class="banner info"><span class="spinner"></span><span class="grow">
            {app.jobs[id]?.message || t("tr.processing")}{#if app.jobs[id]} · {Math.round(app.jobs[id].progress || 0)}%{#if app.jobs[id].eta} · {app.jobs[id].eta}{/if}{/if}
            · {t("tr.keep_working")}</span></div>
          <div class="skeleton">{#each [72, 90, 64, 84, 58, 88, 70] as w, i (i)}<i style="width: {w}%"></i>{/each}</div>
        {:else if source.status === "recorded"}
          <div class="banner warn"><Icon name="clock" /><span class="grow">{t("tr.recorded")}</span></div>
        {:else if source.status === "failed"}
          <div class="banner danger"><Icon name="warn" /><span class="grow">{t("tr.failed", { error: source.error || "" })}</span></div>
        {/if}
      </div>
    {:else}
      <Panes screen="source">
        <div class="scope">
          <span class="block-title cap">{blockTitle}</span>
          {#if markedCount}
            <div class="seg" role="group" aria-label={t("tr.view")}>
              <button aria-pressed={!only} onclick={() => (only = false)}>{isText ? t("tr.all_paras") : t("tr.all_lines")}</button>
              <button aria-pressed={only} onclick={() => (only = true)}>{t("tr.only_marked")}<span class="n">{markedCount}</span></button>
            </div>
          {/if}
          <span class="t3 num opt">{isText ? t("meta.paragraphs", { n: source.segments.length }) : t("meta.segments", { n: source.segments.length })}</span>
          <span class="grow"></span>
          <label class="search">
            <Icon name="search" size={14} />
            <input id="tr-find" type="search" bind:value={find} placeholder={t("tr.find")} aria-label={t("tr.find")}
                   onkeydown={e => { if (e.key === "Escape") { find = ""; e.currentTarget.blur(); } }} />
            <span class="kbd">/</span>
          </label>
          {#if !isText}
            <button class="btn ghost" disabled={focusIdx == null} title={t("tr.correct_tip")}
                    onclick={() => { const s = source.segments.find(x => x.idx === focusIdx); if (s) editSeg = { idx: s.idx, text: s.text }; }}>
              <Icon name="pencil" size={14} /> {t("tr.correct")}</button>
          {/if}
        </div>

        <div class="pane-body scroll">
          {#if !source.segments.length}
            <div class="empty"><p>{t("tr.no_segments")}</p></div>
          {:else if !lines.length}
            <div class="empty"><p>{t("tr.none_found")}</p>
              <button class="btn" onclick={() => { find = ""; only = false; }}>{t("at.show_all")}</button></div>
          {:else}
            <div class="transcript" class:text={isText}>
              {#each lines as seg (seg.idx)}
                {@const m = marks[seg.idx]}
                <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
                <div class="seg-line" class:seg-row={!isText} class:para={isText} class:playing={seg.idx === activeIdx} class:flash={seg.idx === flashIdx}
                     class:focus={seg.idx === focusIdx} id="seg-{seg.idx}" onclick={() => (focusIdx = seg.idx)}
                     ondblclick={() => !isText && (editSeg = { idx: seg.idx, text: seg.text })}>
                  {#if isText}
                    <span class="time mono t3 num">{seg.idx + 1}</span>
                  {:else}
                    <div class="seg-meta">
                      {#if seg.start != null}
                        <button class="time mono" disabled={!source.audio_url} onclick={e => { e.stopPropagation(); seek(seg.start); }}
                                title={source.audio_url ? t("tr.play_from") : ""}>{fmtTime(seg.start)}</button>
                      {:else}<span></span>{/if}
                      {#if seg.speaker}<span class="spk {speakerClass(seg.speaker, speakerOrder)}" title={speakerDisplay(seg.speaker, seg.speaker_name, t)}><span class="trunc">{speakerDisplay(seg.speaker, seg.speaker_name, t)}</span></span>{:else}<span></span>{/if}
                    </div>
                  {/if}
                  <div class="seg-text">
                    {#if editSeg?.idx === seg.idx}
                      <!-- svelte-ignore a11y_autofocus -->
                      <textarea class="input seg-edit" rows="3" bind:value={editSeg.text} autofocus aria-label={t("tr.correct")}
                                onclick={e => e.stopPropagation()}
                                onkeydown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); saveSegment(); }
                                                  if (e.key === "Escape") editSeg = null; }}></textarea>
                      <div class="actions">
                        <button class="btn sm primary" onclick={saveSegment}>{t("at.save")} <span class="kbd">↵</span></button>
                        <button class="btn sm ghost" onclick={() => (editSeg = null)}>{t("at.cancel")} <span class="kbd">esc</span></button>
                        <span class="hint">{t("tr.correct_note")}</span>
                      </div>
                    {:else}
                      <p>{#each parts(seg) as part, k (k)}{#if part.m}<mark>{part.t}</mark>{:else}{part.t}{/if}{/each}{#if seg.corrected} <span class="badge" title={t("tr.corrected_hint")}>{t("tr.corrected")}</span>{/if}</p>
                      {#if m}
                        <div class="seg-atoms">{#each m as a, k (a.atom_id + ":" + k)}<button class="seg-atom" class:rejected={a.status === "rejected"} title={a.statement}
                            onclick={e => { e.stopPropagation(); go(`/atoms/atom/${a.atom_id}`); }}><span class="type {typeClass[a.type]}">{PREFIX[a.type]}</span><span class="trunc">{a.statement}</span></button>{/each}</div>
                      {/if}
                    {/if}
                  </div>
                </div>
              {/each}
            </div>
          {/if}
        </div>

        {#if source.audio_url}
          <div class="player">
            <button class="play" onclick={togglePlay} aria-label={playing ? t("tr.pause") : t("tr.play")} title="{playing ? t('tr.pause') : t('tr.play')} · Space">
              <Icon name={playing ? "pause" : "play"} /></button>
            <span class="mono num">{fmtTime(now)}</span>
            <input class="scrub" type="range" min="0" max={duration || 0} step="0.1" value={now} style="--p: {duration ? 100 * now / duration : 0}%"
                   oninput={e => { audio.currentTime = Number(e.currentTarget.value); }} aria-label={t("tr.seek")} />
            <span class="mono num t3">{fmtTime(duration)}</span>
            <span class="up"><PopMenu value={speed} ariaLabel={t("tr.speed")} align="right"
                     items={[0.75, 1, 1.25, 1.5, 2].map(v => ({ value: v, label: String(v).replace(".", app.lang === "ru" ? "," : ".") + "×" }))}
                     onpick={v => (speed = v)} /></span>
          </div>
        {/if}

        {#snippet inspector()}
          <div class="pane-head">
            <div class="seg" role="tablist">
              <button role="tab" aria-selected={side === "summary"} onclick={() => (side = "summary")}>{t("tr.summary")}</button>
              {#if speakerOrder.length && !isText}
                <button role="tab" aria-selected={side === "speakers"} onclick={() => (side = "speakers")}>{t("tr.speakers")}<span class="n">{speakerOrder.length}</span></button>
              {/if}
            </div>
            <span class="grow"></span>
            {#if side === "summary" && summaryText && !summarizing}
              <button class="btn sm ghost" onclick={copySummaryAsEmail}>
                <Icon name={summaryCopied ? "check" : "mail"} size={14} /> {summaryCopied ? t("tr.copied") : t("tr.recap")}</button>
            {/if}
          </div>
          <div class="pane-body scroll">
            <div class="insp-body">
              {#if side === "speakers"}
                <p class="hint">{t("tr.speaker_hint")}</p>
                <div class="speakers">
                  {#each speakerOrder as label (label)}
                    <label class="speaker">
                      <span class="spk {speakerClass(label, speakerOrder)}"><span class="trunc">{speakerDisplay(label, null, t)}</span></span>
                      <input class="input" bind:value={names[label]} placeholder={t("tr.speaker_name")}
                             onblur={() => renameSpeaker(label)} onkeydown={e => e.key === "Enter" && e.currentTarget.blur()} />
                    </label>
                  {/each}
                </div>
              {:else}
                {#if summaryError}
                  <div class="banner danger"><Icon name="warn" /><span class="grow">{summaryError.message}</span>
                    {#if summaryError.setup}<button class="btn sm" onclick={() => go("/settings")}>{t("err.open_settings")}</button>{/if}</div>
                {/if}
                {#if summaryText}
                  <div class="md">{@html renderMarkdown(summaryText)}</div>
                  {#if summaryMeta}<p class="hint">{summaryMeta}</p>{/if}
                {:else if summarizing}
                  <p class="hint"><span class="spinner"></span> {t("tr.writing", { s: tick })}</p>
                {:else if !summaryError}
                  <div class="empty small"><p>{t("tr.no_summary")}</p>
                    <button class="btn" onclick={summarize}><Icon name="spark" size={14} /> {t("tr.summarize")}</button></div>
                {/if}
              {/if}
            </div>
          </div>
        {/snippet}

        {#snippet context()}
          <div class="pane-head"><h2 class="grow trunc">{t("tr.ctx")}</h2><span class="t3 num">{atoms.length}</span></div>
          <div class="pane-body scroll">
            {#each atoms as a (a.id)}
              <button class="ctx-row" class:rejected={a.status === "rejected"} onclick={() => a.evidence[0] && showSegment(a.evidence.find(e => e.source_id === id)?.segment_idx)}
                      ondblclick={() => go(`/atoms/atom/${a.id}`)}>
                <span class="type {typeClass[a.type]}">{a.rid || PREFIX[a.type]}</span>
                <span class="grow">{a.statement}</span>
                {#if a.status === "accepted"}<span class="status ok"><Icon name="check" size={12} /></span>{/if}
              </button>
            {:else}
              <p class="ctx-none">{t("src.atoms_none")}</p>
            {/each}
          </div>
        {/snippet}
      </Panes>
    {/if}
  {/if}
</Page>

{#if refine}
  <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
  <div class="scrim" onclick={e => e.target === e.currentTarget && (refine = null)}>
    <div class="sheet" role="dialog" aria-modal="true" aria-labelledby="refine-h">
      <h2 id="refine-h">{t("tr.extract_again_q")}</h2>
      <p>{t("at.reextract_hint")}</p>
      <div class="field">
        <label class="label" for="refine-note">{t("tr.refine_label")}</label>
        <!-- svelte-ignore a11y_autofocus -->
        <textarea class="input" id="refine-note" rows="3" bind:value={refine.note} autofocus placeholder={t("ai.refine_ph.extract")}></textarea>
      </div>
      <div class="acts">
        <button class="btn" onclick={() => (refine = null)}>{t("at.cancel")}</button>
        <button class="btn primary" onclick={runRefine}>{t("tr.extract_again_yes")}</button>
      </div>
    </div>
  </div>
{/if}

<style>
  audio { display: none; }
  .pad { padding: var(--s-6) var(--gutter); display: grid; gap: var(--s-6); }
  .skeleton { display: grid; gap: var(--s-5); max-width: 72ch; }
  .skeleton i { height: 12px; border-radius: var(--r-xs); background: var(--c-fill-2); animation: breathe 1.6s ease-in-out infinite; }
  @keyframes breathe { 50% { opacity: .45; } }
  .title-input { font: var(--w-semibold) var(--t-title-3)/var(--lh-title-3) var(--font-display); width: min(520px, 40vw); height: 24px; }
  .title-btn:hover { color: var(--c-accent-text); }
  .search { width: clamp(160px, 22cqw, 300px); }
  .search .kbd { background: none; }

  .transcript { padding: var(--s-6) 0 var(--s-11); }
  .seg-line { display: grid; grid-template-columns: 52px minmax(80px, 148px) minmax(0, 72ch); gap: var(--s-5); padding: var(--s-4) var(--gutter);
    position: relative; transition: background var(--d-fast); scroll-margin: 80px 0; }
  .seg-line.para { grid-template-columns: 36px minmax(0, 80ch); }
  .seg-meta { display: contents; }
  .seg-line:hover { background: var(--c-fill-1); }
  .seg-line.focus { background: var(--c-fill-2); }
  .seg-line.playing { background: var(--c-accent-tint); }
  .seg-line.playing::before { content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 3px; background: var(--c-accent); }
  .seg-line.flash { animation: flash 2.4s ease-out; }
  @keyframes flash { 0%, 40% { background: var(--c-mark); } }
  .time { border: 0; background: none; padding: 1px 0 0; color: var(--c-text-3); cursor: pointer; text-align: left; height: 22px; font-variant-numeric: tabular-nums; }
  .time:hover:not(:disabled) { color: var(--c-accent-text); }
  .time:disabled { cursor: default; }
  .spk { display: inline-flex; align-items: center; gap: var(--s-3); font-weight: var(--w-medium); height: 22px; min-width: 0; }
  .spk::before { content: ""; width: 6px; height: 6px; border-radius: 50%; background: currentColor; flex: none; }
  .seg-text { min-width: 0; }
  .seg-text p { font: var(--w-regular) var(--t-item)/22px var(--font); text-wrap: pretty; }
  .para .seg-text p { font-size: var(--t-read); line-height: var(--lh-read); }
  .seg-edit { font: var(--w-regular) var(--t-item)/22px var(--font); }
  .seg-text .actions { margin-top: var(--s-3); }
  .seg-atoms { display: flex; flex-wrap: wrap; gap: var(--s-3); margin-top: var(--s-3); }
  .seg-atom { display: inline-flex; align-items: center; gap: var(--s-3); height: 22px; padding: 0 var(--s-4); border: 0; border-radius: var(--r-sm);
    background: var(--c-fill-1); font-size: var(--t-foot); color: var(--c-text-2); max-width: min(100%, 52ch); cursor: pointer; }
  .seg-atom:hover { background: var(--c-fill-3); color: var(--c-text); }
  .seg-atom.rejected .trunc { text-decoration: line-through; color: var(--c-text-3); }
  @container ws (max-width: 1000px) {
    .seg-line.seg-row { grid-template-columns: 52px minmax(0, 1fr); row-gap: 0; }
    .seg-row .spk { grid-column: 2; } .seg-row .seg-text { grid-column: 2; } .seg-row .time { grid-row: 1 / span 2; }
  }

  .player { display: flex; align-items: center; gap: var(--s-5); height: 52px; padding: 0 var(--gutter); border-top: 1px solid var(--c-line);
    background: var(--c-toolbar); -webkit-backdrop-filter: var(--blur-toolbar); backdrop-filter: var(--blur-toolbar); flex: none; }
  .play { width: 32px; height: 32px; border-radius: 50%; border: 0; background: var(--c-text); color: var(--c-content); display: grid; place-items: center;
    flex: none; cursor: pointer; transition: transform var(--d-instant); }
  .play:active { transform: scale(.94); }
  .scrub { flex: 1; min-width: 80px; appearance: none; -webkit-appearance: none; height: 4px; border-radius: var(--r-full); cursor: pointer;
    background: linear-gradient(90deg, var(--c-accent) var(--p), var(--c-fill-3) var(--p)); }
  .scrub::-webkit-slider-thumb { -webkit-appearance: none; width: 12px; height: 12px; border-radius: 50%; background: #fff;
    box-shadow: 0 0 0 0.5px rgba(0,0,0,.2), 0 1px 3px rgba(0,0,0,.3); }
  .up :global(.menu) { top: auto; bottom: calc(100% + 8px); min-width: 120px; }

  .speakers { display: grid; gap: var(--s-5); grid-template-columns: minmax(0, 1fr); }
  .speaker { display: grid; grid-template-columns: minmax(80px, 120px) minmax(0, 1fr); gap: var(--s-4); align-items: center; }
  .empty.small { padding: var(--s-9) 0; }
  .empty.small p { font-size: var(--t-body); }
  .ctx-row { display: grid; grid-template-columns: 60px minmax(0, 1fr) auto; gap: var(--s-4); padding: var(--s-4) var(--s-6); border: 0; background: none; width: 100%;
    text-align: left; border-bottom: 1px solid var(--c-line); cursor: pointer; line-height: 20px; align-items: start; }
  .ctx-row:hover { background: var(--c-fill-1); }
  .ctx-row.rejected .grow { text-decoration: line-through; color: var(--c-text-3); }
  .ctx-none { padding: var(--s-9) var(--s-7); color: var(--c-text-3); text-align: center; }
</style>
