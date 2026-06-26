"""HTTP surface: shell, datasets, and statistics.

Every route takes a spec and returns JSON. The browser never sends code,
never sends SQL and never sends a command line; it sends the id of a
registry entry plus values for that entry's declared fields.
"""

import json
import os
from urllib.parse import urlparse

from flask import Flask, Response, jsonify, request
from werkzeug.utils import secure_filename

from . import (APP_NAME, APP_TAGLINE, APP_VERSION, analysis_guide, config, datasets, db,
               harvest, library, plots_registry, projects, reporting, screening,
               stats_registry, stats_run)
from .jobs import JOBS

_PROXY_HEADERS = ("X-Forwarded-For", "X-Real-IP", "Forwarded", "CF-Connecting-IP")


def create_app():
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 250 * 1024 * 1024
    db.init()
    JOBS.recover_interrupted()
    from .api_v1 import create_blueprint
    app.register_blueprint(create_blueprint())

    @app.before_request
    def same_origin_mutations():
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            origin = request.headers.get("Origin")
            if origin:
                parsed = urlparse(origin)
                if parsed.netloc != request.host:
                    return jsonify({"error": "Cross-origin mutation rejected."}), 403

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; connect-src 'self'",
        )
        return response

    def active_project():
        """The project everything is scoped to. Stored in config so it
        survives a restart. Returns None when nothing is selected, which is
        the unfiled bucket rather than "everything"."""
        pid = config.get("active_project")
        if pid and not projects.get(pid):
            # The project was deleted out from under the setting.
            config.update({"active_project": None})
            return None
        return pid

    def scope(body=None):
        """A request may name a project explicitly; otherwise the active one
        applies. Explicit wins so a job queued against one project cannot be
        rerouted by switching in another tab mid-run."""
        if body and body.get("project") is not None:
            return body["project"]
        q = request.args.get("project")
        return q if q is not None else active_project()

    def _public_config():
        # API credentials are write-only from the browser.  LabDesk may be
        # deliberately bound to a LAN address, and bootstrap data must not turn
        # that into a credential-disclosure endpoint.
        out = dict(config.CONFIG)
        for key in ("ncbi_api_key", "semantic_scholar_key"):
            if key in out:
                out[key] = ""
        return out

    def _dataset_in_scope(ds_id, body=None):
        m = datasets.meta(ds_id)
        return m if m and m.get("project_id") == scope(body) else None

    def _run_in_scope(run_id, body=None):
        return db.one("SELECT * FROM analysis_run WHERE id=? AND project_id IS ?",
                      (run_id, scope(body)))

    def _inside(path, root):
        try:
            path = os.path.realpath(path)
            root = os.path.realpath(root)
            return os.path.commonpath([path, root]) == root
        except (OSError, ValueError):
            return False

    def _loopback_request():
        """True only for a browser on this machine talking to us directly.
        Behind a reverse proxy every request arrives from 127.0.0.1, so a
        forwarding header means the real client is somewhere else."""
        if any(request.headers.get(h) for h in _PROXY_HEADERS):
            return False
        return request.remote_addr in ("127.0.0.1", "::1", None)

    # ── shell ────────────────────────────────────────────────────────────
    @app.get("/")
    def index():
        from .ui.html import page
        return Response(page(), mimetype="text/html")

    @app.get("/api/bootstrap")
    def bootstrap():
        """Everything the client needs to build itself."""
        return jsonify({
            "app": {"name": APP_NAME, "version": APP_VERSION, "tagline": APP_TAGLINE},
            "config": _public_config(),
            "defaults": config.DEFAULT_CONFIG,
            "deps": config.dependency_report(),
            "tests": {"groups": stats_registry.GROUPS, "entries": stats_registry.REGISTRY,
                      "goals": analysis_guide.public_goals()},
            "plots": {"groups": plots_registry.GROUPS, "entries": plots_registry.REGISTRY,
                      "common": plots_registry.COMMON,
                      "presets": plots_registry.JOURNAL_PRESETS,
                      "palettes": plots_registry.PALETTES},
            "sources": {"groups": harvest.GROUPS, "entries": harvest.REGISTRY},
            "instruments": screening.INSTRUMENTS,
            "forms": {k: {"label": v["label"], "fields": v["fields"]}
                      for k, v in screening.DEFAULT_FORMS.items()},
            "checklists": {k: v["label"] for k, v in reporting.CHECKLISTS.items()},
            "exclusion_reasons": screening.EXCLUSION_REASONS,
            "library": library.grouped(),
            "projects": projects.listing(),
            "active_project": active_project(),
            "project_kinds": projects.KINDS,
            "reset_scopes": [{"id": k, "label": v[0], "description": v[1]}
                             for k, v in RESET_SCOPES.items()],
            "transforms": datasets.TRANSFORMS,
            "outlier_methods": datasets.OUTLIER_METHODS,
            "counts": {"tests_ready": stats_registry.ready_count(),
                       "tests_total": len(stats_registry.TESTS),
                       "plots_total": len(plots_registry.PLOTS),
                       "sources_total": len(harvest.SOURCES)},
        })

    @app.post("/api/config")
    def set_config():
        try:
            return jsonify(config.public(config.update(request.json or {})))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    # ── datasets ─────────────────────────────────────────────────────────
    @app.get("/api/datasets")
    def list_ds():
        return jsonify(datasets.list_datasets(scope()))

    @app.post("/api/datasets/upload")
    def upload_ds():
        f = request.files.get("file")
        if not f:
            return jsonify({"error": "No file received."}), 400
        original = f.filename or "upload.csv"
        safe = secure_filename(original) or "upload.csv"
        tmp = os.path.join(config.TMP_DIR, f"{db.new_id('up_')}_{safe}")
        f.save(tmp)
        try:
            project_id = request.form.get("project") or active_project()
            ds_id = datasets.import_file(tmp, name=original, source=original,
                                         project_id=project_id)
        except Exception as exc:
            return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 400
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass
        return jsonify(datasets.meta(ds_id))

    @app.post("/api/datasets/path")
    def path_ds():
        if not _loopback_request():
            return jsonify({"error": "Server-side path import is available only from localhost; upload the file instead."}), 403
        p = (request.json or {}).get("path", "")
        if not os.path.exists(p):
            return jsonify({"error": f"No file at {p}"}), 400
        try:
            return jsonify(datasets.meta(
                datasets.import_file(p, project_id=active_project())))
        except Exception as exc:
            return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 400

    @app.get("/api/datasets/<ds_id>")
    def get_ds(ds_id):
        m = _dataset_in_scope(ds_id)
        if not m:
            return jsonify({"error": "Not found"}), 404
        df = datasets.load(ds_id)
        m["preview"] = json.loads(df.head(200).to_json(orient="records", date_format="iso"))
        return jsonify(m)

    @app.post("/api/datasets/<ds_id>/dictionary")
    def set_dict(ds_id):
        if not _dataset_in_scope(ds_id):
            return jsonify({"error": "Not found"}), 404
        return jsonify(datasets.set_dictionary(ds_id, request.json or {}))

    @app.get("/api/datasets/<ds_id>/missing")
    def ds_missing(ds_id):
        if not _dataset_in_scope(ds_id):
            return jsonify({"error": "Not found"}), 404
        return jsonify(datasets.missingness(ds_id))

    @app.post("/api/datasets/<ds_id>/deident")
    def ds_deident(ds_id):
        if not _dataset_in_scope(ds_id):
            return jsonify({"error": "Not found"}), 404
        qi = (request.json or {}).get("quasi_identifiers") or []
        return jsonify(datasets.deident_check(ds_id, qi))

    @app.delete("/api/datasets/<ds_id>")
    def del_ds(ds_id):
        """Remove a dataset. Its runs are kept unless asked for, because the
        ledger is evidence: deleting the data should not silently erase the
        record that the analyses happened."""
        also_runs = request.args.get("runs") == "1"
        m = _dataset_in_scope(ds_id)
        if not m:
            return jsonify({"error": "Not found"}), 404
        n_runs = db.runs_on_dataset(m["sha256"], m.get("project_id"))
        if m and m.get("path") and os.path.exists(m["path"]):
            try:
                os.remove(m["path"])
            except OSError:
                pass
        datasets._cache.pop(ds_id, None)
        db.exec_("DELETE FROM dataset_op WHERE dataset_id=?", (ds_id,))
        db.exec_("DELETE FROM dataset WHERE id=?", (ds_id,))
        if also_runs and m:
            db.exec_("DELETE FROM analysis_run WHERE dataset_id=? AND project_id IS ?",
                     (ds_id, m.get("project_id")))
        return jsonify({"ok": True, "runs_kept": 0 if also_runs else n_runs,
                        "runs_deleted": n_runs if also_runs else 0})

    # ── statistics ───────────────────────────────────────────────────────
    @app.post("/api/analysis/compatible")
    def api_analysis_compatible():
        """Deterministically match the reviewed dictionary to method roles.

        This endpoint never chooses a test. It only reports which READY
        registry entries can be structurally populated from the active
        dataset, optionally constrained by researcher-selected anchor columns.
        """
        body = request.json or {}
        ds_id = body.get("dataset")
        m = _dataset_in_scope(ds_id, body) if ds_id else None
        if not m:
            return jsonify({"error": "Choose a dataset in this project first."}), 400
        try:
            return jsonify(analysis_guide.compatible_methods(
                m.get("dictionary") or {},
                goal_id=body.get("goal") or "compare",
                primary=body.get("primary") or None,
                secondary=body.get("secondary") or None,
                limit=body.get("limit", 12),
            ))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    @app.post("/api/preflight")
    def api_preflight():
        try:
            spec = request.json or {}
            spec.setdefault("project", active_project())
            return jsonify(stats_run.preflight(spec))
        except Exception as exc:
            return jsonify({"ok": False, "errors": [f"{type(exc).__name__}: {exc}"]}), 400

    @app.post("/api/run")
    def api_run():
        spec = request.json or {}
        spec.setdefault("project", active_project())
        heavy = spec.get("test") in ("permutation_two", "bootstrap_diff", "power_sim",
                                     "classifier_eval", "network_meta")
        if heavy or spec.get("as_job"):
            entry = stats_registry.get(spec.get("test")) or {}
            job = JOBS.submit("analysis", entry.get("label", spec.get("test", "Analysis")),
                              lambda ctl: stats_run.run(spec, ctl), spec)
            return jsonify({"job": job.id, "queued": True})
        try:
            return jsonify(stats_run.run(spec))
        except stats_run.NotImplementedRunner as exc:
            return jsonify({"ok": False, "not_implemented": True,
                            "errors": [str(exc)]}), 501
        except Exception as exc:
            return jsonify({"ok": False, "errors": [f"{type(exc).__name__}: {exc}"]}), 400

    @app.get("/api/runs")
    def api_runs():
        rows = db.query("SELECT id, test_id, status, created_at, duration_ms, note, "
                        "dataset_id, dataset_sha FROM analysis_run "
                        "WHERE project_id IS ? ORDER BY created_at DESC LIMIT 300",
                        (scope(),))
        return jsonify(rows)

    @app.get("/api/runs/<run_id>")
    def api_run_detail(run_id):
        r = _run_in_scope(run_id)
        if not r:
            return jsonify({"error": "Not found"}), 404
        for k in ("spec", "result", "assumptions", "versions"):
            try:
                r[k] = json.loads(r[k] or "null")
            except Exception:
                pass
        return jsonify(r)

    @app.delete("/api/runs/<run_id>")
    def del_run(run_id):
        """Delete one entry from the provenance ledger, and every figure that
        was drawn from it. The count of what went is returned so the interface
        can say what it did rather than just going quiet."""
        r = _run_in_scope(run_id)
        if not r:
            return jsonify({"error": "Not found"}), 404
        figs = db.query("SELECT * FROM figure WHERE run_id=? AND project_id IS ?",
                        (run_id, scope()))
        for f in figs:
            _unlink_fig(f)
        db.exec_("DELETE FROM figure WHERE run_id=? AND project_id IS ?", (run_id, scope()))
        db.exec_("DELETE FROM analysis_run WHERE id=? AND project_id IS ?", (run_id, scope()))
        return jsonify({"ok": True, "figures_deleted": len(figs)})

    @app.post("/api/runs/clear")
    def clear_runs():
        """Scope: all | dataset | failed | blocked | before. Clearing the whole
        ledger resets the multiplicity audit, so the response says so."""
        b = request.json or {}
        clear_scope = b.get("scope", "all")
        project_id = scope(b)
        where, args = "project_id IS ?", [project_id]
        if clear_scope == "dataset" and b.get("dataset"):
            m = _dataset_in_scope(b["dataset"], b)
            where, args = "project_id IS ? AND dataset_id=?", [project_id, b["dataset"] if m else ""]
        elif clear_scope == "failed":
            where += " AND status='failed'"
        elif clear_scope == "blocked":
            where += " AND status='blocked'"
        elif clear_scope == "before" and b.get("before"):
            where += " AND created_at < ?"; args.append(float(b["before"]))
        ids = [r["id"] for r in db.query(f"SELECT id FROM analysis_run WHERE {where}",
                                         tuple(args))]
        for f in db.query("SELECT * FROM figure WHERE project_id IS ?", (args[0],)):
            if f["run_id"] in ids:
                _unlink_fig(f)
                db.exec_("DELETE FROM figure WHERE id=?", (f["id"],))
        db.exec_(f"DELETE FROM analysis_run WHERE {where}", tuple(args))
        return jsonify({"ok": True, "deleted": len(ids), "scope": clear_scope,
                        "note": ("The multiplicity audit now counts from zero. "
                                 "That is the point of clearing it, but it also means "
                                 "the tests you ran before this are no longer recorded."
                                 if clear_scope == "all" else None)})

    def _unlink_fig(f):
        if f.get("path") and os.path.exists(f["path"]):
            try:
                os.remove(f["path"])
            except OSError:
                pass

    return app