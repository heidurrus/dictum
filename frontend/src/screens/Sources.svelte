<script>
  import { keyOf } from "../lib/keys.js";
  // Sources (redesign §8.2): a table of everything the project was given, a preview of the selected
  // source, and two ways in: record a call or import files (the whole window takes a drop).
  import Icon from "../components/Icon.svelte";
  import Page from "../components/Page.svelte";
  import Panes from "../components/Panes.svelte";
  import FirstRun from "../components/FirstRun.svelte";
  import AsrOptions from "../components/AsrOptions.svelte";
  import { api } from "../lib/api.js";
  import { cap, importFiles, transcribeSaved, loadMics, askThenRecord, confirmConsent, stopRecording } from "../lib/capture.svelte.js";
  import { extractAtoms } from "../lib/atoms.js";
  import { fmtDate, fmtDuration, renderMarkdown } from "../lib/format.js";
  import { saveAudio } from "../lib/audio.js";
  import { app, t, go, loadSources, toast, rememberSource } from "../lib/state.svelte.js";

  let selectedId = $state(null);
  let editingId = $state(null);
  let editTitle = $state("");
  let recOpen = $state(false);
  let recWrap = $state(null);
  let fileInput = $state(null);
  let dragging = $state(0);
  let preview = $state(null);            // the selected source in full (summary)

  $effect(() => { app.device.desktop; loadMics(); });
  $effect(() => { app.currentProjectId; selectedId = null; });
  const rows = $derived([...app.sources].sort((a, b) => (b.created_at || 0) - (a.created_at || 0)));
  const selected = $derived(rows.find(s => s.id === selectedId) || null);
  // The list saves the main file (both sides of a recording, or the imported file); the transcript offers each channel.
  async function saveMainAudio(source) {
    try {
      const { files } = await api(`/api/sources/${source.id}/audio/files`);
      if (files?.length) await saveAudio(source, files[0]);
    } catch (e) { toast(String(e?.message || e), { kind: "danger" }); }
  }
  $effect(() => { if (!selected && rows.length) selectedId = rows[0].id; });
  $effect(() => {
    const id = selectedId;
    const s = selected;
    preview = null;
    if (!id || !s || s.status !== "ready") return;
    s.has_summary;
    api(`/api/sources/${id}`).then(b => { if (selectedId === id) preview = b; }).catch(() => {});
  });

  function open(id) { rememberSource(id); go(`/source/${id}`); }
  function pick(id) {
    selectedId = id;
    const ws = document.querySelector(".workspace");
    if (ws && ws.clientWidth < 900) app.inspectorOverlay = true;
  }
  function startRename(s) { editingId = s.id; editTitle = s.title; }
  async function saveRename(s) {
    const title = editTitle.trim();
    editingId = null;
    if (!title || title === s.title) return;
    try { await api(`/api/sources/${s.id}`, { method: "PATCH", body: { title } }); await loadSources(); }
    catch (err) { toast(err.message, { kind: "danger" }); }
  }
  async function remove(s) {
    await api(`/api/sources/${s.id}`, { method: "DELETE" });
    await loadSources();
    toast(t("sources.deleted", { title: s.title }), {
      action: t("sources.undo"),
      onAction: async () => { await api(`/api/sources/${s.id}/restore`, { method: "POST" }); await loadSources(); },
    });
  }

  const busy = $derived(app.sources.filter(s => s.status === "processing").length);
  const kindIcon = { audio: "wave", video: "wave", recording: "mic", transcript: "transcript", email: "mail", document: "file" };
  const review = $derived(app.status?.atoms?.review || 0);

  function stateOf(s) {
    if (app.extracting[s.id]) return { cls: "accent", spin: true, text: t("src.st.extracting") };
    if (app.jobs[s.id]) return { cls: "accent", spin: true, text: t("src.st.transcribing", { p: Math.round(app.jobs[s.id].progress || 0) }) };
    if (s.status === "processing") return { cls: "accent", spin: true, text: t("src.st.queued") };
    if (s.status === "failed") return { cls: "danger", icon: "warn", text: t("src.st.failed") };
    if (s.status === "recorded") return { cls: "warn", icon: "clock", text: t("src.st.recorded") };
    if (!s.atom_count) return { cls: "", icon: "clock", text: t("src.st.no_atoms") };
    return { cls: "ok", icon: "check", text: t("src.st.ready") };
  }

  function onKey(e) {
    const key = keyOf(e);
    if (app.route.name !== "sources" || app.palette || e.target.closest("input, textarea, select, [contenteditable], .menu")) return;
    if ((e.metaKey || e.ctrlKey) && (key === "o" || key === "O")) { e.preventDefault(); fileInput?.click(); return; }
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const i = rows.findIndex(s => s.id === selectedId);
    if (key === "ArrowDown" || key === "j") { if (rows[i + 1]) selectedId = rows[i + 1].id; }
    else if (key === "ArrowUp" || key === "k") { if (i > 0) selectedId = rows[i - 1].id; }
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
<input type="file" multiple class="hidden" bind:this={fileInput} aria-label={t("src.import")}
       onchange={e => { importFiles(e.currentTarget.files); e.currentTarget.value = ""; }} />

<Page title={t("sources.title")} inspector={rows.length ? "sources" : ""} record={false}
        sub={t("sources.count", { n: app.sources.length }) + (busy ? " · " + t("sources.busy", { busy }) : "")}>
  {#snippet actions()}
    <span class="rec-wrap" bind:this={recWrap}>
      {#if cap.recording}
        <button class="btn" onclick={stopRecording}><i class="recdot sq"></i> {t("rec.stop_save")}</button>
      {:else}
        <button class="btn" onclick={() => (recOpen = !recOpen)} aria-expanded={recOpen} aria-haspopup="dialog">
          <i class="recdot"></i> {t("sources.record.title")}</button>
      {/if}
      {#if recOpen}
        <div class="menu right rec-pop" role="dialog" aria-label={t("sources.record.title")}>
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
    <button class="btn" onclick={() => fileInput.click()} disabled={cap.uploading} title="⌘O">
      {#if cap.uploading}<span class="spinner"></span>{:else}<Icon name="upload" size={14} />{/if} {t("src.import")}</button>
    {#if app.status?.atoms?.total}
      <button class="btn primary" onclick={() => go("/atoms")}>
        {review ? t("src.to_review", { n: review }) : t("src.to_atoms")} <Icon name="arrow" size={14} /></button>
    {/if}
  {/snippet}

  {#if !rows.length}
    <div class="page scroll">
      {#if cap.error}<div class="banner danger top"><Icon name="warn" /><span class="grow">{cap.error}</span></div>{/if}
      <FirstRun onRecord={askThenRecord} onImport={() => fileInput.click()} />
    </div>
  {:else}
    <Panes screen="sources">
      {#if cap.error}<div class="notices"><div class="banner danger"><Icon name="warn" /><span class="grow">{cap.error}</span>
        <button class="btn sm ghost" onclick={() => (cap.error = "")}>{t("src.dismiss")}</button></div></div>{/if}
      <div class="pane-body scroll">
        <table class="table">
          <thead><tr>
            <th>{t("at.source")}</th><th class="c-wide">{t("src.col.people")}</th><th>{t("src.col.date")}</th>
            <th class="c-wide">{t("src.col.size")}</th><th>{t("nav.atoms")}</th><th>{t("at.col.status")}</th>
          </tr></thead>
          <tbody>
            {#each rows as s (s.id)}
              {@const st = stateOf(s)}
              <tr id="src-{s.id}" class="item" aria-selected={s.id === selectedId} onclick={() => pick(s.id)} ondblclick={() => open(s.id)}>
                <td>
                  <div class="name">
                    <span class="kind"><Icon name={kindIcon[s.kind] || "file"} /></span>
                    <div class="grow">
                      {#if editingId === s.id}
                        <!-- svelte-ignore a11y_autofocus -->
                        <input class="input" bind:value={editTitle} autofocus aria-label={t("sources.rename")}
                               onclick={e => e.stopPropagation()}
                               onkeydown={e => { e.stopPropagation(); if (e.key === "Enter") saveRename(s); if (e.key === "Escape") editingId = null; }}
                               onblur={() => saveRename(s)} />
                      {:else}
                        <button class="title-btn trunc" onclick={e => { e.stopPropagation(); open(s.id); }}
                                disabled={s.status === "processing" && !s.duration} title={s.title}>{s.title}</button>
                      {/if}
                      <span class="sub trunc">{t("kind." + s.kind)}{#if s.status === "failed" && s.error} · <span class="err">{s.error}</span>{/if}</span>
                    </div>
                  </div>
                </td>
                <td class="c-wide t2 num">{s.speakers && !["email", "document"].includes(s.kind) ? s.speakers : ""}</td>
                <td class="t2 num nowrap">{fmtDate(s.created_at, app.lang)}</td>
                <td class="c-wide t2 num nowrap">{fmtDuration(s.duration, app.lang) || ""}</td>
                <td class="num">{#if s.atom_count}<button class="link" onclick={e => { e.stopPropagation(); go(`/atoms/source/${s.id}`); }}>{s.atom_count}</button>{:else}<span class="t3">—</span>{/if}</td>
                <td>
                  <span class="status {st.cls}">{#if st.spin}<span class="spinner"></span>{:else}<Icon name={st.icon} size={12} />{/if} {st.text}</span>
                  {#if app.jobs[s.id]}<span class="progress"><i style="width: {app.jobs[s.id].progress}%"></i></span>{/if}
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
        <button class="drop" onclick={() => fileInput.click()}>
          <Icon name="upload" /><span><b>{t("src.drop")}</b> {t("src.drop_d")}</span>
        </button>
      </div>

      {#snippet inspector()}
        {#if selected}
          {@const st = stateOf(selected)}
          <div class="pane-head"><span class="kind sm"><Icon name={kindIcon[selected.kind] || "file"} size={14} /></span>
            <h2 class="trunc grow">{t("kind." + selected.kind)}</h2>
            <span class="status {st.cls}">{st.text}</span></div>
          <div class="pane-body scroll">
            <div class="insp-body">
              <div class="insp-sec">
                <p class="insp-statement">{selected.title}</p>
                <div class="actions">
                  <button class="btn primary" onclick={() => open(selected.id)} disabled={selected.status === "processing" && !selected.duration}>
                    {t("src.open")} <span class="kbd">↵</span></button>
                  {#if selected.status === "recorded" || (selected.status === "failed" && selected.audio_file)}
                    <button class="btn" onclick={() => transcribeSaved(selected.id)}>{t("sources.transcribe_now")}</button>
                  {/if}
                  {#if selected.status === "ready" && !selected.atom_count && !app.extracting[selected.id]}
                    <button class="btn" onclick={() => extractAtoms(selected.id)}>{t("at.extract")}</button>
                  {/if}
                </div>
                {#if app.jobs[selected.id]}
                  <div class="banner info"><span class="spinner"></span>
                    <span class="grow">{app.jobs[selected.id].message || t("src.st.queued")}{#if app.jobs[selected.id].eta} · {app.jobs[selected.id].eta}{/if}</span></div>
                {:else if app.extracting[selected.id]}
                  <div class="banner info"><span class="spinner"></span><span class="grow">{app.extracting[selected.id].message}</span></div>
                {:else if selected.status === "failed" && selected.error}
                  <div class="banner danger"><Icon name="warn" /><span class="grow">{selected.error}</span></div>
                {/if}
              </div>
              <div class="insp-sec">
                <p class="cap">{t("src.facts")}</p>
                <dl class="kv">
                  <dt>{t("src.col.date")}</dt><dd class="num">{fmtDate(selected.created_at, app.lang)}</dd>
                  {#if selected.duration}<dt>{t("src.col.size")}</dt><dd class="num">{fmtDuration(selected.duration, app.lang)}</dd>{/if}
                  {#if selected.speakers && !["email", "document"].includes(selected.kind)}<dt>{t("src.col.people")}</dt><dd class="num">{selected.speakers}</dd>{/if}
                  <dt>{t("nav.atoms")}</dt>
                  <dd>{#if selected.atom_count}<button class="link" onclick={() => go(`/atoms/source/${selected.id}`)}>{t("src.atoms_n", { n: selected.atom_count })}</button>
                      {:else}<span class="t3">{t("src.atoms_none")}</span>{/if}</dd>
                </dl>
              </div>
              {#if preview?.summary?.text}
                <div class="insp-sec">
                  <p class="cap">{t("tr.summary")}</p>
                  <div class="md clamp">{@html renderMarkdown(preview.summary.text)}</div>
                </div>
              {/if}
              <div class="insp-sec manage">
                {#if selected.audio_file}
                  <button class="btn sm ghost" onclick={() => saveMainAudio(selected)}><Icon name="download" size={14} /> {t("tr.save_audio")}</button>
                {/if}
                <button class="btn sm ghost" onclick={() => startRename(selected)}><Icon name="pencil" size={14} /> {t("sources.rename")}</button>
                <button class="btn sm ghost danger" onclick={() => remove(selected)}><Icon name="trash" size={14} /> {t("src.delete")}</button>
              </div>
            </div>
          </div>
        {/if}
      {/snippet}
    </Panes>
  {/if}
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
  .page { height: 100%; }
  .top { margin: var(--s-5) var(--gutter) 0; }
  .notices { padding: var(--s-4) var(--gutter) 0; }
  .recdot { width: 10px; height: 10px; border-radius: 50%; background: var(--c-rec); flex: none; }
  .recdot.sq { border-radius: 2px; width: 9px; height: 9px; }
  .rec-wrap { position: relative; display: inline-flex; }
  .rec-pop { top: calc(100% + 6px); width: 320px; max-width: none; padding: var(--s-6); display: grid; gap: var(--s-5); grid-template-columns: minmax(0, 1fr); }
  .rec-pop details summary { cursor: pointer; color: var(--c-text-2); font-size: var(--t-foot); }
  .rec-pop details[open] summary { margin-bottom: var(--s-5); }

  .table th:first-child, .table td:first-child { padding-left: var(--gutter); }
  .table th:last-child, .table td:last-child { padding-right: var(--gutter); }
  .table tr { cursor: default; }
  .name { display: flex; align-items: center; gap: var(--s-5); min-width: 0; }
  .name .grow { display: grid; min-width: 0; }
  .kind { width: 28px; height: 28px; border-radius: 7px; background: var(--c-fill-2); color: var(--c-text-2); display: grid; place-items: center; flex: none; }
  .kind.sm { width: 22px; height: 22px; border-radius: 6px; }
  .title-btn { border: 0; background: none; padding: 0; font: var(--w-medium) var(--t-item)/var(--lh-item) var(--font); text-align: left; cursor: pointer;
    color: var(--c-text); max-width: 100%; justify-self: start; }
  .title-btn:hover:not(:disabled) { color: var(--c-accent-text); }
  .sub { font-size: var(--t-foot); color: var(--c-text-3); display: block; }
  .sub::first-letter, .pane-head h2::first-letter { text-transform: uppercase; }
  .err { color: var(--c-danger); }
  .nowrap { white-space: nowrap; }
  .link { border: 0; background: none; padding: 0; font: inherit; color: var(--c-accent-text); cursor: pointer; }
  .link:hover { text-decoration: underline; }
  td .progress { display: block; width: 96px; margin-top: var(--s-2); }
  .table td { max-width: 0; }
  .table td:first-child { width: 50%; }
  .drop { margin: var(--s-6) var(--gutter); padding: var(--s-6); border-radius: var(--r-lg); border: 1px dashed var(--c-line-control); display: flex;
    align-items: center; gap: var(--s-5); color: var(--c-text-2); background: none; width: calc(100% - 2 * var(--gutter)); text-align: left; cursor: pointer; }
  .drop:hover { background: var(--c-fill-1); }
  .drop b { color: var(--c-text); font-weight: var(--w-medium); }
  .clamp { max-height: 340px; overflow: hidden; -webkit-mask: linear-gradient(#000 80%, transparent); mask: linear-gradient(#000 80%, transparent); }
  .manage { display: flex; gap: var(--s-3); flex-wrap: wrap; }
  .dropzone { position: fixed; inset: 0; z-index: 140; background: color-mix(in srgb, var(--c-accent) 14%, var(--c-scrim)); display: grid; place-items: center;
    pointer-events: none; animation: fade var(--d-fast) var(--ease-out); }
  .dropzone div { background: var(--c-raised); border-radius: var(--r-xl); box-shadow: var(--e-4); padding: var(--s-9) var(--s-10); text-align: center;
    display: grid; justify-items: center; gap: var(--s-3); max-width: 480px; color: var(--c-accent-text); }
  .dropzone h3 { font: var(--w-semibold) var(--t-title-2)/var(--lh-title-2) var(--font-display); color: var(--c-text); }
  .dropzone p { color: var(--c-text-3); font-size: var(--t-foot); }
</style>
