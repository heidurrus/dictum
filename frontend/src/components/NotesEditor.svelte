<script>
  // Meeting notes (spec 5.0 C3, prototype-v5 .notes-editor / .fmt): raw Markdown in a textarea, saved by itself
  // a second after the last keystroke. The format bar inserts Markdown at the caret; the preview renders it.
  import { onDestroy, tick, untrack } from "svelte";
  import { api } from "../lib/api.js";
  import { renderMarkdown } from "../lib/format.js";
  import { app, t } from "../lib/state.svelte.js";
  import { comboLabel } from "../lib/hotkeys.js";

  let { sourceId, value = "", onsaved = () => {} } = $props();

  let text = $state("");
  let ta = $state(null);
  let preview = $state(false);
  let status = $state("idle");             // idle | saving | saved | error
  let savedAt = $state(null);
  let error = $state("");
  let timer = null;
  let dirty = false;

  // A line added on the server (the question card, later a whisper) arrives through `value`: take it unless
  // the BA has unsaved typing, which the next save sends anyway.
  $effect(() => { const v = value || ""; untrack(() => { if (!dirty && v !== text) text = v; }); });

  async function save() {
    clearTimeout(timer);
    timer = null;
    const sent = text;
    status = "saving";
    try {
      const r = await api(`/api/sources/${sourceId}/notes`, { method: "PUT", body: { text: sent } });
      savedAt = r.saved_at;
      if (text === sent) { dirty = false; status = "saved"; }
      onsaved(r.text);
    } catch (err) {
      status = "error";
      error = err.message;
    }
  }
  function changed() {
    dirty = true;
    status = "idle";
    clearTimeout(timer);
    timer = setTimeout(save, 1000);
  }
  // Leaving the page or the meeting with a save pending: send it now (keepalive survives a reload).
  function flush() {
    if (!timer) return;
    clearTimeout(timer);
    timer = null;
    fetch(`/api/sources/${sourceId}/notes`, { method: "PUT", keepalive: true, headers: { "Content-Type": "application/json" },
                                              body: JSON.stringify({ text }) }).catch(() => {});
  }
  onDestroy(flush);

  async function select(a, b) {
    await tick();
    ta?.focus();
    ta?.setSelectionRange(a, b);
  }
  function wrap(mark, placeholder) {
    if (!ta) return;
    const a = ta.selectionStart, b = ta.selectionEnd;
    const inner = text.slice(a, b) || placeholder;
    text = text.slice(0, a) + mark + inner + mark + text.slice(b);
    changed();
    select(a + mark.length, a + mark.length + inner.length);
  }
  const LIST = /^(\s*)(?:[-*•]\s\[[ xX]\]\s|[-*•]\s|\d+[.)]\s|#{1,6}\s)/;
  function prefix(p) {
    if (!ta) return;
    const a = ta.selectionStart, b = ta.selectionEnd;
    const start = text.lastIndexOf("\n", a - 1) + 1;
    let end = text.indexOf("\n", b);
    if (end < 0) end = text.length;
    const lines = text.slice(start, end).split("\n");
    const all = lines.every(l => l.startsWith(p));
    const out = lines.map((l, i) => {
      if (all) return l.slice(p.length);                               // pressing it again takes it off
      const bare = l.replace(LIST, "$1");
      return (p === "1. " ? `${i + 1}. ` : p) + bare;
    }).join("\n");
    text = text.slice(0, start) + out + text.slice(end);
    changed();
    select(start + out.length, start + out.length);
  }
  const TOOLS = [
    { label: "B", tip: "nt.b", key: "cmd+b", run: () => wrap("**", t("nt.bold_ph")), cls: "b" },
    { label: "I", tip: "nt.i", key: "cmd+i", run: () => wrap("*", t("nt.italic_ph")), cls: "i" },
    { label: "H", tip: "nt.h", run: () => prefix("## ") },
    { label: "•", tip: "nt.ul", run: () => prefix("- ") },
    { label: "1.", tip: "nt.ol", run: () => prefix("1. ") },
    { label: "☐", tip: "nt.todo", run: () => prefix("- [ ] ") },
  ];
  function onKey(e) {
    if (!(e.metaKey || e.ctrlKey) || e.altKey || e.shiftKey) return;
    const k = e.key.toLowerCase();
    if (k === "b" || k === "и") { e.preventDefault(); TOOLS[0].run(); }
    else if (k === "i" || k === "ш") { e.preventDefault(); TOOLS[1].run(); }
  }
  const clock = s => new Date(s * 1000).toLocaleTimeString(app.lang === "en" ? "en-GB" : "ru-RU", { hour: "2-digit", minute: "2-digit" });
</script>

<svelte:window onpagehide={flush} />

<div class="col-head">
  <h2>{t("meet.tab.notes")}</h2>
  <span class="t3 small notes-state" class:err={status === "error"} title={status === "error" ? error : undefined}>
    {#if status === "saving"}{t("nt.saving")}
    {:else if status === "error"}{t("nt.save_failed")}
    {:else if status === "saved" && savedAt}{t("nt.saved", { time: clock(savedAt) })}
    {:else}{t("nt.auto")}{/if}</span>
  <span class="grow"></span>
  {#if !preview}<span class="t3 small kbds">⌘B ⌘I</span>{/if}
  <button class="btn sm ghost" aria-pressed={preview} onclick={() => (preview = !preview)}>{preview ? t("nt.edit") : t("nt.preview")}</button>
</div>
{#if preview}
  <div class="notes-preview scroll">
    {#if text.trim()}<div class="md">{@html renderMarkdown(text)}</div>
    {:else}<p class="t3">{t("nt.empty")}</p>{/if}
  </div>
{:else}
  <div class="fmt" role="toolbar" aria-label={t("nt.format")}>
    {#each TOOLS as tool (tool.label)}
      <button class={tool.cls} title={t(tool.tip, { key: tool.key ? comboLabel(tool.key) : "" })} aria-label={t(tool.tip, { key: tool.key ? comboLabel(tool.key) : "" })} onmousedown={e => e.preventDefault()} onclick={tool.run}>{tool.label}</button>
    {/each}
  </div>
  <textarea class="notes-editor" bind:this={ta} bind:value={text} oninput={changed} onkeydown={onKey} onblur={() => timer && save()}
            placeholder={t("nt.ph")} aria-label={t("meet.tab.notes")} spellcheck="true"></textarea>
{/if}

<style>
  /* prototype-v5 "Session": .col-head, .fmt, .notes-editor */
  .col-head { display: flex; align-items: center; gap: 10px; padding: 12px 16px; border-bottom: 1px solid var(--outline-2); flex: none; min-width: 0; }
  .col-head h2 { font-size: 15px; font-weight: 600; }
  .small { font-size: 12px; }
  .notes-state { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0; }
  .notes-state.err { color: var(--danger); }
  .kbds { white-space: nowrap; }
  .fmt { display: flex; gap: 2px; padding: 6px 10px; border-bottom: 1px solid var(--outline-2); flex: none; }
  .fmt button { width: 30px; height: 30px; border: 0; border-radius: 8px; background: none; color: var(--text-2); font: 600 13px/1 var(--font); cursor: pointer; }
  .fmt button:hover { background: var(--surface-2); color: var(--text); }
  .fmt button.i { font-style: italic; }
  .notes-editor { flex: 1; min-height: 160px; width: 100%; border: 0; background: none; resize: none; outline: none; line-height: 22px;
    padding: 12px 16px; font: 400 14px/22px var(--font); color: var(--text); box-shadow: none; }
  .notes-preview { flex: 1; min-height: 160px; padding: 12px 16px; }
</style>
