<script>
  // The pane grid of a screen: [outline] content [inspector] [context].
  // Widths come from the workspace through container queries; nothing here is a fixed column.
  import { app, inspectorOn } from "../lib/state.svelte.js";

  let { screen = "", wideOutline = false, comparing = false, outline, inspector, context, children, contentClass = "" } = $props();
  const off = $derived(!!screen && !inspectorOn(screen));
  function onKey(e) {
    if (e.key === "Escape" && app.inspectorOverlay) app.inspectorOverlay = false;
  }
</script>

<svelte:window onkeydown={onKey} />

<div class="panes" class:has-outline={!!outline} class:wide-outline={wideOutline} class:has-inspector={!!inspector}
     class:has-context={!!context && !comparing} class:no-insp={off} class:insp-open={app.inspectorOverlay} class:comparing>
  {#if outline}<aside class="pane outline secondary">{@render outline()}</aside>{/if}
  <section class="pane content {contentClass}">{@render children?.()}</section>
  {#if inspector}<aside class="pane inspector secondary">{@render inspector()}</aside>{/if}
  {#if context && !comparing}<aside class="pane context secondary">{@render context()}</aside>{/if}
</div>
