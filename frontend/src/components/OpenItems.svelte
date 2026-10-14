<script>
  // The client loop (PM-15, PM-19, PM-21, bet 4.2): open questions with their state, conflicts waiting
  // for the client, action items from the calls, and the follow-up email that asks them all.
  import Icon from "./Icon.svelte";
  import { api } from "../lib/api.js";
  import { app, t, go, toast } from "../lib/state.svelte.js";

  let { atoms = [], conflicts = [], onChange } = $props();

  let actions = $state([]);
  let showAnswered = $state(false);
  let answering = $state(null);          // {id, answer, source, resolution, statement}
  let adding = $state(null);             // {text, owner, due}
  let letter = $state(null);             // {text, question_ids}
  let copied = $state(false);

  async function loadActions() {
    try { actions = (await api(`/api/projects/${app.currentProjectId}/actions`)).actions; } catch (_) { actions = []; }
  }
  $effect(() => { app.currentProjectId; app.atomsVersion; loadActions(); });

  const waiting = $derived(Object.fromEntries(conflicts.filter(c => c.question_atom).map(c => [c.question_atom, c])));
  const questions = $derived(atoms.filter(a => a.type === "question" && a.status !== "rejected"));
  const open = $derived(questions.filter(q => q.q_state !== "answered"));
  const answered = $derived(questions.filter(q => q.q_state === "answered"));
  const openActions = $derived(actions.filter(a => a.status === "open"));

  function startAnswer(q) {
    answering = { id: q.id, answer: q.answer || "", source: q.answer_source || "", resolution: "", statement: "" };
  }
  async function saveAnswer() {
    const a = answering;
    try {
      await api(`/api/atoms/${a.id}/answer`, { method: "POST", body: {
        answer: a.answer, source: a.source, resolution: a.resolution || null, statement: a.statement || null } });
      answering = null;
      toast(t("oi.answered"));
      onChange && onChange();
    } catch (err) { toast(err.message, { kind: "danger" }); }
  }
  async function setAsked(q, asked) {
    try { await api(`/api/atoms/${q.id}`, { method: "PATCH", body: { q_state: asked ? "asked" : "open" } }); onChange && onChange(); }
    catch (err) { toast(err.message, { kind: "danger" }); }
  }

  async function toggleAction(a) {
    await api(`/api/actions/${a.id}`, { method: "PATCH", body: { status: a.status === "open" ? "done" : "open" } });
    loadActions();
  }
  async function removeAction(a) {
    await api(`/api/actions/${a.id}`, { method: "DELETE" });
    loadActions();
  }
  async function addAction() {
    const d = adding;
    if (!d.text.trim()) return;
    try {
      actions = (await api(`/api/projects/${app.currentProjectId}/actions`, { method: "POST", body: d })).actions;
      adding = null;
    } catch (err) { toast(err.message, { kind: "danger" }); }
  }

  async function openLetter() {
    try { letter = await api(`/api/projects/${app.currentProjectId}/followup?lang=${app.lang}`); copied = false; }
    catch (err) { toast(err.message, { kind: "danger" }); }
  }
  async function copyLetter() {
    await navigator.clipboard.writeText(letter.text);
    copied = true;
  }
  async function markSent() {
    await api(`/api/projects/${app.currentProjectId}/followup/sent`, { method: "POST", body: { question_ids: letter.question_ids } });
    toast(t("oi.marked", { n: letter.question_ids.length }));
    letter = null;
    onChange && onChange();
  }
  const stateTag = { open: "outline", asked: "warn", answered: "ok" };
</script>

