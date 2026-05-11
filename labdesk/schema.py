"""
Declarative primitives.

The client sends a spec, never a command, and the option surface exists in
exactly one place. This is the TubeForge contract carried over intact.
"""


def P(pid, label, ptype="text", default=None, choices=None, min=None, max=None,
      step=None, unit=None, help=None, adv=False, depends=None, placeholder=None,
      group=None):
    """One control."""
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
    """One variable role slot."""
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


_KIND_COMPAT = {
    "continuous": {"continuous"},
    "categorical": {"categorical", "binary", "ordinal"},
    "binary": {"binary"},
    "ordinal": {"ordinal"},
    "time": {"time"},
    "event": {"event", "binary"},
    "id": {"id", "categorical", "text"},
    "any": {"continuous", "categorical", "binary", "ordinal", "time",
            "event", "id", "text", "unknown", "constant"},
}


def validate_spec(entry, spec, df=None, dictionary=None):
    """Check roles and params before anything touches the data.

    Returns (errors, cleaned_params). Errors are user-facing sentences that
    say what is wrong and what to do, never a traceback.
    """
    errors = []
    roles = spec.get("roles", {}) or {}
    used = {}
    for r in entry.get("roles", []):
        got = roles.get(r["id"]) or []
        if isinstance(got, str):
            got = [got]
        if len(got) < r["min"] and not r.get("optional"):
            errors.append(f"{r['label']}: choose at least {r['min']} variable.")
        if r["max"] and len(got) > r["max"]:
            errors.append(f"{r['label']}: at most {r['max']} variable.")
        for col in got:
            if df is not None and col not in df.columns:
                errors.append(f"{r['label']}: {col!r} is not a column in this dataset.")
                continue
            prior = used.get(col)
            if prior and prior != r["id"]:
                errors.append(f"{col!r} is assigned to both {prior!r} and {r['id']!r}; "
                              "choose distinct variables for distinct roles.")
            used[col] = r["id"]
            if dictionary and col in dictionary:
                actual = dictionary[col].get("kind")
                allowed = _KIND_COMPAT.get(r.get("kind", "any"), {r.get("kind")})
                if actual and actual not in allowed:
                    errors.append(
                        f"{r['label']}: {col!r} is marked {actual!r} in the variable "
                        f"dictionary, but this role requires {r.get('kind', 'any')!r}."
                    )
            if df is not None and r.get("levels") is not None and col in df.columns:
                n_levels = int(df[col].nunique(dropna=True))
                req = r["levels"]
                if isinstance(req, (list, tuple)):
                    lo, hi = req[0], req[-1]
                    if n_levels < lo or n_levels > hi:
                        errors.append(f"{r['label']}: {col!r} has {n_levels} levels; "
                                      f"expected between {lo} and {hi}.")
                elif n_levels != req:
                    errors.append(f"{r['label']}: {col!r} has {n_levels} levels; "
                                  f"expected exactly {req}.")

    clean = {}
    for p in entry.get("params", []):
        v = (spec.get("params") or {}).get(p["id"], p.get("default"))
        t = p["type"]
        try:
            if t == "int" and v is not None and v != "":
                v = int(v)
            elif t in ("number", "range") and v is not None and v != "":
                v = float(v)
            elif t == "bool":
                v = bool(v) if not isinstance(v, str) else v.lower() in ("1", "true", "on", "yes")
        except (TypeError, ValueError):
            errors.append(f"{p['label']}: expected a number, got {v!r}.")
            continue
        if t == "column" and v not in (None, "") and df is not None:
            if v not in df.columns:
                errors.append(f"{p['label']}: {v!r} is not a column in this dataset.")
        elif t == "columns" and v not in (None, "") and df is not None:
            chosen = v if isinstance(v, list) else [v]
            missing = [c for c in chosen if c not in df.columns]
            if missing:
                errors.append(f"{p['label']}: unknown column(s): {', '.join(map(str, missing))}.")
        if p.get("choices") and v not in (None, ""):
            allowed = [c[0] for c in p["choices"]]
            if t == "multiselect":
                bad = [x for x in (v if isinstance(v, list) else [v]) if x not in allowed]
                if bad:
                    errors.append(f"{p['label']}: {', '.join(map(str, bad))} "
                                  "is not among the allowed values.")
            elif v not in allowed:
                errors.append(f"{p['label']}: {v!r} is not one of the allowed values.")
        if p.get("min") is not None and isinstance(v, (int, float)) and v < p["min"]:
            errors.append(f"{p['label']}: minimum is {p['min']}.")
        if p.get("max") is not None and isinstance(v, (int, float)) and v > p["max"]:
            errors.append(f"{p['label']}: maximum is {p['max']}.")
        clean[p["id"]] = v
    return errors, clean
