// Saving a source's audio: the recording's channels or the imported file (see /api/sources/<id>/audio/files).
import { t } from "./state.svelte.js";
import { saveUrl } from "./save.js";

const SUFFIX = { mic: "tr.audio_suffix_mic", sys: "tr.audio_suffix_sys" };
const LABEL = { mixed: "tr.save_audio_mixed", mic: "tr.save_audio_mic", sys: "tr.save_audio_sys", original: "tr.save_audio_original" };

export function audioFilename(source, file) {
  if (file.filename) return file.filename;
  const safe = (source.title || "").replace(/[\\/:*?"<>|]+/g, " ").trim() || "audio";
  const ext = file.name.slice(file.name.lastIndexOf("."));
  return safe + (SUFFIX[file.id] ? " — " + t(SUFFIX[file.id]) : "") + ext;
}

export function audioLabel(file, count) {
  return count === 1 || !LABEL[file.id] ? t("tr.save_audio") : t(LABEL[file.id]);
}

export function fmtBytes(bytes) {
  if (!bytes) return "";
  if (bytes >= 1e9) return (bytes / 1e9).toFixed(1) + " " + t("llm.gb");
  return bytes >= 1e6 ? Math.round(bytes / 1e6) + " " + t("asr.mb") : Math.max(1, Math.round(bytes / 1e3)) + " " + t("tr.kb");
}

export function saveAudio(source, file) {
  const name = audioFilename(source, file);
  return saveUrl(`/api/sources/${source.id}/audio/download/${file.id}?name=${encodeURIComponent(name)}`, name);
}
