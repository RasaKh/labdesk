"""
Spec compilation and execution.

The browser posts {test, dataset, roles, params}. Nothing else. This module
resolves the roles against the dataset, runs the declared assumption checks,
applies the gate policy, dispatches to a runner, computes effect sizes,
formats the numbers, emits equivalent Python and R, and writes one row to
the provenance ledger.

A runner never sees a request object and never formats anything for display.
It takes (df, roles, params, ctl) and returns a plain dict.
"""
import math

import numpy as np
import pandas as pd

from .config import get

def fmt_p(p, style=None):
    if p is None or (isinstance(p, float) and math.isnan(p)):
        return "NA"
    style = style or get("stats_report_style", "apa")
    floor = get("p_min_display", 0.001)
    if p < floor:
        s = f"< {floor:g}".replace("0.", ".") if style == "apa" else f"< {floor:g}"
        return "p " + s
    d = get("p_decimals", 4)
    txt = f"{p:.{d}f}".rstrip("0").rstrip(".")
    if style == "apa" and txt.startswith("0."):
        txt = txt[1:]
    return "p = " + txt


def fmt_n(x, d=None):
    if x is None:
        return "NA"
    if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
        return "NA" if math.isnan(x) else ("∞" if x > 0 else "-∞")
    d = get("decimals", 3) if d is None else d
    return f"{x:.{d}f}"


def stars(p, thresholds=None, ns=None):
    if p is None or (isinstance(p, float) and math.isnan(p)):
        return ""
    for cutoff, mark in (thresholds or get("star_thresholds")):
        if p < cutoff:
            return mark
    return ns if ns is not None else get("ns_label", "ns")


def ci_str(lo, hi, level=None):
    level = level or get("ci_level", 0.95)
    return f"{int(level*100)}% CI [{fmt_n(lo)}, {fmt_n(hi)}]"
def cohen_d(a, b, paired=False, pooled=True):
    a = pd.Series(a).dropna().astype(float)
    b = pd.Series(b).dropna().astype(float)
    if paired:
        d = (pd.Series(a).reset_index(drop=True) - pd.Series(b).reset_index(drop=True)).dropna()
        return float(d.mean() / d.std(ddof=1)) if d.std(ddof=1) else float("nan")
    n1, n2 = len(a), len(b)
    s1, s2 = a.std(ddof=1), b.std(ddof=1)
    if pooled:
        sp = math.sqrt(((n1 - 1) * s1**2 + (n2 - 1) * s2**2) / max(1, n1 + n2 - 2))
    else:
        sp = math.sqrt((s1**2 + s2**2) / 2)
    return float((a.mean() - b.mean()) / sp) if sp else float("nan")


def hedges_g(a, b, paired=False):
    d = cohen_d(a, b, paired=paired)
    if paired:
        n = min(len(pd.Series(a).dropna()), len(pd.Series(b).dropna()))
        df = n - 1
    else:
        n = len(pd.Series(a).dropna()) + len(pd.Series(b).dropna())
        df = n - 2
    J = 1 - 3 / (4 * df - 1) if df > 1 else 1.0
    return float(d * J)


def d_ci(d, n1, n2, level=None):
    """Approximate noncentral interval via the standard error of d."""
    level = level or get("ci_level", 0.95)
    from scipy import stats
    se = math.sqrt((n1 + n2) / (n1 * n2) + d**2 / (2 * (n1 + n2)))
    z = stats.norm.ppf(1 - (1 - level) / 2)
    return d - z * se, d + z * se


def rank_biserial(a, b):
    a = pd.Series(a).dropna().astype(float).values
    b = pd.Series(b).dropna().astype(float).values
    if not len(a) or not len(b):
        return float("nan")
    gt = sum((x > y) for x in a for y in b) if len(a) * len(b) <= 4_000_000 else None
    if gt is None:
        from scipy import stats
        u = stats.mannwhitneyu(a, b, alternative="two-sided").statistic
        return float(2 * u / (len(a) * len(b)) - 1)
    eq = sum((x == y) for x in a for y in b)
    return float((gt + 0.5 * eq) * 2 / (len(a) * len(b)) - 1)


def cles(a, b):
    """Common language effect size: P(a random value from a exceeds one from b)."""
    a = pd.Series(a).dropna().astype(float).values
    b = pd.Series(b).dropna().astype(float).values
    if not len(a) or not len(b):
        return float("nan")
    if len(a) * len(b) > 4_000_000:
        m = a.mean() - b.mean()
        s = math.sqrt(a.var(ddof=1) + b.var(ddof=1))
        from scipy import stats
        return float(stats.norm.cdf(m / s)) if s else float("nan")
    return float(np.mean([(x > y) + 0.5 * (x == y) for x in a for y in b]))


def hodges_lehmann(a, b=None):
    a = np.asarray(pd.Series(a).dropna().astype(float))
    if b is None:
        walsh = [(a[i] + a[j]) / 2 for i in range(len(a)) for j in range(i, len(a))]
        return float(np.median(walsh))
    b = np.asarray(pd.Series(b).dropna().astype(float))
    if len(a) * len(b) > 4_000_000:
        return float(np.median(a) - np.median(b))
    return float(np.median([x - y for x in a for y in b]))


def eta_squared(ss_between, ss_total):
    return float(ss_between / ss_total) if ss_total else float("nan")


def omega_squared(ss_between, ss_within, df_between, ms_within, n):
    num = ss_between - df_between * ms_within
    den = ss_between + ss_within + ms_within
    return float(num / den) if den else float("nan")


def epsilon_squared(H, n):
    return float((H - 1) / (n - 1)) if n > 1 else float("nan")


def cramers_v(chi2, n, r, c):
    k = min(r - 1, c - 1)
    return float(math.sqrt(chi2 / (n * k))) if n and k else float("nan")


# ─────────────────────────────────────────────────────────────────────────
#  Multiplicity
# ─────────────────────────────────────────────────────────────────────────

def adjust_p(pvals, method="holm"):
    p = np.asarray([np.nan if v is None else float(v) for v in pvals], float)
    ok = ~np.isnan(p)
    out = np.full(p.shape, np.nan)
    x = p[ok]
    n = len(x)
    if n == 0:
        return out.tolist()
    order = np.argsort(x)
    ranked = x[order]
    if method in (None, "none"):
        adj = ranked
    elif method == "bonferroni":
        adj = np.minimum(1, ranked * n)
    elif method == "sidak":
        adj = 1 - (1 - ranked) ** n
    elif method == "holm":
        adj = np.maximum.accumulate(np.minimum(1, ranked * (n - np.arange(n))))
    elif method == "fdr_bh":
        adj = np.minimum.accumulate(
            (ranked * n / (np.arange(n) + 1))[::-1])[::-1]
        adj = np.minimum(1, adj)
    elif method == "fdr_by":
        c = np.sum(1.0 / (np.arange(n) + 1))
        adj = np.minimum.accumulate(
            (ranked * n * c / (np.arange(n) + 1))[::-1])[::-1]
        adj = np.minimum(1, adj)
    elif method == "storey":
        lam = 0.5
        pi0 = min(1.0, np.mean(x > lam) / (1 - lam))
        adj = np.minimum.accumulate(
            (ranked * n * pi0 / (np.arange(n) + 1))[::-1])[::-1]
        adj = np.minimum(1, adj)
    else:
        adj = ranked
    back = np.empty(n)
    back[order] = adj
    out[ok] = back
    return out.tolist()
