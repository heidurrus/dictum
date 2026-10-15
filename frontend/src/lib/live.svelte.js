// The transcript of a meeting while it is being recorded (spec 5.0 C4.1): the page polls
// GET /api/sources/<id>/live?after=<idx> every 2 s and appends what is new. The same answer carries the
// silence counter and, once the recording stopped by itself, why (C4.3), and the question card (C4.3: a question
// heard in the call, answered from the materials).
import { api } from "./api.js";

export const LIVE_POLL_MS = 2000;

export function createLive(sourceId) {
  const st = $state({ segments: [], recording: true, paused: false, elapsed: 0, live: "on", listening: false, error: "",
                      silence: 0, silence_stop: 0, stopped: null, question: null });
  let after = -1;
  const hidden = new Set();       // question cards dismissed here (an older poll may still carry one)

  async function poll() {
    try {
      const body = await api(`/api/sources/${sourceId}/live?after=${after}`);
      if (body.segments.length) {
        st.segments = [...st.segments, ...body.segments];
        after = body.segments[body.segments.length - 1].idx;
      }
      Object.assign(st, { recording: body.recording, paused: body.paused, elapsed: body.elapsed, live: body.live,
                          listening: body.listening, error: "",
                          silence: body.silence || 0, silence_stop: body.silence_stop || 0, stopped: body.stopped || null,
                          question: body.question && !hidden.has(body.question.id) ? body.question : null });
    } catch (err) { st.error = err.message; }       // transient: the next poll tries again
    return st;
  }

  // "Скрыть" / "Добавить в заметки" on the question card: gone at once, and the server stops showing it.
  async function dismissQuestion() {
    const q = st.question;
    if (!q) return;
    hidden.add(q.id);
    st.question = null;
    try { await api(`/api/sources/${sourceId}/live/question/dismiss`, { method: "POST", body: { id: q.id } }); }
    catch (_) { /* it expires by itself */ }
  }

  // Poll until stopped or the recording ends; onFirst gets the first answer.
  function follow(onFirst) {
    let stopped = false;
    (async () => {
      await poll();
      if (!stopped) onFirst?.(st);
      while (!stopped && st.recording) {
        await new Promise(r => setTimeout(r, LIVE_POLL_MS));
        if (!stopped) await poll();
      }
    })();
    return () => { stopped = true; };
  }

  return { state: st, poll, follow, dismissQuestion };
}
