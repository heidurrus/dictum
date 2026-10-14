<script>
  // While a call is being recorded, this pill is on every screen (redesign §8.2).
  // On the page of the meeting being recorded, that page's own pill takes over.
  // After the recording stopped itself on a long silence (5.0 C4.3) it says so, with a link to the meeting.
  import { cap, clock, stopRecording, togglePause } from "../lib/capture.svelte.js";
  import { app, t, go } from "../lib/state.svelte.js";
  const onItsPage = $derived(!!cap.sourceId && app.route.name === "transcript" && app.route.id === cap.sourceId);
  const stoppedHere = $derived(!!cap.autoStopped && app.route.name === "transcript" && app.route.id === cap.autoStopped.sourceId);
  function openStopped() {
    const id = cap.autoStopped.sourceId;
    cap.autoStopped = null;
    go(`/meeting/${id}`);
  }
</script>

{#if cap.recording && !onItsPage}
  <div class="hud" class:paused={cap.paused} role="status">
    <span class="pulse"></span>
    <span>{cap.paused ? t("live.paused") : t("rec.recording")}</span>
    <span class="num mono">{clock(cap.elapsed)}</span>
    {#if cap.problems.length}<span class="warn" title={cap.problems.join(" · ")}>{t("rec.problems")}</span>{/if}
    {#if cap.sourceId}
      <button class="btn sm" onclick={togglePause}>{cap.paused ? t("live.resume") : t("live.pause")}</button>
    {/if}
    <button class="btn sm" onclick={stopRecording}><i></i> {t("rec.stop_save")}</button>
  </div>
{:else if !cap.recording && cap.autoStopped && !stoppedHere}
  <div class="hud stopped" role="status">
    <span class="pulse"></span>
    <span>{t("live.stopped_silence")}</span>
    <button class="btn sm" onclick={openStopped}>{t("meet.open")}</button>
    <button class="btn sm icon" onclick={() => (cap.autoStopped = null)} aria-label={t("live.dismiss")} title={t("live.dismiss")}>×</button>
  </div>
{/if}

<style>
  .hud { position: fixed; top: var(--s-5); left: 50%; transform: translateX(-50%); z-index: 120; display: flex; align-items: center; gap: var(--s-4);
    height: 36px; padding: 0 var(--s-3) 0 var(--s-6); border-radius: var(--r-full); background: var(--c-hud); color: var(--c-hud-text);
    box-shadow: var(--e-4); -webkit-backdrop-filter: var(--blur-hud); backdrop-filter: var(--blur-hud); animation: drop var(--d-slow) var(--ease-out); }
  .pulse { width: 8px; height: 8px; border-radius: 50%; background: var(--c-rec); animation: pulse 1.4s ease-in-out infinite; }
  @keyframes pulse { 50% { opacity: .35; } }
  .paused .pulse { animation: none; background: #FFD28A; }
  .stopped .pulse { animation: none; background: rgba(255,255,255,.5); }
  .warn { color: #FFD28A; font-size: var(--t-foot); }
  .btn { background: rgba(255,255,255,.14); color: var(--c-hud-text); box-shadow: none; border-radius: var(--r-full); }
  .btn:hover { background: rgba(255,255,255,.24) !important; }
  .btn i { width: 8px; height: 8px; border-radius: 2px; background: var(--c-rec); }
  .btn.icon { width: 28px; padding: 0; justify-content: center; }
</style>
