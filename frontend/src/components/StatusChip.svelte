<script>
  // Status chip (prototype-v5 .status-chip): what the machine is doing. A recording first, else the first job
  // with its progress ring, else "Готово". Click lists every job with progress and cancel where it exists.
  import { api } from "../lib/api.js";
  import { app, t, go, toast } from "../lib/state.svelte.js";
  import { cap, clock } from "../lib/capture.svelte.js";

  let jobs = $state([]);
  let recording = $state(null);           // the server recorder (desktop window); cap.* covers a browser recording
  let now = $state(Date.now() / 1000);
  let open = $state(false);
  let wrap = $state(null);
  let timer = null;

  async function refresh() {
    clearTimeout(timer);
    try {
      const body = await api("/api/jobs");
      jobs = body.jobs || [];
      recording = body.recording;
    } catch (_) { /* the chip is optional; try again later */ }
    now = Date.now() / 1000;
    const busy = jobs.length || recording || cap.recording;
    timer = setTimeout(refresh, busy ? 2000 : 15000);
  }
  $effect(() => { app.jobsTick; cap.recording; refresh(); return () => clearTimeout(timer); });

  const recOn = $derived(cap.recording || !!recording);
  const recSeconds = $derived(cap.recording ? cap.elapsed : Math.floor(recording?.elapsed || 0));
  const first = $derived(jobs[0]);
  const kindText = j => t(`status.kind.${j.kind}`) === `status.kind.${j.kind}` ? t("status.kind.other") : t(`status.kind.${j.kind}`);
  const text = $derived(recOn ? t("status.recording", { time: clock(recSeconds) })
    : first ? (first.progress != null ? `${kindText(first)} · ${first.progress}% · ` : `${kindText(first)}… · `) + t("status.jobs_n", { n: jobs.length })
    : t("status.idle"));
  const elapsed = j => (j.started_at ? clock(Math.max(0, Math.floor(now - j.started_at))) : "");

  function onChip() {
    if (recOn) { go("/sources"); return; }      // the recording HUD and its stop button live there
    open = !open;
    if (open) refresh();
  }
  async function cancel(j) {
    try { await api(j.cancel_url, { method: "POST" }); } catch (err) { toast(err.message, { kind: "danger" }); }
    refresh();
  }
  function onDoc(e) { if (open && wrap && !wrap.contains(e.target)) open = false; }
  function onKey(e) { if (open && e.key === "Escape") open = false; }
</script>

<svelte:document onmousedown={onDoc} />
<svelte:window onkeydown={onKey} />

<div class="chip-wrap" bind:this={wrap}>
  <button class="status-chip" class:idle={!recOn && !first} onclick={onChip} title={recOn ? t("status.open_recording") : t("status.title")}
          aria-label={text} aria-haspopup={recOn ? undefined : "dialog"} aria-expanded={recOn ? undefined : open}>
    {#if recOn}<span class="rec" aria-hidden="true"></span>
    {:else if first}<span class="ring" class:spin={first.progress == null} style:--p={first.progress ?? 25} aria-hidden="true"></span>
    {:else}<span class="ok" aria-hidden="true"></span>{/if}
    <span class="txt">{text}</span>
  </button>
  {#if open}
    <div class="menu jobs-pop" role="dialog" aria-label={t("status.title")}>
      <p class="menu-label">{t("status.title")}</p>
      {#each jobs as j (j.id)}
        <div class="job">
          <div class="row">
            <span class="grow trunc"><b>{kindText(j)}</b>{j.label ? " · " + j.label : ""}</span>
            <span class="t3 num">{[j.progress != null ? j.progress + "%" : "", elapsed(j)].filter(Boolean).join(" · ")}</span>
          </div>
          <div class="bar" class:unknown={j.progress == null}><i style:width={(j.progress ?? 100) + "%"}></i></div>
          {#if j.cancellable && j.cancel_url}
            <button class="btn sm ghost" onclick={() => cancel(j)}>{t("status.cancel")}</button>
          {/if}
        </div>
      {:else}
        <p class="none t3">{t("status.none")}</p>
      {/each}
    </div>
  {/if}
</div>

<style>
  .chip-wrap { position: relative; flex: none; }
  .status-chip { display: inline-flex; align-items: center; gap: 8px; height: 36px; padding: 0 14px 0 12px; border: 0; border-radius: 18px;
    background: var(--surface); box-shadow: var(--shadow-1); color: var(--text-2); font-weight: 500; cursor: pointer; max-width: 46vw; }
  .status-chip:hover { background: color-mix(in srgb, var(--surface), var(--text) 4%); }
  .status-chip.idle { color: var(--text-3); }
  .txt { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .ring { width: 16px; height: 16px; border-radius: 50%; flex: none; position: relative;
    background: conic-gradient(var(--primary) calc(var(--p) * 1%), var(--surface-3) 0); }
  .ring::after { content: ""; position: absolute; inset: 3px; border-radius: 50%; background: var(--surface); }
  .ring.spin { animation: spin 1.2s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .rec { width: 10px; height: 10px; border-radius: 50%; background: var(--rec); flex: none; animation: pulse 1.4s ease-in-out infinite; }
  @keyframes pulse { 50% { opacity: .35; } }
  .ok { width: 8px; height: 8px; border-radius: 50%; background: var(--surface-4); flex: none; }
  .jobs-pop { right: 0; top: calc(100% + 6px); width: 320px; }
  .job { padding: 6px var(--s-4) 8px; display: grid; gap: 6px; }
  .job + .job { border-top: 1px solid var(--c-line); }
  .row { display: flex; gap: 8px; align-items: baseline; min-width: 0; }
  .bar { height: 4px; border-radius: 2px; background: var(--surface-3); overflow: hidden; }
  .bar i { display: block; height: 100%; background: var(--primary); border-radius: 2px; }
  .bar.unknown i { opacity: .35; }
  .job .btn { justify-self: start; }
  .none { padding: var(--s-3) var(--s-4) var(--s-4); margin: 0; }
  @media (max-width: 760px) {
    .status-chip { padding: 0 10px; gap: 0; }
    .status-chip .txt { display: none; }
    .ring { width: 18px; height: 18px; }
  }
</style>
