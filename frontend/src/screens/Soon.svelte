<script>
  // Rail sections that ship in later 5.0 updates (Материалы, Спросить, Шепнуть): the headline and an empty state.
  import Page from "../components/Page.svelte";
  import Icon from "../components/Icon.svelte";
  import { t, currentProject } from "../lib/state.svelte.js";

  let { title = "", icon = "" } = $props();
</script>

<Page {title} sub={currentProject()?.name || ""}>
  <div class="empty soon">
    <span class="glyph" aria-hidden="true"><Icon name={icon} size={24} /></span>
    <h3>{title}</h3>
    <p>{t("shell.soon")}</p>
  </div>
</Page>

<style>
  .soon { height: 100%; align-content: center; }
</style>
