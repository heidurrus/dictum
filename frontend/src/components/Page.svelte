<script>
  // One page = the headline row (back crumb, title, status line, actions, inspector toggle) and the workspace
  // card under it (prototype-v5 .page-head and .card). The card holds the screen's Panes as its columns.
  import Icon from "./Icon.svelte";
  import { app, t, go, toggleInspector, inspectorOn } from "../lib/state.svelte.js";
  import { recordFromShell } from "../lib/capture.svelte.js";

  let { title = "", crumb = "", crumbPath = "", sub = "", inspector = "", record = true, heading, actions, children } = $props();
</script>

<header class="page-head toolbar screen-head">
  <div class="tb-title">
    {#if crumb}
      <button class="crumb" onclick={() => go(crumbPath)} aria-label={t("shell.back", { name: crumb })} title={t("shell.back", { name: crumb })}>
        <Icon name="back" size={14} />{crumb}</button>
    {/if}
    {#if heading}{@render heading()}
    {:else}
      <h1 class="screen-title">{title}</h1>
    {/if}
    {#if sub}<p class="screen-sub">{sub}</p>{/if}
  </div>
  <div class="tb-actions">
    {@render actions?.()}
    <!-- Phone width: the rail's record button moves here, unless the screen has its own (Sources: `record={false}`). -->
    {#if record}
      <button class="ph-rec" onclick={recordFromShell} aria-label={t("shell.record")} title={t("shell.record_tip")}><span class="dot"></span></button>
    {/if}
    {#if inspector}
      <button class="btn ghost icon" class:on={inspectorOn(inspector) || app.inspectorOverlay} onclick={() => toggleInspector(inspector)}
              aria-label={t("shell.inspector")} aria-pressed={inspectorOn(inspector)} title={`${t("shell.inspector")} · ⌥⌘I`}>
        <Icon name="inspector" /></button>
    {/if}
  </div>
</header>
<div class="workspace card-m">
  {@render children?.()}
</div>

<style>
  .on { color: var(--primary); }
  .tb-title :global(.title-btn) { border: 0; background: none; padding: 0; font: inherit; color: inherit; cursor: text; text-align: left; max-width: 100%; }
  .crumb { display: inline-flex; align-items: center; gap: 4px; justify-self: start; height: 24px; padding: 0 8px 0 4px; margin: 0 0 2px -4px;
    border: 0; border-radius: 12px; background: none; color: var(--text-2); font-size: 13px; font-weight: 500; cursor: pointer; }
  .crumb:hover { background: var(--surface-2); color: var(--text); }
  .ph-rec { display: none; width: 40px; height: 40px; border: 0; border-radius: 20px; background: var(--primary-c); place-items: center;
    cursor: pointer; flex: none; }
  .ph-rec .dot { width: 12px; height: 12px; border-radius: 50%; background: var(--rec); box-shadow: 0 0 0 3px rgba(217,48,37,.2); }
  @media (max-width: 760px) { .ph-rec { display: grid; } }
</style>
