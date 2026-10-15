<script>
  // The meeting's language (5.0.5): Russian or Multilingual, in the record panel and the import menu on Встречи.
  // Preselected from the project; a pick is this meeting's language and the project's next default. Each language
  // stands for the speech model chosen in Settings → Модели; a missing one shows its Download button here.
  import Icon from "./Icon.svelte";
  import { api } from "../lib/api.js";
  import { app, t, toast, asrModelFor, projectAsrLang, setProjectAsrLang } from "../lib/state.svelte.js";

  let { onsettings = null } = $props();
  const uid = $props.id();

  let asr = $state(null);                // /api/asr/models
  let timer = null;
  const busy = d => ["downloading", "verifying"].includes(d?.status);
  async function load() {
    try { asr = await api("/api/asr/models"); } catch (err) { toast(err.message, { kind: "danger" }); return; }
    clearTimeout(timer);
    if (busy(asr.download)) timer = setTimeout(load, 1000);
  }
  $effect(() => { load(); return () => clearTimeout(timer); });

  const lang = $derived(projectAsrLang());
  const modelId = $derived(asr?.langs?.[lang] || asrModelFor(lang));
  const model = $derived(asr?.models.find(m => m.id === modelId) || null);
  const dl = $derived(busy(asr?.download) && asr.download.model === modelId ? asr.download : null);
  const mb = n => (n / 1048576 >= 1000 ? (n / 1073741824).toLocaleString(app.lang, { maximumFractionDigits: 1 }) + " " + t("llm.gb")
                                        : Math.round(n / 1048576).toLocaleString(app.lang) + " " + t("asr.mb"));
  async function download() {
    try { asr = await api(`/api/asr/models/${modelId}/download`, { method: "POST" }); load(); }
    catch (err) { toast(err.message, { kind: "danger" }); }
  }
</script>

<div class="ml" data-lang={lang} data-model={modelId} data-installed={model ? String(!!model.installed) : ""}>
  <div class="ml-head">
    <Icon name="transcript" size={16} />
    <span class="grow" id="{uid}-label">{t("mlang.title")}</span>
    {#if onsettings}<button class="linkish" onclick={onsettings}>{t("mlang.models")}</button>{/if}
  </div>
  <div class="seg ml-seg" role="group" aria-labelledby="{uid}-label">
    {#each ["ru", "multi"] as l (l)}
      <button aria-pressed={lang === l} data-lang={l} onclick={() => setProjectAsrLang(l)}>{t("mlang." + l)}</button>
    {/each}
  </div>
  <p class="hint">{t("mlang." + lang + "_hint")} · <span class="mono">{modelId}</span>{#if model?.installed}{" · "}{t("meet.rp.installed")}{/if}</p>
  {#if model && !model.installed}
    <div class="ml-warn" role="status">
      <span><Icon name="warn" size={14} /> {t("mlang.not_installed")}</span>
      {#if dl}
        <div class="ml-dl"><div class="progress"><i style="width: {Math.round(100 * dl.done / Math.max(dl.total, 1))}%"></i></div>
          <span class="t3 num">{dl.status === "verifying" ? t("llm.verifying") : `${mb(dl.done)} / ${mb(dl.total)}`}</span></div>
      {:else}
        <button class="btn sm ml-download" disabled={busy(asr?.download)} onclick={download}>
          <Icon name="download" size={14} /> {t("asr.download", { size: mb(model.size) })}</button>
      {/if}
    </div>
  {/if}
</div>

<style>
  .ml { display: grid; gap: var(--s-3); font-size: var(--size-foot); color: var(--text); }
  .ml-head { display: flex; align-items: center; gap: var(--s-4); min-height: var(--h-ctl-sm); }
  .ml-head :global(svg) { color: var(--text-3); flex: none; }
  .ml-head .grow { min-width: 0; }
  .ml-seg { display: flex; width: 100%; }
  .ml-seg button { flex: 1; }
  .ml .hint { margin: 0; }
  .linkish { border: 0; background: none; padding: 0; color: var(--primary); font: inherit; cursor: pointer; white-space: nowrap; margin-left: auto; }
  .linkish:hover { text-decoration: underline; }
  .linkish:focus-visible { box-shadow: var(--ring); border-radius: var(--r-s); }
  .ml-warn { display: grid; gap: var(--s-3); justify-items: start; padding: var(--s-4) var(--s-5); border-radius: var(--r-m);
    background: var(--warn-c); color: var(--warn); }
  .ml-warn :global(svg) { vertical-align: -2px; }
  .ml-dl { display: grid; gap: var(--s-2); width: 100%; }
</style>
