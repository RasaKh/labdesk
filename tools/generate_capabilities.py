#!/usr/bin/env python3
"""Write the runtime capability inventory used for release review."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from labdesk import harvest, plots_registry, stats_registry
from labdesk.config import missing_deps
from labdesk.plots_run import RENDERERS
from labdesk.runners import RUNNERS


def state(entry, implementations):
    if entry.get("status") != "ready":
        return "unimplemented"
    missing = missing_deps(entry.get("deps"))
    if missing:
        return "missing_dependency"
    if entry["id"] not in implementations:
        return "verification_failed"
    return "available"


payload = {
    "schema_version": 1,
    "analysis": [{"id": e["id"], "label": e["label"],
                  "declared_status": e.get("status", "stub"),
                  "capability": state(e, RUNNERS), "dependencies": e.get("deps", [])}
                 for e in stats_registry.TESTS],
    "plots": [{"id": e["id"], "label": e["label"],
               "declared_status": e.get("status", "stub"),
               "capability": state(e, RENDERERS), "dependencies": e.get("deps", [])}
              for e in plots_registry.PLOTS],
    "sources": [{"id": e["id"], "label": e["label"],
                 "declared_status": e.get("status", "stub")}
                for e in harvest.SOURCES],
}
Path("CAPABILITIES.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
print("Wrote CAPABILITIES.json")
