<script>
  // Settings → Модели (5.0 C9): the provider, speech cards (/api/asr/models), language-model cards and the index model
  // (/api/local-llm), the "Claude (облако)" card with its key, the machine line and the stats row (/api/stats).
  import Icon from "./Icon.svelte";
  import AsrOptions from "./AsrOptions.svelte";
  import { api } from "../lib/api.js";
  import { app, t, saveOptions, toast } from "../lib/state.svelte.js";

  let { s, save } = $props();

  let asr = $state(null);          // {models, download}
  let llm = $state(null);          // /api/local-llm
  let stats = $state(null);
  let period = $state("7d");
  let keyDraft = $state("");
  let showKey = $state(false);
  let hfDraft = $state("");
  let showHf = $state(false);
  let ollama = $state(null);
  let asrTimer = null, llmTimer = null;
  const busy = d => ["downloading", "verifying"].includes(d?.status);

  async function loadAsr() {
    try { asr = await api("/api/asr/models"); } catch (err) { toast(err.message, { kind: "danger" }); return; }
    clearTimeout(asrTimer);
    if (busy(asr.download)) asrTimer = setTimeout(loadAsr, 1000);
  }
  async function loadLlm() {
    try { llm = await api("/api/local-llm"); } catch (err) { toast(err.message, { kind: "danger" }); return; }
    clearTimeout(llmTimer);
    if (busy(llm.download)) llmTimer = setTimeout(loadLlm, 1000);
  }
  async function loadStats() {
    try { stats = await api(`/api/stats?period=${period}`); } catch (_) { stats = null; }
  }
  $effect(() => { loadAsr(); loadLlm(); return () => { clearTimeout(asrTimer); clearTimeout(llmTimer); }; });
  $effect(() => { period; loadStats(); });
  $effect(() => { if (s.llm_provider === "ollama") checkOllama(); });
  async function checkOllama() { ollama = (await api("/ollama/status").catch(() => ({ reachable: false }))).reachable; }

  // A finished or failed download is reported once.
  let asrLast = null, llmLast = null;
  $effect(() => {
    const d = asr?.download;
    if (!d || d.status === asrLast) return;
    if (asrLast && d.status === "done") toast(t("asr.downloaded", { name: d.model }));
    if (asrLast && d.status === "error") toast(d.error, { kind: "danger" });
    asrLast = d.status;
  });
  $effect(() => {
    const d = llm?.download;
    if (!d || d.status === llmLast) return;
    if (llmLast && d.status === "done") toast(t("llm.downloaded"));
    if (llmLast && d.status === "error") toast(d.error, { kind: "danger" });
    llmLast = d.status;
  });

  // ── speech ──
  const asrDl = $derived(busy(asr?.download) ? asr.download : null);
  let allAsr = $state(false);
  // The ones that matter by default: what is on disk, the recommended one and the faster sibling; the rest on request.
  const asrShown = $derived(!asr ? [] : allAsr ? asr.models : asr.models.filter(m => m.installed || m.recommended || m.damaged
    || m.partial || m.id === "v3_e2e_ctc" || m.id === app.options.model || asrDl?.model === m.id));
  async function asrDownload(id) {
    try { asr = await api(`/api/asr/models/${id}/download`, { method: "POST" }); asrLast = asr.download?.status; loadAsr(); }
    catch (err) { toast(err.message, { kind: "danger" }); }
  }
  async function asrCancel() { asr = await api("/api/asr/download/cancel", { method: "POST" }); setTimeout(loadAsr, 300); }
  async function asrRemove(m) {
    if (!confirm(t("asr.delete_confirm", { name: m.id }))) return;
    try {
      asr = await api(`/api/asr/models/${m.id}`, { method: "DELETE" });
      if (app.options.model === m.id) { app.options.model = asr.models.find(x => x.installed)?.id || "v3_e2e_rnnt"; saveOptions(); }
    } catch (err) { toast(err.message, { kind: "danger" }); }
  }
  function asrPick(id) { app.options.model = id; saveOptions(); }

  // ── language models and the index model ──
  const llmDl = $derived(busy(llm?.download) ? llm.download : null);
  const activeLocal = $derived(llm ? (llm.models.find(m => m.installed && m.id === s.local_model) || llm.models.find(m => m.installed)) : null);
  async function llmDownload(id) {
    try { llm = await api("/api/local-llm/download", { method: "POST", body: { model: id } }); llmLast = llm.download.status; loadLlm(); }
    catch (err) { toast(err.message, { kind: "danger" }); }
  }
  async function llmCancel() { await api("/api/local-llm/cancel", { method: "POST" }); setTimeout(loadLlm, 300); }
  async function llmRemove(m) {
    if (!confirm(t("llm.delete_confirm", { name: m.label }))) return;
    try { llm = await api(`/api/local-llm/models/${m.id}`, { method: "DELETE" }); } catch (err) { toast(err.message, { kind: "danger" }); }
  }
  async function saveKey() { if (!keyDraft.trim()) return; await save({ anthropic_api_key: keyDraft.trim() }); keyDraft = ""; }
  async function saveHf() { if (!hfDraft.trim()) return; await save({ hf_token: hfDraft.trim() }); hfDraft = ""; }

  const gb = n => (n / 1024 ** 3).toLocaleString(app.lang, { maximumFractionDigits: 1 });
  const mb = n => (n / 1048576 >= 1000 ? gb(n) + " " + t("llm.gb") : Math.round(n / 1048576).toLocaleString(app.lang) + " " + t("asr.mb"));
  const machineLine = $derived.by(() => {
    const m = llm?.machine;
    if (!m?.ram) return "";
    const ram = Math.round(m.ram / 1024 ** 3);
    if (m.chip) return t("set.m.machine_chip", { ram, chip: m.chip });
    return t(m.os === "darwin" ? "set.m.machine_mac" : "set.m.machine", { ram });
  });

  // ── stats ──
  const compact = n => new Intl.NumberFormat(app.lang, { notation: "compact", maximumFractionDigits: 1 }).format(n || 0);
  const minutes = sec => Math.round((sec || 0) / 60);
  const tiles = $derived(stats ? [
    ["tokens_local", compact(stats.tokens_local), t("set.st.tokens_local")],
    ["meetings", compact(stats.meetings), t("set.st.meetings", { n: stats.meetings })],
    ["asr", compact(minutes(stats.seconds_transcribed)), t("set.st.asr_min", { n: minutes(stats.seconds_transcribed) })],
    ["embeddings", compact(stats.embeddings), t("set.st.embeddings", { n: stats.embeddings })],
    ["cloud", compact(stats.cloud_calls), t("set.st.cloud", { n: stats.cloud_calls, tokens: compact(stats.tokens_cloud) })],
  ] : []);
