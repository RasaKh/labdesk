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
