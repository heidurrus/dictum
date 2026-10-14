<script>
  // Спросить (spec 5.0 C6, prototype-v5 pageAsk): the chat card (questions, answers with a status line and citation
  // chips where the model put its [Источник N] markers, "Создано Q-n" when an answer made a question for the client),
  // the composer with the "в контексте" switch and the privacy line, and the history column by day.
  import Icon from "../components/Icon.svelte";
  import Page from "../components/Page.svelte";
  import { api, pollJob } from "../lib/api.js";
  import { fmtTime } from "../lib/format.js";
  import { app, t, go, currentProject, writePref } from "../lib/state.svelte.js";

  const PREF = "askContextOnly";
  function readCtx() {
    try { const v = localStorage.getItem("wb." + PREF); return v === null ? true : JSON.parse(v) !== false; }
    catch (_) { return true; }
  }

  let question = $state("");
  let contextOnly = $state(readCtx());
  let history = $state([]);
  let searchable = $state(true);
  let loaded = $state(false);
  let chat = $state([]);                 // [{key, question, running, stage, partial, error, needsSetup, ...answer}]
  let input = $state(null);
  let msgs = $state(null);
  let flash = $state(null);

  const project = $derived(currentProject());
  const local = $derived(!!project?.local_only || app.settings?.llm_provider === "local");
  const busy = $derived(chat.some(m => m.running));

  async function loadHistory() {
    const pid = app.currentProjectId;
    if (!pid) return;
    try {
      const body = await api(`/api/projects/${pid}/ask/history?limit=50`);
      if (pid !== app.currentProjectId) return;
      history = body.items;
      searchable = body.searchable;
    } catch (_) { /* the history is optional */ }
    loaded = true;
  }
  $effect(() => { app.currentProjectId; loadHistory(); });

  function setContext(on) {
    contextOnly = on;
    writePref(PREF, on);
  }

  function scrollDown() {
    requestAnimationFrame(() => { if (msgs) msgs.scrollTop = msgs.scrollHeight; });
  }

  async function send() {
    const q = question.trim();
    if (!q || busy) return;
    question = "";
    const key = "m" + Date.now();
    chat = [...chat, { key, question: q, running: true, stage: "search", partial: "" }];
    scrollDown();
    const patch = changes => { chat = chat.map(m => (m.key === key ? { ...m, ...changes } : m)); };
    try {
      const { job } = await api(`/api/projects/${app.currentProjectId}/ask`, { method: "POST", body: { question: q, context_only: contextOnly } });
      const done = await pollJob(job, j => {
        patch({ stage: (j.progress || 0) >= 40 || j.partial ? "generate" : "search", partial: j.partial || "" });
        scrollDown();
      }, { interval: 400 });
      patch({ ...done.result, running: false });
      history = [{ ...done.result }, ...history.filter(h => h.id !== done.result.id)];
      searchable = true;
    } catch (err) {
      patch({ running: false, error: err.message, needsSetup: !!err.body?.needs_setup });
    }
    scrollDown();
  }

  function onKey(e) {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); }
  }

  // ⌘J (the hotkeys map's "ask") lands here and puts the cursor in the composer.
  $effect(() => {
    if (input) input.focus();
    const focus = () => input?.focus();
    window.addEventListener("dictum:ask-focus", focus);
    return () => window.removeEventListener("dictum:ask-focus", focus);
  });

  function reshow(h) {
    const at = chat.find(m => m.id === h.id);
    if (!at) chat = [{ ...h, key: "h" + h.id, running: false }];
    flash = h.id;
    setTimeout(() => { if (flash === h.id) flash = null; }, 1600);
    requestAnimationFrame(() => document.getElementById("ans-" + h.id)?.scrollIntoView({ block: "nearest" }));
  }

  async function remove(h) {
    try {
      await api(`/api/ask/${h.id}`, { method: "DELETE" });
      history = history.filter(x => x.id !== h.id);
      chat = chat.filter(m => m.id !== h.id);
    } catch (_) { /* already gone */ }
  }

  // ── an answer as text and chips ────────────────────────────────────────────
  const MARKER = /\[\s*(?:Источник|Источники|Source|Sources)\s+(\d+(?:\s*(?:,|и|and)\s*\d+)*)\s*\]/gi;
  function parts(text, citations) {
    const byN = Object.fromEntries((citations || []).map(c => [c.n, c]));
    const out = [];
    let last = 0;
    for (const m of (text || "").matchAll(MARKER)) {
      if (m.index > last) out.push(...bold(text.slice(last, m.index)));
      for (const n of m[1].match(/\d+/g)) if (byN[n]) out.push({ cite: byN[n] });
      last = m.index + m[0].length;
    }
    if (last < (text || "").length) out.push(...bold(text.slice(last)));
    return out;
  }
  function bold(s) {
    return s.split(/\*\*(.+?)\*\*/g).map((x, i) => ({ text: x, b: i % 2 === 1 })).filter(p => p.text);
  }
  const plainPartial = s => (s || "").replace(MARKER, "");

  function chip(c) {
    if (c.entity === "segment") return c.start != null ? `${t("ask.cite_meeting")} · ${fmtTime(c.start)}` : t("ask.cite_meeting");
    return c.title;
  }
  function open(c) {
    if (c.entity === "segment") go(`/meeting/${c.entity_id}/seg/${c.locator}`);
    else if (c.entity === "atom") go(`/atoms/atom/${c.entity_id}`);
    else go(`/library/${c.entity_id}`);
  }

  function seconds(s) {
    return t("ask.seconds", { s: Number(s || 0).toLocaleString(app.lang === "en" ? "en-US" : "ru-RU", { minimumFractionDigits: 1, maximumFractionDigits: 1 }) });
  }
  function statusLine(m) {
    const found = m.sources_used ? (m.sources_used === 1 ? t("ask.found_one") : t("ask.found_n", { n: m.sources_used })) : t("ask.found_none");
    return [found, m.model, seconds(m.elapsed), m.indexed === false ? t("ask.keywords_only") : ""].filter(Boolean).join(" · ");
  }

  // ── the history by day ─────────────────────────────────────────────────────
  const groups = $derived.by(() => {
    const start = new Date(); start.setHours(0, 0, 0, 0);
    const today = start.getTime() / 1000, yesterday = today - 86400;
    const out = [{ key: "today", items: [] }, { key: "yesterday", items: [] }, { key: "earlier", items: [] }];
    for (const h of history) out[h.created_at >= today ? 0 : h.created_at >= yesterday ? 1 : 2].items.push(h);
    return out.filter(g => g.items.length);
  });
  const empty = $derived(loaded && !searchable && !history.length);
