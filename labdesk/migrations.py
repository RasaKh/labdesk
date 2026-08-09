"""Numbered, transactional schema migrations.

The original application built its schema with CREATE TABLE IF NOT EXISTS and
then patched columns at startup.  That made a successful start indistinguishable
from a successful migration.  This module gives every post-v1 change an id,
checksum and completion record while leaving the legacy tables readable.
"""

from __future__ import annotations

import hashlib
import time


MIGRATIONS = (
    (1, "versioned artifacts, attempts and durable jobs", r"""
CREATE TABLE IF NOT EXISTS artifact (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  path TEXT NOT NULL UNIQUE,
  sha256 TEXT NOT NULL,
  size_bytes INTEGER NOT NULL,
  media_type TEXT,
  state TEXT NOT NULL DEFAULT 'ready',
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS dataset_version (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  dataset_id TEXT NOT NULL REFERENCES dataset(id) ON DELETE CASCADE,
  parent_id TEXT REFERENCES dataset_version(id),
  artifact_id TEXT NOT NULL REFERENCES artifact(id),
  storage_format TEXT NOT NULL,
  schema_json TEXT NOT NULL,
  semantic_sha TEXT NOT NULL,
  hash_version INTEGER NOT NULL DEFAULT 1,
  n_rows INTEGER NOT NULL,
  n_cols INTEGER NOT NULL,
  transform_spec TEXT,
  created_at REAL NOT NULL,
  UNIQUE(project_id, id),
  UNIQUE(dataset_id, semantic_sha, id)
);
CREATE INDEX IF NOT EXISTS idx_dataset_version_dataset
  ON dataset_version(project_id, dataset_id, created_at);

CREATE TABLE IF NOT EXISTS dictionary_revision (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  dataset_version_id TEXT NOT NULL REFERENCES dataset_version(id) ON DELETE CASCADE,
  parent_id TEXT REFERENCES dictionary_revision(id),
  payload TEXT NOT NULL,
  semantic_sha TEXT NOT NULL,
  reviewed INTEGER NOT NULL DEFAULT 0,
  revision INTEGER NOT NULL,
  created_at REAL NOT NULL,
  UNIQUE(dataset_version_id, revision)
);
CREATE INDEX IF NOT EXISTS idx_dictionary_revision_version
  ON dictionary_revision(project_id, dataset_version_id, revision);

CREATE TABLE IF NOT EXISTS preflight_snapshot (
  token TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  dataset_version_id TEXT,
  dictionary_revision_id TEXT,
  request_sha TEXT NOT NULL,
  resolved_spec TEXT NOT NULL,
  result TEXT NOT NULL,
  expires_at REAL NOT NULL,
  consumed_at REAL
);

CREATE TABLE IF NOT EXISTS analysis_attempt (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  dataset_version_id TEXT,
  dictionary_revision_id TEXT,
  requested_spec TEXT NOT NULL,
  resolved_spec TEXT,
  request_sha TEXT NOT NULL,
  settings TEXT NOT NULL,
  method_id TEXT,
  method_version TEXT,
  registry_version TEXT,
  status TEXT NOT NULL,
  job_id TEXT,
  run_id TEXT,
  retry_of TEXT REFERENCES analysis_attempt(id),
  diagnostics TEXT,
  error TEXT,
  created_at REAL NOT NULL,
  started_at REAL,
  ended_at REAL,
  UNIQUE(project_id, id)
);
CREATE INDEX IF NOT EXISTS idx_attempt_project
  ON analysis_attempt(project_id, created_at DESC);

CREATE TABLE IF NOT EXISTS idempotency_key (
  project_id TEXT NOT NULL,
  operation TEXT NOT NULL,
  key TEXT NOT NULL,
  request_sha TEXT NOT NULL,
  resource_id TEXT NOT NULL,
  created_at REAL NOT NULL,
  PRIMARY KEY(project_id, operation, key)
);

CREATE TABLE IF NOT EXISTS job_event (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id TEXT NOT NULL,
  job_id TEXT NOT NULL,
  type TEXT NOT NULL,
  payload TEXT NOT NULL,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_job_event_project
  ON job_event(project_id, id);

CREATE TABLE IF NOT EXISTS audit_event (
  id TEXT PRIMARY KEY,
  project_id TEXT,
  actor TEXT NOT NULL DEFAULT 'local-user',
  action TEXT NOT NULL,
  entity_type TEXT,
  entity_id TEXT,
  detail TEXT,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_project
  ON audit_event(project_id, created_at DESC);

CREATE TABLE IF NOT EXISTS report_snapshot (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  title TEXT NOT NULL,
  selection TEXT NOT NULL,
  narrative TEXT,
  artifact_id TEXT REFERENCES artifact(id),
  created_at REAL NOT NULL
);
"""),
    (2, "analysis drafts and hypothesis families", r"""
CREATE TABLE IF NOT EXISTS analysis_draft (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  name TEXT NOT NULL,
  spec TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  UNIQUE(project_id, name)
);

CREATE TABLE IF NOT EXISTS hypothesis_family (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  name TEXT NOT NULL,
  revision INTEGER NOT NULL,
  alpha REAL NOT NULL,
  correction TEXT NOT NULL,
  members TEXT NOT NULL,
  frozen_at REAL,
  created_at REAL NOT NULL,
  UNIQUE(project_id, name, revision)
);
"""),
    (3, "preserved source uploads", r"""
CREATE TABLE IF NOT EXISTS dataset_source (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  dataset_id TEXT NOT NULL REFERENCES dataset(id) ON DELETE CASCADE,
  artifact_id TEXT NOT NULL REFERENCES artifact(id),
  original_name TEXT NOT NULL,
  imported_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dataset_source
  ON dataset_source(project_id,dataset_id,imported_at);
"""),
    (4, "append-only screening history", r"""
ALTER TABLE resolution ADD COLUMN vote_sha TEXT;
ALTER TABLE resolution ADD COLUMN superseded_at REAL;

CREATE TABLE IF NOT EXISTS screening_event (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  record_id TEXT NOT NULL REFERENCES record(id) ON DELETE CASCADE,
  stage TEXT NOT NULL,
  reviewer TEXT,
  action TEXT NOT NULL,
  decision TEXT,
  reason TEXT,
  predecessor_event_id TEXT REFERENCES screening_event(id),
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_screening_event_record
  ON screening_event(project_id,record_id,stage,created_at);
"""),
    (5, "retrieval provenance and report-study identities", r"""
CREATE TABLE IF NOT EXISTS search_execution (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  source TEXT NOT NULL,
  query_spec TEXT NOT NULL,
  status TEXT NOT NULL,
  n_returned INTEGER,
  n_imported INTEGER,
  n_duplicates INTEGER,
  error TEXT,
  started_at REAL NOT NULL,
  ended_at REAL
);
CREATE TABLE IF NOT EXISTS retrieval_hit (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  search_execution_id TEXT NOT NULL REFERENCES search_execution(id) ON DELETE CASCADE,
  source TEXT NOT NULL,
  source_uid TEXT,
  record_id TEXT REFERENCES record(id),
  metadata TEXT NOT NULL,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_retrieval_hit_search
  ON retrieval_hit(project_id,search_execution_id);
CREATE TABLE IF NOT EXISTS evidence_report (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  record_id TEXT NOT NULL REFERENCES record(id) ON DELETE CASCADE,
  report_kind TEXT NOT NULL DEFAULT 'publication',
  created_at REAL NOT NULL,
  UNIQUE(project_id,record_id)
);
CREATE TABLE IF NOT EXISTS study (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  label TEXT NOT NULL,
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS study_report (
  project_id TEXT NOT NULL,
  study_id TEXT NOT NULL REFERENCES study(id) ON DELETE CASCADE,
  report_id TEXT NOT NULL REFERENCES evidence_report(id) ON DELETE CASCADE,
  relationship TEXT NOT NULL DEFAULT 'primary',
  created_at REAL NOT NULL,
  PRIMARY KEY(project_id,study_id,report_id)
);
"""),
)


