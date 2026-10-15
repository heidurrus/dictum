<script>
  // The context pane (redesign §5.19): the source around one line, so a requirement can be read
  // where it was said without leaving the screen.
  import Icon from "./Icon.svelte";
  import { api } from "../lib/api.js";
  import { fmtTime, speakerDisplay } from "../lib/format.js";
  import { t, go } from "../lib/state.svelte.js";

  let { sourceId = null, segmentIdx = null, quote = "", title = "", head = "" } = $props();

  const cache = new Map();                // source id → segments
  let segments = $state([]);
  let body = $state(null);

  $effect(() => {
    const id = sourceId;
    if (!id) { segments = []; return; }
    if (!cache.has(id)) cache.set(id, api(`/api/sources/${id}`).then(s => s.segments).catch(() => []));
    cache.get(id).then(s => { if (sourceId === id) segments = s; });
  });
  const at = $derived(segments.findIndex(s => s.idx === segmentIdx));
  const lines = $derived(at < 0 ? segments.slice(0, 40) : segments.slice(Math.max(0, at - 12), at + 13));
  $effect(() => {
    lines; segmentIdx;
    requestAnimationFrame(() => body?.querySelector(".hit")?.scrollIntoView({ block: "center" }));
  });
  const speakers = $derived([...new Set(segments.map(s => s.speaker).filter(Boolean))]);

  function mark(text, q) {
    const i = text.toLowerCase().indexOf((q || "").toLowerCase());
    if (!q || i < 0) return [{ t: text }];
    return [{ t: text.slice(0, i) }, { t: text.slice(i, i + q.length), m: true }, { t: text.slice(i + q.length) }];
  }
</script>

<div class="pane-head">
  <h2 class="trunc grow">{head || title}</h2>
  {#if sourceId}
    <button class="btn sm ghost" onclick={() => go(`/source/${sourceId}${segmentIdx != null ? "/seg/" + segmentIdx : ""}`)}>
      {t("ctx.open_source")} <Icon name="arrow" size={12} /></button>
  {/if}
</div>
<div class="pane-body scroll" bind:this={body}>
  {#if !sourceId}
    <p class="none">{t("ctx.none")}</p>
  {:else}
    {#if head && title}<p class="src t3 trunc">{title}</p>{/if}
    {#each lines as l (l.idx)}
      <div class="line" class:hit={l.idx === segmentIdx}>
        <time class="mono t3">{l.start != null ? fmtTime(l.start) : ""}</time>
        <div>
          {#if l.speaker}<span class="spk spk-{Math.max(0, speakers.indexOf(l.speaker)) % 5}">{speakerDisplay(l.speaker, l.speaker_name, t)}</span>{/if}
          <p>{#if l.idx === segmentIdx}{#each mark(l.text, quote) as part, k (k)}{#if part.m}<mark>{part.t}</mark>{:else}{part.t}{/if}{/each}{:else}{l.text}{/if}</p>
        </div>
      </div>
    {/each}
  {/if}
</div>

<style>
  /* 5.0: the evidence context card; the quoted line on the tonal primary container. */
  .pane-head { height: 56px; padding: 0 20px; border-bottom-color: var(--outline-2); }
  .pane-head .btn { border-radius: 14px; }
  .none { padding: var(--s-9) var(--s-7); color: var(--text-3); text-align: center; }
  .src { padding: 14px 20px 0; font-size: 12px; }
  .line { display: grid; grid-template-columns: 44px minmax(0, 1fr); gap: var(--s-4); padding: 8px 20px; position: relative; }
  .line.hit { background: var(--primary-c); color: var(--on-primary-c); }
  .line.hit::before { content: ""; position: absolute; left: 0; top: 6px; bottom: 6px; width: 3px; border-radius: 0 3px 3px 0; background: var(--primary); }
  .line time { padding-top: 1px; }
  .line p { line-height: 20px; color: var(--text-2); text-wrap: pretty; }
  .line.hit p { color: inherit; }
  .spk { display: inline-flex; align-items: center; gap: var(--s-3); font-weight: 600; font-size: 12px; }
  .spk::before { content: ""; width: 8px; height: 8px; border-radius: 50%; background: currentColor; flex: none; }
</style>
