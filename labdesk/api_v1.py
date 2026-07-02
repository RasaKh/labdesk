"""Explicitly project-scoped v1 HTTP contracts."""

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

    @bp.get("/projects/<pid>/analysis-drafts")
    def analysis_drafts(pid):
        from . import workflow
        return jsonify({"items": workflow.list_drafts(pid)})

    @bp.post("/projects/<pid>/analysis-drafts")
    def save_analysis_draft(pid):
        from . import workflow
        body = request.get_json(silent=True) or {}
        try:
            return jsonify(workflow.save_draft(pid, body.get("name", "Primary analysis"),
                                               body.get("spec") or {},
                                               body.get("expected_revision"))), 201
        except workflow.RevisionConflict as exc:
            return _error("revision_conflict", str(exc), 409)
        except ValueError as exc:
            return _error("invalid_draft", str(exc), 422)

    @bp.get("/projects/<pid>/hypothesis-families")
    def hypothesis_families(pid):
        from . import workflow
        return jsonify({"items": workflow.list_families(pid)})

    @bp.post("/projects/<pid>/hypothesis-families")
    def create_hypothesis_family(pid):
        from . import workflow
        body = request.get_json(silent=True) or {}
        try:
            return jsonify(workflow.create_family(
                pid, body.get("name", ""), body.get("alpha", config.get("alpha", .05)),
                body.get("correction", config.get("multiplicity_default", "holm")),
                body.get("members") or [], bool(body.get("freeze")))), 201
        except ValueError as exc:
            return _error("invalid_family", str(exc), 422)

    @bp.post("/projects/<pid>/report-snapshots")
    def create_report_snapshot(pid):
        from . import workflow
        body = request.get_json(silent=True) or {}
        try:
            return jsonify(workflow.create_report_snapshot(
                pid, body.get("title", ""), body.get("selection") or {},
                body.get("narrative", ""))), 201
        except ValueError as exc:
            return _error("invalid_selection", str(exc), 422)

    @bp.get("/projects/<pid>/search-executions")
    def search_executions(pid):
        from . import evidence
        if not _project(pid):
            return _error("not_found", "Project not found.", 404)
        return jsonify({"items": evidence.search_executions(pid)})

    @bp.get("/projects/<pid>/search-executions/<sid>/hits")
    def retrieval_hits(pid, sid):
        from . import evidence
        try:
            return jsonify({"items": evidence.retrieval_hits(pid, sid)})
        except KeyError as exc:
            return _error("not_found", str(exc), 404)

    @bp.post("/projects/<pid>/records/<rid>/report")
    def ensure_evidence_report(pid, rid):
        from . import evidence
        body = request.get_json(silent=True) or {}
        try:
            return jsonify(evidence.ensure_report(
                pid, rid, body.get("report_kind", "publication"))), 201
        except KeyError as exc:
            return _error("not_found", str(exc), 404)

    @bp.get("/projects/<pid>/studies")
    def list_studies(pid):
        from . import evidence
        if not _project(pid):
            return _error("not_found", "Project not found.", 404)
        return jsonify({"items": evidence.studies(pid)})

    @bp.post("/projects/<pid>/studies")
    def create_study(pid):
        from . import evidence
        if not _project(pid):
            return _error("not_found", "Project not found.", 404)
        body = request.get_json(silent=True) or {}
        try:
            return jsonify(evidence.create_study(
                pid, body.get("label", ""), body.get("report_ids") or [],
                body.get("relationship", "primary"))), 201
        except ValueError as exc:
            return _error("invalid_study", str(exc), 422)

    @bp.get("/projects/<pid>/screening-events")
    def screening_events(pid):
        if not _project(pid):
            return _error("not_found", "Project not found.", 404)
        clauses = ["project_id=?"]
        args = [pid]
        for query_name, column in (("record_id", "record_id"), ("stage", "stage"),
                                   ("reviewer", "reviewer")):
            value = request.args.get(query_name)
            if value:
                clauses.append(f"{column}=?")
                args.append(value)
        try:
            limit = max(1, min(int(request.args.get("limit", 200)), 1000))
        except ValueError:
            return _error("invalid_limit", "Limit must be an integer.", 422)
        rows = db.query("SELECT * FROM screening_event WHERE " + " AND ".join(clauses) +
                        " ORDER BY created_at DESC LIMIT ?", (*args, limit))
        return jsonify({"items": rows})

    @bp.get("/backups")
    def backups():
        from . import backup
        return jsonify({"items": backup.listing()})

    @bp.post("/backups")
    def create_backup():
        from . import backup
        try:
            return jsonify(backup.create()), 201
        except Exception as exc:
            return _error("backup_failed", f"{type(exc).__name__}: {exc}", 422)

    @bp.post("/backups/verify")
    def verify_backup():
        from . import backup
        body = request.get_json(silent=True) or {}
        path = os.path.realpath(str(body.get("path") or ""))
        root = os.path.realpath(config.BACKUP_DIR)
        if not path or os.path.commonpath([path, root]) != root:
            return _error("invalid_backup", "Backup must be inside LabDesk's backup directory.", 422)
        result = backup.verify(path)
        return jsonify(result), (200 if result["ok"] else 422)

    return bp
