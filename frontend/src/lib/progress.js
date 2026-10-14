// Progress text comes from the backend in English; show it in the interface language (PM-08).
import { t } from "./state.svelte.js";

const MAP = [
  [/^Queued — waiting for (\d+) job\(s\) to finish…$/, "pg.queued", m => ({ n: +m[1] })],
  [/^Transcribing segments… (\d+)\/(\d+)$/, "pg.segments", m => ({ i: m[1], n: m[2] })],
  [/^Transcribing (\d+) segments…$/, "pg.segments_n", m => ({ n: m[1] })],
  [/^Reading part (\d+) of (\d+)…$/, "pg.part", m => ({ i: m[1], n: m[2] })],
  [/^Rewriting (\d+) changed requirement\(s\)…$/, "pg.rewriting", m => ({ n: +m[1] })],
  [/^Loading model on (\w+)…$/, "pg.loading_model", m => ({ device: m[1] })],
  [/^Long file — running VAD segmentation…$/, "pg.vad"],
  [/^Transcribing your microphone…$/, "pg.mic"],
  [/^Transcribing the other side of the call…$/, "pg.other"],
  [/^Transcribing…$/, "pg.transcribing"],
  [/^Loading audio…$/, "pg.audio"],
  [/^Loading diarization pipeline…$/, "pg.diar_load"],
  [/^Starting diarization…$/, "pg.diar_start"],
  [/^Running speaker diarization…$/, "pg.diar"],
  [/^Reading the source…$/, "pg.reading"],
  [/^Checking for duplicates and conflicts…$/, "pg.dedup"],
  [/^Writing the document…$/, "pg.document"],
  [/^Checking quality…$/, "pg.quality"],
  [/^Writing stories…$/, "pg.stories"],
  [/^Checking coverage…$/, "pg.coverage"],
  [/^Checking stories…$/, "pg.invest"],
  [/^Writing summary…$/, "pg.summary"],
  [/^Writing the recap…$/, "pg.recap"],
  [/^Updating the recap…$/, "pg.recap_update"],
  [/^Reading Jira…$/, "pg.jira_read"],
  [/^Connecting to Jira…$/, "pg.jira_connect"],
  [/^Trying the skill…$/, "pg.try"],
  [/^Searching the project…$/, "pg.ask_search"],
  [/^Writing the answer…$/, "pg.ask_answer"],
  [/^Waiting for the speech model download…$/, "pg.wait_asr"],
  [/^Starting…$/, "pg.starting"],
  [/^Done$/, "pg.done"],
];

export function progressText(message) {
  if (!message) return message;
  for (const [re, key, vars] of MAP) {
    const m = message.match(re);
    if (m) return t(key, vars ? vars(m) : undefined);
  }
  return message;                       // titles of items being pushed, etc.
}
