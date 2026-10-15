<script>
  // Шепнуть (spec 5.0 C7, prototype-v5 pageWhisper): the capture card (idle → listening with the words as they are
  // spoken → the result card: what was said, the parsed item with type chips, title, due and project, the other items
  // of the same phrase, Сохранить / Переговорить / Отменить) and the inbox (search, open count, Сегодня / Вчера /
  // Раньше, tick, "Сделать вопросом", delete with undo). The inbox is personal: it ignores the current project.
  import Icon from "../components/Icon.svelte";
  import Page from "../components/Page.svelte";
  import PopMenu from "../components/PopMenu.svelte";
  import { api } from "../lib/api.js";
  import { comboLabel, DEFAULT_HOTKEYS } from "../lib/hotkeys.js";
  import { app, t, go, toast } from "../lib/state.svelte.js";
  import { wh, toggleWhisper, startWhisper, cancelWhisper, saveWhisper } from "../lib/whisper.svelte.js";

  const KINDS = { task: "check", note: "pencil", remind: "bell", idea: "bolt" };
  const FILTERS = ["all", "open", "task", "note", "remind"];

  let filter = $state("all");
  let q = $state("");
  let items = $state([]);
  let open = $state(0);
  let loaded = $state(false);
  let active = $state(0);              // the item the result card edits
  let editingDue = $state(false);
  let saving = $state(false);

  const key = $derived(comboLabel(app.settings?.hotkeys?.whisper || DEFAULT_HOTKEYS.whisper));
  // macOS desktop: ⌥Space works from any window when core/hotkeys.py registered it, or another app holds it.
  let globalKey = $state("off");
  api("/api/hotkeys/status").then(s => (globalKey = s.whisper)).catch(() => {});
  const projectName = id => app.projects.find(p => p.id === id)?.name || app.archivedProjects.find(p => p.id === id)?.name || "";

  async function load() {
    const params = new URLSearchParams({ filter });
    if (q.trim()) params.set("q", q.trim());
    try {
      const body = await api(`/api/whispers?${params}`);
      items = body.items;
      open = body.open;
    } catch (err) { toast(err.message, { kind: "danger" }); }
    loaded = true;
  }
  let searchTimer = null;
  $effect(() => {
    filter; q; wh.saved;
    clearTimeout(searchTimer);
    searchTimer = setTimeout(load, q ? 200 : 0);
    return () => clearTimeout(searchTimer);
  });
  $effect(() => { if (wh.state === "result") { active = 0; editingDue = false; } });

  // ── dates ──────────────────────────────────────────────────────────────────
  const locale = () => (app.lang === "en" ? "en-GB" : "ru-RU");
  function dayStart(offset = 0) {
    const d = new Date(); d.setHours(0, 0, 0, 0); d.setDate(d.getDate() + offset);
    return d.getTime() / 1000;
  }
  function fmtDue(ts) {
    if (ts == null) return "";
    const d = new Date(ts * 1000);
    const time = d.toLocaleTimeString(locale(), { hour: "2-digit", minute: "2-digit" });
    if (ts >= dayStart(0) && ts < dayStart(1)) return t("wh.today_at", { time });
    if (ts >= dayStart(1) && ts < dayStart(2)) return t("wh.tomorrow_at", { time });
    if (ts >= dayStart(-1) && ts < dayStart(0)) return t("wh.yesterday_at", { time });
    return d.toLocaleDateString(locale(), { day: "numeric", month: "short" }) + ", " + time;
  }
  const pad = n => String(n).padStart(2, "0");
  function toInput(ts) {
    if (ts == null) return "";
    const d = new Date(ts * 1000);
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }
  const fromInput = v => (v ? new Date(v).getTime() / 1000 : null);
  function duration(s) {
    s = Math.round(s || 0);
    return `${Math.floor(s / 60)}:${pad(s % 60)}`;
  }

  // ── the result card ────────────────────────────────────────────────────────
  const cur = $derived(wh.items[active] || null);
  function setItem(i, changes) { wh.items[i] = { ...wh.items[i], ...changes }; }
  function reason(item) {
    const words = (item.project_words || []).map(w => `«${w}»`);
    if (!words.length) return "";
    const list = words.length > 1 ? words.slice(0, -1).join(", ") + t("wh.and") + words[words.length - 1] : words[0];
    return t("wh.reason", { words: list });
  }
  const projectItems = $derived([{ value: "", label: t("wh.project_none") }, { sep: true },
                                 ...app.projects.map(p => ({ value: p.id, label: p.name }))]);
  // "Сделать вопросом" makes a requirement, so it offers only projects with business analysis on (5.0.4).
  const qProjects = $derived(app.projects.filter(p => p.analysis !== false));
  const linkedOn = w => qProjects.some(p => p.id === w.project_id);
  function dropItem(i) {
    wh.items = wh.items.filter((_, j) => j !== i);
    if (active >= wh.items.length) active = Math.max(0, wh.items.length - 1);
  }
  async function save() {
    if (saving) return;
    saving = true;
    try {
      const reminders = wh.items.filter(i => (i.kind === "remind" || i.kind === "task") && i.due_at != null);
      const body = await saveWhisper();
      if (body) {
        const when = reminders.length ? " · " + t("wh.saved_notify", { when: fmtDue(Math.min(...reminders.map(i => i.due_at))) }) : "";
        toast(t("wh.saved_n", { n: body.items.length }) + when);
      }
    } catch (err) { toast(err.message, { kind: "danger" }); }
    saving = false;
  }

  // ── the inbox ──────────────────────────────────────────────────────────────
  const groups = $derived.by(() => {
    const today = dayStart(0), yesterday = dayStart(-1);
    const out = [{ key: "today", items: [] }, { key: "yesterday", items: [] }, { key: "earlier", items: [] }];
    for (const w of items) out[w.created_at >= today ? 0 : w.created_at >= yesterday ? 1 : 2].items.push(w);
    return out.filter(g => g.items.length);
  });
  const checkable = w => w.kind === "task" || w.kind === "remind";

  async function tick(w) {
    try {
      const body = await api(`/api/whispers/${w.id}`, { method: "PATCH", body: { done: !w.done } });
      open = body.open;
      if (filter === "open" && body.done) items = items.filter(x => x.id !== w.id);
      else items = items.map(x => (x.id === w.id ? { ...x, ...body } : x));
    } catch (err) { toast(err.message, { kind: "danger" }); }
  }

  async function remove(w) {
    try {
      const body = await api(`/api/whispers/${w.id}`, { method: "DELETE" });
      items = items.filter(x => x.id !== w.id);
      open = body.open;
      toast(t("wh.deleted"), { action: t("wh.undo"), onAction: async () => {
        await api(`/api/whispers/${w.id}/restore`, { method: "POST" });
        load();
      } });
    } catch (err) { toast(err.message, { kind: "danger" }); }
  }

  async function toQuestion(w, projectId = null) {
    try {
      const body = await api(`/api/whispers/${w.id}/to-question`, { method: "POST", body: projectId ? { project_id: projectId } : {} });
      items = items.map(x => (x.id === w.id ? { ...x, atom_id: body.atom_id } : x));
      app.atomsVersion++;
      toast(t("wh.question_made", { label: body.label, project: body.project_name }), {
        action: t("wh.question_open"), onAction: () => openQuestion(body.atom_id, body.project_id) });
    } catch (err) { toast(err.message, { kind: "danger" }); }
  }
  async function openQuestion(atomId, projectId) {
    if (projectId && projectId !== app.currentProjectId) {
      await api(`/api/projects/${projectId}/current`, { method: "POST" });
      app.currentProjectId = projectId;
    }
    go(`/atoms/atom/${atomId}`);
  }
