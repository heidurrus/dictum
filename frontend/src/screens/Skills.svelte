<script>
  import { keyOf } from "../lib/keys.js";
  import { untrack } from "svelte";
  import Icon from "../components/Icon.svelte";
  import Page from "../components/Page.svelte";
  import Panes from "../components/Panes.svelte";
  import { explain } from "../lib/errors.js";
  import { api, pollJob } from "../lib/api.js";
  import { fmtDate, renderMarkdown } from "../lib/format.js";
  import { saveUrl } from "../lib/save.js";
  import { app, t, go, toast, currentProject } from "../lib/state.svelte.js";

  let list = $state(null);               // {stages, skills, project_id}
  let skill = $state(null);              // full skill as loaded
  let draft = $state(null);              // editable copy
  let error = $state("");
  let saving = $state(false);
  let historyText = $state(null);        // {id, text}
  let tryState = $state(null);           // {running, progress, message, result, partial}
  let trySource = $state("");
  let importInput = $state(null);
  let templateInput = $state(null);

  const selected = $derived(app.route.skill || null);
  const clone = o => JSON.parse(JSON.stringify(o));     // reactive state can't go through structuredClone
  // The desktop bridge can arrive slightly after the page loads.
  let desktop = $state(!!window.pywebview);
  $effect(() => {
    const ready = () => (desktop = true);
    window.addEventListener("pywebviewready", ready);
    return () => window.removeEventListener("pywebviewready", ready);
  });

  async function loadList() {
    try { list = await api(`/api/skills?project_id=${app.currentProjectId}`); }
    catch (err) { error = err.message; }
  }
  async function loadSkill(name) {
    if (!name) { skill = draft = null; return; }
    try {
      skill = await api(`/api/skills/${name}`);
      draft = clone({ title: skill.title, description: skill.description, instructions: skill.instructions,
                                meta: skill.meta });
      historyText = null;
      tryState = null;
    } catch (err) { skill = draft = null; toast(err.message, { kind: "danger" }); }
  }
  $effect(() => { app.currentProjectId; app.lang; loadList(); });
  $effect(() => { app.lang; loadSkill(selected); });

  const dirty = $derived(!!(skill && draft) && JSON.stringify(draft) !== JSON.stringify(
    { title: skill.title, description: skill.description, instructions: skill.instructions, meta: skill.meta }));
  const editable = $derived(!!skill && !skill.builtin && !skill.error);
  const stageInfo = $derived(list && skill ? list.stages.find(s => s.id === skill.stage) : null);
  const grouped = $derived(list ? list.stages.map(st => ({ ...st, skills: list.skills.filter(s => s.stage === st.id) }))
    .concat([{ id: "broken", skills: list.skills.filter(s => s.error) }]).filter(g => g.skills.length) : []);
  const readySources = $derived(app.sources.filter(s => s.status === "ready"));

  function open(name) {
    if (dirty && !confirm(t("sk.leave"))) return;
    go(`/skills/${name}`);
  }
  // Warn before leaving the app screen with unsaved edits.
  $effect(() => {
    const handler = e => { if (dirty) { e.preventDefault(); e.returnValue = ""; } };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  });

  async function save() {
    if (!editable || !dirty) return;
    saving = true;
    try {
      const updated = await api(`/api/skills/${skill.name}`, { method: "PUT", body: { ...draft, lang: app.lang } });
      skill = updated;
      draft = clone({ title: updated.title, description: updated.description,
                                instructions: updated.instructions, meta: updated.meta });
      toast(t("sk.saved", { v: updated.version }));
      loadList();
    } catch (err) { toast(err.message, { kind: "danger", ms: 12000 }); }
    finally { saving = false; }
  }
  function onKey(e) {
    const key = keyOf(e);
    if ((e.metaKey || e.ctrlKey) && key.toLowerCase() === "s" && app.route.name === "skills") { e.preventDefault(); save(); }
  }

  async function copy() {
    try {
      const c = await api("/api/skills", { method: "POST", body: { from: skill.name } });
      await loadList();
      toast(t("sk.copied"));
      go(`/skills/${c.name}`);
    } catch (err) { toast(err.message, { kind: "danger" }); }
  }
  async function remove() {
    const name = skill.name, title = skill.title;
    if (!confirm(`${t("sk.delete")}: ${title}?`)) return;
    try {
      await api(`/api/skills/${name}`, { method: "DELETE" });
      await loadList();
      go("/skills");
      toast(t("sk.deleted", { name: title }), { action: t("at.undo"), onAction: async () => {
        await api(`/api/skills/${name}/undelete`, { method: "POST" });
        await loadList();
        go(`/skills/${name}`);
      } });
    } catch (err) { toast(err.message, { kind: "danger" }); }
  }
  async function reveal(what) {
    try {
      await api(`/api/skills/${skill.name}/open`, { method: "POST", body: { what } });
      if (what === "template") toast(t("sk.template_opened"), { ms: 9000 });
    } catch (err) { toast(err.message, { kind: "danger" }); }
  }

  async function useGlobally() {
    try { list = await api("/api/skills/active", { method: "PUT", body: { stage: skill.stage, skill: skill.name } }); }
    catch (err) { toast(err.message, { kind: "danger" }); }
  }
  const titleOf2 = name => list?.skills.find(x => x.name === name)?.title || name;
  async function useForProject(on) {
    try {
      list = await api("/api/skills/active", { method: "PUT",
        body: { stage: skill.stage, skill: on ? skill.name : null, project_id: app.currentProjectId } });
    } catch (err) { toast(err.message, { kind: "danger" }); }
  }

  async function importFile(e) {
    const f = e.currentTarget.files[0];
    e.currentTarget.value = "";
    if (!f) return;
    const form = new FormData();
    form.append("file", f);
    try {
      const s = await api("/api/skills/import", { method: "POST", form });
      await loadList();
      toast(t("sk.imported", { name: s.title }));
      go(`/skills/${s.name}`);
    } catch (err) { toast(err.message, { kind: "danger", ms: 12000 }); }
  }
  async function uploadTemplate(e) {
    const f = e.currentTarget.files[0];
    e.currentTarget.value = "";
    if (!f) return;
    const form = new FormData();
    form.append("file", f);
    try { skill = await api(`/api/skills/${skill.name}/template`, { method: "POST", form }); toast(t("sk.template_uploaded")); }
    catch (err) { toast(err.message, { kind: "danger" }); }
  }

  async function showHistory(h) {
    if (h.kind !== "text") return;
    try { historyText = { id: h.id, ...(await api(`/api/skills/${skill.name}/history/${h.id}`)) }; }
    catch (err) { toast(err.message, { kind: "danger" }); }
  }
  async function restore(h) {
    if (dirty && !confirm(t("sk.leave"))) return;
    try {
      await api(`/api/skills/${skill.name}/history/${h.id}/restore`, { method: "POST" });
      await loadSkill(skill.name);
      toast(t("sk.restored"));
    } catch (err) { toast(err.message, { kind: "danger" }); }
  }

  // ── try it ────────────────────────────────────────────────────────────────
  const tryMode = $derived(!skill ? null : ["summary", "global", "extract"].includes(skill.stage) ? "source"
    : ["frd", "quality"].includes(skill.stage) ? "project" : skill.stage === "export" ? "export" : null);
  $effect(() => { if (!trySource && readySources.length) trySource = readySources[0].id; });

  async function runTry() {
    tryState = { running: true, progress: 0, message: "", partial: "" };
    try {
      const { job_id } = await api("/api/skills/try", { method: "POST", body: {
        name: skill.name, ...draft, source_id: tryMode === "source" ? trySource : null, project_id: app.currentProjectId } });
      const job = await pollJob(job_id, j => { tryState = { running: true, progress: j.progress || 0,
        message: j.progress_msg || "", partial: j.partial || "" }; });
      tryState = { running: false, result: job.result };
    } catch (err) {
      tryState = null;
      const e = explain(err);
      toast(e.message, { kind: "danger", ...(e.setup ? { action: t("err.open_settings"), onAction: () => go("/settings") } : {}) });
    }
  }
  async function exportSample() {
    try {
      const body = await api(`/api/projects/${app.currentProjectId}/document`);
      if (!body.version) { toast(t("sk.try_no_doc")); return; }
      saveUrl(`/api/documents/${body.document.id}/export.docx?template=${skill.name}`, `${body.document.title} (${skill.title}).docx`);
    } catch (err) { toast(err.message, { kind: "danger" }); }
  }

  // ── stage editors ─────────────────────────────────────────────────────────
  const REQUIRED = ["functional", "nfr", "questions"];
  const KINDS = ["purpose", "context", "functional", "nfr", "out_of_scope", "questions"];
  const titleOf = (title, lang) => (typeof title === "object" && title) ? (title[lang] ?? "") : (lang === "ru" ? title ?? "" : "");
  function setTitle(sec, lang, value) {
    const cur = typeof sec.title === "object" && sec.title ? sec.title : { ru: sec.title || "" };
    sec.title = { ...cur, [lang]: value };
  }
  function move(i, d) {
    const s = draft.meta.sections;
    const j = i + d;
    if (j < 0 || j >= s.length) return;
    [s[i], s[j]] = [s[j], s[i]];
  }
  function addSection() {
    const keys = new Set(draft.meta.sections.map(s => s.key));
    let n = 1;
    while (keys.has(`section_${n}`)) n++;
    draft.meta.sections.push({ key: `section_${n}`, title: { ru: "", en: "" }, instructions: "" });
  }
  const words = lang => (draft.meta.vague_words?.[lang] || []).join(", ");
  function setWords(lang, text) {
    draft.meta.vague_words = { ...(draft.meta.vague_words || {}),
      [lang]: text.split(",").map(w => w.trim()).filter(Boolean) };
  }
  function addRule() {
    draft.meta.rules = [...(draft.meta.rules || []), { id: `rule_${(draft.meta.rules || []).length + 1}`, title: "", description: "" }];
  }
  const typeClass = { functional: "fr", nfr: "nfr", question: "q", business: "br", risk: "rsk", current: "as" };

  // Editor tabs: what a stage has decides which appear.
  const tabs = $derived(!skill ? [] : [
    ...(skill.stage !== "export" ? ["instructions"] : []),
    ...(skill.stage === "frd" ? ["sections"] : []),
    ...(skill.stage === "quality" ? ["rules"] : []),
    ...(skill.stage === "export" ? ["template"] : []),
    ...(tryMode && !skill.error ? ["try"] : []),
    "contract",
    ...(editable ? ["history"] : []),
    ...(!skill.error ? ["usage"] : []),
  ]);
  const PREFIX = { functional: "FR", nfr: "NFR", question: "Q", business: "BR", risk: "RSK", current: "AS" };
  let tab = $state("instructions");
  $effect(() => { skill?.name; untrack(() => { tab = tabs[0] || "instructions"; }); });
  function tabKey(e) {
    const i = tabs.indexOf(tab);
    if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
      e.preventDefault();
      tab = tabs[(i + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
      requestAnimationFrame(() => document.getElementById("sk-tab-" + tab)?.focus());
    }
  }
</script>

<svelte:window onkeydown={onKey} />

<Page title={t("sk.title")} sub={t("sk.sub")} inspector={skill && !skill.error ? "skills" : ""}>
  {#snippet actions()}
    <input type="file" accept=".zip,.md" class="hidden" bind:this={importInput} onchange={importFile} aria-label={t("sk.import")} />
    <button class="btn" title={t("sk.import_hint")} onclick={() => importInput.click()}><Icon name="upload" size={14} /> {t("sk.import")}</button>
    {#if skill && !skill.error}
      <button class="btn" title={t("sk.export_zip_hint")}
              onclick={() => saveUrl(`/api/skills/${skill.name}/export.zip`, `${skill.name}.zip`)}><Icon name="download" size={14} /> {t("sk.export_zip")}</button>
      <button class="btn" class:primary={!editable} onclick={copy}><Icon name="copy" size={14} /> {t("sk.copy")}</button>
    {/if}
  {/snippet}

  {#if error}<div class="pad"><div class="banner danger"><Icon name="warn" /><span class="grow">{error}</span></div></div>{/if}

  {#if list}
    <Panes screen="skills" wideOutline>
      {#snippet outline()}
        <div class="pane-body scroll">
          <nav class="list" aria-label={t("sk.title")}>
            {#each grouped as g (g.id)}
              <p class="cap g-title">{g.id === "broken" ? t("sk.broken") : t("sk.stage." + g.id)}</p>
              {#each g.skills as s (s.name + g.id)}
                {#if g.id === "broken" || !s.error}
                  {@const used = g.id !== "broken" && g.id !== "frd" && g.effective === s.name}
                  <button class="item" class:err={!!s.error} onclick={() => open(s.name)} aria-current={s.name === selected ? "true" : undefined}>
                    <b class="i-title trunc">{s.title}</b>
                    {#if used}<span class="status ok"><Icon name="check" size={12} /> {t("sk.in_use")}</span>{:else}<span></span>{/if}
                    <span class="sub">{s.error ? t("sk.broken") : s.builtin ? t("sk.builtin") : t("sk.custom")}</span>
                  </button>
                {/if}
              {/each}
            {/each}
          </nav>
        </div>
      {/snippet}

      {#if !skill || !draft}
        <div class="empty"><div class="glyph"><Icon name="skills" size={20} /></div><p>{t("sk.pick")}</p></div>
      {:else}
        {#key skill.name}
        <div class="editor">
          <div class="editor-head">
            <div class="e-title">
              {#if editable}
                <input class="input title-input" bind:value={draft.title} aria-label={t("sk.name")} />
              {:else}
                <h2>{skill.title}</h2>
              {/if}
              <p class="meta t3"><span class="mono">{skill.name}</span> · {t("sk.stage." + skill.stage)} · v{skill.version} · {skill.builtin ? t("sk.builtin") : t("sk.custom")}</p>
              {#if editable}
                <input class="input desc-input" id="sk-desc" bind:value={draft.description} placeholder={t("sk.description")} aria-label={t("sk.description")} />
              {:else if skill.description}
                <p class="t2 desc">{skill.description}</p>
              {/if}
            </div>
            {#if skill.error}<div class="banner danger"><Icon name="warn" /><span class="grow">{t("sk.error", { error: skill.error })}</span></div>
            {:else if !editable}<div class="banner info"><Icon name="lock" /><span class="grow">{t("sk.readonly")}</span>
              <button class="btn sm" onclick={copy}>{t("sk.copy")}</button></div>{/if}
          </div>

          <div class="tabs" role="tablist" aria-label={skill.title}>
            {#each tabs as k (k)}
              <button role="tab" id="sk-tab-{k}" class:narrow-tab={k === "usage"} aria-selected={tab === k} tabindex={tab === k ? 0 : -1}
                      aria-controls="sk-pane" onclick={() => (tab = k)} onkeydown={tabKey}>
                {t("sk.tab." + k)}
                {#if k === "sections" && draft.meta.sections}<span class="n">{draft.meta.sections.length}</span>{/if}
                {#if k === "history"}<span class="n">{skill.history.length}</span>{/if}
              </button>
            {/each}
          </div>

          <div class="pane-body scroll">
            <div class="tab-pane" id="sk-pane" role="tabpanel" aria-labelledby="sk-tab-{tab}">
              {#if tab === "instructions"}
                <p class="hint pane-hint">{t("sk.hint." + skill.stage)}</p>
                <div class="field">
                  <label class="field-l" for="sk-instr"><span>{t("sk.instructions")}</span>
                    {#if ["frd", "fix", "global", "quality"].includes(skill.stage)}<span class="t3 vars">{t("sk.vars")}</span>{/if}</label>
                  <textarea id="sk-instr" class="input code-area" rows="18" readonly={!editable}
                            bind:value={draft.instructions} spellcheck="false"></textarea>
                </div>
              {:else if tab === "sections"}
                <p class="hint pane-hint">{t("sk.sections_hint")}</p>
                <ol class="sections">
                  {#each draft.meta.sections as sec, i (i + sec.key)}
                    <li class="sec-row">
                      <div class="sec-head">
                        <span class="mono t3">{i + 1}. {sec.key}</span>
                        {#if REQUIRED.includes(sec.key) && draft.meta.requirements !== "none"}<span class="tag outline">{t("sk.sec.required")}</span>{/if}
                        {#if sec.format === "table"}<span class="tag fr" title={(sec.columns || []).map(c => titleOf(c, app.lang) || titleOf(c, "ru")).join(" | ")}>
                          {t("sk.sec.table", { n: (sec.columns || []).length })}</span>{/if}
                        <span class="spacer"></span>
                        {#if editable}
                          <button class="btn sm ghost" disabled={i === 0} onclick={() => move(i, -1)}>{t("bl.up")}</button>
                          <button class="btn sm ghost" disabled={i === draft.meta.sections.length - 1} onclick={() => move(i, 1)}>{t("bl.down")}</button>
                          {#if !REQUIRED.includes(sec.key)}
                            <button class="btn sm ghost danger" onclick={() => draft.meta.sections.splice(i, 1)}>{t("sk.sec.remove")}</button>
                          {/if}
                        {/if}
                      </div>
                      <div class="sec-fields">
                        <input class="input" placeholder={t("sk.sec.title_ru")} aria-label={t("sk.sec.title_ru")} readonly={!editable}
                               value={titleOf(sec.title, "ru")} oninput={e => setTitle(sec, "ru", e.currentTarget.value)} />
                        <input class="input" placeholder={t("sk.sec.title_en")} aria-label={t("sk.sec.title_en")} readonly={!editable}
                               value={titleOf(sec.title, "en")} oninput={e => setTitle(sec, "en", e.currentTarget.value)} />
                      </div>
                      {#if sec.format === "table"}
                        <p class="hint cols">{t("sk.sec.columns")}: {(sec.columns || []).map(c => titleOf(c, app.lang) || titleOf(c, "ru")).join(" · ")}</p>
                      {/if}
                      {#if !KINDS.includes(sec.key)}
                        <textarea class="input area" rows="2" placeholder={t("sk.sec.instructions")} aria-label={t("sk.sec.instructions")}
                                  readonly={!editable} bind:value={sec.instructions}></textarea>
                      {/if}
                    </li>
                  {/each}
                </ol>
                {#if editable}
                  <button class="btn btn-sm" onclick={addSection}><Icon name="plus" size={14} /> {t("sk.sec.add")}</button>
                {/if}
              {:else if tab === "rules"}
                <p class="field-l">{t("sk.vague")}</p>
                <p class="hint pane-hint">{t("sk.vague_hint")}</p>
                <div class="grid-2 vague">
                  {#each ["ru", "en"] as lang (lang)}
                    <div class="field">
                      <label class="label" for="sk-vague-{lang}">{lang === "ru" ? "Русский" : "English"}</label>
                      <textarea class="input area" id="sk-vague-{lang}" rows="3" readonly={!editable} value={words(lang)}
                                onchange={e => setWords(lang, e.currentTarget.value)}></textarea>
                    </div>
                  {/each}
                </div>
                <p class="field-l rules-t">{t("sk.rules")} <span class="t3 num">{(draft.meta.rules || []).length}</span></p>
                <ul class="rules">
                  {#each draft.meta.rules || [] as rule, i (i)}
                    <li class="rule">
                      <div class="sec-fields">
                        <input class="input code" placeholder={t("sk.rule.id")} aria-label={t("sk.rule.id")} readonly={!editable} bind:value={rule.id} />
                        <input class="input" placeholder={t("sk.rule.title")} aria-label={t("sk.rule.title")} readonly={!editable} bind:value={rule.title} />
                        {#if editable}<button class="btn sm ghost danger" onclick={() => draft.meta.rules.splice(i, 1)}>{t("sk.rule.remove")}</button>{/if}
                      </div>
                      <textarea class="input area" rows="2" placeholder={t("sk.rule.description")} aria-label={t("sk.rule.description")}
                                readonly={!editable} bind:value={rule.description}></textarea>
                    </li>
                  {/each}
                </ul>
                {#if editable}<button class="btn btn-sm" onclick={addRule}><Icon name="plus" size={14} /> {t("sk.rule.add")}</button>{/if}
              {:else if tab === "template"}
                <p class="field-l">{t("sk.template")}</p>
                {#if !editable}<p class="hint pane-hint">{t("sk.template_builtin")}</p>{/if}
                <div class="actions">
                  <button class="btn" onclick={() => saveUrl(`/api/skills/${skill.name}/template.docx`, `${skill.name}.docx`)}>
                    <Icon name="download" size={14} /> {t("sk.template_download")}</button>
                  {#if editable}
                    {#if desktop}<button class="btn btn-primary" onclick={() => reveal("template")}>{t("sk.template_open")}</button>{/if}
                    <input type="file" accept=".docx" class="hidden" bind:this={templateInput} onchange={uploadTemplate} aria-label={t("sk.template_upload")} />
                    <button class="btn" onclick={() => templateInput.click()}><Icon name="upload" size={14} /> {t("sk.template_upload")}</button>
                  {/if}
                </div>
                <div class="field num-field">
                  <label class="label" for="sk-num">{t("sk.numbering")}</label>
                  <select class="select" id="sk-num" disabled={!editable} bind:value={draft.meta.numbering}>
                    <option value="dot">{t("sk.numbering.dot")}</option>
                    <option value="plain">{t("sk.numbering.plain")}</option>
                  </select>
                </div>
                <p class="field-l ph-t">{t("sk.placeholders")}</p>
                <p class="hint pane-hint">{t("sk.placeholders_hint")}</p>
                <table class="table ph"><tbody>
                  {#each skill.placeholders || [] as ph (ph.code)}
                    <tr><td class="mono">{ph.code}</td><td>{ph.label}</td></tr>
                  {/each}
                </tbody></table>
              {:else if tab === "try"}
                <p class="hint pane-hint">{t("sk.try_hint." + tryMode)}</p>
                {#if tryMode === "export"}
                  <button class="btn" onclick={exportSample}><Icon name="download" size={14} /> {t("sk.try_export")}</button>
                {:else}
                  <div class="row">
                    {#if tryMode === "source"}
                      <div class="field grow">
                        <label class="label" for="sk-src">{t("sk.try_source")}</label>
                        {#if readySources.length}
                          <select class="select" id="sk-src" bind:value={trySource}>
                            {#each readySources as s (s.id)}<option value={s.id}>{s.title}</option>{/each}
                          </select>
                        {:else}<p class="muted">{t("sk.try_none")}</p>{/if}
                      </div>
                    {/if}
                    <button class="btn btn-primary" disabled={tryState?.running || (tryMode === "source" && !trySource)}
                            onclick={runTry}>{#if tryState?.running}<span class="spinner"></span>{/if}{t("sk.try_run")}</button>
                  </div>
                  {#if tryState?.running}
                    <p class="hint" style="margin-top: var(--sp-4)">{tryState.message}</p>
                    {#if tryState.partial}<div class="md result">{@html renderMarkdown(tryState.partial)}</div>{/if}
                  {:else if tryState?.result}
                    {@const r = tryState.result}
                    <div class="result">
                      {#if r.kind === "markdown"}
                        <div class="md">{@html renderMarkdown(r.text)}</div>
                      {:else if r.kind === "atoms"}
                        {#if r.compare && r.compare.current}
                          <div class="compare">
                            <p><b>{t("sk.cmp_title", { n: r.compare.current })}</b> · {t("sk.cmp_same", { n: r.compare.same })}</p>
                            {#if r.compare.new.length}<p class="cmp-h ok">+ {t("sk.cmp_new", { n: r.compare.new.length })}</p>
                              <ul>{#each r.compare.new as x, i (i)}<li>{x}</li>{/each}</ul>{/if}
                            {#if r.compare.missing.length}<p class="cmp-h danger">− {t("sk.cmp_missing", { n: r.compare.missing.length })}</p>
                              <ul>{#each r.compare.missing as x, i (i)}<li>{x}</li>{/each}</ul>{/if}
                          </div>
                        {/if}
                        <p class="label">{t("sk.try_atoms", { n: r.atoms.length })}{#if r.dropped} · {t("sk.try_dropped", { n: r.dropped })}{/if}</p>
                        <ul class="try-atoms">
                          {#each r.atoms as a, i (i)}
                            <li><span class="type {typeClass[a.type]}">{PREFIX[a.type]}</span> <span class="st">{a.statement}</span>
                              {#each a.evidence as ev, j (j)}<span class="quote">«{ev.quote}»</span>{/each}</li>
                          {/each}
                        </ul>
                        {#if r.skipped?.length}
                          <p class="label">{t("sk.try_skipped")}: {r.skipped.length}</p>
                          <ul class="try-atoms skipped">
                            {#each r.skipped as x, i (i)}<li><span class="tag outline">{t("sk.skip." + x.type)}</span> {x.statement}</li>{/each}
                          </ul>
                        {/if}
                      {:else if r.kind === "document"}
                        {#each r.content.sections as sec (sec.key)}
                          <h4>{sec.number}. {sec.title}</h4>
                          {#each [...sec.blocks, ...(sec.subsections || []).flatMap(sub => [{ kind: "sub", text: `${sub.number} ${sub.title}` }, ...sub.blocks])] as b, i (i)}
                            {#if b.kind === "sub"}<h5>{b.text}</h5>
                            {:else if b.kind === "req"}<p><b class="mono">{b.id}</b> {b.text}
                              {#each b.issues || [] as is, k (k)}<span class="tag warn">{r.content.rule_titles?.[is.rule] || t("doc.rule." + is.rule)}: {is.message}</span>{/each}</p>
                            {:else if b.kind === "text"}<p>{b.text}</p>
                            {:else if b.kind === "list"}<ul>{#each b.items as it, k (k)}<li>{it}</li>{/each}</ul>{/if}
                          {/each}
                        {/each}
                      {/if}
                    </div>
                  {/if}
                {/if}
              {:else if tab === "contract"}
                <p class="hint pane-hint">{t("sk.contract_hint")}</p>
                {#if skill.contract}<pre class="contract">{skill.contract}</pre>{:else}<p class="muted">{t("sk.no_contract")}</p>{/if}
              {:else if tab === "usage"}
                {@render usage()}
              {:else if tab === "history"}
                {#if !skill.history.length}<p class="muted">{t("sk.history_empty")}</p>{/if}
                <ul class="history">
                  {#each skill.history as h (h.id)}
                    <li>
                      <span class="num">{fmtDate(h.at, app.lang)}</span>
                      <span class="tag outline">{h.kind === "template" ? t("sk.history_template") : t("sk.history_text")}</span>
                      <span class="spacer"></span>
                      {#if h.kind === "text"}<button class="btn btn-ghost btn-sm" onclick={() => showHistory(h)}>{t("sk.show")}</button>{/if}
                      <button class="btn btn-sm" onclick={() => restore(h)}>{t("sk.restore")}</button>
                    </li>
                    {#if historyText?.id === h.id}<li class="h-text"><pre class="contract">{historyText.text}</pre></li>{/if}
                  {/each}
                </ul>
              {/if}
            </div>
          </div>

          {#if editable && dirty}
            <div class="pane-foot savebar">
              <span class="t2">{t("sk.unsaved")}</span>
              <span class="grow"></span>
              <button class="btn ghost" onclick={() => loadSkill(skill.name)}>{t("sk.revert")}</button>
              <button class="btn primary" disabled={saving} onclick={save}>{#if saving}<span class="spinner"></span>{/if}{t("sk.save")} <span class="kbd">⌘S</span></button>
            </div>
          {/if}
        </div>
        {/key}
      {/if}

      {#snippet inspector()}
        {#if skill && !skill.error}
          <div class="pane-head"><h2 class="grow trunc">{t("sk.tab.usage")}</h2></div>
          <div class="pane-body scroll"><div class="insp-body">
            {@render usage()}
            {#if editable}
              <div class="insp-sec manage">
                <p class="cap">{t("sk.files")}</p>
                {#if desktop}<button class="btn sm" onclick={() => reveal("folder")}>{t("sk.folder")}</button>{/if}
                <button class="btn sm ghost danger" onclick={remove}><Icon name="trash" size={14} /> {t("sk.delete")}…</button>
              </div>
            {/if}
          </div></div>
        {/if}
      {/snippet}
    </Panes>
  {/if}
</Page>

{#snippet usage()}
  {#if stageInfo && skill.stage === "frd"}
    <div class="usage">
      <p class="cap">{t("sk.u.doc_type")}</p>
      <p class="t2">{t("sk.doc_type_hint")}</p>
      <div><button class="btn primary" onclick={() => go(`/document/new/${skill.name}`)}>{t("sk.doc_type_create")}</button></div>
    </div>
  {:else if stageInfo}
    {@const here = stageInfo.effective === skill.name}
    {@const pinnedHere = stageInfo.project === skill.name}
    {@const isDefault = stageInfo.global === skill.name}
    <div class="usage">
      <p class="cap">{t("sk.u.title", { stage: t("sk.stage." + skill.stage) })}</p>
      <div class="u-row">
        <span class="ring" class:done={here}></span>
        <div class="grow">
          <b>{t("sk.u.this_project", { name: currentProject()?.name || "" })}</b>
          <p class="t3">{#if here && pinnedHere}{t("sk.u.here_pinned")}{:else if here}{t("sk.u.here_default")}{:else}{t("sk.u.here_other", { name: titleOf2(stageInfo.effective) })}{/if}</p>
          {#if pinnedHere}
            <button class="btn sm" onclick={() => useForProject(false)}>{t("sk.u.unpin", { name: titleOf2(stageInfo.global) })}</button>
          {:else if !here}
            <button class="btn sm primary" onclick={() => useForProject(true)}>{t("sk.u.use_here")}</button>
          {/if}
        </div>
      </div>
      <div class="u-row">
        <span class="ring" class:done={isDefault}></span>
        <div class="grow">
          <b>{t("sk.u.others")}</b>
          <p class="t3">{isDefault ? t("sk.u.is_default") : t("sk.u.default_is", { name: titleOf2(stageInfo.global) })}</p>
          {#if !isDefault}<button class="btn sm" onclick={useGlobally}>{t("sk.u.make_default")}</button>{/if}
        </div>
      </div>
    </div>
  {/if}
{/snippet}

<style>
  .pad { padding: var(--s-5) var(--gutter); }
  .list { padding: var(--s-4) var(--s-4) var(--s-9); display: grid; gap: 1px; align-content: start; grid-template-columns: minmax(0, 1fr); }
  .g-title { padding: var(--s-6) var(--s-4) var(--s-3); }
  .g-title:first-child { padding-top: var(--s-3); }
  .item { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: 0 var(--s-4); min-height: 44px; padding: var(--s-3) var(--s-4);
    border: 0; background: none; border-radius: var(--r-sm); text-align: left; width: 100%; cursor: pointer; }
  .item:hover { background: var(--c-fill-1); } .item[aria-current="true"] { background: var(--c-fill-2); }
  .item b { font-weight: var(--w-medium); }
  .item .sub { grid-column: 1 / -1; font-size: var(--t-foot); color: var(--c-text-3); }
  .item.err b { color: var(--c-danger); }

  .editor { display: flex; flex-direction: column; min-height: 0; height: 100%; }
  .editor-head { padding: var(--s-7) var(--gutter) var(--s-5); display: grid; gap: var(--s-5); flex: none; grid-template-columns: minmax(0, 1fr); }
  .e-title { display: grid; gap: var(--s-3); grid-template-columns: minmax(0, 1fr); }
  .e-title h2, .title-input { font: var(--w-semibold) var(--t-title-1)/var(--lh-title-1) var(--font-display); letter-spacing: -.016em; }
  .title-input { height: 36px; max-width: 720px; }
  .desc-input { max-width: 880px; }
  .desc { max-width: var(--w-measure); }
  .meta { font-size: var(--t-foot); }
  .tab-pane { padding: var(--s-6) var(--gutter) var(--s-11); display: grid; gap: var(--s-5); align-content: start; grid-template-columns: minmax(0, 1fr); max-width: 1200px; }
  @container ws (min-width: 1200px) { .narrow-tab { display: none !important; } }
  .savebar { background: var(--c-toolbar); }

  .tab-pane :global(.field-l) { font-weight: var(--w-semibold); display: flex; align-items: baseline; gap: var(--s-4); justify-content: space-between; }
  .tab-pane :global(.vars) { font-weight: var(--w-regular); font-size: var(--t-foot); }
  .tab-pane :global(.code-area) { font: var(--w-regular) 12.5px/20px var(--font-mono); padding: var(--s-6); border-radius: var(--r-md); background: var(--c-pane);
    border-color: var(--c-line); max-width: 110ch; tab-size: 2; resize: vertical; }
  .tab-pane :global(.code-area:focus) { border-color: var(--c-focus); background: var(--c-content); }
  .sections, .rules, .history, .try-atoms { list-style: none; margin: 0; padding: 0; display: grid; gap: 0; grid-template-columns: minmax(0, 1fr); }
  .sec-row, .rule { display: grid; gap: var(--s-3); padding: var(--s-5) 0; border-bottom: 1px solid var(--c-line); grid-template-columns: minmax(0, 1fr); }
  .sec-head { display: flex; align-items: center; gap: var(--s-4); flex-wrap: wrap; }
  .spacer { flex: 1; }
  .sec-fields { display: flex; gap: var(--s-4); flex-wrap: wrap; align-items: center; }
  .sec-fields .input { flex: 1 1 220px; }
  .cols { margin: 0; }
  .vague { display: grid; gap: var(--s-5); grid-template-columns: repeat(auto-fit, minmax(min(100%, 320px), 1fr)); }
  .rules-t { margin-top: var(--s-5); }
  .num-field { max-width: 320px; }
  .ph-t { margin-top: var(--s-5); }
  .ph { max-width: 880px; }
  .ph :global(td) { height: 32px; }
  .result { display: grid; gap: var(--s-4); grid-template-columns: minmax(0, 1fr); padding: var(--s-6); border-radius: var(--r-lg); background: var(--c-pane);
    box-shadow: inset 0 0 0 1px var(--c-line); max-width: 110ch; }
  .result h4 { font: var(--w-semibold) var(--t-title-3)/var(--lh-title-3) var(--font-display); margin-top: var(--s-4); }
  .result h5 { font: var(--w-semibold) var(--t-body)/var(--lh-body) var(--font); margin: var(--s-3) 0 0; }
  .result p { line-height: 20px; }
  .try-atoms li { padding: var(--s-4) 0; border-bottom: 1px solid var(--c-line); line-height: 20px; }
  .try-atoms .st { font-weight: var(--w-medium); }
  .try-atoms .quote { display: block; color: var(--c-text-2); }
  .skipped li { color: var(--c-text-2); }
  .compare { padding: var(--s-5); border-radius: var(--r-md); background: var(--c-fill-1); display: grid; gap: var(--s-2); }
  .compare ul { margin: 0; padding-left: var(--s-7); }
  .cmp-h { font-weight: var(--w-semibold); }
  .cmp-h.ok { color: var(--c-ok); } .cmp-h.danger { color: var(--c-danger); }
  .contract { font: var(--w-regular) 12.5px/20px var(--font-mono); padding: var(--s-6); border-radius: var(--r-md); background: var(--c-pane);
    box-shadow: inset 0 0 0 1px var(--c-line); white-space: pre-wrap; margin: 0; max-width: 110ch; overflow-x: auto; }
  .history li { display: flex; align-items: center; gap: var(--s-4); padding: var(--s-4) 0; border-bottom: 1px solid var(--c-line); flex-wrap: wrap; }
  .history .h-text { border-bottom: 0; }
  .usage { display: grid; gap: var(--s-5); grid-template-columns: minmax(0, 1fr); }
  .u-row { display: flex; gap: var(--s-5); align-items: flex-start; }
  .u-row .ring { margin-top: 2px; }
  .u-row b { font-weight: var(--w-medium); }
  .u-row .btn { margin-top: var(--s-3); }
  .manage { justify-items: start; }
</style>
