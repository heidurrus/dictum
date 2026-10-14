// App-wide state (Svelte 5 runes). Components read and mutate `app` directly.
import { api } from "./api.js";
import { translate } from "./i18n.js";

function readPref(key, fallback) {
  try { const v = localStorage.getItem("wb." + key); return v === null ? fallback : JSON.parse(v); }
  catch (_) { return fallback; }
}
export function writePref(key, value) {
  try { localStorage.setItem("wb." + key, JSON.stringify(value)); } catch (_) { /* private mode */ }
}

// First start: the interface follows the OS (Russian for ru-*, English otherwise); a stored choice wins afterwards.
function osLang() {
  const l = (typeof navigator !== "undefined" && (navigator.language || navigator.languages?.[0])) || "";
  return /^ru\b/i.test(l) ? "ru" : "en";
}

// 5.0 names of the rail items that still open a 4.x screen; the 4.x Sources and Overview addresses open Встречи.
const ALIASES = { sources: "meetings", overview: "meetings", requirements: "atoms", documents: "document" };

export function parseRoute(hash = location.hash) {
  const parts = hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  if (ALIASES[parts[0]]) parts[0] = ALIASES[parts[0]];
  // A meeting: #/meeting/<id> is the address; #/source/<id> (4.x and the atoms' links) opens the same page.
  if ((parts[0] === "meeting" || parts[0] === "source") && parts[1]) return { name: "transcript", id: parts[1], summarize: parts[2] === "summarize",
                                                  seg: parts[2] === "seg" ? Number(parts[3]) : null };
  if (parts[0] === "document") return { name: "document", doc: parts[1] && parts[1] !== "new" ? parts[1] : null,
                                       newKind: parts[1] === "new" ? parts[2] : null };
  if (parts[0] === "backlog") return { name: "backlog" };
  if (parts[0] === "export") return { name: "export" };
  if (parts[0] === "skills") return { name: "skills", skill: parts[1] || null };
  if (parts[0] === "atoms") return { name: "atoms", source: parts[1] === "source" ? parts[2] : null,
                                    atom: parts[1] === "atom" ? parts[2] : null };
  if (parts[0] === "settings") return { name: "settings" };
  if (parts[0] === "transcript") return { name: "transcript", id: null };
  if (parts[0] === "meetings") return { name: "meetings" };
  if (parts[0] === "library") return { name: "library", id: parts[1] || null };
  if (parts[0] === "ask") return { name: "ask" };
  if (parts[0] === "whisper") return { name: "whisper" };
  return { name: "home" };            // resolved by the app: Встречи
}

export const app = $state({
  route: parseRoute(),
  lang: readPref("lang", osLang()),
  projects: [],
  archivedProjects: [],
  currentProjectId: null,
  sources: [],
  documents: [],            // the project's documents, for the sidebar
  inspector: readPref("inspector", {}),     // screen → false when the BA closed its inspector
  inspectorOverlay: false,  // narrow windows: the inspector slides over the content
  palette: false,           // ⌘K
  lastSourceId: readPref("lastSource", null),
  device: { cuda: false, mps: false, gpu_name: null, desktop: false },
  health: null,
  models: [],
  options: readPref("asrOptions", { model: "v3_e2e_rnnt", device: "cpu", diarize: false, word_timestamps: false }),
  toasts: [],               // at most 2; they belong to the screen that raised them
  status: null,             // per-step counts for the rail badges
  theme: readPref("theme", "auto"),
  // source id → { jobId, progress, message } for work started in this session
  jobs: {},
  // source id → { jobId, progress, message } for atom extraction
  extracting: {},
  work: {},                 // other long jobs shown in the sidebar: key → { title, progress, message, path }
  atomsVersion: 0,
  settings: null,           // GET /settings, loaded at boot (the hotkeys map lives there)
  jobsTick: 0,              // bumped when something started a job: the status chip polls at once
  returnTo: null,           // {hash, name}: where Settings was opened from          // bumped when atoms change elsewhere, so open screens reload
});

export const t = (key, vars) => translate(app.lang, key, vars);

