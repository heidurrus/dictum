<script>
  // Overview (redesign §8.1): the project at a glance. One next step, then where each stage of
  // the pipeline stands, what waits for the client, and what changed since the last visit.
  import Icon from "../components/Icon.svelte";
  import Page from "../components/Page.svelte";
  import { api } from "../lib/api.js";
  import { fmtDate } from "../lib/format.js";
  import { nextStep } from "../lib/next.js";
  import { app, t, go, currentProject, writePref } from "../lib/state.svelte.js";

  const pid = $derived(app.currentProjectId);
  const project = $derived(currentProject());
  const s = $derived(app.status);
  const next = $derived(nextStep());
  let atoms = $state([]);
  let since = $state([]);
  let failed = $state(false);

  async function load() {
    failed = false;
    try { atoms = (await api(`/api/projects/${pid}/atoms`)).atoms || []; }
    catch (_) { failed = true; }
  }
  $effect(() => { pid; app.atomsVersion; load(); });

  // "Since last time": what the audit log recorded after this project was last opened.
  $effect(() => {
    const id = pid;
    if (!id) return;
    let last = null;
    try { last = JSON.parse(localStorage.getItem("wb.lastVisit." + id)); } catch (_) { /* private mode */ }
    since = [];
    api(`/api/projects/${id}/activity?limit=8${last ? "&since=" + last : ""}`).then(b => (since = b.entries)).catch(() => {});
    writePref("lastVisit." + id, Date.now() / 1000);
  });

  const TYPES = [["business", "br", "BR"], ["functional", "fr", "FR"], ["nfr", "nfr", "NFR"], ["risk", "rsk", "RSK"], ["current", "as", "AS"], ["question", "q", "Q"]];
  const byType = $derived(TYPES.map(([type, cls, code]) => {
    const list = atoms.filter(a => a.type === type);
    const n = k => list.filter(a => a.status === k).length;
    return { type, cls, code, total: list.length, accepted: n("accepted"), pending: n("pending"), rejected: n("rejected") };
  }).filter(x => x.total));
  const most = $derived(Math.max(1, ...byType.map(x => x.total)));

  const stages = $derived(!s ? [] : [
    { key: "sources", path: "/sources", name: t("nav.sources"), ring: !s.sources ? "" : s.processing ? "active" : "done", p: s.processing ? 50 : 100,
      text: !s.sources ? t("ov.s.sources_none") : s.processing ? t("ov.s.sources_run", { n: s.processing, all: s.sources }) : t("ov.s.sources", { n: s.sources }) },
    { key: "atoms", path: "/atoms", name: t("nav.atoms"), ring: !s.atoms.total ? "" : s.atoms.review ? "active" : s.atoms.conflicts ? "stale" : "done",
      p: s.atoms.total ? Math.round(100 * (s.atoms.total - s.atoms.review) / s.atoms.total) : 0,
      text: !s.atoms.total ? t("ov.s.atoms_none") : t("ov.s.atoms", { n: s.atoms.review, accepted: s.atoms.accepted })
            + (s.atoms.conflicts ? " · " + t("nav.st.conflicts", { n: s.atoms.conflicts }) : "") },
    { key: "document", path: "/document", name: t("nav.document"),
      ring: !s.document.version ? "" : (s.document.stale || s.document.others_stale) ? "stale" : s.document.status === "approved" ? "done" : "active", p: 50,
      text: !s.document.version ? t("ov.s.doc_none") : s.document.stale ? t("next.doc_stale", { n: s.document.changed })
            : t("ov.s.doc", { n: s.document.count, v: s.document.version }) },
    { key: "backlog", path: "/backlog", name: t("nav.decomposition"), ring: !s.backlog.items ? "" : s.backlog.stale ? "stale" : "active", p: 100,
      text: !s.backlog.items ? t("ov.s.bl_none") : s.backlog.stale ? t("next.bl_stale") : t("ov.s.bl", { n: s.backlog.included }) },
    { key: "export", path: "/export", name: t("nav.export"),
      ring: !s.export.pushed ? "" : (s.export.stale || s.export.orphans) ? "stale" : "done",
      p: s.export.pushed ? Math.round(100 * s.export.pushed / (s.export.pushed + s.export.pending)) : 0,
      text: !s.export.pushed ? t("ov.s.ex_none") : t("ov.s.ex", { n: s.export.pushed }) + (s.export.pending ? " · " + t("ov.s.ex_pending", { n: s.export.pending }) : "") },
  ]);
  const recent = $derived([...app.sources].sort((a, b) => (b.created_at || 0) - (a.created_at || 0)).slice(0, 5));
  const act = e => (t("home.act." + e.entity) === "home.act." + e.entity ? e.entity : t("home.act." + e.entity));
  const actText = e => (t("act." + e.action) === "act." + e.action ? e.action : t("act." + e.action));
</script>