</script>

<div class="setcard card-m" id="set-provider">
  <h3>{t("set.provider")}</h3><p class="d">{t("set.provider_hint." + s.llm_provider)}</p>
  <div class="row">
    <div class="seg provider" role="group" aria-label={t("set.provider")}>
      {#each ["claude", "local", "ollama"] as p (p)}
        <button aria-pressed={s.llm_provider === p} onclick={() => save({ llm_provider: p })}>{t("set.provider." + p)}</button>
      {/each}
    </div>
  </div>
  {#if s.llm_provider === "ollama"}
    <div class="row">
      <label class="l" for="omodel"><b>{t("set.ollama_model")}</b>
        {#if ollama !== null}<small class:ok={ollama} class:bad={!ollama}>{ollama ? t("set.ollama_running") : t("set.ollama_stopped")}</small>{/if}
        <small>{t("set.ollama_note")}</small></label>
      <input class="input code w-220" id="omodel" value={s.ollama_model} placeholder="qwen3:8b"
             onchange={e => save({ ollama_model: e.currentTarget.value.trim() || "qwen3:8b" })} />
    </div>
  {/if}
  {#if machineLine}<p class="machine t2">{machineLine}</p>{/if}
</div>

<div class="setcard card-m" id="set-llm">
  <h3>{t("onb.m.llm")}</h3><p class="d">{t("set.m.llm_d")}</p>
  {#if llm}
    {#if !llm.supported}<p class="note warn">{t("llm.unsupported")}</p>{/if}
    <div class="models">
      {#if llm.supported}
        {#each llm.models as m (m.id)}
          {@const on = s.llm_provider === "local" && activeLocal?.id === m.id}
          <div class="model llm-card" class:on class:dim={!m.fits} data-model={m.id}>
            <b>{m.label}</b>
            <small>{t("set.m.needs", { n: m.min_ram_gb })} · {gb(m.size)} {t("llm.gb")}</small>
            <div class="tags">
              {#if on}<span class="tag ok">{t("set.m.active")}</span>{:else if m.installed}<span class="tag">{t("onb.m.installed")}</span>{/if}
              {#if m.recommended}<span class="tag accent">{t("onb.m.recommended")}</span>{/if}
              {#if !m.fits}<span class="tag danger low-ram">{t("set.m.no_ram")}</span>{/if}
              {#if m.speed}<span class="tag speed" class:warn={m.speed !== "fast"}>{t("set.m.speed." + m.speed)}</span>{/if}
            </div>
            <div class="acts">
              {#if llmDl && llmDl.model === m.id}
                <div class="dl"><div class="progress"><i style="width: {Math.round(100 * llmDl.done / Math.max(llmDl.total, 1))}%"></i></div>
                  <span class="t3 num">{llmDl.status === "verifying" ? t("llm.verifying") : `${gb(llmDl.done)} / ${gb(llmDl.total)} ${t("llm.gb")}`}</span></div>
                <button class="btn sm ghost" onclick={llmCancel}>{t("at.cancel")}</button>
              {:else if m.installed}
                {#if !on}<button class="btn sm" onclick={() => save({ llm_provider: "local", local_model: m.id })}>{t("set.m.use")}</button>{/if}
                <button class="btn sm ghost danger" onclick={() => llmRemove(m)}>{t("llm.remove")}</button>
              {:else}
                <button class="btn sm" class:primary={m.recommended} disabled={!!llmDl} onclick={() => llmDownload(m.id)}>
                  <Icon name="download" size={14} /> {t("llm.download", { size: gb(m.size) })}</button>
              {/if}
            </div>
          </div>
        {/each}
      {/if}
      <div class="model claude-card" class:on={s.llm_provider === "claude"}>
        <b>{t("onb.m.claude")}</b>
        <small>{s.anthropic_key_set ? t("onb.m.claude_set") : t("onb.m.claude_d")}</small>
        <div class="tags"><span class="tag warn">{t("onb.m.cloud")}</span>
          {#if s.llm_provider === "claude"}<span class="tag ok">{t("set.m.active")}</span>{/if}</div>
        <div class="acts">
          {#if s.llm_provider !== "claude"}<button class="btn sm" onclick={() => save({ llm_provider: "claude" })}>{t("set.m.use")}</button>{/if}
        </div>
      </div>
    </div>
    {#if llm.download?.status === "error"}<p class="note danger">{llm.download.error}</p>{/if}
    <p class="hint">{t("llm.note", { free: gb(llm.disk_free) })} {t("llm.quality_note")}</p>
  {/if}
  <div class="row col">
    <label class="l" for="akey"><b>{t("set.anthropic_key")}</b>
      <small class:ok={s.anthropic_key_set} class:bad={!s.anthropic_key_set}>{s.anthropic_key_set ? t("set.key_set") : t("set.key_unset")}</small></label>
    <div class="input-row">
      <input class="input code" id="akey" type={showKey ? "text" : "password"} bind:value={keyDraft} autocomplete="off"
             placeholder={s.anthropic_key_set ? t("set.key_saved_placeholder") : "sk-ant-..."} />
      <button class="btn" onclick={() => (showKey = !showKey)}>{showKey ? t("set.hide") : t("set.show")}</button>
      <button class="btn btn-primary" onclick={saveKey} disabled={!keyDraft.trim()}>{t("set.save")}</button>
    </div>
  </div>
  <div class="row">
    <label class="l" for="cmodel"><b>{t("set.claude_model")}</b><small>{t("set.claude_note")}</small></label>
    <select class="select w-220" id="cmodel" value={s.claude_model} onchange={e => save({ claude_model: e.currentTarget.value })}>
      {#each s.claude_models as m (m.id)}<option value={m.id}>{t("model." + m.id) === "model." + m.id ? m.label : t("model." + m.id)}</option>{/each}
    </select>
  </div>
</div>

<div class="setcard card-m stats-card" id="set-stats">
  <div class="stats-head">
    <div><h3>{t("set.st.title")}</h3>
      {#if stats}<p class="d stats-line">{t("set.st.line." + period, { tokens: compact(stats.tokens_local), meetings: stats.meetings, cloud: stats.cloud_calls })}</p>{/if}</div>
    <div class="seg period" role="group" aria-label={t("set.st.period")}>
      {#each ["7d", "30d", "all"] as p (p)}
        <button aria-pressed={period === p} onclick={() => (period = p)}>{t("set.st.p." + p)}</button>
      {/each}
    </div>
  </div>
  <div class="tiles">
    {#each tiles as [k, value, label] (k)}
      <div class="tile" data-stat={k}><b class="num">{value}</b><small>{label}</small></div>
    {/each}
  </div>
</div>

{#if llm?.supported && llm.embed_models?.length}
  <div class="setcard card-m" id="set-index">
    <h3>{t("onb.m.index")}</h3><p class="d">{t("set.m.index_d")}</p>
    <div class="models">
      {#each llm.embed_models as m (m.id)}
        {@const on = m.installed && (!s.embed_model || s.embed_model === m.id)}
        <div class="model index-card" class:on data-model={m.id}>
          <b>{m.label}</b>
          <small>{gb(m.size)} {t("llm.gb")} · {t("set.m.index_used")}</small>
          {#if on}<span class="tag ok">{t("set.m.active")}</span>{:else if m.installed}<span class="tag">{t("onb.m.installed")}</span>{/if}
          <div class="acts">
            {#if llmDl && llmDl.model === m.id}
              <div class="dl"><div class="progress"><i style="width: {Math.round(100 * llmDl.done / Math.max(llmDl.total, 1))}%"></i></div></div>
              <button class="btn sm ghost" onclick={llmCancel}>{t("at.cancel")}</button>
            {:else if m.installed}
              {#if llm.embed_models.length > 1 && !on}<button class="btn sm" onclick={() => save({ embed_model: m.id })}>{t("set.m.use")}</button>{/if}
              <button class="btn sm ghost danger" onclick={() => llmRemove(m)}>{t("llm.remove")}</button>
            {:else}
              <button class="btn sm primary" disabled={!!llmDl} onclick={() => llmDownload(m.id)}>
                <Icon name="download" size={14} /> {t("llm.download", { size: gb(m.size) })}</button>
            {/if}
          </div>
        </div>
      {/each}
    </div>
  </div>
{/if}

<div class="setcard card-m" id="set-asr">
  <h3>{t("onb.m.asr")}</h3><p class="d">{t("set.m.asr_d")}</p>
  {#if asr}
    <div class="models">
      {#each asrShown as m (m.id)}
        <div class="model asr-card" class:on={m.installed && app.options.model === m.id} data-model={m.id}>
          <b class="mono">{m.id}</b>
          <small>{t("asr.m." + m.id)} · {mb(m.size)} · {m.langs === "multi" ? t("asr.multi") : t("asr.ru")}</small>
          {#if m.installed && app.options.model === m.id}<span class="tag ok">{t("set.m.active")}</span>
          {:else if m.installed}<span class="tag">{t("onb.m.installed")}</span>
          {:else if m.recommended}<span class="tag accent">{t("onb.m.recommended")}</span>{/if}
          <div class="acts">
            {#if asrDl && asrDl.model === m.id}
              <div class="dl"><div class="progress"><i style="width: {Math.round(100 * asrDl.done / Math.max(asrDl.total, 1))}%"></i></div>
                <span class="t3 num">{asrDl.status === "verifying" ? t("llm.verifying") : `${mb(asrDl.done)} / ${mb(asrDl.total)}`}</span></div>
              <button class="btn sm ghost" onclick={asrCancel}>{t("at.cancel")}</button>
            {:else if m.installed}
              {#if app.options.model !== m.id}<button class="btn sm" onclick={() => asrPick(m.id)}>{t("set.m.use")}</button>{/if}
              <button class="btn sm ghost danger" onclick={() => asrRemove(m)}>{t("llm.remove")}</button>
            {:else if m.damaged || m.partial}
              <span class="status danger"><Icon name="warn" size={12} /> {t("asr.damaged")}</span>
              <button class="btn sm" disabled={!!asrDl} onclick={() => asrDownload(m.id)}><Icon name="download" size={14} /> {t("asr.redownload")}</button>
            {:else}
              <button class="btn sm" class:primary={m.recommended} disabled={!!asrDl} onclick={() => asrDownload(m.id)}>
                <Icon name="download" size={14} /> {t("asr.download", { size: mb(m.size) })}</button>
            {/if}
          </div>
        </div>
      {/each}
    </div>
    {#if asrShown.length < asr.models.length}
      <button class="btn sm ghost more" onclick={() => (allAsr = true)}>{t("set.m.all_asr", { n: asr.models.length })}</button>
    {/if}
    <p class="hint">{t("asr.note")}</p>
  {/if}
  <div class="row col"><AsrOptions list={false} /></div>
  <div class="row col">
    <label class="l" for="hf"><b>{t("set.hf_token")}</b>
      <small class:ok={s.hf_token_set} class:bad={!s.hf_token_set}>{s.hf_token_set ? t("set.hf_set") : t("set.hf_unset")}</small></label>
    <div class="input-row">
      <input class="input code" id="hf" type={showHf ? "text" : "password"} bind:value={hfDraft} autocomplete="off"
             placeholder={s.hf_token_set ? t("set.key_saved_placeholder") : "hf_..."} />
      <button class="btn" onclick={() => (showHf = !showHf)}>{showHf ? t("set.hide") : t("set.show")}</button>
      <button class="btn btn-primary" onclick={saveHf} disabled={!hfDraft.trim()}>{t("set.save")}</button>
    </div>
    <div class="hint hf-note">
      {t("set.hf_note")}
      <ul>
        <li><a href="https://huggingface.co/settings/tokens" target="_blank" rel="noopener">huggingface.co/settings/tokens</a></li>
        <li><a href="https://huggingface.co/pyannote/segmentation-3.0" target="_blank" rel="noopener">pyannote/segmentation-3.0</a></li>
        <li><a href="https://huggingface.co/pyannote/speaker-diarization-3.1" target="_blank" rel="noopener">pyannote/speaker-diarization-3.1</a></li>
        <li><a href="https://huggingface.co/pyannote/speaker-diarization-community-1" target="_blank" rel="noopener">pyannote/speaker-diarization-community-1</a></li>
      </ul>
    </div>
  </div>
</div>

<style>
  .w-220 { min-width: 220px; width: auto; max-width: 100%; flex: none; }
  .machine { margin-top: 12px; font-size: 13px; }
  .models { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 10px; margin: 4px 0 12px; }
  .model { position: relative; border-radius: 16px; padding: 14px 16px; background: var(--surface-2); color: var(--text); display: grid; gap: 4px;
    align-content: start; }
  .model.on { box-shadow: inset 0 0 0 2px var(--primary); background: var(--primary-c); color: var(--on-primary-c); }
  .model.dim:not(.on) { opacity: .7; }
  .model b { font-size: 14px; padding-right: 84px; }
  .model b.mono { font-family: var(--mono); font-size: 13px; }
  .model small { color: var(--text-2); font-size: 12px; } .model.on small { color: inherit; opacity: .8; }
  .model > .tag { position: absolute; top: 12px; right: 12px; }
  .tags { display: flex; flex-wrap: wrap; gap: 4px; }
  .acts { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin-top: 6px; }
  .dl { display: grid; gap: 4px; flex: 1; min-width: 120px; }
  .dl .progress { height: 6px; border-radius: 3px; background: var(--surface-3); overflow: hidden; display: block; }
  .dl .progress i { display: block; height: 100%; background: var(--primary); transition: width .4s; }
  .more { margin: -4px 0 8px; }
  .hf-note ul { margin: 4px 0 0; padding-left: 20px; }
  .ok { color: var(--ok) !important; } .bad { color: var(--danger) !important; }
  .stats-head { display: flex; align-items: flex-start; gap: 12px; flex-wrap: wrap; }
  .stats-head > div:first-child { flex: 1; min-width: 220px; }
  .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 10px; margin-top: 8px; }
  .tile { border-radius: 14px; background: var(--surface-2); padding: 12px 14px; display: grid; gap: 2px; }
  .tile b { font-size: 22px; line-height: 28px; font-weight: 600; }
  .tile small { color: var(--text-2); font-size: 12px; }
</style>
