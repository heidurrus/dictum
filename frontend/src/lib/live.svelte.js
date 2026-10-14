// The transcript of a meeting while it is being recorded (spec 5.0 C4.1): the page polls
// GET /api/sources/<id>/live?after=<idx> every 2 s and appends what is new.
import { api } from "./api.js";

export const LIVE_POLL_MS = 2000;

export function createLive(sourceId) {
  const st = $state({ segments: [], recording: true, paused: false, elapsed: 0, live: "on", listening: false, error: "" });
  let after = -1;

  async function poll() {
    try {
      const body = await api(`/api/sources/${sourceId}/live?after=${after}`);
      if (body.segments.length) {
        st.segments = [...st.segments, ...body.segments];
        after = body.segments[body.segments.length - 1].idx;
      }
      Object.assign(st, { recording: body.recording, paused: body.paused, elapsed: body.elapsed, live: body.live,
                          listening: body.listening, error: "" });
    } catch (err) { st.error = err.message; }       // transient: the next poll tries again
    return st;
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

  return { state: st, poll, follow };
}
