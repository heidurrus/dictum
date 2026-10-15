<script>
  // Built-in local model: one-click download with progress, pick, delete.
  import Icon from "./Icon.svelte";
  import { api } from "../lib/api.js";
  import { app, t, toast } from "../lib/state.svelte.js";

  let { selected = "", onSelect, onReady, only = null } = $props();

  let st = $state(null);
  let timer = null;

  async function load() {
    try { st = await api("/api/local-llm"); } catch (err) { toast(err.message, { kind: "danger" }); }
    clearTimeout(timer);
    if (["downloading", "verifying"].includes(st?.download?.status)) timer = setTimeout(load, 1000);
  }
  $effect(() => { load(); return () => clearTimeout(timer); });

  // Report a finished or failed download once.
  let lastStatus = null;
  $effect(() => {
    const d = st?.download;
    if (!d || d.status === lastStatus) return;
    if (lastStatus && d.status === "done") {
      toast(t("llm.downloaded"));
      if (onReady) onReady();
      if (!selected && onSelect) onSelect(d.model);
    }
    if (lastStatus && d.status === "error") toast(d.error, { kind: "danger" });
    lastStatus = d.status;
  });

  async function download(id) {
    try { st = await api("/api/local-llm/download", { method: "POST", body: { model: id } }); lastStatus = st.download.status; load(); }
    catch (err) { toast(err.message, { kind: "danger" }); }
  }
  async function cancel() { await api("/api/local-llm/cancel", { method: "POST" }); setTimeout(load, 300); }
  async function remove(m) {
    if (!confirm(t("llm.delete_confirm", { name: m.label }))) return;
    try { st = await api(`/api/local-llm/models/${m.id}`, { method: "DELETE" }); } catch (err) { toast(err.message, { kind: "danger" }); }
  }

  const gb = n => (n / 1024 ** 3).toLocaleString(app.lang, { maximumFractionDigits: 1 });
  // `only`: show just this model (e.g. the recommended one, in a compact prompt).
  const shown = $derived(st ? st.models.filter(m => !only || m.id === (only === "recommended" ? st.recommended : only)) : []);
  const active = $derived(st ? (st.models.find(m => m.installed && m.id === selected) || st.models.find(m => m.installed)) : null);
  const dl = $derived(st?.download?.status === "downloading" || st?.download?.status === "verifying" ? st.download : null);
</script>

{#if st}
  {#if !st.supported}
    <p class="note warn">{t("llm.unsupported")}</p>
  {:else}
    {#if st.gpu && st.gpu.name}
      <p class="hint gpu">{t("llm.gpu", { name: st.gpu.name, gb: gb(st.gpu.memory) })}</p>
    {:else if st.gpu}
      <p class="note warn">{t("llm.no_gpu")}</p>
    {/if}
    <ul class="models">
      {#each shown as m (m.id)}
        <li class="model" class:on={active?.id === m.id}>
          <label class="pick">
            <input type="radio" name="local-model" class:hidden={!!only} checked={active?.id === m.id} disabled={!m.installed}
                   onchange={() => onSelect && onSelect(m.id)} />
            <span class="name">
              <b>{m.label}</b>
              {#if m.recommended}<span class="tag accent">{t("llm.recommended")}</span>{/if}
              {#if !m.fits}<span class="tag warn">{t("llm.low_ram", { n: m.min_ram_gb })}</span>
              {:else if m.speed === "partial"}<span class="tag warn">{t("llm.speed.partial")}</span>
              {:else if m.speed === "slow" && st.gpu?.name}<span class="tag warn">{t("llm.speed.slow")}</span>{/if}
              <span class="hint">{t("llm.meta", { size: gb(m.size), ram: m.min_ram_gb })}</span>
            </span>
          </label>
          <div class="side">
            {#if dl && dl.model === m.id}
              <div class="dl">
                <div class="bar"><i style="width: {Math.round(100 * dl.done / dl.total)}%"></i></div>
                <span class="mono faint">{dl.status === "verifying" ? t("llm.verifying") : `${gb(dl.done)} / ${gb(dl.total)} ${t("llm.gb")}`}</span>
              </div>
              <button class="btn btn-sm btn-ghost" onclick={cancel}>{t("at.cancel")}</button>
            {:else if m.installed}
              <span class="tag ok">{st.running === m.id ? t("llm.running") : t("llm.installed")}</span>
              <button class="btn sm ghost danger" onclick={() => remove(m)}>{t("llm.remove")}</button>
            {:else}
              <button class="btn btn-sm" class:btn-primary={m.recommended} disabled={!!dl} onclick={() => download(m.id)}>
                <Icon name="download" size={14} /> {t("llm.download", { size: gb(m.size) })}
              </button>
            {/if}
          </div>
        </li>
      {/each}
    </ul>
    {#if st.download?.status === "error"}<p class="note danger">{st.download.error}</p>{/if}
    <p class="hint">{t("llm.note", { free: gb(st.disk_free) })}</p>
  {/if}
{/if}

<style>
  .gpu { margin-bottom: var(--s-4); }
  .note.warn { margin-bottom: var(--s-4); }
  .models { list-style: none; margin: 0; padding: 0; border-radius: var(--r-m); box-shadow: 0 0 0 1px var(--outline); overflow: hidden; }
  .model { display: flex; align-items: center; gap: var(--s-5); flex-wrap: wrap; padding: var(--s-5); }
  .model + .model { border-top: 1px solid var(--outline-2); }
  .model.on { background: var(--primary-c); }
  .pick { display: flex; align-items: flex-start; gap: var(--s-5); flex: 1 1 260px; min-width: 0; cursor: pointer; }
  .pick input { margin-top: 4px; accent-color: var(--primary); }
  .pick input:disabled { cursor: default; }
  .name { display: flex; flex-wrap: wrap; align-items: center; gap: var(--s-2) var(--s-4); min-width: 0; }
  .name b { font-weight: 500; }
  .name .hint { flex-basis: 100%; }
  .side { display: flex; align-items: center; gap: var(--s-4); margin-left: auto; }
  .dl { display: flex; flex-direction: column; gap: var(--s-2); width: 180px; }
</style>
