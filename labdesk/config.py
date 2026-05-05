"""Paths, persisted configuration, and optional-dependency probing.

Mirrors TubeForge's config module. The dependency report is the direct
analogue of `dependency_report()` there: instead of asking whether ffmpeg
exists, it asks whether statsmodels exists, and the answer gates which
entries in the test registry are runnable.
"""

import importlib
import json
import os
import tempfile
import threading
import contextvars
from contextlib import contextmanager

HOME = os.path.expanduser("~")
CONF_DIR = os.path.join(
    os.environ.get("XDG_CONFIG_HOME", os.path.join(HOME, ".config")), "labdesk"
)
DATA_DIR = os.path.join(CONF_DIR, "data")
FIG_DIR = os.path.join(CONF_DIR, "figures")
EXPORT_DIR = os.path.join(CONF_DIR, "exports")
BACKUP_DIR = os.path.join(CONF_DIR, "backups")
CACHE_DIR = os.path.join(CONF_DIR, "cache")
DB_PATH = os.path.join(CONF_DIR, "labdesk.db")
CONF_PATH = os.path.join(CONF_DIR, "config.json")
TMP_DIR = os.path.join(tempfile.gettempdir(), "labdesk")

for _d in (CONF_DIR, DATA_DIR, FIG_DIR, EXPORT_DIR, BACKUP_DIR, CACHE_DIR, TMP_DIR):
    os.makedirs(_d, exist_ok=True)


DEFAULT_CONFIG = {
    "alpha": 0.05,
    "ci_level": 0.95,
    "decimals": 3,
    "p_decimals": 4,
    "p_min_display": 0.001,
    "exact_p_in_plots": False,
    "star_thresholds": [[0.001, "***"], [0.01, "**"], [0.05, "*"]],
    "ns_label": "ns",
    "multiplicity_default": "holm",
    "error_bar_default": "ci95",
    "assumption_policy": "warn",
    "seed": 20260804,
    "citation_style": "vancouver",
    "stats_report_style": "apa",
    "software_footer": True,
    "fig_dpi": 300,
    "fig_format": "png",
    "fig_width_mm": 89,
    "palette": "okabe_ito",
    "greyscale_check": True,
    "ncbi_api_key": "",
    "ncbi_email": "",
    "semantic_scholar_key": "",
    "harvest_cache_hours": 24,
    "harvest_rate_limit": 3,
    "max_concurrent_jobs": 2,
    "keep_job_history": 500,
    "backup_keep": 5,
    "theme": "daylight",
    "typeface": "site",
    "ui_scale": 110,
    "config_version": 3,
    "confirm_destructive": True,
    "provenance_strict": True,
    "multiplicity_nag_after": 10,
}

_lock = threading.RLock()
_execution_overrides = contextvars.ContextVar("labdesk_execution_overrides", default=None)


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(CONF_PATH, "r", encoding="utf-8") as fh:
            cfg.update(json.load(fh))
    except Exception:
        pass
    return cfg


def save_config(cfg):
    with _lock:
        tmp = CONF_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2)
        os.replace(tmp, CONF_PATH)


CONFIG_VERSION = 3
APPEARANCE_KEYS = ("theme", "typeface", "ui_scale")


def _stored_version():
    """Read the version from the file rather than the merged dict."""
    try:
        with open(CONF_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh).get("config_version")
    except Exception:
        return CONFIG_VERSION


def _migrate(cfg):
    if _stored_version() == CONFIG_VERSION:
        return cfg
    for k in APPEARANCE_KEYS:
        cfg[k] = DEFAULT_CONFIG[k]
    cfg.pop("accent", None)
    cfg.pop("font_scale", None)
    cfg["config_version"] = CONFIG_VERSION
    save_config(cfg)
    return cfg


CONFIG = _migrate(load_config())


def get(key, default=None):
    overrides = _execution_overrides.get()
    if overrides is not None and key in overrides:
        return overrides[key]
    return CONFIG.get(key, DEFAULT_CONFIG.get(key, default))


@contextmanager
def execution_settings(settings):
    """Freeze settings for one job without mutating process-wide defaults."""
    token = _execution_overrides.set(dict(settings or {}))
    try:
        yield
    finally:
        _execution_overrides.reset(token)


SECRET_KEYS = {"ncbi_api_key", "semantic_scholar_key"}
PUBLIC_KEYS = set(DEFAULT_CONFIG)


def public(cfg=None):
    out = dict(CONFIG if cfg is None else cfg)
    for key in SECRET_KEYS:
        if key in out:
            out[key] = ""
    return out


def update(patch):
    unknown = set(patch) - PUBLIC_KEYS - {"active_project"}
    if unknown:
        raise ValueError("Unknown setting(s): " + ", ".join(sorted(unknown)))
    with _lock:
        clean = dict(patch)
        for key in SECRET_KEYS:
            if clean.get(key) == "":
                clean.pop(key)
        CONFIG.update(clean)
        save_config(CONFIG)
    return CONFIG

# Every registry entry declares which optional deps it needs; the UI greys
# out anything unavailable and gives the exact pip line rather than letting
# it fail at run time with an ImportError in a job log.
OPTIONAL_DEPS = {
    "numpy":        ("numpy", "Arrays and numerics", True),
    "pandas":       ("pandas", "Data frames and import/export", True),
    "scipy":        ("scipy", "Core statistical tests", True),
    "matplotlib":   ("matplotlib", "Figure rendering", True),
    "pyarrow":      ("pyarrow", "Typed, immutable Parquet dataset versions", True),
    "statsmodels":  ("statsmodels", "Regression, GLM, GEE, mixed models, multiplicity", False),
    "pingouin":     ("pingouin", "ANOVA family, effect sizes, ICC, sphericity", False),
    "lifelines":    ("lifelines", "Kaplan-Meier, Cox, competing risks", False),
    "sklearn":      ("scikit-learn", "ROC, calibration, penalised regression, clustering", False),
    "seaborn":      ("seaborn", "Distribution plot styles", False),
    "requests":     ("requests", "Literature and registry APIs", False),
    "docx":         ("python-docx", "Word export of tables and methods text", False),
    "openpyxl":     ("openpyxl", "Excel import/export", False),
    "pyreadstat":   ("pyreadstat", "SPSS .sav and Stata .dta import", False),
    "rapidfuzz":    ("rapidfuzz", "Fuzzy title matching for deduplication", False),
    "umap":         ("umap-learn", "UMAP embedding", False),
}

_dep_cache = {}


def have(mod):
    if mod not in _dep_cache:
        try:
            importlib.import_module(mod)
            _dep_cache[mod] = True
        except Exception:
            _dep_cache[mod] = False
    return _dep_cache[mod]


def dependency_report():
    out = []
    for mod, (pipname, why, required) in OPTIONAL_DEPS.items():
        ok = have(mod)
        ver = ""
        if ok:
            try:
                import importlib.metadata as im
                ver = im.version(pipname)
            except Exception:
                ver = "?"
        out.append({
            "module": mod, "pip": pipname, "why": why,
            "required": required, "ok": ok, "version": ver,
            "install": f"pip install {pipname}",
        })
    return out


def missing_deps(deps):
    return [d for d in (deps or []) if not have(d)]
