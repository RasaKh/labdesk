"""Immutable dataset artifacts and version hashing."""

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
