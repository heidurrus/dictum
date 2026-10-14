<script>
  // Speech recognition: the model (what is on disk, what can be downloaded), the device, who-said-what.
  // `list={false}`: only the device and who-said-what (Settings → Модели shows the models as cards).
  import Icon from "./Icon.svelte";
  import PopMenu from "./PopMenu.svelte";
  import { api } from "../lib/api.js";
  import { app, t, saveOptions, toast } from "../lib/state.svelte.js";

  let { list = true } = $props();

  let st = $state(null);                 // {models, download}
  let timer = null;
  async function load() {
    try { st = await api("/api/asr/models"); } catch (err) { toast(err.message, { kind: "danger" }); return; }
    clearTimeout(timer);
    if (["downloading", "verifying"].includes(st?.download?.status)) timer = setTimeout(load, 1000);
  }
  $effect(() => { load(); return () => clearTimeout(timer); });

  let lastStatus = null;
  $effect(() => {
    const d = st?.download;
    if (!d || d.status === lastStatus) return;
    if (lastStatus && d.status === "done") { toast(t("asr.downloaded", { name: d.model })); }
    if (lastStatus && d.status === "error") toast(d.error, { kind: "danger" });
    lastStatus = d.status;
  });

  async function download(id) {
    try { st = await api(`/api/asr/models/${id}/download`, { method: "POST" }); lastStatus = st.download?.status; load(); }
    catch (err) { toast(err.message, { kind: "danger" }); }
  }
  async function cancel() { st = await api("/api/asr/download/cancel", { method: "POST" }); setTimeout(load, 300); }
  async function remove(m) {
    if (!confirm(t("asr.delete_confirm", { name: m.id }))) return;
    try {
      st = await api(`/api/asr/models/${m.id}`, { method: "DELETE" });
      if (app.options.model === m.id) { app.options.model = installed[0]?.id || "v3_e2e_rnnt"; saveOptions(); }
    } catch (err) { toast(err.message, { kind: "danger" }); }
  }
  function pick(id) { app.options.model = id; saveOptions(); }

  const mb = n => (n / 1048576 >= 1000 ? (n / 1073741824).toLocaleString(app.lang, { maximumFractionDigits: 1 }) + " " + t("llm.gb")
                                        : Math.round(n / 1048576).toLocaleString(app.lang) + " " + t("asr.mb"));
  const installed = $derived(st ? st.models.filter(m => m.installed) : []);
  const current = $derived(st ? st.models.find(m => m.id === app.options.model) : null);
  const dl = $derived(st?.download && ["downloading", "verifying"].includes(st.download.status) ? st.download : null);
</script>

<div class="opts">
  {#if list}
  <div class="field">
    <span class="label">{t("opt.model")}</span>
    {#if st}
      <PopMenu value={app.options.model} ariaLabel={t("opt.model")} onpick={pick}
               items={st.models.map(m => ({ value: m.id, label: m.id + (m.installed ? "" : " · " + t("asr.not_installed")), hint: m.langs === "multi" ? t("asr.multi") : "RU" }))} />
      {#if current && !current.installed}
        <p class="hint warn-t">{t("asr.pick_not_installed")}</p>
      {:else if current}<p class="hint">{t("asr.m." + current.id)}</p>{/if}
    {/if}
  </div>

  {#if st}
    <div class="field">
      <span class="label">{t("asr.on_disk")}</span>
      <ul class="models">
        {#each st.models as m (m.id)}
          <li class="model" class:on={m.id === app.options.model}>
            <div class="name">
              <b>{m.id}</b>
              {#if m.recommended}<span class="badge accent">{t("asr.recommended")}</span>{/if}
              <span class="badge">{m.langs === "multi" ? t("asr.multi") : t("asr.ru")}</span>
              <span class="hint">{t("asr.m." + m.id)} · {mb(m.size)}</span>
            </div>
            <div class="side">
              {#if dl && dl.model === m.id}
                <div class="dl">
                  <div class="progress"><i style="width: {Math.round(100 * dl.done / Math.max(dl.total, 1))}%"></i></div>
                  <span class="t3 num">{dl.status === "verifying" ? t("llm.verifying") : `${mb(dl.done)} / ${mb(dl.total)}`}</span>
                </div>
                <button class="btn sm ghost" onclick={cancel}>{t("at.cancel")}</button>
              {:else if m.installed}
                <span class="status ok"><Icon name="check" size={12} /> {t("llm.installed")}</span>
                <button class="btn sm ghost danger" onclick={() => remove(m)}>{t("llm.remove")}</button>
              {:else if m.damaged || m.partial}
                <span class="status danger"><Icon name="warn" size={12} /> {t("asr.damaged")}</span>
                <button class="btn sm" disabled={!!dl} onclick={() => download(m.id)}><Icon name="download" size={14} /> {t("asr.redownload")}</button>
              {:else}
                <button class="btn sm" class:primary={m.recommended} disabled={!!dl} onclick={() => download(m.id)}>
                  <Icon name="download" size={14} /> {t("asr.download", { size: mb(m.size) })}</button>
              {/if}
            </div>
          </li>
        {/each}
      </ul>
      <p class="hint">{t("asr.note")}</p>
    </div>
  {/if}
  {/if}

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
  .warn-t { color: var(--c-warn); }
  .sw { display: flex; align-items: center; gap: var(--s-6); justify-content: space-between; cursor: pointer; }
  .sw b { font-weight: var(--w-medium); display: block; }
  .sw .hint { display: block; }
  .models { list-style: none; margin: 0; padding: 0; width: 100%; border-radius: var(--r-md); box-shadow: 0 0 0 1px var(--c-line); background: var(--c-content); overflow: hidden; }
  .model { display: flex; align-items: center; gap: var(--s-5); flex-wrap: wrap; padding: var(--s-4) var(--s-5); }
  .model + .model { border-top: 1px solid var(--c-line); }
  .model.on { background: var(--c-accent-tint); }
  .name { display: flex; flex-wrap: wrap; align-items: center; gap: var(--s-2) var(--s-4); min-width: 0; flex: 1 1 260px; }
  .name b { font: var(--w-medium) var(--t-mono)/var(--lh-body) var(--font-mono); }
  .name .hint { flex-basis: 100%; }
  .side { display: flex; align-items: center; gap: var(--s-4); margin-left: auto; }
  .dl { display: grid; gap: var(--s-2); width: 180px; }
</style>
