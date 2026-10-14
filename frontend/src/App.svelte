<script>
  import { keyOf } from "./lib/keys.js";
  import Rail, { RAIL_PATHS } from "./components/Rail.svelte";
  import TopBar from "./components/TopBar.svelte";
  import CommandPalette from "./components/CommandPalette.svelte";
  import RecordingHud from "./components/RecordingHud.svelte";
  import Toast from "./components/Toast.svelte";
  import Meetings from "./screens/Meetings.svelte";
  import Meeting from "./screens/Meeting.svelte";
  import Settings from "./screens/Settings.svelte";
  import Atoms from "./screens/Atoms.svelte";
  import DocumentScreen from "./screens/Document.svelte";
  import Skills from "./screens/Skills.svelte";
  import Backlog from "./screens/Backlog.svelte";
  import Export from "./screens/Export.svelte";
  import Library from "./screens/Library.svelte";
  import Ask from "./screens/Ask.svelte";
  import Whisper from "./screens/Whisper.svelte";
  import Onboarding from "./screens/Onboarding.svelte";
  import Tutorial from "./components/Tutorial.svelte";
  import { onb, loadOnboarding } from "./lib/onboarding.svelte.js";
  import { api, setProgressTranslator, setLangSource, setJobStartedHook } from "./lib/api.js";
  import { actionFor } from "./lib/hotkeys.js";
  import { cap, recordFromShell, stopRecording } from "./lib/capture.svelte.js";
  import { toggleWhisper } from "./lib/whisper.svelte.js";
  import { progressText } from "./lib/progress.js";
  import { app, t, go, loadProjects, loadSources, setLang, applyTheme, setTheme, isDark, loadStatus, undoLast, toggleInspector, jobsTick } from "./lib/state.svelte.js";

  let ready = $state(false);
  let error = $state("");

  applyTheme();
  setProgressTranslator(progressText);
  setLangSource(() => app.lang);
  setJobStartedHook(jobsTick);
  // Screens rebuilt on panes; the others still scroll as one page inside the main area.
  const INSPECTOR = { transcript: "source", atoms: "atoms", document: "document", backlog: "backlog", skills: "skills" };
  // The first run (5.0 C8) replaces the shell until it is done; #/onboarding opens it again from Help.
  const onboarding = $derived(ready && (!onb.done || app.route.name === "onboarding"));
  function onKey(e) {
    if (onboarding) return;
    const key = keyOf(e);
    if ((e.metaKey || e.ctrlKey) && !e.shiftKey && (key === "z" || key === "Z")
        && !e.target.closest?.("input:not([type=checkbox]), textarea, [contenteditable]")) {
      if (undoLast()) e.preventDefault();
      return;
    }
    if ((e.metaKey || e.ctrlKey) && e.altKey && e.code === "KeyI" && INSPECTOR[app.route.name]) {
      e.preventDefault();
      toggleInspector(INSPECTOR[app.route.name]);
      return;
    }
    // Everything else comes from the hotkeys map (settings; the defaults until it has loaded).
    const action = actionFor(e, app.settings?.hotkeys);
    if (!action) return;
    // A binding without ⌘ (⌥Space) must not fire while the BA is typing.
    if (!(e.metaKey || e.ctrlKey) && e.target.closest?.("input:not([type=checkbox]), textarea, select, [contenteditable]")) return;
    if (action === "record") {
      if (!app.device.desktop) return;            // a browser tab keeps ⌘R as the reload
      e.preventDefault();
      recordFromShell();
    } else if (action === "palette") { e.preventDefault(); app.palette = !app.palette; }
    else if (action === "theme") { e.preventDefault(); setTheme(isDark() ? "light" : "dark"); }
    else if (action === "ask") {
      e.preventDefault();
      go("/ask");
      requestAnimationFrame(() => window.dispatchEvent(new CustomEvent("dictum:ask-focus")));   // the composer
    }
    else if (action === "whisper") {      // go to Шепнуть and start listening; pressed again while listening, stop
      e.preventDefault();
      go("/whisper");
      toggleWhisper();
    }
    else if (/^nav\d$/.test(action)) {
      const path = RAIL_PATHS[Number(action.slice(3)) - 1];
      if (path) { e.preventDefault(); app.palette = false; go(path); }
    }
  }
  // macOS: the global hot keys and the menu-bar item (core/hotkeys.py) bring the window forward and send their
  // action here; the same handlers as the keys, plus "record_stop" from the menu while a meeting records.
  function onGlobalAction(e) {
    if (onboarding) return;
    const action = e.detail?.action;
    if (action === "whisper") { go("/whisper"); toggleWhisper(); }
    else if (action === "record") recordFromShell();
    else if (action === "record_stop" && cap.recording) stopRecording();
  }
  $effect(() => {
    window.addEventListener("dictum:hotkey", onGlobalAction);
    return () => window.removeEventListener("dictum:hotkey", onGlobalAction);
  });
  // The empty address opens Встречи, the home page.
  $effect(() => {
    if (ready && app.route.name === "home") go("/meetings");
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
      api("/settings").then(s => (app.settings = s)).catch(() => {});   // hotkeys; the defaults work meanwhile
      if (!models.includes(app.options.model)) app.options.model = models[0];
      if (app.options.device !== "cpu" && !device.cuda && !device.mps) app.options.device = "cpu";
      if (app.options.device === "cuda" && !device.cuda && device.mps) app.options.device = "mps";
      await loadProjects();
      await loadSources();
      await loadOnboarding();
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
{:else if onboarding}
  <Onboarding />
  <Toast />
{:else if ready}
  <div class="shell">
    <Rail />
    <main class="main">
      <TopBar />
      <div class="page">
        {#if app.route.name === "meetings"}
          <Meetings />
        {:else if app.route.name === "atoms"}
          <Atoms />
        {:else if app.route.name === "document"}
          <DocumentScreen />
        {:else if app.route.name === "backlog"}
          <Backlog />
        {:else if app.route.name === "export"}
          <Export />
        {:else if app.route.name === "skills"}
          <Skills />
        {:else if app.route.name === "transcript"}
          {#key app.route.id}<Meeting id={app.route.id} autoSummarize={app.route.summarize} focusSeg={app.route.seg} />{/key}
        {:else if app.route.name === "settings"}
          <Settings />
        {:else if app.route.name === "library"}
          <Library />
        {:else if app.route.name === "ask"}
          {#key app.currentProjectId}<Ask />{/key}
        {:else if app.route.name === "whisper"}
          <Whisper />
        {/if}
      </div>
    </main>
  </div>
  <CommandPalette />
  <RecordingHud />
  <Toast />
  {#if onb.tutorial}<Tutorial />{/if}
{/if}

<style>
  .boot-error { margin: var(--sp-9) auto; width: min(560px, 90vw); }
</style>
