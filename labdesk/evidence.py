"""Report and study identities layered over the legacy record corpus."""

from __future__ import annotations

import time

from . import db


def ensure_report(project_id: str, record_id: str, report_kind="publication") -> dict:
    record = db.one("SELECT id FROM record WHERE id=? AND project_id IS ?",
                    (record_id, project_id))
    if not record:
        raise KeyError("Record not found in this project.")
    row = db.one("SELECT * FROM evidence_report WHERE project_id=? AND record_id=?",
                 (project_id, record_id))
    if row:
        return row
    rid = db.new_id("report_")
    db.insert("evidence_report", {"id": rid, "project_id": project_id,
              "record_id": record_id, "report_kind": report_kind,
              "created_at": time.time()})
    return db.one("SELECT * FROM evidence_report WHERE id=?", (rid,))


def create_study(project_id: str, label: str, report_ids: list[str],
                 relationship="primary") -> dict:
    if not label.strip():
        raise ValueError("Study label is required.")
    report_ids = list(dict.fromkeys(report_ids or []))
    if not report_ids:
        raise ValueError("Link at least one report to the study.")
    marks = ",".join("?" for _ in report_ids)
    rows = db.query(f"SELECT id FROM evidence_report WHERE project_id=? AND id IN ({marks})",
                    (project_id, *report_ids))
    if len(rows) != len(report_ids):
        raise ValueError("One or more reports do not belong to this project.")
    sid = db.new_id("study_")
    now = time.time()
    with db.transaction():
        db.insert("study", {"id": sid, "project_id": project_id,
                  "label": label.strip(), "created_at": now})
        for report_id in report_ids:
            db.exec_("INSERT INTO study_report(project_id,study_id,report_id,relationship,created_at) "
                     "VALUES(?,?,?,?,?)", (project_id, sid, report_id, relationship, now))
    return study_detail(project_id, sid)