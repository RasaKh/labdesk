"""Explicitly project-scoped v1 HTTP contracts: dataset revisions, analysis, jobs, exports."""

from __future__ import annotations

import json
import os
import time

from flask import Blueprint, Response, jsonify, request
from werkzeug.utils import secure_filename

from . import analysis_guide, attempts, config, datasets, db, projects, revisions
from .jobs import JOBS, sse


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

    @bp.get("/projects/<pid>/datasets/<did>/versions")
    def versions(pid, did):
        try:
            return jsonify({"items": revisions.list_versions(pid, did)})
        except KeyError as exc:
            return _error("not_found", str(exc), 404)

    @bp.post("/projects/<pid>/datasets/<did>/versions")
    def transform(pid, did):
        body = request.get_json(silent=True) or {}
        try:
            row = revisions.transform(pid, did, body.get("parent_id"),
                                      body.get("operation") or {})
            return jsonify(row), 201
        except KeyError as exc:
            return _error("not_found", str(exc), 404)
        except (ValueError, RuntimeError) as exc:
            return _error("invalid_transform", str(exc), 422)

    @bp.get("/projects/<pid>/datasets/<did>/versions/<vid>/preview")
    def preview(pid, did, vid):
        row = revisions.get_version(pid, did, vid)
        if not row:
            return _error("not_found", "Dataset version not found.", 404)
        try:
            offset = max(0, int(request.args.get("offset", 0)))
            limit = max(1, min(int(request.args.get("limit", 100)), 500))
            frame = datasets.read_any(row["path"])
            wanted = request.args.getlist("column")
            if wanted:
                missing = [c for c in wanted if c not in frame.columns]
                if missing:
                    return _error("invalid_columns", "Unknown preview columns.", 422,
                                  {"columns": missing})
                frame = frame[wanted]
            page = frame.iloc[offset:offset + limit]
            return jsonify({"offset": offset, "limit": limit, "total": len(frame),
                            "columns": list(page.columns),
                            "rows": json.loads(page.to_json(orient="records", date_format="iso"))})
        except Exception as exc:
            return _error("preview_failed", f"{type(exc).__name__}: {exc}", 422)

    @bp.get("/projects/<pid>/datasets/<did>/dictionary")
    def get_dictionary(pid, did):
        try:
            return jsonify(revisions.dictionary(pid, did, request.args.get("revision_id")))
        except KeyError as exc:
            return _error("not_found", str(exc), 404)

    @bp.post("/projects/<pid>/datasets/<did>/dictionary-revisions")
    def set_dictionary(pid, did):
        body = request.get_json(silent=True) or {}
        try:
            row = revisions.create_dictionary(pid, did, body.get("payload") or {},
                                              body.get("expected_revision"))
            return jsonify(row), 201
        except KeyError as exc:
            return _error("not_found", str(exc), 404)
        except RuntimeError as exc:
            return _error("revision_conflict", str(exc), 409)
        except ValueError as exc:
            return _error("invalid_dictionary", str(exc), 422)

    @bp.post("/projects/<pid>/analysis/compatible")
    def compatible(pid):
        body = request.get_json(silent=True) or {}
        try:
            dictionary = revisions.dictionary(pid, body.get("dataset"),
                                              body.get("dictionary_revision_id"))
            return jsonify(analysis_guide.compatible_methods(
                dictionary["payload"], body.get("goal") or "compare",
                body.get("primary") or None, body.get("secondary") or None,
                body.get("limit", 12),
            ))
        except KeyError as exc:
            return _error("not_found", str(exc), 404)
        except ValueError as exc:
            return _error("invalid_guide_request", str(exc), 422)

    @bp.post("/projects/<pid>/analysis/preflight")
    def preflight(pid):
        if not _project(pid):
            return _error("not_found", "Project not found.", 404)
        try:
            return jsonify(attempts.preflight(pid, request.get_json(silent=True) or {}))
        except attempts.Conflict as exc:
            return _error("revision_conflict", str(exc), 409)
        except (ValueError, KeyError) as exc:
            return _error("invalid_preflight", str(exc), 422)

    @bp.post("/projects/<pid>/analysis-attempts")
    def submit_attempt(pid):
        try:
            row = attempts.submit(pid, request.get_json(silent=True) or {},
                                  request.headers.get("Idempotency-Key"))
            return jsonify(row), 202
        except attempts.Conflict as exc:
            return _error("submission_conflict", str(exc), 409)
        except KeyError as exc:
            return _error("not_found", str(exc), 404)
        except ValueError as exc:
            return _error("invalid_submission", str(exc), 422)

    @bp.get("/projects/<pid>/analysis-attempts")
    def list_attempts(pid):
        return jsonify({"items": attempts.listing(pid, request.args.get("limit", 100))})

    @bp.get("/projects/<pid>/analysis-attempts/<aid>")
    def attempt_detail(pid, aid):
        try:
            return jsonify(attempts.detail(pid, aid))
        except KeyError as exc:
            return _error("not_found", str(exc), 404)

    @bp.get("/projects/<pid>/jobs")
    def jobs(pid):
        live = JOBS.list(pid)
        live_ids = {j["id"] for j in live}
        stored = db.query("SELECT * FROM job WHERE project_id=? ORDER BY COALESCE(created_at,started_at) DESC LIMIT 200",
                          (pid,))
        return jsonify({"items": live + [j for j in stored if j["id"] not in live_ids]})

    @bp.post("/projects/<pid>/jobs/<jid>/cancel")
    def cancel(pid, jid):
        live = JOBS.get(jid)
        if live and live.project_id == pid:
            live.cancel()
            return jsonify({"ok": True, "status": live.status})
        stored = JOBS.stored(jid, pid)
        if not stored:
            return _error("not_found", "Job not found.", 404)
        return _error("not_cancellable", "Job is no longer running in this process.", 409)

    @bp.get("/projects/<pid>/events")
    def events(pid):
        if not _project(pid):
            return _error("not_found", "Project not found.", 404)
        try:
            cursor = int(request.headers.get("Last-Event-ID") or request.args.get("after") or 0)
        except ValueError:
            cursor = 0

        def stream():
            nonlocal cursor
            yield sse({"type": "hello", "project_id": pid, "after": cursor})
            while True:
                rows = db.query("SELECT * FROM job_event WHERE project_id=? AND id>? ORDER BY id LIMIT 100",
                                (pid, cursor))
                if rows:
                    for row in rows:
                        cursor = row["id"]
                        payload = db.json_value(row["payload"], {})
                        payload.update({"type": row["type"], "job": row["job_id"],
                                        "project_id": pid})
                        yield f"id: {cursor}\n" + sse(payload)
                else:
                    yield ": keepalive\n\n"
                time.sleep(1)
        return Response(stream(), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @bp.post("/projects/<pid>/exports")
    def export_project(pid):
        from . import exports_v1
        body = request.get_json(silent=True) or {}
        if body.get("mode", "audit") != "audit":
            return _error("unsupported_export", "Only audit export is implemented in v1.", 422)
        try:
            return jsonify(exports_v1.create_audit_bundle(
                pid, include_data=bool(body.get("include_data", False)))), 201
        except KeyError as exc:
            return _error("not_found", str(exc), 404)
        except Exception as exc:
            return _error("export_failed", f"{type(exc).__name__}: {exc}", 422)

    return bp