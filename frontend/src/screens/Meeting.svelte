<script>
  // A meeting (spec 5.0 C3, prototype-v5 pageSession after the recording ended): the header card, then two
  // cards: "Транскрипт" (channel chips, search with a hit counter, the "with requirements" filter, lines with
  // quotes and atom chips, the player) and "Заметки" (Markdown notes that save themselves, then the
  // requirements from this meeting). The inspector keeps Резюме (recap styles) and Участники (rename).
  import { keyOf } from "../lib/keys.js";
  import Icon from "../components/Icon.svelte";
  import Page from "../components/Page.svelte";
  import Panes from "../components/Panes.svelte";
  import PopMenu from "../components/PopMenu.svelte";
  import NotesEditor from "../components/NotesEditor.svelte";
  import Recap from "../components/Recap.svelte";
  import AudioPill from "../components/AudioPill.svelte";
  import { api } from "../lib/api.js";
  import { extractAtoms } from "../lib/atoms.js";
  import { adoptRecording, cap, clock, stopRecording, togglePause, transcribeSaved } from "../lib/capture.svelte.js";
  import { createLive } from "../lib/live.svelte.js";
  import { fmtTime, fmtDate, fmtDuration, speakerClass, speakerDisplay } from "../lib/format.js";
  import { saveText } from "../lib/save.js";
  import { audioLabel, fmtBytes, saveAudio } from "../lib/audio.js";
  import { app, t, go, loadSources, toast, rememberSource, analysisOn, asrModelFor, projectAsrLang } from "../lib/state.svelte.js";

  let { id, autoSummarize = false, focusSeg = null } = $props();

  let source = $state(null);
  let loadError = $state("");
  let audio = $state(null);
  let playing = $state(false);
  let now = $state(0);
  let duration = $state(0);
  let names = $state({});
  let copied = $state(false);
  let titleEl = $state(null);
  let recapText = $state("");

  // Business analysis off (5.0.4): no extraction, requirement chips, quote marks, "with requirements" filter or panel.
  const ba = $derived(analysisOn());
  // Lines that became atoms (FR-TR-03 / PM-17) and in-place corrections (PM-25).
  const marks = $derived(ba ? source?.atom_marks || {} : {});
  let editSeg = $state(null);            // {idx, text}
  async function saveSegment() {
    const e = editSeg;
    editSeg = null;
    try {
      const r = await api(`/api/sources/${id}/segments/${e.idx}`, { method: "PATCH", body: { text: e.text } });
      await load();
      if (r.broken.length && ba) toast(t("tr.quote_broken", { n: r.broken.length }), { kind: "danger", action: t("at.open"),
                                                                                  onAction: () => go(`/atoms/atom/${r.broken[0]}`) });
    } catch (err) { toast(err.message, { kind: "danger" }); }
  }
  let summaryCopied = $state(false);
  async function copySummaryAsEmail() {
    const plain = recapText.replace(/^#+\s*/gm, "").replace(/\*\*(.+?)\*\*/g, "$1").replace(/\[(\d\d:\d\d)[^\]]*\]/g, "($1)");
    await navigator.clipboard.writeText(t("tr.recap_intro", { title: source.title }) + "\n\n" + plain.trim());
    summaryCopied = true;
    setTimeout(() => (summaryCopied = false), 1500);
  }

  async function load() {
    loadError = "";
    try {
      source = await api(`/api/sources/${id}`);
      if (source.kind === "material") { location.replace(`#/library/${id}`); return; }   // a material opens in Материалы
      names = { ...source.speaker_names };
      rememberSource(id);
    } catch (err) {
      source = null;
      loadError = err.message;
    }
  }

  // Reload when the route points at another source; keep polling while it's being processed. While it is being
  // recorded the live poller (lib/live.svelte.js) follows the transcript; once the recorder stops, the source
  // is reloaded until the final transcription has finished.
  $effect(() => {
    const current = id;
    let stop = false;
    load().then(async () => {
      if (focusSeg != null) showSegment(focusSeg);
      while (!stop && source && source.id === current && (source.status === "processing" || source.status === "recording")) {
        await new Promise(r => setTimeout(r, 2000));
        if (!stop && (source?.status !== "recording" || (live && !live.state.recording))) await load();
      }
    });
    return () => { stop = true; };
  });

  // ── live session (5.0 C4.1) ───────────────────────────────────────────────
  const isLive = $derived(source?.status === "recording");
  let live = $state(null);
  let liveBody = $state(null);
  let stick = true;                      // follow the newest line while the reader is at the bottom
  let stopping = $state(false);
  $effect(() => {
    if (!isLive) { live = null; return; }
    const l = createLive(id);
    live = l;
    return l.follow(st => adoptRecording(id, st));      // after a reload: take the recording over
  });
  const liveSt = $derived(live?.state || null);
  const livePaused = $derived(cap.recording && cap.sourceId === id ? cap.paused : !!liveSt?.paused);
  const liveSeconds = $derived(cap.recording && cap.sourceId === id ? cap.elapsed : Math.floor(liveSt?.elapsed || 0));
  const liveChannel = l => (l === "BA" ? "mic" : "sys");
  const liveName = l => (l === "BA" || l === "OTHER" ? t(l === "BA" ? "mt.ch.mic" : "mt.ch.sys") : speakerDisplay(l, null, t));
  // After stop the live lines stay until the full transcript replaces them, and stay as the rough version when the
  // full pass failed or has not run (5.0.5).
  const rough = $derived(source && source.status !== "ready" && !isLive ? source.segments.filter(s => s.provisional) : []);
  function onLiveScroll(e) {
    const el = e.currentTarget;
    stick = el.scrollHeight - el.scrollTop - el.clientHeight < 48;
  }
  $effect(() => {
    liveSt?.segments.length;
    if (stick && liveBody) requestAnimationFrame(() => { if (liveBody) liveBody.scrollTop = liveBody.scrollHeight; });
  });
  async function liveToggle() {
    if (!cap.recording && liveSt) adoptRecording(id, liveSt);
    await togglePause();
    live?.poll();
  }
  // The question card (5.0 C4.3): a question heard in the call with its answer from the materials "в контексте".
  const liveQuestion = $derived(liveSt?.question || null);
  async function questionToNotes() {
    const q = liveQuestion;
    if (!q) return;
    const line = t("q.note", { q: q.text, a: q.answer, src: q.citation?.title || "" });
    try {
      const res = await api(`/api/sources/${id}/notes/append`, { method: "POST", body: { line } });
      if (source) source.notes = res.text;
      toast(t("q.added"));
      live?.dismissQuestion();
    } catch (err) { toast(err.message, { kind: "danger" }); }
  }

  // The recording stopped itself after a long silence (5.0 C4.3): said on the page until the meeting is processed.
  let stoppedBy = $state(null);
  $effect(() => { if (liveSt?.stopped?.reason === "silence") stoppedBy = liveSt.stopped; });
  $effect(() => { id; stoppedBy = null; });
  const silenceStopped = $derived(stoppedBy || (cap.autoStopped?.sourceId === id ? cap.autoStopped : null));

  async function liveStop() {
    if (!cap.recording && liveSt) adoptRecording(id, liveSt);
    stopping = true;
    try { await stopRecording(); } finally { stopping = false; }
    await load();
  }

  const speakerOrder = $derived(source ? [...new Set(source.segments.map(s => s.speaker).filter(Boolean))] : []);
  // Two-channel recordings label the sides, not people: the chips say Микрофон / Собеседники.
  const channels = $derived(speakerOrder.length > 0 && speakerOrder.every(l => l === "BA" || l === "OTHER"));
  const chips = $derived(speakerOrder.map(l => ({ label: l, cls: channels ? (l === "BA" ? "mic" : "sys") : speakerClass(l, speakerOrder),
    text: channels && !(source.speaker_names[l]) ? t(l === "BA" ? "mt.ch.mic" : "mt.ch.sys") : speakerDisplay(l, source.speaker_names[l], t) })));
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
  // A [Name, mm:ss] reference in the recap: the line said at that moment.
  function showTime(seconds) {
    let idx = null;
    for (const seg of source?.segments || []) if (seg.start != null && seg.start <= seconds + 0.5) idx = seg.idx;
    if (idx == null && source?.segments.length) idx = source.segments[0].idx;
    if (idx != null) { only = false; showSegment(idx); }
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

  // The title is edited in place, as in the Встречи panel: blur or Enter saves, Escape puts it back.
  $effect(() => {
    const title = source?.title || "";
    if (titleEl && document.activeElement !== titleEl) titleEl.textContent = title;
  });
  async function saveTitle() {
    if (!source || !titleEl) return;
    const title = (titleEl.textContent || "").replace(/\s+/g, " ").trim();
    if (!title || title === source.title) { titleEl.textContent = source.title; return; }
    try {
      source = { ...source, ...(await api(`/api/sources/${id}`, { method: "PATCH", body: { title } })) };
      loadSources();
      toast(t("meet.renamed"));
    } catch (err) { titleEl.textContent = source.title; toast(err.message, { kind: "danger" }); }
  }
  function titleKey(e) {
    if (e.key === "Enter") { e.preventDefault(); e.currentTarget.blur(); }
    else if (e.key === "Escape") { e.preventDefault(); e.currentTarget.textContent = source?.title || ""; e.currentTarget.blur(); }
  }

  async function renameSpeaker(label) {
    const name = (names[label] || "").trim();
    if ((source.speaker_names[label] || "") === name) return;
    try {
      await api(`/api/sources/${id}/speakers/${encodeURIComponent(label)}`, { method: "PUT", body: { name } });
      await load();
    } catch (err) { toast(err.message, { kind: "danger" }); }
  }

  // Through the shared tracker, so the job shows in the sidebar card and in this screen's banner. The ⋯ menu
  // offers both languages (5.0.7): a recording made with the wrong one is redone here, not from the record panel.
  async function retranscribe(lang = projectAsrLang()) {
    await transcribeSaved(id, asrModelFor(lang));
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

  // View: every line, or only the lines that became requirements. The search highlights and counts its hits;
  // Enter / ⇧Enter step through them.
  let only = $state(false);
  let find = $state("");
  let focusIdx = $state(null);
  let side = $state("summary");          // inspector segment: summary | speakers
  let speed = $state(1);
  let refine = $state(null);             // {note}: extract again, with a one-off instruction
  let hitAt = $state(0);
  const needle = $derived(find.trim().toLowerCase());
  const markedCount = $derived(Object.keys(marks).length);
  const lines = $derived(!source ? [] : source.segments.filter(s => !only || !ba || marks[s.idx]));
  const PREFIX = { functional: "FR", nfr: "NFR", question: "Q", business: "BR", risk: "RSK", current: "AS" };
  const typeClass = { functional: "fr", nfr: "nfr", question: "q", business: "br", risk: "rsk", current: "as" };
  $effect(() => { if (audio) audio.playbackRate = speed; });

  const countIn = (text) => { if (!needle) return 0; const low = text.toLowerCase(); let n = 0, i = -1; while ((i = low.indexOf(needle, i + 1)) >= 0) { n++; i += needle.length - 1; } return n; };
  // Hits before each line, so every hit has its number in the whole transcript.
  const hitBase = $derived.by(() => {
    const base = {};
    let n = 0;
    for (const seg of lines) { base[seg.idx] = n; n += countIn(seg.text); }
    base.total = n;
    return base;
  });
  const hitTotal = $derived(hitBase.total || 0);
  $effect(() => { needle; only; hitAt = 0; });
  function step(dir) {
    if (!hitTotal) return;
    hitAt = (hitAt + dir + hitTotal) % hitTotal;
    requestAnimationFrame(() => document.getElementById(`hit-${hitAt}`)?.scrollIntoView({ block: "center" }));
  }

  // Quotes of the requirements made from a line, marked in its text; search hits on top.
  function quoteParts(seg) {
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
  function pieces(seg) {
    const parts = quoteParts(seg);
    if (!needle) return parts;
    const out = [];
    let n = hitBase[seg.idx] || 0;
    for (const p of parts) {
      const low = p.t.toLowerCase();
      let at = 0, i;
      while ((i = low.indexOf(needle, at)) >= 0) {
        if (i > at) out.push({ t: p.t.slice(at, i), m: p.m });
        out.push({ t: p.t.slice(i, i + needle.length), m: p.m, h: n++ });
        at = i + needle.length;
      }
      if (at < p.t.length) out.push({ t: p.t.slice(at), m: p.m });
    }
    return out;
  }

  // Requirements of this meeting, under the notes.
  let atoms = $state([]);
  $effect(() => {
    const sid = id;
    app.atomsVersion; atomCount; source?.status;
    if (!sid || !app.currentProjectId || !ba) { atoms = []; return; }
    api(`/api/projects/${app.currentProjectId}/atoms?source_id=${sid}`).then(b => { if (sid === id) atoms = b.atoms.filter(a => a.status !== "merged"); }).catch(() => {});
  });
  const quoteOf = a => a.evidence.find(e => e.source_id === id) || null;
  const excerpt = q => (q.length > 90 ? q.slice(0, 88).trimEnd() + "…" : q);

  // Neighbouring sources: ⌥↑ / ⌥↓.
  const ordered = $derived([...app.sources].sort((a, b) => (b.created_at || 0) - (a.created_at || 0)));
  function onKey(e) {
    const key = keyOf(e);
    if (app.route.name !== "transcript" || app.palette) return;
    if (e.altKey && (key === "ArrowUp" || key === "ArrowDown")) {
      const i = ordered.findIndex(s => s.id === id);
      const next = ordered[i + (key === "ArrowDown" ? 1 : -1)];
      if (next) { e.preventDefault(); go(`/meeting/${next.id}`); }
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
    else if (v.startsWith("asr:")) retranscribe(v.slice(4));
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

<Page title={source?.title || ""} crumb={t("nav.meetings")} crumbPath="/meetings" {sub} card={false} headClass="sess-head"
      inspector={source?.status === "ready" ? "source" : ""}>
  {#snippet heading()}
    <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
    <h1 class="screen-title mt-title" contenteditable={source ? "true" : "false"} spellcheck="false" bind:this={titleEl}
        title={t("meet.title_tip")} aria-label={t("tr.edit_title")} onblur={saveTitle} onkeydown={titleKey}></h1>
  {/snippet}
  {#snippet actions()}
    {#if source && isLive}
      <div class="levels" class:still={livePaused} aria-hidden="true"><i></i><i></i><i></i><i></i><i></i></div>
      <span class="timer num" aria-label={t("live.elapsed")}>{clock(liveSeconds)}</span>
      <AudioPill paused={livePaused} busy={stopping} silence={liveSt?.silence || 0} silenceStop={liveSt?.silence_stop || 0}
                 ontoggle={liveToggle} onstop={liveStop} />
    {:else if source}
      {#if source.status !== "ready" && audioItems.length}
        <PopMenu cls="btn ghost" text={t("tr.more")} ariaLabel={t("tr.more")} align="right" onpick={more} items={audioItems} />
      {/if}
      {#if source.status === "ready"}
        <PopMenu cls="btn ghost" text={t("tr.more")} ariaLabel={t("tr.more")} align="right" onpick={more}
                 items={[{ value: "copy", label: copied ? t("tr.copied") : t("tr.copy_text"), icon: "copy" },
                         { value: "txt", label: t("tr.save_txt"), icon: "download" },
                         ...(audioItems.length ? [{ sep: true }, ...audioItems] : []),
                         ...(atomCount && ba ? [{ sep: true }, { value: "extract", label: t("tr.extract_again"), icon: "refresh", disabled: !!app.extracting[id] }] : []),
                         ...(source.audio_url ? [{ sep: true }, ...["ru", "multi"].map(l => ({ value: "asr:" + l, label: `${t("tr.asr_again")} · ${t("mlang." + l)}`, icon: "wave" }))] : [])]} />
        {#if !ba}
          <!-- a meeting recorder: nothing to extract -->
        {:else if app.extracting[id]}
          <button class="btn primary" disabled><span class="spinner"></span> {app.extracting[id].message || t("src.st.extracting")}</button>
        {:else if atomCount}
          <button class="btn primary" onclick={() => go(`/atoms/source/${id}`)}>{t("tr.to_atoms", { n: atomCount })} <Icon name="arrow" size={14} /></button>
        {:else}
          <button class="btn primary" onclick={() => extractAtoms(id)}>{t("at.extract")}</button>
        {/if}
      {:else if source.audio_url && source.status !== "processing"}
        <button class="btn primary" onclick={retranscribe}>{t("tr.transcribe")}</button>
      {/if}
    {/if}
  {/snippet}

  {#if !id}
    <div class="empty"><p>{t("tr.none")}</p>
      <button class="btn" onclick={() => go("/meetings")}>{t("tr.back")}</button></div>
  {:else if loadError}
    <div class="pad"><div class="banner danger"><Icon name="warn" /><span class="grow">{loadError}</span>
      <button class="btn sm" onclick={load}>{t("ov.retry")}</button></div></div>
  {:else if source}
    {#if source.audio_url}
      <audio bind:this={audio} src={source.audio_url} preload="metadata"
             ontimeupdate={() => (now = audio.currentTime)} onloadedmetadata={() => (duration = audio.duration)}
             onplay={() => (playing = true)} onpause={() => (playing = false)}></audio>
    {/if}
    {#if isLive}
      <Panes contentClass="mt-content">
        <div class="sess-body">
          <section class="card col tr-card live-card" aria-label={t("nav.transcript")}>
            <div class="col-head">
              <h2 class="block-title">{t("nav.transcript")}</h2>
              <span class="t3 opt">·</span>
              <span class="chan mic opt"><i></i><span class="trunc">{t("mt.ch.mic")}</span></span>
              <span class="chan sys opt"><i></i><span class="trunc">{t("mt.ch.sys")}</span></span>
            </div>
            <div class="col-body scroll" bind:this={liveBody} onscroll={onLiveScroll}>
              <div class="transcript live-lines">
                {#each liveSt?.segments || [] as seg (seg.idx)}
                  <div class="seg-line line seg-row live-row" class:provisional={seg.provisional} id="seg-{seg.idx}">
                    <span class="time mono">{seg.start != null ? fmtTime(seg.start) : ""}</span>
                    <div class="seg-text"><p>{#if seg.speaker}<span class="spk {liveChannel(seg.speaker)}">{liveName(seg.speaker)}</span>{" "}{/if}{seg.text}</p></div>
                  </div>
                {/each}
                {#if livePaused}
                  <div class="listening paused"><Icon name="pause" size={16} /> {t("live.paused_note")}</div>
                {:else if !liveSt || liveSt.live === "off"}
                  <div class="listening off"><Icon name="clock" size={16} /> {t("live.after_stop")}</div>
                {:else}
                  <div class="listening on"><span class="spinner"></span> {t("live.listening")}{#if liveSt.live === "catching_up"}<span class="t3"> · {t("live.catching_up")}</span>{/if}</div>
                {/if}
              </div>
            </div>
          </section>
          <section class="card col notes-card" aria-label={t("meet.tab.notes")}>
            <NotesEditor sourceId={id} value={source.notes} onsaved={text => { if (source) source.notes = text; }} />
          </section>
          {#if liveQuestion}
            {#key liveQuestion.id}
              <div class="q-card" role="status">
                <h4><Icon name="bolt" size={16} /> {t("q.title")}</h4>
                <p>«{liveQuestion.text}» — {liveQuestion.answer}{#if liveQuestion.citation?.title} <span class="q-src">({liveQuestion.citation.title})</span>{/if}</p>
                <div class="row">
                  <button class="btn filled" onclick={questionToNotes}>{t("q.add")}</button>
                  <button class="btn text" onclick={() => live?.dismissQuestion()}>{t("q.hide")}</button>
                </div>
              </div>
            {/key}
          {/if}
        </div>
      </Panes>
    {:else if source.status !== "ready"}
      <div class="card pad">
        {#if silenceStopped}
          <div class="banner warn stopped-silence"><Icon name="clock" /><span class="grow">{t("live.stopped_silence_n", { n: silenceStopped.minutes })}</span></div>
        {/if}
        {#if source.status === "processing"}
          <div class="banner info"><span class="spinner"></span><span class="grow">
            {app.jobs[id]?.message || t("tr.processing")}{#if app.jobs[id]} · {Math.round(app.jobs[id].progress || 0)}%{#if app.jobs[id].eta} · {app.jobs[id].eta}{/if}{/if}
            · {t("tr.keep_working")}</span></div>
          {#if !rough.length}
            <div class="skeleton">{#each [72, 90, 64, 84, 58, 88, 70] as w, i (i)}<i style="width: {w}%"></i>{/each}</div>
          {/if}
        {:else if source.status === "recorded"}
          <div class="banner warn"><Icon name="clock" /><span class="grow">{t("tr.recorded")}</span></div>
        {:else if source.status === "failed"}
          <div class="banner danger"><Icon name="warn" /><span class="grow">{t("tr.failed", { error: source.error || "" })}</span></div>
        {/if}
        {#if rough.length}
          <p class="rough-note">{t(source.status === "processing" ? "live.kept_processing" : "live.kept_rough")}</p>
          <div class="transcript live-lines rough-lines">
            {#each rough as seg (seg.idx)}
              <div class="seg-line line seg-row live-row provisional" id="seg-{seg.idx}">
                <span class="time mono">{seg.start != null ? fmtTime(seg.start) : ""}</span>
                <div class="seg-text"><p>{#if seg.speaker}<span class="spk {liveChannel(seg.speaker)}">{liveName(seg.speaker)}</span>{" "}{/if}{seg.text}</p></div>
              </div>
            {/each}
          </div>
        {/if}
      </div>
    {:else}
      <Panes screen="source" contentClass="mt-content">
        <div class="sess-body">
          <section class="card col tr-card" aria-label={blockTitle}>
            <div class="col-head">
              <h2 class="block-title">{blockTitle}</h2>
              {#if chips.length && !isText}
                <span class="t3 opt">·</span>
                {#each chips as c (c.label)}<span class="chan {c.cls} opt" title={c.text}><i></i><span class="trunc">{c.text}</span></span>{/each}
              {/if}
              <span class="grow"></span>
              <label class="msearch sm">
                <Icon name="search" size={14} />
                <input id="tr-find" type="search" bind:value={find} placeholder={t("mt.find")} aria-label={t("tr.find")} title={t("mt.find_tip")}
                       onkeydown={e => { if (e.key === "Enter") { e.preventDefault(); step(e.shiftKey ? -1 : 1); }
                                         else if (e.key === "Escape") { find = ""; e.currentTarget.blur(); } }} />
                {#if needle}<span class="hits num" aria-live="polite">{hitTotal ? t("mt.hits", { i: hitAt + 1, n: hitTotal }) : t("mt.no_hits")}</span>
                {:else}<span class="kbd">/</span>{/if}
              </label>
              {#if markedCount}
                <div class="chips" role="group" aria-label={t("tr.view")}>
                  <button class="fchip" class:on={!only} aria-pressed={!only} onclick={() => (only = false)}>{isText ? t("tr.all_paras") : t("tr.all_lines")}</button>
                  <button class="fchip" class:on={only} aria-pressed={only} onclick={() => (only = true)}>{t("mt.with_reqs")}<span class="n">{markedCount}</span></button>
                </div>
              {/if}
              {#if !isText}
                <button class="btn sm ghost icon" disabled={focusIdx == null} title={t("tr.correct_tip")} aria-label={t("tr.correct")}
                        onclick={() => { const s = source.segments.find(x => x.idx === focusIdx); if (s) editSeg = { idx: s.idx, text: s.text }; }}>
                  <Icon name="pencil" size={14} /></button>
              {/if}
            </div>

            <div class="col-body scroll">
              {#if !source.segments.length}
                <div class="empty"><p>{t("tr.no_segments")}</p></div>
              {:else if !lines.length}
                <div class="empty"><p>{t("tr.none_found")}</p>
                  <button class="btn" onclick={() => (only = false)}>{t("at.show_all")}</button></div>
              {:else}
                <div class="transcript" class:text={isText}>
                  {#each lines as seg (seg.idx)}
                    {@const m = marks[seg.idx]}
                    <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
                    <div class="seg-line line" class:seg-row={!isText} class:para={isText} class:playing={seg.idx === activeIdx} class:flash={seg.idx === flashIdx}
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
                          <p>{#if seg.speaker && !isText}<span class="spk {channels ? (seg.speaker === 'BA' ? 'mic' : 'sys') : speakerClass(seg.speaker, speakerOrder)}"
                                title={speakerDisplay(seg.speaker, seg.speaker_name, t)}>{speakerDisplay(seg.speaker, seg.speaker_name, t)}</span>{" "}{/if}{#each pieces(seg) as part, k (k)}{#if part.h != null}<mark
                                class="hit" class:cur={part.h === hitAt} class:q={part.m} id="hit-{part.h}">{part.t}</mark>{:else if part.m}<mark class="q">{part.t}</mark>{:else}{part.t}{/if}{/each}{#if seg.corrected} <span class="badge" title={t("tr.corrected_hint")}>{t("tr.corrected")}</span>{/if}</p>
                          {#if m}
                            <div class="seg-atoms">{#each m as a, k (a.atom_id + ":" + k)}<button class="seg-atom" class:rejected={a.status === "rejected"} title={a.statement}
                                onclick={e => { e.stopPropagation(); go(`/atoms/atom/${a.atom_id}`); }}><span class="type plain {typeClass[a.type]}">{PREFIX[a.type]}</span><span class="trunc">{a.statement}</span></button>{/each}</div>
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
          </section>

          <section class="card col notes-card" aria-label={t("meet.tab.notes")}>
            <NotesEditor sourceId={id} value={source.notes} onsaved={text => { if (source) source.notes = text; }} />
            {#if ba}
            <div class="live-req">
              <div class="col-head">
                <h2>{t("mt.reqs")}</h2><span class="t3 num">{atoms.length || ""}</span><span class="grow"></span>
                {#if atoms.length}<button class="btn sm ghost" onclick={() => go(`/atoms/source/${id}`)}>{t("mt.reqs_all")}</button>{/if}
              </div>
              <div class="scroll req-list">
                {#each atoms as a (a.id)}
                  {@const ev = quoteOf(a)}
                  <button class="req" class:rejected={a.status === "rejected"} onclick={() => go(`/atoms/atom/${a.id}`)}
                          title={t("at.open")}>
                    <span class="type plain {typeClass[a.type]}">{a.rid || PREFIX[a.type]}</span>
                    <span class="req-body"><span class="st">{a.statement}</span>
                      {#if ev?.quote}<span class="qt">{#if ev.start != null}<span class="num">{fmtTime(ev.start)}</span> · {/if}«{excerpt(ev.quote)}»</span>{/if}</span>
                    {#if a.status === "accepted"}<span class="status ok"><Icon name="check" size={12} /></span>{:else}<span></span>{/if}
                  </button>
                {:else}
                  <p class="ctx-none">{app.extracting[id] ? app.extracting[id].message || t("src.st.extracting") : t("src.atoms_none")}</p>
                {/each}
              </div>
            </div>
            {/if}
          </section>
        </div>

        {#snippet inspector()}
          <div class="pane-head">
            <div class="seg" role="tablist">
              <button role="tab" aria-selected={side === "summary"} onclick={() => (side = "summary")}>{t("meet.tab.summary")}</button>
              {#if speakerOrder.length && !isText}
                <button role="tab" aria-selected={side === "speakers"} onclick={() => (side = "speakers")}>{t("tr.speakers")}<span class="n">{speakerOrder.length}</span></button>
              {/if}
            </div>
            <span class="grow"></span>
            {#if side === "summary" && recapText}
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
                <Recap {source} auto={autoSummarize} onref={showTime} onchange={load} bind:shown={recapText} />
              {/if}
            </div>
          </div>
        {/snippet}
      </Panes>
    {/if}
  {/if}
</Page>

{#if refine && ba}
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
  /* prototype-v5 "Session" (.sess-head, .sess-body, .col, .col-head, .col-body, .live-req, .req) and "Meetings" (.line) */
  audio { display: none; }
  .card { background: var(--surface); border-radius: var(--r-l); box-shadow: var(--shadow-1); min-width: 0; }
  .pad { padding: var(--s-6) var(--gutter); display: grid; gap: var(--s-6); }
  .skeleton { display: grid; gap: var(--s-5); max-width: 72ch; }
  .skeleton i { height: 12px; border-radius: var(--r-xs); background: var(--surface-3); animation: breathe 1.6s ease-in-out infinite; }
  @keyframes breathe { 50% { opacity: .45; } }

  :global(.page-head.sess-head) { background: var(--surface); border-radius: var(--r-l); box-shadow: var(--shadow-1); padding: 14px 18px;
    margin-bottom: 14px; align-items: center; }
  .mt-title { font-size: 20px; line-height: 26px; letter-spacing: -.01em; outline: none; border-radius: 6px; cursor: text; padding: 0 2px; }
  .mt-title:focus { box-shadow: 0 0 0 2px var(--primary); padding: 0 4px; white-space: normal; }

  /* The cards sit on the window; the inspector is a third card. */
  :global(.panes:has(> .mt-content)) { gap: 14px; }
  :global(.pane.mt-content) { background: none; overflow-y: auto; }
  :global(.panes:has(> .mt-content) > .pane.inspector) { background: var(--surface); border-radius: var(--r-l); box-shadow: var(--shadow-1);
    border-left: 0; overflow: hidden; }
  .sess-body { display: grid; grid-template-columns: minmax(0, 1.2fr) minmax(320px, 1fr); gap: 14px; height: 100%; min-height: 0; position: relative; }
  /* prototype-v5 .q-card: the dark card bottom-left */
  .q-card { position: absolute; left: 24px; bottom: 24px; width: 380px; max-width: calc(100% - 48px); z-index: 5; background: var(--hud);
    color: var(--hud-text); border-radius: 20px; padding: 16px 18px; box-shadow: var(--shadow-3); animation: qfade .25s; }
  .q-card h4 { font-size: 14px; display: flex; gap: 8px; align-items: center; }
  .q-card p { color: var(--hud-text-2); margin: 8px 0 12px; line-height: 20px; }
  .q-card .row { display: flex; gap: 8px; }
  .q-card .btn { background: var(--hud-2); color: var(--hud-text); height: 34px; border: 0; box-shadow: none; }
  .q-card .btn.filled { background: var(--primary-c); color: var(--on-primary-c); }
  :global(:root[data-theme="dark"]) .q-card .btn.text { color: var(--primary); }
  @keyframes qfade { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
  @media (max-width: 760px) { .q-card { position: fixed; left: 16px; right: 16px; bottom: 16px; width: auto; max-width: none; } }
  .col { display: flex; flex-direction: column; min-height: 0; overflow: hidden; }
  .col-head { display: flex; align-items: center; gap: 10px; padding: 12px 16px; border-bottom: 1px solid var(--outline-2); flex: none; min-width: 0; flex-wrap: wrap; }
  .col-head h2 { font-size: 15px; font-weight: 600; }
  .col-body { flex: 1; min-height: 0; padding: 8px 16px; }

  .chan { display: inline-flex; align-items: center; gap: 6px; font-weight: 600; font-size: 13px; max-width: 18ch; min-width: 0; }
  .chan i { width: 8px; height: 8px; border-radius: 50%; background: currentColor; flex: none; }
  .mic { color: var(--mic); } .sys { color: var(--sys); }
  .msearch { display: flex; align-items: center; gap: 8px; height: 36px; padding: 0 12px; border-radius: 18px; background: var(--surface-2);
    color: var(--text-2); min-width: 120px; max-width: 260px; flex: 0 1 220px; }
  .msearch input { flex: 1; min-width: 0; border: 0; background: none; outline: none; color: var(--text); font: inherit; box-shadow: none; }
  .msearch:focus-within { box-shadow: 0 0 0 2px var(--primary); }
  .msearch .kbd { background: none; }
  .hits { font-size: 12px; color: var(--text-3); white-space: nowrap; }
  .chips { display: inline-flex; gap: 6px; }
  .fchip { display: inline-flex; align-items: center; gap: 6px; height: 28px; padding: 0 10px; border: 0; border-radius: 8px; background: none;
    box-shadow: inset 0 0 0 1px var(--outline); font: 500 13px/1 var(--font); color: var(--text-2); cursor: pointer; white-space: nowrap; }
  .fchip.on { background: var(--secondary-c); box-shadow: none; color: var(--text); }
  .fchip .n { opacity: .7; font-variant-numeric: tabular-nums; }

  .transcript { padding: 4px 0 var(--s-9); }
  .line { display: grid; grid-template-columns: 52px minmax(0, 1fr); gap: 10px; padding: 8px 6px; line-height: 22px; border-radius: 8px;
    position: relative; transition: background var(--d-fast); scroll-margin: 80px 0; }
  .line.para { grid-template-columns: 36px minmax(0, 1fr); }
  .seg-meta { display: contents; }
  .line:hover { background: var(--surface-2); }
  .line.focus { background: var(--surface-3); }
  .line.playing { background: var(--primary-c); }
  .line.playing::before { content: ""; position: absolute; left: 0; top: 6px; bottom: 6px; width: 3px; border-radius: 2px; background: var(--primary); }
  .line.flash { animation: flash 2.4s ease-out; }
  @keyframes flash { 0%, 40% { background: var(--mark); } }
  .time { border: 0; background: none; padding: 3px 0 0; color: var(--text-3); font-family: var(--mono); font-size: 12px; cursor: pointer; text-align: left;
    height: 22px; font-variant-numeric: tabular-nums; align-self: start; }
  .time:hover:not(:disabled) { color: var(--primary); }
  .time:disabled { cursor: default; }
  .spk { font-weight: 600; font-size: 13px; display: inline-flex; align-items: center; gap: 6px; }
  .spk::before { content: ""; width: 8px; height: 8px; border-radius: 50%; background: currentColor; flex: none; }
  .seg-text { min-width: 0; }
  .seg-text p { font: 400 14px/22px var(--font); text-wrap: pretty; }
  .para .seg-text p { font-size: var(--size-read); line-height: var(--lh-read); }
  mark { color: inherit; }
  mark.q { background: var(--mark); border-radius: 3px; padding: 0 2px; }
  mark.hit { background: var(--primary-c); color: var(--on-primary-c); border-radius: 3px; padding: 0; }
  mark.hit.cur { box-shadow: 0 0 0 2px var(--primary); }
  .seg-edit { font: 400 14px/22px var(--font); }
  .seg-text .actions { margin-top: var(--s-3); }
  .seg-atoms { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 4px; }
  .seg-atom { display: inline-flex; align-items: center; gap: 6px; height: 24px; padding: 0 8px 0 4px; border: 0; border-radius: 6px;
    background: var(--surface-2); font-size: 12px; color: var(--text-2); max-width: min(100%, 52ch); cursor: pointer; }
  .seg-atom:hover { background: var(--surface-3); color: var(--text); }
  .seg-atom.rejected .trunc { text-decoration: line-through; color: var(--text-3); }

  .player { display: flex; align-items: center; gap: var(--s-5); height: 52px; padding: 0 16px; border-top: 1px solid var(--outline-2); flex: none; }
  .play { width: 32px; height: 32px; border-radius: 50%; border: 0; background: var(--text); color: var(--surface); display: grid; place-items: center;
    flex: none; cursor: pointer; transition: transform var(--d-instant); }
  .play:active { transform: scale(.94); }
  .scrub { flex: 1; min-width: 80px; appearance: none; -webkit-appearance: none; height: 4px; border-radius: var(--r-full); cursor: pointer;
    background: linear-gradient(90deg, var(--primary) var(--p), var(--surface-4) var(--p)); }
  .scrub::-webkit-slider-thumb { -webkit-appearance: none; width: 12px; height: 12px; border-radius: 50%; background: #fff;
    box-shadow: 0 0 0 0.5px rgba(0,0,0,.2), 0 1px 3px rgba(0,0,0,.3); }
  .up :global(.menu) { top: auto; bottom: calc(100% + 8px); min-width: 120px; }

  .notes-card :global(.notes-editor) { min-height: 120px; }

  /* prototype-v5 "Session" while recording: .levels, .timer, .listening; provisional lines are lighter */
  .levels { display: flex; gap: 3px; align-items: center; height: 24px; flex: none; }
  .levels i { width: 3px; height: 6px; border-radius: 2px; background: var(--primary); animation: lv 1s ease-in-out infinite; }
  .levels i:nth-child(2) { animation-delay: .15s; } .levels i:nth-child(3) { animation-delay: .3s; }
  .levels i:nth-child(4) { animation-delay: .45s; } .levels i:nth-child(5) { animation-delay: .6s; }
  .levels.still i { animation: none; background: var(--outline); }
  @keyframes lv { 0%, 100% { height: 6px; } 50% { height: 22px; } }
  @media (prefers-reduced-motion: reduce) { .levels i { animation: none; height: 12px; } }
  .timer { font: 600 18px/1 var(--mono); color: var(--text-2); letter-spacing: .02em; flex: none; }
  .live-row .time { cursor: default; }
  .live-row.provisional .seg-text p { color: var(--text-2); }
  .rough-note { margin: var(--s-5) 0 0; color: var(--text-3); font-size: 13px; font-style: italic; }
  .rough-lines { max-width: 80ch; }
  .listening { display: flex; gap: 10px; align-items: center; color: var(--text-3); padding: 10px 6px; font-style: italic; }
  .live-req { border-top: 1px solid var(--outline-2); display: flex; flex-direction: column; min-height: 0; max-height: 45%; flex: none; }
  .live-req .col-head { border-bottom: 0; }
  .req-list { padding-bottom: 6px; min-height: 0; }
  .req { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; gap: 10px; padding: 8px 16px; border: 0; background: none; width: 100%;
    text-align: left; align-items: start; cursor: pointer; font: inherit; color: inherit; }
  .req:hover { background: var(--surface-2); }
  .req .type { padding-top: 2px; }
  .req-body { display: grid; min-width: 0; }
  .req .st { font-size: 14px; line-height: 20px; }
  .req .qt { color: var(--text-3); font-size: 12px; margin-top: 3px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .req.rejected .st { text-decoration: line-through; color: var(--text-3); }
  .ctx-none { padding: 12px 16px 16px; color: var(--text-3); }

  .speakers { display: grid; gap: var(--s-5); grid-template-columns: minmax(0, 1fr); }
  .speaker { display: grid; grid-template-columns: minmax(80px, 120px) minmax(0, 1fr); gap: var(--s-4); align-items: center; }

  /* Narrow: the cards stack, the transcript first. */
  @container ws (max-width: 860px) {
    .sess-body { grid-template-columns: minmax(0, 1fr); grid-template-rows: minmax(420px, 1fr) auto; height: auto; }
    .live-req { max-height: none; }
  }
</style>
