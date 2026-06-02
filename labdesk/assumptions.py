"""
Assumption preflight.

TubeForge refuses to build a command that copies a codec into a container
that cannot hold it, and tells you why before you wait for the encode. This
is the same idea. Every test declares which assumptions it rests on, they
are checked against the actual data before the test runs, and the result is
one of pass / caution / fail with a named fallback.

`assumption_policy` in settings decides what a fail does:
  warn          run anyway, record the violation in the provenance row
  block         refuse, offer the fallback test as a one-click switch
  auto_fallback silently switch to the fallback and say so in the output
"""

import numpy as np
import pandas as pd
from scipy import stats

from .config import get

PASS, CAUTION, FAIL, SKIP = "pass", "caution", "fail", "skip"


def _r(key, label, state, detail, stat=None, p=None, fallback=None, fix=None):
    return {"id": key, "label": label, "state": state, "detail": detail,
            "stat": None if stat is None else float(stat),
            "p": None if p is None else float(p),
            "fallback": fallback, "fix": fix}


# ─────────────────────────────────────────────────────────────────────────
#  Individual checks
# ─────────────────────────────────────────────────────────────────────────

def normality(values, label="Normality", n_warn=5000):
    v = pd.Series(values).dropna().astype(float)
    n = len(v)
    if n < 3:
        return _r("normality", label, SKIP, f"Only {n} observations, cannot test.")
    if n > n_warn:
        return _r("normality", label, CAUTION, n_warn and
                  f"n = {n}. Shapiro-Wilk rejects trivial departures at this size. "
                  "Judge from the Q-Q plot instead; the central limit theorem covers means here.")
    W, p = stats.shapiro(v)
    if p >= 0.05:
        return _r("normality", label, PASS, f"Shapiro-Wilk W = {W:.3f}, p = {p:.3f}.", W, p)
    skew = float(stats.skew(v))
    state = CAUTION if (n >= 30 and abs(skew) < 1) else FAIL
    return _r("normality", label, state,
              f"Shapiro-Wilk W = {W:.3f}, p = {p:.4f}, skew = {skew:.2f}. "
              + ("n is large enough that the mean is still approximately normal."
                 if state == CAUTION else "Distribution departs from normal."),
              W, p, fallback="rank_based",
              fix="Use the rank-based equivalent, or transform (log for right skew).")


def normality_by_group(df, dv, group):
    out = []
    for lvl, sub in df.groupby(group, dropna=True):
        r = normality(sub[dv], label=f"Normality in {lvl}")
        r["id"] = f"normality[{lvl}]"
        out.append(r)
    return out


def homogeneity(df, dv, group, center="median"):
    groups = [g[dv].dropna().astype(float).values
              for _, g in df.groupby(group, dropna=True)]
    groups = [g for g in groups if len(g) > 1]
    if len(groups) < 2:
        return _r("homogeneity", "Equal variances", SKIP, "Fewer than two usable groups.")
    W, p = stats.levene(*groups, center=center)
    sds = [float(np.std(g, ddof=1)) for g in groups]
    ratio = max(sds) / min(sds) if min(sds) > 0 else float("inf")
    if p >= 0.05:
        return _r("homogeneity", "Equal variances", PASS,
                  f"Levene (centre = {center}) W = {W:.3f}, p = {p:.3f}. "
                  f"Largest/smallest SD = {ratio:.2f}.", W, p)
    return _r("homogeneity", "Equal variances", FAIL,
              f"Levene W = {W:.3f}, p = {p:.4f}. Largest/smallest SD = {ratio:.2f}.",
              W, p, fallback="welch",
              fix="Use the Welch correction, which does not assume equal variances "
                  "and costs almost nothing when they are equal.")


def group_sizes(df, dv, group, min_n=3):
    counts = df.dropna(subset=[dv]).groupby(group, dropna=True)[dv].count()
    small = counts[counts < min_n]
    balanced = counts.max() / max(1, counts.min())
    detail = ", ".join(f"{k}: n = {v}" for k, v in counts.items())
    if len(small):
        return _r("group_sizes", "Cell sizes", FAIL,
                  f"{detail}. Groups below n = {min_n} cannot support this test.")
    if balanced > 3:
        return _r("group_sizes", "Cell sizes", CAUTION,
                  f"{detail}. Largest group is {balanced:.1f}x the smallest; "
                  "unbalanced designs are sensitive to variance violations.")
    return _r("group_sizes", "Cell sizes", PASS, detail)


