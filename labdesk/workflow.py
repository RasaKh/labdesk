"""Durable analysis drafts."""

from __future__ import annotations

import time

from . import db, revisions

class RevisionConflict(RuntimeError):
    pass


def save_draft(project_id: str, name: str, spec: dict,
               expected_revision: int | None = None) -> dict:
    if not str(name).strip():
        raise ValueError("Draft name is required.")
    if not isinstance(spec, dict):
        raise ValueError("Draft specification must be an object.")
    prior = db.one("SELECT * FROM analysis_draft WHERE project_id=? AND name=?",
                   (project_id, name.strip()))
    now = time.time()
    if prior:
        if expected_revision is None or int(expected_revision) != prior["revision"]:
            raise RevisionConflict("Draft changed since it was loaded.")
        db.exec_("UPDATE analysis_draft SET spec=?,revision=revision+1,updated_at=? "
                 "WHERE id=? AND revision=?",
                 (revisions.canonical_json(spec), now, prior["id"], prior["revision"]))
        did = prior["id"]
    else:
        if expected_revision not in (None, 0):
            raise RevisionConflict("Draft no longer exists at the expected revision.")
        did = db.new_id("draft_")
        db.insert("analysis_draft", {"id": did, "project_id": project_id,
                  "name": name.strip(), "spec": revisions.canonical_json(spec),
                  "revision": 1, "created_at": now, "updated_at": now})
    return get_draft(project_id, did)


def get_draft(project_id: str, draft_id: str) -> dict:
    row = db.one("SELECT * FROM analysis_draft WHERE id=? AND project_id=?",
                 (draft_id, project_id))
    if not row:
        raise KeyError("Draft not found in this project.")
    row["spec"] = db.json_value(row["spec"], {})
    return row


def list_drafts(project_id: str) -> list[dict]:
    rows = db.query("SELECT * FROM analysis_draft WHERE project_id=? ORDER BY updated_at DESC",
                    (project_id,))
    for row in rows:
        row["spec"] = db.json_value(row["spec"], {})
    return rows
