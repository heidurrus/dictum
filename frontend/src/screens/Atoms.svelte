<script>
  import { keyOf } from "../lib/keys.js";
  import Icon from "../components/Icon.svelte";
  import Page from "../components/Page.svelte";
  import Panes from "../components/Panes.svelte";
  import PopMenu from "../components/PopMenu.svelte";
  import SourceContext from "../components/SourceContext.svelte";
  import OpenItems from "../components/OpenItems.svelte";
  import AtomInspector from "../components/AtomInspector.svelte";
  import { api, pollJob } from "../lib/api.js";
  import { extractAtoms } from "../lib/atoms.js";
  import { explain } from "../lib/errors.js";
  import { fmtTime, speakerDisplay } from "../lib/format.js";
  import { app, t, go, toast, loadSources, writePref } from "../lib/state.svelte.js";
  import { SvelteSet } from "svelte/reactivity";

  let atoms = $state([]);
  let stats = $state(null);
  let conflicts = $state([]);
  let loaded = $state(false);
  let error = $state("");

  // Filters are remembered per project (PM-18): "accepted" in one project mustn't hide the next one's queue.
  function readFilters(pid) {
    try { return (JSON.parse(localStorage.getItem("wb.atoms.filters")) || {})[pid] || {}; } catch (_) { return {}; }
  }
  let statusFilter = $state("all");      // pending | accepted | rejected | conflicts | all
  let typeFilter = $state("all");
  let groupBy = $state("none");
  let search = $state("");
  let tab = $state("atoms");
  let autoFilter = true;                 // no stored choice yet: open on what waits for review
  $effect(() => {
    const f = readFilters(app.currentProjectId);
    autoFilter = !f.status;
    statusFilter = f.status || "all"; typeFilter = f.type || "all"; groupBy = f.group || "none";
  });
  function setStatus(f) { statusFilter = f; autoFilter = false; }
  $effect(() => {
    let all = {};
    try { all = JSON.parse(localStorage.getItem("wb.atoms.filters")) || {}; } catch (_) { /* private mode */ }
    all[app.currentProjectId] = { status: statusFilter, type: typeFilter, group: groupBy };
    writePref("atoms.filters", all);
  });

  let selectedId = $state(null);
  let editingId = $state(null);
  let busy = $state(false);

  async function load() {
    const pid = app.currentProjectId;
    try {
      const [a, c] = await Promise.all([api(`/api/projects/${pid}/atoms`), api(`/api/projects/${pid}/conflicts`)]);
      if (pid !== app.currentProjectId) return;
      atoms = a.atoms;
      stats = a.stats;
      conflicts = c.conflicts;
      error = "";
      if (autoFilter) { autoFilter = false; statusFilter = a.stats?.pending ? "pending" : "all"; }
    } catch (err) {
      error = err.message;
    } finally {
      loaded = true;
    }
  }

  // Reload on project switch and whenever an extraction finishes.
  $effect(() => { app.currentProjectId; app.atomsVersion; load(); });

  const sourceFilter = $derived(app.route.source || null);
  const sourceFilterTitle = $derived(app.sources.find(s => s.id === sourceFilter)?.title || "");
  const needle = $derived(search.trim().toLowerCase());
  const byStatus = (a, f) => f === "all" || (f === "conflicts" ? a.conflicts.length > 0 : a.status === f);
  // Source and search narrow everything; the status and type counts are taken inside them, so a count
  // always equals the number of rows that choice will show.
  const scoped = $derived(atoms.filter(a =>
    (!sourceFilter || a.evidence.some(e => e.source_id === sourceFilter)) &&
    (!needle || a.statement.toLowerCase().includes(needle) || a.evidence.some(e => e.quote.toLowerCase().includes(needle)))));
  const filtered = $derived(scoped.filter(a => byStatus(a, statusFilter) && (typeFilter === "all" || a.type === typeFilter)));
  // Grouping (PM-18): by source or speaker; the list order follows the groups so J/K walk them in order.
  const groups = $derived.by(() => {
    if (groupBy === "none") return [{ key: "", title: "", items: filtered }];
    const out = new Map();
    for (const a of filtered) {
      const e = a.evidence[0] || {};
      const key = groupBy === "source" ? (e.source_id || "—") : (e.speaker_name || e.speaker || "—");
      const title = groupBy === "source" ? (e.source_title || t("at.no_source")) : (e.speaker ? speakerDisplay(e.speaker, e.speaker_name, t) : t("at.no_speaker"));
      if (!out.has(key)) out.set(key, { key, title, items: [] });
      out.get(key).items.push(a);
    }
    return [...out.values()];
  });
  const visible = $derived(groups.flatMap(g => g.items));
  const focused = $derived(visible.find(a => a.id === selectedId) || null);
  const inConflict = $derived(atoms.filter(a => a.conflicts.length).length);
  const manySources = $derived(new Set(atoms.flatMap(a => a.evidence.map(e => e.source_id))).size > 1);
  const readySources = $derived(app.sources.filter(s => s.status === "ready"));
  const statementOf = $derived(Object.fromEntries(atoms.map(a => [a.id, a.statement])));
  const openConflicts = $derived(conflicts.filter(c => c.status === "open"));

  // Opened from a transcript line or a document: show that atom, whatever the filters were.
  let routedAtom = null;
  $effect(() => {
    const target = app.route.atom;
    if (!target || !loaded || routedAtom === target || !atoms.some(a => a.id === target)) return;
    routedAtom = target;
    statusFilter = "all"; typeFilter = "all"; search = ""; tab = "atoms";
    requestAnimationFrame(() => select(target));
  });

  $effect(() => {
    // Keep a valid selection while the list changes under the filters.
    if (!visible.length) selectedId = null;
    else if (!visible.some(a => a.id === selectedId)) selectedId = visible[0].id;
  });

  function select(id, scroll = true) {
    selectedId = id;
    editingId = null;
    if (scroll) requestAnimationFrame(() => document.getElementById(`atom-${id}`)?.scrollIntoView({ block: "nearest" }));
  }
  function pick(id) {                     // a click: on a narrow window it also slides the inspector in
    select(id, false);
    const ws = document.querySelector(".workspace");
    if (ws && ws.clientWidth < 900) app.inspectorOverlay = true;
  }

  async function patch(atom, body) {
    const updated = await api(`/api/atoms/${atom.id}`, { method: "PATCH", body });
    stats = updated.stats;
    const { stats: _, ...fresh } = updated;
    atoms = atoms.map(a => (a.id === atom.id ? { ...a, ...fresh } : a));
    // Answering a conflict's question closes the conflict: refresh the flags on both atoms.
    if (atom.type === "question" && body.status && conflicts.some(c => c.question_atom === atom.id)) await load();
    return fresh;
  }

  // Buttons toggle (clicking again takes the decision back); keys only set it.
  async function decide(atom, status, { toggle = true } = {}) {
    const previous = atom.status;
    const next = toggle && previous === status ? "pending" : status;
    // Move on to the next atom still to review right away, so fast keyboard review never lands twice on one atom.
    const i = visible.findIndex(a => a.id === atom.id);
    const others = visible.filter(a => a.id !== atom.id && a.status === "pending");
    const after = next === "pending" ? null
      : visible.slice(i + 1).find(a => a.status === "pending") || others[0] || visible[i + 1];
    if (after) select(after.id);
    if (next === previous) return;
    try {
      await patch(atom, { status: next });
      if (next !== "pending") {
        toast(t(next === "accepted" ? "at.accepted_toast" : "at.rejected_toast"), {
          action: t("at.undo"), onAction: () => patch(atom, { status: previous }).then(() => select(atom.id)) });
      }
    } catch (err) {
      select(atom.id);
      toast(err.message, { kind: "danger" });
    }
  }

  // ── bulk review: check atoms, then accept / reject / retype them together ──
  const checked = new SvelteSet();
  let anchorId = null;                    // for shift-click ranges
  let bulkBusy = $state(false);
  $effect(() => { app.currentProjectId; checked.clear(); });
  const checkedVisible = $derived(visible.filter(a => checked.has(a.id)));
  const allChecked = $derived(visible.length > 0 && checkedVisible.length === visible.length);
  const checkedInConflict = $derived(checkedVisible.filter(a => a.conflicts.length).length);
  const sourcesWithAtoms = $derived(app.sources.filter(s => s.atom_count));

  function toggleCheck(atom, shift = false) {
    const on = !checked.has(atom.id);
    if (shift && anchorId) {
      const a = visible.findIndex(x => x.id === anchorId), b = visible.findIndex(x => x.id === atom.id);
      if (a >= 0 && b >= 0) {
        for (const x of visible.slice(Math.min(a, b), Math.max(a, b) + 1)) on ? checked.add(x.id) : checked.delete(x.id);
        anchorId = atom.id;
        return;
      }
    }
    on ? checked.add(atom.id) : checked.delete(atom.id);
    anchorId = atom.id;
  }
  function toggleAll() {
    if (allChecked) for (const a of visible) checked.delete(a.id);
    else for (const a of visible) checked.add(a.id);
  }

  async function bulk(change, { skipConflicts = false } = {}) {
    const pool = skipConflicts ? checkedVisible.filter(a => !a.conflicts.length) : checkedVisible;
    const targets = pool.filter(a => Object.entries(change).some(([k, v]) => (a[k] ?? null) !== v));
    if (!targets.length) { checked.clear(); return; }
    const before = targets.map(a => ({ id: a.id, status: a.status, type: a.type, priority: a.priority || null,
                                       reject_reason: a.reject_reason || null }));
    bulkBusy = true;
    try {
      const r = await bulkSend(targets.map(a => ({ id: a.id, ...change })));
      checked.clear();
      toast(t("at.bulk_done", { n: r.changed.length }), { action: t("at.undo"), ms: 10000, onAction: async () => {
        const undo = before.filter(b => r.changed.includes(b.id)).map(b => ({ id: b.id,
          ...(change.status ? { status: b.status } : {}), ...(change.type ? { type: b.type } : {}),
          ...("priority" in change ? { priority: b.priority } : {}),
          ...(change.status || "reject_reason" in change ? { reject_reason: b.reject_reason } : {}) }));
        await bulkSend(undo);
      } });
    } catch (err) {
      toast(err.message, { kind: "danger" });
    } finally {
      bulkBusy = false;
    }
  }
  async function bulkSend(items) {
    const r = await api(`/api/projects/${app.currentProjectId}/atoms/bulk`, { method: "POST", body: { items } });
    const byId = Object.fromEntries(items.map(i => [i.id, i]));
    atoms = atoms.map(a => (r.changed.includes(a.id) ? { ...a, ...byId[a.id] } : a));
    stats = r.stats;
    // Accepting questions may have closed conflicts: refresh those flags.
    if (items.some(i => i.status === "accepted") && conflicts.some(c => c.question_atom && r.changed.includes(c.question_atom))) await load();
    return r;
  }

  // Delete (with undo): gone from the list, the counters and the next document build.
  async function removeAtoms(list) {
    if (!list.length) return;
    const ids = list.map(a => a.id);
    const i = visible.findIndex(a => a.id === ids[0]);
    try {
      const r = await api(`/api/projects/${app.currentProjectId}/atoms/delete`, { method: "POST", body: { ids } });
      stats = r.stats;
      atoms = atoms.filter(a => !r.deleted.includes(a.id));
      for (const id of r.deleted) checked.delete(id);
      const next = visible[Math.min(i, visible.length - 1)];
      if (next) select(next.id);
      if (conflicts.length) load();
      loadSources();
      toast(t("at.deleted", { n: r.deleted.length }), { action: t("at.undo"), ms: 10000, onAction: async () => {
        await api(`/api/projects/${app.currentProjectId}/atoms/restore`, { method: "POST", body: { ids: r.deleted } });
        await load();
        loadSources();
      } });
    } catch (err) { toast(err.message, { kind: "danger" }); }
  }

  function startEdit(atom) {
    selectedId = atom.id;
    editingId = atom.id;
    const ws = document.querySelector(".workspace");
    if (ws && ws.clientWidth < 900) app.inspectorOverlay = true;
    else if (app.inspector.atoms === false) app.inspector = { ...app.inspector, atoms: true };
  }

  async function saveEdit(atom, statement) {
    editingId = null;
    if (statement.trim() === atom.statement) return;
    try { await patch(atom, { statement }); } catch (err) { toast(err.message, { kind: "danger" }); }
  }
  async function patchProps(atom, body) {
    try { await patch(atom, body); } catch (err) { toast(err.message, { kind: "danger" }); }
  }

  async function resolve(conflict, action, statement) {
    busy = true;
    try {
      const r = await api(`/api/conflicts/${conflict.id}/resolve`, { method: "POST", body: { action, statement } });
      toast(t(r.status === "awaiting_answer" ? "at.question_toast" : "at.resolved_toast"));
      await load();
      loadSources();
    } catch (err) {
      toast(err.message, { kind: "danger" });
    } finally {
      busy = false;
    }
  }

  async function setPriority(atom, priority) {
    try { await patch(atom, { priority: priority || "" }); } catch (err) { toast(err.message, { kind: "danger" }); }
  }
  async function setReason(atom, reason) {
    try { await patch(atom, { reject_reason: reason || "" }); } catch (err) { toast(err.message, { kind: "danger" }); }
  }

  // Re-type existing atoms with the AI (business / risk / as-is appeared in 3.3), one undo for all.
  let reclassifying = $state(null);          // {progress, message}
  const hasNewTypes = $derived(atoms.some(a => ["business", "risk", "current"].includes(a.type)));
  let reclassifyHidden = $state(false);
  async function reclassify() {
    reclassifying = { progress: 0, message: "" };
    try {
      const { job_id } = await api(`/api/projects/${app.currentProjectId}/atoms/reclassify`, { method: "POST" });
      const job = await pollJob(job_id, j => (reclassifying = { progress: j.progress || 0, message: j.progress_msg || "" }));
      const changes = job.result.changes;
      await load();
      if (!changes.length) { toast(t("at.rc.none")); return; }
      const by = {};
      for (const c of changes) by[c.to] = (by[c.to] || 0) + 1;
      toast(t("at.rc.done", { n: changes.length }) + ": " + Object.entries(by).map(([k, n]) => `${t("at.f." + k)} ${n}`).join(" · "),
            { action: t("at.undo"), ms: 20000, onAction: async () => {
              await bulkSend(changes.map(c => ({ id: c.id, type: c.from })));
            } });
    } catch (err) {
      const e = explain(err);
      toast(e.message, { kind: "danger", ...(e.setup ? { action: t("err.open_settings"), onAction: () => go("/settings") } : {}) });
    } finally { reclassifying = null; }
  }

  // ＋ Атом: the BA's own requirement (PM-16)
  let adding = $state(null);
  async function addAtom() {
    try {
      const r = await api(`/api/projects/${app.currentProjectId}/atoms`, { method: "POST", body: adding });
      adding = null;
      stats = r.stats;
      await load();
      select(r.id);
      toast(t("at.added"));
    } catch (err) { toast(err.message, { kind: "danger" }); }
  }

  // Steer by review (bet 4.3): rules proposed from repeated decisions
  let suggestions = $state([]);
  let showRule = $state(null);
  async function loadSuggestions() {
    try { suggestions = (await api(`/api/projects/${app.currentProjectId}/suggestions?lang=${app.lang}`)).suggestions; }
    catch (_) { suggestions = []; }
  }
  $effect(() => { app.currentProjectId; stats; loadSuggestions(); });
  let dismissedRules = $state(new Set());
  async function applyRule(sg) {
    try {
      const r = await api(`/api/projects/${app.currentProjectId}/suggestions/apply`, { method: "POST", body: { rule: sg.rule, lang: app.lang } });
      dismissedRules = new Set([...dismissedRules, sg.id]);
      toast(t("at.rule_added"), { action: t("nav.skills"), onAction: () => go(`/skills/${r.skill}`) });
    } catch (err) { toast(err.message, { kind: "danger" }); }
  }
  const shownSuggestions = $derived(suggestions.filter(s => !dismissedRules.has(s.id)));

  function onKey(e) {
    const key = keyOf(e);
    if (app.route.name !== "atoms" || tab !== "atoms" || app.palette
        || e.target.closest("textarea, select, [contenteditable], input:not([type=checkbox]), .menu")) return;
    const onCheckbox = e.target.matches?.("input[type=checkbox]");     // shortcuts still work after ticking a box
    if ((e.metaKey || e.ctrlKey) && key.toLowerCase() === "a") {   // select every atom under the filters
      e.preventDefault();
      for (const a of visible) checked.add(a.id);
      return;
    }
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const i = visible.findIndex(a => a.id === selectedId);
    const atom = visible[i];
    if (key === " " && onCheckbox) return;                          // Space toggles the focused box itself
    if (key === " " && atom) toggleCheck(atom, e.shiftKey);
    else if (key === "Escape" && checked.size) checked.clear();
    else if (key === "j" || key === "ArrowDown") { if (visible[i + 1]) select(visible[i + 1].id); }
    else if (key === "k" || key === "ArrowUp") { if (i > 0) select(visible[i - 1].id); }
    else if (key === "a" && atom) decide(atom, "accepted", { toggle: false });
    else if (key === "x" && atom) decide(atom, "rejected", { toggle: false });
    else if (key === "e" && atom) startEdit(atom);
    else if (key === "/") document.getElementById("at-search")?.focus();
    else if (["1", "2", "3", "4", "0"].includes(key) && (checkedVisible.length || atom)) {
      const p = { 1: "must", 2: "should", 3: "could", 4: "wont", 0: "" }[key];
      if (checkedVisible.length) bulk({ priority: p || null });
      else setPriority(atom, p);
    }
    else if ((key === "Delete" || key === "Backspace") && (checkedVisible.length || atom))
      removeAtoms(checkedVisible.length ? checkedVisible : [atom]);
    else return;
    e.preventDefault();
  }

  const PREFIX = { functional: "FR", nfr: "NFR", question: "Q", business: "BR", risk: "RSK", current: "AS" };
  const codeOf = $derived(Object.fromEntries(atoms.map(a => [a.id, a.rid || PREFIX[a.type]])));
  const evSource = ev => (ev ? ev.source_title : "");
  const evSpeaker = ev => (ev?.speaker ? speakerDisplay(ev.speaker, ev.speaker_name, t) : "");

  // The scope row (prototype-v5): На проверку / Принятые / Все, rejected only while there are some; conflicts are a chip.
  const SEGS = ["pending", "accepted", "rejected", "all"];
  // business → BRD, functional/nfr → SRS, risk → risk register, current → As-Is, questions everywhere
  const ALL_TYPES = ["business", "functional", "nfr", "risk", "current", "question"];
  const typeClass = { functional: "fr", nfr: "nfr", question: "q", business: "br", risk: "rsk", current: "as" };
  const REASONS = ["not_requirement", "duplicate", "out_of_scope", "wrong", "other"];
  const PRIOS = ["must", "should", "could", "wont"];
  const openQuestions = $derived(atoms.filter(a => a.type === "question" && a.status !== "rejected" && a.q_state !== "answered").length);
  const statusCount = f => scoped.filter(a => byStatus(a, f) && (typeFilter === "all" || a.type === typeFilter)).length;
  const typeCount = ty => scoped.filter(a => byStatus(a, statusFilter) && a.type === ty).length;
  const narrowed = $derived([
    sourceFilter ? t("at.nf.source", { title: sourceFilterTitle || "…" }) : "",
    typeFilter !== "all" ? t("at.nf.type", { type: t("at.full." + typeFilter) }) : "",
    needle ? t("at.nf.search", { q: search.trim() }) : "",
    statusFilter !== "all" ? t("at.nf.status", { status: t("at.s." + statusFilter) }) : ""].filter(Boolean));
  function showAll() {
    setStatus("all"); typeFilter = "all"; search = "";
    if (sourceFilter) go("/atoms");
  }
  const focusedConflicts = $derived(focused ? conflicts.filter(c => focused.conflicts.some(x => x.id === c.id)) : []);
  const focusedEv = $derived(focused?.evidence[0] || null);

  // The toast stack moves up while the bulk bar is visible.
  $effect(() => {
    document.body.classList.toggle("has-bulk", checkedVisible.length > 0);
    return () => document.body.classList.remove("has-bulk");
  });
  // One banner at most: the first thing that applies.
  const shownSuggestion = $derived(shownSuggestions[0] || null);
  const showReclassify = $derived(atoms.length >= 5 && !hasNewTypes && !reclassifyHidden);
  const sub = $derived(stats && stats.total ? t("at.head", stats) + (stats.open_conflicts ? " · " + t("nav.st.conflicts", { n: stats.open_conflicts }) : "") : t("at.sub_empty"));
  // "Извлечь из новых встреч": the meetings without requirements first, each starts the usual per-source extraction.
  const extractItems = $derived([...readySources].sort((a, b) => (a.atom_count ? 1 : 0) - (b.atom_count ? 1 : 0)).map(s => ({
    value: s.id, label: s.title, icon: s.atom_count ? "refresh" : "bolt", disabled: !!app.extracting[s.id],
    hint: app.extracting[s.id] ? "…" : s.atom_count ? String(s.atom_count) : t("at.extract_new_tag") })));
  // "Проверить n": the queue of pending requirements, focused on the first.
  function reviewNext() {
    if (statusFilter !== "pending") setStatus("pending");
    requestAnimationFrame(() => {
      const a = visible.find(x => x.status === "pending");
      if (a) { select(a.id); document.getElementById(`atom-${a.id}`)?.focus({ preventScroll: true }); }
    });
  }
