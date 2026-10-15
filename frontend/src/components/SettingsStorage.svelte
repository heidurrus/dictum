<script>
  // Settings → Хранилище (5.0 C9): the data folder, what it holds and its size; "Показать"; "Сменить папку…" moves the
  // whole folder as a job (POST /api/data-dir/move) and asks for a restart; audio always stays next to its transcript.
  import Icon from "./Icon.svelte";
  import { api, pollJob } from "../lib/api.js";
  import { app, t, toast } from "../lib/state.svelte.js";

  let st = $state(null);            // {path, counts, bytes, default, movable, moved_to}
  let choosing = $state(false);
  let target = $state("");
  let moving = $state(null);        // {progress, message}
  let error = $state("");
  let done = $state("");            // the new folder: restart

  async function load() {
    try { st = await api("/api/storage"); if (st.moved_to) done = st.moved_to; } catch (err) { toast(err.message, { kind: "danger" }); }
  }
  $effect(() => { load(); });

  const desktop = () => !!window.pywebview?.api;
  function reveal(path) { window.pywebview?.api?.reveal?.(path); }
  async function change() {
    error = "";
    if (window.pywebview?.api?.choose_folder) {
      const r = await window.pywebview.api.choose_folder();
      if (r?.path) target = r.path;
      else if (r?.cancelled) return;
    }
    choosing = true;
  }
  async function move() {
    error = "";
    try {
      const { job_id } = await api("/api/data-dir/move", { method: "POST", body: { path: target.trim() } });
      moving = { progress: 0, message: "" };
      const job = await pollJob(job_id, j => (moving = { progress: j.progress || 0, message: j.progress_msg || "" }));
      done = job.result.path;
      choosing = false;
    } catch (err) {
      const code = err.body?.code;
      error = code && t("set.sto.err." + code) !== "set.sto.err." + code ? t("set.sto.err." + code) : err.message;
    } finally { moving = null; }
  }

  const size = n => n >= 1024 ** 3 ? t("set.sto.gb", { n: (n / 1024 ** 3).toLocaleString(app.lang, { maximumFractionDigits: 1 }) })
                                   : t("set.sto.mb", { n: Math.max(1, Math.round(n / 1048576)).toLocaleString(app.lang) });
</script>

<div class="setcard card-m storage-card">
  <h3>{t("set.sto.title")}</h3><p class="d">{t("set.sto.d")}</p>
  {#if st}
    <div class="row">
      <div class="l"><b class="mono path">{st.path}</b>
        <small class="counts">{t("set.sto.counts", { projects: st.counts.projects, meetings: st.counts.meetings,
          materials: st.counts.materials, whispers: st.counts.whispers })} · {size(st.bytes)}</small></div>
      {#if st.movable && !done}<button class="btn sm" onclick={change} disabled={!!moving}>{t("set.sto.change")}</button>{/if}
      {#if desktop()}<button class="btn sm" onclick={() => reveal(st.path)}><Icon name="folder" size={14} /> {t("set.sto.show")}</button>{/if}
    </div>
    {#if !st.movable}<p class="hint">{t("set.sto.env")}</p>{/if}
    {#if choosing && !done}
      <div class="row col move">
        <label class="l" for="newdir"><b>{t("set.sto.new")}</b><small>{t("set.sto.new_d")}</small></label>
        <div class="input-row">
          <input class="input code" id="newdir" bind:value={target} placeholder={t(app.health?.platform === "win32" ? "set.sto.placeholder_win" : "set.sto.placeholder")} disabled={!!moving}
                 onkeydown={e => e.key === "Enter" && target.trim() && move()} />
          <button class="btn primary" onclick={move} disabled={!target.trim() || !!moving}>{t("set.sto.move")}</button>
          <button class="btn ghost" onclick={() => { choosing = false; error = ""; }} disabled={!!moving}>{t("at.cancel")}</button>
        </div>
        {#if moving}<p class="hint"><span class="spinner"></span> {moving.message || t("pg.data_move")}</p>{/if}
        {#if error}<p class="note danger move-error">{error}</p>{/if}
      </div>
    {/if}
    {#if done}
      <p class="note warn restart"><Icon name="info" size={14} /> {t("set.sto.restart", { path: done })}</p>
    {/if}
  {/if}
  <label class="row">
    <span class="l"><b>{t("set.sto.audio")}</b><small>{t("set.sto.audio_d")}</small></span>
    <input type="checkbox" class="switch" checked disabled aria-label={t("set.sto.audio")} />
  </label>
</div>

<style>
  .path { font-family: var(--mono); font-size: 13px; word-break: break-all; }
  .move .input-row { flex-wrap: wrap; }
  .move .input { flex: 1; min-width: 240px; }
  .restart { margin-top: 8px; display: flex; gap: 6px; align-items: center; }
</style>
