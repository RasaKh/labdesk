"""HTTP surface: shell, datasets, and statistics.

Every route takes a spec and returns JSON. The browser never sends code,
never sends SQL and never sends a command line; it sends the id of a
registry entry plus values for that entry's declared fields.
"""

import json
import os
from urllib.parse import urlparse

from flask import Flask, Response, jsonify, request, send_file
from werkzeug.utils import secure_filename

from . import (APP_NAME, APP_TAGLINE, APP_VERSION, analysis_guide, config, datasets, db,
               harvest, library, plots_registry, projects, reporting, screening,
               plots_run, stats_registry, stats_run)
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

    def _record_in_scope(record_id, body=None):
        return db.one("SELECT * FROM record WHERE id=? AND project_id IS ?",
                      (record_id, scope(body)))

    def _figure_in_scope(fig_id, body=None):
        return db.one("SELECT * FROM figure WHERE id=? AND project_id IS ?",
                      (fig_id, scope(body)))

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

    # ── plots ────────────────────────────────────────────────────────────
    @app.post("/api/plot")
    def api_plot():
        body = request.json or {}
        run_id = body.get("run_id")
        result = body.get("result")
        if run_id:
            # A figure attached to a ledger run is rendered from that run's
            # immutable stored result/spec, never from a caller-supplied
            # replacement carrying the same run id.
            r = _run_in_scope(run_id, body)
            if not r:
                return jsonify({"error": "Run not found"}), 404
            result = json.loads(r["result"] or "{}")
            result["run_id"] = run_id
            result["project_id"] = r.get("project_id")
            spec = json.loads(r["spec"] or "{}")
        else:
            spec = body.get("spec") or {}
        if result is not None:
            result.setdefault("project_id", scope(body))
        data = _raw_for_plot(spec, result, body.get("plot"), body)
        try:
            path = plots_run.render(body.get("plot"), result, body.get("params") or {}, data)
        except NotImplementedError as exc:
            return jsonify({"error": str(exc), "not_implemented": True}), 501
        except Exception as exc:
            return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 400
        return jsonify({"path": path, "url": f"/api/figure?path={path}",
                        "name": os.path.basename(path)})

    def _raw_for_plot(spec, result, plot_id, body=None):
        """Attach the raw values a plot needs but a result dict does not carry."""
        try:
            ds_id = spec.get("dataset")
            if ds_id and not _dataset_in_scope(ds_id, body):
                return None
            df = datasets.load(ds_id) if ds_id else None
        except Exception:
            return None
        if df is None:
            return None
        roles = spec.get("roles") or {}

        def first(k):
            v = roles.get(k)
            return v[0] if isinstance(v, list) and v else v

        import pandas as pd
        dv, group = first("dv"), first("group")
        if dv and group and dv in df.columns and group in df.columns:
            out = {}
            for lvl, sub in df.groupby(group, dropna=True, observed=True):
                out[str(lvl)] = pd.to_numeric(sub[dv], errors="coerce").dropna().tolist()
            return out
        if plot_id in ("qq", "hist"):
            col = dv or first("vars") or (roles.get("vars") or [None])[0]
            if col and col in df.columns:
                return {"values": pd.to_numeric(df[col], errors="coerce").dropna().tolist(),
                        "label": col}
        if plot_id == "scatter_fit":
            vs = roles.get("vars") or []
            if len(vs) >= 2:
                pair = df[vs[:2]].apply(pd.to_numeric, errors="coerce").dropna()
                return {"x": pair[vs[0]].tolist(), "y": pair[vs[1]].tolist(),
                        "xlabel": vs[0], "ylabel": vs[1]}
        return None

    @app.get("/api/figure")
    def api_figure():
        p = request.args.get("path", "")
        if not _inside(p, config.FIG_DIR) or not os.path.isfile(p):
            return jsonify({"error": "Not found"}), 404
        if not db.one("SELECT id FROM figure WHERE path=? AND project_id IS ?", (p, scope())):
            return jsonify({"error": "Not found"}), 404
        return send_file(p)

    @app.get("/api/figures")
    def api_figures():
        rows = db.query("SELECT * FROM figure WHERE project_id IS ? "
                        "ORDER BY created_at DESC LIMIT 200", (scope(),))
        for r in rows:
            r["exists"] = bool(r.get("path") and os.path.exists(r["path"]))
        return jsonify(rows)

    @app.delete("/api/figures/<fig_id>")
    def del_fig(fig_id):
        f = _figure_in_scope(fig_id)
        if f:
            _unlink_fig(f)
            db.exec_("DELETE FROM figure WHERE id=?", (fig_id,))
        return jsonify({"ok": bool(f)})

    @app.post("/api/figures/clear")
    def clear_figs():
        project_id = scope()
        rows = db.query("SELECT * FROM figure WHERE project_id IS ?", (project_id,))
        for f in rows:
            _unlink_fig(f)
        db.exec_("DELETE FROM figure WHERE project_id IS ?", (project_id,))
        return jsonify({"ok": True, "deleted": len(rows)})


    # ── harvest ──────────────────────────────────────────────────────────
    @app.post("/api/harvest")
    def api_harvest():
        body = request.json or {}
        sid = body.get("source")
        entry = harvest.REGISTRY.get(sid)
        if not entry:
            return jsonify({"error": f"Unknown source {sid!r}"}), 400
        params = body.get("params") or {}
        pid = scope(body)
        job = JOBS.submit("harvest", f"{entry['label']} search",
                          lambda ctl: harvest.harvest(sid, params, pid, ctl), body,
                          project_id=pid)
        return jsonify({"job": job.id, "queued": True})

    @app.get("/api/records")
    def api_records():
        pid = scope()
        q = request.args.get("q", "")
        sql = ("SELECT id, source, doi, title, authors, journal, year, retracted, oa_url, "
               "dedup_of FROM record WHERE project_id IS ?")
        args = [pid]
        if q:
            sql += " AND (title LIKE ? OR abstract LIKE ?)"
            args += [f"%{q}%", f"%{q}%"]
        sql += " ORDER BY year DESC LIMIT 500"
        return jsonify(db.query(sql, tuple(args)))

    @app.post("/api/dedup")
    def api_dedup():
        pid = scope(request.json or {})
        job = JOBS.submit("dedup", "Deduplicating corpus",
                          lambda ctl: screening.deduplicate(pid, ctl=ctl),
                          project_id=pid)
        return jsonify({"job": job.id, "queued": True})

    @app.post("/api/records/preview")
    def records_preview():
        """Count what a trim would remove before it removes it. Narrowing a
        search after the fact is normal; doing it blind is not."""
        where, args = _record_filter(request.json or {})
        n = db.one(f"SELECT COUNT(*) c FROM record WHERE {where}", tuple(args))
        sample = db.query(f"SELECT title, year, source, doi FROM record WHERE {where} "
                          "ORDER BY year DESC LIMIT 12", tuple(args))
        total = db.one("SELECT COUNT(*) c FROM record WHERE project_id IS ?", (scope(request.json or {}),))
        return jsonify({"matched": n["c"] if n else 0,
                        "total": total["c"] if total else 0,
                        "remaining": (total["c"] - n["c"]) if (total and n) else 0,
                        "sample": sample})

    @app.post("/api/records/delete")
    def records_delete():
        where, args = _record_filter(request.json or {})
        n = db.one(f"SELECT COUNT(*) c FROM record WHERE {where}", tuple(args))
        # Screening decisions, extractions and risk-of-bias rows cascade with
        # the record, so a trim cannot leave orphaned judgements behind.
        db.exec_(f"DELETE FROM record WHERE {where}", tuple(args))
        return jsonify({"ok": True, "deleted": n["c"] if n else 0})

    @app.delete("/api/records/<rec_id>")
    def del_record(rec_id):
        rec = _record_in_scope(rec_id)
        if not rec:
            return jsonify({"error": "Not found"}), 404
        db.exec_("DELETE FROM record WHERE id=? AND project_id IS ?", (rec_id, scope()))
        return jsonify({"ok": True})

    def _record_filter(b):
        """Build a WHERE clause from the trim controls. Anything left blank is
        simply not applied, so an empty filter matches everything and the
        preview will say so loudly."""
        clauses, args = [], []
        # Always project-scoped. A trim in one project must never be able to
        # reach into another's corpus.
        clauses.append("project_id IS ?")
        args.append(b["project"] if b.get("project") is not None else active_project())
        if b.get("ids"):
            marks = ",".join("?" for _ in b["ids"])
            clauses.append(f"id IN ({marks})"); args += list(b["ids"])
        if b.get("source"):
            clauses.append("source = ?"); args.append(b["source"])
        if b.get("query"):
            clauses.append("(title LIKE ? OR abstract LIKE ?)")
            args += [f"%{b['query']}%"] * 2
        if b.get("not_query"):
            clauses.append("(COALESCE(title,'') NOT LIKE ? AND COALESCE(abstract,'') NOT LIKE ?)")
            args += [f"%{b['not_query']}%"] * 2
        if b.get("year_before"):
            clauses.append("(year IS NULL OR year < ?)"); args.append(int(b["year_before"]))
        if b.get("year_after"):
            clauses.append("year > ?"); args.append(int(b["year_after"]))
        if b.get("no_abstract"):
            clauses.append("(abstract IS NULL OR abstract = '')")
        if b.get("retracted"):
            clauses.append("retracted > 0")
        if b.get("duplicates"):
            clauses.append("dedup_of IS NOT NULL")
        if b.get("unscreened"):
            clauses.append("id NOT IN (SELECT record_id FROM screen)")
        if b.get("excluded"):
            clauses.append("id IN (SELECT record_id FROM screen WHERE decision='exclude')")
        return (" AND ".join(clauses) if clauses else "1=1"), args

    # ── screening ────────────────────────────────────────────────────────
    @app.get("/api/screen/queue")
    def api_queue():
        return jsonify(screening.queue(
            scope(),
            request.args.get("stage", "title_abstract"),
            request.args.get("reviewer"),
            int(request.args.get("limit", 50)),
            blind=request.args.get("blind", "1") != "0"))

    @app.post("/api/screen/decide")
    def api_decide():
        b = request.json or {}
        if not _record_in_scope(b.get("record_id"), b):
            return jsonify({"error": "Record not found in this project."}), 404
        return jsonify(screening.decide(b["record_id"], b["decision"],
                                        b.get("stage", "title_abstract"),
                                        b.get("reviewer"), b.get("reason")))

    @app.post("/api/screen/undo")
    def api_undo():
        """Remove the most recent decision by this reviewer at this stage, so
        a mis-keyed include is genuinely retractable rather than just scrolled
        past."""
        b = request.json or {}
        row = screening.undo_latest(scope(b), b.get("stage", "title_abstract"),
                                    b.get("reviewer"))
        if not row:
            return jsonify({"ok": False, "message": "Nothing to undo at this stage."})
        return jsonify({"ok": True, "undone": row["decision"], "title": row["title"],
                        "record_id": row["record_id"]})

    @app.post("/api/screen/reset")
    def api_screen_reset():
        """Scope: stage | reviewer | all. Records are untouched; only the
        judgements go, so the corpus survives a restart of the screen."""
        b = request.json or {}
        reset_scope = b.get("scope", "stage")
        project_id = scope(b)
        base = "record_id IN (SELECT id FROM record WHERE project_id IS ?)"
        args = [project_id]
        if reset_scope == "all":
            where = base
        elif reset_scope == "reviewer":
            where = base + " AND reviewer=?"; args.append(b.get("reviewer"))
        else:
            where = base + " AND stage=? AND reviewer=?"
            args += [b.get("stage", "title_abstract"), b.get("reviewer")]
        n = db.one(f"SELECT COUNT(*) c FROM screen WHERE {where}", tuple(args))
        db.exec_(f"DELETE FROM screen WHERE {where}", tuple(args))
        return jsonify({"ok": True, "deleted": n["c"] if n else 0,
                        "note": "Records kept. Only the decisions were cleared."})

    @app.delete("/api/screen/<record_id>")
    def api_unscreen(record_id):
        if not _record_in_scope(record_id):
            return jsonify({"error": "Not found"}), 404
        db.exec_("DELETE FROM screen WHERE record_id=?", (record_id,))
        return jsonify({"ok": True})

    @app.delete("/api/extraction/<record_id>")
    def api_del_extraction(record_id):
        if not _record_in_scope(record_id):
            return jsonify({"error": "Not found"}), 404
        db.exec_("DELETE FROM extraction WHERE record_id=?", (record_id,))
        return jsonify({"ok": True})

    @app.delete("/api/rob/<record_id>")
    def api_del_rob(record_id):
        if not _record_in_scope(record_id):
            return jsonify({"error": "Not found"}), 404
        db.exec_("DELETE FROM rob WHERE record_id=?", (record_id,))
        return jsonify({"ok": True})

    @app.get("/api/screen/agreement")
    def api_agreement():
        return jsonify(screening.agreement(scope(),
                                           request.args.get("stage", "title_abstract"),
                                           request.args.get("a"), request.args.get("b")))

    @app.get("/api/screen/prisma")
    def api_prisma():
        return jsonify(screening.prisma_counts(scope()))

    @app.post("/api/extraction")
    def api_extract():
        b = request.json or {}
        if not _record_in_scope(b.get("record_id"), b):
            return jsonify({"error": "Record not found in this project."}), 404
        return jsonify(screening.save_extraction(b["record_id"], b["form_id"],
                                                 b.get("payload") or {}))

    @app.get("/api/extraction")
    def api_extract_table():
        return jsonify(screening.extraction_table(request.args.get("form", "rct"),
                                                  scope()))

    @app.get("/api/extraction/meta")
    def api_extract_meta():
        return jsonify(screening.to_meta_frame(request.args.get("form", "rct"),
                                               scope(),
                                               request.args.get("measure", "SMD")))

    @app.post("/api/rob")
    def api_rob():
        b = request.json or {}
        if not _record_in_scope(b.get("record_id"), b):
            return jsonify({"error": "Record not found in this project."}), 404
        return jsonify(screening.set_rob(b["record_id"], b["instrument"],
                                         b.get("domains") or {}, b.get("overall")))

    @app.get("/api/rob")
    def api_rob_summary():
        return jsonify(screening.rob_summary(request.args.get("instrument", "rob2"),
                                             scope()))


    # ── projects ─────────────────────────────────────────────────────────
    @app.get("/api/projects")
    def api_projects():
        return jsonify({
            "projects": projects.listing(
                include_archived=request.args.get("archived") == "1"),
            "active": active_project(),
            "kinds": projects.KINDS,
            "unfiled": projects.unfiled(),
        })

    @app.post("/api/projects")
    def api_create_project():
        b = request.json or {}
        p = projects.create(b.get("name", ""), b.get("kind", "review"),
                            b.get("question", ""), b.get("registered", ""),
                            b.get("notes", ""))
        if b.get("activate", True):
            config.update({"active_project": p["id"]})
        if b.get("adopt_unfiled"):
            projects.adopt_unfiled(p["id"])
        return jsonify(p)

    @app.get("/api/projects/<pid>")
    def api_project(pid):
        p = projects.get(pid)
        if not p:
            return jsonify({"error": "Not found"}), 404
        p["progress"] = projects.progress(pid)
        p["counts"] = projects.counts(pid)
        p["timeline"] = projects.timeline(pid)
        return jsonify(p)

    @app.patch("/api/projects/<pid>")
    def api_update_project(pid):
        return jsonify(projects.update(pid, request.json or {}))

    @app.post("/api/projects/<pid>/activate")
    def api_activate(pid):
        if not projects.get(pid):
            return jsonify({"error": "Not found"}), 404
        config.update({"active_project": pid})
        return jsonify({"ok": True, "active": pid})

    @app.post("/api/projects/<pid>/stage")
    def api_stage(pid):
        b = request.json or {}
        projects.set_stage_note(pid, b["stage"], b.get("note"), b.get("done"))
        return jsonify(projects.progress(pid))

    @app.post("/api/projects/<pid>/adopt")
    def api_adopt(pid):
        b = request.json or {}
        return jsonify(projects.adopt_unfiled(
            pid, b.get("what") or ("records", "datasets", "runs", "figures")))

    @app.delete("/api/projects/<pid>")
    def api_del_project(pid):
        purge = request.args.get("purge") != "0"
        res = projects.delete(pid, purge=purge)
        if config.get("active_project") == pid:
            config.update({"active_project": None})
        return jsonify(res)

    # ── library ──────────────────────────────────────────────────────────
    @app.get("/api/library")
    def api_library():
        return jsonify({"sections": library.grouped(),
                        "count": len(library.ENTRIES)})

    @app.get("/api/library/<entry_id>")
    def api_library_entry(entry_id):
        e = library.get(entry_id)
        return jsonify(e) if e else (jsonify({"error": "Not found"}), 404)

    @app.get("/api/library/search")
    def api_library_search():
        return jsonify(library.search(request.args.get("q", "")))

    # ── reviewers ────────────────────────────────────────────────────────
    @app.get("/api/reviewers")
    def api_reviewers():
        return jsonify(screening.reviewers(scope()))

    @app.post("/api/reviewers")
    def api_add_reviewer():
        b = request.json or {}
        if b.get("id"):
            return jsonify(screening.rename_reviewer(b["id"], b.get("name", "")))
        return jsonify(screening.add_reviewer(b.get("name", ""), b.get("role", "screener")))

    @app.delete("/api/reviewers/<rid>")
    def api_del_reviewer(rid):
        keep = request.args.get("decisions") != "0"
        return jsonify(screening.remove_reviewer(rid, keep_decisions=keep))

    @app.post("/api/screen/resolve")
    def api_resolve():
        b = request.json or {}
        if not _record_in_scope(b.get("record_id"), b):
            return jsonify({"error": "Record not found in this project."}), 404
        return jsonify(screening.resolve(b["record_id"], b.get("stage", "title_abstract"),
                                         b["decision"], b.get("rationale", ""),
                                         b.get("by")))

    # ── reporting ────────────────────────────────────────────────────────
    @app.post("/api/report/sentence")
    def api_sentence():
        b = request.json or {}
        return jsonify({"text": reporting.sentence(b.get("result") or {}, b.get("style"))})

    @app.get("/api/report/methods")
    def api_methods():
        return jsonify(reporting.methods_paragraph(request.args.get("sha"),
                                                   project_id=scope()))

    @app.get("/api/report/checklist/<kind>")
    def api_checklist(kind):
        try:
            return jsonify(reporting.checklist(kind))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 404

    @app.post("/api/report/bundle")
    def api_bundle():
        b = request.json or {}
        try:
            return jsonify(reporting.bundle(b.get("dataset"), b.get("include_data", True),
                                            project_id=scope(b)))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    @app.post("/api/report/prereg")
    def api_prereg():
        b = request.json or {}
        return jsonify(reporting.prereg_draft(b.get("question", ""),
                                              b.get("outcomes", ""),
                                              b.get("hypotheses", "")))

    @app.get("/api/download")
    def api_download():
        p = request.args.get("path", "")
        if not (_inside(p, config.EXPORT_DIR) or _inside(p, config.FIG_DIR)) \
                or not os.path.isfile(p):
            return jsonify({"error": "Not found"}), 404
        return send_file(p, as_attachment=True)


    # ── wholesale clearing ───────────────────────────────────────────────
    #
    # Everything above deletes one thing. This deletes a whole category, and
    # is deliberately the only place that can. Each scope reports what it would
    # remove before it removes it, so nothing here is a one-click surprise.

    RESET_SCOPES = {
        "cache":     ("Harvest cache", "Cached API responses. Safe: they refetch."),
        "figures":   ("Figures", "Rendered images on disk and their records."),
        "runs":      ("Run ledger", "Every analysis result and the multiplicity audit."),
        "screening": ("Screening decisions", "Include/exclude judgements. Records kept."),
        "extraction":("Extractions and risk of bias", "Extracted data and RoB judgements."),
        "corpus":    ("Corpus", "All harvested records, and everything attached to them."),
        "datasets":  ("Datasets", "Imported data files. Runs are kept."),
        "everything":("Everything", "Full reset back to a first launch."),
    }

    @app.get("/api/reset/scopes")
    def reset_scopes():
        out = []
        for key, (label, desc) in RESET_SCOPES.items():
            out.append({"id": key, "label": label, "description": desc,
                        "count": _reset_count(key)})
        return jsonify(out)

    def _reset_count(scope):
        # Project-local. Clearing the corpus in one project must not touch
        # another's, which is the whole point of projects existing.
        pid = active_project()
        one = lambda q, a=(): (db.one(q, a) or {}).get("c", 0)
        if scope == "figures":
            return one("SELECT COUNT(*) c FROM figure WHERE project_id IS ?", (pid,))
        if scope == "runs":
            return one("SELECT COUNT(*) c FROM analysis_run WHERE project_id IS ?", (pid,))
        if scope == "screening":
            return one("SELECT COUNT(*) c FROM screen s JOIN record r "
                       "ON r.id = s.record_id WHERE r.project_id IS ?", (pid,))
        if scope == "extraction":
            return (one("SELECT COUNT(*) c FROM extraction e JOIN record r "
                        "ON r.id = e.record_id WHERE r.project_id IS ?", (pid,))
                    + one("SELECT COUNT(*) c FROM rob rb JOIN record r "
                          "ON r.id = rb.record_id WHERE r.project_id IS ?", (pid,)))
        if scope == "corpus":
            return one("SELECT COUNT(*) c FROM record WHERE project_id IS ?", (pid,))
        if scope == "datasets":
            return one("SELECT COUNT(*) c FROM dataset WHERE project_id IS ?", (pid,))
        if scope == "cache":
            try:
                return len(os.listdir(config.CACHE_DIR))
            except OSError:
                return 0
        if scope == "everything":
            return sum(_reset_count(k) for k in RESET_SCOPES if k != "everything")
        return 0

    @app.post("/api/reset")
    def do_reset():
        b = request.json or {}
        scope = b.get("scope")
        if scope not in RESET_SCOPES:
            return jsonify({"error": f"Unknown scope {scope!r}."}), 400
        if b.get("confirm") is not True:
            return jsonify({"error": "This needs an explicit confirmation.",
                            "would_delete": _reset_count(scope)}), 400
        n = _reset_count(scope)
        targets = [scope] if scope != "everything" else \
            [k for k in RESET_SCOPES if k != "everything"]
        pid = active_project()

        # Gather paths before changing the ledger. Filesystem deletion cannot
        # participate in SQLite's transaction, so database state is committed
        # atomically first and best-effort file cleanup follows.
        figure_files = []
        dataset_files = []
        if "figures" in targets:
            figure_files = [f.get("path") for f in
                            db.query("SELECT path FROM figure WHERE project_id IS ?", (pid,))
                            if f.get("path")]
        if "datasets" in targets:
            dataset_files = [d.get("path") for d in
                             db.query("SELECT path FROM dataset WHERE project_id IS ?", (pid,))
                             if d.get("path")]

        with db.transaction():
            for t in targets:
                if t == "figures":
                    db.exec_("DELETE FROM figure WHERE project_id IS ?", (pid,))
                elif t == "runs":
                    db.exec_("DELETE FROM analysis_run WHERE project_id IS ?", (pid,))
                elif t == "screening":
                    db.exec_("DELETE FROM resolution WHERE record_id IN "
                             "(SELECT id FROM record WHERE project_id IS ?)", (pid,))
                    db.exec_("DELETE FROM screen WHERE record_id IN "
                             "(SELECT id FROM record WHERE project_id IS ?)", (pid,))
                elif t == "extraction":
                    db.exec_("DELETE FROM extraction WHERE record_id IN "
                             "(SELECT id FROM record WHERE project_id IS ?)", (pid,))
                    db.exec_("DELETE FROM rob WHERE record_id IN "
                             "(SELECT id FROM record WHERE project_id IS ?)", (pid,))
                elif t == "corpus":
                    db.exec_("DELETE FROM record WHERE project_id IS ?", (pid,))
                    db.exec_("DELETE FROM harvest_query WHERE project_id IS ?", (pid,))
                elif t == "datasets":
                    db.exec_("DELETE FROM dataset_op WHERE dataset_id IN "
                             "(SELECT id FROM dataset WHERE project_id IS ?)", (pid,))
                    db.exec_("DELETE FROM dataset WHERE project_id IS ?", (pid,))

        if "figures" in targets:
            for path in figure_files:
                try:
                    if path and os.path.exists(path):
                        os.remove(path)
                except OSError:
                    pass
        if "datasets" in targets:
            datasets._cache.clear()
            for path in dataset_files:
                try:
                    if path and os.path.exists(path):
                        os.remove(path)
                except OSError:
                    pass
        if "cache" in targets:
            try:
                names = os.listdir(config.CACHE_DIR)
            except OSError:
                names = []
            for name in names:
                try:
                    path = os.path.join(config.CACHE_DIR, name)
                    if os.path.isfile(path):
                        os.remove(path)
                except OSError:
                    pass
        return jsonify({"ok": True, "scope": scope, "deleted": n})


    return app