</script>

<svelte:window onkeydown={onKey} />

<Page title={t("at.title")} {sub} headClass="m" card={false} inspector={tab === "atoms" ? "atoms" : ""}>
  {#snippet actions()}
    <div class="seg-m tb-opt2" role="tablist">
      <button role="tab" aria-selected={tab === "atoms"} onclick={() => (tab = "atoms")}>{t("at.tab.atoms")}
        {#if stats}<span class="n">{stats.total}</span>{/if}</button>
      <button role="tab" aria-selected={tab === "open"} onclick={() => (tab = "open")}>{t("at.tab.open")}
        {#if openQuestions}<span class="n">{openQuestions}</span>{/if}</button>
    </div>
    <button class="btn icon" title={t("at.add")} aria-label={t("at.add")}
            onclick={() => { tab = "atoms"; adding = { type: "functional", statement: "", note: "" }; }}><Icon name="plus" size={16} /></button>
    <PopMenu cls="btn xbtn" icon="bolt" chevron="" text={t("at.extract_new")} ariaLabel={t("at.extract_new")} align="right"
             disabled={!readySources.length} items={extractItems} onpick={v => extractAtoms(v)} />
    {#if stats?.pending}
      <button class="btn primary" onclick={reviewNext}>{t("at.review_n", { n: stats.pending })} <Icon name="arrow" size={16} /></button>
    {:else if stats && stats.accepted}
      <button class="btn primary" onclick={() => go("/document")}>
        {app.status?.document?.version ? t("at.to_doc_update") : t("doc.build_cta")} <Icon name="arrow" size={16} /></button>
    {/if}
  {/snippet}

  {#if tab === "open"}
    <div class="page scroll"><div class="open-wrap"><OpenItems {atoms} {conflicts} onChange={load} /></div></div>
  {:else}
  <div class="at-screen">
    {#if atoms.length}
      <div class="scope scope-row">
        <div class="seg-m" role="group" aria-label={t("at.f.status")}>
          {#each SEGS as f (f)}
            {#if f !== "rejected" || statusCount(f) || statusFilter === "rejected"}
              <button class="pill" aria-pressed={statusFilter === f} onclick={() => setStatus(f)}>
                {t("at.s." + f)} <span class="n">· {statusCount(f)}</span>
              </button>
            {/if}
          {/each}
        </div>
        <div class="types" role="group" aria-label={t("insp.type")}>
          {#each ALL_TYPES as ty (ty)}
            <button class="chip-m sm" aria-pressed={typeFilter === ty} title={t("at.full." + ty)}
                    onclick={() => (typeFilter = typeFilter === ty ? "all" : ty)}>{PREFIX[ty]}{#if typeFilter === ty} <span class="n">· {typeCount(ty)}</span>{/if}</button>
          {/each}
        </div>
        {#if inConflict || statusFilter === "conflicts"}
          <button class="chip-m sm danger" aria-pressed={statusFilter === "conflicts"}
                  onclick={() => setStatus(statusFilter === "conflicts" ? "pending" : "conflicts")}>{t("at.in_conflict", { n: statusCount("conflicts") })}</button>
        {/if}
        {#if sourcesWithAtoms.length > 1 || sourceFilter}
          <PopMenu cls="popbtn src-pop" label={t("at.source")} value={sourceFilter || ""} ariaLabel={t("at.source")}
                   items={[{ value: "", label: t("at.all_sources") }, { sep: true },
                           ...sourcesWithAtoms.map(s => ({ value: s.id, label: s.title, hint: String(s.atom_count) })),
                           ...(sourceFilter && !sourcesWithAtoms.some(s => s.id === sourceFilter) ? [{ value: sourceFilter, label: sourceFilterTitle }] : [])]}
                   onpick={v => go(v ? `/atoms/source/${v}` : "/atoms")} />
        {/if}
        <span class="grow"></span>
        <label class="search">
          <Icon name="search" size={14} />
          <input id="at-search" type="search" bind:value={search} placeholder={t("at.search")} aria-label={t("at.search")}
                 onkeydown={e => { if (e.key === "Escape") { search = ""; e.currentTarget.blur(); } }} />
          <span class="kbd">/</span>
        </label>
        <PopMenu cls="btn ghost icon" chevron="" icon="more" ariaLabel={t("at.more")} title={t("at.more")} align="right"
                 items={[{ heading: t("at.group") },
                         ...["none", "source", "speaker"].map(g => ({ value: "g:" + g, label: t(g === "none" ? "at.group.no" : "at.group." + g), icon: groupBy === g ? "check" : "" })),
                         { sep: true }, { value: "rc", label: t("at.rc.button"), icon: "bolt", disabled: !!reclassifying }]}
                 onpick={v => (v === "rc" ? reclassify() : (groupBy = v.slice(2)))} />
      </div>
    {/if}

    <div class="pane-cards">
  <Panes screen="atoms">
    <div class="notices">
      {#if error}<div class="banner danger"><Icon name="warn" /><span class="grow">{error}</span>
        <button class="btn sm" onclick={load}>{t("ov.retry")}</button></div>
      {:else if reclassifying}
        <div class="banner info"><span class="spinner"></span><span class="grow">{reclassifying.message || t("at.rc.running")}</span></div>
      {:else if stats && stats.total && !stats.pending && statusFilter !== "pending" && visible.length}
        <div class="banner" class:ok={!stats.open_conflicts} class:warn={!!stats.open_conflicts}>
          <Icon name={stats.open_conflicts ? "warn" : "check"} />
          <span class="grow"><b>{t("at.done_title")}</b> · {t("at.done_meta", stats)}{#if stats.open_conflicts}, {t("at.done_but_conflicts", { n: stats.open_conflicts })}{/if}</span>
          {#if stats.open_conflicts}
            <button class="btn sm" onclick={() => setStatus("conflicts")}>{t("at.resolve_conflicts")}</button>
          {:else}
            <button class="btn sm" onclick={() => go("/document")}>{t("doc.build_cta")} <Icon name="arrow" size={12} /></button>
          {/if}
        </div>
      {:else if shownSuggestion}
        {@const sg = shownSuggestion}
        <div class="banner info rule">
          <Icon name="spark" />
          <div class="grow">
            <b>{sg.kind === "rewrite" ? t("at.sg.rewrite", { n: sg.count, old: sg.old, new: sg.new }) : t("at.sg.reject", { n: sg.count, reason: t("at.reason." + sg.reason) })}</b>
            {#if showRule === sg.id}<pre class="rule-text">{sg.rule}</pre>{/if}
          </div>
          <button class="btn sm ghost" onclick={() => (showRule = showRule === sg.id ? null : sg.id)}>{t("at.sg.show")}</button>
          <button class="btn sm" onclick={() => applyRule(sg)}>{t("at.sg.apply")}</button>
          <button class="btn sm ghost" onclick={() => (dismissedRules = new Set([...dismissedRules, sg.id]))}>{t("at.sg.no")}</button>
        </div>
      {:else if showReclassify}
        <div class="banner info rule">
          <Icon name="info" />
          <div class="grow"><b>{t("at.rc.banner_title")}</b> {t("at.rc.banner")}</div>
          <button class="btn sm primary" onclick={reclassify}>{t("at.rc.button")}</button>
          <button class="btn sm ghost" onclick={() => (reclassifyHidden = true)}>{t("at.sg.no")}</button>
        </div>
      {/if}
    </div>

    {#if adding}
      <section class="add-card">
        <div class="seg-m" role="group" aria-label={t("insp.type")}>
          {#each ALL_TYPES as ty (ty)}
            <button aria-pressed={adding.type === ty} onclick={() => (adding.type = ty)} title={t("at.full." + ty)}>{PREFIX[ty]}</button>
          {/each}
        </div>
        <!-- svelte-ignore a11y_autofocus -->
        <textarea class="input" rows="2" bind:value={adding.statement} autofocus placeholder={t("at.add_ph")} aria-label={t("at.add_ph")}
                  onkeydown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); adding.statement.trim() && addAtom(); } if (e.key === "Escape") adding = null; }}></textarea>
        <input class="input" bind:value={adding.note} placeholder={t("at.add_note")} aria-label={t("at.add_note")} />
        <div class="actions">
          <span class="hint grow">{t("at.add_hint")}</span>
          <button class="btn sm ghost" onclick={() => (adding = null)}>{t("at.cancel")}</button>
          <button class="btn sm primary" disabled={!adding.statement.trim()} onclick={addAtom}>{t("at.save")}</button>
        </div>
      </section>
    {/if}

    <div class="pane-body scroll rows-wrap">
      {#if loaded && !atoms.length}
        <div class="empty">
          <div class="glyph"><Icon name="atoms" size={20} /></div>
          <h3>{t("at.none_title")}</h3>
          <p>{t("at.none")}</p>
          <button class="btn lg primary" onclick={() => go("/sources")}>{t("at.to_sources")} <Icon name="arrow" size={14} /></button>
        </div>
      {:else if loaded && !visible.length}
        {#if statusFilter === "pending" && stats && !stats.pending && !needle && typeFilter === "all" && !sourceFilter}
          <div class="empty">
            <div class="glyph" class:ok={!stats.open_conflicts}><Icon name={stats.open_conflicts ? "warn" : "check"} size={20} /></div>
            <h3>{t("at.done_title")}</h3>
            <p>{t("at.done_meta", stats)}{#if stats.open_conflicts}. {t("at.done_but_conflicts", { n: stats.open_conflicts })}{/if}</p>
            {#if stats.open_conflicts}
              <button class="btn lg primary" onclick={() => setStatus("conflicts")}>{t("at.resolve_conflicts")}</button>
            {/if}
          </div>
        {:else}
          <div class="empty"><h3>{t("at.none_filtered")}</h3>
            <p>{narrowed.join(" · ")}</p>
            <button class="btn lg primary" onclick={showAll}>{t("at.show_all_n", { n: atoms.length })}</button></div>
        {/if}
      {:else}
        <div class="rows" class:selecting={checkedVisible.length > 0}>
          <div class="rows-head">
            <label class="check-all" title="⌘A">
              <input type="checkbox" checked={allChecked} indeterminate={checkedVisible.length > 0 && !allChecked} disabled={!visible.length}
                     onchange={toggleAll} aria-label={t("at.select_all", { n: visible.length })} />
            </label>
            <span>{t("at.col.id")}</span><span>{t("at.col.statement")}</span>
            <span class="col-src">{t("at.source")}</span><span class="col-x">{t("insp.speaker")}</span><span class="col-x">{t("at.priority")}</span>
            <span class="col-status">{t("at.col.status")}</span>
          </div>
          {#each groups as g (g.key)}
            {#if g.title}<div class="group-head"><b class="trunc">{g.title}</b><span class="t3 num">{g.items.length}</span></div>{/if}
            {#each g.items as atom (atom.id)}
              {@const ev = atom.evidence[0]}
              <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
              <div class="atom" id="atom-{atom.id}" class:focus={atom.id === selectedId} class:rejected={atom.status === "rejected"}
                   aria-selected={checked.has(atom.id) || atom.id === selectedId} role="row" tabindex="-1"
                   onclick={() => pick(atom.id)} ondblclick={() => startEdit(atom)}>
                <input type="checkbox" class="row-check" checked={checked.has(atom.id)} aria-label={atom.statement}
                       onclick={e => { e.stopPropagation(); toggleCheck(atom, e.shiftKey); }} />
                <span><span class="type idb {typeClass[atom.type]}" title={t("at.full." + atom.type)}>{codeOf[atom.id]}</span></span>
                <div class="body">
                  <p class="row-title">{atom.statement}</p>
                  {#each atom.evidence.slice(0, 2) as e (e.id)}
                    <p class="quote">{e.quote}</p>
                  {/each}
                  <p class="row-meta">
                    {#if ev}<span class="m-src">{#if ev.source_kind === "material"}<span class="mat" title={t("at.material")}><Icon name="file" size={10} /></span>{/if}{evSource(ev)}</span>{#if ev.start != null}<span class="num">{fmtTime(ev.start)}</span>{/if}{/if}
                    {#if atom.origin === "ba"}<span>{t("at.ba_origin")}</span>{/if}
                    {#if atom.statement !== atom.original_statement}<span>{t("at.edited")}</span>{/if}
                    {#if atom.type === "question" && atom.q_state}<span class:ok={atom.q_state === "answered"}>{t("oi.st." + atom.q_state)}</span>{/if}
                    {#each atom.conflicts as c (c.id)}
                      <span class="conf"><Icon name="warn" size={12} /> {codeOf[c.other] && statementOf[c.other] ? t("at.conflict_code", { code: codeOf[c.other] }) : t("at.conflict_with", { text: c.description })}</span>
                    {/each}
                  </p>
                </div>
                <span class="col-src">
                  {#if ev}
                    <span class="src-cell">{#if ev.source_kind === "material"}<span class="mat" title={t("at.material")}><Icon name="file" size={10} /></span>{/if}<span class="trunc">{evSource(ev)}</span></span>
                    {#if atom.evidence.length > 1}<span class="t3 more-src">+{atom.evidence.length - 1}</span>{/if}
                  {/if}
                </span>
                <span class="col-x trunc">{evSpeaker(ev)}</span>
                <span class="col-x">{atom.priority ? t("at.prio." + atom.priority) : ""}</span>
                <span class="col-status">
                  {#if atom.conflicts.length && atom.status !== "rejected"}<span class="tag-m danger">{t("at.tag.conflict")}</span>
                  {:else if atom.status === "accepted"}<span class="tag-m ok">{t("at.tag.accepted")}</span>
                  {:else if atom.status === "rejected"}<span class="tag-m">{t("at.tag.rejected")}</span>
                  {:else}<span class="tag-m warn">{t("at.tag.pending")}</span>{/if}
                </span>
              </div>
            {/each}
          {/each}
        </div>
      {/if}
    </div>

    {#if checkedVisible.length}
      <div class="bulkbar" role="toolbar" aria-label={t("at.selected", { n: checkedVisible.length })}>
        <b class="count num">{t("at.selected", { n: checkedVisible.length })}</b>
        {#if checkedInConflict}<span class="conf">{t("at.bulk_conflicts", { n: checkedInConflict })}</span>{/if}
        <span class="vsep"></span>
        {#if checkedInConflict && checkedInConflict < checkedVisible.length}
          <button class="btn primary" disabled={bulkBusy} onclick={() => bulk({ status: "accepted" }, { skipConflicts: true })}
                  title={t("at.bulk_skip_hint")}>
            <Icon name="check" size={14} /> {t("at.accept")} {checkedVisible.length - checkedInConflict}</button>
          <button class="btn" disabled={bulkBusy} onclick={() => bulk({ status: "accepted" })}>{t("at.bulk_with_conflicts", { n: checkedInConflict })}</button>
        {:else}
          <button class="btn primary" disabled={bulkBusy} onclick={() => bulk({ status: "accepted" })}>
            <Icon name="check" size={14} /> {t("at.accept")}</button>
        {/if}
        <button class="btn" disabled={bulkBusy} onclick={() => bulk({ status: "rejected" })}>
          <Icon name="close" size={14} /> {t("at.reject")}</button>
        <span class="up"><PopMenu cls="btn" text={t("at.bulk_more")} ariaLabel={t("at.bulk_more")} disabled={bulkBusy}
                 items={[{ value: "st:pending", label: t("at.bulk_pending") },
                         { heading: t("at.bulk_reason") }, ...REASONS.map(r => ({ value: "rs:" + r, label: t("at.reason." + r) })),
                         { heading: t("at.priority") }, ...PRIOS.map(p => ({ value: "pr:" + p, label: t("at.prio." + p) })), { value: "pr:", label: t("at.prio.none") }]}
                 onpick={v => { const [k, x] = v.split(":"); if (k === "st") bulk({ status: x }); else if (k === "rs") bulk({ status: "rejected", reject_reason: x }); else bulk({ priority: x || null }); }} /></span>
        <span class="up type-menu"><PopMenu cls="btn" text={t("at.bulk_type")} ariaLabel={t("at.bulk_type")} disabled={bulkBusy}
                 items={ALL_TYPES.map(ty => ({ value: ty, label: t("at.full." + ty) }))} onpick={v => bulk({ type: v })} /></span>
        <button class="btn danger-text" disabled={bulkBusy} onclick={() => removeAtoms(checkedVisible)}>
          <Icon name="trash" size={14} /> {t("at.delete")}</button>
        <span class="vsep"></span>
        <button class="btn ghost" onclick={() => checked.clear()}>{t("at.bulk_clear")} <span class="kbd">esc</span></button>
      </div>
    {/if}

    {#snippet inspector()}
      <AtomInspector atom={checkedVisible.length > 1 ? null : focused} count={checkedVisible.length} code={focused ? codeOf[focused.id] : ""}
                     conflicts={focusedConflicts} {statementOf} {codeOf} editing={!!focused && editingId === focused.id} {busy}
                     onDecide={(a, st) => decide(a, st)} onEdit={startEdit} onSave={saveEdit} onCancel={() => (editingId = null)}
                     onDelete={a => removeAtoms([a])} onResolve={resolve} onPatch={patchProps} />
    {/snippet}
    {#snippet context()}
      <SourceContext sourceId={focusedEv?.source_id || null} segmentIdx={focusedEv?.segment_idx ?? null} quote={focusedEv?.quote || ""}
                     title={focusedEv?.source_title || ""} head={focused ? t("ctx.where", { code: codeOf[focused.id] }) : t("ctx.title")} />
    {/snippet}
  </Panes>
    </div>
  </div>
  {/if}
</Page>

<style>
  /* prototype-v5 pageRequirements(): the scope row on the background, the table in a card */
  .page { height: 100%; }
  .open-wrap { max-width: 1100px; margin: 0 auto; padding: 0 4px var(--s-11); }
  .at-screen { display: flex; flex-direction: column; height: 100%; min-height: 0; }
  .at-screen > .pane-cards { flex: 1; min-height: 0; }
  .scope-row { display: flex; align-items: center; gap: 8px; padding: 0 4px 14px; flex-wrap: wrap; min-height: 0; border: 0; flex: none; }
  .types { display: inline-flex; gap: 6px; flex-wrap: wrap; }
  .scope-row :global(.pop) { flex: none; }
  .scope-row :global(.popbtn) { height: 32px; border-radius: 16px; background: var(--surface-2); padding: 0 10px 0 14px; }
  .scope-row :global(.popbtn:hover) { background: var(--surface-3); }
  .scope-row :global(.btn.icon) { width: 36px; height: 36px; border-radius: 18px; }
  .search { width: clamp(150px, 18cqw, 280px); flex: 0 1 auto; height: 36px; border-radius: 18px; background: var(--surface); box-shadow: var(--shadow-1); padding: 0 12px; }
  .search .kbd { background: var(--surface-2); }
  .notices:not(:empty) { padding: var(--s-5) 14px 0; }
  .notices .banner { flex-wrap: wrap; }
  .rule-text { white-space: pre-wrap; font: var(--size-mono)/var(--lh-mono) var(--mono); margin: var(--s-3) 0 0; color: var(--text); }
  .add-card { margin: var(--s-5) 14px 0; padding: var(--s-5); border-radius: var(--r-m); background: var(--surface-2);
    display: grid; gap: var(--s-4); grid-template-columns: minmax(0, 1fr); justify-items: start; flex: none; }
  .add-card textarea, .add-card input, .add-card .actions { width: 100%; }
  .add-card .input { background: var(--surface); }
  .add-card textarea { font: var(--w-medium) var(--size-item)/var(--lh-item) var(--font); }

  .rows-wrap { display: flex; flex-direction: column; }
  .rows { container-type: inline-size; container-name: list; padding-bottom: 96px; }
  .rows-head, .atom { display: grid; align-items: start; column-gap: 14px; padding: 0 14px;
    grid-template-columns: 18px 72px minmax(0, 1fr) 120px; }
  .rows-head { position: sticky; top: 0; z-index: 2; align-items: center; min-height: 38px; background: var(--surface); border-bottom: 1px solid var(--outline-2);
    font-size: 12px; font-weight: 600; color: var(--text-3); white-space: nowrap; }
  .check-all { display: inline-grid; place-items: center; width: 18px; }
  .col-x, .col-src { display: none; font-size: 13px; line-height: var(--lh-item); color: var(--text-2); min-width: 0; }
  .rows-head .col-x, .rows-head .col-src { color: var(--text-3); font-size: 12px; }
  .col-status { justify-self: start; }
  .atom { padding-top: 12px; padding-bottom: 12px; position: relative; cursor: default; scroll-margin: 40px 0 96px;
    border-bottom: 1px solid var(--outline-2); transition: background var(--d-fast) var(--ease-out); }
  .atom:hover { background: var(--surface-2); }
  .atom[aria-selected="true"] { background: var(--secondary-c); }
  .atom.focus::before { content: ""; position: absolute; left: 0; top: 8px; bottom: 8px; width: 3px; border-radius: 0 3px 3px 0; background: var(--primary); }
  .atom .row-check { margin-top: 2px; opacity: 0; transition: opacity var(--d-fast); }
  .atom:hover .row-check, .atom .row-check:checked, .atom.focus .row-check, .rows.selecting .row-check { opacity: 1; }
  @media (hover: none) { .atom .row-check { opacity: 1; } }
  .body { min-width: 0; }
  .row-title { font-size: 14px; line-height: 20px; color: var(--text); max-width: 96ch; text-wrap: pretty; }
  .atom.rejected .row-title { color: var(--text-3); text-decoration: line-through; text-decoration-thickness: 1px; }
  .quote { display: -webkit-box; -webkit-line-clamp: 2; line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; margin-top: 2px; text-align: left;
    color: var(--text-2); font-size: 13px; max-width: 96ch; }
  .quote::before { content: "«"; } .quote::after { content: "»"; }
  .row-meta { display: flex; flex-wrap: wrap; align-items: center; gap: 2px var(--s-4); margin-top: var(--s-2); font-size: 12px;
    line-height: var(--lh-foot); color: var(--text-3); }
  .row-meta:empty { display: none; }
  .row-meta > span + span::before { content: "·"; margin-right: var(--s-4); color: var(--text-3); }
  .row-meta .conf { color: var(--danger); font-weight: 500; display: inline-flex; align-items: center; gap: var(--s-2); }
  .row-meta .ok { color: var(--ok); }
  .m-src { display: inline-flex; align-items: center; gap: 4px; }
  .src-cell { display: flex; align-items: center; gap: 6px; min-width: 0; }
  .more-src { font-size: 12px; }
  .mat { width: 18px; height: 18px; border-radius: 5px; background: #5B45C9; color: #fff; display: inline-grid; place-items: center; flex: none; }
  .col-status { padding-top: 0; }
  @container list (min-width: 760px) {
    .rows-head, .atom { grid-template-columns: 18px 72px minmax(0, 1fr) minmax(140px, 200px) 120px; }
    .col-src { display: block; }
    .m-src { display: none; }
    .row-meta > .m-src + span::before { display: none; }
  }
  @container list (min-width: 1160px) {
    .rows-head, .atom { grid-template-columns: 18px 72px minmax(0, 1fr) minmax(140px, 220px) 120px 80px 120px; }
    .col-x { display: block; }
  }
  .group-head { position: sticky; top: 38px; z-index: 1; display: flex; align-items: center; gap: var(--s-4); height: 30px; padding: 0 14px;
    background: var(--surface-2); font-size: 12px; color: var(--text-2); }
  .group-head b { font-weight: 600; }
  .glyph.ok { background: var(--ok-c); color: var(--ok); }

  .bulkbar { position: absolute; left: 50%; bottom: var(--s-8); transform: translateX(-50%); z-index: 20;
    display: flex; align-items: center; gap: var(--s-4); min-height: 52px; padding: 6px 8px 6px 20px; border-radius: 26px;
    background: var(--hud); color: var(--hud-text); box-shadow: var(--shadow-3); -webkit-backdrop-filter: var(--blur-hud); backdrop-filter: var(--blur-hud);
    max-width: calc(100% - 32px); flex-wrap: wrap; animation: hud-in var(--d-slow) var(--ease-out); }
  @keyframes hud-in { from { opacity: 0; transform: translate(-50%, 24px); } }
  .bulkbar .count { font-weight: 600; white-space: nowrap; }
  .bulkbar .conf { color: #FFB4A8; font-size: 12px; white-space: nowrap; }
  .bulkbar .vsep { width: 1px; height: 20px; background: var(--hud-line); }
  .bulkbar :global(.btn) { height: 36px; padding: 0 14px; border-radius: 18px; background: var(--hud-2); color: var(--hud-text); box-shadow: none; }
  .bulkbar :global(.btn:hover:not(:disabled)) { background: color-mix(in srgb, var(--hud-2), #fff 10%); }
  .bulkbar :global(.btn.primary) { background: #A8C7FA; color: #062E6F; }
  .bulkbar :global(.btn.primary:hover:not(:disabled)) { background: #BCD4FB; }
  .bulkbar :global(.btn.ghost) { background: none; color: var(--hud-text-2); }
  .bulkbar :global(.btn.danger-text) { color: #FFB4A8; }
  .bulkbar :global(.kbd) { background: rgba(255,255,255,.14); color: var(--hud-text); }
  .bulkbar .up :global(.menu) { top: auto; bottom: calc(100% + 8px); color: var(--text); }
  @media (max-width: 760px) {
    :global(.page-head.m .xbtn .trunc) { display: none; }
    :global(.page-head.m .xbtn) { width: 36px; padding: 0 !important; }
    .scope-row { gap: 6px; }
    .search { width: 100%; flex: 1 1 100%; order: 9; }
  }
</style>
