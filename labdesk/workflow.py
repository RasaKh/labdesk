"""Durable analysis drafts, hypothesis-family revisions and report snapshots."""

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


def create_family(project_id: str, name: str, alpha: float, correction: str,
                  members: list, freeze=False) -> dict:
    if not name.strip():
        raise ValueError("Family name is required.")
    if not 0 < float(alpha) < 1:
        raise ValueError("Family alpha must be between 0 and 1.")
    allowed = {"holm", "bonferroni", "hochberg", "bh", "by", "none"}
    if correction not in allowed:
        raise ValueError("Unsupported multiplicity correction.")
    if not isinstance(members, list) or not members:
        raise ValueError("A hypothesis family needs at least one declared member.")
    prior = db.one("SELECT MAX(revision) revision FROM hypothesis_family "
                   "WHERE project_id=? AND name=?", (project_id, name.strip()))
    revision = int((prior or {}).get("revision") or 0) + 1
    fid = db.new_id("fam_")
    now = time.time()
    db.insert("hypothesis_family", {
        "id": fid, "project_id": project_id, "name": name.strip(),
        "revision": revision, "alpha": float(alpha), "correction": correction,
        "members": revisions.canonical_json(members),
        "frozen_at": now if freeze else None, "created_at": now,
    })
    return get_family(project_id, fid)


def get_family(project_id: str, family_id: str) -> dict:
    row = db.one("SELECT * FROM hypothesis_family WHERE id=? AND project_id=?",
                 (family_id, project_id))
    if not row:
        raise KeyError("Hypothesis family not found in this project.")
    row["members"] = db.json_value(row["members"], [])
    return row


def list_families(project_id: str) -> list[dict]:
    rows = db.query("SELECT * FROM hypothesis_family WHERE project_id=? "
                    "ORDER BY name,revision DESC", (project_id,))
    for row in rows:
        row["members"] = db.json_value(row["members"], [])
    return rows


def create_report_snapshot(project_id: str, title: str, selection: dict,
                           narrative="") -> dict:
    run_ids = list((selection or {}).get("run_ids") or [])
    figure_ids = list((selection or {}).get("figure_ids") or [])
    for table, ids in (("analysis_run", run_ids), ("figure", figure_ids)):
        if not ids:
            continue
        marks = ",".join("?" for _ in ids)
        count = db.one(f"SELECT COUNT(*) c FROM {table} WHERE project_id IS ? "
                       f"AND id IN ({marks})", (project_id, *ids))["c"]
        if count != len(set(ids)):
            raise ValueError(f"Report selection contains an inaccessible {table} item.")
    sid = db.new_id("report_")
    db.insert("report_snapshot", {
        "id": sid, "project_id": project_id,
        "title": title.strip() or "Untitled report snapshot",
        "selection": revisions.canonical_json(selection or {}),
        "narrative": narrative, "artifact_id": None, "created_at": time.time(),
    })
    return report_snapshot(project_id, sid)


def report_snapshot(project_id: str, snapshot_id: str) -> dict:
    row = db.one("SELECT * FROM report_snapshot WHERE id=? AND project_id=?",
                 (snapshot_id, project_id))
    if not row:
        raise KeyError("Report snapshot not found in this project.")
    row["selection"] = db.json_value(row["selection"], {})
    return row

