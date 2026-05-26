"""Deterministic analysis compatibility guide.

This module deliberately does *not* choose a statistical method for the user.
It connects two declarative sources LabDesk already trusts:

* the reviewed variable dictionary says what each dataset column is; and
* the statistics registry says what variable roles each method accepts.

The result is constraint matching: which READY methods can be populated from
this dataset, and which role assignments are structurally compatible with the
variables the researcher has selected. Scientific intent, estimands, causal
claims and final method choice remain human decisions.
"""

from __future__ import annotations

from .schema import _KIND_COMPAT
from .stats_registry import READY, TESTS


GOALS = {
    "describe": {
        "label": "Describe / check data",
        "blurb": "Summaries, distributions, missingness and basic assumption checks.",
        "groups": {"Descriptives", "Assumption checks"},
        "exclude": {"power_achieved"},
        "primary_label": "Variable to focus on",
        "secondary_label": "Optional grouping variable",
        "primary_roles": ("vars", "dv", "var", "row"),
        "secondary_roles": ("group", "col"),
    },
    "compare": {
        "label": "Compare groups",
        "blurb": "Independent-group comparisons for continuous or categorical outcomes.",
        "groups": {"Two groups", "Three or more groups", "Categorical and proportions",
                   "Bayesian and equivalence"},
        # Paired/repeated procedures have their own intent below. One-sample
        # procedures do not compare dataset groups.
        "exclude": {"ttest_paired", "wilcoxon", "ttest_1samp", "wilcoxon_1samp",
                    "mcnemar", "cochran_q", "friedman", "binomial", "goodness_fit"},
        "primary_label": "Outcome",
        "secondary_label": "Group / exposure",
        "primary_roles": ("dv", "outcome", "row"),
        "secondary_roles": ("group", "ordered", "col"),
    },
    "paired": {
        "label": "Paired / repeated measurements",
        "blurb": "Measurements linked within the same subjects or units.",
        "include": {"ttest_paired", "wilcoxon", "mcnemar", "cochran_q", "friedman",
                    "bland_altman"},
        "primary_label": "First measurement / outcome",
        "secondary_label": "Second measurement / within factor",
        "primary_roles": ("a", "dv", "vars"),
        "secondary_roles": ("b", "within", "vars"),
    },
    "association": {
        "label": "Association / relationship",
        "blurb": "Associations between variables without declaring one to be an outcome model.",
        "include": {"correlation", "crosstab", "chi2", "fisher", "armitage"},
        "primary_label": "First variable",
        "secondary_label": "Second variable",
        "primary_roles": ("vars", "row", "outcome"),
        "secondary_roles": ("vars", "col", "ordered"),
    },
    "agreement": {
        "label": "Agreement / reliability",
        "blurb": "Agreement between methods or raters and reliability of repeated measures/items.",
        "include": {"icc", "bland_altman", "kappa", "cronbach"},
        "primary_label": "First measure / item",
        "secondary_label": "Second measure / rater",
        "primary_roles": ("a", "value", "raters", "items"),
        "secondary_roles": ("b", "rater", "raters", "items"),
    },
    "model": {
        "label": "Model an outcome",
        "blurb": "Regression models where one variable is explicitly the outcome.",
        "groups": {"Regression"},
        "primary_label": "Outcome",
        "secondary_label": "Optional predictor to prefill",
        "primary_roles": ("dv",),
        "secondary_roles": ("predictors",),
    },
    "survival": {
        "label": "Time-to-event",
        "blurb": "Survival/time-to-event analyses using a time variable and event indicator.",
        "groups": {"Survival"},
        "primary_label": "Follow-up / survival time",
        "secondary_label": "Event indicator",
        "primary_roles": ("time",),
        "secondary_roles": ("event",),
    },
    "diagnostic": {
        "label": "Diagnostic / prediction performance",
        "blurb": "Accuracy of a score or binary test against a binary reference outcome.",
        "groups": {"Diagnostic accuracy and prediction"},
        "primary_label": "Reference / truth",
        "secondary_label": "Score / test",
        "primary_roles": ("truth",),
        "secondary_roles": ("score", "test"),
    },
    "meta": {
        "label": "Meta-analysis dataset",
        "blurb": "Study-level effect estimates and their uncertainty.",
        "groups": {"Meta-analysis"},
        "primary_label": "Effect estimate",
        "secondary_label": "Standard error",
        "primary_roles": ("effect",),
        "secondary_roles": ("se",),
    },
    "bench": {
        "label": "Bench / omics",
        "blurb": "Structured assay and multivariate workflows whose required columns are declared by each method.",
        "groups": {"Bench and omics"},
        "primary_label": "Variable to focus on",
        "secondary_label": "Second variable",
        "primary_roles": ("ct", "od", "vars"),
        "secondary_roles": ("gene", "conc", "colour"),
    },
}


