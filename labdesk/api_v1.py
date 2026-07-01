"""Explicitly project-scoped v1 HTTP contracts: project and dataset staging."""

from __future__ import annotations

import os

from flask import Blueprint, jsonify, request
from werkzeug.utils import secure_filename

from . import config, datasets, db, projects, revisions


def _error(code, message, status, fields=None, retryable=False):
    return jsonify({"error": {"code": code, "message": message,
                              "fields": fields or {}, "retryable": retryable,
                              "request_id": db.new_id("req_")}}), status


def _project(pid):
    return projects.get(pid)


def create_blueprint():
    bp = Blueprint("api_v1", __name__, url_prefix="/api/v1")

    @bp.get("/capabilities")
    def capabilities():
        from . import plots_registry, stats_registry
        return jsonify({
            "schema_version": 1,
            "dependencies": config.dependency_report(),
            "analysis": stats_registry.REGISTRY,
            "plots": plots_registry.REGISTRY,
        })

    @bp.get("/projects")
    def list_projects():
        return jsonify({"items": projects.listing(request.args.get("archived") == "1")})

    @bp.post("/projects")
    def create_project():
        body = request.get_json(silent=True) or {}
        if not str(body.get("name") or "").strip():
            return _error("invalid_project", "Project name is required.", 422,
                          {"name": "required"})
        return jsonify(projects.create(body["name"], body.get("kind", "analysis"),
                                       body.get("question", ""), body.get("registered", ""),
                                       body.get("notes", ""))), 201

    @bp.get("/projects/<pid>")
    def project_detail(pid):
        item = _project(pid)
        if not item:
            return _error("not_found", "Project not found.", 404)
        item["progress"] = projects.progress(pid)
        item["counts"] = projects.counts(pid)
        return jsonify(item)

    @bp.patch("/projects/<pid>")
    def update_project(pid):
        if not _project(pid):
            return _error("not_found", "Project not found.", 404)
        expected = request.headers.get("If-Match")
        try:
            expected = int(expected.strip('"')) if expected is not None else None
            return jsonify(projects.update(pid, request.get_json(silent=True) or {}, expected))
        except (ValueError, RuntimeError) as exc:
            return _error("revision_conflict", str(exc), 409)

    @bp.get("/projects/<pid>/datasets")
    def list_datasets(pid):
        if not _project(pid):
            return _error("not_found", "Project not found.", 404)
        return jsonify({"items": datasets.list_datasets(pid)})

    @bp.post("/projects/<pid>/imports")
    def import_dataset(pid):
        if not _project(pid):
            return _error("not_found", "Project not found.", 404)
        uploaded = request.files.get("file")
        if not uploaded:
            return _error("missing_file", "Choose a data file.", 400)
        original = uploaded.filename or "upload.csv"
        safe = secure_filename(original) or "upload.csv"
        tmp = os.path.join(config.TMP_DIR, f"{db.new_id('up_')}_{safe}")
        uploaded.save(tmp)
        try:
            dataset_id = datasets.import_file(tmp, name=original, source=original,
                                              project_id=pid)
            revisions.preserve_source(pid, dataset_id, tmp, original)
            return jsonify({"dataset": datasets.meta(dataset_id),
                            "version": revisions.current(pid, dataset_id)}), 201
        except Exception as exc:
            return _error("import_failed", f"{type(exc).__name__}: {exc}", 422)
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass

    return bp