export function go(path) {
  if (location.hash !== "#" + path) location.hash = path;
  else app.route = parseRoute();
}
window.addEventListener("hashchange", e => {
  const prev = app.route.name;
  // Remember where Settings was opened from, so it can send the BA back (PM-26).
  if (parseRoute().name === "settings" && prev !== "settings") {
    app.returnTo = { hash: new URL(e.oldURL).hash.slice(1) || "/meetings", name: prev };
  }
  app.route = parseRoute();
  if (app.route.name !== prev) { app.toasts = []; app.inspectorOverlay = false; }   // toasts belong to the screen that raised them
  loadStatus();
});

export function jobsTick() { app.jobsTick++; }

export function setTheme(theme) {
  app.theme = theme;
  writePref("theme", theme);
  applyTheme();
}
export function applyTheme() {
  if (app.theme === "auto") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = app.theme;
}
export function isDark() {
  if (app.theme !== "auto") return app.theme === "dark";
  return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
}

let statusTimer = null;
export function loadStatus() {
  clearTimeout(statusTimer);            // coalesce bursts of changes
  statusTimer = setTimeout(async () => {
    const pid = app.currentProjectId;
    if (!pid) return;
    try {
      const [status, docs] = await Promise.all([api(`/api/projects/${pid}/status`),
                                                api(`/api/projects/${pid}/documents`).catch(() => null)]);
      if (pid !== app.currentProjectId) return;
      app.status = status;
      if (docs) app.documents = docs.documents;
    } catch (_) { /* the sidebar state is optional */ }
  }, 150);
}

export function inspectorOn(screen) { return app.inspector[screen] !== false; }
export function toggleInspector(screen) {
  // Narrow workspace (< 900 px): the inspector is an overlay, so the button opens and closes that.
  const ws = document.querySelector(".workspace");
  if (ws && ws.clientWidth < 900) { app.inspectorOverlay = !app.inspectorOverlay; return; }
  app.inspector = { ...app.inspector, [screen]: !inspectorOn(screen) };
  writePref("inspector", app.inspector);
}

export function setLang(lang) {
  app.lang = lang;
  writePref("lang", lang);
  document.documentElement.lang = lang;
}

export function saveOptions() { writePref("asrOptions", app.options); }

export function currentProject() {
  return app.projects.find(p => p.id === app.currentProjectId) || null;
}

export async function loadProjects() {
  const body = await api("/api/projects?archived=1");
  app.projects = body.projects.filter(p => !p.archived);
  app.archivedProjects = body.projects.filter(p => p.archived);
  app.currentProjectId = body.current_project_id;
}

export async function loadSources() {
  if (!app.currentProjectId) return;
  const body = await api(`/api/projects/${app.currentProjectId}/sources`);
  app.sources = body.sources;
}

export async function restoreProject(id) {
  await api(`/api/projects/${id}`, { method: "PATCH", body: { archived: false } });
  await loadProjects();
}

export async function switchProject(id) {
  await api(`/api/projects/${id}/current`, { method: "POST" });
  app.currentProjectId = id;
  app.sources = [];
  app.documents = [];
  await loadSources();
  app.status = null;
  loadStatus();
  go("/meetings");
}

let toastSeq = 0;
export function dismissToast(id) {
  app.toasts = app.toasts.filter(x => x.id !== id);
}
// The most recent undo stays available to ⌘Z for as long as its toast would have (PM-10: ≥ 10 s).
let lastUndo = null;
export function undoLast() {
  if (!lastUndo || Date.now() > lastUndo.until) return false;
  const u = lastUndo;
  lastUndo = null;
  dismissToast(u.id);
  u.run();
  return true;
}

export function toast(message, { action, onAction, kind = "info", ms } = {}) {
  ms = ms ?? (action ? 10000 : 6000);
  if (action) ms = Math.max(ms, 10000);
  const id = ++toastSeq;
  if (action && onAction && kind !== "danger") lastUndo = { id, run: onAction, until: Date.now() + ms };
  // Only one undo at a time: a newer action toast replaces an older one.
  const keep = action ? app.toasts.filter(x => !x.action) : app.toasts;
  app.toasts = [...keep, { id, message, action, onAction, kind }].slice(-2);
  setTimeout(() => dismissToast(id), ms);
  loadStatus();                         // most toasts follow a change worth counting
}

export function rememberSource(id) {
  app.lastSourceId = id;
  writePref("lastSource", id);
}
