"""SQLite persistence and provenance ledger."""

import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager

from .config import DB_PATH

_local = threading.local()


def db():
    conn = getattr(_local, "conn", None)
    if conn is not None and getattr(_local, "path", None) != DB_PATH:
        # DB_PATH was repointed (the test suite does this). close() only reaches the
        # calling thread, so worker threads notice here instead of writing
        # to the old file.
        conn.close()
        conn = None
    if conn is None:
        conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _local.conn = conn
        _local.path = DB_PATH
    return conn


def close():
    conn = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
        _local.conn = None


SCHEMA = """
CREATE TABLE IF NOT EXISTS dataset (
  id             TEXT PRIMARY KEY,
  project_id     TEXT,
  name           TEXT NOT NULL,
  path           TEXT,
  source         TEXT,
  sha256         TEXT,
  dictionary_sha TEXT,
  n_rows         INTEGER,
  n_cols         INTEGER,
  dictionary     TEXT,
  created_at     REAL,
  notes          TEXT
);

CREATE TABLE IF NOT EXISTS dataset_op (
  id            TEXT PRIMARY KEY,
  dataset_id    TEXT REFERENCES dataset(id) ON DELETE CASCADE,
  seq           INTEGER,
  op            TEXT,
  spec          TEXT,
  rows_before   INTEGER,
  rows_after    INTEGER,
  created_at    REAL
);

CREATE TABLE IF NOT EXISTS analysis_run (
  id             TEXT PRIMARY KEY,
  project_id     TEXT,
  dataset_id     TEXT,
  dataset_sha    TEXT,
  dictionary_sha TEXT,
  test_id        TEXT,
  spec           TEXT,
  assumptions    TEXT,
  result         TEXT,
  code_python    TEXT,
  code_r         TEXT,
  seed           INTEGER,
  alpha          REAL,
  ci_level       REAL,
  versions       TEXT,
  status         TEXT,
  error          TEXT,
  duration_ms    INTEGER,
  created_at     REAL,
  note           TEXT
);

CREATE TABLE IF NOT EXISTS figure (
  id            TEXT PRIMARY KEY,
  project_id    TEXT,
  run_id        TEXT,
  plot_id       TEXT,
  spec          TEXT,
  path          TEXT,
  created_at    REAL
);

CREATE TABLE IF NOT EXISTS project (
  id            TEXT PRIMARY KEY,
  name          TEXT NOT NULL,
  kind          TEXT,
  question      TEXT,
  registered    TEXT,
  notes         TEXT,
  status        TEXT,
  stage_notes   TEXT,
  created_at    REAL,
  updated_at    REAL
);

CREATE TABLE IF NOT EXISTS project_event (
  id            TEXT PRIMARY KEY,
  project_id    TEXT REFERENCES project(id) ON DELETE CASCADE,
  kind          TEXT,
  stage         TEXT,
  detail        TEXT,
  at            REAL
);
CREATE INDEX IF NOT EXISTS idx_event_project ON project_event(project_id);

CREATE TABLE IF NOT EXISTS record (
  id            TEXT PRIMARY KEY,
  project_id    TEXT REFERENCES project(id) ON DELETE CASCADE,
  source        TEXT,
  source_uid    TEXT,
  doi           TEXT,
  title         TEXT,
  abstract      TEXT,
  authors       TEXT,
  journal       TEXT,
  year          INTEGER,
  pub_types     TEXT,
  meta          TEXT,
  retracted     INTEGER DEFAULT 0,
  oa_url        TEXT,
  dedup_of      TEXT,
  fetched_at    REAL
);
CREATE INDEX IF NOT EXISTS idx_record_project ON record(project_id);
CREATE INDEX IF NOT EXISTS idx_record_doi ON record(doi);

CREATE TABLE IF NOT EXISTS screen (
  id            TEXT PRIMARY KEY,
  record_id     TEXT REFERENCES record(id) ON DELETE CASCADE,
  stage         TEXT,
  reviewer      TEXT,
  decision      TEXT,
  reason        TEXT,
  decided_at    REAL
);
CREATE INDEX IF NOT EXISTS idx_screen_record ON screen(record_id);

CREATE TABLE IF NOT EXISTS reviewer (
  id            TEXT PRIMARY KEY,
  name          TEXT NOT NULL,
  initials      TEXT,
  role          TEXT,
  colour        TEXT,
  created_at    REAL
);

CREATE TABLE IF NOT EXISTS resolution (
  id            TEXT PRIMARY KEY,
  record_id     TEXT REFERENCES record(id) ON DELETE CASCADE,
  stage         TEXT,
  decision      TEXT,
  rationale     TEXT,
  resolved_by   TEXT,
  resolved_at   REAL
);
CREATE INDEX IF NOT EXISTS idx_resolution_record ON resolution(record_id);

CREATE TABLE IF NOT EXISTS extraction (
  id            TEXT PRIMARY KEY,
  record_id     TEXT REFERENCES record(id) ON DELETE CASCADE,
  form_id       TEXT,
  payload       TEXT,
  updated_at    REAL
);

CREATE TABLE IF NOT EXISTS rob (
  id            TEXT PRIMARY KEY,
  record_id     TEXT REFERENCES record(id) ON DELETE CASCADE,
  instrument    TEXT,
  domains       TEXT,
  overall       TEXT,
  updated_at    REAL
);

CREATE TABLE IF NOT EXISTS job (
  id            TEXT PRIMARY KEY,
  kind          TEXT,
  title         TEXT,
  status        TEXT,
  spec          TEXT,
  result        TEXT,
  started_at    REAL,
  ended_at      REAL
);

CREATE TABLE IF NOT EXISTS preset (
  id            TEXT PRIMARY KEY,
  scope         TEXT,
  name          TEXT,
  spec          TEXT,
  created_at    REAL
);

CREATE TABLE IF NOT EXISTS harvest_query (
  id            TEXT PRIMARY KEY,
  project_id    TEXT,
  source        TEXT,
  query         TEXT,
  n_returned    INTEGER,
  ran_at        REAL
);
"""

