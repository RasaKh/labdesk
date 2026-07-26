"""Version-bound preflight snapshots."""

from __future__ import annotations

import time

from . import config, db, revisions, stats_run

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
