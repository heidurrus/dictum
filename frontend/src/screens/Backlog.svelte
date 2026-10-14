<script>
  import { keyOf } from "../lib/keys.js";
  import Icon from "../components/Icon.svelte";
  import Page from "../components/Page.svelte";
  import Panes from "../components/Panes.svelte";
  import PopMenu from "../components/PopMenu.svelte";
  import { explain } from "../lib/errors.js";
  import { api, pollJob } from "../lib/api.js";
  import { app, t, go, toast } from "../lib/state.svelte.js";
  import { SvelteSet } from "svelte/reactivity";

  const collapsed = new SvelteSet();          // item ids folded in this session
  const fold = id => (collapsed.has(id) ? collapsed.delete(id) : collapsed.add(id));
  const glyph = { epic: "E", story: "S", subtask: "T", nfr: "N" };

  let body = $state(null);
  let error = $state("");
  let job = $state(null);                // {kind, progress, message}
  let editing = $state(null);            // {id, title, body, goal, acceptance}

  async function load() {
    const pid = app.currentProjectId;
    try {
      const b = await api(`/api/projects/${pid}/backlog`);
      if (pid !== app.currentProjectId) return;
      body = b;
      error = "";
      if (b.running && !job) follow(b.running, "build");
    } catch (err) { error = err.message; }
  }
  $effect(() => { app.currentProjectId; load(); });

  const items = $derived(body?.items || []);
  const byParent = $derived.by(() => {
    const m = {};
    for (const i of items) (m[i.parent_id || "root"] ||= []).push(i);
    return m;
  });
  const epics = $derived((byParent.root || []).filter(i => i.kind !== "nfr"));
  const nfrs = $derived(items.filter(i => i.kind === "nfr"));
  const storyTitle = $derived(Object.fromEntries(items.filter(i => i.kind === "story").map(i => [i.id, i.title])));
  const hasFindings = $derived(items.some(i => i.kind === "story" && i.invest?.length));

  function fail(err) {
    const e = explain(err);
    toast(e.message, { kind: "danger", ...(e.setup ? { action: t("err.open_settings"), onAction: () => go("/settings") } : {}) });
  }
  async function follow(jobId, kind) {
    job = { kind, progress: 0, message: "" };
    try {
      const j = await pollJob(jobId, x => (job = { kind, progress: x.progress || 0, message: x.progress_msg || "" }), { interval: 800 });
      if (kind === "invest") toast(t("bl.invest_done", { n: j.result.with_findings }));
      else {
        const bits = [t("bl.built", { n: j.result.stories })];
        const linked = items.filter(i => i.jira_key).length;
        if (j.result.matched && linked) bits.push(t("bl.kept_links", { n: linked }));
        if (j.result.orphans?.length) bits.push(t("bl.orphans", { n: j.result.orphans.length }));
        toast(bits.join(" · "), j.result.orphans?.length ? { action: t("nav.export"), onAction: () => go("/export") } : {});
      }
    } catch (err) { fail(err); }
    finally { job = null; load(); }
  }
  let refineOpen = $state(false);
  let refineNote = $state("");
  async function run(kind, note = null) {
    refineOpen = false;
    docCache.clear();
    try {
      const { job_id } = await api(`/api/projects/${app.currentProjectId}/backlog/${kind}`, { method: "POST",
                                                                                          body: note ? { note } : {} });
      follow(job_id, kind);
    } catch (err) { fail(err); }
  }

  async function include(item, on) {
    try { body = { ...body, ...(await api(`/api/projects/${app.currentProjectId}/backlog/include`,
      { method: "POST", body: { ids: [item.id], included: on } })) }; }
    catch (err) { fail(err); }
  }
  async function move(item, direction) {
    try { body = await api(`/api/backlog/${item.id}/move`, { method: "POST", body: { direction } }); }
    catch (err) { fail(err); }
  }
  async function remove(item) {
    try {
      await api(`/api/backlog/${item.id}`, { method: "DELETE" });
      await load();
      toast(t("bl.deleted", { title: item.title }), { action: t("at.undo"), onAction: async () => {
        await api(`/api/backlog/${item.id}/restore`, { method: "POST" });
        load();
      } });
    } catch (err) { fail(err); }
  }
  async function add(kind, parent) {
    try {
      const it = await api(`/api/projects/${app.currentProjectId}/backlog`, { method: "POST",
        body: { kind, title: t("bl.new." + kind), parent_id: parent?.id || null } });
      await load();
      startEdit(it);
    } catch (err) { fail(err); }
  }
  function startEdit(item) {
    selectedId = item.id;
    if (app.inspector.backlog === false) app.inspector = { ...app.inspector, backlog: true };
    const ws = document.querySelector(".workspace");
    if (ws && ws.clientWidth < 900) app.inspectorOverlay = true;
    editing = { id: item.id, title: item.title, body: item.body, goal: item.goal,
                acceptance: (item.acceptance || []).map(a => ({ ...a })) };
  }
  async function saveEdit(item) {
    const e = editing;
    editing = null;
    const changes = {};
    for (const k of ["title", "body", "goal"]) if ((e[k] ?? "") !== (item[k] ?? "")) changes[k] = e[k];
    if (JSON.stringify(e.acceptance) !== JSON.stringify(item.acceptance || [])) changes.acceptance = e.acceptance;
    if (!Object.keys(changes).length) return;
    try { await api(`/api/backlog/${item.id}`, { method: "PATCH", body: changes }); load(); }
    catch (err) { fail(err); }
  }
  async function setPriority(item, priority) {
    try { await api(`/api/backlog/${item.id}`, { method: "PATCH", body: { priority: priority || null } }); load(); }
    catch (err) { fail(err); }
  }
  async function applyFix(item, fix) {
    try { await api(`/api/backlog/${item.id}`, { method: "PATCH", body: { body: fix } }); load(); toast(t("bl.fix_applied")); }
    catch (err) { fail(err); }
  }
  async function moveInto(nfr, storyId) {
    try {
      await api(`/api/backlog/${nfr.id}/move-into/${storyId}`, { method: "POST" });
      await load();
      toast(t("bl.moved_into", { title: storyTitle[storyId] || "" }));
    } catch (err) { fail(err); }
  }
  const refLabel = r => `§${r.section} · ${r.id}`;
  const children = id => byParent[id] || [];

  // One line per item; the selected item is read and edited in the inspector.
  let selectedId = $state(null);
  const flat = $derived.by(() => {
    const out = [];
    for (const e of epics) {
      out.push({ item: e, level: 0, foldable: children(e.id).length > 0 });
      if (collapsed.has(e.id)) continue;
      for (const s of children(e.id)) {
        out.push({ item: s, level: 1, foldable: children(s.id).length > 0 });
        if (!collapsed.has(s.id)) for (const x of children(s.id)) out.push({ item: x, level: 2, foldable: false });
      }
    }
    return out;
  });
  const order = $derived([...flat.map(f => f.item), ...nfrs]);
  const selected = $derived(items.find(i => i.id === selectedId) || null);
  $effect(() => { if (!selected && order.length) selectedId = order[0].id; });
  function pick(id) {
    selectedId = id;
    if (editing && editing.id !== id) editing = null;
    const ws = document.querySelector(".workspace");
    if (ws && ws.clientWidth < 900) app.inspectorOverlay = true;
  }
  const kindClass = { epic: "epic", story: "story", subtask: "sub", nfr: "nfr" };
  const parentOf = i => items.find(x => x.id === i.parent_id) || null;

  // The requirement a story comes from, for the context pane.
  const docCache = new Map();
  let refText = $state([]);              // [{ref, text, title}]
  $effect(() => {
    const it = selected;
    const refs = it?.refs || [];
    if (!refs.length) { refText = []; return; }
    const pid = app.currentProjectId;
    Promise.all(refs.map(async r => {
      const key = r.doc_id || "main";
      if (!docCache.has(key)) docCache.set(key, api(`/api/projects/${pid}/document${r.doc_id ? "?document=" + r.doc_id : ""}`).catch(() => null));
      const d = await docCache.get(key);
      const blocks = (d?.version?.content?.sections || []).flatMap(s => [...s.blocks, ...(s.subsections || []).flatMap(x => x.blocks)]);
      const b = blocks.find(x => x.id === r.id);
      return { ref: r, text: b?.text || "", sources: b?.sources || [], title: d?.document?.short || "" };
    })).then(list => { if (selected?.id === it.id) refText = list; });
  });

  function onKey(e) {
    const key = keyOf(e);
    if (app.route.name !== "backlog" || app.palette || e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.target.closest("textarea, select, [contenteditable], input:not([type=checkbox]), .menu")) return;
    const i = order.findIndex(x => x.id === selectedId);
    const it = order[i];
    if (key === "ArrowDown" || key === "j") { if (order[i + 1]) pick(order[i + 1].id); }
    else if (key === "ArrowUp" || key === "k") { if (i > 0) pick(order[i - 1].id); }
    else if (key === "ArrowLeft" && it && !collapsed.has(it.id) && children(it.id).length) collapsed.add(it.id);
    else if (key === "ArrowRight" && it) collapsed.delete(it.id);
    else if (key === " " && it && !e.target.matches?.("input[type=checkbox]")) include(it, !it.included);
    else if (key === "e" && it) startEdit(it);
    else return;
    e.preventDefault();
    requestAnimationFrame(() => document.getElementById(`bl-${selectedId}`)?.scrollIntoView({ block: "nearest" }));
  }
  const sub = $derived(body && items.length ? t("bl.sub", { e: body.counts.epic, s: body.counts.story, t: body.counts.subtask, n: body.included }) : t("bl.sub_empty"));