# Columns added after initial releases. CREATE TABLE IF NOT EXISTS does not
# migrate an existing database, so add them explicitly and non-destructively.
_ADDED_COLUMNS = {
    "dataset": [("project_id", "TEXT"), ("dictionary_sha", "TEXT")],
    "analysis_run": [
        ("project_id", "TEXT"), ("dictionary_sha", "TEXT"),
        ("alpha", "REAL"), ("ci_level", "REAL"),
    ],
    "figure": [("project_id", "TEXT")],
    "project": [
        ("notes", "TEXT"), ("status", "TEXT"),
        ("stage_notes", "TEXT"), ("updated_at", "REAL"),
    ],
}

_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_dataset_project ON dataset(project_id);
CREATE INDEX IF NOT EXISTS idx_run_project ON analysis_run(project_id);
CREATE INDEX IF NOT EXISTS idx_figure_project ON figure(project_id);
DROP INDEX IF EXISTS ux_screen_record_stage_reviewer;
CREATE UNIQUE INDEX IF NOT EXISTS ux_screen_record_stage_reviewer
  ON screen(record_id, stage, reviewer);
CREATE UNIQUE INDEX IF NOT EXISTS ux_resolution_record_stage
  ON resolution(record_id, stage);
CREATE UNIQUE INDEX IF NOT EXISTS ux_extraction_record_form
  ON extraction(record_id, form_id);
CREATE UNIQUE INDEX IF NOT EXISTS ux_rob_record_instrument
  ON rob(record_id, instrument);
CREATE UNIQUE INDEX IF NOT EXISTS ux_dataset_op_seq
  ON dataset_op(dataset_id, seq);
