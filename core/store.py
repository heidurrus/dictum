"""Local project store: SQLite database + one folder per source (spec increment 1).

Spec refs: FR-PRJ-01…05 (projects, "Local only"), FR-SRC-07 (sources list),
FR-TR-01/05 (stored transcript, speaker names), NFR-DATA-03 (persistence),
NFR-MAINT-02 (team-ready: UUID keys, created/updated by/at on every row, the
audit log doubles as a change feed), NFR-AUD-02 (audit log of changes).

Stdlib only. One connection per call keeps it safe across Flask's threads;
WAL mode lets readers and a writer work at the same time.
"""
import getpass
import json
import os
import re
import shutil
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager

from core.paths import app_data_dir

SCHEMA_VERSION = 9
BACKLOG_KINDS = {"epic", "story", "subtask", "nfr"}
ATOM_TYPES = {"functional", "nfr", "question", "business", "risk", "current"}
# Stable ID prefix per atom type: FR / NFR / Q, BR (business requirement), RSK (risk), AS (as-is: today's process).
ATOM_PREFIX = {"functional": "FR", "nfr": "NFR", "question": "Q", "business": "BR", "risk": "RSK", "current": "AS"}
ATOM_STATUSES = {"pending", "accepted", "rejected", "merged"}
CONFLICT_ACTIONS = {"keep_a", "keep_b", "merge", "question"}
REJECT_REASONS = {"not_requirement", "duplicate", "out_of_scope", "wrong", "other"}
PRIORITIES = {"must", "should", "could", "wont"}
QUESTION_STATES = {"open", "asked", "answered"}
JIRA_QUOTES = {"auto", "full", "link", "none"}
DOC_STATUSES = {"draft", "review", "approved"}
ACTION_STATUSES = {"open", "done"}
RECAP_STYLES = ("brief", "bullets", "actions")
SOURCE_KINDS = {"recording", "audio", "transcript", "document", "email"}
SOURCE_STATUSES = {"recording", "recorded", "processing", "ready", "failed"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, local_only INTEGER NOT NULL DEFAULT 0,
  archived INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL, created_by TEXT NOT NULL, updated_at REAL NOT NULL, updated_by TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sources (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
  kind TEXT NOT NULL, title TEXT NOT NULL, original_filename TEXT,
  status TEXT NOT NULL, error TEXT, duration REAL, speakers INTEGER, asr_model TEXT,
  diarized INTEGER NOT NULL DEFAULT 0, import_format TEXT, audio_file TEXT, text TEXT, words_json TEXT,
  meta_json TEXT, deleted_at REAL, notes TEXT, recap_style TEXT,
  created_at REAL NOT NULL, created_by TEXT NOT NULL, updated_at REAL NOT NULL, updated_by TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS sources_by_project ON sources(project_id, deleted_at, created_at);
CREATE TABLE IF NOT EXISTS segments (
  source_id TEXT NOT NULL REFERENCES sources(id), idx INTEGER NOT NULL,
  speaker TEXT, start REAL, "end" REAL, text TEXT NOT NULL, PRIMARY KEY (source_id, idx));
CREATE TABLE IF NOT EXISTS speakers (
  source_id TEXT NOT NULL REFERENCES sources(id), label TEXT NOT NULL, name TEXT NOT NULL,
  updated_at REAL NOT NULL, updated_by TEXT NOT NULL, PRIMARY KEY (source_id, label));
CREATE TABLE IF NOT EXISTS summaries (
  id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(id),
  provider TEXT NOT NULL, model TEXT NOT NULL, text TEXT NOT NULL,
  created_at REAL NOT NULL, created_by TEXT NOT NULL, style TEXT NOT NULL DEFAULT 'brief', through_idx INTEGER);
CREATE INDEX IF NOT EXISTS summaries_by_source ON summaries(source_id, created_at);
CREATE TABLE IF NOT EXISTS audit_log (
  id TEXT PRIMARY KEY, entity TEXT NOT NULL, entity_id TEXT NOT NULL, action TEXT NOT NULL,
  before_json TEXT, after_json TEXT, at REAL NOT NULL, by TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS audit_by_entity ON audit_log(entity, entity_id, at);
CREATE TABLE IF NOT EXISTS atoms (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
  type TEXT NOT NULL, statement TEXT NOT NULL, original_statement TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending', merged_into TEXT, model TEXT,
  created_at REAL NOT NULL, created_by TEXT NOT NULL, updated_at REAL NOT NULL, updated_by TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS atoms_by_project ON atoms(project_id, status, created_at);
CREATE TABLE IF NOT EXISTS evidence (
  id TEXT PRIMARY KEY, atom_id TEXT NOT NULL REFERENCES atoms(id), source_id TEXT NOT NULL REFERENCES sources(id),
  segment_idx INTEGER, start REAL, speaker TEXT, quote TEXT NOT NULL, created_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS evidence_by_atom ON evidence(atom_id);
CREATE INDEX IF NOT EXISTS evidence_by_source ON evidence(source_id);
CREATE TABLE IF NOT EXISTS conflicts (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
  atom_a TEXT NOT NULL REFERENCES atoms(id), atom_b TEXT NOT NULL REFERENCES atoms(id),
  description TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open', resolution TEXT, question_atom TEXT,
  created_at REAL NOT NULL, created_by TEXT NOT NULL, resolved_at REAL, resolved_by TEXT);
CREATE INDEX IF NOT EXISTS conflicts_by_project ON conflicts(project_id, status);
CREATE TABLE IF NOT EXISTS documents (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), title TEXT NOT NULL,
  template TEXT NOT NULL DEFAULT 'neutral',
  created_at REAL NOT NULL, created_by TEXT NOT NULL, updated_at REAL NOT NULL, updated_by TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS doc_versions (
  id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id), number INTEGER NOT NULL,
  content_json TEXT NOT NULL, snapshot_json TEXT NOT NULL, atom_count INTEGER NOT NULL,
  provider TEXT, model TEXT, mode TEXT, created_at REAL NOT NULL, created_by TEXT NOT NULL,
  UNIQUE(document_id, number));
CREATE TABLE IF NOT EXISTS requirement_ids (
  project_id TEXT NOT NULL REFERENCES projects(id), prefix TEXT NOT NULL, number INTEGER NOT NULL,
  atom_id TEXT NOT NULL REFERENCES atoms(id), created_at REAL NOT NULL,
  PRIMARY KEY (project_id, prefix, number), UNIQUE (atom_id, prefix));
CREATE TABLE IF NOT EXISTS free_blocks (
  id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id), section TEXT NOT NULL,
  text TEXT NOT NULL, position REAL NOT NULL, deleted_at REAL,
  created_at REAL NOT NULL, created_by TEXT NOT NULL, updated_at REAL NOT NULL, updated_by TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS backlog_items (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), parent_id TEXT,
  kind TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL DEFAULT '', goal TEXT NOT NULL DEFAULT '',
  acceptance_json TEXT NOT NULL DEFAULT '[]', refs_json TEXT NOT NULL DEFAULT '[]', invest_json TEXT NOT NULL DEFAULT '[]',
  included INTEGER NOT NULL DEFAULT 1, generated INTEGER NOT NULL DEFAULT 0, pinned INTEGER NOT NULL DEFAULT 0,
  position REAL NOT NULL, frd_version INTEGER, jira_key TEXT, deleted_at REAL,
  created_at REAL NOT NULL, created_by TEXT NOT NULL, updated_at REAL NOT NULL, updated_by TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS backlog_by_project ON backlog_items(project_id, deleted_at, position);
CREATE TABLE IF NOT EXISTS action_items (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), source_id TEXT REFERENCES sources(id),
  text TEXT NOT NULL, owner TEXT, due TEXT, status TEXT NOT NULL DEFAULT 'open', quote TEXT, segment_idx INTEGER,
  start REAL, deleted_at REAL,
  created_at REAL NOT NULL, created_by TEXT NOT NULL, updated_at REAL NOT NULL, updated_by TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS actions_by_project ON action_items(project_id, deleted_at, created_at);
CREATE TABLE IF NOT EXISTS jira_targets (
  project_id TEXT PRIMARY KEY REFERENCES projects(id), cloud_id TEXT NOT NULL, site_url TEXT NOT NULL,
  project_key TEXT NOT NULL, project_name TEXT, types_json TEXT NOT NULL DEFAULT '{}',
  updated_at REAL NOT NULL, updated_by TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS project_skills (
  project_id TEXT NOT NULL REFERENCES projects(id), stage TEXT NOT NULL, skill TEXT NOT NULL,
  updated_at REAL NOT NULL, updated_by TEXT NOT NULL, PRIMARY KEY (project_id, stage));
CREATE TABLE IF NOT EXISTS quality_dismissals (
  document_id TEXT NOT NULL REFERENCES documents(id), atom_id TEXT NOT NULL, rule TEXT NOT NULL,
  statement TEXT NOT NULL, created_at REAL NOT NULL, created_by TEXT NOT NULL,
  PRIMARY KEY (document_id, atom_id, rule));
"""

PROJECT_FIELDS = ("id", "name", "local_only", "archived", "language", "jira_quotes", "auto_extract",
                  "created_at", "created_by", "updated_at", "updated_by")
OUTPUT_LANGUAGES = ("auto", "ru", "en")
SOURCE_FIELDS = ("id", "project_id", "kind", "title", "original_filename", "status", "error", "duration",
                 "speakers", "asr_model", "diarized", "import_format", "audio_file", "meta_json", "deleted_at",
                 "created_at", "created_by", "updated_at", "updated_by")


# Project export format ids: 4.9+ writes the first; files exported by 4.x still import.
PROJECT_FORMATS = ("dictum-project", "requirements-workbench-project")

class StoreError(ValueError):
    """A request the store refuses (unknown id, duplicate name, …)."""


def current_user():
    try:
        return getpass.getuser()
    except Exception:
        return "local"


class Store:
    def __init__(self, root=None, user=None, clock=time.time):
        self.root = root or os.path.join(app_data_dir(), "library")
        os.makedirs(self.root, exist_ok=True)
        self.db_path = os.path.join(self.root, "workbench.db")
        self.user = user or current_user()
        self._clock = clock
        self._write_lock = threading.Lock()
        with self._conn() as c:
            c.executescript(SCHEMA)
            self._migrate(c)
            c.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))

    @staticmethod
    def _migrate(c):
        """Bring databases created by older versions up to the current schema."""
        cols = {r["name"] for r in c.execute("PRAGMA table_info(sources)")}
        if "meta_json" not in cols:                       # v1 → v2: email / document metadata
            c.execute("ALTER TABLE sources ADD COLUMN meta_json TEXT")
        acols = {r["name"] for r in c.execute("PRAGMA table_info(atoms)")}
        if "deleted_at" not in acols:                     # v7: atoms can be deleted (soft, with undo)
            c.execute("ALTER TABLE atoms ADD COLUMN deleted_at REAL")
        pcols = {r["name"] for r in c.execute("PRAGMA table_info(projects)")}
        if "language" not in pcols:                       # v7: the language the AI writes in, per project
            c.execute("ALTER TABLE projects ADD COLUMN language TEXT NOT NULL DEFAULT 'auto'")
        bcols = {r["name"] for r in c.execute("PRAGMA table_info(backlog_items)")}
        for col in ("jira_hash TEXT", "jira_pushed_at REAL", "jira_remote_updated TEXT", "jira_url TEXT",  # v6 → v7
                    "priority TEXT"):                                                                       # v8
            if col.split()[0] not in bcols:
                c.execute(f"ALTER TABLE backlog_items ADD COLUMN {col}")
        # v8 (PM review): quote policy and auto-extract per project; reject reasons, MoSCoW, question
        # lifecycle and BA-written atoms; document sign-off; corrected transcript segments.
        for table, cols in (("projects", ("jira_quotes TEXT NOT NULL DEFAULT 'auto'", "auto_extract INTEGER NOT NULL DEFAULT 1")),
                            ("atoms", ("reject_reason TEXT", "priority TEXT", "q_state TEXT", "answer TEXT",
                                       "answer_source TEXT", "origin TEXT")),
                            ("doc_versions", ("status TEXT NOT NULL DEFAULT 'draft'", "status_at REAL", "status_by TEXT")),
                            ("documents", ("kind TEXT", "deleted_at REAL", "decompose INTEGER")),
                            ("segments", ("original_text TEXT",)),
                            # v9 (5.0 C3): meeting notes and recap styles, one summary row per style.
                            ("sources", ("notes TEXT", "recap_style TEXT")),
                            ("summaries", ("style TEXT NOT NULL DEFAULT 'brief'", "through_idx INTEGER")),
                            # v9 part 2 (5.0 C4.1): lines from the live pass while recording, replaced on stop.
                            ("segments", ("provisional INTEGER NOT NULL DEFAULT 0",))):
            have = {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}
            for col in cols:
                if col.split()[0] not in have:
                    c.execute(f"ALTER TABLE {table} ADD COLUMN {col}")
        # 3.2: "FRD" became the SRS document type; old default titles follow.
        c.execute("UPDATE documents SET title = 'SRS — ' || substr(title, 7) WHERE title LIKE 'FRD — %' AND kind IS NULL")

    # ── plumbing ─────────────────────────────────────────────────────────────
    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @contextmanager
    def _write(self):
        with self._write_lock, self._conn() as c:
            yield c

    def _audit(self, c, entity, entity_id, action, before=None, after=None):
        c.execute("INSERT INTO audit_log VALUES (?,?,?,?,?,?,?,?)",
                  (str(uuid.uuid4()), entity, entity_id, action,
                   json.dumps(before, ensure_ascii=False) if before is not None else None,
                   json.dumps(after, ensure_ascii=False) if after is not None else None,
                   self._clock(), self.user))

    def _stamp(self):
        now = self._clock()
        return now, self.user

    @staticmethod
    def _row(row, fields):
        if row is None:
            return None
        d = {f: row[f] for f in fields}
        if "meta_json" in d:
            raw = d.pop("meta_json")
            d["meta"] = json.loads(raw) if raw else None
        for flag in ("local_only", "archived", "diarized", "auto_extract"):
            if flag in d and d[flag] is not None:
                d[flag] = bool(d[flag])
        return d

    # ── projects ─────────────────────────────────────────────────────────────
    def list_projects(self, include_archived=False):
        q = "SELECT * FROM projects" + ("" if include_archived else " WHERE archived = 0") + " ORDER BY created_at"
        with self._conn() as c:
            return [self._row(r, PROJECT_FIELDS) for r in c.execute(q)]

    def get_project(self, project_id):
        with self._conn() as c:
            p = self._row(c.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone(), PROJECT_FIELDS)
        if p is None:
            raise StoreError("project not found")
        return p

    def _check_name(self, c, name, exclude_id=None):
        name = (name or "").strip()
        if not name:
            raise StoreError("project name must not be empty")
        if len(name) > 100:
            raise StoreError("project name is too long (max 100 characters)")
        # Compare in Python: SQLite's lower() only folds ASCII, so Cyrillic names would slip through.
        folded = name.casefold()
        clash = any(r["name"].casefold() == folded
                    for r in c.execute("SELECT id, name FROM projects WHERE id != ?", (exclude_id or "",)))
        if clash:
            raise StoreError(f"a project called “{name}” already exists")
        return name

    def create_project(self, name, local_only=False):
        with self._write() as c:
            name = self._check_name(c, name)
            now, by = self._stamp()
            pid = str(uuid.uuid4())
            c.execute("INSERT INTO projects (id, name, local_only, archived, created_at, created_by, updated_at, updated_by) "
                      "VALUES (?,?,?,?,?,?,?,?)", (pid, name, int(local_only), 0, now, by, now, by))
            project = self._row(c.execute("SELECT * FROM projects WHERE id = ?", (pid,)).fetchone(), PROJECT_FIELDS)
            self._audit(c, "project", pid, "create", after=project)
        return project

    def update_project(self, project_id, **changes):
        allowed = {"name", "local_only", "archived", "language", "jira_quotes", "auto_extract"}
        unknown = set(changes) - allowed
        if unknown:
            raise StoreError(f"cannot change {sorted(unknown)}")
        if "language" in changes and changes["language"] not in OUTPUT_LANGUAGES:
            raise StoreError(f"language must be one of {OUTPUT_LANGUAGES}")
        if "jira_quotes" in changes and changes["jira_quotes"] not in JIRA_QUOTES:
            raise StoreError(f"jira_quotes must be one of {sorted(JIRA_QUOTES)}")
        with self._write() as c:
            before = self._row(c.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone(), PROJECT_FIELDS)
            if before is None:
                raise StoreError("project not found")
            if "name" in changes:
                changes["name"] = self._check_name(c, changes["name"], exclude_id=project_id)
            for flag in ("local_only", "archived", "auto_extract"):
                if flag in changes:
                    changes[flag] = int(bool(changes[flag]))
            if changes:
                now, by = self._stamp()
                sets = ", ".join(f"{k} = ?" for k in changes)
                c.execute(f"UPDATE projects SET {sets}, updated_at = ?, updated_by = ? WHERE id = ?",
                          (*changes.values(), now, by, project_id))
            after = self._row(c.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone(), PROJECT_FIELDS)
            if after != before:
                self._audit(c, "project", project_id, "update", before, after)
        return after

    def ensure_default_project(self, name="Мой проект"):
        projects = self.list_projects()
        return projects[0] if projects else self.create_project(name)

    def current_project(self):
        """The project the app shows; falls back to the first active one (created if none)."""
        with self._conn() as c:
            row = c.execute("SELECT value FROM meta WHERE key = 'current_project'").fetchone()
        if row:
            try:
                p = self.get_project(row["value"])
                if not p["archived"]:
                    return p
            except StoreError:
                pass
        return self.ensure_default_project()

    def set_current_project(self, project_id):
        p = self.get_project(project_id)
        if p["archived"]:
            raise StoreError("that project is archived; restore it first")
        with self._write() as c:
            c.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('current_project', ?)", (project_id,))
        return p

    # ── sources ──────────────────────────────────────────────────────────────
    def source_dir(self, source):
        return os.path.join(self.root, "projects", source["project_id"], "sources", source["id"])

    def create_source(self, project_id, kind, title, original_filename=None, status="processing", **fields):
        if kind not in SOURCE_KINDS:
            raise StoreError(f"unknown source kind {kind}")
        self.get_project(project_id)
        with self._write() as c:
            now, by = self._stamp()
            sid = str(uuid.uuid4())
            c.execute("""INSERT INTO sources (id, project_id, kind, title, original_filename, status, asr_model,
                         import_format, created_at, created_by, updated_at, updated_by)
                         VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (sid, project_id, kind, (title or "Untitled").strip()[:200], original_filename, status,
                       fields.get("asr_model"), fields.get("import_format"), now, by, now, by))
            source = self._row(c.execute("SELECT * FROM sources WHERE id = ?", (sid,)).fetchone(), SOURCE_FIELDS)
            self._audit(c, "source", sid, "create", after=source)
        os.makedirs(self.source_dir(source), exist_ok=True)
        return source

    def get_source(self, source_id, include_deleted=False):
        with self._conn() as c:
            row = c.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
        s = self._row(row, SOURCE_FIELDS)
        if s is None or (s["deleted_at"] and not include_deleted):
            raise StoreError("source not found")
        return s

    # Timed transcripts (Teams/Zoom exports) are imports of a call; other text sources are text.
    TIMED_IMPORT_FORMATS = ("vtt", "srt")
    SOURCE_SORTS = {"new": "s.created_at DESC", "old": "s.created_at ASC", "az": "s.created_at DESC"}   # az: sorted below

    @classmethod
    def source_tag(cls, kind, import_format):
        """The list tag key: recording | import | text (the UI translates it)."""
        if kind == "recording":
            return "recording"
        if kind == "audio" or (kind == "transcript" and (import_format or "").lower() in cls.TIMED_IMPORT_FORMATS):
            return "import"
        return "text"

    def list_sources(self, project_id, q=None, sort="new"):
        """The project's sources, newest first by default. `q` matches the title, the source text and the
        segment text, case-insensitively (any script). Each row carries `people`, `atoms` and `tags`."""
        order = self.SOURCE_SORTS.get(sort or "new")
        if order is None:
            raise StoreError(f"unknown sort {sort}")
        needle = (q or "").strip().casefold()
        where, args = "s.project_id = ? AND s.deleted_at IS NULL", [project_id]
        if needle:
            where += """ AND (ci_has(s.title, ?) OR ci_has(s.text, ?)
                         OR EXISTS (SELECT 1 FROM segments g WHERE g.source_id = s.id AND ci_has(g.text, ?)))"""
            args += [needle] * 3
        with self._conn() as c:
            c.create_function("ci_has", 2, lambda hay, n: int(bool(hay) and n in hay.casefold()), deterministic=True)
            rows = c.execute(f"""SELECT s.*, (SELECT COUNT(*) FROM summaries m WHERE m.source_id = s.id) AS summary_count,
                                  (SELECT COUNT(DISTINCT e.atom_id) FROM evidence e JOIN atoms a ON a.id = e.atom_id
                                   WHERE e.source_id = s.id AND a.status != 'merged' AND a.deleted_at IS NULL) AS atom_count,
                                  (SELECT COUNT(DISTINCT e.atom_id) FROM evidence e JOIN atoms a ON a.id = e.atom_id
                                   WHERE e.source_id = s.id AND a.status NOT IN ('merged', 'rejected')
                                   AND a.deleted_at IS NULL) AS live_atoms
                                FROM sources s WHERE {where}
                                ORDER BY {order}""", args).fetchall()
            if sort == "az":      # SQLite's NOCASE folds ASCII only; Cyrillic titles sort here
                rows.sort(key=lambda r: (r["title"] or "").casefold())
            ids = [r["id"] for r in rows]
            renamed, labels = {}, {}
            if ids:
                marks = ",".join("?" * len(ids))
                for r in c.execute(f"SELECT source_id, label, name FROM speakers WHERE source_id IN ({marks}) "
                                   "ORDER BY updated_at", ids):
                    renamed.setdefault(r["source_id"], {})[r["label"]] = r["name"]
                for r in c.execute(f"""SELECT source_id, speaker FROM segments WHERE source_id IN ({marks})
                                       AND speaker IS NOT NULL AND speaker != ''
                                       GROUP BY source_id, speaker ORDER BY source_id, MIN(idx)""", ids):
                    labels.setdefault(r["source_id"], []).append(r["speaker"])
        out = []
        for r in rows:
            s = self._row(r, SOURCE_FIELDS)
            s["has_summary"] = r["summary_count"] > 0
            s["atom_count"] = r["atom_count"]
            s["atoms"] = r["live_atoms"]
            names = renamed.get(s["id"], {})
            order_labels = labels.get(s["id"], [])
            # Renamed speakers first (in the order they speak), then the others by their label.
            people = [names[l] for l in order_labels if l in names]
            people += [n for l, n in names.items() if l not in order_labels]
            people += [l for l in order_labels if l not in names]
            s["people"] = ", ".join(people[:4])
            s["tags"] = self.source_tag(s["kind"], s.get("import_format"))
            out.append(s)
        return out

    def update_source(self, source_id, audit=True, **changes):
        allowed = {"title", "status", "error", "duration", "speakers", "asr_model", "diarized",
                   "import_format", "audio_file", "text", "words_json", "meta_json"}
        unknown = set(changes) - allowed
        if unknown:
            raise StoreError(f"cannot change {sorted(unknown)}")
        if "status" in changes and changes["status"] not in SOURCE_STATUSES:
            raise StoreError(f"unknown status {changes['status']}")
        if "title" in changes:
            changes["title"] = (changes["title"] or "").strip()[:200]
            if not changes["title"]:
                raise StoreError("title must not be empty")
        with self._write() as c:
            before = self._row(c.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone(), SOURCE_FIELDS)
            if before is None:
                raise StoreError("source not found")
            now, by = self._stamp()
            if "diarized" in changes:
                changes["diarized"] = int(bool(changes["diarized"]))
            sets = ", ".join(f"{k} = ?" for k in changes)
            c.execute(f"UPDATE sources SET {sets}, updated_at = ?, updated_by = ? WHERE id = ?",
                      (*changes.values(), now, by, source_id))
            after = self._row(c.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone(), SOURCE_FIELDS)
            if audit:
                self._audit(c, "source", source_id, "update", before, after)
        return after

    def delete_source(self, source_id):
        """Soft delete: hidden everywhere, files kept, recoverable with restore_source()."""
        with self._write() as c:
            before = self._row(c.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone(), SOURCE_FIELDS)
            if before is None or before["deleted_at"]:
                raise StoreError("source not found")
            now, by = self._stamp()
            c.execute("UPDATE sources SET deleted_at = ?, updated_at = ?, updated_by = ? WHERE id = ?",
                      (now, now, by, source_id))
            self._audit(c, "source", source_id, "delete", before)

    def restore_source(self, source_id):
        with self._write() as c:
            now, by = self._stamp()
            n = c.execute("UPDATE sources SET deleted_at = NULL, updated_at = ?, updated_by = ? "
                          "WHERE id = ? AND deleted_at IS NOT NULL", (now, by, source_id)).rowcount
            if not n:
                raise StoreError("nothing to restore")
            self._audit(c, "source", source_id, "restore")

    def save_transcript(self, source_id, result, asr_model=None):
        """Store a transcription or import result (the shape produced by app._transcribe
        and core.transcripts) and mark the source ready."""
        segments = result.get("segments") or []
        if not segments and result.get("text"):
            segments = [{"text": result["text"]}]
        ends = [s["end"] for s in segments if s.get("end") is not None]
        speakers = {s.get("speaker") for s in segments if s.get("speaker")}
        with self._write() as c:
            c.execute("DELETE FROM segments WHERE source_id = ?", (source_id,))
            c.executemany('INSERT INTO segments (source_id, idx, speaker, start, "end", text) VALUES (?,?,?,?,?,?)',
                          [(source_id, i, s.get("speaker"), s.get("start"), s.get("end"), s.get("text", ""))
                           for i, s in enumerate(segments)])
        changes = dict(status="ready", error=None, text=result.get("text", ""),
                       diarized=bool(result.get("diarized")), speakers=len(speakers) or None,
                       words_json=json.dumps(result["words"], ensure_ascii=False) if result.get("words") else None)
        if ends:
            changes["duration"] = max(ends)
        if asr_model:
            changes["asr_model"] = asr_model
        if result.get("imported"):
            changes["import_format"] = result["imported"].get("format")
        if result.get("email"):
            changes["meta_json"] = json.dumps({"email": result["email"]}, ensure_ascii=False)
        return self.update_source(source_id, **changes)

    def edit_segment(self, source_id, idx, text):
        """Correct a recognition error (PM-25). The first original is kept; the source text is rebuilt;
        atoms quoting this line whose quote no longer appears in it are returned so the BA can check them."""
        from core.atoms import normalize             # local import: atoms imports this module
        text = (text or "").strip()
        if not text:
            raise StoreError("the text must not be empty")
        with self._write() as c:
            row = c.execute("SELECT * FROM segments WHERE source_id = ? AND idx = ?", (source_id, idx)).fetchone()
            if row is None:
                raise StoreError("segment not found")
            if row["text"] == text:
                return {"broken": []}
            original = row["original_text"] if row["original_text"] is not None else row["text"]
            c.execute("UPDATE segments SET text = ?, original_text = ? WHERE source_id = ? AND idx = ?",
                      (text, None if text == original else original, source_id, idx))
            full = " ".join(r["text"] for r in c.execute("SELECT text FROM segments WHERE source_id = ? ORDER BY idx",
                                                         (source_id,)))
            now, by = self._stamp()
            c.execute("UPDATE sources SET text = ?, updated_at = ?, updated_by = ? WHERE id = ?", (full, now, by, source_id))
            self._audit(c, "source", source_id, "edit_segment", {"idx": idx, "text": row["text"]}, {"idx": idx, "text": text})
            broken = [r["atom_id"] for r in c.execute("SELECT atom_id, quote FROM evidence WHERE source_id = ? AND segment_idx = ?",
                                                      (source_id, idx)) if normalize(r["quote"]) not in normalize(text)]
        return {"broken": sorted(set(broken))}

    def atom_marks(self, source_id):
        """Which lines of a source became atoms (FR-TR-03): segment idx → [{atom_id, status, type}]."""
        with self._conn() as c:
            rows = c.execute("""SELECT e.segment_idx, e.quote, a.id, a.status, a.type, a.statement FROM evidence e JOIN atoms a ON a.id = e.atom_id
                                WHERE e.source_id = ? AND a.deleted_at IS NULL AND a.status != 'merged'""", (source_id,)).fetchall()
        out = {}
        seen = set()                      # an atom with two quotes on one line is marked once
        for r in rows:
            if r["segment_idx"] is None or (r["segment_idx"], r["id"]) in seen:
                continue
            seen.add((r["segment_idx"], r["id"]))
            out.setdefault(r["segment_idx"], []).append({"atom_id": r["id"], "status": r["status"], "type": r["type"],
                                                         "statement": r["statement"], "quote": r["quote"]})
        return out

    def reset_stale_processing(self):
        """A source still marked "processing" when the app starts was cut off mid-job (quit, crash):
        no job survives a restart. Put it back where the BA can transcribe it again."""
        with self._write() as c:
            rows = c.execute("SELECT id, audio_file FROM sources WHERE status = 'processing' AND deleted_at IS NULL").fetchall()
            now, by = self._stamp()
            for r in rows:
                status, error = ("recorded", None) if r["audio_file"] else ("failed", "Interrupted before it finished")
                c.execute("UPDATE sources SET status = ?, error = ?, updated_at = ?, updated_by = ? WHERE id = ?",
                          (status, error, now, by, r["id"]))
                self._audit(c, "source", r["id"], "interrupted", after={"status": status})
        return len(rows)

    def recover_interrupted_recordings(self):
        """A source still "recording" when the app starts lost its recorder (quit, crash). Its mic.wav / sys.wav
        are on disk and untouched: offer it as an untranscribed recording, so the BA can press Расшифровать.
        Only reads the folder; never opens, moves or rewrites an audio file."""
        with self._write() as c:
            rows = c.execute("SELECT * FROM sources WHERE status = 'recording' AND deleted_at IS NULL").fetchall()
            now, by = self._stamp()
            for r in rows:
                folder = self.source_dir(r)
                have = [n for n in ("mixed.wav", "sys.wav", "mic.wav")
                        if os.path.exists(os.path.join(folder, n)) and os.path.getsize(os.path.join(folder, n)) > 44]
                if have:
                    status, error, audio = "recorded", None, have[0]
                else:
                    status, error, audio = "failed", "Interrupted before any audio was captured", r["audio_file"]
                c.execute("UPDATE sources SET status = ?, error = ?, audio_file = ?, updated_at = ?, updated_by = ? "
                          "WHERE id = ?", (status, error, audio, now, by, r["id"]))
                self._audit(c, "source", r["id"], "interrupted", after={"status": status, "audio_file": audio})
        return len(rows)

    # ── live transcript (5.0 C4.1) ───────────────────────────────────────────
    def append_provisional_segments(self, source_id, segments):
        """Append live-pass lines ({speaker, start, end, text}) after the existing ones; returns them with idx."""
        out = []
        with self._write() as c:
            r = c.execute("SELECT MAX(idx) AS m FROM segments WHERE source_id = ?", (source_id,)).fetchone()
            nxt = (r["m"] + 1) if r["m"] is not None else 0
            for s in segments:
                c.execute('INSERT INTO segments (source_id, idx, speaker, start, "end", text, provisional) '
                          'VALUES (?,?,?,?,?,?,1)', (source_id, nxt, s.get("speaker"), s.get("start"), s.get("end"),
                                                     s.get("text", "")))
                out.append({**s, "idx": nxt, "provisional": True})
                nxt += 1
        return out

    def delete_provisional_segments(self, source_id):
        with self._write() as c:
            return c.execute("DELETE FROM segments WHERE source_id = ? AND provisional = 1", (source_id,)).rowcount

    def fail_source(self, source_id, error):
        return self.update_source(source_id, status="failed", error=str(error)[:1000])

    def transcript(self, source_id):
        """Segments with display names applied, plus the speaker map."""
        with self._conn() as c:
            names = {r["label"]: r["name"] for r in c.execute(
                "SELECT label, name FROM speakers WHERE source_id = ?", (source_id,))}
            segs = [dict(idx=r["idx"], speaker=r["speaker"], start=r["start"], end=r["end"], text=r["text"],
                         corrected=r["original_text"] is not None, provisional=bool(r["provisional"]))
                    for r in c.execute('SELECT idx, speaker, start, "end", text, original_text, provisional FROM segments '
                                       'WHERE source_id = ? ORDER BY idx', (source_id,))]
        for s in segs:
            s["speaker_name"] = names.get(s["speaker"], s["speaker"])
        return segs, names

    def rename_speaker(self, source_id, label, name):
        name = (name or "").strip()[:80]
        self.get_source(source_id)
        with self._write() as c:
            exists = c.execute("SELECT 1 FROM segments WHERE source_id = ? AND speaker = ? LIMIT 1",
                               (source_id, label)).fetchone()
            if not exists:
                raise StoreError(f"no speaker {label!r} in this source")
            old = c.execute("SELECT name FROM speakers WHERE source_id = ? AND label = ?", (source_id, label)).fetchone()
            now, by = self._stamp()
            if name and name != label:
                c.execute("INSERT OR REPLACE INTO speakers VALUES (?,?,?,?,?)", (source_id, label, name, now, by))
            else:
                c.execute("DELETE FROM speakers WHERE source_id = ? AND label = ?", (source_id, label))
            self._audit(c, "speaker", f"{source_id}:{label}", "rename",
                        {"name": old["name"] if old else label}, {"name": name or label})

    def transcript_text(self, source_id, after_idx=None):
        """Plain text for summaries, with renamed speakers and timestamps (only the lines after `after_idx` if given)."""
        from core.transcripts import format_time
        segs, _ = self.transcript(source_id)
        lines = []
        for s in segs:
            if after_idx is not None and s["idx"] <= after_idx:
                continue
            prefix = f"[{s['speaker_name']}] " if s.get("speaker_name") else ""
            if s.get("start") is not None:
                end = f" - {format_time(s['end'])}" if s.get("end") is not None else ""
                prefix += f"[{format_time(s['start'])}{end}] "
            lines.append(prefix + s["text"])
        return "\n".join(lines)

    # ── summaries ────────────────────────────────────────────────────────────
    def add_summary(self, source_id, provider, model, text, style="brief", through_idx=None):
        """Store the recap of one style; it replaces that style's earlier row (one row per style)."""
        if style not in RECAP_STYLES:
            raise StoreError(f"unknown recap style {style}")
        self.get_source(source_id)
        with self._write() as c:
            now, by = self._stamp()
            mid = str(uuid.uuid4())
            old = [r["id"] for r in c.execute("SELECT id FROM summaries WHERE source_id = ? AND style = ?", (source_id, style))]
            c.execute("DELETE FROM summaries WHERE source_id = ? AND style = ?", (source_id, style))
            c.execute("""INSERT INTO summaries (id, source_id, provider, model, text, created_at, created_by, style, through_idx)
                         VALUES (?,?,?,?,?,?,?,?,?)""", (mid, source_id, provider, model, text, now, by, style, through_idx))
            self._audit(c, "summary", mid, "create", after={"source_id": source_id, "provider": provider, "model": model,
                                                            "style": style, "through_idx": through_idx, "replaces": old})
        return {"id": mid, "source_id": source_id, "provider": provider, "model": model, "text": text,
                "created_at": now, "created_by": by, "style": style, "through_idx": through_idx}

    def latest_summary(self, source_id, style=None):
        q, args = "SELECT * FROM summaries WHERE source_id = ?", [source_id]
        if style:
            q += " AND style = ?"
            args.append(style)
        with self._conn() as c:
            r = c.execute(q + " ORDER BY created_at DESC LIMIT 1", args).fetchone()
        return dict(r) if r else None

    def summaries(self, source_id):
        """{style: summary row}: the newest row of each style."""
        out = {}
        with self._conn() as c:
            for r in c.execute("SELECT * FROM summaries WHERE source_id = ? ORDER BY created_at", (source_id,)):
                out[r["style"]] = dict(r)
        return out

    def last_segment_idx(self, source_id):
        with self._conn() as c:
            r = c.execute("SELECT MAX(idx) AS m FROM segments WHERE source_id = ?", (source_id,)).fetchone()
        return r["m"]

    # ── meeting notes (5.0 C3) ───────────────────────────────────────────────
    def notes(self, source_id):
        """(notes, recap_style) of a source."""
        with self._conn() as c:
            r = c.execute("SELECT notes, recap_style, deleted_at FROM sources WHERE id = ?", (source_id,)).fetchone()
        if r is None or r["deleted_at"]:
            raise StoreError("source not found")
        return r["notes"] or "", r["recap_style"]

    NOTES_MAX = 200_000
    NOTES_COALESCE = 60          # seconds: autosaves within this window update one audit entry

    def update_notes(self, source_id, change, action="notes"):
        """Set the notes to change(old_text) in one transaction; returns {saved_at, text}.
        Autosaves ("notes") by the same person within a minute share one audit entry, so typing does not
        flood the log; every append ("notes_append") is its own entry."""
        with self._write() as c:
            r = c.execute("SELECT notes, deleted_at FROM sources WHERE id = ?", (source_id,)).fetchone()
            if r is None or r["deleted_at"]:
                raise StoreError("source not found")
            before = r["notes"] or ""
            text = change(before)
            if not isinstance(text, str):
                raise StoreError("notes must be text")
            if len(text) > self.NOTES_MAX:
                raise StoreError("the notes are too long")
            now, by = self._stamp()
            c.execute("UPDATE sources SET notes = ?, updated_at = ?, updated_by = ? WHERE id = ?", (text, now, by, source_id))
            last = c.execute("SELECT id, action, at, by, before_json FROM audit_log WHERE entity = 'source' AND entity_id = ? "
                             "ORDER BY at DESC LIMIT 1", (source_id,)).fetchone()
            if (action == "notes" and last and last["action"] == "notes" and last["by"] == by
                    and now - last["at"] <= self.NOTES_COALESCE):
                c.execute("UPDATE audit_log SET after_json = ?, at = ? WHERE id = ?",
                          (json.dumps({"notes": text}, ensure_ascii=False), now, last["id"]))
            elif text != before:
                self._audit(c, "source", source_id, action, {"notes": before}, {"notes": text})
        return {"saved_at": now, "text": text}

    def set_recap_style(self, source_id, style):
        if style not in RECAP_STYLES:
            raise StoreError(f"unknown recap style {style}")
        with self._write() as c:
            c.execute("UPDATE sources SET recap_style = ? WHERE id = ?", (style, source_id))

    # ── audit ────────────────────────────────────────────────────────────────
    def audit(self, entity=None, entity_id=None, limit=200):
        q, args = "SELECT * FROM audit_log", []
        conds = []
        if entity:
            conds.append("entity = ?")
            args.append(entity)
        if entity_id:
            conds.append("entity_id = ?")
            args.append(entity_id)
        if conds:
            q += " WHERE " + " AND ".join(conds)
        q += " ORDER BY at DESC LIMIT ?"
        args.append(limit)
        with self._conn() as c:
            rows = c.execute(q, args).fetchall()
        return [dict(r, before=json.loads(r["before_json"]) if r["before_json"] else None,
                     after=json.loads(r["after_json"]) if r["after_json"] else None) for r in rows]

    def activity(self, project_id, limit=100, since=None):
        """A project's history across sources, atoms, conflicts, the document, the backlog and actions (PM-23)."""
        q = """SELECT l.*, COALESCE(a.statement, s.title, b.title, d.title, x.text, '') AS label FROM audit_log l
               LEFT JOIN atoms a ON l.entity = 'atom' AND a.id = l.entity_id
               LEFT JOIN sources s ON l.entity = 'source' AND s.id = l.entity_id
               LEFT JOIN backlog_items b ON l.entity = 'backlog' AND b.id = l.entity_id
               LEFT JOIN documents d ON l.entity = 'document' AND d.id = l.entity_id
               LEFT JOIN action_items x ON l.entity = 'action' AND x.id = l.entity_id
               LEFT JOIN conflicts cf ON l.entity = 'conflict' AND cf.id = l.entity_id
               WHERE (a.project_id = ? OR s.project_id = ? OR b.project_id = ? OR d.project_id = ? OR x.project_id = ?
                      OR cf.project_id = ? OR (l.entity = 'project' AND l.entity_id = ?))"""
        args = [project_id] * 7
        if since:
            q += " AND l.at > ?"
            args.append(since)
        q += " ORDER BY l.at DESC LIMIT ?"
        args.append(limit)
        with self._conn() as c:
            rows = c.execute(q, args).fetchall()
        return [{"entity": r["entity"], "entity_id": r["entity_id"], "action": r["action"], "at": r["at"], "by": r["by"],
                 "label": r["label"], "before": json.loads(r["before_json"]) if r["before_json"] else None,
                 "after": json.loads(r["after_json"]) if r["after_json"] else None} for r in rows]

    # ── project export / import (PM-31) ───────────────────────────────────────
    _EXPORT_TABLES = (  # table, how rows belong to the project
        ("projects", "id = ?"), ("sources", "project_id = ?"),
        ("segments", "source_id IN (SELECT id FROM sources WHERE project_id = ?)"),
        ("speakers", "source_id IN (SELECT id FROM sources WHERE project_id = ?)"),
        ("summaries", "source_id IN (SELECT id FROM sources WHERE project_id = ?)"),
        ("atoms", "project_id = ?"), ("evidence", "atom_id IN (SELECT id FROM atoms WHERE project_id = ?)"),
        ("conflicts", "project_id = ?"), ("documents", "project_id = ?"),
        ("doc_versions", "document_id IN (SELECT id FROM documents WHERE project_id = ?)"),
        ("requirement_ids", "project_id = ?"),
        ("free_blocks", "document_id IN (SELECT id FROM documents WHERE project_id = ?)"),
        ("quality_dismissals", "document_id IN (SELECT id FROM documents WHERE project_id = ?)"),
        ("project_skills", "project_id = ?"), ("backlog_items", "project_id = ?"), ("action_items", "project_id = ?"),
    )

    def export_project(self, project_id):
        """Every row of the project (and its audit trail) as plain data; audio files are added by the caller."""
        self.get_project(project_id)
        out = {"format": "dictum-project", "schema": SCHEMA_VERSION, "tables": {}}
        with self._conn() as c:
            for table, where in self._EXPORT_TABLES:
                out["tables"][table] = [dict(r) for r in c.execute(f"SELECT * FROM {table} WHERE {where}", (project_id,))]
        out["audit"] = [dict(r) for r in self._audit_rows_for(project_id)]
        return out

    def _audit_rows_for(self, project_id):
        ids = {project_id}
        with self._conn() as c:
            for table in ("sources", "atoms", "conflicts", "documents", "backlog_items", "action_items"):
                ids |= {r[0] for r in c.execute(f"SELECT id FROM {table} WHERE project_id = ?", (project_id,))}
            marks = ",".join("?" * len(ids))
            return c.execute(f"SELECT * FROM audit_log WHERE entity_id IN ({marks}) ORDER BY at", list(ids)).fetchall()

    def import_project(self, data):
        """Load an exported project. Refused if a project with the same id already exists here."""
        if not isinstance(data, dict) or data.get("format") not in PROJECT_FORMATS:
            raise StoreError("this is not a Dictum project file")
        tables = data.get("tables") or {}
        [project] = tables.get("projects") or [None]
        if not project:
            raise StoreError("the file has no project")
        with self._write() as c:
            if c.execute("SELECT 1 FROM projects WHERE id = ?", (project["id"],)).fetchone():
                raise StoreError("this project is already in your library")
            name = project["name"]
            n = 2
            while c.execute("SELECT 1 FROM projects WHERE lower(name) = lower(?)", (name,)).fetchone():
                name = f"{project['name']} ({n})"
                n += 1
            project = {**project, "name": name, "archived": 0}
            tables = {**tables, "projects": [project]}
            for table, _where in self._EXPORT_TABLES:
                cols = {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}
                for row in tables.get(table) or []:
                    row = {k: v for k, v in row.items() if k in cols}
                    if row:
                        c.execute(f"INSERT OR IGNORE INTO {table} ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})",
                                  list(row.values()))
            for r in data.get("audit") or []:
                c.execute("INSERT OR IGNORE INTO audit_log (id, entity, entity_id, action, before_json, after_json, at, by) "
                          "VALUES (?,?,?,?,?,?,?,?)", (r["id"], r["entity"], r["entity_id"], r["action"], r.get("before_json"),
                                                       r.get("after_json"), r["at"], r["by"]))
            self._audit(c, "project", project["id"], "import", after={"name": name})
        return self.get_project(project["id"])

    def audit_event(self, entity, entity_id, action, before=None, after=None):
        with self._write() as c:
            self._audit(c, entity, entity_id, action, before, after)

    # ── atoms (spec increment 2: FR-ATM-*, BR-01…04, BR-13, D-06, D-09) ────────
    def _atom_row(self, c, atom_id):
        r = c.execute("SELECT * FROM atoms WHERE id = ?", (atom_id,)).fetchone()
        if r is None:
            raise StoreError("atom not found")
        return dict(r)

    def add_atoms(self, project_id, atoms, model=None):
        """atoms: [{type, statement, evidence: [{source_id, segment_idx, start, speaker, quote}]}]"""
        self.get_project(project_id)
        created = []
        with self._write() as c:
            for a in atoms:
                if a["type"] not in ATOM_TYPES:
                    raise StoreError(f"unknown atom type {a['type']}")
                statement = (a.get("statement") or "").strip()
                if not statement or not a.get("evidence"):
                    raise StoreError("an atom needs a statement and at least one piece of evidence")
                now, by = self._stamp()
                aid = str(uuid.uuid4())
                c.execute("INSERT INTO atoms (id, project_id, type, statement, original_statement, status, model, "
                          "created_at, created_by, updated_at, updated_by) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                          (aid, project_id, a["type"], statement, statement, "pending", model, now, by, now, by))
                for ev in a["evidence"]:
                    c.execute("INSERT INTO evidence VALUES (?,?,?,?,?,?,?,?)",
                              (str(uuid.uuid4()), aid, ev["source_id"], ev.get("segment_idx"), ev.get("start"),
                               ev.get("speaker"), ev["quote"], now))
                self._audit(c, "atom", aid, "create", after={"type": a["type"], "statement": statement})
                created.append(aid)
        return created

    def _evidence(self, c, atom_ids):
        out = {i: [] for i in atom_ids}
        if not atom_ids:
            return out
        marks = ",".join("?" * len(atom_ids))
        for r in c.execute(f"""SELECT e.*, s.title AS source_title, s.kind AS source_kind, s.created_at AS source_date,
                               COALESCE(sp.name, e.speaker) AS speaker_name
                               FROM evidence e JOIN sources s ON s.id = e.source_id
                               LEFT JOIN speakers sp ON sp.source_id = e.source_id AND sp.label = e.speaker
                               WHERE e.atom_id IN ({marks}) ORDER BY e.created_at, e.start""", atom_ids):
            out[r["atom_id"]].append({k: r[k] for k in ("id", "source_id", "source_title", "source_kind", "source_date",
                                                         "segment_idx", "start", "speaker", "speaker_name", "quote")})
        return out

    def list_atoms(self, project_id, status=None, type=None, source_id=None):
        q, args = "SELECT * FROM atoms WHERE project_id = ? AND deleted_at IS NULL", [project_id]
        if status:
            q += " AND status = ?"
            args.append(status)
        if type:
            q += " AND type = ?"
            args.append(type)
        if source_id:
            q += " AND id IN (SELECT atom_id FROM evidence WHERE source_id = ?)"
            args.append(source_id)
        q += " ORDER BY created_at, rowid"
        with self._conn() as c:
            atoms = [dict(r) for r in c.execute(q, args)]
            ev = self._evidence(c, [a["id"] for a in atoms])
            conflicts = {}
            for r in c.execute("SELECT * FROM conflicts WHERE project_id = ? AND status != 'resolved'", (project_id,)):
                for side, other in (("atom_a", "atom_b"), ("atom_b", "atom_a")):
                    conflicts.setdefault(r[side], []).append({"id": r["id"], "other": r[other],
                                                              "description": r["description"], "status": r["status"]})
        for a in atoms:
            a["evidence"] = ev[a["id"]]
            a["conflicts"] = conflicts.get(a["id"], [])
        return atoms

    def get_atom(self, atom_id):
        with self._conn() as c:
            a = self._atom_row(c, atom_id)
            a["evidence"] = self._evidence(c, [atom_id])[atom_id]
        return a

    def update_atom(self, atom_id, **changes):
        allowed = {"statement", "type", "status", "reject_reason", "priority", "q_state"}
        if not changes:
            raise StoreError("nothing to change")
        if set(changes) - allowed:
            raise StoreError(f"cannot change {sorted(set(changes) - allowed)}")
        if changes.get("reject_reason") not in (None, "") and changes["reject_reason"] not in REJECT_REASONS:
            raise StoreError(f"reject_reason must be one of {sorted(REJECT_REASONS)}")
        if changes.get("priority") not in (None, "") and changes["priority"] not in PRIORITIES:
            raise StoreError(f"priority must be one of {sorted(PRIORITIES)}")
        if changes.get("q_state") not in (None, "") and changes["q_state"] not in QUESTION_STATES:
            raise StoreError(f"q_state must be one of {sorted(QUESTION_STATES)}")
        for k in ("reject_reason", "priority", "q_state"):
            if k in changes and changes[k] == "":
                changes[k] = None
        if "type" in changes and changes["type"] not in ATOM_TYPES:
            raise StoreError(f"unknown atom type {changes['type']}")
        if "status" in changes and changes["status"] not in ATOM_STATUSES - {"merged"}:
            raise StoreError("status must be pending, accepted or rejected")
        if "statement" in changes:
            changes["statement"] = (changes["statement"] or "").strip()
            if not changes["statement"]:
                raise StoreError("the statement must not be empty")
        with self._write() as c:
            before = self._atom_row(c, atom_id)
            if before["status"] == "merged":
                raise StoreError("this atom was merged into another one")
            if before.get("deleted_at"):
                raise StoreError("this atom was deleted")
            if changes.get("status") and changes["status"] != "rejected" and before["reject_reason"] \
                    and "reject_reason" not in changes:
                changes["reject_reason"] = None       # a reason only means something on a rejected atom
            now, by = self._stamp()
            sets = ", ".join(f"{k} = ?" for k in changes)
            c.execute(f"UPDATE atoms SET {sets}, updated_at = ?, updated_by = ? WHERE id = ?",
                      (*changes.values(), now, by, atom_id))
            after = self._atom_row(c, atom_id)
            action = changes.get("status") if changes.get("status") and set(changes) <= {"status", "reject_reason"} else "edit"
            self._audit(c, "atom", atom_id, action, {k: before[k] for k in changes}, {k: after[k] for k in changes})
        return self.get_atom(atom_id)

    def bulk_update_atoms(self, project_id, items):
        """Change many atoms in one transaction: items = [{id, status?, type?}]. Merged atoms and atoms
        of other projects are skipped. Each change is audited like a single one. Returns the ids changed."""
        if not isinstance(items, list) or not items:
            raise StoreError("nothing to change")
        if len(items) > 5000:
            raise StoreError("too many atoms at once")
        for it in items:
            if not isinstance(it, dict) or not it.get("id") or not ({"status", "type", "priority", "reject_reason"} & set(it)):
                raise StoreError("each item needs an id and a status, type or priority")
            if set(it) - {"id", "status", "type", "priority", "reject_reason"}:
                raise StoreError("only status, type, priority and the reject reason can be changed in bulk")
            if it.get("priority") not in (None, "") and it["priority"] not in PRIORITIES:
                raise StoreError(f"priority must be one of {sorted(PRIORITIES)}")
            if it.get("reject_reason") not in (None, "") and it["reject_reason"] not in REJECT_REASONS:
                raise StoreError(f"reject_reason must be one of {sorted(REJECT_REASONS)}")
            if "status" in it and it["status"] not in ATOM_STATUSES - {"merged"}:
                raise StoreError("status must be pending, accepted or rejected")
            if "type" in it and it["type"] not in ATOM_TYPES:
                raise StoreError(f"unknown atom type {it['type']}")
        changed = []
        with self._write() as c:
            now, by = self._stamp()
            for it in items:
                row = c.execute("SELECT * FROM atoms WHERE id = ?", (it["id"],)).fetchone()
                if row is None or row["project_id"] != project_id or row["status"] == "merged" or row["deleted_at"]:
                    continue
                changes = {k: (it[k] or None) for k in ("status", "type", "priority", "reject_reason")
                           if k in it and (it[k] or None) != row[k]}
                if changes.get("status") and changes["status"] != "rejected" and row["reject_reason"]:
                    changes["reject_reason"] = None
                if not changes:
                    continue
                sets = ", ".join(f"{k} = ?" for k in changes)
                c.execute(f"UPDATE atoms SET {sets}, updated_at = ?, updated_by = ? WHERE id = ?",
                          (*changes.values(), now, by, it["id"]))
                action = changes["status"] if set(changes) == {"status"} else "edit"
                self._audit(c, "atom", it["id"], action, {k: row[k] for k in changes},
                            {**changes, "bulk": True})
                changed.append(it["id"])
        return changed

    def merge_atoms(self, duplicate_id, into_id, audit_reason="duplicate"):
        """Fold a duplicate into another atom: its quotes move over, it leaves the review queue (BR-03)."""
        if duplicate_id == into_id:
            raise StoreError("cannot merge an atom into itself")
        with self._write() as c:
            dup, target = self._atom_row(c, duplicate_id), self._atom_row(c, into_id)
            if dup["project_id"] != target["project_id"]:
                raise StoreError("atoms belong to different projects")
            if target["status"] == "merged":
                into_id = target["merged_into"]
            have = {(r["source_id"], r["quote"]) for r in c.execute(
                "SELECT source_id, quote FROM evidence WHERE atom_id = ?", (into_id,))}
            for r in c.execute("SELECT * FROM evidence WHERE atom_id = ?", (duplicate_id,)).fetchall():
                if (r["source_id"], r["quote"]) in have:
                    c.execute("DELETE FROM evidence WHERE id = ?", (r["id"],))
                else:
                    c.execute("UPDATE evidence SET atom_id = ? WHERE id = ?", (into_id, r["id"]))
            now, by = self._stamp()
            c.execute("UPDATE atoms SET status = 'merged', merged_into = ?, updated_at = ?, updated_by = ? WHERE id = ?",
                      (into_id, now, by, duplicate_id))
            self._audit(c, "atom", duplicate_id, "merge", {"status": dup["status"]},
                        {"merged_into": into_id, "reason": audit_reason})

    def delete_atoms(self, project_id, ids):
        """Delete atoms (soft: undo restores them). Open conflicts they're part of close, and reopen on undo."""
        if not isinstance(ids, list) or not ids:
            raise StoreError("nothing to delete")
        with self._write() as c:
            now, by = self._stamp()
            done = []
            for aid in ids:
                row = c.execute("SELECT project_id, deleted_at FROM atoms WHERE id = ?", (aid,)).fetchone()
                if row is None or row["project_id"] != project_id or row["deleted_at"]:
                    continue
                c.execute("UPDATE atoms SET deleted_at = ?, updated_at = ?, updated_by = ? WHERE id = ?", (now, now, by, aid))
                c.execute("UPDATE conflicts SET status = 'resolved', resolution = 'deleted', resolved_at = ?, resolved_by = ? "
                          "WHERE (atom_a = ? OR atom_b = ?) AND status != 'resolved'", (now, by, aid, aid))
                self._audit(c, "atom", aid, "delete")
                done.append(aid)
        return done

    def restore_atoms(self, project_id, ids):
        with self._write() as c:
            now, by = self._stamp()
            done = []
            for aid in ids or []:
                row = c.execute("SELECT project_id, deleted_at FROM atoms WHERE id = ?", (aid,)).fetchone()
                if row is None or row["project_id"] != project_id or not row["deleted_at"]:
                    continue
                c.execute("UPDATE atoms SET deleted_at = NULL, updated_at = ?, updated_by = ? WHERE id = ?", (now, by, aid))
                done.append(aid)
                self._audit(c, "atom", aid, "restore")
            for aid in done:                                 # conflicts closed by the deletion come back
                c.execute("""UPDATE conflicts SET status = 'open', resolution = NULL, resolved_at = NULL, resolved_by = NULL
                             WHERE (atom_a = ? OR atom_b = ?) AND resolution = 'deleted'
                             AND atom_a IN (SELECT id FROM atoms WHERE deleted_at IS NULL)
                             AND atom_b IN (SELECT id FROM atoms WHERE deleted_at IS NULL)""", (aid, aid))
        return done

    def delete_pending_atoms_for_source(self, source_id):
        """Before re-extraction: drop atoms still pending that only this source supports
        (reviewed atoms are kept, so no review work is lost; spec FR-TR-04 AC2)."""
        with self._write() as c:
            ids = [r["id"] for r in c.execute(
                """SELECT a.id FROM atoms a WHERE a.status = 'pending'
                   AND EXISTS (SELECT 1 FROM evidence e WHERE e.atom_id = a.id AND e.source_id = ?)
                   AND NOT EXISTS (SELECT 1 FROM evidence e WHERE e.atom_id = a.id AND e.source_id != ?)""",
                (source_id, source_id))]
            for aid in ids:
                c.execute("DELETE FROM conflicts WHERE atom_a = ? OR atom_b = ?", (aid, aid))
                c.execute("DELETE FROM evidence WHERE atom_id = ?", (aid,))
                c.execute("DELETE FROM atoms WHERE id = ?", (aid,))
            if ids:
                self._audit(c, "source", source_id, "clear_pending_atoms", after={"count": len(ids)})
        return len(ids)

    def atom_stats(self, project_id):
        with self._conn() as c:
            counts = {r["status"]: r["n"] for r in c.execute(
                "SELECT status, COUNT(*) AS n FROM atoms WHERE project_id = ? AND deleted_at IS NULL GROUP BY status",
                (project_id,))}
            open_conflicts = c.execute("SELECT COUNT(*) FROM conflicts WHERE project_id = ? AND status = 'open'",
                                       (project_id,)).fetchone()[0]
        stats = {s: counts.get(s, 0) for s in ATOM_STATUSES}
        stats["total"] = sum(v for k, v in stats.items() if k != "merged")
        stats["open_conflicts"] = open_conflicts
        return stats

    # ── conflicts (D-06: keep one / merge / turn into a question; never blocks) ──
    def add_conflict(self, project_id, atom_a, atom_b, description):
        with self._write() as c:
            now, by = self._stamp()
            cid = str(uuid.uuid4())
            c.execute("INSERT INTO conflicts (id, project_id, atom_a, atom_b, description, status, created_at, created_by) "
                      "VALUES (?,?,?,?,?,'open',?,?)", (cid, project_id, atom_a, atom_b, description.strip(), now, by))
            self._audit(c, "conflict", cid, "create", after={"atoms": [atom_a, atom_b], "description": description})
        return cid

    def list_conflicts(self, project_id, include_resolved=False):
        q = "SELECT * FROM conflicts WHERE project_id = ?" + ("" if include_resolved else " AND status != 'resolved'")
        with self._conn() as c:
            rows = [dict(r) for r in c.execute(q + " ORDER BY created_at", (project_id,))]
        for r in rows:
            r["a"], r["b"] = self.get_atom(r["atom_a"]), self.get_atom(r["atom_b"])
        return rows

    def resolve_conflict(self, conflict_id, action, statement=None):
        if action not in CONFLICT_ACTIONS:
            raise StoreError(f"unknown resolution {action}")
        with self._conn() as c:
            conf = c.execute("SELECT * FROM conflicts WHERE id = ?", (conflict_id,)).fetchone()
        if conf is None:
            raise StoreError("conflict not found")
        conf = dict(conf)
        a, b = conf["atom_a"], conf["atom_b"]
        question_atom, status = None, "resolved"
        if action == "keep_a":
            self.update_atom(b, status="rejected")
        elif action == "keep_b":
            self.update_atom(a, status="rejected")
        elif action == "merge":
            if not (statement or "").strip():
                raise StoreError("merging needs the combined statement")
            self.update_atom(a, statement=statement)
            self.merge_atoms(b, a, audit_reason="conflict merge")
        else:  # question: ask the client; both stay flagged until it's answered (BR-17)
            atom_a = self.get_atom(a)
            text = (statement or "").strip() or f"Уточнить у заказчика: {conf['description']}"
            evidence = [{k: e[k] for k in ("source_id", "segment_idx", "start", "speaker", "quote")}
                        for e in atom_a["evidence"] + self.get_atom(b)["evidence"]]
            question_atom = self.add_atoms(atom_a["project_id"], [{"type": "question", "statement": text,
                                                                   "evidence": evidence}])[0]
            status = "awaiting_answer"
        with self._write() as c:
            now, by = self._stamp()
            c.execute("UPDATE conflicts SET status = ?, resolution = ?, question_atom = ?, resolved_at = ?, resolved_by = ? "
                      "WHERE id = ?", (status, action, question_atom, now, by, conflict_id))
            self._audit(c, "conflict", conflict_id, "resolve", {"status": "open"},
                        {"status": status, "resolution": action, "question_atom": question_atom})
        return {"status": status, "question_atom": question_atom}

    def answer_question(self, question_atom_id, answer, source=None, resolution=None, statement=None):
        """Record the client's answer to a question (PM-21). For a question raised by a conflict,
        `resolution` (keep_a / keep_b / merge + statement) settles the conflict explicitly; without it
        the conflict stays open. Accepting a question no longer closes anything by itself."""
        answer = (answer or "").strip()
        if not answer:
            raise StoreError("the answer must not be empty")
        with self._write() as c:
            before = self._atom_row(c, question_atom_id)
            if before["type"] != "question":
                raise StoreError("only questions can be answered")
            now, by = self._stamp()
            c.execute("UPDATE atoms SET q_state = 'answered', answer = ?, answer_source = ?, updated_at = ?, updated_by = ? "
                      "WHERE id = ?", (answer, (source or "").strip() or None, now, by, question_atom_id))
            self._audit(c, "atom", question_atom_id, "answer", {"q_state": before["q_state"], "answer": before["answer"]},
                        {"q_state": "answered", "answer": answer, "source": source})
            conf = c.execute("SELECT id FROM conflicts WHERE question_atom = ? AND status = 'awaiting_answer'",
                             (question_atom_id,)).fetchone()
        if conf and resolution:
            if resolution not in {"keep_a", "keep_b", "merge"}:
                raise StoreError("resolution must be keep_a, keep_b or merge")
            self.resolve_conflict(conf["id"], resolution, statement)
            with self._write() as c:            # keep the link to the question that settled it
                c.execute("UPDATE conflicts SET question_atom = ? WHERE id = ?", (question_atom_id, conf["id"]))
        return self.get_atom(question_atom_id)

    def add_ba_atom(self, project_id, type, statement, note=None, source_id=None, segment_idx=None):
        """A requirement the BA writes down themselves (PM-16). Evidence is the BA's own note, or a
        segment of a source when they point at one."""
        if type not in ATOM_TYPES:
            raise StoreError(f"unknown atom type {type}")
        statement = (statement or "").strip()
        if not statement:
            raise StoreError("the statement must not be empty")
        self.get_project(project_id)
        with self._write() as c:
            now, by = self._stamp()
            aid = str(uuid.uuid4())
            c.execute("INSERT INTO atoms (id, project_id, type, statement, original_statement, status, model, origin, "
                      "created_at, created_by, updated_at, updated_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                      (aid, project_id, type, statement, statement, "accepted", None, "ba", now, by, now, by))
            if source_id:
                seg = c.execute("SELECT * FROM segments WHERE source_id = ? AND idx = ?", (source_id, segment_idx)).fetchone()
                if seg is None:
                    raise StoreError("segment not found")
                c.execute("INSERT INTO evidence VALUES (?,?,?,?,?,?,?,?)",
                          (str(uuid.uuid4()), aid, source_id, segment_idx, seg["start"], seg["speaker"], seg["text"], now))
            self._audit(c, "atom", aid, "create", after={"type": type, "statement": statement, "origin": "ba",
                                                         "note": (note or "").strip() or None})
        return self.get_atom(aid)

    # ── action items (PM-19): kept, never part of the FRD ─────────────────────
    _ACTION_FIELDS = ("id", "project_id", "source_id", "text", "owner", "due", "status", "quote", "segment_idx", "start",
                      "created_at", "updated_at")

    def add_actions(self, project_id, source_id, items):
        with self._write() as c:
            now, by = self._stamp()
            for it in items:
                text = (it.get("text") or "").strip()
                if not text:
                    continue
                c.execute("INSERT INTO action_items (id, project_id, source_id, text, owner, due, status, quote, segment_idx, "
                          "start, created_at, created_by, updated_at, updated_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          (str(uuid.uuid4()), project_id, source_id, text, (it.get("owner") or "").strip() or None,
                           (it.get("due") or "").strip() or None, "open", it.get("quote"), it.get("segment_idx"),
                           it.get("start"), now, by, now, by))

    def clear_actions_for_source(self, source_id):
        with self._write() as c:
            c.execute("DELETE FROM action_items WHERE source_id = ? AND status = 'open'", (source_id,))

    def list_actions(self, project_id):
        with self._conn() as c:
            rows = c.execute("""SELECT a.*, s.title AS source_title FROM action_items a LEFT JOIN sources s ON s.id = a.source_id
                                WHERE a.project_id = ? AND a.deleted_at IS NULL ORDER BY a.status, a.created_at""",
                             (project_id,)).fetchall()
        return [{**{k: r[k] for k in self._ACTION_FIELDS}, "source_title": r["source_title"]} for r in rows]

    def update_action(self, action_id, **changes):
        allowed = {"text", "owner", "due", "status"}
        if not changes or set(changes) - allowed:
            raise StoreError(f"cannot change {sorted(set(changes) - allowed) or 'nothing'}")
        if "status" in changes and changes["status"] not in ACTION_STATUSES:
            raise StoreError("status must be open or done")
        with self._write() as c:
            now, by = self._stamp()
            sets = ", ".join(f"{k} = ?" for k in changes)
            if not c.execute(f"UPDATE action_items SET {sets}, updated_at = ?, updated_by = ? WHERE id = ?",
                             (*changes.values(), now, by, action_id)).rowcount:
                raise StoreError("action item not found")
            self._audit(c, "action", action_id, "edit", after=changes)

    def delete_action(self, action_id):
        with self._write() as c:
            now, by = self._stamp()
            c.execute("UPDATE action_items SET deleted_at = ?, updated_at = ?, updated_by = ? WHERE id = ?", (now, now, by, action_id))
            self._audit(c, "action", action_id, "delete")

    # ── FRD documents (spec increment 3, FR-DOC-*) ────────────────────────────
    LEGACY_TEMPLATES = {"neutral": "export-standard", "gost": "export-gost"}   # 2.6.0 values → export skills
    FREE_SECTIONS = ("purpose", "context", "functional", "nfr", "out_of_scope", "questions")

    def document(self, project_id, create=True):
        """The project's FRD (one per project, spec A-11), created on first use."""
        project = self.get_project(project_id)
        with self._conn() as c:
            row = c.execute("SELECT * FROM documents WHERE project_id = ? AND deleted_at IS NULL ORDER BY created_at LIMIT 1",
                            (project_id,)).fetchone()
        if row is not None or not create:
            return self._doc_row(row) if row else None
        with self._write() as c:
            now, by = self._stamp()
            did = str(uuid.uuid4())
            c.execute("INSERT INTO documents (id, project_id, title, template, created_at, created_by, updated_at, updated_by) "
                      "VALUES (?,?,?,?,?,?,?,?)", (did, project_id, f"SRS — {project['name']}", "export-standard", now, by, now, by))
            self._audit(c, "document", did, "create")
        return self.get_document(did)

    def documents(self, project_id):
        """All documents of a project (BRD, SRS, Vision & Scope, …), oldest first; the first is the primary one."""
        self.get_project(project_id)
        with self._conn() as c:
            return [self._doc_row(r) for r in c.execute(
                "SELECT * FROM documents WHERE project_id = ? AND deleted_at IS NULL ORDER BY created_at, rowid", (project_id,))]

    def create_document(self, project_id, kind, title):
        """Another document of a given type (its document skill)."""
        self.get_project(project_id)
        title = (title or "").strip()[:200]
        if not title:
            raise StoreError("the title must not be empty")
        with self._write() as c:
            now, by = self._stamp()
            did = str(uuid.uuid4())
            c.execute("INSERT INTO documents (id, project_id, title, template, kind, created_at, created_by, updated_at, updated_by) "
                      "VALUES (?,?,?,?,?,?,?,?,?)", (did, project_id, title, "export-standard", kind, now, by, now, by))
            self._audit(c, "document", did, "create", after={"kind": kind, "title": title})
        return self.get_document(did)

    def delete_document(self, document_id):
        doc = self.get_document(document_id)
        if len(self.documents(doc["project_id"])) <= 1:
            raise StoreError("a project keeps at least one document")
        with self._write() as c:
            now, by = self._stamp()
            c.execute("UPDATE documents SET deleted_at = ?, updated_at = ?, updated_by = ? WHERE id = ?", (now, now, by, document_id))
            self._audit(c, "document", document_id, "delete")

    def get_document(self, document_id):
        with self._conn() as c:
            row = c.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
        if row is None:
            raise StoreError("document not found")
        return self._doc_row(row)

    def _doc_row(self, row):
        d = dict(row)
        d["template"] = self.LEGACY_TEMPLATES.get(d["template"], d["template"])
        return d

    def update_document(self, document_id, **changes):
        if set(changes) - {"title", "template", "kind", "decompose"}:
            raise StoreError("only the title, template, type and decomposition can be changed")
        if "decompose" in changes and changes["decompose"] is not None:
            changes["decompose"] = int(bool(changes["decompose"]))
        if "template" in changes and not re.match(r"^[a-z0-9][a-z0-9-]{1,62}$", str(changes["template"])):
            raise StoreError("template must be the name of an export skill")
        if "title" in changes:
            changes["title"] = (changes["title"] or "").strip()[:200]
            if not changes["title"]:
                raise StoreError("the title must not be empty")
        before = self.get_document(document_id)
        with self._write() as c:
            now, by = self._stamp()
            sets = ", ".join(f"{k} = ?" for k in changes)
            c.execute(f"UPDATE documents SET {sets}, updated_at = ?, updated_by = ? WHERE id = ?",
                      (*changes.values(), now, by, document_id))
            self._audit(c, "document", document_id, "edit", {k: before[k] for k in changes}, changes)
        return self.get_document(document_id)

    def known_requirement_ids(self, project_id):
        """IDs already given to atoms ({atom_id: {prefix: "FR-3"}}); gives out nothing new, so it is safe for lists."""
        out = {}
        with self._conn() as c:
            for r in c.execute("SELECT atom_id, prefix, number FROM requirement_ids WHERE project_id = ?", (project_id,)):
                out.setdefault(r["atom_id"], {})[r["prefix"]] = f"{r['prefix']}-{r['number']}"
        return out

    def requirement_ids(self, project_id, atoms):
        """Stable IDs (FR-n, NFR-n, Q-n) per atom and type; numbers are never reused (BR-14)."""
        prefix_of = ATOM_PREFIX
        out = {}
        with self._write() as c:
            for atom in atoms:
                prefix = prefix_of[atom["type"]]
                row = c.execute("SELECT number FROM requirement_ids WHERE atom_id = ? AND prefix = ?",
                                (atom["id"], prefix)).fetchone()
                if row is None:
                    n = c.execute("SELECT COALESCE(MAX(number), 0) + 1 FROM requirement_ids "
                                  "WHERE project_id = ? AND prefix = ?", (project_id, prefix)).fetchone()[0]
                    c.execute("INSERT INTO requirement_ids VALUES (?,?,?,?,?)",
                              (project_id, prefix, n, atom["id"], self._clock()))
                else:
                    n = row["number"]
                out[atom["id"]] = f"{prefix}-{n}"
        return out

    def add_version(self, document_id, content, snapshot, atom_count, provider=None, model=None, mode=None):
        with self._write() as c:
            n = c.execute("SELECT COALESCE(MAX(number), 0) + 1 FROM doc_versions WHERE document_id = ?",
                          (document_id,)).fetchone()[0]
            now, by = self._stamp()
            vid = str(uuid.uuid4())
            c.execute("INSERT INTO doc_versions (id, document_id, number, content_json, snapshot_json, atom_count, provider, "
                      "model, mode, created_at, created_by) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                      (vid, document_id, n, json.dumps(content, ensure_ascii=False),
                       json.dumps(snapshot, ensure_ascii=False), atom_count, provider, model, mode, now, by))
            self._audit(c, "document", document_id, "build", after={"version": n, "atoms": atom_count, "mode": mode})
        return n

    def set_version_status(self, document_id, number, status):
        """Sign-off (PM-34): draft → review → approved. Approving makes this version the baseline."""
        if status not in DOC_STATUSES:
            raise StoreError(f"status must be one of {sorted(DOC_STATUSES)}")
        with self._write() as c:
            row = c.execute("SELECT status FROM doc_versions WHERE document_id = ? AND number = ?",
                            (document_id, int(number))).fetchone()
            if row is None:
                raise StoreError("version not found")
            now, by = self._stamp()
            c.execute("UPDATE doc_versions SET status = ?, status_at = ?, status_by = ? WHERE document_id = ? AND number = ?",
                      (status, now, by, document_id, int(number)))
            self._audit(c, "document", document_id, "status", {"version": int(number), "status": row["status"]},
                        {"version": int(number), "status": status})

    def baseline(self, document_id):
        """The latest approved version number, or None."""
        with self._conn() as c:
            r = c.execute("SELECT MAX(number) FROM doc_versions WHERE document_id = ? AND status = 'approved'",
                          (document_id,)).fetchone()
        return r[0]

    def versions(self, document_id):
        with self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT number, atom_count, provider, model, mode, status, status_at, created_at, created_by FROM doc_versions "
                "WHERE document_id = ? ORDER BY number DESC", (document_id,))]

    def version(self, document_id, number=None):
        """A version with its content (the latest when number is None); None if never built."""
        q = "SELECT * FROM doc_versions WHERE document_id = ?"
        args = [document_id]
        if number is not None:
            q += " AND number = ?"
            args.append(int(number))
        with self._conn() as c:
            row = c.execute(q + " ORDER BY number DESC LIMIT 1", args).fetchone()
        if row is None:
            return None
        v = dict(row)
        v["content"] = json.loads(v.pop("content_json"))
        v["snapshot"] = json.loads(v.pop("snapshot_json"))
        return v

    # pinned free-text blocks (FR-DOC-04, BR-07): the BA's own text, kept verbatim
    def free_blocks(self, document_id):
        with self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT id, section, text, position, updated_at, updated_by FROM free_blocks "
                "WHERE document_id = ? AND deleted_at IS NULL ORDER BY section, position", (document_id,))]

    def add_free_block(self, document_id, section, text):
        self.get_document(document_id)
        if not re.match(r"^[a-z][a-z0-9_]{0,40}$", str(section or "")):
            raise StoreError("unknown section")
        text = (text or "").strip()
        if not text:
            raise StoreError("the text must not be empty")
        with self._write() as c:
            pos = c.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM free_blocks WHERE document_id = ? AND section = ?",
                            (document_id, section)).fetchone()[0]
            now, by = self._stamp()
            bid = str(uuid.uuid4())
            c.execute("INSERT INTO free_blocks VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (bid, document_id, section, text, pos, None, now, by, now, by))
            self._audit(c, "free_block", bid, "create", after={"section": section, "text": text})
        return bid

    def update_free_block(self, block_id, text):
        text = (text or "").strip()
        if not text:
            raise StoreError("the text must not be empty")
        with self._write() as c:
            row = c.execute("SELECT text FROM free_blocks WHERE id = ? AND deleted_at IS NULL", (block_id,)).fetchone()
            if row is None:
                raise StoreError("block not found")
            now, by = self._stamp()
            c.execute("UPDATE free_blocks SET text = ?, updated_at = ?, updated_by = ? WHERE id = ?", (text, now, by, block_id))
            self._audit(c, "free_block", block_id, "edit", {"text": row["text"]}, {"text": text})

    def delete_free_block(self, block_id, restore=False):
        with self._write() as c:
            now, by = self._stamp()
            n = c.execute("UPDATE free_blocks SET deleted_at = ?, updated_at = ?, updated_by = ? WHERE id = ?",
                          (None if restore else now, now, by, block_id)).rowcount
            if not n:
                raise StoreError("block not found")
            self._audit(c, "free_block", block_id, "restore" if restore else "delete")

    # skills chosen for one project, overriding the global choice (FR-SET-04, D-13)
    def project_skills(self, project_id):
        with self._conn() as c:
            return {r["stage"]: r["skill"] for r in c.execute(
                "SELECT stage, skill FROM project_skills WHERE project_id = ?", (project_id,))}

    def set_project_skill(self, project_id, stage, skill):
        """skill None removes the override (the project follows the global choice again)."""
        self.get_project(project_id)
        before = self.project_skills(project_id).get(stage)
        with self._write() as c:
            if skill:
                now, by = self._stamp()
                c.execute("INSERT OR REPLACE INTO project_skills VALUES (?,?,?,?,?)", (project_id, stage, skill, now, by))
            else:
                c.execute("DELETE FROM project_skills WHERE project_id = ? AND stage = ?", (project_id, stage))
            self._audit(c, "project", project_id, "skill", {"stage": stage, "skill": before}, {"stage": stage, "skill": skill})

    # quality findings the BA chose to ignore (FR-DOC-06 AC2: dismiss)
    def dismiss_finding(self, document_id, atom_id, rule):
        atom = self.get_atom(atom_id)
        with self._write() as c:
            now, by = self._stamp()
            c.execute("INSERT OR REPLACE INTO quality_dismissals VALUES (?,?,?,?,?,?)",
                      (document_id, atom_id, rule, atom["statement"], now, by))
            self._audit(c, "atom", atom_id, "dismiss_finding", after={"rule": rule})

    def dismissed(self, document_id):
        """{(atom_id, rule): statement} — a dismissal lapses when the statement changes."""
        with self._conn() as c:
            return {(r["atom_id"], r["rule"]): r["statement"] for r in c.execute(
                "SELECT atom_id, rule, statement FROM quality_dismissals WHERE document_id = ?", (document_id,))}

    # ── backlog (spec increment 4, FR-DEC-*) ─────────────────────────────────
    _BACKLOG_JSON = ("acceptance", "refs", "invest")

    def _backlog_row(self, r):
        d = dict(r)
        for k in self._BACKLOG_JSON:
            d[k] = json.loads(d.pop(f"{k}_json") or "[]")
        for k in ("included", "generated", "pinned"):
            d[k] = bool(d[k])
        return d

    def backlog(self, project_id):
        """Live items in tree order (parents before children, by position)."""
        with self._conn() as c:
            rows = [self._backlog_row(r) for r in c.execute(
                "SELECT * FROM backlog_items WHERE project_id = ? AND deleted_at IS NULL ORDER BY position", (project_id,))]
        children = {}
        for r in rows:
            children.setdefault(r["parent_id"], []).append(r)
        out = []

        def walk(parent):
            for item in children.get(parent, []):
                out.append(item)
                walk(item["id"])
        walk(None)
        return out

    def get_backlog_item(self, item_id):
        with self._conn() as c:
            r = c.execute("SELECT * FROM backlog_items WHERE id = ? AND deleted_at IS NULL", (item_id,)).fetchone()
        if r is None:
            raise StoreError("backlog item not found")
        return self._backlog_row(r)

    def _insert_backlog(self, c, project_id, item, parent_id, position, frd_version):
        if item["kind"] not in BACKLOG_KINDS:
            raise StoreError(f"unknown backlog kind {item['kind']}")
        now, by = self._stamp()
        iid = item.get("id") or str(uuid.uuid4())
        if item.get("priority") not in (None, "") and item["priority"] not in PRIORITIES:
            raise StoreError(f"priority must be one of {sorted(PRIORITIES)}")
        c.execute("INSERT INTO backlog_items (id, project_id, parent_id, kind, title, body, goal, acceptance_json, "
                  "refs_json, invest_json, included, generated, pinned, position, frd_version, created_at, created_by, "
                  "updated_at, updated_by, priority) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (iid, project_id, parent_id, item["kind"], item["title"].strip(), item.get("body", "").strip(),
                   item.get("goal", "").strip(), json.dumps(item.get("acceptance") or [], ensure_ascii=False),
                   json.dumps(item.get("refs") or [], ensure_ascii=False),
                   json.dumps(item.get("invest") or [], ensure_ascii=False), int(item.get("included", True)),
                   int(item.get("generated", False)), int(item.get("pinned", False)), position, frd_version,
                   now, by, now, by, item.get("priority") or None))
        return iid

    @staticmethod
    def _match_backlog(old, tree):
        """Pair each new item with the old item it replaces, so a rebuild keeps ids and Jira links.

        Stories and NFRs match by their first FRD reference, epics by title or by where most of
        their stories came from, sub-tasks by (matched parent, title). Returns new-item-id → old item.
        """
        def first_ref(i):
            refs = i.get("refs") or []
            return refs[0]["id"] if refs else None

        by_ref, used, match = {}, set(), {}
        for o in old:
            if o["kind"] in ("story", "nfr") and first_ref(o):
                cur = by_ref.get((o["kind"], first_ref(o)))
                if cur is None or (o.get("jira_key") and not cur.get("jira_key")):
                    by_ref[(o["kind"], first_ref(o))] = o
        for epic in tree:
            for it in [epic] + (epic.get("children") or []):
                if it["kind"] in ("story", "nfr"):
                    o = by_ref.get((it["kind"], first_ref(it)))
                    if o and o["id"] not in used:
                        match[id(it)] = o
                        used.add(o["id"])
        epics_by_title = {}
        for o in old:
            if o["kind"] == "epic":
                epics_by_title.setdefault(o["title"].strip().lower(), o)
        for epic in tree:
            if epic["kind"] != "epic":
                continue
            o = epics_by_title.get(epic["title"].strip().lower())
            if not o or o["id"] in used:
                parents = [match[id(c)]["parent_id"] for c in epic.get("children") or [] if id(c) in match]
                parents = [x for x in parents if x and x not in used]
                o = next((e for e in old if e["kind"] == "epic" and parents and e["id"] == max(set(parents), key=parents.count)), None)
            if o and o["id"] not in used:
                match[id(epic)] = o
                used.add(o["id"])
        subs = {(o["parent_id"], o["title"].strip().lower()): o for o in old if o["kind"] == "subtask"}
        for epic in tree:
            for story in epic.get("children") or []:
                parent = match.get(id(story))
                for sub in story.get("children") or []:
                    o = parent and subs.get((parent["id"], sub["title"].strip().lower()))
                    if o and o["id"] not in used:
                        match[id(sub)] = o
                        used.add(o["id"])
        return match

    def replace_backlog(self, project_id, tree, frd_version, sources=None):
        """Regenerate from a new tree (FR-DEC-05). Pinned (BA-edited) items stay as they are; a new
        item that replaces an old one keeps its id, its Jira link and the BA's "in export" choice,
        so the next push updates the issue instead of creating a duplicate. Old items that were in
        Jira and have no successor are reported as orphans.
        tree = [{kind, title, …, children: [...]}]."""
        self.get_project(project_id)
        old = self.backlog(project_id)
        match = self._match_backlog(old, tree)
        with self._write() as c:
            now, by = self._stamp()
            pinned = {o["id"] for o in old if o["pinned"]}
            c.execute("UPDATE backlog_items SET deleted_at = ?, updated_at = ?, updated_by = ? "
                      "WHERE project_id = ? AND deleted_at IS NULL AND pinned = 0", (now, now, by, project_id))
            start = (c.execute("SELECT COALESCE(MAX(position), 0) FROM backlog_items WHERE project_id = ? "
                               "AND deleted_at IS NULL", (project_id,)).fetchone()[0] or 0) + 1
            counter = [start]
            kept, idmap = [], {}

            def revive(o, item, parent):
                c.execute("UPDATE backlog_items SET deleted_at = NULL, parent_id = ?, kind = ?, title = ?, body = ?, "
                          "goal = ?, acceptance_json = ?, refs_json = ?, invest_json = ?, generated = ?, position = ?, "
                          "frd_version = ?, priority = COALESCE(?, priority), updated_at = ?, updated_by = ? WHERE id = ?",
                          (parent, item["kind"], item["title"].strip(), item.get("body", "").strip(),
                           item.get("goal", "").strip(), json.dumps(item.get("acceptance") or [], ensure_ascii=False),
                           json.dumps(item.get("refs") or [], ensure_ascii=False),
                           json.dumps(item.get("invest") or [], ensure_ascii=False), int(item.get("generated", False)),
                           counter[0], frd_version, item.get("priority") or None, now, by, o["id"]))
                return o["id"]

            def add(items, parent):
                for item in items:
                    o = match.get(id(item))
                    if item.get("invest"):          # NFR "move into" links point at new story ids
                        item = {**item, "invest": [{**f, "move_to": [idmap.get(x, x) for x in f.get("move_to") or []]}
                                                   if f.get("move_to") else f for f in item["invest"]]}
                    if o and o["pinned"]:
                        # The BA's edited version stands in for the regenerated one.
                        if parent and o["parent_id"] != parent:
                            c.execute("UPDATE backlog_items SET parent_id = ? WHERE id = ?", (parent, o["id"]))
                        if item.get("id"):
                            idmap[item["id"]] = o["id"]
                        add(item.get("children") or [], o["id"])
                        continue
                    if o:
                        iid = revive(o, item, parent)
                        kept.append(o["id"])
                    else:
                        iid = self._insert_backlog(c, project_id, item, parent, counter[0], frd_version)
                    if item.get("id"):
                        idmap[item["id"]] = iid
                    counter[0] += 1
                    add(item.get("children") or [], iid)
            add(tree, None)
            # A kept (pinned) item whose parent was dropped moves to the top level.
            c.execute("UPDATE backlog_items SET parent_id = NULL WHERE project_id = ? AND deleted_at IS NULL AND "
                      "parent_id IS NOT NULL AND parent_id NOT IN (SELECT id FROM backlog_items WHERE deleted_at IS NULL)",
                      (project_id,))
            alive = set(kept) | pinned
            orphans = [{"key": o["jira_key"], "title": o["title"]} for o in old
                       if o.get("jira_key") and o["id"] not in alive]
            self._audit(c, "project", project_id, "backlog_build",
                        after={"frd_version": frd_version, "kept_pinned": len(pinned), "matched": len(kept),
                               "orphaned_jira": [x["key"] for x in orphans], "sources": sources})
        return {"matched": len(kept), "orphans": orphans}

    def jira_orphans(self, project_id):
        """Issues this project created in Jira whose backlog item no longer exists (PM-24)."""
        with self._conn() as c:
            live = {r[0] for r in c.execute("SELECT jira_key FROM backlog_items WHERE project_id = ? AND "
                                            "deleted_at IS NULL AND jira_key IS NOT NULL", (project_id,))}
            rows = c.execute("SELECT id, kind, title, jira_key, jira_url, deleted_at FROM backlog_items WHERE project_id = ? "
                             "AND deleted_at IS NOT NULL AND jira_key IS NOT NULL ORDER BY deleted_at DESC",
                             (project_id,)).fetchall()
        out, seen = [], set()
        for r in rows:
            if r["jira_key"] in live or r["jira_key"] in seen:
                continue
            seen.add(r["jira_key"])
            out.append({"item_id": r["id"], "kind": r["kind"], "title": r["title"], "key": r["jira_key"],
                        "url": r["jira_url"], "removed_at": r["deleted_at"]})
        return out

    def forget_jira_orphan(self, project_id, key):
        """The BA dealt with it in Jira: stop listing it."""
        with self._write() as c:
            c.execute("UPDATE backlog_items SET jira_key = NULL WHERE project_id = ? AND deleted_at IS NOT NULL "
                      "AND jira_key = ?", (project_id, key))
            self._audit(c, "project", project_id, "jira_orphan_forget", after={"key": key})

    def add_backlog_item(self, project_id, item, parent_id=None, after_id=None):
        """A BA-created item (pinned: regeneration never removes it)."""
        if parent_id:
            self.get_backlog_item(parent_id)
        with self._write() as c:
            if after_id:
                pos = c.execute("SELECT position FROM backlog_items WHERE id = ?", (after_id,)).fetchone()
                pos = (pos[0] + 0.5) if pos else None
            else:
                pos = None
            if pos is None:
                pos = (c.execute("SELECT COALESCE(MAX(position), 0) FROM backlog_items WHERE project_id = ?",
                                 (project_id,)).fetchone()[0] or 0) + 1
            iid = self._insert_backlog(c, project_id, {**item, "pinned": True}, parent_id, pos, None)
            self._audit(c, "backlog", iid, "create", after={"kind": item["kind"], "title": item["title"]})
        return self.get_backlog_item(iid)

    def update_backlog_item(self, item_id, pin=True, **changes):
        """Edit an item. BA edits pin it (FR-DEC-05); toggling 'included' alone does not."""
        allowed = {"title", "body", "goal", "acceptance", "refs", "invest", "included", "kind", "parent_id", "position",
                   "priority"}
        if not changes or set(changes) - allowed:
            raise StoreError(f"cannot change {sorted(set(changes) - allowed) or 'nothing'}")
        if "title" in changes and not str(changes["title"] or "").strip():
            raise StoreError("the title must not be empty")
        if "kind" in changes and changes["kind"] not in BACKLOG_KINDS:
            raise StoreError("unknown kind")
        if "priority" in changes:
            changes["priority"] = changes["priority"] or None
            if changes["priority"] and changes["priority"] not in PRIORITIES:
                raise StoreError(f"priority must be one of {sorted(PRIORITIES)}")
        if "acceptance" in changes:
            ac = changes["acceptance"]
            if not isinstance(ac, list) or any(not isinstance(x, dict) for x in ac):
                raise StoreError("acceptance must be a list of {given, when, then}")
            changes["acceptance"] = [{k: str(x.get(k) or "").strip() for k in ("given", "when", "then")} for x in ac
                                     if any(str(x.get(k) or "").strip() for k in ("given", "when", "then"))]
        before = self.get_backlog_item(item_id)
        cols = {}
        for k, v in changes.items():
            if k in self._BACKLOG_JSON:
                cols[f"{k}_json"] = json.dumps(v, ensure_ascii=False)
            elif k == "included":
                cols[k] = int(bool(v))
            else:
                cols[k] = v.strip() if isinstance(v, str) else v
        if pin and set(changes) - {"included", "invest", "position", "priority"}:
            cols["pinned"] = 1
        with self._write() as c:
            now, by = self._stamp()
            sets = ", ".join(f"{k} = ?" for k in cols)
            c.execute(f"UPDATE backlog_items SET {sets}, updated_at = ?, updated_by = ? WHERE id = ?",
                      (*cols.values(), now, by, item_id))
            self._audit(c, "backlog", item_id, "edit", {k: before.get(k) for k in changes}, changes)
        return self.get_backlog_item(item_id)

    def set_backlog_included(self, project_id, ids, included):
        """Tick / untick several items (a parent's children follow it, FR-DEC-02 AC2)."""
        items = {i["id"]: i for i in self.backlog(project_id)}
        targets, stack = set(), [i for i in ids if i in items]
        while stack:
            iid = stack.pop()
            if iid in targets:
                continue
            targets.add(iid)
            if not included:                         # unticking a parent unticks its children
                stack += [i["id"] for i in items.values() if i["parent_id"] == iid]
        if included:                                 # ticking a child ticks its parents, so it has a home
            for iid in list(targets):
                p = items[iid]["parent_id"]
                while p and p in items:
                    targets.add(p)
                    p = items[p]["parent_id"]
        with self._write() as c:
            now, by = self._stamp()
            for iid in targets:
                c.execute("UPDATE backlog_items SET included = ?, updated_at = ?, updated_by = ? WHERE id = ?",
                          (int(bool(included)), now, by, iid))
            self._audit(c, "project", project_id, "backlog_include", after={"ids": sorted(targets), "included": included})
        return sorted(targets)

    # Jira target per project and what was pushed (FR-JIRA-01/04)
    def jira_target(self, project_id):
        with self._conn() as c:
            r = c.execute("SELECT * FROM jira_targets WHERE project_id = ?", (project_id,)).fetchone()
        if r is None:
            return None
        d = dict(r)
        d["types"] = json.loads(d.pop("types_json") or "{}")
        return d

    def set_jira_target(self, project_id, cloud_id, site_url, project_key, project_name=None, types=None):
        self.get_project(project_id)
        if not cloud_id or not project_key:
            raise StoreError("choose a Jira site and project")
        with self._write() as c:
            now, by = self._stamp()
            c.execute("INSERT OR REPLACE INTO jira_targets VALUES (?,?,?,?,?,?,?,?)",
                      (project_id, cloud_id, site_url or "", project_key, project_name,
                       json.dumps(types or {}, ensure_ascii=False), now, by))
            self._audit(c, "project", project_id, "jira_target", after={"site": site_url, "project": project_key})
        return self.jira_target(project_id)

    def mark_pushed(self, item_id, key, url, fingerprint, remote_updated=None):
        with self._write() as c:
            now, by = self._stamp()
            c.execute("UPDATE backlog_items SET jira_key = ?, jira_url = ?, jira_hash = ?, jira_pushed_at = ?, "
                      "jira_remote_updated = ?, updated_at = updated_at WHERE id = ?",
                      (key, url, fingerprint, now, remote_updated, item_id))
            self._audit(c, "backlog", item_id, "jira_push", after={"key": key})

    def delete_backlog_item(self, item_id, restore=False):
        """Soft-delete an item and its subtree (undo restores the same subtree)."""
        with self._conn() as c:
            row = c.execute("SELECT * FROM backlog_items WHERE id = ?", (item_id,)).fetchone()
        if row is None:
            raise StoreError("backlog item not found")
        with self._write() as c:
            now, by = self._stamp()
            stamp = row["deleted_at"] if restore else now
            ids, stack = [], [item_id]
            while stack:
                iid = stack.pop()
                ids.append(iid)
                stack += [r["id"] for r in c.execute("SELECT id FROM backlog_items WHERE parent_id = ? AND "
                                                     + ("deleted_at = ?" if restore else "deleted_at IS NULL"),
                                                     (iid, stamp) if restore else (iid,))]
            for iid in ids:
                c.execute("UPDATE backlog_items SET deleted_at = ?, updated_at = ?, updated_by = ? WHERE id = ?",
                          (None if restore else now, now, by, iid))
            self._audit(c, "backlog", item_id, "restore" if restore else "delete", after={"items": len(ids)})
        return ids

    # ── files ────────────────────────────────────────────────────────────────
    def attach_file(self, source, src_path, name, move=False):
        """Copy (or move) a file into the source's folder; returns the stored path."""
        dest_dir = self.source_dir(source)
        os.makedirs(dest_dir, exist_ok=True)
        dest = os.path.join(dest_dir, os.path.basename(name))
        (shutil.move if move else shutil.copy2)(src_path, dest)
        return dest