def _checksum(version: int, name: str, sql: str) -> str:
    raw = f"{version}\n{name}\n{sql}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _columns(conn, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _add_columns(conn) -> None:
    additions = {
        "dataset": (
            ("current_version_id", "TEXT"),
            ("current_dictionary_revision_id", "TEXT"),
            ("archived_at", "REAL"),
        ),
        "job": (
            ("project_id", "TEXT"), ("attempt_id", "TEXT"),
            ("progress", "REAL"), ("note", "TEXT"), ("error", "TEXT"),
            ("lease_token", "TEXT"), ("lease_expires_at", "REAL"),
            ("cancel_requested_at", "REAL"), ("created_at", "REAL"),
        ),
        "project": (("revision", "INTEGER NOT NULL DEFAULT 1"),),
    }
    for table, columns in additions.items():
        have = _columns(conn, table)
        for name, declaration in columns:
            if name not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")


def run(conn) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migration (
          version INTEGER PRIMARY KEY,
          name TEXT NOT NULL,
          checksum TEXT NOT NULL,
          applied_at REAL NOT NULL
        )
    """)
    applied = {row[0]: row[1] for row in conn.execute(
        "SELECT version, checksum FROM schema_migration"
    )}
    for version, name, sql in MIGRATIONS:
        checksum = _checksum(version, name, sql)
        if version in applied:
            if applied[version] != checksum:
                raise RuntimeError(
                    f"Migration {version} ({name}) changed after it was applied. "
                    "Restore the migration text or create a new migration."
                )
            continue
        try:
            # executescript commits a pending transaction before running, so
            # BEGIN must be part of the script itself.
            conn.executescript("BEGIN IMMEDIATE;\n" + sql)
            _add_columns(conn)
            conn.execute(
                "INSERT INTO schema_migration(version,name,checksum,applied_at) VALUES(?,?,?,?)",
                (version, name, checksum, time.time()),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