def public_goals():
    """Browser-safe description of the deterministic intents."""
    return [{"id": gid, "label": g["label"], "blurb": g["blurb"],
             "primary_label": g["primary_label"],
             "secondary_label": g["secondary_label"]}
            for gid, g in GOALS.items()]

def _n_levels(meta):
    if meta.get("n_unique") is not None:
        try:
            return int(meta["n_unique"])
        except (TypeError, ValueError):
            pass
    levels = meta.get("levels")
    return len(levels) if isinstance(levels, list) else None

def role_accepts(role, column, dictionary):
    """Whether one reviewed dictionary column satisfies one declared role."""
    meta = (dictionary or {}).get(column) or {}
    actual = meta.get("kind")
    allowed = _KIND_COMPAT.get(role.get("kind", "any"), {role.get("kind", "any")})
    if actual not in allowed:
        return False
    req = role.get("levels")
    if req is not None:
        n = _n_levels(meta)
        if n is None:
            return False
        if isinstance(req, (list, tuple)):
            lo, hi = req[0], req[-1]
            if n < lo or n > hi:
                return False
        elif n != req:
            return False
    return True

def role_options(entry, dictionary):
    cols = list((dictionary or {}).keys())
    return {r["id"]: [c for c in cols if role_accepts(r, c, dictionary)]
            for r in entry.get("roles", [])}

def _has_required_assignment(entry, options):
    """True if required role slots can be filled with distinct variables.

    The backtracking is intentionally tiny: registry role minima are small and
    datasets rarely have enough role types to make this expensive. It protects
    against a misleading match such as one binary column being the only option
    for two distinct required roles.
    """
    slots = []
    for role in entry.get("roles", []):
        need = int(role.get("min", 0) or 0)
        if role.get("optional"):
            need = 0
        opts = options.get(role["id"], [])
        if len(opts) < need:
            return False
        slots.extend((role["id"], opts) for _ in range(need))
    slots.sort(key=lambda item: len(item[1]))

    def place(i, used):
        if i == len(slots):
            return True
        _rid, opts = slots[i]
        for col in opts:
            if col not in used and place(i + 1, used | {col}):
                return True
        return False

    return place(0, set())

def _entries_for_goal(goal_id):
    goal = GOALS.get(goal_id)
    if not goal:
        raise ValueError(f"Unknown analysis goal {goal_id!r}.")
    include = goal.get("include")
    groups = goal.get("groups")
    exclude = goal.get("exclude", set())
    out = []
    for entry in TESTS:
        if entry.get("status") != READY or entry["id"] in exclude:
            continue
        if include is not None and entry["id"] not in include:
            continue
        if groups is not None and entry.get("group") not in groups:
            continue
        # The guide is about analyses driven by dataset variables. Registry
        # utilities with no roles remain available in the manual library.
        if not entry.get("roles"):
            continue
        out.append(entry)
    return out