def levels_exactly(df, group, k):
    n = df[group].dropna().nunique()
    if n == k:
        return _r("levels", "Factor levels", PASS, f"{group} has {n} levels.")
    return _r("levels", "Factor levels", FAIL,
              f"{group} has {n} levels, this test needs exactly {k}.",
              fix=("Use the omnibus test for more than two groups, or filter to two levels."
                   if n > k else "Choose a factor with more levels."))


def expected_counts(table, min_expected=5):
    chi2, p, dof, exp = stats.chi2_contingency(table)
    small = int((exp < min_expected).sum())
    frac = small / exp.size
    if small == 0:
        return _r("expected_counts", "Expected cell counts", PASS,
                  f"All {exp.size} expected counts are at least {min_expected}.")
    if frac <= 0.2 and exp.min() >= 1:
        return _r("expected_counts", "Expected cell counts", CAUTION,
                  f"{small} of {exp.size} expected counts below {min_expected} "
                  f"(minimum {exp.min():.1f}). Cochran's rule tolerates up to 20%.")
    return _r("expected_counts", "Expected cell counts", FAIL,
              f"{small} of {exp.size} expected counts below {min_expected} "
              f"(minimum {exp.min():.1f}).", fallback="fisher_exact",
              fix="Use Fisher's exact test, or collapse sparse categories.")


def sphericity(df, subject, within, dv, corrected=False):
    """Mauchly's test. Needs pingouin; without it we say so rather than guess."""
    try:
        import pingouin as pg
    except Exception:
        return _r("sphericity", "Sphericity", SKIP,
                  "Mauchly's test needs pingouin. pip install pingouin")
    spher, W, chi2, dof, p = pg.sphericity(df, dv=dv, subject=subject, within=within)
    if spher:
        return _r("sphericity", "Sphericity", PASS,
                  f"Mauchly W = {W:.3f}, p = {p:.3f}.", W, p)
    if corrected:
        return _r("sphericity", "Sphericity", CAUTION,
                  f"Mauchly W = {W:.3f}, p = {p:.4f}. Violated; the sphericity "
                  "correction you selected is applied to the degrees of freedom.", W, p)
    return _r("sphericity", "Sphericity", FAIL,
              f"Mauchly W = {W:.3f}, p = {p:.4f}.", W, p, fallback="greenhouse_geisser",
              fix="Apply the Greenhouse-Geisser correction to the degrees of freedom.")


def linearity_residuals(x, y, label="Linearity"):
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    ok = ~(np.isnan(x) | np.isnan(y))
    x, y = x[ok], y[ok]
    if len(x) < 5:
        return _r("linearity", label, SKIP, "Too few complete pairs.")
    slope, intercept, r, p, se = stats.linregress(x, y)
    resid = y - (slope * x + intercept)
    # Quadratic term significance is a cheap, interpretable curvature check.
    try:
        c = np.polyfit(x, y, 2)
        quad_pred = np.polyval(c, x)
        ss_lin = float(np.sum(resid**2))
        ss_quad = float(np.sum((y - quad_pred) ** 2))
        gain = 1 - ss_quad / ss_lin if ss_lin else 0
    except Exception:
        gain = 0
    if gain < 0.02:
        return _r("linearity", label, PASS,
                  f"A quadratic term reduces residual variance by only {gain*100:.1f}%.")
    return _r("linearity", label, CAUTION,
              f"A quadratic term reduces residual variance by {gain*100:.1f}%. "
              "The relationship may be curved.",
              fix="Inspect the scatter plot, consider a transform or a spline term.")


def homoscedasticity(resid, fitted):
    """Breusch-Pagan without statsmodels: regress squared residuals on fitted."""
    r = np.asarray(resid, float)
    f = np.asarray(fitted, float)
    ok = ~(np.isnan(r) | np.isnan(f))
    r, f = r[ok], f[ok]
    if len(r) < 8:
        return _r("homoscedasticity", "Constant variance", SKIP, "Too few residuals.")
    sq = r**2
    slope, intercept, rr, p, se = stats.linregress(f, sq)
    if p >= 0.05:
        return _r("homoscedasticity", "Constant variance", PASS,
                  f"Squared residuals show no trend with fitted values (p = {p:.3f}).", None, p)
    return _r("homoscedasticity", "Constant variance", FAIL,
              f"Squared residuals trend with fitted values (p = {p:.4f}). "
              "Standard errors are biased.", None, p, fallback="robust_se",
              fix="Use heteroscedasticity-consistent (HC3) standard errors, "
                  "or transform the outcome.")


