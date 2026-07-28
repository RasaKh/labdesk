"""Immutable dataset artifacts, versions and dictionary revisions."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import shutil
import time
from pathlib import Path

import pandas as pd

from . import db
from .config import DATA_DIR

SCHEMA_VERSION = 1


def canonical_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False, default=str)


def request_hash(value) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def file_hash(path: str) -> tuple[str, int]:
    h = hashlib.sha256()
    size = 0
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            size += len(chunk)
            h.update(chunk)
    return h.hexdigest(), size


def frame_schema(frame: pd.DataFrame) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "columns": [
            {"name": str(name), "dtype": str(frame[name].dtype),
             "nullable": bool(frame[name].isna().any())}
            for name in frame.columns
        ],
        "index": {"name": None if frame.index.name is None else str(frame.index.name),
                  "dtype": str(frame.index.dtype)},
    }


def _artifact(project_id: str, path: str, media_type: str | None = None) -> str:
    digest, size = file_hash(path)
    aid = db.new_id("art_")
    db.insert("artifact", {
        "id": aid, "project_id": project_id, "path": os.path.realpath(path),
        "sha256": digest, "size_bytes": size,
        "media_type": media_type or mimetypes.guess_type(path)[0] or "application/octet-stream",
        "state": "ready", "created_at": time.time(),
    })
    return aid


def preserve_source(project_id: str, dataset_id: str, source_path: str,
                    original_name: str) -> dict:
    """Keep the exact uploaded bytes independently from canonical storage."""
    if not db.one("SELECT id FROM dataset WHERE id=? AND project_id=?",
                  (dataset_id, project_id)):
        raise KeyError("Dataset not found in this project.")
    suffix = Path(original_name).suffix.lower()
    target = Path(DATA_DIR) / f"source_{dataset_id}_{db.new_id()[:8]}{suffix}"
    staged = target.with_name("." + target.name + ".stage")
    shutil.copy2(source_path, staged)
    os.replace(staged, target)
    try:
        aid = _artifact(project_id, str(target))
        sid = db.new_id("src_")
        db.insert("dataset_source", {"id": sid, "project_id": project_id,
                  "dataset_id": dataset_id, "artifact_id": aid,
                  "original_name": original_name, "imported_at": time.time()})
        return {"id": sid, "artifact_id": aid, "original_name": original_name}
    except Exception:
        try:
            target.unlink()
        except OSError:
            pass
        raise


def ensure_baseline(dataset_id: str) -> dict:
    """Create a baseline immutable version for a legacy dataset exactly once."""
    ds = db.one("SELECT * FROM dataset WHERE id=?", (dataset_id,))
    if not ds:
        raise KeyError(f"No dataset {dataset_id}.")
    if not ds.get("project_id"):
        raise ValueError("A versioned dataset must belong to a project.")
    current = ds.get("current_version_id")
    if current:
        row = get_version(ds["project_id"], dataset_id, current)
        if row:
            return row
    if not ds.get("path") or not os.path.exists(ds["path"]):
        raise FileNotFoundError("The stored dataset artifact is missing.")
    from . import datasets
    frame = datasets.load(dataset_id)
    vid = db.new_id("dv_")
    aid = _artifact(ds["project_id"], ds["path"])
    ext = Path(ds["path"]).suffix.lower().lstrip(".") or "unknown"
    now = time.time()
    dictionary = db.json_value(ds.get("dictionary"), {})
    did = db.new_id("dict_")
    with db.transaction():
        db.insert("dataset_version", {
            "id": vid, "project_id": ds["project_id"], "dataset_id": dataset_id,
            "parent_id": None, "artifact_id": aid, "storage_format": ext,
            "schema_json": canonical_json(frame_schema(frame)),
            "semantic_sha": datasets.sha256_of_frame(frame), "hash_version": 1,
            "n_rows": len(frame), "n_cols": frame.shape[1],
            "transform_spec": canonical_json({"kind": "legacy_import"}),
            "created_at": now,
        })
        db.insert("dictionary_revision", {
            "id": did, "project_id": ds["project_id"], "dataset_version_id": vid,
            "parent_id": None, "payload": canonical_json(dictionary),
            "semantic_sha": datasets.sha256_of_dictionary(dictionary),
            "reviewed": int(dictionary_reviewed(dictionary)), "revision": 1,
            "created_at": now,
        })
        db.exec_("UPDATE dataset SET current_version_id=?, "
                 "current_dictionary_revision_id=? WHERE id=?",
                 (vid, did, dataset_id))
    return get_version(ds["project_id"], dataset_id, vid)


def dictionary_reviewed(payload: dict) -> bool:
    values = list((payload or {}).values())
    return bool(values) and all(bool(v.get("reviewed")) for v in values)


def get_version(project_id: str, dataset_id: str, version_id: str) -> dict | None:
    row = db.one(
        "SELECT v.*,a.path,a.sha256 artifact_sha,a.size_bytes,a.media_type "
        "FROM dataset_version v JOIN artifact a ON a.id=v.artifact_id "
        "WHERE v.id=? AND v.dataset_id=? AND v.project_id=?",
        (version_id, dataset_id, project_id),
    )
    if row:
        row["schema"] = db.json_value(row.pop("schema_json"), {})
        row["transform"] = db.json_value(row.pop("transform_spec"), None)
    return row


def current(project_id: str, dataset_id: str) -> dict:
    ds = db.one("SELECT * FROM dataset WHERE id=? AND project_id=?",
                (dataset_id, project_id))
    if not ds:
        raise KeyError("Dataset not found in this project.")
    return ensure_baseline(dataset_id)


def list_versions(project_id: str, dataset_id: str) -> list[dict]:
    if not db.one("SELECT id FROM dataset WHERE id=? AND project_id=?",
                  (dataset_id, project_id)):
        raise KeyError("Dataset not found in this project.")
    ensure_baseline(dataset_id)
    rows = db.query(
        "SELECT id,parent_id,storage_format,semantic_sha,hash_version,n_rows,n_cols,"
        "transform_spec,created_at FROM dataset_version "
        "WHERE project_id=? AND dataset_id=? ORDER BY created_at DESC",
        (project_id, dataset_id),
    )
    for row in rows:
        row["transform"] = db.json_value(row.pop("transform_spec"), None)
    return rows


def dictionary(project_id: str, dataset_id: str,
               revision_id: str | None = None) -> dict:
    ds = db.one("SELECT * FROM dataset WHERE id=? AND project_id=?",
                (dataset_id, project_id))
    if not ds:
        raise KeyError("Dataset not found in this project.")
    ensure_baseline(dataset_id)
    rid = revision_id or db.one(
        "SELECT current_dictionary_revision_id id FROM dataset WHERE id=?",
        (dataset_id,),
    )["id"]
    row = db.one(
        "SELECT r.* FROM dictionary_revision r JOIN dataset_version v "
        "ON v.id=r.dataset_version_id WHERE r.id=? AND r.project_id=? "
        "AND v.dataset_id=?", (rid, project_id, dataset_id),
    )
    if not row:
        raise KeyError("Dictionary revision not found in this project.")
    row["payload"] = db.json_value(row["payload"], {})
    return row


def create_dictionary(project_id: str, dataset_id: str, payload: dict,
                      expected_revision: int | None = None) -> dict:
    if not isinstance(payload, dict) or not payload:
        raise ValueError("Dictionary payload must contain at least one variable.")
    version = current(project_id, dataset_id)
    prior = dictionary(project_id, dataset_id)
    if expected_revision is not None and prior["revision"] != expected_revision:
        raise RuntimeError("Dictionary changed since it was loaded.")
    expected_columns = {c["name"] for c in version["schema"]["columns"]}
    if set(payload) != expected_columns:
        missing = sorted(expected_columns - set(payload))
        extra = sorted(set(payload) - expected_columns)
        raise ValueError(f"Dictionary columns do not match data (missing={missing}, extra={extra}).")
    rid = db.new_id("dict_")
    now = time.time()
    with db.transaction():
        db.insert("dictionary_revision", {
            "id": rid, "project_id": project_id,
            "dataset_version_id": version["id"], "parent_id": prior["id"],
            "payload": canonical_json(payload),
            "semantic_sha": request_hash(payload),
            "reviewed": int(dictionary_reviewed(payload)),
            "revision": prior["revision"] + 1, "created_at": now,
        })
        db.exec_("UPDATE dataset SET dictionary=?,dictionary_sha=?,"
                 "current_dictionary_revision_id=? WHERE id=? AND project_id=?",
                 (canonical_json(payload), request_hash(payload), rid,
                  dataset_id, project_id))
    return dictionary(project_id, dataset_id, rid)
