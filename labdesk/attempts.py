"""Version-bound preflights and durable analysis-attempt lifecycle."""

from __future__ import annotations

import json
import time

from . import config, db, revisions, stats_registry, stats_run
from .jobs import JOBS


PREFLIGHT_TTL_SECONDS = 15 * 60
FROZEN_SETTING_KEYS = (
    "alpha", "ci_level", "seed", "assumption_policy", "multiplicity_default",
    "multiplicity_nag_after", "p_decimals", "p_min_display",
)


class Conflict(RuntimeError):
    pass


def frozen_settings() -> dict:
    return {key: config.get(key) for key in FROZEN_SETTING_KEYS}


def _bound(project_id: str, body: dict) -> tuple[dict, dict, dict]:
    dataset_id = body.get("dataset")
    if not dataset_id:
        raise ValueError("Choose a dataset.")
    version = revisions.current(project_id, dataset_id)
    wanted_version = body.get("dataset_version_id")
    if wanted_version and wanted_version != version["id"]:
        raise Conflict(
            "This runner adapter currently executes the dataset's current version. "
            "Switch the dataset to the requested version before preflight."
        )
    dictionary = revisions.dictionary(
        project_id, dataset_id, body.get("dictionary_revision_id")
    )
    if dictionary["dataset_version_id"] != version["id"]:
        raise Conflict("The selected dictionary does not describe this dataset version.")
    spec = {
        "test": body.get("test"), "dataset": dataset_id, "project": project_id,
        "roles": body.get("roles") or {}, "params": body.get("params") or {},
    }
    return spec, version, dictionary


def preflight(project_id: str, body: dict) -> dict:
    spec, version, dictionary = _bound(project_id, body)
    settings = frozen_settings()
    with config.execution_settings(settings):
        result = stats_run.preflight(spec)
    resolved = {
        "schema_version": 1, "project_id": project_id,
        "dataset_id": spec["dataset"], "dataset_version_id": version["id"],
        "dictionary_revision_id": dictionary["id"], "method_id": spec["test"],
        "method_version": "1", "roles": spec["roles"], "parameters": spec["params"],
        "execution": settings,
    }
    digest = revisions.request_hash(resolved)
    token = db.new_id("pf_")
    db.exec_(
        "INSERT INTO preflight_snapshot(token,project_id,dataset_version_id,"
        "dictionary_revision_id,request_sha,resolved_spec,result,expires_at,consumed_at) "
        "VALUES(?,?,?,?,?,?,?,?,NULL)",
        (token, project_id, version["id"], dictionary["id"], digest,
         revisions.canonical_json(resolved), revisions.canonical_json(result),
         time.time() + PREFLIGHT_TTL_SECONDS),
    )
    return {**result, "preflight_token": token, "request_sha": digest,
            "dataset_version_id": version["id"],
            "dictionary_revision_id": dictionary["id"],
            "expires_at": time.time() + PREFLIGHT_TTL_SECONDS}


