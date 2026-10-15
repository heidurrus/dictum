<script>
  // The selected requirement: statement, conflict, evidence in context, properties,
  // history, and the actions with their keys printed on them. Editing happens here.
  import Icon from "./Icon.svelte";
  import PopMenu from "./PopMenu.svelte";
  import { api } from "../lib/api.js";
  import { fmtTime, fmtDate, speakerDisplay } from "../lib/format.js";
  import { app, t, go } from "../lib/state.svelte.js";

  let { atom, code = "", conflicts = [], statementOf = {}, codeOf = {}, editing = false, busy = false, count = 0,
        onDecide, onEdit, onSave, onCancel, onDelete, onResolve, onPatch } = $props();

  const cache = new Map();                // source id → segments
  let context = $state([]);               // [{ev, lines:[{idx, text, speaker, start, hit}]}]
  let history = $state([]);
  let draft = $state("");
  let merging = $state(null);             // conflict id
  let mergeDraft = $state("");

  async function segmentsOf(sourceId) {
    if (!cache.has(sourceId)) cache.set(sourceId, api(`/api/sources/${sourceId}`).then(s => s.segments).catch(() => []));
    return cache.get(sourceId);
  }
  $effect(() => {
    const a = atom;
    if (!a) { context = []; history = []; return; }
    a.status; a.statement; a.type; a.priority;
    Promise.all(a.evidence.map(async ev => {
      const segs = await segmentsOf(ev.source_id);
      const i = segs.findIndex(s => s.idx === ev.segment_idx);
      const lines = i < 0 ? [] : segs.slice(Math.max(0, i - 1), i + 2).map(s => ({ ...s, hit: s.idx === ev.segment_idx }));
      return { ev, lines };
    })).then(c => { if (atom?.id === a.id) context = c; });
    api(`/api/audit?entity=atom&entity_id=${a.id}&limit=20`).then(b => { if (atom?.id === a.id) history = b.entries; }).catch(() => {});
  });
  $effect(() => { if (editing && atom) draft = atom.statement; });
  $effect(() => { atom?.id; merging = null; });

  // Long paragraphs (documents, letters) are cut to the words around the quote; the context pane has the rest.
  const NEAR = 140;
  const cut = (s, n, tail) => (s.length <= n ? s : tail ? "…" + s.slice(-n) : s.slice(0, n) + "…");
  function mark(text, quote) {
    const i = text.toLowerCase().indexOf((quote || "").toLowerCase());
    if (!quote || i < 0) return [{ t: cut(text, NEAR * 2) }];
    return [{ t: cut(text.slice(0, i), NEAR, true) }, { t: text.slice(i, i + quote.length), m: true }, { t: cut(text.slice(i + quote.length), NEAR) }];
  }
  const typeClass = { functional: "fr", nfr: "nfr", question: "q", business: "br", risk: "rsk", current: "as" };
  const TYPES = ["business", "functional", "nfr", "risk", "current", "question"];
  const PRIOS = ["must", "should", "could", "wont"];
  const REASONS = ["not_requirement", "duplicate", "out_of_scope", "wrong", "other"];
  const hText = e => {
    const a = e.after || {};
    const key = "at.h." + e.action;
    const base = t(key) === key ? e.action : t(key);
    if (["accepted", "rejected", "pending"].includes(e.action)) return base + (a.bulk ? " · " + t("at.h.bulk") : "") + (a.reject_reason ? " · " + t("at.reason." + a.reject_reason) : "");
    if (e.action === "edit") return base + (a.statement ? `: «${a.statement}»` : a.priority ? ": " + t("at.prio." + a.priority) : a.type ? ": " + t("at.f." + a.type) : "");
    return base;
  };
  function save() { if (draft.trim()) onSave(atom, draft); }
</script>

