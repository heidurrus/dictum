<script>
  // 16-px line icons (docs/design/prototype.html). Static markup only, never user data.
  let { name, size = 16 } = $props();
  const ICONS = {
    chevron: '<path d="M6 3.5L10.5 8 6 12.5"/>',
    chevd: '<path d="M3.5 6L8 10.5 12.5 6"/>',
    play: '<path d="M5 3.2v9.6L12.5 8z" fill="currentColor"/>',
    pause: '<path d="M5 3.5v9M11 3.5v9"/>',
    back: '<path d="M13 8H3M7 4L3 8l4 4"/>',
    arrow: '<path d="M3 8h10M9 4l4 4-4 4"/>',
    plus: '<path d="M8 3v10M3 8h10"/>',
    close: '<path d="M4 4l8 8M12 4l-8 8"/>',
    pencil: '<path d="M10.5 2.8l2.7 2.7-7.6 7.6-3.2.5.5-3.2z"/>',
    trash: '<path d="M2.8 4.3h10.4M6.3 4.3V2.8h3.4v1.5M4.2 4.3l.6 9h6.4l.6-9"/>',
    copy: '<rect x="5.3" y="5.3" width="8.2" height="8.2" rx="1.3"/><path d="M10.7 5.3V3.3c0-.5-.4-.8-.8-.8H3.3c-.5 0-.8.3-.8.8v6.6c0 .4.3.8.8.8h2"/>',
    download: '<path d="M8 2.5V11M4.8 7.8L8 11l3.2-3.2M2.5 11v1.8c0 .4.3.7.7.7h9.6c.4 0 .7-.3.7-.7V11"/>',
    upload: '<path d="M8 11V2.5M4.8 5.7L8 2.5l3.2 3.2M2.5 11v1.8c0 .4.3.7.7.7h9.6c.4 0 .7-.3.7-.7V11"/>',
    check: '<path d="M3.2 8.4l3 3 6.6-6.8"/>',
    mic: '<rect x="5.8" y="1.8" width="4.4" height="8" rx="2.2"/><path d="M3.5 7.8a4.5 4.5 0 0 0 9 0M8 12.3v2"/>',
    lock: '<rect x="3.5" y="7" width="9" height="6.5" rx="1.3"/><path d="M5.5 7V5.2a2.5 2.5 0 0 1 5 0V7"/>',
    cloud: '<path d="M4.5 12.5a3 3 0 0 1-.3-6 4 4 0 0 1 7.7-.7 3.4 3.4 0 0 1-.4 6.7z"/>',
    sources: '<path d="M3 5.5v5M6 3v10M9 5v6M12 6.5v3"/>',
    transcript: '<path d="M3 4h10M3 7h10M3 10h6M3 13h8"/>',
    atoms: '<rect x="2.5" y="2.5" width="4.5" height="4.5" rx="1.2"/><rect x="9" y="2.5" width="4.5" height="4.5" rx="1.2"/><rect x="2.5" y="9" width="4.5" height="4.5" rx="1.2"/><path d="M9.8 11.3l1.3 1.3 2.3-2.6"/>',
    doc: '<path d="M4 1.8h5.2L12.5 5v8.7a.8.8 0 0 1-.8.8H4a.8.8 0 0 1-.8-.8V2.6a.8.8 0 0 1 .8-.8z"/><path d="M9 2v3.3h3.3M5.5 8.5h5M5.5 11h3.5"/>',
    tree: '<rect x="2" y="2" width="5" height="3.2" rx="1"/><rect x="7" y="7" width="7" height="2.8" rx="1"/><rect x="7" y="11.4" width="7" height="2.8" rx="1"/><path d="M4.5 5.2v7.6h2.5M4.5 8.4h2.5"/>',
    export: '<path d="M8 10V2.5M5 5.3L8 2.3l3 3"/><path d="M3 9v3.7c0 .5.4.8.8.8h8.4c.5 0 .8-.3.8-.8V9"/>',
    skills: '<path d="M3 13l6.5-6.5M11 2.3l.5 1.4 1.4.5-1.4.5-.5 1.4-.5-1.4-1.4-.5 1.4-.5zM13.2 8l.3.8.8.3-.8.3-.3.8-.3-.8-.8-.3.8-.3zM7 2l.3.8.8.3-.8.3L7 4.2l-.3-.8-.8-.3.8-.3z"/>',
    gear: '<circle cx="8" cy="8" r="2.2"/><path d="M8 1.8v1.6M8 12.6v1.6M14.2 8h-1.6M3.4 8H1.8M12.4 3.6l-1.1 1.1M4.7 11.3l-1.1 1.1M12.4 12.4l-1.1-1.1M4.7 4.7L3.6 3.6"/>',
    search: '<circle cx="7" cy="7" r="4.3"/><path d="M10.2 10.2l3.3 3.3"/>',
    sun: '<circle cx="8" cy="8" r="3"/><path d="M8 1.5v1.3M8 13.2v1.3M14.5 8h-1.3M2.8 8H1.5M12.6 3.4l-.9.9M4.3 11.7l-.9.9M12.6 12.6l-.9-.9M4.3 4.3l-.9-.9"/>',
    moon: '<path d="M13 9.6A5.5 5.5 0 0 1 6.4 3a5.5 5.5 0 1 0 6.6 6.6z"/>',
    pin: '<path d="M9.5 2l4.5 4.5-2 .8-2.4 2.4.3 2.8-1.2 1.2L6.3 11.3 2.8 14.8M4.2 8.2l1.2-1.2 2.8.3 2.4-2.4.8-2"/>',
    warn: '<path d="M8 2.2l6.2 11H1.8z"/><path d="M8 6.5v3M8 11.4v.1"/>',
    help: '<circle cx="8" cy="8" r="6"/><path d="M6.2 6.3a1.9 1.9 0 0 1 3.7.5c0 1.3-1.9 1.5-1.9 2.7M8 11.4v.1"/>',
    info: '<circle cx="8" cy="8" r="6"/><path d="M8 7.3v3.8M8 5v.1"/>',
    bolt: '<path d="M9 1.8L3.5 9h4l-.8 5.2L12.5 7h-4z"/>',
    more: '<circle cx="3.5" cy="8" r=".9"/><circle cx="8" cy="8" r=".9"/><circle cx="12.5" cy="8" r=".9"/>',
    mail: '<rect x="2" y="3.5" width="12" height="9" rx="1.3"/><path d="M2.5 4.5L8 9l5.5-4.5"/>',
    file: '<path d="M4 1.8h5.2L12.5 5v8.7a.8.8 0 0 1-.8.8H4a.8.8 0 0 1-.8-.8V2.6a.8.8 0 0 1 .8-.8z"/><path d="M9 2v3.3h3.3"/>',
    wave: '<path d="M2 8h1.5M5 5v6M8 3v10M11 5.5v5M14 8h-1"/>',
    compare: '<path d="M5 2.5v8.5M5 11a2 2 0 1 0 0 .1M11 13.5V5M11 5a2 2 0 1 0 0-.1M5 5.5l2-2-2-2"/>',
    refresh: '<path d="M13 7.5A5 5 0 0 0 4 4.3L2.8 5.5M3 8.5a5 5 0 0 0 9 3.2l1.2-1.2M2.8 2.5v3h3M13.2 13.5v-3h-3"/>',
    link: '<path d="M7 9a2.8 2.8 0 0 0 4 0l2-2a2.8 2.8 0 0 0-4-4l-.8.8M9 7a2.8 2.8 0 0 0-4 0L3 9a2.8 2.8 0 0 0 4 4l.8-.8"/>',
    sidebar: '<rect x="1.8" y="2.8" width="12.4" height="10.4" rx="1.8"/><path d="M6 3v10"/>',
    clock: '<circle cx="8" cy="8" r="6"/><path d="M8 4.8V8l2.2 1.5"/>',
    inspector: '<rect x="1.8" y="2.8" width="12.4" height="10.4" rx="1.8"/><path d="M10 3v10"/>',
    home: '<path d="M2.5 7.5L8 2.8l5.5 4.7v5.2a.8.8 0 0 1-.8.8H3.3a.8.8 0 0 1-.8-.8z"/><path d="M6.5 13.3V9.5h3v3.8"/>',
    updown: '<path d="M5 6l3-3 3 3M5 10l3 3 3-3"/>',
    spark: '<path d="M8 1.8l1.5 4.2 4.2 1.5-4.2 1.5L8 13.2 6.5 9 2.3 7.5 6.5 6z"/>',
    table: '<rect x="2" y="2.8" width="12" height="10.4" rx="1.5"/><path d="M2 6.5h12M2 10h12M6.5 6.5v6.7"/>',
    word: '<path d="M4 1.8h5.2L12.5 5v8.7a.8.8 0 0 1-.8.8H4a.8.8 0 0 1-.8-.8V2.6a.8.8 0 0 1 .8-.8z"/><path d="M5.3 8l1 3.5L8 8.3l1.7 3.2 1-3.5"/>',
    jira: '<path d="M8 1.8L14.2 8 8 14.2 1.8 8z"/><path d="M8 5.2L10.8 8 8 10.8 5.2 8z"/>',
    filter: '<path d="M2.5 3.5h11L9.5 8.4v4.3l-3 1V8.4z"/>',
    cube: '<path d="M8 1.8l5.5 3v6.4L8 14.2l-5.5-3V4.8zM2.8 5L8 8l5.2-3M8 8v6"/>',
  };
</script>

<svg class="icon" width={size} height={size} viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor"
     stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">{@html ICONS[name] || ""}</svg>

<style>
  .icon { flex: none; display: block; }
</style>
