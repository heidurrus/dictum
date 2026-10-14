// The transcript of a meeting while it is being recorded (spec 5.0 C4.1): the page polls
// GET /api/sources/<id>/live?after=<idx> every 2 s and appends what is new. The same answer carries the
// meeting's requirements found so far (C4.2), the silence counter and, once the recording stopped by itself,
// why (C4.3).
import { api } from "./api.js";

export const LIVE_POLL_MS = 2000;

export function createLive(sourceId) {
  const st = $state({ segments: [], recording: true, paused: false, elapsed: 0, live: "on", listening: false, error: "",
                      atoms: [], silence: 0, silence_stop: 0, stopped: null });
  let after = -1;
  let seenAt = 0;                 // created_at of the newest requirement when the user last looked at the block
  const pending = {};             // atom id → status set here and not reported by the server yet

  // A status set here wins over the server's until the server reports it too (an older poll may still arrive).
  const mark = list => list.map(a => {
    if (pending[a.id] === a.status) delete pending[a.id];
    return { ...a, status: pending[a.id] || a.status, new: a.created_at > seenAt };
  });

  async function poll() {
    try {
      const body = await api(`/api/sources/${sourceId}/live?after=${after}&atoms_after=${seenAt}`);
      if (body.segments.length) {
        st.segments = [...st.segments, ...body.segments];
        after = body.segments[body.segments.length - 1].idx;
      }
      Object.assign(st, { recording: body.recording, paused: body.paused, elapsed: body.elapsed, live: body.live,
                          listening: body.listening, error: "", atoms: mark(body.atoms || []),
                          silence: body.silence || 0, silence_stop: body.silence_stop || 0, stopped: body.stopped || null });
    } catch (err) { st.error = err.message; }       // transient: the next poll tries again
    return st;
  }

  // The user looked at the requirements block: nothing in it is new any more.
  function markSeen() {
    seenAt = Math.max(seenAt, ...st.atoms.map(a => a.created_at));
    st.atoms = st.atoms.map(a => ({ ...a, new: false }));
  }

  // The checkbox: accepted ↔ pending, at once on screen, through the atom's own endpoint.
  async function setStatus(atom, status) {
    const before = atom.status;
    pending[atom.id] = status;
    st.atoms = st.atoms.map(a => (a.id === atom.id ? { ...a, status } : a));
    try {
      await api(`/api/atoms/${atom.id}`, { method: "PATCH", body: { status } });
    } catch (err) {
      delete pending[atom.id];
      st.atoms = st.atoms.map(a => (a.id === atom.id ? { ...a, status: before } : a));
      throw err;
    }
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

  return { state: st, poll, follow, markSeen, setStatus };
}
