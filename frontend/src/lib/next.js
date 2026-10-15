// The one next step of the pipeline, from the project's status.
// Used by the pipeline strip on Встречи; screens name their own primary button from the same state.
import { app, t, analysisOn } from "./state.svelte.js";

export function nextStep() {
  const s = app.status;
  if (!s) return null;
  if (!s.sources) return { icon: "sources", title: t("next.import"), text: t("next.import_d"), cta: t("nav.sources"), go: "/sources" };
  if (s.processing) return { icon: "clock", title: t("next.wait", { n: s.processing }), text: t("next.wait_d"), wait: true };
  if (!analysisOn()) return null;       // a meeting recorder (5.0.4): nothing after the meetings themselves
  if (s.atoms.review) return { icon: "atoms", title: t("next.review", { n: s.atoms.review }), text: t("next.review_d"), cta: t("next.review_cta"), go: "/atoms" };
  if (s.atoms.conflicts) return { icon: "warn", title: t("next.conflicts", { n: s.atoms.conflicts }), text: t("next.conflicts_d"), cta: t("next.conflicts_cta"), go: "/atoms" };
  if (!s.atoms.total) return { icon: "atoms", title: t("next.extract"), text: t("next.extract_d"), cta: t("nav.sources"), go: "/sources" };
  if (!s.document.version) return { icon: "doc", title: t("next.build", { n: s.atoms.accepted }), text: t("next.build_d"), cta: t("doc.build_cta"), go: "/document" };
  if (s.document.stale) return { icon: "doc", title: t("next.doc_stale", { n: s.document.changed }), text: t("next.doc_stale_d"), cta: t("next.update_cta"), go: "/document" };
  if (!s.backlog.items) return { icon: "tree", title: t("next.backlog"), text: t("next.backlog_d"), cta: t("bl.build"), go: "/backlog" };
  if (s.backlog.stale) return { icon: "tree", title: t("next.bl_stale"), text: t("next.bl_stale_d"), cta: t("next.update_cta"), go: "/backlog" };
  if (s.export.pending) return { icon: "export", title: t("next.push", { n: s.export.pending }), text: t("next.push_d"), cta: t("next.push_cta"), go: "/export" };
  if (!s.export.pushed) return { icon: "export", title: t("next.first_push"), text: t("next.push_d"), cta: t("next.push_cta"), go: "/export" };
  if (s.open_items.questions) return { icon: "mail", title: t("next.questions", { n: s.open_items.questions }), text: t("next.questions_d"), cta: t("next.letter_cta"), go: "/atoms" };
  return { icon: "check", title: t("next.done"), text: t("next.done_d"), done: true };
}