</script>

<Page title={t("nav.ask")} sub={local ? t("ask.sub_local") : t("ask.sub_cloud")} card={false}>
  <div class="ask">
    <section class="card chat" aria-label={t("nav.ask")}>
      <div class="msgs scroll" bind:this={msgs} aria-live="polite">
        {#if empty}
          <div class="empty">
            <span class="glyph" aria-hidden="true"><Icon name="search" size={24} /></span>
            <h3>{t("ask.empty_title")}</h3>
            <p>{t("ask.empty_text")}</p>
            <button class="btn" onclick={() => go("/library")}>{t("ask.empty_action")}</button>
          </div>
        {:else if !chat.length}
          <p class="hint t3">{t("ask.hint")}</p>
        {/if}
        {#each chat as m (m.key)}
          <div class="msg me">{m.question}</div>
          <div class="msg ai" class:flash={flash && flash === m.id} id={m.id ? "ans-" + m.id : null}>
            {#if m.running}
              <div class="st"><span class="spinner"></span> {m.stage === "generate" ? t("ask.generating") : t("ask.searching")}</div>
              {#if m.partial}<div class="text">{plainPartial(m.partial)}</div>{/if}
            {:else if m.error}
              <div class="st err"><Icon name="warn" size={14} /> {m.error}</div>
              {#if m.needsSetup}<button class="btn sm" onclick={() => go("/settings")}>{t("ask.open_settings")}</button>{/if}
            {:else}
              <div class="st"><Icon name="check" size={14} /> {statusLine(m)}</div>
              <div class="text">{#each parts(m.answer, m.citations) as p, i (i)}{#if p.cite}<button class="cite" title={t("ask.cite_open", { title: p.cite.title })}
                  onclick={() => open(p.cite)}>{chip(p.cite)}</button>{:else if p.b}<b>{p.text}</b>{:else}{p.text}{/if}{/each}</div>
              {#if m.created}
                <div class="created"><Icon name="check" size={14} /> {t("ask.created")}
                  <button class="cite" onclick={() => go(`/atoms/atom/${m.created.atom_id}`)}>{m.created.label}</button>
                  <span class="t2">«{m.created.statement}»</span></div>
              {/if}
            {/if}
          </div>
        {/each}
      </div>
      <div class="composer">
        <div class="box">
          <input bind:this={input} bind:value={question} placeholder={t("ask.placeholder")} aria-label={t("ask.placeholder")}
                 onkeydown={onKey} disabled={empty} />
          <button class="send" onclick={send} disabled={!question.trim() || busy || empty} aria-label={t("ask.send")} title={t("ask.send")}>
            <Icon name="arrow" size={20} /></button>
        </div>
        <div class="opts">
          <label class="ctx"><input type="checkbox" class="switch" checked={contextOnly} onchange={e => setContext(e.currentTarget.checked)} />
            <span>{t("ask.ctx_only")}</span></label>
          <span class="t3 opt">·</span>
          <span class="t3 opt privacy">{local ? t("ask.privacy_local") : t("ask.privacy_cloud")}</span>
        </div>
      </div>
    </section>
    <section class="card hist scroll" aria-label={t("ask.history")}>
      <h4>{t("ask.history")}</h4>
      {#each groups as g (g.key)}
        <p class="day">{t("ask." + g.key)}</p>
        {#each g.items as h (h.id)}
          <div class="h">
            <button class="hq" onclick={() => reshow(h)}>{h.question}</button>
            <button class="x" onclick={() => remove(h)} aria-label={t("ask.delete")} title={t("ask.delete")}><Icon name="close" size={14} /></button>
          </div>
        {/each}
      {:else}
        <p class="none t3">{t("ask.history_none")}</p>
      {/each}
    </section>
  </div>
</Page>

<style>
  /* prototype-v5 "Ask" */
  .ask { display: grid; grid-template-columns: minmax(0, 1fr) 300px; gap: 14px; height: 100%; min-height: 0; }
  .card { background: var(--surface); border-radius: var(--r-l); box-shadow: var(--shadow-1); min-width: 0; min-height: 0; }
  .chat { display: flex; flex-direction: column; min-height: 0; }
  .msgs { flex: 1; min-height: 0; padding: 20px 24px; display: flex; flex-direction: column; gap: 18px; }
  .hint { margin: auto; max-width: 46ch; text-align: center; line-height: 22px; }
  .msg.me { align-self: flex-end; background: var(--primary-c); color: var(--on-primary-c); border-radius: 20px 20px 6px 20px;
    padding: 12px 16px; max-width: 70%; white-space: pre-wrap; word-break: break-word; }
  .msg.ai { max-width: 80%; line-height: 22px; border-radius: 12px; }
  .msg.ai.flash { animation: flash 1.6s ease-out; }
  @keyframes flash { from { background: var(--c-accent-tint); } to { background: transparent; } }
  .msg.ai .st { color: var(--text-3); font-size: 12px; margin-bottom: 8px; display: flex; gap: 8px; align-items: center; }
  .msg.ai .st.err { color: var(--danger); }
  .text { white-space: pre-wrap; word-break: break-word; }
  .created { margin-top: 10px; display: flex; gap: 6px; align-items: center; flex-wrap: wrap; font-size: 13px; color: var(--text-2); }
  .cite { display: inline-flex; align-items: center; height: 20px; padding: 0 7px; border: 0; border-radius: 10px; background: var(--surface-2);
    color: var(--primary); font: 600 11px/1 var(--font); margin: 0 2px; cursor: pointer; vertical-align: 2px; max-width: 32ch;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .cite:hover { background: var(--primary-c); }
  .composer { padding: 12px 16px 16px; display: grid; gap: 10px; flex: none; }
  .composer .box { display: flex; align-items: center; gap: 10px; background: var(--surface-2); border-radius: 26px; padding: 6px 6px 6px 18px; min-height: 52px; }
  .composer .box:focus-within { box-shadow: 0 0 0 2px var(--primary); }
  .composer input { flex: 1; min-width: 0; border: 0; background: none; outline: none; font-size: 15px; box-shadow: none; color: var(--text); }
  .composer .send { width: 40px; height: 40px; border: 0; border-radius: 20px; background: var(--primary); color: var(--on-primary);
    display: grid; place-items: center; cursor: pointer; flex: none; }
  .composer .send:disabled { opacity: .45; cursor: default; }
  .composer .opts { display: flex; gap: 14px; align-items: center; font-size: 13px; color: var(--text-2); padding: 0 8px; flex-wrap: wrap; }
  .ctx { display: inline-flex; gap: 10px; align-items: center; cursor: pointer; }
  .hist { padding-bottom: 12px; }
  .hist h4 { font-size: 12px; font-weight: 600; color: var(--text-3); text-transform: uppercase; letter-spacing: .04em; padding: 16px 16px 8px; }
  .day { font-size: 11px; color: var(--text-3); padding: 8px 16px 4px; }
  .none { padding: 4px 16px; font-size: 13px; }
  .h { display: flex; align-items: flex-start; gap: 4px; margin: 0 6px; border-radius: 12px; }
  .h:hover { background: var(--surface-2); }
  .hq { flex: 1; min-width: 0; border: 0; background: none; text-align: left; padding: 10px; font: 400 13px/18px var(--font); color: var(--text);
    cursor: pointer; overflow: hidden; display: -webkit-box; -webkit-line-clamp: 2; line-clamp: 2; -webkit-box-orient: vertical; }
  .x { border: 0; background: none; color: var(--text-3); padding: 10px 8px; cursor: pointer; opacity: 0; display: inline-grid; }
  .h:hover .x, .x:focus-visible { opacity: 1; }
  .x:hover { color: var(--danger); }
  @media (max-width: 760px) {
    .ask { grid-template-columns: minmax(0, 1fr); }
    .hist { display: none; }
    .opt { display: none; }
    .msg.ai, .msg.me { max-width: 100%; }
  }
</style>