{#if !atom}
  <div class="empty insp-empty">
    {#if count > 1}<h3>{t("at.selected", { n: count })}</h3><p>{t("insp.many")}</p>
    {:else}<p>{t("insp.none")}</p>{/if}
  </div>
{:else}
  <div class="pane-head">
    <span class="type idb {typeClass[atom.type]}">{code}</span>
    <span class="t3 trunc grow">{t("at.full." + atom.type)}</span>
    {#if atom.status === "accepted"}<span class="tag-m ok">{t("at.tag.accepted")}</span>
    {:else if atom.status === "rejected"}<span class="tag-m">{t("at.tag.rejected")}</span>
    {:else}<span class="tag-m warn">{t("at.tag.pending")}</span>{/if}
  </div>

  <div class="pane-body scroll">
    <div class="insp-body inspector-body" aria-label={t("at.inspector")}>
      {#if editing}
        <div class="insp-sec">
          <!-- svelte-ignore a11y_autofocus -->
          <textarea class="input edit" rows="4" bind:value={draft} autofocus aria-label={t("at.edit")}
                    onkeydown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); save(); }
                                      if (e.key === "Escape") { e.stopPropagation(); onCancel(); } }}></textarea>
          {#if atom.statement !== atom.original_statement}<p class="hint">{t("at.was", { text: atom.original_statement })}</p>{/if}
          <div class="actions">
            <button class="btn sm primary" disabled={!draft.trim()} onclick={save}>{t("at.save")} <span class="kbd">↵</span></button>
            <button class="btn sm ghost" onclick={onCancel}>{t("at.cancel")} <span class="kbd">esc</span></button>
          </div>
        </div>
      {:else}
        <div class="insp-sec">
          <p class="insp-statement">{atom.statement}</p>
          {#if atom.statement !== atom.original_statement}<p class="hint">{t("at.was", { text: atom.original_statement })}</p>{/if}
        </div>
      {/if}

      {#each conflicts as c (c.id)}
        <div class="conflict" class:waiting={c.status === "awaiting_answer"}>
          <h4 class="cf-head"><Icon name="warn" size={14} /> {t("at.cf.title")}
            {#if c.status === "awaiting_answer"}<span class="badge warn">{t("at.awaiting")}</span>{/if}</h4>
          <p class="cf-desc">{c.description}</p>
          <div class="conflict-sides">
            {#each [["A", c.a], ["B", c.b]] as [side, a] (side)}
              <div class="conflict-side">
                <b>{side}</b>
                <div>
                  <p>{a.statement}</p>
                  {#if a.evidence[0]}
                    <p class="t3 meta">{a.evidence[0].speaker ? speakerDisplay(a.evidence[0].speaker, a.evidence[0].speaker_name, t) + " · " : ""}{a.evidence[0].source_title}{a.evidence[0].start != null ? " · " + fmtTime(a.evidence[0].start) : ""}</p>
                  {/if}
                </div>
              </div>
            {/each}
          </div>
          {#if c.status === "open"}
            {#if merging === c.id}
              <label class="label" for="merge-{c.id}">{t("at.merge_hint")}</label>
              <textarea class="input" id="merge-{c.id}" rows="3" bind:value={mergeDraft}></textarea>
              <div class="conflict-actions">
                <button class="btn sm primary" disabled={busy || !mergeDraft.trim()} onclick={() => onResolve(c, "merge", mergeDraft)}>{t("at.save")}</button>
                <button class="btn sm ghost" onclick={() => (merging = null)}>{t("at.cancel")}</button>
              </div>
            {:else}
              <div class="conflict-actions">
                <button class="btn sm" disabled={busy} onclick={() => onResolve(c, "keep_a")}>{t("at.keep", { side: "A" })}</button>
                <button class="btn sm" disabled={busy} onclick={() => onResolve(c, "keep_b")}>{t("at.keep", { side: "B" })}</button>
                <button class="btn sm" disabled={busy} onclick={() => { merging = c.id; mergeDraft = c.a.statement; }}>{t("at.merge")}</button>
                <button class="btn sm" disabled={busy} onclick={() => onResolve(c, "question")}>{t("at.to_question")}</button>
              </div>
            {/if}
          {/if}
        </div>
      {/each}

      {#if context.length || atom.origin === "ba"}
        <div class="insp-sec">
          <p class="cap">{t("insp.evidence")}</p>
          {#each context as c (c.ev.id)}
            <div class="well evidence">
              <button class="evidence-head" onclick={() => go(c.ev.source_kind === "material" ? `/library/${c.ev.source_id}` : `/source/${c.ev.source_id}/seg/${c.ev.segment_idx}`)} title={t("at.jump")}>
                <Icon name={c.ev.start != null ? "wave" : "file"} size={14} />
                <b class="trunc grow">{c.ev.source_title}</b>
                {#if c.ev.start != null}<span class="mono t3">{fmtTime(c.ev.start)}</span>{/if}
              </button>
              {#each c.lines as l (l.idx)}
                <p class="ev-line" class:hit={l.hit}>
                  <span class="mono t3">{l.hit && l.start != null ? fmtTime(l.start) : "…"}</span>
                  <span>{#if l.speaker}<span class="who">{speakerDisplay(l.speaker, l.speaker_name, t)}.</span> {/if}{#if l.hit}{#each mark(l.text, c.ev.quote) as part, k (k)}{#if part.m}<mark>{part.t}</mark>{:else}{part.t}{/if}{/each}{:else}{cut(l.text, NEAR)}{/if}</span>
                </p>
              {:else}
                <p class="ev-line hit"><span></span><span>«{c.ev.quote}»</span></p>
              {/each}
            </div>
          {/each}
          {#if !context.length && atom.origin === "ba"}<p class="hint">{t("at.ba_origin")}</p>{/if}
        </div>
      {/if}

      <div class="insp-sec">
        <p class="cap">{t("insp.props")}</p>
        <dl class="kv">
          <dt>{t("insp.type")}</dt>
          <dd><PopMenu value={atom.type} items={TYPES.map(v => ({ value: v, label: t("at.full." + v) }))} ariaLabel={t("insp.type")}
                       onpick={v => v !== atom.type && onPatch(atom, { type: v })} /></dd>
          <dt title={t("at.prio_hint")}>{t("at.priority")}</dt>
          <dd><PopMenu value={atom.priority || ""} ariaLabel={t("at.priority")}
                       items={[...PRIOS.map(v => ({ value: v, label: t("at.prio." + v) })), { sep: true }, { value: "", label: t("at.prio.none") }]}
                       onpick={v => onPatch(atom, { priority: v })} /></dd>
          {#if atom.status === "rejected"}
            <dt>{t("at.reason")}</dt>
            <dd><PopMenu value={atom.reject_reason || ""} ariaLabel={t("at.reason")} text={atom.reject_reason ? "" : t("insp.pick")}
                         items={REASONS.map(v => ({ value: v, label: t("at.reason." + v) }))}
                         onpick={v => onPatch(atom, { reject_reason: v })} /></dd>
          {/if}
          {#if atom.type === "question"}
            <dt>{t("oi.questions")}</dt><dd>{t("oi.st." + (atom.q_state || "open"))}{#if atom.answer} · {atom.answer}{/if}</dd>
          {/if}
          {#if atom.evidence[0]?.speaker}
            <dt>{t("insp.speaker")}</dt><dd class="trunc">{speakerDisplay(atom.evidence[0].speaker, atom.evidence[0].speaker_name, t)}</dd>
          {/if}
          <dt>{t("insp.in_docs")}</dt>
          <dd class="t2">{atom.rid ? atom.rid : atom.status === "accepted" ? t("insp.in_docs_next") : t("insp.in_docs_no")}</dd>
          {#if atom.model}<dt>{t("at.model")}</dt><dd class="t2 trunc">{atom.model}</dd>{/if}
        </dl>
      </div>

      <div class="insp-sec del">
        <button class="btn sm ghost danger" onclick={() => onDelete(atom)} title="{t('at.delete')} · Delete">
          <Icon name="trash" size={14} /> {t("at.delete_one")}</button>
      </div>

      {#if history.length}
        <div class="insp-sec hist">
          <p class="cap">{t("at.history")}</p>
          <ol class="timeline">
            {#each history as h, i (i)}<li><time>{fmtDate(h.at, app.lang)}</time><span>{hText(h)}</span></li>{/each}
          </ol>
        </div>
      {/if}
    </div>
  </div>

  <div class="pane-foot">
    <button class="btn" class:primary={atom.status !== "accepted"} onclick={() => onDecide(atom, "accepted")} aria-pressed={atom.status === "accepted"}>
      <Icon name="check" size={14} /> {atom.status === "accepted" ? t("at.accepted_btn") : t("at.accept")} <span class="kbd">A</span></button>
    <button class="btn" onclick={() => onDecide(atom, "rejected")} aria-pressed={atom.status === "rejected"}>
      <Icon name="close" size={14} /> {atom.status === "rejected" ? t("at.rejected_btn") : t("at.reject")} <span class="kbd">X</span></button>
    <button class="btn ghost" onclick={() => onEdit(atom)}><Icon name="pencil" size={14} /> {t("at.edit")} <span class="kbd">E</span></button>
  </div>
{/if}

<style>
  /* 5.0: the inspector card. Statement, conflict cards, evidence wells and the decision bar in tonal surfaces. */
  .pane-head { height: 56px; padding: 0 20px; border-bottom-color: var(--outline-2); }
  .insp-empty { padding-top: 20vh; }
  .del { justify-items: start; order: 9; }
  .pane-foot { padding: 12px 16px; gap: 8px; background: var(--surface); border-top-color: var(--outline-2); }
  .pane-foot .btn { height: 36px; padding: 0 16px; border-radius: 18px; background: var(--surface-2); box-shadow: none; font-weight: 600; }
  .pane-foot .btn:hover:not(:disabled) { background: var(--surface-3); }
  .pane-foot .btn.primary { background: var(--primary); color: var(--on-primary); }
  .pane-foot .btn.primary:hover:not(:disabled) { background: var(--primary); box-shadow: var(--shadow-2); }
  .pane-foot .btn.ghost { background: none; }
  .pane-foot .btn[aria-pressed="true"]:not(.primary) { background: var(--secondary-c); color: var(--on-secondary-c); }
  .insp-empty p { font-size: var(--size-body); color: var(--text-3); }
  .edit { font: var(--w-medium) var(--size-item)/var(--lh-item) var(--font); resize: vertical; border-radius: 12px; }
  .conflict { border-radius: 16px; background: var(--danger-c); padding: 14px 16px; display: grid; gap: var(--s-4); grid-template-columns: minmax(0, 1fr); }
  .conflict.waiting { background: var(--warn-c); }
  .conflict h4 { font-size: 13px; font-weight: 600; color: var(--danger); display: flex; align-items: center; gap: var(--s-3); flex-wrap: wrap; }
  .conflict.waiting h4 { color: var(--warn); }
  .cf-desc { color: var(--text-2); }
  .conflict-sides { display: grid; gap: var(--s-3); }
  .conflict-side { display: grid; grid-template-columns: 20px minmax(0, 1fr); gap: var(--s-3); padding: 10px 12px; border-radius: 12px; background: var(--surface); }
  .conflict-side b { font: 600 var(--size-mono)/var(--lh-body) var(--mono); color: var(--text-3); }
  .conflict-side .meta { font-size: 12px; margin-top: 2px; }
  .conflict-actions { display: flex; gap: var(--s-3); flex-wrap: wrap; }
  .conflict-actions .btn { height: 30px; border-radius: 15px; padding: 0 12px; box-shadow: none; background: var(--surface); }
  .conflict-actions .btn.primary { background: var(--primary); color: var(--on-primary); }
  .conflict-actions .btn.ghost { background: none; }
  .evidence { border-radius: 16px; box-shadow: none; background: var(--surface-2); }
  .evidence + .evidence { margin-top: var(--s-3); }
  .evidence-head { display: flex; align-items: center; gap: var(--s-3); padding: 10px 14px; border: 0; border-bottom: 1px solid var(--outline-2);
    background: none; width: 100%; text-align: left; font-size: 12px; color: var(--text-2); cursor: pointer; }
  .evidence-head:hover { background: var(--surface-3); }
  .evidence-head b { color: var(--text); font-weight: 500; }
  .ev-line { display: grid; grid-template-columns: 44px minmax(0, 1fr); gap: var(--s-4); padding: 6px 14px; color: var(--text-3); }
  .ev-line:last-child { padding-bottom: 10px; }
  .ev-line.hit { color: var(--text); }
  .ev-line .who { font-weight: 500; color: var(--text-2); }
  .kv dd :global(.popbtn) { max-width: 100%; border-radius: 16px; }
</style>
