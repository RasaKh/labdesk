"""HTTP surface: the app factory, shell routes, and config.

Every route takes a spec and returns JSON. The browser never sends code,
never sends SQL and never sends a command line; it sends the id of a
registry entry plus values for that entry's declared fields.
"""

import json
import os
from urllib.parse import urlparse

from flask import Flask, Response, jsonify, request

from . import (APP_NAME, APP_TAGLINE, APP_VERSION, analysis_guide, config, datasets, db,
               harvest, library, plots_registry, projects, reporting, screening,
               stats_registry)
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

    return app