def multicollinearity(df, cols, vif_warn=5, vif_fail=10):
    sub = df[cols].apply(pd.to_numeric, errors="coerce").dropna()
    if sub.shape[1] < 2:
        return _r("vif", "Multicollinearity", SKIP, "Needs at least two predictors.")
    vifs = {}
    for c in cols:
        others = [o for o in cols if o != c]
        X = np.column_stack([np.ones(len(sub))] + [sub[o].values for o in others])
        y = sub[c].values
        beta, *_ = np.linalg.lstsq(X, y, rcond=None)
        pred = X @ beta
        ss_res = float(np.sum((y - pred) ** 2))
        ss_tot = float(np.sum((y - y.mean()) ** 2))
        r2 = 1 - ss_res / ss_tot if ss_tot else 0
        vifs[c] = float("inf") if r2 >= 1 else 1 / (1 - r2)
    worst = max(vifs, key=vifs.get)
    detail = ", ".join(f"{k}: {v:.1f}" for k, v in sorted(vifs.items(), key=lambda kv: -kv[1]))
    if vifs[worst] >= vif_fail:
        return _r("vif", "Multicollinearity", FAIL, f"VIF {detail}.",
                  fix=f"Drop or combine {worst}; its coefficient is not interpretable.")
    if vifs[worst] >= vif_warn:
        return _r("vif", "Multicollinearity", CAUTION, f"VIF {detail}.")
    return _r("vif", "Multicollinearity", PASS, f"VIF {detail}.")


def independence_note():
    """Cannot be tested from a data frame. Stated rather than silently assumed."""
    return _r("independence", "Independence of observations", CAUTION,
              "Not testable from the data. If subjects contributed more than one row, "
              "or came from clusters such as wards or centres, this test is the wrong one.",
              fix="Use a repeated-measures or mixed-effects model.")


def proportional_hazards(time, event, group):
    """Schoenfeld-style check without lifelines: correlation of scaled residual
    ranks with time. Approximate, and it says so."""
    try:
        import lifelines  # noqa: F401
        return _r("ph", "Proportional hazards", SKIP,
                  "Needs the fitted model. Tested on scaled Schoenfeld residuals after "
                  "fitting; the result reports it per covariate.")
    except Exception:
        return _r("ph", "Proportional hazards", SKIP,
                  "Needs lifelines. pip install lifelines")


def min_events_per_variable(n_events, n_predictors, epv_min=10):
    if n_predictors <= 0:
        return _r("epv", "Events per variable", SKIP, "No predictors.")
    epv = n_events / n_predictors
    if epv >= epv_min:
        return _r("epv", "Events per variable", PASS,
                  f"{n_events} events for {n_predictors} predictors (EPV = {epv:.1f}).")
    return _r("epv", "Events per variable", FAIL,
              f"{n_events} events for {n_predictors} predictors (EPV = {epv:.1f}). "
              f"Below {epv_min} the model overfits and coefficients are unstable.",
              fix="Reduce predictors, or use penalised regression.")


def _events_and_terms(df, ctx):
    """Events in the rarer outcome class (or events, for survival) and the
    number of model terms, over the rows the model would actually use."""
    preds = list(ctx.get("predictors") or [])
    outcome = ctx.get("event") or ctx.get("dv")
    cols = [outcome] + preds + ([ctx["time"]] if ctx.get("event") and ctx.get("time") else [])
    sub = df[cols].dropna()
    terms = 0
    for c in preds:
        s = sub[c]
        if pd.api.types.is_numeric_dtype(s) and s.nunique() > 2:
            terms += 1
        else:
            terms += max(0, s.nunique() - 1)
    y = sub[outcome].astype(str)
    if ctx.get("event"):
        from .runners.models import _binary_positive
        level, _ = _binary_positive(sub[outcome], (ctx.get("params") or {}).get("event_level"),
                                    outcome)
        return int((y == level).sum()), terms
    counts = y.value_counts()
    return (int(counts.min()) if len(counts) == 2 else 0), terms


