<script>
  // The recording pill of the meeting page (prototype-v5 .audio-pill): live dot, state, pause/resume, stop.
  // After two minutes without speech it counts down to the auto-stop (5.0 C4.3).
  import Icon from "./Icon.svelte";
  import { t } from "../lib/state.svelte.js";

  let { paused = false, busy = false, silence = 0, silenceStop = 0, ontoggle, onstop } = $props();
  const HINT_AFTER = 120;
  const mmss = s => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
  const countdown = $derived(!paused && silenceStop > 0 && silence >= HINT_AFTER
    ? t("live.silence_hint", { quiet: mmss(silence), left: mmss(Math.max(0, silenceStop - silence)) }) : "");
</script>

<div class="audio-pill" class:paused role="status" aria-live="polite">
  <span class="live" aria-hidden="true"></span>
  <span class="state">{paused ? t("live.paused") : t("rec.recording")}</span>
  {#if countdown}<span class="quiet num">{countdown}</span>{/if}
  <button class="toggle" onclick={ontoggle} disabled={busy} title={paused ? t("live.resume") : t("live.pause")}
          aria-label={paused ? t("live.resume") : t("live.pause")}><Icon name={paused ? "play" : "pause"} size={18} /></button>
  <button class="stop" onclick={onstop} disabled={busy} title={t("live.stop_tip")} aria-label={t("live.stop_tip")}>
    <Icon name="stop" size={18} /></button>
</div>

<style>
  .audio-pill { display: inline-flex; align-items: center; gap: 4px; height: 48px; padding: 0 6px 0 16px; border-radius: 24px;
    background: var(--hud); color: var(--hud-text); flex: none; }
  .live { width: 10px; height: 10px; border-radius: 50%; background: var(--rec); margin-right: 8px; animation: pulse 1.6s infinite; }
  .paused .live { animation: none; background: var(--warn); }
  @keyframes pulse { 0%, 100% { box-shadow: 0 0 0 0 rgba(217,48,37,.35); } 50% { box-shadow: 0 0 0 10px rgba(217,48,37,0); } }
  .state { font-weight: 600; font-size: 13px; margin-right: 6px; white-space: nowrap; }
  .quiet { font-size: 12px; opacity: .75; margin-right: 6px; white-space: nowrap; }
  button { width: 36px; height: 36px; border-radius: 18px; display: grid; place-items: center; color: var(--hud-text);
    background: none; border: 0; cursor: pointer; padding: 0; }
  button:hover:not(:disabled) { background: var(--hud-2); }
  button:disabled { opacity: .6; cursor: default; }
  .stop { background: var(--rec); color: #fff; }
  .stop:hover:not(:disabled) { background: #c22a1f; }
  @media (prefers-reduced-motion: reduce) { .live { animation: none; } }
</style>