def _set(attempt_id: str, status: str, **fields) -> None:
    allowed = {"job_id", "run_id", "diagnostics", "error", "started_at", "ended_at"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    updates["status"] = status
    sets, args = [], []
    for key, value in updates.items():
        sets.append(f"{key}=?")
        if key == "diagnostics" and not isinstance(value, str):
            value = revisions.canonical_json(value)
        args.append(value)
    args.append(attempt_id)
    db.exec_(f"UPDATE analysis_attempt SET {','.join(sets)} WHERE id=?", tuple(args))


def _execute(attempt_id: str, legacy_spec: dict, settings: dict):
    def body(ctl):
        _set(attempt_id, "running", started_at=time.time())
        with config.execution_settings(settings):
            return stats_run.run(legacy_spec, ctl)
    return body


def _finish(attempt_id: str):
    """Settle the attempt from its job's terminal state. Runs after the job row
    is persisted, so a terminal attempt always points at a terminal job."""
    def finish(job):
        now = time.time()
        if job.status == "cancelled":
            _set(attempt_id, "cancelled", error="Cancelled.", ended_at=now)
        elif job.status != "done":
            _set(attempt_id, "failed", error=job.error or f"Job {job.status}.", ended_at=now)
        elif (job.result or {}).get("ok"):
            _set(attempt_id, "succeeded", run_id=job.result.get("run_id"),
                 diagnostics=job.result.get("checks") or [], ended_at=now)
        else:
            result = job.result or {}
            state = "blocked" if result.get("blocked") else "rejected"
            _set(attempt_id, state, diagnostics=result.get("checks") or [],
                 error="; ".join(result.get("errors") or []), ended_at=now)
    return finish


def submit(project_id: str, body: dict, idempotency_key: str | None = None) -> dict:
    token = body.get("preflight_token")
    if not token:
        raise ValueError("Run preflight before submitting an analysis.")
    pf = db.one("SELECT * FROM preflight_snapshot WHERE token=? AND project_id=?",
                (token, project_id))
    if not pf:
        raise KeyError("Preflight token not found in this project.")
    if idempotency_key:
        existing = db.one(
            "SELECT * FROM idempotency_key WHERE project_id=? AND operation=? AND key=?",
            (project_id, "analysis_attempt", idempotency_key),
        )
        if existing:
            if existing["request_sha"] != pf["request_sha"]:
                raise Conflict("Idempotency key was already used with another request.")
            return detail(project_id, existing["resource_id"])
    if pf["consumed_at"] is not None:
        raise Conflict("This preflight was already submitted.")
    if pf["expires_at"] < time.time():
        raise Conflict("Preflight expired; review the inputs again.")
    resolved = db.json_value(pf["resolved_spec"], {})
    # Re-bind current pointers and settings. Any drift invalidates the review.
    spec, version, dictionary = _bound(project_id, {
        "dataset": resolved.get("dataset_id"), "test": resolved.get("method_id"),
        "roles": resolved.get("roles"), "params": resolved.get("parameters"),
        "dataset_version_id": resolved.get("dataset_version_id"),
        "dictionary_revision_id": resolved.get("dictionary_revision_id"),
    })
    if version["id"] != pf["dataset_version_id"] or dictionary["id"] != pf["dictionary_revision_id"]:
        raise Conflict("Dataset or dictionary changed after preflight.")
    if frozen_settings() != resolved.get("execution"):
        raise Conflict("Analysis defaults changed after preflight; review them again.")
    digest = revisions.request_hash(resolved)
    if digest != pf["request_sha"]:
        raise Conflict("Preflight contents failed integrity validation.")

    attempt_id = db.new_id("att_")
    now = time.time()
    settings = resolved["execution"]
    entry = stats_registry.get(spec["test"]) or {}
    with db.transaction():
        db.insert("analysis_attempt", {
            "id": attempt_id, "project_id": project_id,
            "dataset_version_id": version["id"],
            "dictionary_revision_id": dictionary["id"],
            "requested_spec": revisions.canonical_json(spec),
            "resolved_spec": revisions.canonical_json(resolved),
            "request_sha": digest, "settings": revisions.canonical_json(settings),
            "method_id": spec["test"], "method_version": "1",
            "registry_version": "1", "status": "queued", "created_at": now,
        })
        db.exec_("UPDATE preflight_snapshot SET consumed_at=? WHERE token=?",
                 (now, token))
        if idempotency_key:
            db.exec_(
                "INSERT INTO idempotency_key(project_id,operation,key,request_sha,resource_id,created_at) "
                "VALUES(?,?,?,?,?,?)",
                (project_id, "analysis_attempt", idempotency_key, digest, attempt_id, now),
            )
    try:
        job = JOBS.submit(
            "analysis", entry.get("label", spec["test"]),
            _execute(attempt_id, spec, settings), spec=resolved,
            project_id=project_id, attempt_id=attempt_id,
            on_finish=_finish(attempt_id),
            meta={"project_id": project_id, "attempt_id": attempt_id},
        )
        # The worker may start immediately. Attach the job without regressing
        # an already-running or terminal attempt back to queued.
        db.exec_("UPDATE analysis_attempt SET job_id=? WHERE id=?", (job.id, attempt_id))
    except Exception as exc:
        _set(attempt_id, "failed", error=f"Could not queue: {exc}", ended_at=time.time())
        raise
    return detail(project_id, attempt_id)


def detail(project_id: str, attempt_id: str) -> dict:
    row = db.one("SELECT * FROM analysis_attempt WHERE id=? AND project_id=?",
                 (attempt_id, project_id))
    if not row:
        raise KeyError("Analysis attempt not found in this project.")
    for key in ("requested_spec", "resolved_spec", "settings", "diagnostics"):
        row[key] = db.json_value(row.get(key), None)
    if row.get("run_id"):
        run = db.one("SELECT result FROM analysis_run WHERE id=? AND project_id=?",
                     (row["run_id"], project_id))
        row["result"] = db.json_value((run or {}).get("result"), None)
        if isinstance(row["result"], dict):
            row["result"].setdefault("run_id", row["run_id"])
            row["result"].setdefault("project_id", project_id)
    return row


def listing(project_id: str, limit: int = 100) -> list[dict]:
    rows = db.query(
        "SELECT id,method_id,status,job_id,run_id,retry_of,error,created_at,started_at,ended_at "
        "FROM analysis_attempt WHERE project_id=? ORDER BY created_at DESC LIMIT ?",
        (project_id, max(1, min(int(limit), 300))),
    )
    return rows