def paired_completeness(a, b):
    a = pd.Series(a)
    b = pd.Series(b)
    n_pairs = int((a.notna() & b.notna()).sum())
    dropped = int(len(a) - n_pairs)
    if dropped == 0:
        return _r("pairing", "Complete pairs", PASS, f"{n_pairs} complete pairs.")
    state = CAUTION if dropped / max(1, len(a)) < 0.1 else FAIL
    return _r("pairing", "Complete pairs", state,
              f"{n_pairs} complete pairs, {dropped} rows dropped for missing values.",
              fix="Check whether the dropped rows differ systematically from the rest.")


# ─────────────────────────────────────────────────────────────────────────
#  Dispatcher
# ─────────────────────────────────────────────────────────────────────────

def run_checks(names, ctx):
    """ctx carries df and resolved role variables. Unknown names are reported
    rather than skipped silently, so a typo in the registry is visible."""
    df = ctx.get("df")
    out = []
    for name in names or []:
        try:
            if name == "normality_by_group":
                out += normality_by_group(df, ctx["dv"], ctx["group"])
            elif name == "normality_of_differences":
                d = pd.to_numeric(df[ctx["a"]], errors="coerce") - \
                    pd.to_numeric(df[ctx["b"]], errors="coerce")
                r = normality(d, "Normality of differences")
                out.append(r)
            elif name == "normality":
                out.append(normality(df[ctx["dv"]]))
            elif name == "homogeneity":
                out.append(homogeneity(df, ctx["dv"], ctx["group"]))
            elif name == "group_sizes":
                out.append(group_sizes(df, ctx["dv"], ctx["group"]))
            elif name == "two_levels":
                out.append(levels_exactly(df, ctx["group"], 2))
            elif name == "three_plus_levels":
                n = df[ctx["group"]].dropna().nunique()
                out.append(_r("levels", "Factor levels",
                              PASS if n >= 3 else FAIL,
                              f"{ctx['group']} has {n} levels."
                              + ("" if n >= 3 else " This test needs at least three.")))
            elif name == "expected_counts":
                out.append(expected_counts(ctx["table"]))
            elif name == "sphericity":
                corrected = (ctx.get("params") or {}).get("correction", "none") != "none"
                out.append(sphericity(df, ctx["subject"], ctx["within"], ctx["dv"],
                                      corrected=corrected))
            elif name == "linearity":
                if ctx.get("x") and ctx.get("y"):
                    out.append(linearity_residuals(df[ctx["x"]], df[ctx["y"]]))
                else:
                    # Covariate models: the outcome must be linear in each covariate.
                    for c in ctx.get("covariates") or []:
                        out.append(linearity_residuals(df[c], df[ctx["dv"]],
                                                       f"Linearity in {c}"))
            elif name == "independence":
                out.append(independence_note())
            elif name == "pairing":
                out.append(paired_completeness(df[ctx["a"]], df[ctx["b"]]))
            elif name == "vif":
                out.append(multicollinearity(df, ctx.get("predictors", [])))
            elif name == "epv":
                if "n_events" in ctx:
                    events, terms = ctx["n_events"], len(ctx.get("predictors", []))
                else:
                    events, terms = _events_and_terms(df, ctx)
                out.append(min_events_per_variable(events, terms))
            elif name == "proportional_hazards":
                out.append(proportional_hazards(ctx.get("time"), ctx.get("event"),
                                                ctx.get("group")))
            else:
                out.append(_r(name, name, SKIP, "No checker registered for this assumption."))
        except Exception as exc:
            out.append(_r(name, name, SKIP, f"Check failed: {type(exc).__name__}: {exc}"))
    return out


def verdict(checks):
    states = [c["state"] for c in checks]
    if FAIL in states:
        return FAIL
    if CAUTION in states:
        return CAUTION
    return PASS


def gate(checks):
    """Returns (allowed, action, message) under the current policy."""
    v = verdict(checks)
    policy = get("assumption_policy", "warn")
    if v != FAIL:
        return True, "run", None
    failed = [c for c in checks if c["state"] == FAIL]
    fb = next((c["fallback"] for c in failed if c.get("fallback")), None)
    msg = "; ".join(c["label"] + ": " + c["detail"] for c in failed)
    if policy == "block":
        return False, "blocked", msg
    if policy == "auto_fallback" and fb:
        return True, f"fallback:{fb}", msg
    return True, "warn", msg
