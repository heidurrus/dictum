<script>
  // The tips after the first run (5.0 C8, prototype-v5 tutorial()): a spotlight cut out over one element of the shell
  // (#t-rec, #t-whisper, #t-list, #t-library, #t-ask) and a card next to it. Esc closes; it follows resizes.
  import { onb, TUTORIAL } from "../lib/onboarding.svelte.js";
  import { t } from "../lib/state.svelte.js";

  const PAD = 8, TIP_W = 320;
  const id = $derived(TUTORIAL[onb.tutorial - 1]);
  let rect = $state(null);           // the target's box, or null when it is not on screen (phone width)
  let tip = $state(null);
  let tipH = $state(180);
  let viewport = $state({ w: window.innerWidth, h: window.innerHeight });

  function measure() {
    viewport = { w: window.innerWidth, h: window.innerHeight };
    const el = id && document.getElementById("t-" + id);
    const r = el?.getBoundingClientRect();
    rect = r && r.width && r.height ? { left: r.left, top: r.top, width: r.width, height: r.height, right: r.right } : null;
  }
  // The target may render a moment later (Встречи loading): measure again for a short while.
  $effect(() => {
    id;
    measure();
    let n = 0;
    const timer = setInterval(() => { measure(); if (++n > 10) clearInterval(timer); }, 100);
    return () => clearInterval(timer);
  });
  $effect(() => { if (tip) tipH = tip.offsetHeight; });

  const pos = $derived.by(() => {
    if (!rect) return { left: Math.max(16, (viewport.w - TIP_W) / 2), top: Math.max(16, (viewport.h - tipH) / 2) };
    const left = rect.right + 20 + TIP_W < viewport.w ? rect.right + 20 : Math.max(16, rect.left - TIP_W - 20);
    const top = Math.min(viewport.h - tipH - 16, Math.max(16, rect.top));
    return { left: Math.min(left, viewport.w - TIP_W - 16), top: Math.max(16, top) };
  });

  function close() { onb.tutorial = 0; }
  function next() { onb.tutorial = onb.tutorial < TUTORIAL.length ? onb.tutorial + 1 : 0; }
  function onKey(e) {
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(); }
  }
</script>

<svelte:window onresize={measure} onkeydowncapture={onKey} />

<div class="tut" role="dialog" aria-modal="true" aria-labelledby="tut-title">
  {#if rect}
    <div class="spot" style:left={rect.left - PAD + "px"} style:top={rect.top - PAD + "px"}
         style:width={rect.width + PAD * 2 + "px"} style:height={rect.height + PAD * 2 + "px"}></div>
  {:else}
    <div class="scrim"></div>
  {/if}
  <div class="tip" bind:this={tip} style:left={pos.left + "px"} style:top={pos.top + "px"} data-target={"t-" + id}>
    <h4 id="tut-title">{t("tut." + id)}</h4>
    <p>{t(`tut.${id}_d`)}</p>
    <div class="row">
      <span class="n">{t("tut.n", { n: onb.tutorial, total: TUTORIAL.length })}</span>
      <div class="right">
        <button class="btn sm ghost" onclick={close}>{t("tut.close")}</button>
        <!-- svelte-ignore a11y_autofocus -->
        <button class="btn sm primary" onclick={next} autofocus>{onb.tutorial < TUTORIAL.length ? t("tut.next") : t("tut.done")}</button>
      </div>
    </div>
  </div>
</div>

<style>
  .tut { position: fixed; inset: 0; z-index: 60; }
  .scrim { position: absolute; inset: 0; background: rgba(10,10,14,.55); }
  .spot { position: absolute; border-radius: 20px; box-shadow: 0 0 0 9999px rgba(10,10,14,.55); transition: all .3s; pointer-events: none; }
  .tip { position: absolute; width: 320px; max-width: calc(100vw - 32px); background: var(--surface); color: var(--text); border-radius: 20px;
    padding: 18px 20px; box-shadow: var(--shadow-3); animation: fade .25s; transition: left .3s, top .3s; }
  h4 { font-size: 15px; font-weight: 600; margin-bottom: 6px; }
  p { color: var(--text-2); font-size: 13px; line-height: 19px; }
  .row { display: flex; align-items: center; gap: 8px; margin-top: 14px; padding-top: 12px; border-top: 1px solid var(--outline-2); }
  .n { color: var(--text-3); font-size: 12px; }
  .right { margin-left: auto; display: flex; gap: 6px; }
</style>
