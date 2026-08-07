"""Verified snapshots of the database and immutable artifact store."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import threading
import time
import zipfile
from pathlib import Path

from . import db
from .config import BACKUP_DIR, DB_PATH, get


_lock = threading.Lock()


def _hash(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def create() -> dict:
    """Create a SQLite online snapshot plus hash-verified referenced files."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    backup_id = f"backup_{time.strftime('%Y%m%d_%H%M%S')}_{db.new_id()[:6]}"
    staging = Path(tempfile.mkdtemp(prefix=".stage-", dir=BACKUP_DIR))
    final = Path(BACKUP_DIR) / f"{backup_id}.zip"
    with _lock:
        try:
            snapshot = staging / "labdesk.db"
            destination = sqlite3.connect(snapshot)
            try:
                db.db().backup(destination)
            finally:
                destination.close()
            snap = sqlite3.connect(snapshot)
            try:
                integrity = snap.execute("PRAGMA integrity_check").fetchone()[0]
                if integrity != "ok":
                    raise RuntimeError(f"Database snapshot integrity check: {integrity}")
                rows = [dict(zip([c[0] for c in cur.description], row))
                        for cur in [snap.execute("SELECT id,path,sha256,size_bytes FROM artifact WHERE state='ready'")]
                        for row in cur.fetchall()]
            finally:
                snap.close()
            manifest = {"schema_version": 1, "backup_id": backup_id,
                        "created_at": time.time(), "database": {}, "artifacts": [],
                        "omissions": []}
            manifest["database"] = {"path": "labdesk.db", "sha256": _hash(snapshot),
                                    "size_bytes": snapshot.stat().st_size}
            files_dir = staging / "artifacts"
            files_dir.mkdir()
            for row in rows:
                source = row["path"]
                if not source or not os.path.isfile(source):
                    manifest["omissions"].append({"artifact_id": row["id"],
                                                  "reason": "missing"})
                    continue
                actual = _hash(source)
                if actual != row["sha256"]:
                    manifest["omissions"].append({"artifact_id": row["id"],
                                                  "reason": "hash_mismatch"})
                    continue
                suffix = Path(source).suffix
                relative = f"artifacts/{row['id']}{suffix}"
                target = staging / relative
                shutil.copy2(source, target)
                manifest["artifacts"].append({"id": row["id"], "path": relative,
                                              "sha256": actual,
                                              "size_bytes": target.stat().st_size})
            (staging / "manifest.json").write_text(
                json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
            )
            with zipfile.ZipFile(final, "w", zipfile.ZIP_DEFLATED) as archive:
                for path in sorted(staging.rglob("*")):
                    if path.is_file():
                        archive.write(path, path.relative_to(staging).as_posix())
            checked = verify(str(final))
            if not checked["ok"]:
                raise RuntimeError("Backup verification failed: " + "; ".join(checked["errors"]))
        finally:
            shutil.rmtree(staging, ignore_errors=True)
    _prune()
    return {"id": backup_id, "path": str(final), "size_bytes": final.stat().st_size,
            "verified": True, "omissions": manifest["omissions"]}


def verify(path: str) -> dict:
    errors = []
    try:
        with zipfile.ZipFile(path) as archive:
            bad = archive.testzip()
            if bad:
                errors.append(f"Corrupt zip member: {bad}")
            manifest = json.loads(archive.read("manifest.json"))
            for item in [manifest["database"], *manifest.get("artifacts", [])]:
                data = archive.read(item["path"])
                digest = hashlib.sha256(data).hexdigest()
                if digest != item["sha256"]:
                    errors.append(f"Hash mismatch: {item['path']}")
            with tempfile.TemporaryDirectory() as td:
                dbfile = Path(td) / "snapshot.db"
                dbfile.write_bytes(archive.read(manifest["database"]["path"]))
                conn = sqlite3.connect(dbfile)
                try:
                    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
                    if integrity != "ok":
                        errors.append(f"SQLite integrity: {integrity}")
                finally:
                    conn.close()
    except Exception as exc:
        errors.append(f"{type(exc).__name__}: {exc}")
        manifest = None
    return {"ok": not errors, "errors": errors, "manifest": manifest}


def restore(path: str, destination: str) -> dict:
    """Restore a verified backup into a new directory without touching live data."""
    checked = verify(path)
    if not checked["ok"]:
        raise RuntimeError("Backup verification failed: " + "; ".join(checked["errors"]))
    target = Path(destination).resolve()
    if target.exists() and any(target.iterdir()):
        raise ValueError("Restore destination must be new or empty.")
    target.mkdir(parents=True, exist_ok=True)
    manifest = checked["manifest"]
    with zipfile.ZipFile(path) as archive:
        database_path = target / "labdesk.db"
        database_path.write_bytes(archive.read(manifest["database"]["path"]))
        artifact_root = target / "artifacts"
        artifact_root.mkdir()
        restored = []
        for item in manifest.get("artifacts", []):
            suffix = Path(item["path"]).suffix
            output = artifact_root / f"{item['id']}{suffix}"
            output.write_bytes(archive.read(item["path"]))
            if _hash(output) != item["sha256"]:
                raise RuntimeError(f"Restored artifact hash mismatch: {item['id']}")
            restored.append((str(output), item["id"]))
    conn = sqlite3.connect(database_path)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        with conn:
            conn.executemany("UPDATE artifact SET path=? WHERE id=?", restored)
            conn.execute(
                "UPDATE dataset SET path=(SELECT a.path FROM dataset_version v "
                "JOIN artifact a ON a.id=v.artifact_id "
                "WHERE v.id=dataset.current_version_id) "
                "WHERE current_version_id IS NOT NULL"
            )
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        foreign = conn.execute("PRAGMA foreign_key_check").fetchall()
        if integrity != "ok" or foreign:
            raise RuntimeError(f"Restored database check failed: integrity={integrity}, foreign_keys={foreign}")
    finally:
        conn.close()
    report = {"source": os.path.realpath(path), "destination": str(target),
              "database": str(database_path), "artifacts_restored": len(restored),
              "omissions": manifest.get("omissions", []), "verified": True}
    (target / "restore_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def listing() -> list[dict]:
    root = Path(BACKUP_DIR)
    if not root.exists():
        return []
    return [{"name": p.name, "path": str(p), "size_bytes": p.stat().st_size,
             "modified_at": p.stat().st_mtime}
            for p in sorted(root.glob("backup_*.zip"), key=lambda p: p.stat().st_mtime,
                            reverse=True)]


def _prune():
    keep = max(1, int(get("backup_keep", 5)))
    for item in listing()[keep:]:
        try:
            os.remove(item["path"])
        except OSError:
            pass
