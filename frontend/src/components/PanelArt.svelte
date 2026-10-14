<script>
  // The welcome step's three illustrated panels (prototype-v5 .panel-art): CSS drawings, no bitmaps.
  import { t } from "../lib/state.svelte.js";

  let { kind } = $props();          // "record" | "review" | "docs"
  const TEXT = { record: ["onb.w.p1", "onb.w.p1_d"], review: ["onb.w.p2", "onb.w.p2_d"], docs: ["onb.w.p3", "onb.w.p3_d"] };
</script>

<div class="panel-art">
  <div class="art" aria-hidden="true">
    {#if kind === "record"}
      <div class="line" style="left:16px;top:18px;width:60%"></div>
      <div class="line" style="left:16px;top:36px;width:40%"></div>
      <div class="line" style="left:16px;top:54px;width:70%"></div>
      <div class="hud"><b>{t("onb.w.p1_hud")}</b>{t("onb.w.p1_hud_d")}</div>
    {:else if kind === "review"}
      <div class="cardlet" style="left:14px;top:14px;right:40px"><b>{t("onb.w.p2_c1")}</b>{t("onb.w.p2_c1_d")}</div>
      <div class="cardlet" style="left:30px;top:66px;right:14px"><b>{t("onb.w.p2_c2")}</b>{t("onb.w.p2_c2_d")}</div>
      <div class="cardlet" style="left:14px;top:118px;right:60px"><b>{t("onb.w.p2_c3")}</b>{t("onb.w.p2_c3_d")}</div>
    {:else}
      <div class="cardlet" style="left:14px;top:14px;right:14px;bottom:14px;padding:12px"><b>{t("onb.w.p3_c")}</b>
        <div class="line flow" style="margin:8px 0 6px;width:80%"></div>
        <div class="line flow" style="margin:0 0 6px;width:60%"></div>
        <div class="line flow" style="width:70%"></div>
      </div>
    {/if}
  </div>
  <h3>{t(TEXT[kind][0])}</h3>
  <p>{t(TEXT[kind][1])}</p>
</div>

<style>
  .panel-art { background: var(--surface); border-radius: 24px; padding: 20px; box-shadow: var(--shadow-1); min-height: 240px; display: grid;
    grid-template-rows: 1fr auto auto; gap: 4px; }
  .art { border-radius: 16px; background: linear-gradient(160deg, #EEF2FF, #F7E9FF); position: relative; overflow: hidden; min-height: 160px;
    margin-bottom: 10px; }
  .line { position: absolute; height: 10px; border-radius: 5px; background: rgba(27,27,33,.12); }
  .line.flow { position: static; }
  .hud { position: absolute; left: 14px; right: 14px; bottom: 12px; background: var(--hud); border-radius: 12px; padding: 10px; color: var(--hud-text);
    font-size: 11px; line-height: 15px; }
  .hud b { display: block; font-size: 12px; margin-bottom: 2px; }
  .cardlet { position: absolute; background: var(--surface); color: var(--text); border-radius: 10px; padding: 8px 10px; font-size: 11px;
    box-shadow: var(--shadow-1); line-height: 14px; }
  .cardlet b { display: block; font-size: 12px; }
  h3 { font-size: 15px; font-weight: 600; color: var(--text); }
  p { color: var(--text-2); font-size: 13px; }
  :global(:root[data-theme="dark"]) .art { background: linear-gradient(160deg, #22263A, #2D2340); }
  :global(:root[data-theme="dark"]) .line { background: rgba(255,255,255,.14); }
  @media (prefers-color-scheme: dark) {
    :global(:root:not([data-theme="light"])) .art { background: linear-gradient(160deg, #22263A, #2D2340); }
    :global(:root:not([data-theme="light"])) .line { background: rgba(255,255,255,.14); }
  }
</style>