<Page title={t("nav.overview")} sub={project?.name || ""}>
  {#snippet actions()}
    <button class="btn" onclick={() => go("/sources")}><Icon name="plus" size={14} /> {t("ov.add_source")}</button>
  {/snippet}

  <div class="page scroll">
    <div class="ov">
      <header class="ov-head">
        <h2>{project?.name || ""}</h2>
        {#if s}
          <p>{t("ov.counts", { sources: s.sources, atoms: s.atoms.total, docs: s.document.version ? s.document.count : 0 })}</p>
        {/if}
      </header>

      {#if failed}
        <div class="banner danger"><Icon name="warn" /><span class="grow">{t("ov.failed")}</span>
          <button class="btn sm" onclick={load}>{t("ov.retry")}</button></div>
      {/if}

      {#if next}
        <section class="next" class:done={next.done}>
          <div class="grow">
            <p class="cap">{t("ov.next")}</p>
            <h3>{next.title}</h3>
            <p>{next.text}</p>
          </div>
          {#if next.wait}<span class="spinner"></span>
          {:else if next.cta}
            <button class="btn lg primary" onclick={() => go(next.go)}>{next.cta} <Icon name="arrow" size={14} /></button>
          {/if}
        </section>
      {/if}

      <div class="ov-grid">
        <div class="col">
          <section>
            <div class="sec-title"><h3>{t("nav.pipeline")}</h3></div>
            {#each stages as st (st.key)}
              <div class="stage">
                <span class="ring {st.ring}" style="--p: {st.p}"></span>
                <h4>{st.name}</h4>
                <button class="btn sm ghost" onclick={() => go(st.path)}>{t("ov.open")} <Icon name="arrow" size={12} /></button>
                <p>{st.text}</p>
              </div>
            {/each}
          </section>
          {#if app.documents.some(d => d.version)}
            <section>
              <div class="sec-title"><h3>{t("nav.document")}</h3></div>
              {#each app.documents.filter(d => d.version) as d (d.id)}
                <button class="simple-row link-row" onclick={() => go(`/document/${d.id}`)}>
                  <span class="kind"><Icon name="doc" /></span>
                  <h4 class="trunc">{d.title}</h4>
                  {#if d.stale}<span class="status warn">{t("nav.st.stale")}</span>
                  {:else if d.status}<span class="status" class:ok={d.status === "approved"}>{t("doc.st." + d.status)}</span>{/if}
                  <p>{d.type} · v{d.version}</p>
                </button>
              {/each}
            </section>
          {/if}
        </div>

        <div class="col">
          {#if s}
            <section>
              <div class="sec-title"><h3>{t("ov.client")}</h3>
                {#if s.open_items.questions || s.open_items.actions}
                  <button class="btn sm" onclick={() => go("/atoms")}>{t("ov.client_open")}</button>
                {/if}
              </div>
              <div class="simple-row">
                <span class="type q plain">Q</span>
                <h4>{t("ov.questions", { n: s.open_items.questions })}</h4><span></span>
                <p>{s.open_items.questions ? t("ov.questions_d") : t("ov.questions_none")}</p>
              </div>
              <div class="simple-row">
                <span class="t3"><Icon name="check" size={14} /></span>
                <h4>{t("ov.actions", { n: s.open_items.actions })}</h4><span></span>
                <p>{s.open_items.actions ? t("ov.actions_d") : t("ov.actions_none")}</p>
              </div>
            </section>
          {/if}
          {#if byType.length}
            <section>
              <div class="sec-title"><h3>{t("ov.by_type")}</h3>
                <span class="legend t3"><i class="a"></i>{t("ov.l.accepted")} <i class="p"></i>{t("ov.l.pending")} <i class="r"></i>{t("ov.l.rejected")}</span></div>
              {#each byType as x (x.type)}
                <div class="typebar" title={t("at.type." + x.type)}>
                  <span class="type {x.cls}">{x.code}</span>
                  <span class="mini" style="width: {Math.max(8, 100 * x.total / most)}%">
                    <i class="a" style="flex: {x.accepted}"></i><i class="p" style="flex: {x.pending}"></i><i class="r" style="flex: {x.rejected}"></i></span>
                  <span class="t3 num">{x.total}{#if x.pending} · {t("nav.st.review", { n: x.pending })}{/if}</span>
                </div>
              {/each}
            </section>
          {/if}
        </div>

        <div class="col">
          {#if since.length}
            <section>
              <div class="sec-title"><h3>{t("ov.since")}</h3></div>
              {#each since as e, i (i)}
                <div class="simple-row">
                  <span class="t3 cap-w">{act(e)}</span>
                  <h4>{actText(e)}{#if e.label}{": "}<span class="t2 lab">{e.label.slice(0, 90)}</span>{/if}</h4>
                  <time>{fmtDate(e.at, app.lang)}</time>
                </div>
              {/each}
            </section>
          {/if}
          {#if recent.length}
            <section>
              <div class="sec-title"><h3>{t("ov.recent")}</h3>
                <button class="btn sm ghost" onclick={() => go("/sources")}>{t("src.all")} <Icon name="arrow" size={12} /></button></div>
              {#each recent as src (src.id)}
                <button class="simple-row link-row" onclick={() => go(`/source/${src.id}`)}>
                  <span class="kind"><Icon name={src.kind === "audio" || src.kind === "recording" ? "wave" : "file"} /></span>
                  <h4 class="trunc">{src.title}</h4>
                  <time>{fmtDate(src.created_at, app.lang)}</time>
                </button>
              {/each}
            </section>
          {/if}
        </div>
      </div>
    </div>
  </div>
</Page>

<style>
  .page { height: 100%; }
  .ov { padding: var(--s-10) var(--gutter) var(--s-11); display: grid; gap: var(--s-9); max-width: 2200px; margin: 0 auto;
    grid-template-columns: minmax(0, 1fr); animation: fade var(--d-base) var(--ease-out); }
  .ov-head h2 { font: var(--w-bold) var(--t-large)/var(--lh-large) var(--font-display); letter-spacing: -.02em; }
  .ov-head p { color: var(--c-text-2); font-size: var(--t-item); line-height: var(--lh-item); margin-top: var(--s-2); }
  .next { display: flex; align-items: center; gap: var(--s-6); padding: var(--s-6) var(--s-7); border-radius: var(--r-lg); background: var(--c-accent-tint); }
  .next .cap { color: var(--c-accent-text); }
  .next.done { background: var(--c-ok-tint); } .next.done .cap { color: var(--c-ok); }
  .next h3 { font: var(--w-semibold) var(--t-title-2)/var(--lh-title-2) var(--font-display); letter-spacing: -.012em; margin-top: 2px; text-wrap: balance; }
  .next p:not(.cap) { color: var(--c-text-2); margin-top: 2px; max-width: var(--w-measure); }
  .ov-grid { display: grid; gap: var(--s-10) var(--s-9); grid-template-columns: minmax(0, 1fr); align-items: start; }
  @container ws (min-width: 1100px) { .ov-grid { grid-template-columns: minmax(0, 1.25fr) minmax(0, 1fr); } .col:nth-child(3) { grid-column: 1 / -1; } }
  @container ws (min-width: 1800px) { .ov-grid { grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr) minmax(0, 1fr); } .col:nth-child(3) { grid-column: auto; } }
  .col { display: grid; gap: var(--s-10); grid-template-columns: minmax(0, 1fr); align-content: start; }
  .sec-title { display: flex; align-items: baseline; gap: var(--s-4); padding-bottom: var(--s-4); border-bottom: 1px solid var(--c-line); min-height: 33px; }
  .sec-title h3 { font: var(--w-semibold) var(--t-title-3)/var(--lh-title-3) var(--font-display); letter-spacing: -.01em; }
  .sec-title .btn { margin-left: auto; align-self: center; }
  .legend { margin-left: auto; font-size: var(--t-caption); display: inline-flex; align-items: center; gap: var(--s-3); }
  .legend i { width: 8px; height: 8px; border-radius: 2px; display: inline-block; margin-left: var(--s-3); }
  .stage { display: grid; grid-template-columns: 16px minmax(0, 1fr) auto; gap: var(--s-2) var(--s-5); align-items: center; padding: var(--s-5) 0;
    border-bottom: 1px solid var(--c-line); }
  .stage h4 { font: var(--w-medium) var(--t-item)/var(--lh-item) var(--font); }
  .stage p { grid-column: 2; color: var(--c-text-2); }
  .stage .btn { grid-row: 1 / span 2; grid-column: 3; }
  .simple-row { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; gap: var(--s-2) var(--s-5); padding: var(--s-5) 0;
    border: 0; border-bottom: 1px solid var(--c-line); align-items: center; background: none; text-align: left; width: 100%; }
  .simple-row h4 { font: var(--w-medium) var(--t-body)/var(--lh-body) var(--font); text-wrap: pretty; }
  .simple-row p { grid-column: 2; font-size: var(--t-foot); line-height: var(--lh-foot); color: var(--c-text-3); }
  .simple-row time { font-size: var(--t-foot); color: var(--c-text-3); white-space: nowrap; }
  .simple-row .lab { font-weight: var(--w-regular); }
  .cap-w { font-size: var(--t-foot); min-width: 72px; }
  .link-row { cursor: pointer; border-radius: 0; transition: background var(--d-fast); }
  .link-row:hover { background: var(--c-fill-1); }
  .link-row:focus-visible { box-shadow: var(--ring-inset); }
  .kind { width: 28px; height: 28px; border-radius: 7px; background: var(--c-fill-2); color: var(--c-text-2); display: grid; place-items: center; flex: none; }
  .link-row .kind { grid-row: 1 / span 2; }
  .typebar { display: grid; grid-template-columns: 52px minmax(0, 1fr) auto; gap: var(--s-5); align-items: center; padding: var(--s-4) 0;
    border-bottom: 1px solid var(--c-line); }
  .typebar .t3 { font-size: var(--t-foot); white-space: nowrap; }
  .mini { display: flex; gap: 2px; height: 6px; border-radius: var(--r-full); overflow: hidden; background: var(--c-fill-2); }
  .mini i { display: block; height: 100%; }
  .a { background: var(--c-ok); } .p { background: var(--c-accent); } .r { background: var(--c-text-3); }
</style>
