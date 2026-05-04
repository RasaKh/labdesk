"""Paths and persisted configuration.

Mirrors TubeForge's config module: the dependency report gates which test
registry entries are runnable.
"""

import json
import os
import tempfile
import threading

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