def _anchor_role(entry, preferred_ids, anchor, dictionary, already=None):
    if not anchor:
        return None
    already = already or {}
    by_id = {r["id"]: r for r in entry.get("roles", [])}
    for rid in preferred_ids:
        role = by_id.get(rid)
        if not role or not role_accepts(role, anchor, dictionary):
            continue
        cur = list(already.get(rid, []))
        if anchor in cur:
            return rid
        if role.get("max", 1) == 1 and cur:
            continue
        return rid
    return None

def _prefill(entry, goal, dictionary, primary=None, secondary=None):
    """Map user-selected anchor variables to compatible declared roles."""
    roles = {}
    p_role = _anchor_role(entry, goal["primary_roles"], primary, dictionary, roles)
    if p_role:
        roles[p_role] = [primary]
    s_role = _anchor_role(entry, goal["secondary_roles"], secondary, dictionary, roles)
    if s_role:
        roles.setdefault(s_role, [])
        if secondary not in roles[s_role]:
            roles[s_role].append(secondary)
    return roles, bool(primary and p_role), bool(secondary and s_role)

def _prefill_can_complete(entry, options, prefill):
    """Verify there is still a distinct assignment after applying anchors."""
    used = {c for values in prefill.values() for c in values}
    slots = []
    for role in entry.get("roles", []):
        rid = role["id"]
        need = 0 if role.get("optional") else int(role.get("min", 0) or 0)
        have = len(prefill.get(rid, []))
        remaining = max(0, need - have)
        opts = [c for c in options.get(rid, []) if c not in used]
        if len(opts) < remaining:
            return False
        slots.extend((rid, opts) for _ in range(remaining))
    slots.sort(key=lambda item: len(item[1]))

    def place(i, occupied):
        if i == len(slots):
            return True
        _rid, opts = slots[i]
        for col in opts:
            if col not in occupied and place(i + 1, occupied | {col}):
                return True
        return False

    return place(0, set(used))

def compatible_methods(dictionary, goal_id="compare", primary=None, secondary=None,
                       limit=12):
    """Return structurally compatible READY methods for the current dataset.

    `primary` and `secondary` are researcher-selected anchors, not inferred
    semantics. If supplied, methods are retained only when those anchors can be
    mapped to the goal's corresponding declared roles.
    """
    if primary and primary not in dictionary:
        raise ValueError(f"Unknown variable {primary!r}.")
    if secondary and secondary not in dictionary:
        raise ValueError(f"Unknown variable {secondary!r}.")
    if primary and secondary and primary == secondary:
        raise ValueError("Choose two different variables for the two guide fields.")

    goal = GOALS.get(goal_id)
    if not goal:
        raise ValueError(f"Unknown analysis goal {goal_id!r}.")

    results = []
    for order, entry in enumerate(_entries_for_goal(goal_id)):
        opts = role_options(entry, dictionary)
        if not _has_required_assignment(entry, opts):
            continue
        prefill, p_used, s_used = _prefill(entry, goal, dictionary, primary, secondary)
        if primary and not p_used:
            continue
        if secondary and not s_used:
            continue
        if not _prefill_can_complete(entry, opts, prefill):
            continue

        # Anchored matches come first; otherwise preserve the registry's
        # deliberate pedagogical order rather than pretending to rank evidence.
        score = (2 if p_used else 0) + (2 if s_used else 0)
        results.append((score, -order, {
            "id": entry["id"], "label": entry["label"], "group": entry["group"],
            "blurb": entry.get("blurb", ""), "prefill": prefill,
            "role_options": opts,
        }))

    results.sort(key=lambda x: (-x[0], -x[1]))
    total = len(results)
    items = [x[2] for x in results[:max(1, int(limit))]]
    return {
        "goal": goal_id,
        "primary": primary,
        "secondary": secondary,
        "total": total,
        "items": items,
        "disclaimer": (
            "Compatibility is deterministic. LabDesk matches the reviewed variable "
            "dictionary to each method's declared roles; it does not infer the scientific "
            "question, estimand, causal structure, preregistration, or the method you should use."
        ),
    }