<div class="oi">
  <div class="oi-head">
    <p class="t2">{t("oi.intro")}</p>
    <button class="btn btn-primary" onclick={openLetter} disabled={!open.length && !openActions.length}>
      <Icon name="mail" size={14} /> {t("oi.letter")}</button>
  </div>

  <div class="section-h"><h2>{t("oi.questions")}</h2><span class="t3 num">{open.length}</span></div>
  <section class="card list">
    {#if !open.length}<p class="empty-line">{t("oi.no_questions")}</p>{/if}
    {#each open as q (q.id)}
      {@const conf = waiting[q.id]}
      <div class="qrow">
        <div class="body">
          <p class="stm">{q.statement}</p>
          {#if conf}
            <p class="meta conf"><Icon name="warn" size={12} /> {t("oi.from_conflict")}: «{conf.a?.statement}» {t("oi.or")} «{conf.b?.statement}»</p>
          {:else if q.evidence?.[0]}
            <p class="meta">«{q.evidence[0].quote}» · {q.evidence[0].source_title}</p>
          {/if}
          {#if answering?.id === q.id}
            <div class="answer">
              <label class="label" for="ans-{q.id}">{t("oi.answer")}</label>
              <!-- svelte-ignore a11y_autofocus -->
              <textarea class="input" id="ans-{q.id}" rows="2" bind:value={answering.answer} autofocus></textarea>
              <input class="input" bind:value={answering.source} placeholder={t("oi.answer_source")} aria-label={t("oi.answer_source")} />
              {#if conf}
                <div class="seg" role="group" aria-label={t("oi.resolution")}>
                  <button aria-pressed={answering.resolution === ""} onclick={() => (answering.resolution = "")}>{t("oi.res.none")}</button>
                  <button aria-pressed={answering.resolution === "keep_a"} onclick={() => (answering.resolution = "keep_a")}>{t("at.keep", { side: "A" })}</button>
                  <button aria-pressed={answering.resolution === "keep_b"} onclick={() => (answering.resolution = "keep_b")}>{t("at.keep", { side: "B" })}</button>
                  <button aria-pressed={answering.resolution === "merge"} onclick={() => { answering.resolution = "merge"; answering.statement ||= conf.a?.statement || ""; }}>{t("at.merge")}</button>
                </div>
                {#if answering.resolution === "merge"}
                  <textarea class="input" rows="2" bind:value={answering.statement} aria-label={t("at.merge_hint")}></textarea>
                {/if}
              {/if}
              <div class="actions">
                <button class="btn btn-sm btn-primary" disabled={!answering.answer.trim() || (answering.resolution === "merge" && !answering.statement.trim())}
                        onclick={saveAnswer}>{t("at.save")}</button>
                <button class="btn btn-sm btn-ghost" onclick={() => (answering = null)}>{t("at.cancel")}</button>
              </div>
            </div>
          {/if}
        </div>
        <div class="side">
          <span class="tag {stateTag[q.q_state || 'open']}">{t("oi.st." + (q.q_state || "open"))}</span>
          {#if answering?.id !== q.id}
            {#if q.q_state === "asked"}
              <button class="btn btn-sm btn-ghost" onclick={() => setAsked(q, false)}>{t("oi.not_asked")}</button>
            {:else}
              <button class="btn btn-sm btn-ghost" onclick={() => setAsked(q, true)}>{t("oi.mark_asked")}</button>
            {/if}
            <button class="btn btn-sm" onclick={() => startAnswer(q)}>{t("oi.record_answer")}</button>
          {/if}
        </div>
      </div>
    {/each}
  </section>

  {#if answered.length}
    <button class="btn btn-ghost btn-sm more" onclick={() => (showAnswered = !showAnswered)}>
      <Icon name={showAnswered ? "chevd" : "chevron"} size={14} /> {t("oi.answered_n", { n: answered.length })}</button>
    {#if showAnswered}
      <section class="card list">
        {#each answered as q (q.id)}
          <div class="qrow done">
            <div class="body">
              <p class="stm">{q.statement}</p>
              <p class="ans"><b>{t("oi.answer")}:</b> {q.answer}{#if q.answer_source} <span class="t3">· {q.answer_source}</span>{/if}</p>
            </div>
            <div class="side"><button class="btn btn-sm btn-ghost" onclick={() => startAnswer(q)}>{t("at.edit")}</button></div>
          </div>
        {/each}
      </section>
    {/if}
  {/if}

  <div class="section-h"><h2>{t("oi.actions")}</h2><span class="t3 num">{openActions.length}</span>
    <span class="spacer"></span>
    <button class="btn btn-sm btn-ghost" onclick={() => (adding = { text: "", owner: "", due: "" })}><Icon name="plus" size={14} /> {t("oi.add_action")}</button>
  </div>
  <section class="card list">
    {#if adding}
      <div class="arow add">
        <input class="input grow" bind:value={adding.text} placeholder={t("oi.action_text")} aria-label={t("oi.action_text")}
               onkeydown={e => e.key === "Enter" && addAction()} />
        <input class="input small" bind:value={adding.owner} placeholder={t("oi.owner")} aria-label={t("oi.owner")} />
        <input class="input small" bind:value={adding.due} placeholder={t("oi.due")} aria-label={t("oi.due")} />
        <button class="btn btn-sm btn-primary" onclick={addAction} disabled={!adding.text.trim()}>{t("at.save")}</button>
        <button class="btn btn-sm btn-ghost" onclick={() => (adding = null)}>{t("at.cancel")}</button>
      </div>
    {/if}
    {#if !actions.length && !adding}<p class="empty-line">{t("oi.no_actions")}</p>{/if}
    {#each actions as a (a.id)}
      <div class="arow" class:done={a.status === "done"}>
        <span class="cb-hit"><input type="checkbox" checked={a.status === "done"} onchange={() => toggleAction(a)} aria-label={a.text} /></span>
        <div class="body">
          <p class="stm">{a.text}</p>
          <p class="meta">{a.owner || t("oi.no_owner")}{#if a.due} · {t("oi.due")}: {a.due}{/if}{#if a.source_title} ·
            <button class="link" onclick={() => go(a.segment_idx != null ? `/source/${a.source_id}/seg/${a.segment_idx}` : `/source/${a.source_id}`)}>{a.source_title}</button>{/if}</p>
        </div>
        <span class="row-actions"><button class="btn btn-ghost btn-sm icon-btn" aria-label={t("sources.delete")} title={t("sources.delete")}
                onclick={() => removeAction(a)}><Icon name="trash" size={14} /></button></span>
      </div>
    {/each}
  </section>
</div>

{#if letter}
  <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
  <div class="scrim" onclick={e => e.target === e.currentTarget && (letter = null)} onkeydown={e => e.key === "Escape" && (letter = null)}>
    <div class="sheet wide" role="dialog" aria-modal="true" aria-labelledby="letter-h">
      <h2 id="letter-h">{t("oi.letter")}</h2>
      <p class="t2">{t("oi.letter_hint")}</p>
      <textarea class="input letter" rows="14" bind:value={letter.text} aria-label={t("oi.letter")}></textarea>
      <div class="acts">
        <button class="btn" onclick={() => (letter = null)}>{t("at.cancel")}</button>
        <button class="btn" onclick={copyLetter}><Icon name={copied ? "check" : "copy"} size={14} /> {copied ? t("tr.copied") : t("tr.copy")}</button>
        {#if letter.question_ids.length}
          <button class="btn btn-primary" onclick={markSent}>{t("oi.mark_sent", { n: letter.question_ids.length })}</button>
        {/if}
      </div>
    </div>
  </div>
{/if}

<style>
  .oi-head { display: flex; align-items: center; gap: var(--s-5); flex-wrap: wrap; }
  .oi-head p { flex: 1; min-width: 240px; max-width: 72ch; }
  .spacer { flex: 1; }
  .list { overflow: hidden; }
  .empty-line { padding: var(--s-5) var(--s-6); color: var(--text-3); }
  .qrow, .arow { display: flex; gap: var(--s-5); align-items: flex-start; padding: var(--s-5) var(--s-6); border-bottom: 1px solid var(--outline-2); }
  .qrow:last-child, .arow:last-child { border-bottom: 0; }
  .body { flex: 1; min-width: 0; }
  .stm { font-size: 14px; line-height: 20px; font-weight: 500; }
  .meta { margin-top: 2px; font-size: 12px; color: var(--text-3); }
  .meta.conf { color: var(--danger); display: flex; gap: 4px; align-items: baseline; }
  .side { display: flex; align-items: center; gap: var(--s-3); flex-wrap: wrap; justify-content: flex-end; }
  .answer { display: flex; flex-direction: column; gap: var(--s-4); margin-top: var(--s-4); max-width: 640px; }
  .answer textarea, .letter { height: auto; resize: vertical; }
  .ans { margin-top: 4px; }
  .ans b { font-weight: 600; }
  .qrow.done .stm { color: var(--text-2); }
  .more { margin: var(--s-4) 0 0; }
  .arow { align-items: center; }
  .arow.add { flex-wrap: wrap; }
  .arow .grow { flex: 1 1 260px; }
  .arow .small { width: 150px; }
  .arow.done .stm { color: var(--text-3); text-decoration: line-through; }
  .link { border: 0; background: none; padding: 0; color: var(--primary); cursor: pointer; font: inherit; }
  .sheet.wide { width: min(640px, calc(100vw - 32px)); }
  .letter { width: 100%; margin-top: var(--s-5); font-size: 13px; line-height: 19px; }
</style>
