<script>
  // Meeting recap (spec 5.0 C3): the style switch Кратко / По пунктам / Действия, the text of the chosen style,
  // and "Обновлено … · model · Обновить по новым репликам" (incremental, enabled only when lines exist past
  // through_idx) and "Пересобрать" (everything). Used on the meeting page and in the Встречи panel.
  import { untrack } from "svelte";
  import Icon from "./Icon.svelte";
  import { api, pollJob } from "../lib/api.js";
  import { explain } from "../lib/errors.js";
  import { fmtDate, renderMarkdown } from "../lib/format.js";
  import { app, t, go, loadSources } from "../lib/state.svelte.js";

  // auto: write the first summary on arrival (the "import and summarise" route), through the legacy /summarize.
  let { source, auto = false, onref = null, onchange = () => {}, shown = $bindable("") } = $props();

  const STYLES = ["brief", "bullets", "actions"];
  let style = $state("brief");
  let fresh = $state({});                  // rows written here, until the parent's reload brings them
  let running = $state(null);              // {style, incremental}
  let partial = $state("");
  let error = $state(null);
  let tick = $state(0);
  let forId = null;

  $effect(() => {
    const id = source?.id;
    untrack(() => {
      if (!id || id === forId) return;
      forId = id;
      style = source.recap_style || app.settings?.recap_style || "brief";   // Settings → Запись: the default style
      fresh = {};
      error = null;
      if (auto && source.status === "ready" && !Object.keys(source.summaries || {}).length && source.segments?.length) legacy();
    });
  });

  const rows = $derived({ ...(source?.summaries || {}), ...fresh });
  const row = $derived(rows[style] || null);
  const newCount = $derived(!row || row.through_idx == null || !source ? 0
    : source.segments.filter(s => s.idx > row.through_idx).length);
  const hasText = $derived(!!source?.segments?.length);
  $effect(() => { shown = row?.text || ""; });

  async function follow(jobId, which, incremental) {
    running = { style: which, incremental };
    partial = "";
    error = null;
    const started = Date.now();
    const timer = setInterval(() => (tick = Math.round((Date.now() - started) / 1000)), 500);
    const id = source.id;
    try {
      const job = await pollJob(jobId, j => { if (j.partial) partial = j.partial; }, { interval: 600 });
      const r = job.result;
      if (source?.id === id) fresh = { ...fresh, [which]: { text: r.summary, model: r.model, through_idx: r.through_idx,
                                                             created_at: rows[which]?.created_at && r.unchanged ? rows[which].created_at : Date.now() / 1000 } };
      loadSources();
      onchange();
    } catch (err) {
      if (source?.id === id) error = explain(err);
    } finally {
      clearInterval(timer);
      running = null;
      partial = "";
    }
  }
  async function run(incremental) {
    if (running || !source) return;
    const which = style;
    try {
      const { job_id } = await api(`/api/sources/${source.id}/recap`, { method: "POST", body: { style: which, incremental } });
      await follow(job_id, which, incremental);
    } catch (err) { error = explain(err); }
  }
  async function legacy() {
    style = "brief";
    try {
      const { job_id } = await api("/summarize", { method: "POST", body: { source_id: source.id } });
      await follow(job_id, "brief", false);
    } catch (err) { error = explain(err); }
  }
  function pick(s) {
    if (s === style) return;
    style = s;
    error = null;
    if (!rows[s] && hasText && !running) run(false);       // a style with no recap yet gets a full one
    else api(`/api/sources/${source.id}`, { method: "PATCH", body: { recap_style: s } }).catch(() => {});   // remembered
  }
  function onClick(e) {
    const ref = e.target.closest?.(".ref");
    if (!ref || !onref) return;
    const m = /(?:(\d{1,2}):)?(\d{1,2}):(\d{2})/.exec(ref.textContent);
    if (m) onref(Number(m[1] || 0) * 3600 + Number(m[2]) * 60 + Number(m[3]));
  }
</script>

<div class="recap">
  <div class="rc-seg" role="group" aria-label={t("rc.style")}>
    {#each STYLES as s (s)}
      <button class:on={style === s} aria-pressed={style === s} onclick={() => pick(s)}>{t("rc." + s)}</button>
    {/each}
  </div>
  {#if error}
    <div class="banner danger"><Icon name="warn" /><span class="grow">{error.message}</span>
      {#if error.setup}<button class="btn sm" onclick={() => go("/settings")}>{t("err.open_settings")}</button>{/if}</div>
  {/if}
  {#if running && running.style === style}
    {#if partial}<div class="md summary">{@html renderMarkdown(partial)}</div>{/if}
    <p class="hint"><span class="spinner"></span> {t(running.incremental ? "rc.updating" : "rc.writing", { s: tick })}</p>
  {:else if row}
    <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
    <div class="md summary" class:refs={!!onref} onclick={onClick}>{@html renderMarkdown(row.text)}</div>
    <p class="hint rc-foot">
      <span>{t("meet.updated", { when: fmtDate(row.created_at, app.lang), model: row.model })}</span> ·
      <button class="link rc-update" disabled={!newCount || !!running} onclick={() => run(true)}
              title={newCount ? t("rc.new_n", { n: newCount }) : t("rc.none_new")}>{t("rc.update_new")}</button> ·
      <button class="link rc-rebuild" disabled={!!running} onclick={() => run(false)}>{t("rc.rebuild")}</button>
    </p>
  {:else if hasText && !error}
    <div class="empty small"><p>{t("rc.none")}</p>
      <button class="btn" onclick={() => run(false)} disabled={!!running}><Icon name="spark" size={14} /> {t("rc.make")}</button></div>
  {/if}
</div>

<style>
  .recap { display: grid; gap: 10px; align-content: start; min-width: 0; }
  .rc-seg { display: inline-flex; justify-self: start; background: var(--surface-2); border-radius: 20px; padding: 3px; gap: 2px; max-width: 100%; overflow-x: auto; }
  .rc-seg button { height: 32px; padding: 0 14px; border: 0; border-radius: 17px; background: none; font: 500 13px/1 var(--font); color: var(--text-2);
    cursor: pointer; white-space: nowrap; }
  .rc-seg button.on { background: var(--surface); color: var(--text); box-shadow: var(--shadow-1); }
  .hint { color: var(--text-3); font-size: 12px; display: flex; align-items: center; gap: 4px; flex-wrap: wrap; }
  .link { border: 0; background: none; padding: 0; font: inherit; color: var(--primary); cursor: pointer; }
  .link:hover:not(:disabled) { text-decoration: underline; }
  .link:disabled { color: var(--text-3); cursor: default; }
  .summary.refs :global(.ref) { color: var(--primary); cursor: pointer; }
  .summary.refs :global(.ref:hover) { text-decoration: underline; }
  .empty.small { padding: 24px 0; }
  .empty.small p { font-size: var(--size-body); }
</style>
