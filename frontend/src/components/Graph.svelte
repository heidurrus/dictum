<script>
  // The materials graph (spec 5.0 C5; prototype-v5 graphView() and layout()): materials as nodes coloured by their
  // first label, edges between materials that are similar in meaning (GET /api/projects/<id>/materials/graph).
  // The selected node and its edges are highlighted; a click selects the material. +/− zoom, the third button centres.
  import Icon from "./Icon.svelte";
  import { t } from "../lib/state.svelte.js";

  let { nodes = [], edges = [], selected = null, truncated = false, onselect } = $props();
  let zoom = $state(1);

  const W = 600, H = 460, NONE = "#5F6368";

  // Force layout, deterministic: the prototype's layout() with its constants (repulsion 6000/d², springs towards
  // 240 − 120·w, a pull to the centre), 300 iterations.
  function layout(ids, links) {
    const pos = ids.map((id, i) => ({ id, x: 300 + 180 * Math.cos(i * 2.4), y: 230 + 150 * Math.sin(i * 2.4) }));
    const at = Object.fromEntries(pos.map(p => [p.id, p]));
    for (let it = 0; it < 300; it++) {
      for (const a of pos) for (const b of pos) if (a !== b) {
        const dx = a.x - b.x, dy = a.y - b.y, d = Math.max(30, Math.hypot(dx, dy)), k = 6000 / (d * d);
        a.x += dx / d * k; a.y += dy / d * k;
      }
      for (const { a, b, w } of links) if (at[a] && at[b]) {
        const dx = at[b].x - at[a].x, dy = at[b].y - at[a].y, d = Math.hypot(dx, dy) || 1, k = (d - (240 - 120 * w)) * .02;
        at[a].x += dx / d * k; at[a].y += dy / d * k; at[b].x -= dx / d * k; at[b].y -= dy / d * k;
      }
      for (const p of pos) {
        p.x += (300 - p.x) * .006; p.y += (230 - p.y) * .006;
        p.x = Math.max(70, Math.min(530, p.x)); p.y = Math.max(50, Math.min(400, p.y));
      }
    }
    return at;
  }
  const at = $derived(layout(nodes.map(n => n.id), edges));
  const shown = $derived(edges.filter(e => at[e.a] && at[e.b]));
  const legend = $derived([...new Map(nodes.filter(n => n.label).map(n => [n.label, n.color])).entries()]);
  const short = s => (s.length > 26 ? s.slice(0, 25) + "…" : s);
  const badge = n => (n.ext || "txt").toUpperCase().slice(0, 3);
  function key(e, id) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onselect?.(id); } }
</script>

<div class="graph">
  <svg viewBox="0 0 {W} {H}" style:transform="scale({zoom})" role="group" aria-label={t("lib.view.graph")}>
    {#each shown as e (e.a + e.b)}
      <line class="edge" class:hot={e.a === selected || e.b === selected} x1={at[e.a].x} y1={at[e.a].y} x2={at[e.b].x} y2={at[e.b].y}
            stroke-opacity={Math.min(1, .3 + e.w)} />
    {/each}
    {#each nodes as n (n.id)}
      <g class="gnode" class:on={n.id === selected} data-id={n.id} transform="translate({at[n.id].x},{at[n.id].y})" role="button" tabindex="0"
         aria-label={n.title} aria-pressed={n.id === selected} onclick={() => onselect?.(n.id)} onkeydown={e => key(e, n.id)}>
        <circle r={n.id === selected ? 20 : 16} fill={n.color || NONE} />
        <text class="k">{badge(n)}</text>
        <text y="34" text-anchor="middle">{short(n.title)}</text>
      </g>
    {/each}
  </svg>
  <div class="gtools">
    <button onclick={() => (zoom = Math.min(2, zoom + .2))} title={t("lib.graph.zoom_in")} aria-label={t("lib.graph.zoom_in")}>+</button>
    <button onclick={() => (zoom = Math.max(.6, zoom - .2))} title={t("lib.graph.zoom_out")} aria-label={t("lib.graph.zoom_out")}>−</button>
    <button onclick={() => (zoom = 1)} title={t("lib.graph.center")} aria-label={t("lib.graph.center")}><Icon name="search" size={14} /></button>
  </div>
  <div class="glegend">
    {#each legend as [name, color] (name)}<span><i style:background={color}></i>{name}</span>{/each}
    <span class="t3">· {t("lib.graph.legend")}</span>
  </div>
  {#if truncated}<div class="gtrunc">{t("lib.graph.truncated", { n: nodes.length })}</div>{/if}
</div>

<style>
  /* prototype-v5 "Library: labels and graph" */
  .graph { position: relative; flex: 1; min-height: 360px; overflow: hidden; border-radius: 0 0 24px 24px;
    background: radial-gradient(circle at 50% 40%, var(--surface-2), transparent 70%); }
  svg { width: 100%; height: 100%; display: block; transition: transform .15s; }
  .edge { stroke: var(--outline); stroke-width: 1.5; opacity: .7; }
  .edge.hot { stroke: var(--primary); stroke-width: 2.5; opacity: 1; }
  .gnode { cursor: pointer; outline: none; }
  .gnode circle { stroke: var(--surface); stroke-width: 3; transition: r .15s; }
  .gnode:hover circle, .gnode:focus-visible circle { r: 22; }
  .gnode.on circle { stroke: var(--primary); stroke-width: 4; }
  .gnode text { font: 500 11px var(--font); fill: var(--text-2); pointer-events: none; }
  .gnode.on text { fill: var(--text); font-weight: 600; }
  .gnode .k { font: 700 9px var(--mono); fill: #fff; text-anchor: middle; dominant-baseline: central; }
  .gtools { position: absolute; right: 12px; top: 12px; display: flex; gap: 6px; }
  .gtools button { width: 32px; height: 32px; border-radius: 10px; border: 0; background: var(--surface); box-shadow: var(--shadow-1);
    display: grid; place-items: center; color: var(--text-2); font: 600 15px/1 var(--font); cursor: pointer; }
  .gtools button:hover { background: var(--surface-2); }
  .glegend { position: absolute; left: 12px; bottom: 12px; right: 12px; width: fit-content; display: flex; gap: 10px; flex-wrap: wrap; font-size: 12px;
    color: var(--text-2); background: var(--surface); padding: 6px 10px; border-radius: 10px; box-shadow: var(--shadow-1); }
  .glegend i { width: 9px; height: 9px; border-radius: 50%; display: inline-block; margin-right: 5px; }
  .gtrunc { position: absolute; left: 12px; top: 12px; font-size: 12px; color: var(--text-2); background: var(--surface); padding: 6px 10px;
    border-radius: 10px; box-shadow: var(--shadow-1); max-width: 60%; }
</style>
