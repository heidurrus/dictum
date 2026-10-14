// Thin client for the local Flask API. Errors carry the server's message.

export class ApiError extends Error {
  constructor(message, status, body) {
    super(message);
    this.status = status;
    this.body = body || {};
  }
}

// The interface language, sent with every request: skills, document types and section titles come in both.
let currentLang = () => "ru";
export function setLangSource(fn) { currentLang = fn; }

// Set by the app: called after a request that started a job, so the status chip refreshes at once.
let onJobStarted = () => {};
export function setJobStartedHook(fn) { onJobStarted = fn; }

export async function api(path, { method = "GET", body, form, headers } = {}) {
  if (path.startsWith("/api/") && !/[?&]lang=/.test(path)) path += (path.includes("?") ? "&" : "?") + "lang=" + currentLang();
  const init = { method, headers: { ...(headers || {}) } };
  if (form) init.body = form;
  else if (body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  const res = await fetch(path, init);
  let data = null;
  try { data = await res.json(); } catch (_) { /* not JSON */ }
  if (!res.ok) throw new ApiError((data && data.error) || `HTTP ${res.status}`, res.status, data);
  if (method !== "GET" && data && (data.job_id || data.extract_job || /\/download$/.test(path.split("?")[0]))) onJobStarted();
  return data;
}

const sleep = ms => new Promise(r => setTimeout(r, ms));

// Set by the app: turns backend progress text into the interface language.
let translateProgress = m => m;
export function setProgressTranslator(fn) { translateProgress = fn; }

// Poll a job until it finishes. onUpdate(job) gets every intermediate state
// (progress, streamed partial text). Resolves with the finished job.
export async function pollJob(jobId, onUpdate, { interval = 700, signal } = {}) {
  while (true) {
    if (signal && signal.aborted) throw new DOMException("aborted", "AbortError");
    const job = await api(`/job/${jobId}`);
    if (job.progress_msg) job.progress_msg = translateProgress(job.progress_msg);
    if (onUpdate) onUpdate(job);
    if (job.status === "done") return job;
    if (job.status === "error") throw new ApiError(job.error || "failed", 500, job);
    await sleep(interval);
  }
}
