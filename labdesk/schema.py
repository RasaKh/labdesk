"""
Declarative primitives.

Everything the UI can do is described by data in this shape, and the server
compiles a submitted spec against the same definitions.
"""


def P(pid, label, ptype="text", default=None, choices=None, min=None, max=None,
      step=None, unit=None, help=None, adv=False, depends=None, placeholder=None,
      group=None):
    """One control.

    ptype: text | number | int | bool | select | multiselect | column |
           columns | textarea | range | color | file
    """
    d = {"id": pid, "label": label, "type": ptype, "adv": bool(adv)}
    if default is not None:
        d["default"] = default
    if choices is not None:
        d["choices"] = [c if isinstance(c, (list, tuple)) else (c, str(c)) for c in choices]
    for k, v in (("min", min), ("max", max), ("step", step), ("unit", unit),
                 ("help", help), ("depends", depends), ("placeholder", placeholder),
                 ("group", group)):
        if v is not None:
            d[k] = v
    return d


def R(rid, label, kind="continuous", min_vars=1, max_vars=1, levels=None,
      help=None, optional=False):
    """One variable role slot.

    kind: continuous | categorical | binary | ordinal | time | event | id | any
    """
    d = {"id": rid, "label": label, "kind": kind,
         "min": min_vars, "max": max_vars, "optional": bool(optional)}
    if levels is not None:
        d["levels"] = levels
    if help:
        d["help"] = help
    return d


def group_registry(entries):
    """Order-preserving grouping for the left rail."""
    out = []
    seen = {}
    for e in entries:
        g = e.get("group", "Other")
        if g not in seen:
            seen[g] = {"group": g, "items": []}
            out.append(seen[g])
        seen[g]["items"].append({
            "id": e["id"], "label": e["label"],
            "status": e.get("status", "stub"),
            "deps": e.get("deps", []),
        })
    return out


def index(entries):
    return {e["id"]: e for e in entries}


def defaults_for(entry):
    return {p["id"]: p.get("default") for p in entry.get("params", [])}