"""


def _migrate_columns(conn):
    for table, cols in _ADDED_COLUMNS.items():
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if not have:
            continue
        for name, ctype in cols:
            if name not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ctype}")


def _dedupe_natural_keys(conn):
    """Keep the newest row for each logical key before unique indexes exist."""
    statements = [
        "DELETE FROM screen WHERE rowid NOT IN ("
        "SELECT s.rowid FROM screen s WHERE s.rowid=(SELECT s2.rowid FROM screen s2 "
        "WHERE s2.record_id=s.record_id AND s2.stage=s.stage "
        "AND COALESCE(s2.reviewer,'')=COALESCE(s.reviewer,'') "
        "ORDER BY COALESCE(s2.decided_at,0) DESC, s2.rowid DESC LIMIT 1))",
        "DELETE FROM resolution WHERE rowid NOT IN ("
        "SELECT r.rowid FROM resolution r WHERE r.rowid=(SELECT r2.rowid FROM resolution r2 "
        "WHERE r2.record_id=r.record_id AND r2.stage=r.stage "
        "ORDER BY COALESCE(r2.resolved_at,0) DESC, r2.rowid DESC LIMIT 1))",
        "DELETE FROM extraction WHERE rowid NOT IN ("
        "SELECT e.rowid FROM extraction e WHERE e.rowid=(SELECT e2.rowid FROM extraction e2 "
        "WHERE e2.record_id=e.record_id AND e2.form_id=e.form_id "
        "ORDER BY COALESCE(e2.updated_at,0) DESC, e2.rowid DESC LIMIT 1))",
        "DELETE FROM rob WHERE rowid NOT IN ("
        "SELECT r.rowid FROM rob r WHERE r.rowid=(SELECT r2.rowid FROM rob r2 "
        "WHERE r2.record_id=r.record_id AND r2.instrument=r.instrument "
        "ORDER BY COALESCE(r2.updated_at,0) DESC, r2.rowid DESC LIMIT 1))",
        "DELETE FROM dataset_op WHERE rowid NOT IN ("
        "SELECT d.rowid FROM dataset_op d WHERE d.rowid=(SELECT d2.rowid FROM dataset_op d2 "
        "WHERE d2.dataset_id=d.dataset_id AND d2.seq=d.seq "
        "ORDER BY COALESCE(d2.created_at,0) DESC, d2.rowid DESC LIMIT 1))",
    ]
    for sql in statements:
        try:
            conn.execute(sql)
        except sqlite3.OperationalError:
            pass


def init():
    conn = db()
    conn.executescript(SCHEMA)
    _migrate_columns(conn)
    _dedupe_natural_keys(conn)
    conn.executescript(_INDEXES)
    conn.commit()
    from . import migrations
    migrations.run(conn)


def json_value(value, default=None):
    """Decode a JSON database value without making every caller repeat guards."""
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list, int, float, bool)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def exec_(sql, args=()):
    conn = db()
    cur = conn.execute(sql, args)
    if not getattr(_local, "explicit_transaction", False):
        conn.commit()
    return cur


@contextmanager
def transaction():
    """Atomic multi-statement operation on the current thread's connection."""
    conn = db()
    if getattr(_local, "explicit_transaction", False):
        yield conn
        return
    _local.explicit_transaction = True
    try:
        conn.execute("BEGIN")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _local.explicit_transaction = False


def query(sql, args=()):
    return [dict(r) for r in db().execute(sql, args).fetchall()]


def one(sql, args=()):
    rows = query(sql, args)
    return rows[0] if rows else None


def new_id(prefix=""):
    return (prefix + uuid.uuid4().hex[:12]) if prefix else uuid.uuid4().hex[:12]


def insert(table, row):
    """Insert only. Updates/upserts are explicit so provenance rows are not replaced."""
    row = dict(row)
    row.setdefault("id", new_id())
    cols = ",".join(row)
    marks = ",".join("?" for _ in row)
    vals = [json.dumps(v) if isinstance(v, (dict, list)) else v for v in row.values()]
    exec_(f"INSERT INTO {table} ({cols}) VALUES ({marks})", vals)
    return row["id"]


def upsert(table, row, conflict_cols):
    """Explicit UPSERT for ordinary (non-expression) UNIQUE constraints."""
    row = dict(row)
    row.setdefault("id", new_id())
    cols = list(row)
    vals = [json.dumps(row[c]) if isinstance(row[c], (dict, list)) else row[c] for c in cols]
    updates = [c for c in cols if c not in set(conflict_cols) | {"id"}]
    action = ("DO UPDATE SET " + ",".join(f"{c}=excluded.{c}" for c in updates)
              if updates else "DO NOTHING")
    exec_(
        f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)}) "
        f"ON CONFLICT({','.join(conflict_cols)}) {action}", vals,
    )
    where = " AND ".join(f"{c} IS ?" for c in conflict_cols)
    found = one(f"SELECT id FROM {table} WHERE {where}", tuple(row[c] for c in conflict_cols))
    return found["id"] if found else row["id"]


def log_run(**kw):
    kw.setdefault("id", new_id())
    kw.setdefault("created_at", time.time())
    for k in ("spec", "assumptions", "result", "versions"):
        if isinstance(kw.get(k), (dict, list)):
            kw[k] = json.dumps(kw[k], default=str)
    insert("analysis_run", kw)
    return kw["id"]


def runs_on_dataset(sha, project_id=None):
    """Number of successful analyses on this exact dataset in this project."""
    r = one(
        "SELECT COUNT(*) c FROM analysis_run WHERE dataset_sha=? "
        "AND project_id IS ? AND status='ok'", (sha, project_id),
    )
    return r["c"] if r else 0
