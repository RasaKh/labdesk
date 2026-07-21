"""Project audit bundles with complete manifests."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import time
import zipfile
from pathlib import Path

from . import db
from .config import EXPORT_DIR


def _hash(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def create_audit_bundle(project_id: str, include_data=False) -> dict:
    project = db.one("SELECT * FROM project WHERE id=?", (project_id,))
    if not project:
        raise KeyError("Project not found.")
    os.makedirs(EXPORT_DIR, exist_ok=True)
    export_id = f"audit_{time.strftime('%Y%m%d_%H%M%S')}_{db.new_id()[:6]}"
    stage = Path(tempfile.mkdtemp(prefix=".export-", dir=EXPORT_DIR))
    final = Path(EXPORT_DIR) / f"labdesk_{export_id}.zip"
    omissions = []
    try:
        attempts = db.query("SELECT * FROM analysis_attempt WHERE project_id=? ORDER BY created_at",
                            (project_id,))
        runs = db.query("SELECT * FROM analysis_run WHERE project_id IS ? ORDER BY created_at",
                        (project_id,))
        versions = db.query("SELECT * FROM dataset_version WHERE project_id=? ORDER BY created_at",
                            (project_id,))
        dictionaries = db.query("SELECT * FROM dictionary_revision WHERE project_id=? ORDER BY created_at",
                                (project_id,))
        events = db.query("SELECT * FROM audit_event WHERE project_id=? ORDER BY created_at",
                          (project_id,))
        payloads = {
            "project.json": project, "attempts.json": attempts, "runs.json": runs,
            "dataset_versions.json": versions, "dictionary_revisions.json": dictionaries,
            "audit_events.json": events,
        }
        for name, payload in payloads.items():
            (stage / name).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        files = []
        for path in sorted(stage.rglob("*")):
            if path.is_file():
                files.append({"path": path.relative_to(stage).as_posix(),
                              "sha256": _hash(path), "size_bytes": path.stat().st_size})
        # A record-only audit so far: inspection data without a verified replay.
        reproducibility = "record_only"
        manifest = {"schema_version": 1, "export_id": export_id,
                    "created_at": time.time(), "project_id": project_id,
                    "mode": "audit", "include_data": bool(include_data),
                    "reproducibility_status": reproducibility,
                    "omissions": omissions, "files": files}
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        with zipfile.ZipFile(final, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(stage.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(stage).as_posix())
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    return {"id": export_id, "path": str(final), "size_bytes": final.stat().st_size,
            "reproducibility_status": reproducibility, "omissions": omissions}