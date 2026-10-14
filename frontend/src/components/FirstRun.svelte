<script>
  // The empty state of Встречи (redesign §8.10; 5.0 C8 keeps it for projects created after the first run): three rows,
  // name, AI check, first source, in the tonal 5.0 look.
  import Icon from "./Icon.svelte";
  import { api } from "../lib/api.js";
  import { explain } from "../lib/errors.js";
  import { app, t, go, currentProject, loadProjects, toast } from "../lib/state.svelte.js";

  let { onRecord, onImport } = $props();

  let settings = $state(null);
  let local = $state(null);
  let check = $state(null);              // {running} | {ok, message}
  let nameDraft = $state("");

  const pid = $derived(app.currentProjectId);
  const project = $derived(currentProject());
  const DEFAULT_NAMES = ["Мой проект", "My project"];

  async function load() {
    const [s, l] = await Promise.all([api("/settings").catch(() => null), api("/api/local-llm").catch(() => null)]);
    settings = s; local = l;
  }
  $effect(() => { pid; load(); });

  const aiReady = $derived.by(() => {
    if (!settings) return null;
    const localReady = local && local.models?.some(m => m.installed);
    if (project?.local_only) return !!localReady || settings.llm_provider === "ollama";
    if (settings.llm_provider === "claude") return settings.anthropic_key_set;
    if (settings.llm_provider === "local") return !!localReady;
    return true;
  });
  const named = $derived(!!project && !DEFAULT_NAMES.includes(project.name));
  const aiName = $derived(!settings ? "" : settings.llm_provider === "claude" ? t("first.ai_claude")
    : settings.llm_provider === "local" ? t("first.ai_local") : "Ollama");

  async function saveName() {
    const name = nameDraft.trim();
    if (!name) return;
    try {
      await api(`/api/projects/${pid}`, { method: "PATCH", body: { name } });
      await loadProjects();
      nameDraft = "";
    } catch (err) { toast(err.message, { kind: "danger" }); }
  }
  async function runCheck() {
    check = { running: true };
    try {
      const r = await api("/api/ai/check", { method: "POST", body: { project_id: pid } });
      check = r.ok ? { ok: true, message: t("home.ai_ok", { model: r.model }) } : { ok: false, message: explain({ message: r.error || "", body: r }).message };
    } catch (err) { check = { ok: false, message: explain(err).message }; }
  }
</script>

<div class="first">
  <div class="empty-glyph"><Icon name="sources" size={20} /></div>
  <h2>{t("first.title")}</h2>
  <p class="lead">{t("first.lead")}</p>

  <ol>
    <li class:done={named}>
      <span class="n">{#if named}<Icon name="check" size={12} />{:else}1{/if}</span>
      <div class="grow">
        <h3>{t("first.name")}</h3>
        {#if named}<p class="t3">{project.name}</p>
        {:else}
          <p class="t3">{t("home.d.name")}</p>
          <form onsubmit={e => { e.preventDefault(); saveName(); }}>
            <input class="input" bind:value={nameDraft} placeholder={t("home.name_ph")} aria-label={t("home.s.name")} />
            <button class="btn primary" disabled={!nameDraft.trim()}>{t("at.save")}</button>
          </form>
        {/if}
      </div>
    </li>
    <li class:done={!!aiReady}>
      <span class="n">{#if aiReady}<Icon name="check" size={12} />{:else}2{/if}</span>
      <div class="grow">
        <h3>{t("first.ai")}</h3>
        <p class="t3">{aiReady ? aiName : t("home.d.ai")}</p>
        {#if check && !check.running}<p class="check" class:ok={check.ok}>{check.message}</p>{/if}
        <div class="acts">
          {#if !aiReady}<button class="btn primary" onclick={() => go("/settings")}>{t("first.ai_setup")} <Icon name="arrow" size={14} /></button>{/if}
          <button class="btn" onclick={runCheck} disabled={check?.running}>{#if check?.running}<span class="spinner"></span>{/if}{t("first.ai_check")}</button>
        </div>
      </div>
    </li>
    <li>
      <span class="n">3</span>
      <div class="grow">
        <h3>{t("first.source")}</h3>
        <p class="t3">{aiReady === false ? t("first.source_wait") : t("first.source_d")}</p>
        <div class="acts">
          <button class="btn" class:primary={!!aiReady} onclick={onImport}><Icon name="upload" size={14} /> {t("src.import")}</button>
          <button class="btn" onclick={onRecord}><i class="recdot"></i> {t("sources.record.title")}</button>
        </div>
      </div>
    </li>
  </ol>
</div>

<style>
  .first { width: min(560px, 100%); margin: 0 auto; padding: 48px 24px; display: grid; grid-template-columns: minmax(0, 1fr); }
  .empty-glyph { margin: 0 auto 16px; width: 56px; height: 56px; border-radius: 18px; background: var(--primary-c); color: var(--on-primary-c); }
  h2 { font-size: 24px; line-height: 32px; font-weight: 600; letter-spacing: -.016em; text-align: center; color: var(--text); }
  .lead { text-align: center; color: var(--text-2); font-size: 15px; line-height: 22px; margin: 4px 0 24px; }
  ol { list-style: none; margin: 0; padding: 0; display: grid; gap: 10px; }
  li { display: flex; gap: 16px; padding: 16px 18px; border-radius: 20px; background: var(--surface-2); }
  .n { width: 28px; height: 28px; border-radius: 50%; background: var(--surface); display: grid; place-items: center; flex: none;
    font-size: 13px; font-weight: 600; color: var(--text-2); box-shadow: var(--shadow-1); }
  li.done { background: none; box-shadow: inset 0 0 0 1px var(--outline-2); }
  li.done .n { background: var(--ok-c); color: var(--ok); box-shadow: none; }
  h3 { font-size: 15px; line-height: 24px; font-weight: 500; color: var(--text); }
  li.done h3 { color: var(--text-2); }
  .t3 { color: var(--text-3); }
  form, .acts { display: flex; gap: 8px; margin-top: 12px; flex-wrap: wrap; }
  form .input { flex: 1; min-width: 200px; }
  .acts .btn, form .btn { border-radius: 20px; }
  .acts .btn:not(.primary) { background: var(--primary-c); color: var(--on-primary-c); box-shadow: none; }
  .check { margin-top: 8px; color: var(--danger); font-size: 13px; }
  .check.ok { color: var(--ok); }
  .recdot { width: 10px; height: 10px; border-radius: 50%; background: var(--rec); }
</style>