</script>

<svelte:window onkeydown={onKey} />

<Page title={t("nav.decomposition")} {sub} inspector={items.length ? "backlog" : ""}>
  {#snippet actions()}
    {#if body && body.latest}
      {#if items.length}
        <PopMenu cls="btn ghost" text={t("tr.more")} ariaLabel={t("tr.more")} align="right"
                 items={[{ value: "refine", label: t("bl.refine"), icon: "spark" }]} onpick={() => { refineNote = ""; refineOpen = true; }} />
        <button class="btn" disabled={!!job} onclick={() => run("invest")}><Icon name="check" size={14} /> {t("bl.invest")}</button>
        <button class="btn" class:primary={body.stale} disabled={!!job} onclick={() => run("build")}>
          <Icon name="refresh" size={14} /> {t("bl.rebuild")}</button>
        {#if !body.stale}
          <button class="btn primary" onclick={() => go("/export")}>{t("bl.to_export")} · {body.included} <Icon name="arrow" size={14} /></button>
        {/if}
      {:else}
        <button class="btn primary" disabled={!!job} onclick={() => run("build")}>{t("bl.build")}</button>
      {/if}
    {/if}
  {/snippet}

  {#if error}<div class="pad"><div class="banner danger"><Icon name="warn" /><span class="grow">{error}</span>
    <button class="btn sm" onclick={load}>{t("ov.retry")}</button></div></div>{/if}

  {#if body && !items.length}
    <div class="page scroll">
      {#if job}
        <div class="pad"><div class="banner info"><span class="spinner"></span><span class="grow num">{job.message}</span>
          <span class="progress w"><i style="width: {job.progress}%"></i></span></div>
          <div class="skeleton">{#each [50, 70, 64, 72, 46, 68, 60] as w, i (i)}<i style="width: {w}%; margin-left: {i % 3 ? 24 : 0}px"></i>{/each}</div></div>
      {:else if !body.latest}
        <div class="empty">
          <div class="glyph"><Icon name="tree" size={20} /></div>
          <h3>{t("bl.no_doc_title")}</h3>
          <p>{t("bl.no_doc")}</p>
          <button class="btn lg primary" onclick={() => go("/document")}>{t("bl.to_doc")} <Icon name="arrow" size={14} /></button>
        </div>
      {:else}
        <div class="empty">
          <div class="glyph"><Icon name="tree" size={20} /></div>
          <h3>{t("bl.ready_title", { v: body.latest })}</h3>
          <p>{t("bl.ready")}</p>
        </div>
      {/if}
    </div>
  {:else if body}
    <Panes screen="backlog">
      <div class="notices">
        {#if job}
          <div class="banner info"><span class="spinner"></span><span class="grow num">{job.message}</span>
            <span class="progress w"><i style="width: {job.progress}%"></i></span></div>
        {:else if body.stale}
          <div class="banner warn row-note"><Icon name="warn" /><span class="grow">{t("bl.stale", { a: body.built_from, b: body.latest })}</span>
            <button class="btn sm" onclick={() => run("build")}>{t("bl.rebuild")}</button></div>
        {:else if hasFindings}
          <div class="banner warn"><Icon name="warn" /><span class="grow">{t("bl.findings_hint")}</span></div>
        {/if}
      </div>
      <div class="pane-body scroll">
        <div class="tree" role="tree" aria-label={t("nav.decomposition")}>
          <div class="tree-head cap">
            <span></span><span>{t("bl.col.item")}</span>
            <span class="col-x">{t("at.priority")}</span><span class="col-x">INVEST</span><span class="col-x">{t("bl.col.refs")}</span><span class="col-x">Jira</span>
            <span class="col-s">{t("bl.col.state")}</span>
          </div>
          {#each flat as f (f.item.id)}
            {@render line(f.item, f.level, f.foldable)}
          {/each}
          <div class="adds">
            <button class="btn sm ghost" onclick={() => add("epic", null)}><Icon name="plus" size={14} /> {t("bl.add_epic")}</button>
            {#if selected && ["epic", "story"].includes(selected.kind)}
              {@const ep = selected.kind === "epic" ? selected : parentOf(selected)}
              {#if ep}<button class="btn sm ghost" onclick={() => add("story", ep)}><Icon name="plus" size={14} /> {t("bl.add_story_to", { title: ep.title })}</button>{/if}
            {/if}
          </div>
          {#if nfrs.length}
            <div class="group-head" title={t("bl.nfr_hint")}><b>{t("bl.nfr_title")}</b><span class="t3 num">{nfrs.length}</span>
              <span class="t3 trunc grow opt">{t("bl.nfr_short")}</span></div>
            {#each nfrs as nfr (nfr.id)}
              {@render line(nfr, 0, false)}
            {/each}
          {/if}
        </div>
      </div>

      {#snippet inspector()}
        {#if selected}
          {@const item = selected}
          <div class="pane-head">
            <span class="glyph-k {item.kind}">{glyph[item.kind]}</span>
            <h2 class="grow trunc">{t("bl.kind_full." + item.kind)}</h2>
            {#if item.jira_key}<a class="chip mono" href={item.jira_url} target="_blank" rel="noreferrer" title={t("bl.in_jira")}>{item.jira_key}</a>{/if}
          </div>
          <div class="pane-body scroll">
            <div class="insp-body story node {kindClass[item.kind]}">
              {#if editing?.id === item.id}
                <div class="insp-sec edit">
                  <label class="label" for="bl-title">{t("bl.title")}</label>
                  <input class="input" id="bl-title" bind:value={editing.title} />
                  {#if item.kind === "epic"}
                    <label class="label" for="bl-goal">{t("bl.goal")}</label>
                    <input class="input" id="bl-goal" bind:value={editing.goal} />
                  {:else if item.kind === "story"}
                    <label class="label" for="bl-body">{t("bl.story_label")}</label>
                    <textarea class="input" id="bl-body" rows="3" bind:value={editing.body} placeholder={t("bl.story_ph")}></textarea>
                    <p class="label">{t("bl.ac")}</p>
                    {#each editing.acceptance as ac, i (i)}
                      <div class="ac-edit">
                        <input class="input" bind:value={ac.given} placeholder={t("bl.given")} aria-label={t("bl.given")} />
                        <input class="input" bind:value={ac.when} placeholder={t("bl.when")} aria-label={t("bl.when")} />
                        <input class="input" bind:value={ac.then} placeholder={t("bl.then")} aria-label={t("bl.then")} />
                        <button class="btn sm ghost danger" onclick={() => editing.acceptance.splice(i, 1)}>{t("bl.remove_ac")}</button>
                      </div>
                    {/each}
                    <div><button class="btn sm" onclick={() => editing.acceptance.push({ given: "", when: "", then: "" })}>
                      <Icon name="plus" size={14} /> {t("bl.add_ac")}</button></div>
                  {/if}
                </div>
              {:else}
                <div class="insp-sec">
                  <p class="insp-statement">{item.title}</p>
                  <p class="tags">
                    {#if item.pinned}<span class="badge">{t("bl.edited")}</span>{:else if item.generated}<span class="badge">{t("bl.generated")}</span>{/if}
                    {#if !item.included}<span class="badge">{t("bl.not_included")}</span>{/if}
                  </p>
                  {#if item.kind === "epic" && item.goal}<p class="goal">{t("bl.goal_label")}: {item.goal}</p>{/if}
                  {#if item.kind === "story" && item.body}<p class="story-text">{item.body}</p>{/if}
                </div>
                {#if item.acceptance?.length}
                  <div class="insp-sec">
                    <p class="cap">{t("bl.ac")}</p>
                    <div class="acs well">
                      {#each item.acceptance as ac, i (i)}
                        <div class="ac-item">
                          <div class="ac-row"><b>{t("bl.given")}</b><span>{ac.given}</span></div>
                          <div class="ac-row"><b>{t("bl.when")}</b><span>{ac.when}</span></div>
                          <div class="ac-row"><b>{t("bl.then")}</b><span>{ac.then}</span></div>
                        </div>
                      {/each}
                    </div>
                  </div>
                {/if}
                {#each item.invest || [] as f, i (i)}
                  <div class="invest">
                    <p class="status warn"><Icon name="warn" size={12} /> INVEST · {f.letter}</p>
                    <p>{f.reason}</p>
                    {#if f.fix}<p class="fix well">{f.fix}</p>
                      <div><button class="btn sm primary" onclick={() => applyFix(item, f.fix)}>{t("bl.apply")}</button></div>{/if}
                    {#if item.kind === "nfr" && f.move_to?.length}
                      <div class="moves">
                        {#each f.move_to as sid (sid)}
                          {#if storyTitle[sid]}<button class="btn sm" onclick={() => moveInto(item, sid)}>{t("bl.move_into", { title: storyTitle[sid] })}</button>{/if}
                        {/each}
                      </div>
                    {/if}
                  </div>
                {/each}
                <div class="insp-sec">
                  <p class="cap">{t("insp.props")}</p>
                  <dl class="kv">
                    {#if item.kind !== "subtask"}
                      <dt title={t("at.prio_hint")}>{t("at.priority")}</dt>
                      <dd><PopMenu value={item.priority || ""} ariaLabel={t("at.priority")}
                                   items={[...["must", "should", "could", "wont"].map(v => ({ value: v, label: t("at.prio." + v) })), { sep: true }, { value: "", label: t("at.prio.none") }]}
                                   onpick={v => setPriority(item, v)} /></dd>
                    {/if}
                    <dt>{t("bl.to_jira")}</dt>
                    <dd><label class="check"><input type="checkbox" checked={item.included} onchange={e => include(item, e.currentTarget.checked)} />
                      {item.included ? t("bl.inc_yes") : t("bl.inc_no")}</label></dd>
                    {#if item.refs?.length}
                      <dt>{t("bl.col.refs")}</dt>
                      <dd class="refs">{#each item.refs as r (r.id)}<button class="link" onclick={() => go(r.doc_id ? `/document/${r.doc_id}` : "/document")}>{refLabel(r)}</button>{/each}</dd>
                    {/if}
                  </dl>
                </div>
                <div class="insp-sec manage">
                  {#if item.kind === "story"}<button class="btn sm ghost" onclick={() => add("subtask", item)}><Icon name="plus" size={14} /> {t("bl.add_sub")}</button>{/if}
                  {#if item.kind !== "nfr"}
                    <button class="btn sm ghost" onclick={() => move(item, "up")}>{t("bl.up")}</button>
                    <button class="btn sm ghost" onclick={() => move(item, "down")}>{t("bl.down")}</button>
                  {/if}
                  <button class="btn sm ghost danger" onclick={() => remove(item)}><Icon name="trash" size={14} /> {t("at.delete")}</button>
                </div>
              {/if}
            </div>
          </div>
          <div class="pane-foot">
            {#if editing?.id === item.id}
              <button class="btn primary" disabled={!editing.title.trim()} onclick={() => saveEdit(item)}>{t("at.save")}</button>
              <button class="btn ghost" onclick={() => (editing = null)}>{t("at.cancel")}</button>
            {:else}
              <button class="btn" onclick={() => startEdit(item)}><Icon name="pencil" size={14} /> {t("at.edit")} <span class="kbd">E</span></button>
              <button class="btn ghost" onclick={() => include(item, !item.included)}>{item.included ? t("bl.exclude") : t("bl.include")} <span class="kbd">␣</span></button>
            {/if}
          </div>
        {:else}
          <div class="empty insp-empty"><p>{t("bl.pick")}</p></div>
        {/if}
      {/snippet}

      {#snippet context()}
        <div class="pane-head"><h2 class="grow trunc">{t("bl.ctx")}</h2></div>
        <div class="pane-body scroll">
          {#each refText as r (r.ref.id)}
            <div class="ctx-req">
              <p><span class="type plain fr">{r.ref.id}</span> <span class="t3">{r.title} · §{r.ref.section}</span></p>
              <p class="txt">{r.text || t("bl.ctx_missing")}</p>
              {#each r.sources.slice(0, 2) as s, i (i)}
                <button class="chip" title={s.quote} onclick={() => go(`/source/${s.source_id}/seg/${s.segment_idx}`)}>
                  <Icon name={s.start != null ? "wave" : "file"} size={12} /><span class="trunc">{s.source_title}</span></button>
              {/each}
            </div>
          {:else}
            <p class="ctx-none">{t("bl.ctx_none")}</p>
          {/each}
        </div>
      {/snippet}
    </Panes>
  {/if}
</Page>

{#if refineOpen}
  <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
  <div class="scrim" onclick={e => e.target === e.currentTarget && (refineOpen = false)}>
    <div class="sheet" role="dialog" aria-modal="true" aria-labelledby="blr-h">
      <h2 id="blr-h">{t("bl.refine")}</h2>
      <p>{t("bl.refine_hint")}</p>
      <!-- svelte-ignore a11y_autofocus -->
      <textarea class="input" rows="3" bind:value={refineNote} autofocus placeholder={t("ai.refine_ph.backlog")} aria-label={t("bl.refine")}></textarea>
      <div class="acts">
        <button class="btn" onclick={() => (refineOpen = false)}>{t("at.cancel")}</button>
        <button class="btn primary" disabled={!refineNote.trim() || !!job} onclick={() => run("build", refineNote)}>{t("ai.refine_run")}</button>
      </div>
    </div>
  </div>
{/if}

{#snippet line(item, level, foldable)}
  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <div class="node {kindClass[item.kind]} l{level}" class:off={!item.included} id="bl-{item.id}" role="treeitem" tabindex="-1"
       aria-selected={item.id === selectedId} aria-expanded={foldable ? !collapsed.has(item.id) : undefined} onclick={() => pick(item.id)}
       ondblclick={() => startEdit(item)}>
    <div class="row-line">
      <input type="checkbox" class="inc" checked={item.included} aria-label={item.title} onclick={e => e.stopPropagation()}
             onchange={e => include(item, e.currentTarget.checked)} />
      <div class="node-title">
        {#if foldable}
          <button class="twist" class:open={!collapsed.has(item.id)} onclick={e => { e.stopPropagation(); fold(item.id); }}
                  aria-label={item.title} aria-expanded={!collapsed.has(item.id)}><Icon name="chevron" size={12} /></button>
        {:else}<span class="twist"></span>{/if}
        <span class="glyph-k {item.kind}" title={t("bl.kind_full." + item.kind)}>{glyph[item.kind]}</span>
        <span class="t trunc">{item.title}</span>
        {#if item.kind === "epic" && item.goal}<span class="goal t3 trunc opt">{t("bl.goal_label")}: {item.goal}</span>{/if}
      </div>
      <span class="col-x">{item.priority ? t("at.prio." + item.priority) : ""}</span>
      <span class="col-x">{#if item.invest?.length}<span class="status warn">{item.invest.map(f => f.letter).join(" ")}</span>{/if}</span>
      <span class="col-x trunc mono t3">{(item.refs || []).map(r => r.id).join(", ")}</span>
      <span class="col-x">{#if item.jira_key}<a class="mono" href={item.jira_url} target="_blank" rel="noreferrer" onclick={e => e.stopPropagation()}>{item.jira_key}</a>{/if}</span>
      <span class="col-s">
        {#if item.invest?.length}<span class="status warn narrow-only">INVEST</span>{/if}
        {#if item.pinned}<span class="row-note t3">{t("bl.edited")}</span>{:else if item.generated}<span class="row-note t3">{t("bl.generated")}</span>{/if}
      </span>
    </div>
  </div>
{/snippet}

<style>
  .page { height: 100%; }
  .pad { padding: var(--s-6) var(--gutter); display: grid; gap: var(--s-6); }
  .skeleton { display: grid; gap: var(--s-5); }
  .skeleton i { height: 12px; border-radius: var(--r-xs); background: var(--surface-3); animation: breathe 1.6s ease-in-out infinite; }
  @keyframes breathe { 50% { opacity: .45; } }
  .notices:not(:empty) { padding: var(--s-4) var(--gutter) 0; }
  .progress.w { width: 120px; flex: none; }

  .tree { container-type: inline-size; container-name: list; padding-bottom: var(--s-11); }
  .tree-head, .row-line { display: grid; align-items: center; column-gap: var(--s-5); padding: 0 var(--gutter); grid-template-columns: 20px minmax(0, 1fr) 112px; }
  .tree-head { position: sticky; top: 0; z-index: 2; height: 28px; background: var(--surface); border-bottom: 1px solid var(--outline-2); }
  .node { position: relative; cursor: default; transition: background var(--d-fast); scroll-margin: 40px 0; }
  .row-line { min-height: 40px; }
  .node::after { content: ""; position: absolute; left: calc(var(--gutter) + 32px); right: 0; bottom: 0; height: 1px; background: var(--outline-2); }
  .node:hover { background: var(--surface-2); }
  .node[aria-selected="true"] { background: var(--primary-c); }
  .node[aria-selected="true"]::before { content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 3px; background: var(--primary); }
  .node-title { display: flex; align-items: center; gap: var(--s-4); min-width: 0; padding: var(--s-4) 0; }
  .node.epic .node-title { font: var(--w-semibold) var(--size-item)/var(--lh-item) var(--font); }
  .node.story .node-title, .node.nfr .node-title { font: var(--w-medium) var(--size-item)/var(--lh-item) var(--font); }
  .node.l1 .node-title { padding-left: 24px; }
  .node.l2 .node-title { padding-left: 48px; color: var(--text-2); }
  .node.sub .row-line { min-height: 32px; }
  .node.off .t { color: var(--text-3); }
  .goal { font-weight: var(--w-regular); font-size: var(--size-foot); flex: 0 1 auto; }
  .col-x { display: none; font-size: var(--size-foot); color: var(--text-2); min-width: 0; }
  .tree-head .col-x { font-size: var(--size-caption); color: var(--text-3); }
  .col-s { justify-self: end; font-size: var(--size-foot); display: inline-flex; gap: var(--s-4); align-items: center; white-space: nowrap; }
  .twist { width: 16px; height: 16px; color: var(--text-3); display: grid; place-items: center; transition: transform var(--d-base) var(--ease-out);
    flex: none; border: 0; background: none; padding: 0; cursor: pointer; border-radius: var(--r-xs); }
  .twist.open { transform: rotate(90deg); }
  .glyph-k { width: 16px; height: 16px; border-radius: 4px; display: grid; place-items: center; font: var(--w-bold) 10px/1 var(--font); color: #fff; flex: none; }
  .glyph-k.epic { background: #7A5AC8; } .glyph-k.story { background: #2F8F55; } .glyph-k.subtask { background: #3F7DC0; } .glyph-k.nfr { background: #0C6F68; }
  @container list (min-width: 900px) {
    .tree-head, .row-line { grid-template-columns: 20px minmax(0, 1fr) 80px 72px minmax(80px, 140px) 88px 112px; }
    .col-x { display: block; }
    .narrow-only { display: none; }
  }
  .adds { display: flex; gap: var(--s-3); padding: var(--s-4) var(--gutter); flex-wrap: wrap; }
  .group-head { display: flex; align-items: center; gap: var(--s-4); height: 28px; padding: 0 var(--gutter); background: var(--surface-2);
    border-block: 1px solid var(--outline-2); font-size: var(--size-foot); color: var(--text-2); margin-top: var(--s-6); }
  .group-head b { font-weight: var(--w-semibold); }

  .insp-empty { padding-top: 20vh; } .insp-empty p { font-size: var(--size-body); color: var(--text-3); }
  .insp-body.node::after, .insp-body.node::before { display: none; }
  .insp-body.node:hover { background: none; }
  .tags { display: flex; gap: var(--s-3); flex-wrap: wrap; }
  .tags:empty { display: none; }
  .story-text { font: var(--w-regular) var(--size-read)/var(--lh-read) var(--font); letter-spacing: -.005em; text-wrap: pretty; }
  .goal { color: var(--text-2); }
  .ac-item { padding: var(--s-3) 0; }
  .ac-item + .ac-item { border-top: 1px solid var(--outline-2); }
  .ac-row { display: grid; grid-template-columns: 56px minmax(0, 1fr); gap: var(--s-2) var(--s-4); padding: 2px var(--s-5); }
  .ac-row b { font-weight: var(--w-medium); color: var(--text-3); font-size: var(--size-foot); line-height: var(--lh-body); }
  .invest { border-radius: var(--r-m); background: var(--warn-c); padding: var(--s-5); display: grid; gap: var(--s-3); grid-template-columns: minmax(0, 1fr); }
  .invest .fix { padding: var(--s-4); }
  .moves { display: flex; gap: var(--s-3); flex-wrap: wrap; }
  .edit { gap: var(--s-3); }
  .edit .label { margin-top: var(--s-3); }
  .ac-edit { display: grid; gap: var(--s-2); padding: var(--s-4); border-radius: var(--r-m); background: var(--surface-2); justify-items: start; }
  .ac-edit .input { width: 100%; }
  .refs { display: flex; flex-wrap: wrap; gap: var(--s-2) var(--s-5); }
  .link { border: 0; background: none; padding: 0; font: inherit; color: var(--primary); cursor: pointer; }
  .link:hover { text-decoration: underline; }
  .manage { display: flex; gap: var(--s-2); flex-wrap: wrap; }
  .ctx-req { padding: var(--s-5) var(--s-6); border-bottom: 1px solid var(--outline-2); display: grid; gap: var(--s-3); justify-items: start; grid-template-columns: minmax(0, 1fr); }
  .ctx-req .txt { font: var(--w-regular) var(--size-item)/22px var(--font); text-wrap: pretty; }
  .ctx-req .chip { max-width: 100%; }
  .ctx-none { padding: var(--s-9) var(--s-7); color: var(--text-3); text-align: center; }
</style>