</script>

<Page title={t("nav.whisper")} sub={t("wh.sub")} card={false}>
  {#snippet actions()}
    <div class="seg" role="tablist" aria-label={t("wh.filter")}>
      {#each FILTERS as f (f)}
        <button role="tab" aria-selected={filter === f} onclick={() => (filter = f)}>{t("wh.f." + f)}</button>
      {/each}
    </div>
  {/snippet}
  <div class="whisper">
    <section class="card wcap" aria-label={t("nav.whisper")} id="t-whisper">
      {#if wh.state === "idle"}
        <button class="wbtn" onclick={toggleWhisper} title={t("wh.speak", { key })} aria-label={t("wh.speak", { key })}>
          <Icon name="mic" size={44} /></button>
        <h2>{t("wh.idle_title")}</h2>
        <p class="hint">{t("wh.idle_hint")}<br>
          {#if globalKey === "taken"}{t("wh.keys_taken", { key })}
          {:else}{t(globalKey === "ok" ? "wh.idle_keys_global" : "wh.idle_keys")} <span class="kbd">{key}</span>{/if}</p>
      {:else if wh.state === "listening" || wh.state === "processing"}
        <button class="wbtn live" class:busy={wh.state === "processing"} onclick={toggleWhisper} disabled={wh.state === "processing"}
                title={t("wh.done")} aria-label={t("wh.done")}><Icon name="stop" size={40} /></button>
        <h2>{wh.state === "processing" ? t("wh.processing") : t("wh.listening")}</h2>
        <p class="hint">{t("wh.listening_hint")}</p>
        <div class="wlive" aria-live="polite"><span id="wlive">{wh.text}</span>{#if wh.state === "listening"}<span class="cursor"></span>{/if}</div>
      {:else if cur}
        <div class="wres">
          <div class="said"><small>{t("wh.said", { dur: duration(wh.result?.duration), asr: t("wh.asr_local") })}</small>{wh.result?.transcript}</div>
          {#if wh.result?.error}
            <p class="werr">{wh.result.needs_setup ? t("wh.setup_needed") : t("wh.parse_failed", { error: wh.result.error })}
              {#if wh.result.needs_setup}<button class="btn ghost" onclick={() => go("/settings")}>{t("wh.open_settings")}</button>{/if}</p>
          {/if}
          <div class="wparsed">
            <div class="types">
              {#each Object.entries(KINDS) as [k, icon] (k)}
                <button class="chip" aria-pressed={cur.kind === k} onclick={() => setItem(active, { kind: k })}>
                  <Icon name={icon} size={14} /> {t("wh.kind." + k)}</button>
              {/each}
            </div>
            <input class="title" value={cur.title} aria-label={t("wh.title_label")} spellcheck="false"
                   oninput={e => setItem(active, { title: e.currentTarget.value })} />
            <div class="meta">
              {#if editingDue}
                <input type="datetime-local" class="due-input" value={toInput(cur.due_at)} aria-label={t("wh.edit_due")}
                       onchange={e => { setItem(active, { due_at: fromInput(e.currentTarget.value) }); editingDue = false; }}
                       onblur={() => (editingDue = false)} />
              {:else}
                <button class="tag due-tag" class:danger={cur.due_at != null} onclick={() => (editingDue = true)} title={t("wh.edit_due")}>
                  <Icon name="bell" size={12} /> {cur.due_at != null ? fmtDue(cur.due_at) : t("wh.due_none")}</button>
                {#if cur.due_at != null}
                  <button class="x" onclick={() => setItem(active, { due_at: null })} aria-label={t("wh.clear_due")} title={t("wh.clear_due")}><Icon name="close" size={12} /></button>
                {/if}
              {/if}
              <PopMenu cls="tag proj-tag" chevron="" value={cur.project_id || ""} text={cur.project_id ? projectName(cur.project_id) || cur.project_name : t("wh.project_none")}
                       ariaLabel={t("wh.project")} items={projectItems}
                       onpick={v => setItem(active, { project_id: v || null, project_name: v ? projectName(v) : null, project_words: v === cur.project_id ? cur.project_words : [] })} />
              {#if cur.project_id && reason(cur)}<span class="t3">· {reason(cur)}</span>{/if}
            </div>
            {#each wh.items as other, j (j)}
              {#if j !== active}
                <div class="meta more t3">
                  <Icon name="plus" size={12} /> {t("wh.more")}:
                  <button class="more-item" onclick={() => { active = j; editingDue = false; }}>
                    <b class="t2">{t("wh.kind." + other.kind)} · {other.title}{other.due_at != null ? " · " + fmtDue(other.due_at) : ""}</b></button>
                  <button class="x" onclick={() => dropItem(j)} aria-label={t("wh.remove_item")} title={t("wh.remove_item")}><Icon name="close" size={12} /></button>
                </div>
              {/if}
            {/each}
            <div class="acts">
              <button class="btn primary save" onclick={save} disabled={saving || !wh.items.length}>{t("wh.save_n", { n: wh.items.length })} <Icon name="check" size={16} /></button>
              <button class="btn" onclick={() => { cancelWhisper(); startWhisper(); }}><Icon name="mic" size={16} /> {t("wh.again")}</button>
              <button class="btn ghost" onclick={cancelWhisper}>{t("wh.cancel")}</button>
            </div>
          </div>
          <p class="t3 privacy">{t("wh.privacy")}</p>
        </div>
      {/if}
      <p class="t3 notify-hint">{t("wh.notify_hint")}</p>
    </section>

    <section class="card winbox" aria-label={t("wh.inbox")}>
      <div class="list-tools">
        <label class="search grow"><Icon name="search" size={14} />
          <input type="search" bind:value={q} placeholder={t("wh.search")} aria-label={t("wh.search")} /></label>
        <span class="t3 open-n">{t("wh.open_n", { n: open })}</span>
      </div>
      <div class="scroll grow list">
        {#each groups as g (g.key)}
          <div class="wsec">{t("wh." + g.key)}</div>
          {#each g.items as w (w.id)}
            <div class="witem" class:done={w.done}>
              {#if checkable(w)}
                <input type="checkbox" class="cb" checked={w.done} onchange={() => tick(w)} aria-label={t("wh.done_label")} />
              {:else}<span class="cb none"></span>{/if}
              <span class="wkind {w.kind}"><Icon name={KINDS[w.kind]} size={18} /></span>
              <div class="body">
                <div class="tx">{w.title}</div>
                <div class="m">
                  <span>{t("wh.kind." + w.kind)}</span>
                  {#if w.due_at != null}<span class="due" class:ok={w.done}><Icon name="bell" size={11} /> {fmtDue(w.due_at)}</span>{/if}
                  {#if w.project_name}<span>· {w.project_name}</span>{/if}
                  <span class="grow"></span>
                  {#if w.atom_id}
                    <button class="link" onclick={() => openQuestion(w.atom_id, w.project_id)}>{t("wh.question_done")}</button>
                  {:else if w.project_name && linkedOn(w)}
                    <button class="link to-q" onclick={() => toQuestion(w)}>{t("wh.to_question")}</button>
                  {:else if !qProjects.length}
                    <button class="link to-q" disabled title={t("wh.to_question_none")}>{t("wh.to_question")}</button>
                  {:else}
                    <PopMenu cls="link to-q" chevron="" text={t("wh.to_question")} align="right"
                             items={[{ heading: t("wh.question_in") }, ...qProjects.map(p => ({ value: p.id, label: p.name }))]}
                             onpick={v => toQuestion(w, v)} />
                  {/if}
                  <button class="x del" onclick={() => remove(w)} aria-label={t("wh.delete")} title={t("wh.delete")}><Icon name="trash" size={14} /></button>
                </div>
              </div>
            </div>
          {/each}
        {:else}
          {#if loaded}<div class="empty-in t3">{q ? t("wh.nothing_found") : t("wh.empty")}</div>{/if}
        {/each}
      </div>
    </section>
  </div>
</Page>

<style>
  /* prototype-v5 "Whisper" */
  .whisper { display: grid; grid-template-columns: minmax(0, 1fr) minmax(360px, 38%); gap: 16px; height: 100%; min-height: 0; }
  .card { background: var(--surface); border-radius: var(--r-l); box-shadow: var(--shadow-1); min-width: 0; min-height: 0; }
  .wcap { display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 32px; text-align: center;
    position: relative; overflow: auto; }
  .wbtn { width: 112px; height: 112px; border-radius: 56px; border: 0; background: var(--primary); color: var(--on-primary);
    display: grid; place-items: center; box-shadow: var(--shadow-2); transition: transform .15s, background .15s; cursor: pointer; flex: none; }
  .wbtn:hover { transform: scale(1.04); }
  .wbtn.live { background: var(--rec); color: #fff; animation: wpulse 1.4s infinite; }
  .wbtn.busy { animation: none; opacity: .7; cursor: default; }
  @keyframes wpulse { 0%, 100% { box-shadow: 0 0 0 0 rgba(217,48,37,.35), var(--shadow-2); } 50% { box-shadow: 0 0 0 22px rgba(217,48,37,0), var(--shadow-2); } }
  .wcap h2 { font-size: 22px; font-weight: 600; letter-spacing: -.015em; margin-top: 24px; }
  .wcap .hint { color: var(--text-3); margin-top: 6px; font-size: 13px; line-height: 20px; }
  .wlive { margin-top: 24px; max-width: 560px; font-size: 18px; line-height: 28px; color: var(--text); min-height: 56px; }
  .wlive .cursor { display: inline-block; width: 2px; height: 20px; background: var(--primary); vertical-align: -3px; margin-left: 2px; animation: blink 1s steps(2) infinite; }
  @keyframes blink { 50% { opacity: 0; } }
  .wres { width: min(620px, 100%); text-align: left; margin-top: 8px; display: grid; gap: 12px; }
  .wres .said { color: var(--text-2); font-size: 15px; line-height: 23px; padding: 14px 18px; border-radius: 16px; background: var(--surface-2); }
  .wres .said small { display: block; color: var(--text-3); font-size: 12px; margin-bottom: 4px; }
  .werr { color: var(--danger); font-size: 13px; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
  .wparsed { border-radius: 20px; background: var(--surface); box-shadow: inset 0 0 0 2px var(--primary-c); padding: 16px 18px; display: grid; gap: 10px; }
  .types { display: flex; gap: 6px; flex-wrap: wrap; }
  .title { font-size: 17px; font-weight: 600; border: 0; background: none; box-shadow: none; padding: 0 4px; margin: 0 -4px; border-radius: 6px;
    color: var(--text); width: 100%; outline: none; }
  .title:focus { box-shadow: 0 0 0 2px var(--primary); }
  .meta { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; color: var(--text-2); font-size: 13px; }
  .meta.more { font-size: 12px; }
  .more-item { border: 0; background: none; padding: 0; font: inherit; cursor: pointer; text-align: left; }
  .more-item:hover b { text-decoration: underline; }
  .meta :global(.tag) { border: 0; cursor: pointer; font: inherit; font-size: 12px; height: 22px; }
  .meta :global(.proj-tag) { background: var(--surface-2); color: var(--text-2); }
  .due-tag:not(.danger) { background: var(--surface-2); color: var(--text-3); }
  .due-input { height: 26px; font-size: 13px; }
  .acts { display: flex; gap: 8px; margin-top: 4px; flex-wrap: wrap; }
  .privacy { font-size: 12px; text-align: center; line-height: 18px; }
  .notify-hint { position: absolute; bottom: 12px; left: 16px; right: 16px; font-size: 12px; }
  .x { border: 0; background: none; color: var(--text-3); padding: 2px; cursor: pointer; display: inline-grid; place-items: center; border-radius: 6px; }
  .x:hover { color: var(--danger); }
  .wkind { width: 36px; height: 36px; border-radius: 12px; display: grid; place-items: center; flex: none; }
  .wkind.task { background: var(--primary-c); color: var(--on-primary-c); }
  .wkind.note { background: var(--warn-c); color: var(--warn); }
  .wkind.remind { background: var(--danger-c); color: var(--danger); }
  .wkind.idea { background: var(--ok-c); color: var(--ok); }
  .winbox { display: flex; flex-direction: column; min-height: 0; }
  .list-tools { display: flex; gap: 10px; align-items: center; padding: 14px 16px 4px; }
  .open-n { font-size: 12px; white-space: nowrap; }
  .list { padding-bottom: 8px; min-height: 0; overflow: auto; flex: 1; }
  .wsec { font-size: 11px; font-weight: 600; letter-spacing: .06em; text-transform: uppercase; color: var(--text-3); padding: 14px 16px 6px; }
  .witem { display: grid; grid-template-columns: auto 36px minmax(0, 1fr); gap: 12px; align-items: start; padding: 10px 16px; margin: 0 8px; border-radius: 14px; }
  .witem:hover { background: var(--surface-2); }
  .witem .cb { margin-top: 10px; } .witem .cb.none { visibility: hidden; width: 16px; }
  .witem .tx { line-height: 20px; word-break: break-word; } .witem.done .tx { color: var(--text-3); text-decoration: line-through; }
  .witem .m { color: var(--text-3); font-size: 12px; margin-top: 2px; display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
  .witem .m .due { color: var(--danger); font-weight: 500; display: inline-flex; gap: 2px; align-items: center; }
  .witem .m .due.ok { color: var(--ok); }
  .witem .del { opacity: 0; }
  .witem:hover .del, .witem .del:focus-visible { opacity: 1; }
  .m :global(.link), .link { border: 0; background: none; padding: 0; color: var(--primary); font: inherit; font-size: 12px; cursor: pointer; }
  .m :global(.link:hover), .link:hover { text-decoration: underline; }
  .empty-in { padding: 32px 16px; text-align: center; font-size: 13px; }
  @media (max-width: 900px) {
    .whisper { grid-template-columns: minmax(0, 1fr); grid-template-rows: none; height: auto; }
    .wcap { min-height: 360px; }
    .notify-hint { position: static; margin-top: 16px; }
  }
</style>
