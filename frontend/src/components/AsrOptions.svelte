<script>
  // Speech recognition on this machine: the device and who-said-what. The models are cards in Settings → Модели,
  // which hosts this component; the record panel on Встречи shows only a one-line summary of the model.
  import { app, t, saveOptions } from "../lib/state.svelte.js";
</script>

<div class="opts">
  <div class="field">
    <span class="label">{t("opt.device")}</span>
    <div class="seg" role="group" aria-label={t("opt.device")}>
      <button aria-pressed={app.options.device === "cpu"} onclick={() => { app.options.device = "cpu"; saveOptions(); }}>CPU</button>
      <button aria-pressed={app.options.device !== "cpu"} disabled={!app.device.cuda && !app.device.mps}
              onclick={() => { app.options.device = app.device.cuda ? "cuda" : "mps"; saveOptions(); }}>GPU</button>
    </div>
    <p class="hint">{t("asr.device_hint")}</p>
  </div>
  <label class="sw"><span><b>{t("opt.diarize")}</b><span class="hint">{t("opt.diarize_d")}</span></span>
    <input type="checkbox" class="switch" bind:checked={app.options.diarize} onchange={saveOptions} /></label>
  {#if !app.options.diarize}
    <label class="sw"><span><b>{t("opt.words")}</b><span class="hint">{t("opt.words_d")}</span></span>
      <input type="checkbox" class="switch" bind:checked={app.options.word_timestamps} onchange={saveOptions} /></label>
  {/if}
</div>

<style>
  .opts { display: grid; gap: var(--s-6); grid-template-columns: minmax(0, 1fr); }
  .field { justify-items: start; }
  .sw { display: flex; align-items: center; gap: var(--s-6); justify-content: space-between; cursor: pointer; }
  .sw b { font-weight: var(--w-medium); display: block; }
  .sw .hint { display: block; }
</style>
