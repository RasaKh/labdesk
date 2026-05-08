"""SQLite persistence and provenance ledger: connection handling and schema."""

import sqlite3
import threading

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