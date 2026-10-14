<script>
  import { keyOf } from "./lib/keys.js";
  import Rail from "./components/Rail.svelte";
  import TopBar from "./components/TopBar.svelte";
  import CommandPalette from "./components/CommandPalette.svelte";
  import RecordingHud from "./components/RecordingHud.svelte";
  import Overview from "./screens/Overview.svelte";
  import Toast from "./components/Toast.svelte";
  import Sources from "./screens/Sources.svelte";
  import Transcript from "./screens/Transcript.svelte";
  import Settings from "./screens/Settings.svelte";
  import Atoms from "./screens/Atoms.svelte";
  import DocumentScreen from "./screens/Document.svelte";
  import Skills from "./screens/Skills.svelte";
  import Backlog from "./screens/Backlog.svelte";
  import Export from "./screens/Export.svelte";
  import Soon from "./screens/Soon.svelte";
  import { api, setProgressTranslator, setLangSource } from "./lib/api.js";
  import { progressText } from "./lib/progress.js";
  import { app, t, go, loadProjects, loadSources, setLang, applyTheme, setTheme, isDark, loadStatus, undoLast, toggleInspector } from "./lib/state.svelte.js";

  let ready = $state(false);
  let error = $state("");

  applyTheme();
  setProgressTranslator(progressText);
  setLangSource(() => app.lang);
  // Screens rebuilt on panes; the others still scroll as one page inside the main area.
  const INSPECTOR = { transcript: "source", atoms: "atoms", document: "document", backlog: "backlog", skills: "skills", sources: "sources" };
  function onKey(e) {
    const key = keyOf(e);
    if ((e.metaKey || e.ctrlKey) && !e.shiftKey && (key === "z" || key === "Z")
        && !e.target.closest?.("input:not([type=checkbox]), textarea, [contenteditable]")) {
      if (undoLast()) e.preventDefault();
      return;
    }
    if ((e.metaKey || e.ctrlKey) && e.shiftKey && (key === "l" || key === "L")) {
      e.preventDefault();
      setTheme(isDark() ? "light" : "dark");
      return;
    }
    if ((e.metaKey || e.ctrlKey) && e.altKey && e.code === "KeyI" && INSPECTOR[app.route.name]) {
      e.preventDefault();
      toggleInspector(INSPECTOR[app.route.name]);
    }
  }
  // The empty address opens the overview, or Sources while the project has nothing in it.
  $effect(() => {
    if (ready && app.route.name === "home") go(app.sources.length ? "/overview" : "/sources");
  });
  $effect(() => { app.atomsVersion; loadStatus(); });

  async function boot() {
    setLang(app.lang);
    try {
      const [device, models, health] = await Promise.all([
        api("/device-info"), api("/models"), api("/health").catch(() => null)]);
      app.device = device;
      app.models = models;
      app.health = health;
      if (!models.includes(app.options.model)) app.options.model = models[0];
      if (app.options.device !== "cpu" && !device.cuda && !device.mps) app.options.device = "cpu";
      if (app.options.device === "cuda" && !device.cuda && device.mps) app.options.device = "mps";
      await loadProjects();
      await loadSources();
      ready = true;
    } catch (err) {
      error = err.message;
    }
  }
  boot();
</script>

<svelte:window onkeydown={onKey} />

{#if error}
  <div class="boot-error note danger">{t("err.generic", { error })}</div>
{:else if ready}
  <div class="shell">
    <Rail />
    <main class="main">
      <TopBar />
      <div class="page">
        {#if app.route.name === "overview"}
          <Overview />
        {:else if app.route.name === "atoms"}
          <Atoms />
        {:else if app.route.name === "sources"}
          <Sources />
        {:else if app.route.name === "document"}
          <DocumentScreen />
        {:else if app.route.name === "backlog"}
          <Backlog />
        {:else if app.route.name === "export"}
          <Export />
        {:else if app.route.name === "skills"}
          <Skills />
        {:else if app.route.name === "transcript"}
          {#key app.route.id}<Transcript id={app.route.id} autoSummarize={app.route.summarize} focusSeg={app.route.seg} />{/key}
        {:else if app.route.name === "settings"}
          <Settings />
        {:else if app.route.name === "library"}
          <Soon title={t("nav.library")} icon="file" />
        {:else if app.route.name === "ask"}
          <Soon title={t("nav.ask")} icon="search" />
        {:else if app.route.name === "whisper"}
          <Soon title={t("nav.whisper")} icon="mic" />
        {/if}
      </div>
    </main>
  </div>
  <CommandPalette />
  <RecordingHud />
  <Toast />
{/if}

<style>
  .boot-error { margin: var(--sp-9) auto; width: min(560px, 90vw); }
</style>
