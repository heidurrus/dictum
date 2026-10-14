"""Meeting notes and recap styles (spec 5.0 C3).

Notes are the BA's own Markdown, kept raw on the source (`sources.notes`). The client autosaves them
(1 s debounce); server-side additions (the question card in C4, whispers later) go through
`append_note`, which adds one line in the same transaction as it reads the text.

A recap is a summary in one of three styles (brief | bullets | actions). Each style's instructions are
a built-in skill (skills/recap-brief, recap-bullets, recap-actions), editable like any other skill.
One `summaries` row per style remembers `through_idx`, the last segment it covers, so an update can
send the previous recap plus only the new lines and ask the model to revise it rather than rewrite.
"""
import re

from core import skills
from core.store import RECAP_STYLES

STAGE = {style: f"recap_{style}" for style in RECAP_STYLES}

# Added to every recap prompt after the style's skill: the app's part, not editable.
FULL_CONTRACT = ("Write the recap from the whole transcript below, in Markdown. Refer to the moment of each point "
                 "with the speaker and timestamp in square brackets, e.g. [Anna, 12:30], when the transcript has them.")
UPDATE_CONTRACT = ("You are updating an existing recap, not writing a new one. You get the previous recap and only "
                   "the transcript lines said since it was written. Keep everything in the previous recap that is "
                   "still right, in the same structure and wording; add what the new lines bring and change only what "
                   "they correct or settle. Do not drop points because the new lines do not repeat them. "
                   "Return the whole updated recap in Markdown, nothing else.")

# Settings → Запись → notes_style "concise" (5.0 C9): the same recap, said in fewer words.
CONCISE_RULE = ("Keep the recap concise: about half the length you would otherwise write, only the points that matter "
                "most, no repetition.")

_LISTED = re.compile(r"^(?:[-*•]\s|#|\d+[.)]\s)")


def bullet(line):
    """One line for the notes: a Markdown list item unless it already is one (or a heading)."""
    line = " ".join(str(line or "").split())
    if not line:
        raise ValueError("the line is empty")
    return line if _LISTED.match(line) else "- " + line


def save_notes(store, source_id, text):
    """Replace the notes (the editor's autosave). → {saved_at, text}"""
    if not isinstance(text, str):
        raise ValueError("text must be a string")
    return store.update_notes(source_id, lambda _old: text)


def append_note(store, source_id, line):
    """Add one line at the end ("\\n" + line, as a list item). → {saved_at, text} with the whole text."""
    item = bullet(line)
    return store.update_notes(source_id, lambda old: old.rstrip("\n") + "\n" + item if old.strip() else item,
                              action="notes_append")


def system_prompt(skillset, style, incremental, language_rule="", concise=False):
    system = skills.compose(skillset, STAGE[style], UPDATE_CONTRACT if incremental else FULL_CONTRACT)
    if concise:
        system += "\n\n" + CONCISE_RULE
    return system + ("\n\n" + language_rule if language_rule else "")


def plan(store, source_id, style, incremental):
    """What a recap run sends: {incremental, user, through_idx, previous}.
    Incremental needs this style's previous recap with a through_idx; otherwise (or when switching to a style
    that has no recap yet) it is a full recap. `user` is None when nothing was said since the previous one."""
    if style not in RECAP_STYLES:
        raise ValueError(f"unknown recap style {style}")
    source = store.get_source(source_id)
    last = store.last_segment_idx(source_id)
    prev = store.latest_summary(source_id, style)
    if incremental and prev and prev.get("through_idx") is not None:
        new_lines = store.transcript_text(source_id, after_idx=prev["through_idx"]).strip()
        if not new_lines:
            return {"incremental": True, "user": None, "through_idx": prev["through_idx"], "previous": prev}
        user = (f"Meeting: {source['title']}\n\n"
                f"Previous recap:\n<recap>\n{prev['text'].strip()}\n</recap>\n\n"
                f"New transcript lines since that recap:\n<new_lines>\n{new_lines}\n</new_lines>\n\n"
                "Update the recap with the new lines.")
        return {"incremental": True, "user": user, "through_idx": last, "previous": prev}
    text = store.transcript_text(source_id).strip()
    if not text:
        raise ValueError("There is no transcript text to summarise.")
    return {"incremental": False, "user": f"Transcript of: {source['title']}\n\n{text}", "through_idx": last,
            "previous": prev}


def recap(store, source_id, style, incremental, generate, skillset, provider, model, language_rule="",
          on_delta=lambda _t: None, concise=False):
    """Write (or update) the recap of one style and store it as that style's row.
    `generate(system, user, on_delta)` → text. Returns the row plus {"incremental", "unchanged"}."""
    p = plan(store, source_id, style, incremental)
    store.set_recap_style(source_id, style)
    if p["user"] is None:
        return {**p["previous"], "incremental": True, "unchanged": True}
    text = generate(system_prompt(skillset, style, p["incremental"], language_rule, concise), p["user"], on_delta)
    if not (text or "").strip():
        raise ValueError("The model returned an empty recap.")
    row = store.add_summary(source_id, provider, model, text.strip(), style=style, through_idx=p["through_idx"])
    return {**row, "incremental": p["incremental"], "unchanged": False}
